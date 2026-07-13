from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import sys
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


PROJECT_DIR = Path(__file__).resolve().parent
SYNC_SCRIPT_PATH = PROJECT_DIR / "11_sync_webapp_to_planner.py"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_ALLOWED_ORIGINS = (
    "null,"
    "http://localhost,http://localhost:*,"
    "http://127.0.0.1,http://127.0.0.1:*,"
    "https://script.google.com,"
    "https://*.googleusercontent.com,"
    "https://tracuuphaply.vercel.app"
)

sync_lock = threading.Lock()


def load_server_env() -> None:
    if load_dotenv is not None:
        load_dotenv(PROJECT_DIR / ".env")


def setup_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def load_sync_module() -> Any:
    os.chdir(PROJECT_DIR)
    spec = importlib.util.spec_from_file_location("sync_webapp_to_planner_module", SYNC_SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {SYNC_SCRIPT_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync_module = None


def get_sync_module() -> Any:
    global sync_module
    if sync_module is None:
        sync_module = load_sync_module()
    return sync_module


def allowed_origin_patterns() -> list[str]:
    raw = os.getenv("PLANNER_SYNC_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    return [item.strip() for item in raw.split(",") if item.strip()]


def is_origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True

    patterns = allowed_origin_patterns()
    if "*" in patterns:
        return True

    return any(fnmatch.fnmatch(origin, pattern) for pattern in patterns)


class PlannerSyncHandler(BaseHTTPRequestHandler):
    server_version = "PlannerSyncServer/1.0"

    def end_headers(self) -> None:
        origin = self.headers.get("Origin")
        if is_origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin or "*")
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}

        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise ValueError("Request body must be valid JSON.") from exc

        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object.")
        return data

    def do_OPTIONS(self) -> None:
        if not is_origin_allowed(self.headers.get("Origin")):
            self.write_json(HTTPStatus.FORBIDDEN, {"ok": False, "message": "Origin is not allowed."})
            return
        self.write_json(HTTPStatus.OK, {"ok": True})

    def do_GET(self) -> None:
        if self.path != "/health":
            self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "Unknown endpoint."})
            return

        self.write_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "service": "planner_sync_server",
                "sync_endpoint": "/sync-webapp-to-planner",
                "delete_endpoint": "/delete-planner-task",
            },
        )

    def do_POST(self) -> None:
        if self.path == "/delete-planner-task":
            self.handle_delete_planner_task()
            return

        if self.path != "/sync-webapp-to-planner":
            self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "Unknown endpoint."})
            return

        if not is_origin_allowed(self.headers.get("Origin")):
            self.write_json(HTTPStatus.FORBIDDEN, {"ok": False, "message": "Origin is not allowed."})
            return

        try:
            payload = self.read_json_body()
            target_row_number = payload.get("vbqppl_row_number") or payload.get("target_row_number")
            so_hieu = str(payload.get("so_hieu", "") or "").strip()
            dry_run = bool(payload.get("dry_run", False))
            limit = int(payload.get("limit", 1) or 1)

            module = get_sync_module()
            with sync_lock:
                if target_row_number or so_hieu:
                    summary = module.sync_single_webapp_record_to_planner(
                        row_number=target_row_number,
                        so_hieu=so_hieu,
                        dry_run=dry_run,
                    )
                else:
                    summary = module.sync_webapp_to_planner(limit=limit, dry_run=dry_run)

            self.write_json(
                HTTPStatus.OK,
                {
                    "ok": bool(summary.get("ok")),
                    "message": "Planner sync completed." if summary.get("ok") else "Planner sync failed.",
                    "summary": summary,
                    "created_tasks": int(summary.get("created_tasks", 0) or 0),
                    "failed_records": int(summary.get("failed_records", 0) or 0),
                    "skip_reason": summary.get("skip_reason", ""),
                    "raw_skip_reason": summary.get("raw_skip_reason", ""),
                },
            )
        except Exception as exc:
            self.write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "message": str(exc)})

    def handle_delete_planner_task(self) -> None:
        if not is_origin_allowed(self.headers.get("Origin")):
            self.write_json(HTTPStatus.FORBIDDEN, {"ok": False, "message": "Origin is not allowed."})
            return

        try:
            payload = self.read_json_body()
            planner_task_id = str(payload.get("planner_task_id", "") or payload.get("task_id", "") or "").strip()
            so_hieu = str(payload.get("so_hieu", "") or "").strip()
            ten_van_ban = str(payload.get("ten_van_ban", "") or "").strip()
            deleted_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

            if not planner_task_id:
                result = {
                    "ok": True,
                    "deleted": False,
                    "planner_task_id": "",
                    "so_hieu": so_hieu,
                    "ten_van_ban": ten_van_ban,
                    "deleted_at": deleted_at,
                    "message": "Không có Planner Task ID để xóa.",
                }
                print(json.dumps({"event": "PLANNER_TASK_DELETE_RESULT", **result}, ensure_ascii=False))
                self.write_json(HTTPStatus.OK, result)
                return

            import ms_planner

            with sync_lock:
                delete_result = ms_planner.delete_planner_task(planner_task_id, expected_so_hieu=so_hieu)

            result = {
                "ok": bool(delete_result.get("ok")),
                "deleted": bool(delete_result.get("ok")),
                "planner_task_id": planner_task_id,
                "so_hieu": so_hieu,
                "ten_van_ban": ten_van_ban,
                "deleted_at": deleted_at,
                "delete_result": delete_result,
                "message": delete_result.get("message", ""),
            }
            print(json.dumps({"event": "PLANNER_TASK_DELETE_RESULT", **result}, ensure_ascii=False))

            if not result["ok"]:
                self.write_json(HTTPStatus.BAD_REQUEST, result)
                return

            self.write_json(HTTPStatus.OK, result)
        except Exception as exc:
            self.write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "message": str(exc)})


def main() -> None:
    setup_utf8_stdio()
    load_server_env()

    parser = argparse.ArgumentParser(description="Run the local Planner sync HTTP server.")
    parser.add_argument("--host", default=os.getenv("PLANNER_SYNC_SERVER_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("PLANNER_SYNC_SERVER_PORT", str(DEFAULT_PORT))))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), PlannerSyncHandler)
    print(f"Planner sync server listening on http://{args.host}:{args.port}")
    print("POST /sync-webapp-to-planner to create Planner tasks after Dashboard transfers.")
    server.serve_forever()


if __name__ == "__main__":
    main()

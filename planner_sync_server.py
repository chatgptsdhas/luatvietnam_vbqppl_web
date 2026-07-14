from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from planner_sync_security import ReplayCache, SecurityValidationError, verify_request

PROJECT_DIR = Path(__file__).resolve().parent
SYNC_SCRIPT_PATH = PROJECT_DIR / "11_sync_webapp_to_planner.py"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SERVICE_VERSION = "1.1.0-p0"

# P0: đã bỏ "null" khỏi danh sách mặc định — Origin "null" (file:// hoặc sandbox iframe) không
# còn được coi là hợp lệ theo mặc định. Xem PLANNER_SYNC_ALLOWED_ORIGINS trong .env để tùy biến.
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost,http://localhost:*,"
    "http://127.0.0.1,http://127.0.0.1:*,"
    "https://script.google.com,"
    "https://*.googleusercontent.com,"
    "https://tracuuphaply.vercel.app"
)

DEFAULT_MAX_BODY_BYTES = 1048576
DEFAULT_REQUEST_TTL_SECONDS = 300

sync_lock = threading.Lock()
_replay_cache: Optional[ReplayCache] = None
_replay_cache_lock = threading.Lock()


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
    # P0: KHÔNG còn mặc định chấp nhận request thiếu Origin ở tầng allow-list này. Điều đó
    # không đồng nghĩa request thiếu Origin bị chặn tuyệt đối — endpoint ghi dữ liệu vẫn có
    # thể tiếp tục nếu chữ ký HMAC hợp lệ (xem check_origin_if_present / verify_signed_request).
    if not origin:
        return False

    patterns = allowed_origin_patterns()
    if "*" in patterns:
        return True

    return any(fnmatch.fnmatch(origin, pattern) for pattern in patterns)


def get_shared_secret() -> str:
    return os.getenv("PLANNER_SYNC_SHARED_SECRET", "")


def get_max_body_bytes() -> int:
    try:
        return int(os.getenv("PLANNER_SYNC_MAX_BODY_BYTES", str(DEFAULT_MAX_BODY_BYTES)))
    except ValueError:
        return DEFAULT_MAX_BODY_BYTES


def get_request_ttl_seconds() -> int:
    try:
        return int(os.getenv("PLANNER_SYNC_REQUEST_TTL_SECONDS", str(DEFAULT_REQUEST_TTL_SECONDS)))
    except ValueError:
        return DEFAULT_REQUEST_TTL_SECONDS


def get_replay_cache() -> ReplayCache:
    global _replay_cache
    with _replay_cache_lock:
        if _replay_cache is None:
            _replay_cache = ReplayCache(ttl_seconds=get_request_ttl_seconds())
        return _replay_cache


def log_event(event: str, **fields: Any) -> None:
    """Ghi log JSON 1 dòng ra stdout. KHÔNG BAO GIỜ truyền secret/signature/header thô vào đây."""
    try:
        print(json.dumps({"event": event, **fields}, ensure_ascii=False))
    except Exception:
        pass


class PlannerSyncHandler(BaseHTTPRequestHandler):
    server_version = "PlannerSyncServer/1.1-p0"

    def end_headers(self) -> None:
        origin = self.headers.get("Origin")
        if is_origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin or "*")
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-P0-Timestamp, X-P0-Request-Id, X-P0-Signature",
        )
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

    def write_security_error(self, correlation_id: str, exc: SecurityValidationError) -> None:
        log_event("SECURITY_REJECTED", path=self.path, code=exc.code, correlation_id=correlation_id)
        self.write_json(
            HTTPStatus(exc.status_code),
            {"ok": False, "error": exc.code, "message": str(exc), "correlationId": correlation_id},
        )

    def write_internal_error(self, correlation_id: str, exc: Exception) -> None:
        # P0: KHÔNG bao giờ trả stack trace / đường dẫn file / biến môi trường ra client.
        # Chi tiết chỉ ghi server-side qua log_event (không chứa secret/signature).
        log_event("INTERNAL_ERROR", path=self.path, correlation_id=correlation_id, detail=str(exc))
        self.write_json(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            {
                "ok": False,
                "error": "INTERNAL_ERROR",
                "message": "Đã xảy ra lỗi nội bộ. Xem log server để biết chi tiết.",
                "correlationId": correlation_id,
            },
        )

    # ---- Helpers dùng chung cho các endpoint ghi dữ liệu (P0) ----

    def check_content_type(self) -> None:
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise SecurityValidationError(
                "UNSUPPORTED_CONTENT_TYPE", "Content-Type phải là application/json.", 415
            )

    def check_origin_if_present(self) -> None:
        # Chỉ chặn sớm khi Origin CÓ mặt nhưng không nằm trong allow-list (ví dụ trang web lạ).
        # Request KHÔNG có Origin (curl, script nội bộ...) vẫn phải tiếp tục qua verify_signed_request.
        origin = self.headers.get("Origin")
        if origin and not is_origin_allowed(origin):
            raise SecurityValidationError("ORIGIN_FORBIDDEN", "Origin is not allowed.", 403)

    def read_raw_body(self) -> bytes:
        length_header = self.headers.get("Content-Length", "0") or "0"
        try:
            length = int(length_header)
        except ValueError:
            raise SecurityValidationError("INVALID_CONTENT_LENGTH", "Content-Length không hợp lệ.", 400)

        if length <= 0:
            return b""

        max_bytes = get_max_body_bytes()
        if length > max_bytes:
            raise SecurityValidationError("BODY_TOO_LARGE", "Request body vượt giới hạn cho phép.", 413)

        return self.rfile.read(length)

    def parse_json_body(self, raw_body: bytes) -> dict[str, Any]:
        if not raw_body:
            return {}
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise SecurityValidationError("INVALID_JSON_BODY", "Request body must be valid JSON.", 400) from exc
        if not isinstance(data, dict):
            raise SecurityValidationError("INVALID_JSON_BODY", "Request body must be a JSON object.", 400)
        return data

    def verify_signed_request(self, raw_body: bytes) -> None:
        """
        HMAC PHẢI được xác thực trước khi chạy bất kỳ logic sync/delete nào — đây là cơ chế
        xác thực CHÍNH, không phải Origin/CORS (chỉ còn là lớp phòng thủ phụ, xem
        check_origin_if_present). Envelope do apps_script/Security.js::createPlannerSyncEnvelope_
        ký; frontend chỉ chuyển tiếp, không tự ký.
        """
        secret = get_shared_secret()
        if not secret:
            raise SecurityValidationError(
                "SERVER_NOT_CONFIGURED",
                "Server chưa cấu hình PLANNER_SYNC_SHARED_SECRET — từ chối mọi request ghi dữ liệu.",
                401,
            )

        verify_request(
            headers=self.headers,
            path=self.path,
            raw_body=raw_body,
            secret=secret,
            replay_cache=get_replay_cache(),
            max_body_bytes=get_max_body_bytes(),
            ttl_seconds=get_request_ttl_seconds(),
        )

    # ---- HTTP verbs ----

    def do_OPTIONS(self) -> None:
        if not is_origin_allowed(self.headers.get("Origin")):
            self.write_json(HTTPStatus.FORBIDDEN, {"ok": False, "message": "Origin is not allowed."})
            return
        self.write_json(HTTPStatus.OK, {"ok": True})

    def do_GET(self) -> None:
        if self.path != "/health":
            self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "NOT_FOUND", "message": "Unknown endpoint."})
            return

        # P0: /health KHÔNG liệt kê endpoint nhạy cảm nữa — chỉ trạng thái tối thiểu để giám sát.
        self.write_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "service": "planner_sync_server",
                "version": SERVICE_VERSION,
                "server_time": datetime.now(timezone.utc).isoformat(),
            },
        )

    def do_POST(self) -> None:
        if self.path == "/delete-planner-task":
            self.handle_delete_planner_task()
            return

        if self.path != "/sync-webapp-to-planner":
            self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "NOT_FOUND", "message": "Unknown endpoint."})
            return

        self.handle_sync_webapp_to_planner()

    def handle_sync_webapp_to_planner(self) -> None:
        correlation_id = uuid.uuid4().hex
        try:
            self.check_origin_if_present()
            self.check_content_type()
            raw_body = self.read_raw_body()
            self.verify_signed_request(raw_body)
            payload = self.parse_json_body(raw_body)

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
                    "correlationId": correlation_id,
                },
            )
        except SecurityValidationError as sec_err:
            self.write_security_error(correlation_id, sec_err)
        except Exception as exc:
            self.write_internal_error(correlation_id, exc)

    def handle_delete_planner_task(self) -> None:
        correlation_id = uuid.uuid4().hex
        try:
            self.check_origin_if_present()
            self.check_content_type()
            raw_body = self.read_raw_body()
            self.verify_signed_request(raw_body)
            payload = self.parse_json_body(raw_body)

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
                    "correlationId": correlation_id,
                }
                log_event("PLANNER_TASK_DELETE_RESULT", correlation_id=correlation_id, deleted=False, planner_task_id="")
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
                "correlationId": correlation_id,
            }
            log_event(
                "PLANNER_TASK_DELETE_RESULT",
                correlation_id=correlation_id,
                deleted=result["deleted"],
                planner_task_id=planner_task_id,
            )

            if not result["ok"]:
                self.write_json(HTTPStatus.BAD_REQUEST, result)
                return

            self.write_json(HTTPStatus.OK, result)
        except SecurityValidationError as sec_err:
            self.write_security_error(correlation_id, sec_err)
        except Exception as exc:
            self.write_internal_error(correlation_id, exc)


def main() -> None:
    setup_utf8_stdio()
    load_server_env()

    if not get_shared_secret():
        print(
            "CẢNH BÁO: PLANNER_SYNC_SHARED_SECRET chưa được cấu hình trong .env — "
            "mọi request tới /sync-webapp-to-planner và /delete-planner-task sẽ bị từ chối "
            "(401 SERVER_NOT_CONFIGURED) cho đến khi cấu hình secret. Xem P0_MANUAL_ACTIONS.md."
        )

    parser = argparse.ArgumentParser(description="Run the local Planner sync HTTP server.")
    parser.add_argument("--host", default=os.getenv("PLANNER_SYNC_SERVER_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("PLANNER_SYNC_SERVER_PORT", str(DEFAULT_PORT))))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), PlannerSyncHandler)
    print(f"Planner sync server listening on http://{args.host}:{args.port}")
    print("POST /sync-webapp-to-planner and /delete-planner-task require a valid P0 HMAC envelope.")
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Safe shared plumbing for Vercel's same-origin Apps Script proxy.

Microsoft Planner deliberately has no Vercel implementation.  Planner write
requests are signed by Apps Script and are handled only by the local Windows
Planner Sync Server using its delegated Microsoft Graph session.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any

import requests


WEBAPP_TIMEOUT_SECONDS = 45
WEBAPP_MAX_ATTEMPTS = 3
MAX_REQUEST_BYTES = 256 * 1024

# Browser requests go through /api/webapp.  These machine-to-machine actions
# must never become browser-reachable, even when an admin session is present.
SERVICE_ONLY_ACTIONS = {"import_vbqppl_nhap", "update_vbqppl_record"}
ADMIN_ACTIONS = {
    "transfer_record",
    "update_record",
    "request_planner_sync_envelope",
    "validate_admin_session",
}


class ApiProblem(Exception):
    """A deliberately client-safe API error."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = int(status)
        self.code = code
        self.message = message


def env_value(name: str, *, required: bool = True, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    if required:
        raise ApiProblem(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "BACKEND_NOT_CONFIGURED",
            f"Thiếu cấu hình máy chủ: {name}.",
        )
    return default


def clean_text(value: Any) -> str:
    return str(value or "").strip()


class AppsScriptClient:
    """Server-side Apps Script client with the existing transient retry policy."""

    def __init__(self, http: Any = requests):
        self.http = http

    def call(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
        *,
        admin_session: str = "",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "token": env_value("APPS_SCRIPT_TOKEN"),
            "action": action,
            "payload": payload or {},
        }
        if admin_session:
            body["admin_session"] = admin_session

        last_error: Exception | None = None
        response = None
        for attempt in range(1, WEBAPP_MAX_ATTEMPTS + 1):
            try:
                response = self.http.post(
                    env_value("APPS_SCRIPT_WEBAPP_URL"),
                    json=body,
                    timeout=WEBAPP_TIMEOUT_SECONDS,
                )
                if response.ok:
                    data = response.json()
                    if isinstance(data, dict):
                        return data
                    last_error = RuntimeError("Apps Script trả response không hợp lệ.")
                else:
                    last_error = RuntimeError(f"Apps Script HTTP {response.status_code}")
            except (requests.RequestException, ValueError) as exc:
                last_error = exc

            retryable = response is None or response.status_code in (404, 408, 429) or response.status_code >= 500
            if attempt < WEBAPP_MAX_ATTEMPTS and retryable:
                time.sleep(0.5 * attempt)
                continue
            break

        raise ApiProblem(
            HTTPStatus.BAD_GATEWAY,
            "APPS_SCRIPT_UNAVAILABLE",
            "Không thể kết nối Google Sheet. Vui lòng thử lại.",
        ) from last_error


def allowed_origins() -> set[str]:
    raw = os.getenv("BACKEND_ALLOWED_ORIGINS", "")
    configured = {item.strip() for item in raw.replace(";", ",").split(",") if item.strip()}
    return configured or {
        "https://tracuuphaply.vercel.app",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    }


class JsonApiHandler(BaseHTTPRequestHandler):
    """Small BaseHTTPRequestHandler helper compatible with Vercel Python."""

    def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover
        return

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(encoded)

    def _set_cors_headers(self) -> None:
        origin = clean_text(self.headers.get("Origin"))
        if origin and origin in allowed_origins():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def do_OPTIONS(self) -> None:
        origin = clean_text(self.headers.get("Origin"))
        if origin and origin not in allowed_origins():
            self.send_json(
                HTTPStatus.FORBIDDEN,
                {"ok": False, "error": "ORIGIN_NOT_ALLOWED", "message": "Origin không được phép."},
            )
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._set_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def read_json(self) -> dict[str, Any]:
        origin = clean_text(self.headers.get("Origin"))
        if origin and origin not in allowed_origins():
            raise ApiProblem(HTTPStatus.FORBIDDEN, "ORIGIN_NOT_ALLOWED", "Origin không được phép.")
        content_type = clean_text(self.headers.get("Content-Type")).split(";", 1)[0].lower()
        if content_type != "application/json":
            raise ApiProblem(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_CONTENT_TYPE", "Content-Type phải là application/json.")
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiProblem(HTTPStatus.BAD_REQUEST, "INVALID_CONTENT_LENGTH", "Content-Length không hợp lệ.") from exc
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            raise ApiProblem(HTTPStatus.BAD_REQUEST, "INVALID_REQUEST_BODY", "Nội dung request không hợp lệ.")
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiProblem(HTTPStatus.BAD_REQUEST, "INVALID_JSON_BODY", "Request phải là JSON hợp lệ.") from exc
        if not isinstance(payload, dict):
            raise ApiProblem(HTTPStatus.BAD_REQUEST, "INVALID_JSON_BODY", "Request phải là JSON object.")
        return payload


def error_payload(error: Exception, correlation_id: str) -> tuple[int, dict[str, Any]]:
    if isinstance(error, ApiProblem):
        return error.status, {"ok": False, "error": error.code, "message": error.message, "correlationId": correlation_id}
    return HTTPStatus.INTERNAL_SERVER_ERROR, {
        "ok": False,
        "error": "INTERNAL_ERROR",
        "message": "Máy chủ gặp lỗi khi xử lý yêu cầu.",
        "correlationId": correlation_id,
    }


def correlation_id() -> str:
    return secrets.token_hex(16)

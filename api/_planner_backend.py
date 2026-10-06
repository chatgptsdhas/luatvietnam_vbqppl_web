"""Shared server-side services for the Vercel Dashboard API.

The browser never calls Apps Script or Microsoft Graph directly.  This module
keeps the two credentials on the server and provides the small, deterministic
operations used by the API entry points in ``api/``.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import date, datetime, time as clock_time, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
REQUEST_TIMEOUT_SECONDS = 45
WEBAPP_TIMEOUT_SECONDS = 45
WEBAPP_MAX_ATTEMPTS = 3
MAX_REQUEST_BYTES = 256 * 1024
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
CREATED_SYNC_STATUS = "Đã tạo task Planner"

# Browser requests are proxied through Vercel.  Service-only actions cannot be
# invoked through this route; they are used only by this backend.
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


def env_value(name: str, *aliases: str, required: bool = True, default: str = "") -> str:
    for key in (name, *aliases):
        value = os.getenv(key, "").strip()
        if value:
            return value
    if required:
        raise ApiProblem(HTTPStatus.SERVICE_UNAVAILABLE, "BACKEND_NOT_CONFIGURED", f"Thiếu cấu hình máy chủ: {name}.")
    return default


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def parse_csv_env(name: str, *aliases: str) -> list[str]:
    raw = env_value(name, *aliases, required=False)
    if not raw:
        return []
    return [item.strip() for item in raw.replace(";", ",").replace("\n", ",").split(",") if item.strip()]


def planner_task_url(task_id: str) -> str:
    template = env_value("PLANNER_TASK_URL_TEMPLATE", required=False)
    if not template or not task_id:
        return ""
    try:
        return template.format(
            tenant_id=env_value("PLANNER_TENANT_ID", "TENANT_ID", required=False),
            group_id=env_value("PLANNER_GROUP_ID", "GROUP_ID", required=False),
            plan_id=env_value("PLANNER_PLAN_ID"),
            bucket_id=env_value("PLANNER_BUCKET_ID_PHAP_CHE", "PLANNER_BUCKET_ID"),
            task_id=task_id,
        ).strip()
    except KeyError:
        return ""


def parse_date(value: Any) -> date | None:
    text = clean_text(value)
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def format_date(value: Any) -> str:
    parsed = parse_date(value)
    return parsed.strftime("%d/%m/%Y") if parsed else clean_text(value)


def next_response_due() -> str:
    raw_days = env_value("LEGAL_DEFAULT_DUE_DAYS", required=False)
    if raw_days:
        try:
            days = int(raw_days)
        except ValueError as exc:
            raise ApiProblem(HTTPStatus.SERVICE_UNAVAILABLE, "BACKEND_NOT_CONFIGURED", "LEGAL_DEFAULT_DUE_DAYS không hợp lệ.") from exc
        if days < 0:
            raise ApiProblem(HTTPStatus.SERVICE_UNAVAILABLE, "BACKEND_NOT_CONFIGURED", "LEGAL_DEFAULT_DUE_DAYS không được âm.")
        return (datetime.now(LOCAL_TIMEZONE).date() + timedelta(days=days)).strftime("%d/%m/%Y")
    raise ApiProblem(HTTPStatus.SERVICE_UNAVAILABLE, "BACKEND_NOT_CONFIGURED", "Thiếu LEGAL_DEFAULT_DUE_DAYS.")


def to_due_datetime(value: str) -> str:
    due_date = parse_date(value)
    if not due_date:
        return ""
    local_due = datetime.combine(due_date, clock_time(17, 0), tzinfo=LOCAL_TIMEZONE)
    return local_due.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def planner_title(record: dict[str, Any]) -> str:
    so_hieu = clean_text(record.get("Số hiệu"))
    title = clean_text(record.get("Tên văn bản"))
    if not so_hieu or not title:
        raise ApiProblem(HTTPStatus.UNPROCESSABLE_ENTITY, "INVALID_RECORD", "Văn bản thiếu Số hiệu hoặc Tên văn bản.")
    prefix = f"[{so_hieu}] "
    full_title = prefix + title
    return full_title if len(full_title) <= 255 else prefix + title[: 255 - len(prefix) - 1] + "…"


def planner_description(record: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Số hiệu: {clean_text(record.get('Số hiệu'))}",
            f"Tên văn bản: {clean_text(record.get('Tên văn bản'))}",
            f"Loại văn bản: {clean_text(record.get('Loại văn bản'))}",
            f"Ngày hiệu lực: {format_date(record.get('Ngày hiệu lực'))}",
        ]
    )


def planner_references(record: dict[str, Any]) -> dict[str, dict[str, str]]:
    url = clean_text(record.get("Link Văn bản") or record.get("Link văn bản"))
    if not url:
        return {}
    if not url.lower().startswith(("https://", "http://")):
        raise ApiProblem(HTTPStatus.UNPROCESSABLE_ENTITY, "INVALID_RECORD", "Link Văn bản phải là URL http/https.")
    alias = clean_text(record.get("Tên văn bản")) or url
    if len(alias) > 100:
        alias = alias[:97].rstrip() + "..."
    reference_key = url.replace("%", "%25").replace(".", "%2E").replace(":", "%3A").replace("@", "%40").replace("#", "%23")
    return {
        reference_key: {
            "@odata.type": "microsoft.graph.plannerExternalReference",
            "alias": alias,
            "previewPriority": " !",
            "type": "Other",
        }
    }


def initial_assignees() -> list[dict[str, str]]:
    user_ids = parse_csv_env("PLANNER_INITIAL_ASSIGNEE_USER_IDS")
    emails = parse_csv_env("PLANNER_INITIAL_ASSIGNEE_EMAILS")
    departments = parse_csv_env("PLANNER_INITIAL_ASSIGNEE_DEPARTMENTS")
    if not (len(user_ids) == len(emails) == len(departments)):
        raise ApiProblem(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "BACKEND_NOT_CONFIGURED",
            "Ba cấu hình PLANNER_INITIAL_ASSIGNEE_* phải có cùng số phần tử.",
        )
    return [{"user_id": user_id, "email": email, "department": department} for user_id, email, department in zip(user_ids, emails, departments)]


def build_checklist(due: str) -> dict[str, dict[str, Any]]:
    checklist: dict[str, dict[str, Any]] = {}
    for assignee in initial_assignees():
        title = f"{assignee['department']} | {assignee['email']} | Hạn hoàn thành: {due} | Phân tích sơ bộ"
        if len(title) > 100:
            raise ApiProblem(HTTPStatus.SERVICE_UNAVAILABLE, "BACKEND_NOT_CONFIGURED", "Checklist Planner vượt quá 100 ký tự.")
        checklist[str(uuid4())] = {
            "@odata.type": "microsoft.graph.plannerChecklistItem",
            "title": title,
            "isChecked": False,
        }
    return checklist


class AppsScriptClient:
    def __init__(self, http: Any = requests):
        self.http = http

    def call(self, action: str, payload: dict[str, Any] | None = None, *, admin_session: str = "", service: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {
            "token": env_value("APPS_SCRIPT_TOKEN"),
            "action": action,
            "payload": payload or {},
        }
        if admin_session:
            body["admin_session"] = admin_session
        if service:
            body["service_token"] = env_value("APPS_SCRIPT_SERVICE_TOKEN")

        last_error: Exception | None = None
        for attempt in range(1, WEBAPP_MAX_ATTEMPTS + 1):
            response = None
            try:
                response = self.http.post(
                    env_value("APPS_SCRIPT_WEBAPP_URL"), json=body, timeout=WEBAPP_TIMEOUT_SECONDS
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

        raise ApiProblem(HTTPStatus.BAD_GATEWAY, "APPS_SCRIPT_UNAVAILABLE", "Không thể kết nối Google Sheet. Vui lòng thử lại.") from last_error

    def validate_admin_session(self, admin_session: str) -> None:
        if not clean_text(admin_session):
            raise ApiProblem(HTTPStatus.UNAUTHORIZED, "ADMIN_SESSION_REQUIRED", "Vui lòng đăng nhập quản trị viên.")
        result = self.call("validate_admin_session", {}, admin_session=admin_session)
        if not result.get("ok"):
            raise ApiProblem(HTTPStatus.UNAUTHORIZED, result.get("error", "ADMIN_SESSION_REQUIRED"), result.get("message", "Phiên quản trị đã hết hạn."))

    def get_records(self) -> list[dict[str, Any]]:
        result = self.call("get_all_records")
        rows = result.get("data") if isinstance(result, dict) else []
        if not result.get("ok") or not isinstance(rows, list):
            raise ApiProblem(HTTPStatus.BAD_GATEWAY, "APPS_SCRIPT_ERROR", "Không đọc được dữ liệu VBQPPL.")
        return [row for row in rows if isinstance(row, dict)]

    def update_planner_fields(self, row_number: int, fields: dict[str, Any]) -> dict[str, Any]:
        result = self.call(
            "update_vbqppl_record",
            {"row_number": row_number, "updates": fields},
            service=True,
        )
        if not result.get("ok"):
            raise ApiProblem(HTTPStatus.BAD_GATEWAY, "APPS_SCRIPT_ERROR", result.get("message", "Không cập nhật được trạng thái Planner vào Sheet."))
        return result


_access_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


class GraphPlannerClient:
    def __init__(self, http: Any = requests):
        self.http = http

    def access_token(self) -> str:
        if _access_token_cache["token"] and float(_access_token_cache["expires_at"]) > time.time() + 120:
            return str(_access_token_cache["token"])
        tenant_id = env_value("MS_GRAPH_TENANT_ID", "TENANT_ID")
        response = self.http.post(
            f"https://login.microsoftonline.com/{quote(tenant_id, safe='')}/oauth2/v2.0/token",
            data={
                "client_id": env_value("MS_GRAPH_CLIENT_ID", "CLIENT_ID"),
                "client_secret": env_value("MS_GRAPH_CLIENT_SECRET"),
                "scope": GRAPH_SCOPE,
                "grant_type": "client_credentials",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if not response.ok:
            raise ApiProblem(HTTPStatus.SERVICE_UNAVAILABLE, "GRAPH_AUTH_FAILED", "Máy chủ chưa xác thực được Microsoft Planner.")
        data = response.json()
        token = clean_text(data.get("access_token")) if isinstance(data, dict) else ""
        if not token:
            raise ApiProblem(HTTPStatus.SERVICE_UNAVAILABLE, "GRAPH_AUTH_FAILED", "Microsoft không trả access token cho Planner.")
        _access_token_cache.update({"token": token, "expires_at": time.time() + int(data.get("expires_in", 3600) or 3600)})
        return token

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any] | None:
        request_headers = {"Authorization": f"Bearer {self.access_token()}", "Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        response = self.http.request(method, f"{GRAPH_BASE_URL}{path}", headers=request_headers, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        if not response.ok:
            # Do not pass Graph's raw response through to the browser: it may contain tenant internals.
            raise ApiProblem(HTTPStatus.BAD_GATEWAY, "PLANNER_REQUEST_FAILED", "Microsoft Planner không xử lý được yêu cầu. Vui lòng thử lại.")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    def find_task_by_title(self, title: str) -> dict[str, Any] | None:
        plan_id = env_value("PLANNER_PLAN_ID")
        next_path = f"/planner/plans/{quote(plan_id, safe='')}/tasks"
        while next_path:
            response = self.request("GET", next_path) or {}
            for task in response.get("value", []) if isinstance(response, dict) else []:
                if clean_text(task.get("title")) == title:
                    return task
            next_link = clean_text(response.get("@odata.nextLink")) if isinstance(response, dict) else ""
            next_path = next_link.replace(GRAPH_BASE_URL, "", 1) if next_link.startswith(GRAPH_BASE_URL) else ""
        return None

    def create_task(self, record: dict[str, Any]) -> dict[str, Any]:
        result = self.request(
            "POST",
            "/planner/tasks",
            {
                "planId": env_value("PLANNER_PLAN_ID"),
                "bucketId": env_value("PLANNER_BUCKET_ID_PHAP_CHE", "PLANNER_BUCKET_ID"),
                "title": planner_title(record),
            },
        ) or {}
        if not clean_text(result.get("id")):
            raise ApiProblem(HTTPStatus.BAD_GATEWAY, "PLANNER_REQUEST_FAILED", "Planner đã không trả Task ID.")
        return result

    def configure_new_task(self, task_id: str, record: dict[str, Any], due: str) -> None:
        details = self.request("GET", f"/planner/tasks/{quote(task_id, safe='')}/details") or {}
        details_etag = clean_text(details.get("@odata.etag"))
        if not details_etag:
            raise ApiProblem(HTTPStatus.BAD_GATEWAY, "PLANNER_REQUEST_FAILED", "Không lấy được phiên bản chi tiết của Planner task.")
        self.request(
            "PATCH",
            f"/planner/tasks/{quote(task_id, safe='')}/details",
            {
                "description": planner_description(record),
                "previewType": "automatic",
                "checklist": build_checklist(due),
                "references": planner_references(record),
            },
            {"If-Match": details_etag, "Prefer": "return=representation"},
        )

        assignments = {
            item["user_id"]: {"@odata.type": "#microsoft.graph.plannerAssignment", "orderHint": " !"}
            for item in initial_assignees()
        }
        legal_user_id = env_value("LEGAL_PIC_USER_ID", required=False)
        if legal_user_id:
            assignments[legal_user_id] = {"@odata.type": "#microsoft.graph.plannerAssignment", "orderHint": " !"}
        task = self.request("GET", f"/planner/tasks/{quote(task_id, safe='')}") or {}
        task_etag = clean_text(task.get("@odata.etag"))
        if not task_etag:
            raise ApiProblem(HTTPStatus.BAD_GATEWAY, "PLANNER_REQUEST_FAILED", "Không lấy được phiên bản Planner task.")
        patch_body: dict[str, Any] = {"assignments": assignments}
        due_datetime = to_due_datetime(due)
        if due_datetime:
            patch_body["dueDateTime"] = due_datetime
        self.request(
            "PATCH",
            f"/planner/tasks/{quote(task_id, safe='')}",
            patch_body,
            {"If-Match": task_etag, "Prefer": "return=representation"},
        )

    def delete_task(self, task_id: str, expected_so_hieu: str) -> dict[str, Any]:
        task = self.request("GET", f"/planner/tasks/{quote(task_id, safe='')}") or {}
        title = clean_text(task.get("title"))
        if expected_so_hieu and expected_so_hieu not in title:
            raise ApiProblem(HTTPStatus.CONFLICT, "PLANNER_TASK_MISMATCH", "Task Planner không khớp với số hiệu văn bản.")
        etag = clean_text(task.get("@odata.etag"))
        if not etag:
            raise ApiProblem(HTTPStatus.BAD_GATEWAY, "PLANNER_REQUEST_FAILED", "Không lấy được phiên bản Planner task để xóa.")
        self.request("DELETE", f"/planner/tasks/{quote(task_id, safe='')}", headers={"If-Match": etag})
        return {"ok": True, "deleted": True, "planner_task_id": task_id, "title": title}


def find_record(records: list[dict[str, Any]], *, target_row_number: Any = "", so_hieu: str = "") -> dict[str, Any] | None:
    target_row = clean_text(target_row_number)
    target_number = clean_text(so_hieu)
    for record in records:
        if target_row and clean_text(record.get("_rowNumber")) == target_row:
            return record
    for record in records:
        if target_number and clean_text(record.get("Số hiệu")) == target_number:
            return record
    return None


def sync_transferred_record(apps: AppsScriptClient, graph: GraphPlannerClient, *, target_row_number: Any = "", so_hieu: str = "") -> dict[str, Any]:
    record = find_record(apps.get_records(), target_row_number=target_row_number, so_hieu=so_hieu)
    if not record:
        raise ApiProblem(HTTPStatus.NOT_FOUND, "RECORD_NOT_FOUND", "Không tìm thấy văn bản vừa chuyển trong VBQPPL.")
    row_number = int(record.get("_rowNumber") or 0)
    if row_number < 2:
        raise ApiProblem(HTTPStatus.BAD_GATEWAY, "INVALID_RECORD", "Dòng VBQPPL không hợp lệ.")
    task_id = clean_text(record.get("Planner Task ID"))
    document_number = clean_text(record.get("Số hiệu"))
    due = next_response_due()
    created = False
    if not task_id:
        title = planner_title(record)
        existing = graph.find_task_by_title(title)
        if existing:
            task_id = clean_text(existing.get("id"))
        else:
            created_task = graph.create_task(record)
            task_id = clean_text(created_task.get("id"))
            try:
                graph.configure_new_task(task_id, record, due)
            except Exception:
                # A partially configured task should not turn into an orphan.  Best effort only;
                # the original error remains the meaningful result for the caller.
                try:
                    graph.delete_task(task_id, document_number)
                except Exception:
                    pass
                raise
            created = True

    apps.update_planner_fields(
        row_number,
        {
            "Planner Task ID": task_id,
            "Planner Plan ID": env_value("PLANNER_PLAN_ID"),
            "Planner Bucket ID": env_value("PLANNER_BUCKET_ID_PHAP_CHE", "PLANNER_BUCKET_ID"),
            "Planner Bucket Name": "Pháp chế",
            "Planner Task URL": planner_task_url(task_id),
            "Planner Sync Status": CREATED_SYNC_STATUS,
            "Planner Last Sync": datetime.now(LOCAL_TIMEZONE).strftime("%d/%m/%Y %H:%M:%S"),
            "Current PIC": env_value("PLANNER_INITIAL_ASSIGNEE_EMAILS", required=False),
            "Current Checkpoint": "Phân tích sơ bộ",
            "Next Response Due": due,
        },
    )
    return {
        "ok": True,
        "created": created,
        "already_existed": not created,
        "task_id": task_id,
        "planner_task_url": planner_task_url(task_id),
        "target_row_number": row_number,
        "so_hieu": document_number,
        "next_response_due": due,
    }


def allowed_origins() -> set[str]:
    configured = parse_csv_env("BACKEND_ALLOWED_ORIGINS")
    return set(configured or ["https://tracuuphaply.vercel.app", "http://localhost:5500", "http://127.0.0.1:5500"])


class JsonApiHandler(BaseHTTPRequestHandler):
    """Small BaseHTTPRequestHandler helper compatible with Vercel Python."""

    def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover - avoids request-body logging
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
            self.send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "ORIGIN_NOT_ALLOWED", "message": "Origin không được phép."})
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

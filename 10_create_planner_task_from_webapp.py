import json
import os
import sys
from datetime import datetime, time, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from graph_auth import get_access_token


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
REQUEST_TIMEOUT_SECONDS = 45
MAX_CHECKLIST_TITLE_LENGTH = 100
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def setup_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


setup_utf8_stdio()
load_dotenv()


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Thiếu biến môi trường {name} trong .env")
    return value


def get_optional_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def graph_request(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> dict | None:
    token = get_access_token()
    url = f"{GRAPH_BASE_URL}{path}"
    request_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if headers:
        request_headers.update(headers)

    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    response = requests.request(
        method=method,
        url=url,
        headers=request_headers,
        data=data,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    print(f"{method} {path} -> {response.status_code}")

    if not response.ok:
        print(f"Graph error status_code={response.status_code}")
        print(response.text)
        response.raise_for_status()

    if not response.text:
        return None

    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def build_title(record: dict) -> str:
    so_hieu = str(record.get("Số hiệu", "") or "").strip()
    ten_van_ban = str(record.get("Tên văn bản", "") or "").strip()

    if not so_hieu:
        raise ValueError("Thiếu trường 'Số hiệu' trong record.")
    if not ten_van_ban:
        raise ValueError("Thiếu trường 'Tên văn bản' trong record.")

    return f"[{so_hieu}] {ten_van_ban}"


def build_description(record: dict) -> str:
    so_hieu = str(record.get("Số hiệu", "") or "").strip()
    ten_van_ban = str(record.get("Tên văn bản", "") or "").strip()
    loai_van_ban = str(record.get("Loại văn bản", "") or "").strip()
    ngay_hieu_luc = str(record.get("Ngày hiệu lực", "") or "").strip()
    link_van_ban = str(record.get("Link Văn bản", "") or record.get("Link văn bản", "") or "").strip()

    return "\n".join(
        [
            f"Số hiệu: {so_hieu}",
            f"Tên văn bản: {ten_van_ban}",
            f"Loại văn bản: {loai_van_ban}",
            f"Ngày hiệu lực: {ngay_hieu_luc}",
            f"Link văn bản: {link_van_ban}",
        ]
    )


def validate_checklist_title(title: str) -> None:
    if len(title) > MAX_CHECKLIST_TITLE_LENGTH:
        raise ValueError(
            "Checklist title vượt quá 100 ký tự: "
            f"{len(title)} ký tự. Title: {title}"
        )


def parse_ddmmyyyy(value: str):
    return datetime.strptime(value, "%d/%m/%Y").date()


def format_ddmmyyyy(value) -> str:
    return value.strftime("%d/%m/%Y")


def resolve_legal_next_response_due() -> str:
    due_days = get_optional_env("LEGAL_DEFAULT_DUE_DAYS")
    due_day = get_optional_env("LEGAL_DEFAULT_DUEDAY")

    if due_days:
        try:
            days = int(due_days)
        except ValueError as exc:
            raise RuntimeError("LEGAL_DEFAULT_DUE_DAYS phải là số nguyên.") from exc
        if days < 0:
            raise RuntimeError("LEGAL_DEFAULT_DUE_DAYS không được là số âm.")
        due_date = datetime.now(LOCAL_TIMEZONE).date() + timedelta(days=days)
        return format_ddmmyyyy(due_date)

    if not due_day:
        raise RuntimeError("Thiếu LEGAL_DEFAULT_DUE_DAYS hoặc LEGAL_DEFAULT_DUEDAY trong .env")

    try:
        days = int(due_day)
    except ValueError:
        try:
            return format_ddmmyyyy(parse_ddmmyyyy(due_day))
        except ValueError as exc:
            raise RuntimeError("LEGAL_DEFAULT_DUEDAY phải là số nguyên hoặc ngày dạng dd/MM/YYYY.") from exc

    if days < 0:
        raise RuntimeError("LEGAL_DEFAULT_DUEDAY không được là số âm.")
    due_date = datetime.now(LOCAL_TIMEZONE).date() + timedelta(days=days)
    return format_ddmmyyyy(due_date)


def build_initial_checklist(next_response_due: str | None = None) -> dict:
    legal_pic_email = get_required_env("LEGAL_PIC_EMAIL")
    due_day = next_response_due or resolve_legal_next_response_due()
    title = f"Pháp chế | {legal_pic_email} | DueDay: {due_day} | Phân tích sơ bộ"
    validate_checklist_title(title)

    return {
        str(uuid4()): {
            "@odata.type": "microsoft.graph.plannerChecklistItem",
            "title": title,
            "isChecked": False,
        }
    }


def convert_ddmmyyyy_to_utc_due_datetime(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""

    try:
        due_date = parse_ddmmyyyy(value)
    except ValueError:
        return ""

    local_due_datetime = datetime.combine(due_date, time(hour=17, minute=0), tzinfo=LOCAL_TIMEZONE)
    utc_due_datetime = local_due_datetime.astimezone(timezone.utc)
    return utc_due_datetime.isoformat().replace("+00:00", "Z")


def create_task(record: dict) -> dict:
    body = {
        "planId": get_required_env("PLANNER_PLAN_ID"),
        "bucketId": get_required_env("PLANNER_BUCKET_ID_PHAP_CHE"),
        "title": build_title(record),
    }
    return graph_request("POST", "/planner/tasks", body=body) or {}


def get_task_details(task_id: str) -> dict:
    return graph_request("GET", f"/planner/tasks/{task_id}/details") or {}


def update_task_details(task_id: str, etag: str, description: str, checklist: dict) -> dict:
    if not etag:
        raise ValueError("Thiếu @odata.etag của plannerTaskDetails.")

    body = {
        "description": description,
        "previewType": "checklist",
        "checklist": checklist,
    }
    return graph_request(
        "PATCH",
        f"/planner/tasks/{task_id}/details",
        body=body,
        headers={
            "If-Match": etag,
            "Prefer": "return=representation",
        },
    ) or {}


def get_task(task_id: str) -> dict:
    return graph_request("GET", f"/planner/tasks/{task_id}") or {}


def update_task(task_id: str, etag: str, body: dict) -> dict:
    if not etag:
        raise ValueError("Thiếu @odata.etag của plannerTask.")
    if not body:
        return {}

    return graph_request(
        "PATCH",
        f"/planner/tasks/{task_id}",
        body=body,
        headers={
            "If-Match": etag,
            "Prefer": "return=representation",
        },
    ) or {}


def build_task_patch_body(next_response_due: str | None = None) -> dict:
    body: dict[str, Any] = {}
    legal_pic_user_id = get_optional_env("LEGAL_PIC_USER_ID")
    if not legal_pic_user_id:
        return body

    due_day = next_response_due or resolve_legal_next_response_due()
    due_datetime = convert_ddmmyyyy_to_utc_due_datetime(due_day)
    if due_datetime:
        body["dueDateTime"] = due_datetime

    body["assignments"] = {
        legal_pic_user_id: {
            "@odata.type": "#microsoft.graph.plannerAssignment",
            "orderHint": " !",
        }
    }

    return body


def create_planner_task_from_record(record: dict) -> dict:
    task_id = ""
    title = ""
    next_response_due = ""
    try:
        next_response_due = resolve_legal_next_response_due()
        title = build_title(record)
        description = build_description(record)
        checklist = build_initial_checklist(next_response_due)

        created_task = create_task(record)
        task_id = str(created_task.get("id", "") or "")
        if not task_id:
            raise RuntimeError("Graph đã tạo task nhưng response không có id.")

        details = get_task_details(task_id)
        update_task_details(
            task_id=task_id,
            etag=str(details.get("@odata.etag", "") or ""),
            description=description,
            checklist=checklist,
        )

        patch_body = build_task_patch_body(next_response_due)
        if patch_body:
            latest_task = get_task(task_id)
            update_task(
                task_id=task_id,
                etag=str(latest_task.get("@odata.etag", "") or ""),
                body=patch_body,
            )

        return {
            "ok": True,
            "task_id": task_id,
            "title": title,
            "planner_web_url": str(created_task.get("webUrl", "") or ""),
            "next_response_due": next_response_due,
            "message": "Đã tạo Planner task và cập nhật details/checklist.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "task_id": task_id,
            "title": title,
            "planner_web_url": "",
            "next_response_due": next_response_due,
            "message": str(exc),
        }


if __name__ == "__main__":
    sample_record = {
        "Số hiệu": "37/2026/TT-BGDĐT",
        "Tên văn bản": "Thông tư quy định về quản lý sách giáo khoa",
        "Loại văn bản": "Thông tư",
        "Ngày hiệu lực": "01/07/2026",
        "Link Văn bản": "https://luatvietnam.vn/test.html",
    }

    result = create_planner_task_from_record(sample_record)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("ok"):
        print(f"task_id={result.get('task_id', '')}")

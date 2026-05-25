import json
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from get_token_browser import get_token


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
REQUEST_TIMEOUT_SECONDS = 45
MAX_CHECKLIST_TITLE_LENGTH = 100
MAX_TASK_TITLE_LENGTH = 255
MAX_REFERENCE_ALIAS_LENGTH = 100
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
PLANNER_REFERENCE_ODATA_TYPE = "microsoft.graph.plannerExternalReference"
PLANNER_REFERENCE_KEY_REPLACEMENTS = [
    ("%", "%25"),
    (".", "%2E"),
    (":", "%3A"),
    ("@", "%40"),
    ("#", "%23"),
]


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


def parse_env_list(name: str, required: bool = True) -> list[str]:
    value = get_required_env(name) if required else get_optional_env(name)
    if not value:
        return []
    normalized = value.replace(";", ",").replace("\n", ",")
    if "," in normalized:
        return [item.strip() for item in normalized.split(",") if item.strip()]
    return [item.strip() for item in normalized.split() if item.strip()]


def get_initial_assignees() -> list[dict[str, str]]:
    user_ids = parse_env_list("PLANNER_INITIAL_ASSIGNEE_USER_IDS")
    emails = parse_env_list("PLANNER_INITIAL_ASSIGNEE_EMAILS")
    departments = parse_env_list("PLANNER_INITIAL_ASSIGNEE_DEPARTMENTS")

    if not (len(user_ids) == len(emails) == len(departments)):
        raise RuntimeError(
            "PLANNER_INITIAL_ASSIGNEE_USER_IDS, PLANNER_INITIAL_ASSIGNEE_EMAILS, "
            "PLANNER_INITIAL_ASSIGNEE_DEPARTMENTS phải có cùng số lượng phần tử."
        )

    return [
        {
            "user_id": user_id,
            "email": email,
            "department": department,
        }
        for user_id, email, department in zip(user_ids, emails, departments)
    ]


def graph_request(
    token: str,
    method: str,
    path: str,
    body: dict | None = None,
    headers: dict | None = None,
) -> dict | None:
    if not token:
        raise RuntimeError("Thiếu Microsoft Graph access token.")

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
        raise requests.HTTPError(
            f"{response.status_code} Client Error for {url}: {response.text}",
            response=response,
        )

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

    title = f"[{so_hieu}] {ten_van_ban}"

    if len(title) > MAX_TASK_TITLE_LENGTH:
        # Tính số ký tự còn lại cho Tên văn bản sau khi trừ phần [so_hieu] + dấu cách
        prefix = f"[{so_hieu}] "
        max_ten = MAX_TASK_TITLE_LENGTH - len(prefix) - 1  # trừ 1 cho dấu "…"
        ten_van_ban_truncated = ten_van_ban[:max_ten] + "…"
        title = prefix + ten_van_ban_truncated

    return title


def build_description(record: dict) -> str:
    so_hieu = str(record.get("Số hiệu", "") or "").strip()
    ten_van_ban = str(record.get("Tên văn bản", "") or "").strip()
    loai_van_ban = str(record.get("Loại văn bản", "") or "").strip()
    ngay_hieu_luc = format_effective_date(record.get("Ngày hiệu lực", ""))

    return "\n".join(
        [
            f"Số hiệu: {so_hieu}",
            f"Tên văn bản: {ten_van_ban}",
            f"Loại văn bản: {loai_van_ban}",
            f"Ngày hiệu lực: {ngay_hieu_luc}",
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


def format_effective_date(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, datetime):
        effective_datetime = value
        if effective_datetime.tzinfo is not None:
            effective_datetime = effective_datetime.astimezone(LOCAL_TIMEZONE)
        return format_ddmmyyyy(effective_datetime)

    if isinstance(value, date):
        return format_ddmmyyyy(value)

    text = str(value or "").strip()
    if not text:
        return ""

    try:
        parsed_date = parse_ddmmyyyy(text)
        if len(text) == 10 and text[2] == "/" and text[5] == "/":
            return text
        return format_ddmmyyyy(parsed_date)
    except ValueError:
        pass

    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed_datetime = datetime.fromisoformat(iso_text)
    except ValueError:
        try:
            return format_ddmmyyyy(date.fromisoformat(text))
        except ValueError:
            return text

    if parsed_datetime.tzinfo is not None:
        parsed_datetime = parsed_datetime.astimezone(LOCAL_TIMEZONE)
    return format_ddmmyyyy(parsed_datetime)


def get_document_link(record: dict) -> str:
    return str(record.get("Link Văn bản", "") or record.get("Link văn bản", "") or "").strip()


def encode_planner_reference_key(url: str) -> str:
    encoded = url.strip()
    for old, new in PLANNER_REFERENCE_KEY_REPLACEMENTS:
        encoded = encoded.replace(old, new)
    return encoded


def build_references(record: dict) -> dict:
    link_van_ban = get_document_link(record)
    if not link_van_ban:
        return {}

    lower_url = link_van_ban.lower()
    if not (lower_url.startswith("http://") or lower_url.startswith("https://")):
        raise ValueError("Link Văn bản phải là URL http/https để thêm vào Planner references.")

    alias = str(record.get("Tên văn bản", "") or "").strip() or link_van_ban
    if len(alias) > MAX_REFERENCE_ALIAS_LENGTH:
        alias = alias[: MAX_REFERENCE_ALIAS_LENGTH - 3].rstrip() + "..."
    return {
        encode_planner_reference_key(link_van_ban): {
            "@odata.type": PLANNER_REFERENCE_ODATA_TYPE,
            "alias": alias,
            "previewPriority": " !",
            "type": "Other",
        }
    }


def resolve_next_response_due() -> str:
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


def build_initial_checklist(next_response_due: str) -> dict:
    checklist = {}
    for assignee in get_initial_assignees():
        title = (
            f"{assignee['department']} | {assignee['email']} | "
            f"Hạn hoàn thành: {next_response_due} | Phân tích sơ bộ"
        )
        validate_checklist_title(title)
        checklist[str(uuid4())] = {
            "@odata.type": "microsoft.graph.plannerChecklistItem",
            "title": title,
            "isChecked": False,
        }
    return checklist


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


def create_task(token: str, record: dict) -> dict:
    body = {
        "planId": get_required_env("PLANNER_PLAN_ID"),
        "bucketId": get_required_env("PLANNER_BUCKET_ID_PHAP_CHE"),
        "title": build_title(record),
    }
    return graph_request(token, "POST", "/planner/tasks", body=body) or {}


def get_task_details(token: str, task_id: str) -> dict:
    return graph_request(token, "GET", f"/planner/tasks/{task_id}/details") or {}


def update_task_details(
    token: str,
    task_id: str,
    etag: str,
    description: str,
    checklist: dict,
    references: dict,
) -> dict:
    if not etag:
        raise ValueError("Thiếu @odata.etag của plannerTaskDetails.")

    body = {
        "description": description,
        "previewType": "automatic",
        "checklist": checklist,
        "references": references,
    }
    return graph_request(
        token,
        "PATCH",
        f"/planner/tasks/{task_id}/details",
        body=body,
        headers={
            "If-Match": etag,
            "Prefer": "return=representation",
        },
    ) or {}


def get_task(token: str, task_id: str) -> dict:
    return graph_request(token, "GET", f"/planner/tasks/{task_id}") or {}


def update_task(token: str, task_id: str, etag: str, body: dict) -> dict:
    if not etag:
        raise ValueError("Thiếu @odata.etag của plannerTask.")
    if not body:
        return {}

    return graph_request(
        token,
        "PATCH",
        f"/planner/tasks/{task_id}",
        body=body,
        headers={
            "If-Match": etag,
            "Prefer": "return=representation",
        },
    ) or {}


def delete_planner_task(task_id: str, expected_so_hieu: str = "") -> dict:
    try:
        token = get_token()
        task = graph_request(token, "GET", f"/planner/tasks/{task_id}")
        title = str((task or {}).get("title", "") or "")
        expected_so_hieu = str(expected_so_hieu or "").strip()
        if expected_so_hieu and expected_so_hieu not in title:
            return {
                "ok": False,
                "task_id": task_id,
                "title": title,
                "message": f"Planner task không khớp Số hiệu {expected_so_hieu}.",
            }

        etag = str((task or {}).get("@odata.etag", "") or "")
        if not etag:
            raise RuntimeError(f"Không lấy được @odata.etag của task {task_id}.")

        url = f"{GRAPH_BASE_URL}/planner/tasks/{task_id}"
        request_headers = {
            "Authorization": f"Bearer {token}",
            "If-Match": etag,
        }
        response = requests.delete(url, headers=request_headers, timeout=REQUEST_TIMEOUT_SECONDS)
        print(f"DELETE /planner/tasks/{task_id} -> {response.status_code}")

        if response.status_code == 204:
            return {"ok": True, "task_id": task_id, "title": title, "message": "Đã xóa task Planner"}

        print(f"Graph error status_code={response.status_code}")
        print(response.text)
        return {"ok": False, "task_id": task_id, "status_code": response.status_code, "message": response.text}
    except Exception as exc:
        return {"ok": False, "task_id": task_id, "message": str(exc)}


def build_task_patch_body(next_response_due: str) -> dict:
    body: dict[str, Any] = {}
    due_datetime = convert_ddmmyyyy_to_utc_due_datetime(next_response_due)
    if due_datetime:
        body["dueDateTime"] = due_datetime

    assignments = {
        assignee["user_id"]: {
            "@odata.type": "#microsoft.graph.plannerAssignment",
            "orderHint": " !",
        }
        for assignee in get_initial_assignees()
    }

    legal_user_id = get_optional_env("LEGAL_PIC_USER_ID")
    if legal_user_id:
        assignments[legal_user_id] = {
            "@odata.type": "#microsoft.graph.plannerAssignment",
            "orderHint": " !",
        }

    body["assignments"] = assignments
    return body


def build_planner_task_url(task_id: str) -> str:
    template = get_optional_env("PLANNER_TASK_URL_TEMPLATE")
    if not template or not task_id:
        return ""

    values = {
        "tenant_id": get_optional_env("PLANNER_TENANT_ID") or get_optional_env("TENANT_ID"),
        "group_id": get_optional_env("PLANNER_GROUP_ID") or get_optional_env("GROUP_ID"),
        "plan_id": get_optional_env("PLANNER_PLAN_ID"),
        "bucket_id": get_optional_env("PLANNER_BUCKET_ID_PHAP_CHE") or get_optional_env("PLANNER_BUCKET_ID"),
        "task_id": task_id,
    }

    try:
        return template.format(**values).strip()
    except Exception:
        return ""


def create_planner_task_from_record(record: dict) -> dict:
    task_id = ""
    title = ""
    next_response_due = ""
    planner_web_url = ""
    rollback_result = None
    try:
        token = get_token()
        next_response_due = resolve_next_response_due()
        title = build_title(record)
        description = build_description(record)
        checklist = build_initial_checklist(next_response_due)
        references = build_references(record)

        created_task = create_task(token, record)
        task_id = str(created_task.get("id", "") or "")
        if not task_id:
            raise RuntimeError("Graph đã tạo task nhưng response không có id.")
        planner_web_url = build_planner_task_url(task_id)

        details = get_task_details(token, task_id)
        update_task_details(
            token=token,
            task_id=task_id,
            etag=str(details.get("@odata.etag", "") or ""),
            description=description,
            checklist=checklist,
            references=references,
        )

        patch_body = build_task_patch_body(next_response_due)
        if patch_body:
            latest_task = get_task(token, task_id)
            update_task(
                token=token,
                task_id=task_id,
                etag=str(latest_task.get("@odata.etag", "") or ""),
                body=patch_body,
            )

        return {
            "ok": True,
            "task_id": task_id,
            "title": title,
            "planner_web_url": planner_web_url,
            "next_response_due": next_response_due,
            "message": "Đã tạo Planner task và cập nhật details/checklist.",
        }
    except Exception as exc:
        if task_id:
            rollback_result = delete_planner_task(task_id)
        return {
            "ok": False,
            "task_id": task_id,
            "title": title,
            "planner_web_url": planner_web_url,
            "next_response_due": next_response_due,
            "message": str(exc),
            "rollback_result": rollback_result,
        }


def build_test_record() -> dict:
    timestamp = datetime.now(LOCAL_TIMEZONE).strftime("%Y%m%d-%H%M%S")
    return {
        "Số hiệu": f"TEST-MSPLANNER-{timestamp}",
        "Tên văn bản": "Task test Microsoft Planner từ ms_planner.py",
        "Loại văn bản": "Test",
        "Ngày hiệu lực": datetime.now(LOCAL_TIMEZONE).strftime("%d/%m/%Y"),
        "Link Văn bản": "https://luatvietnam.vn/test.html",
    }


def main() -> None:
    result = create_planner_task_from_record(build_test_record())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

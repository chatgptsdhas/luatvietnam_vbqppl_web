"""
Module tạo và quản lý task trong Microsoft Teams Planner.
Sử dụng token cache từ ms_auth_init.py, tự động refresh khi hết hạn.
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import msal
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CLIENT_ID        = os.getenv("CLIENT_ID")
TENANT_ID        = os.getenv("TENANT_ID")
TOKEN_CACHE_PATH = Path(os.getenv("TOKEN_CACHE_PATH", "config/token_cache.json"))

PLAN_ID          = os.getenv("PLANNER_PLAN_ID")
BUCKET_PHAP_CHE  = os.getenv("PLANNER_BUCKET_ID_PHAP_CHE")
LEGAL_EMAIL      = os.getenv("LEGAL_PIC_EMAIL")
LEGAL_USER_ID    = os.getenv("LEGAL_PIC_USER_ID")
DEFAULT_DUE_DAYS = int(os.getenv("LEGAL_DEFAULT_DUE_DAYS", "5"))

GRAPH_URL = "https://graph.microsoft.com/v1.0"

SCOPES = [
    "https://graph.microsoft.com/Tasks.ReadWrite",
    "https://graph.microsoft.com/Group.Read.All",
    "offline_access",
]


def _get_token() -> str:
    if not TOKEN_CACHE_PATH.exists():
        raise FileNotFoundError(
            f"Chưa có token cache tại '{TOKEN_CACHE_PATH}'. "
            "Hãy chạy ms_auth_init.py trước."
        )

    cache = msal.SerializableTokenCache()
    cache.deserialize(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))

    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    )

    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError(
            "Token cache hết hạn (>90 ngày). Hãy chạy lại ms_auth_init.py."
        )

    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result or "access_token" not in result:
        raise RuntimeError(
            f"Không thể refresh token: {result.get('error_description', 'unknown')}. "
            "Hãy chạy lại ms_auth_init.py."
        )

    if cache.has_state_changed:
        TOKEN_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")

    return result["access_token"]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }


def create_task(
    title: str,
    plan_id: str = None,
    bucket_id: str = None,
    due_days: int = None,
    assign_to_user_id: str = None,
) -> dict:
    """
    Tạo task trong Planner. Trả về dict gồm id, title, dueDateTime.
    Mặc định dùng plan/bucket/assignee từ .env nếu không truyền tham số.
    """
    body = {
        "planId": plan_id or PLAN_ID,
        "bucketId": bucket_id or BUCKET_PHAP_CHE,
        "title": title,
    }

    days = due_days if due_days is not None else DEFAULT_DUE_DAYS
    due = datetime.utcnow() + timedelta(days=days)
    body["dueDateTime"] = due.strftime("%Y-%m-%dT00:00:00Z")

    user_id = assign_to_user_id or LEGAL_USER_ID
    if user_id:
        body["assignments"] = {
            user_id: {
                "@odata.type": "#microsoft.graph.plannerAssignment",
                "orderHint": " !",
            }
        }

    resp = requests.post(f"{GRAPH_URL}/planner/tasks", headers=_headers(), json=body)
    resp.raise_for_status()

    task = resp.json()
    logger.info("Tạo task thành công: %s | ID: %s", title, task["id"])

    return {
        "id": task["id"],
        "title": task["title"],
        "dueDateTime": task.get("dueDateTime"),
        "planId": task["planId"],
        "bucketId": task["bucketId"],
    }


def update_task_progress(task_id: str, percent_complete: int) -> dict:
    """Cập nhật tiến độ task: 0 = chưa làm, 50 = đang làm, 100 = hoàn thành."""
    # Lấy ETag trước khi update
    get_resp = requests.get(
        f"{GRAPH_URL}/planner/tasks/{task_id}", headers=_headers()
    )
    get_resp.raise_for_status()
    etag = get_resp.headers.get("ETag")

    h = _headers()
    h["If-Match"] = etag

    patch_resp = requests.patch(
        f"{GRAPH_URL}/planner/tasks/{task_id}",
        headers=h,
        json={"percentComplete": percent_complete},
    )
    patch_resp.raise_for_status()

    logger.info("Cập nhật task %s: %d%%", task_id, percent_complete)
    return {"id": task_id, "percentComplete": percent_complete}


def get_plans() -> list:
    """Lấy danh sách Planner plans của tài khoản đang đăng nhập."""
    resp = requests.get(f"{GRAPH_URL}/me/planner/plans", headers=_headers())
    resp.raise_for_status()
    return resp.json().get("value", [])


def get_buckets(plan_id: str = None) -> list:
    """Lấy danh sách buckets trong một plan."""
    pid = plan_id or PLAN_ID
    resp = requests.get(f"{GRAPH_URL}/planner/plans/{pid}/buckets", headers=_headers())
    resp.raise_for_status()
    return resp.json().get("value", [])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("Danh sách Plans:")
    for p in get_plans():
        print(f"  {p['title']} | ID: {p['id']}")

    print()
    print("Tạo task thử nghiệm...")
    task = create_task(
        title="[TEST] Task thử nghiệm từ Python",
        due_days=1,
    )
    print(f"  Tạo thành công: {task}")

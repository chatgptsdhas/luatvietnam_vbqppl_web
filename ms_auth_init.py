"""
Chạy file này 1 lần để đăng nhập legal@has.edu.vn và lưu token cache.
Sau đó hệ thống tự động refresh, không cần chạy lại trong 90 ngày.

Cách chạy:
    python ms_auth_init.py
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import msal
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID       = os.getenv("CLIENT_ID")
TENANT_ID       = os.getenv("TENANT_ID")
TOKEN_CACHE_PATH = Path(os.getenv("TOKEN_CACHE_PATH", "config/token_cache.json"))

SCOPES = [
    "https://graph.microsoft.com/Tasks.ReadWrite",
    "https://graph.microsoft.com/Group.Read.All",
    "offline_access",
]


def main():
    if not CLIENT_ID or not TENANT_ID:
        print("Lỗi: Thiếu CLIENT_ID hoặc TENANT_ID trong .env")
        sys.exit(1)

    TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_PATH.exists():
        cache.deserialize(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))

    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    )

    # Kiểm tra xem đã có token hợp lệ chưa
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            username = accounts[0].get("username", "")
            print(f"Token hợp lệ đã tồn tại cho: {username}")
            print("Không cần đăng nhập lại.")
            return

    # Bắt đầu Device Code flow
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print(f"Lỗi khởi tạo device flow: {flow.get('error_description')}")
        sys.exit(1)

    print()
    print("=" * 60)
    print(flow["message"])
    print("=" * 60)
    print()
    print("Đăng nhập bằng tài khoản: legal@has.edu.vn")
    print("Sau khi xác nhận OTP, quay lại đây...")
    print()

    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        print(f"Đăng nhập thất bại: {result.get('error_description')}")
        sys.exit(1)

    # Lưu cache
    if cache.has_state_changed:
        TOKEN_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")

    username = result.get("id_token_claims", {}).get("preferred_username", "")
    expire_date = (datetime.now() + timedelta(days=85)).strftime("%d/%m/%Y")

    print(f"Đăng nhập thành công: {username}")
    print(f"Token đã lưu tại: {TOKEN_CACHE_PATH}")
    print()
    print(f"Nhắc nhở: Chạy lại file này trước ngày {expire_date}")


if __name__ == "__main__":
    main()

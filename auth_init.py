"""
Đăng nhập legal@has.edu.vn và lưu token cache.
Chạy 1 lần, tự động refresh trong 90 ngày.

    python auth_init.py

Tenant has.edu.vn chặn Device Code flow → dùng Interactive flow (mở browser).
"""

import os, sys
from datetime import datetime, timedelta
from pathlib import Path
import msal
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID        = os.getenv("CLIENT_ID", "de8bc8b5-d9f9-48b1-a8ad-b748da725064")
TENANT_ID        = os.getenv("TENANT_ID")
TOKEN_CACHE_PATH = Path(os.getenv("TOKEN_CACHE_PATH", "config/token_cache.json"))
LEGAL_EMAIL      = os.getenv("LEGAL_PIC_EMAIL", "legal@has.edu.vn")

SCOPES = [
    "https://graph.microsoft.com/Tasks.ReadWrite",
    "https://graph.microsoft.com/Group.Read.All",
    "offline_access",
]

def main():
    if not TENANT_ID:
        sys.exit("Lỗi: Thiếu TENANT_ID trong .env")

    TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_PATH.exists():
        cache.deserialize(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))

    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    )

    # Dùng token cache nếu còn hợp lệ
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            print(f"Token còn hợp lệ: {accounts[0]['username']}")
            return

    print(f"\nMở browser để đăng nhập {LEGAL_EMAIL}...")
    print("Hoàn tất OTP trên browser, script sẽ tự tiếp tục.\n")

    # Interactive flow - mở browser, không cần device code
    # Cùng cơ chế với Graph Explorer trên browser
    result = app.acquire_token_interactive(
        scopes=SCOPES,
        login_hint=LEGAL_EMAIL,
    )

    if "error" in result:
        sys.exit(f"Thất bại: {result.get('error_description')}")

    if cache.has_state_changed:
        TOKEN_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")

    username = result.get("id_token_claims", {}).get("preferred_username", "")
    print(f"\nThành công! Tài khoản: {username}")
    print(f"Token lưu tại: {TOKEN_CACHE_PATH}")
    print(f"Chạy lại trước: {(datetime.now() + timedelta(days=85)).strftime('%d/%m/%Y')}")

if __name__ == "__main__":
    main()

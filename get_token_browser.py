"""
Lấy access token tự động qua Playwright browser session.

Lần đầu: Mở browser hiện, user login legal@has.edu.vn + OTP.
Các lần sau: Chạy headless, tự refresh token từ session đã lưu (90 ngày).

    python get_token_browser.py
"""

import os, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

SESSION_FILE = Path(os.getenv("BROWSER_SESSION_PATH", "config/browser_session.json"))
LEGAL_EMAIL  = os.getenv("LEGAL_PIC_EMAIL", "legal@has.edu.vn")

# Graph Explorer tự động chạy query "me" khi load → kích hoạt token refresh
GRAPH_EXPLORER = (
    "https://developer.microsoft.com/graph/graph-explorer"
    "?request=me&method=GET&version=v1.0&GraphUrl=https://graph.microsoft.com"
)


def _read_token_from_storage(page) -> str | None:
    """Đọc access token của Graph API từ localStorage của MSAL."""
    return page.evaluate("""
        () => {
            const now = Math.floor(Date.now() / 1000);
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (!key.toLowerCase().includes('accesstoken')) continue;
                try {
                    const item = JSON.parse(localStorage.getItem(key));
                    const notExpired = item?.expiresOn && parseInt(item.expiresOn) > now;
                    const isGraph = key.includes('graph.microsoft.com')
                                 || key.includes('00000003-0000-0000-c000');
                    if (item?.secret && notExpired && isGraph) {
                        return item.secret;
                    }
                } catch (_) {}
            }
            return null;
        }
    """)


def get_token() -> str:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    is_first_run = not SESSION_FILE.exists()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not is_first_run)
        ctx = browser.new_context(
            storage_state=str(SESSION_FILE) if not is_first_run else None
        )
        page = ctx.new_page()
        page.goto(GRAPH_EXPLORER)

        if is_first_run:
            print(f"\nĐăng nhập {LEGAL_EMAIL} trên browser (kể cả OTP)...")
            print("Script tự tiếp tục sau khi đăng nhập thành công.\n")
            token = None
            deadline = time.time() + 120  # Chờ tối đa 2 phút
            while time.time() < deadline:
                page.wait_for_timeout(3_000)
                token = _read_token_from_storage(page)
                if token:
                    break
            if not token:
                browser.close()
                sys.exit("Timeout: Không lấy được token. Thử lại.")
        else:
            # MSAL tự refresh token khi page load - chờ 10 giây
            page.wait_for_timeout(10_000)
            token = _read_token_from_storage(page)

        ctx.storage_state(path=str(SESSION_FILE))
        browser.close()

    if not token:
        print("Session hết hạn. Xóa session cũ và đăng nhập lại...")
        SESSION_FILE.unlink()
        return get_token()

    return token


if __name__ == "__main__":
    token = get_token()
    print(f"\nToken OK! ({len(token)} ký tự)")
    print(f"Preview: {token[:50]}...")

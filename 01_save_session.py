from pathlib import Path
import os

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright


load_dotenv()

LOGIN_URL = os.getenv("LUATVN_LOGIN_URL", "https://luatvietnam.vn/")
AUTH_DIR = Path("auth")
AUTH_FILE = AUTH_DIR / "luatvietnam_state.json"


def main():
    AUTH_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=100,
        )

        context = browser.new_context()
        page = context.new_page()

        print("Đang mở LuatVietnam...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print("\nTrình duyệt đã mở LuatVietnam.")
        print("Ông/Bà hãy đăng nhập thủ công bằng tài khoản hợp lệ.")
        print("Sau khi đăng nhập xong và thấy tài khoản đã vào hệ thống, quay lại Terminal.")
        input("Nhấn Enter tại đây để lưu session đăng nhập... ")

        context.storage_state(path=str(AUTH_FILE))

        print(f"\nĐã lưu session vào: {AUTH_FILE}")
        print("Lần sau có thể dùng session này để mở LuatVietnam mà không cần đăng nhập lại.")

        browser.close()


if __name__ == "__main__":
    main()
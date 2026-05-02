from pathlib import Path
import os
import re

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


load_dotenv()

AUTH_FILE = Path("auth/luatvietnam_state.json")
OUTPUT_DIR = Path("output")

TEST_DOCUMENT_URL = os.getenv("LUATVN_TEST_DOCUMENT_URL")


LUOC_DO_HEADINGS = [
    "Văn bản được hướng dẫn",
    "Văn bản bị sửa đổi, bổ sung",
    "Văn bản hết hiệu lực",
    "Văn bản bị quy định hết hiệu lực",
    "Văn bản hết hiệu lực một phần",
    "Văn bản đang xem",
    "Văn bản tiếng Anh",
    "Văn bản căn cứ",
    "Văn bản dẫn chiếu",
    "Văn bản hướng dẫn",
    "Văn bản sửa đổi, bổ sung",
    "Văn bản thay thế",
    "Văn bản quy định hết hiệu lực",
    "Văn bản quy định hết hiệu lực một phần",
    "Văn bản hợp nhất",
    "Văn bản đính chính",
    "Văn bản đình chỉ",
    "Văn bản đình chỉ một phần",
]


def safe_goto(page, url: str):
    try:
        page.goto(url, wait_until="networkidle", timeout=60000)
    except PlaywrightTimeoutError:
        print("Trang tải quá lâu. Vẫn tiếp tục lấy nội dung hiện có...")


def save_html(page, file_name: str):
    OUTPUT_DIR.mkdir(exist_ok=True)

    output_file = OUTPUT_DIR / file_name
    html = page.content()
    output_file.write_text(html, encoding="utf-8")

    print(f"Đã lưu HTML vào: {output_file}")


def click_luoc_do_tab(page):
    print("\nĐang chuyển sang tab Lược đồ...")

    try:
        page.get_by_text("Lược đồ", exact=True).click(timeout=10000)
        page.wait_for_timeout(3000)
        return True
    except Exception:
        pass

    try:
        page.locator("text=Lược đồ").first.click(timeout=10000)
        page.wait_for_timeout(3000)
        return True
    except Exception as e:
        print("Không bấm được tab Lược đồ.")
        print(f"Lỗi: {e}")
        return False


def expand_luoc_do_sections(page):
    print("\nĐang mở các nhóm Lược đồ có dữ liệu...")

    for heading in LUOC_DO_HEADINGS:
        try:
            pattern = re.compile(rf"^{re.escape(heading)}\s*\([1-9][0-9]*\)$")
            locator = page.get_by_text(pattern).first

            if locator.count() == 0:
                continue

            locator.scroll_into_view_if_needed(timeout=3000)
            locator.click(timeout=3000)
            page.wait_for_timeout(800)

            print(f"Đã thử mở nhóm: {heading}")

        except Exception:
            pass

    page.wait_for_timeout(2000)


def handle_luoc_do_tab(page):
    if click_luoc_do_tab(page):
        expand_luoc_do_sections(page)
        save_html(page, "test_document_luocdo.html")
        print("Đã lưu HTML tab Lược đồ.")
        return True

    print("Chưa lưu được tab Lược đồ. Cần kiểm tra lại selector.")
    return False


def main():
    if not AUTH_FILE.exists():
        raise FileNotFoundError(
            "Chưa tìm thấy file auth/luatvietnam_state.json. "
            "Hãy chạy 01_save_session.py trước."
        )

    if not TEST_DOCUMENT_URL:
        raise ValueError(
            "Thiếu LUATVN_TEST_DOCUMENT_URL trong file .env. "
            "Hãy mở file .env và điền link văn bản mẫu."
        )

    OUTPUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=100,
        )

        context = browser.new_context(
            storage_state=str(AUTH_FILE)
        )

        page = context.new_page()

        print("Đang mở văn bản LuatVietnam bằng session đã lưu...")
        print(f"URL: {TEST_DOCUMENT_URL}")

        safe_goto(page, TEST_DOCUMENT_URL)

        title = page.title()
        current_url = page.url

        print("\nĐã mở trang văn bản.")
        print(f"Tiêu đề trang: {title}")
        print(f"URL hiện tại: {current_url}")

        save_html(page, "test_document.html"
        )

        handle_luoc_do_tab(page)

        print("\nHãy kiểm tra cửa sổ Chromium:")
        print("- Nếu thấy nội dung văn bản và tab Lược đồ: bước này thành công.")
        print("- Nếu thấy màn hình yêu cầu đăng nhập: session chưa dùng được hoặc đã hết hạn.")
        print("- Nếu thấy trang lỗi: kiểm tra lại link trong .env.")

        input("\nNhấn Enter để đóng trình duyệt... ")

        browser.close()


if __name__ == "__main__":
    main()
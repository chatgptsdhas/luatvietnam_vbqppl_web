"""
Script chan doan doc lap: tai truc tiep vai URL van ban bi loi
"Thieu truong bat buoc: Ngay hieu luc" va in ra doan HTML/text xung quanh
khu vuc "hieu luc" de so sanh voi selector/regex hien tai trong
08_process_field_documents_batch.py. Khong sua gi trong pipeline chinh.
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

AUTH_FILE = Path("auth/luatvietnam_state.json")

URLS = [
    # loi (thieu Ngay hieu luc)
    "https://luatvietnam.vn/thue/thong-tu-89-2026-tt-btc-quy-dinh-chi-tiet-luat-quan-ly-thue-va-nghi-dinh-252-2026-nd-cp-440483-d1.html",
    "https://luatvietnam.vn/doanh-nghiep/nghi-dinh-295-2026-nd-cp-ve-dang-ky-to-hop-tac-hop-tac-xa-lien-hiep-hop-tac-xa-441542-d1.html",
    # khong loi truong nay (chi bi loi HTTP 401 khi gui, khong phai thieu field)
    "https://luatvietnam.vn/doanh-nghiep/thong-tu-99-2025-tt-btc-huong-dan-che-do-ke-toan-doanh-nghiep-tu-01-01-2026-417085-d1.html",
]


def normalize_text(value: str) -> str:
    value = str(value or "").replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{2,}", "\n", value)
    return value.strip()


def main():
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=30)
        context = browser.new_context(storage_state=str(AUTH_FILE) if AUTH_FILE.exists() else None)
        page = context.new_page()

        for url in URLS:
            print("\n" + "=" * 100)
            print(f"URL: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
            except Exception as exc:
                print(f"  [ERROR] goto failed: {exc}")
                continue

            try:
                text = page.locator("body").inner_text(timeout=8000)
            except Exception as exc:
                print(f"  [ERROR] inner_text failed: {exc}")
                continue

            lines = [normalize_text(x) for x in text.splitlines() if normalize_text(x)]

            # In ra cac dong co chua tu khoa lien quan "hieu luc" / "ap dung" / "ngay"
            print("  --- Dong chua tu khoa 'hieu luc' / 'ap dung' ---")
            found_any = False
            for i, ln in enumerate(lines):
                low = ln.lower()
                if "hiệu lực" in low or "áp dụng" in low:
                    found_any = True
                    context_before = lines[i - 1] if i > 0 else ""
                    context_after = lines[i + 1] if i + 1 < len(lines) else ""
                    print(f"  [{i}] before: {context_before!r}")
                    print(f"  [{i}] LINE:   {ln!r}")
                    print(f"  [{i}] after:  {context_after!r}")
            if not found_any:
                print("  (khong tim thay dong nao chua 'hieu luc' / 'ap dung')")

            # Thu tim cac selector pho bien tren trang chi tiet luatvietnam cho khu vuc thong tin van ban
            print("  --- Selector .box-info-ish / table thuoc tinh (neu co) ---")
            try:
                html_snippets = page.evaluate(
                    """
                    () => {
                      const out = [];
                      const candidates = document.querySelectorAll(
                        '.vb-info, .box-info, .article-info, .attribute-table, table, .luat-attribute'
                      );
                      candidates.forEach((el, idx) => {
                        if (idx < 5) {
                          const txt = (el.innerText || '').slice(0, 300);
                          if (txt.toLowerCase().includes('hiệu lực') || txt.toLowerCase().includes('hiệu lực'.normalize())) {
                            out.push(el.outerHTML.slice(0, 800));
                          }
                        }
                      });
                      return out;
                    }
                    """
                )
                for snip in html_snippets:
                    print(snip)
                    print("  ---")
            except Exception as exc:
                print(f"  [ERROR] evaluate failed: {exc}")

        browser.close()


if __name__ == "__main__":
    main()

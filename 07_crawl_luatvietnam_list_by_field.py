from pathlib import Path
import json
import re
import sys
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

AUTH_FILE = Path("auth/luatvietnam_state.json")
CONFIG_FILE = Path("config/scan_config.json")

OUTPUT_FILE = Path("output/field_document_urls.json")
OUTPUT_READABLE_FILE = Path("output/field_document_urls_readable.txt")
OUTPUT_DEBUG_FILE = Path("output/field_document_urls_debug.json")

DOCUMENT_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?luatvietnam\.vn/.+?-\d+-d\d+\.html(?:\?.*)?$",
    re.IGNORECASE,
)

DOC_NUMBER_PATTERN = re.compile(
    r"\b\d{1,4}/\d{4}/[A-ZÀ-ỸĐ][A-ZÀ-ỸĐ0-9.\-]*\b",
    re.IGNORECASE,
)

DOC_TYPE_PREFIXES = [
    "Văn bản hợp nhất",
    "Bộ luật",
    "Luật",
    "Nghị định",
    "Thông tư liên tịch",
    "Thông tư",
    "Nghị quyết",
    "Quyết định",
    "Chỉ thị",
    "Công văn",
]

DOC_TYPE_NAME_TO_ID = {
    "Bộ luật": "58",
    "Luật": "10",
    "Nghị định": "11",
    "Thông tư": "21",
}
DOC_TYPE_ID_TO_NAME = {
    "58": "Bộ luật",
    "10": "Luật",
    "11": "Nghị định",
    "21": "Thông tư",
}

EXCLUDED_URL_PATTERNS = [
    r"van-ban-moi\.html",
    r"van-ban-phap-luat-moi\.html",
    r"danh-sach",
    r"tim-kiem",
    r"luat-su-tu-van",
    r"tieu-chuan-viet-nam",
    r"tieu-chuan-quoc-gia",
]

ROW_TITLE_STOP_MARKERS = [
    "Tổng quan",
    "Nội dung",
    "VB gốc",
    "VB liên quan",
    "Hiệu lực",
    "Lược đồ",
    "Tiếng Anh",
    "Tải về",
    "Ban hành:",
    "Áp dụng:",
    "Cập nhật:",
    "Xác thực:",
]

NAV_LINK_TEXTS = {
    "Tổng quan",
    "Nội dung",
    "VB gốc",
    "VB liên quan",
    "Hiệu lực",
    "Lược đồ",
    "Tiếng Anh",
    "Tải về",
    "VB được hợp nhất",
    "Xem chi tiết",
    "Chi tiết",
    "In",
    "Lưu",
}


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def normalize_text(text: str) -> str:
    text = str(text or "").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def configure_console_encoding():
    """Tránh lỗi UnicodeEncodeError trên Windows cp1252/cp1258 console."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if not stream:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def normalize_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    clean = parsed._replace(fragment="").geturl().rstrip("/")
    return clean


def set_query_param(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_items[key] = str(value)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query_items), ""))


def remove_query_param(url: str, key: str) -> str:
    parsed = urlparse(url)
    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_items.pop(key, None)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query_items), ""))


def build_page_url(base_url: str, page_index: int, page_size: int = 100) -> str:
    base = remove_query_param(remove_query_param(base_url, "PageIndex"), "PageSize")
    base = set_query_param(base, "PageSize", str(page_size))
    return set_query_param(base, "PageIndex", str(page_index))


def is_luatvietnam_document_url(url: str) -> bool:
    url = normalize_url(url)
    if not url or "luatvietnam.vn" not in url or not url.lower().endswith(".html"):
        return False
    if not DOCUMENT_URL_PATTERN.search(url):
        return False
    return not any(re.search(p, url, flags=re.IGNORECASE) for p in EXCLUDED_URL_PATTERNS)


def safe_goto(page, url: str):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
    except PlaywrightTimeoutError:
        print("Trang tải quá lâu. Tiếp tục với nội dung hiện có...")


def extract_total_count_from_page(page) -> int:
    try:
        body_text = normalize_text(page.locator("body").inner_text(timeout=10000))
    except Exception:
        return 0

    for pattern in [
        r"Có\s+tất\s+cả\s+([\d\.,]+)\s+văn\s+bản",
        r"Tìm\s+thấy\s+([\d\.,]+)\s+văn\s+bản",
        r"([\d\.,]+)\s+văn\s+bản\s+mới",
    ]:
        m = re.search(pattern, body_text, flags=re.IGNORECASE)
        if not m:
            continue
        try:
            return int(m.group(1).replace(".", "").replace(",", ""))
        except ValueError:
            continue
    return 0


def extract_doc_number_from_title(title: str) -> str:
    matches = DOC_NUMBER_PATTERN.findall(normalize_text(title))
    return matches[0].strip() if matches else ""


def extract_doc_type_from_title(title: str) -> str:
    title = normalize_text(title)
    # bỏ tiền tố STT phổ biến: "12.", "12)", "12 - "
    title = re.sub(r"^\s*\d{1,4}\s*[\.\)\-:]\s*", "", title)

    for prefix in DOC_TYPE_PREFIXES:
        if title.lower().startswith(prefix.lower()):
            return prefix

    # fallback: có thể title chứa thêm tiền tố khác trước loại VB
    for prefix in DOC_TYPE_PREFIXES:
        if re.search(rf"\b{re.escape(prefix)}\b", title, flags=re.IGNORECASE):
            return prefix
    return ""


def get_filters(field: dict) -> dict:
    return field.get("filters", {}) or {}


def get_required_url_path_contains(field: dict) -> list[str]:
    return get_filters(field).get("required_url_path_contains", []) or []


def get_exclude_url_path_contains(field: dict) -> list[str]:
    return get_filters(field).get("exclude_url_path_contains", []) or []


def get_required_field_contains(field: dict) -> list[str]:
    return get_filters(field).get("required_luatvietnam_field_contains", []) or []


def url_matches_required_field_path(url: str, field: dict) -> bool:
    required_paths = get_required_url_path_contains(field)
    exclude_paths = get_exclude_url_path_contains(field)

    if not required_paths:
        ma = str(field.get("ma_linh_vuc", "")).strip()
        required_paths = [ma] if ma else []

    path = urlparse(url).path.lower()
    normalized_path = "/" + path.strip("/") + "/"

    def token_match(token: str) -> bool:
        token = str(token or "").strip().lower()
        if not token:
            return False
        # Hỗ trợ cả dạng "giao-duc" lẫn "/giao-duc/" trong config.
        normalized_token = "/" + token.strip("/") + "/"
        return normalized_token in normalized_path

    if any(token_match(v) for v in exclude_paths):
        return False
    if not required_paths:
        return True
    return any(token_match(v) for v in required_paths)


def passes_extra_filters(doc: dict, field: dict) -> bool:
    filters = get_filters(field)
    title = normalize_text(doc.get("title_from_list", ""))
    url = normalize_text(doc.get("url", "")).lower()
    so_hieu = normalize_text(doc.get("doc_number_from_list", ""))

    for kw in filters.get("exclude_title_keywords", []) or []:
        if kw and kw.lower() in title.lower():
            return False
    for kw in filters.get("exclude_url_keywords", []) or []:
        if kw and kw.lower() in url:
            return False
    for kw in filters.get("exclude_so_hieu_keywords", []) or []:
        if kw and kw.lower() in so_hieu.lower():
            return False
    return True


def get_filter_reject_reason(
    doc: dict,
    field: dict,
    accepted_doc_types: list[str],
    skip_doc_types: list[str],
) -> str:
    """Trả về lý do bị loại đầu tiên để thống kê debug."""
    url = normalize_text(doc.get("url", ""))
    if not url_matches_required_field_path(url, field):
        return "required_url_path_contains"

    doc_type = normalize_text(doc.get("doc_type_from_list", ""))
    if not doc_type:
        doc_type = extract_doc_type_from_title(doc.get("title_from_list", ""))

    crawl_doc_type_id = str(field.get("crawl_doc_type_id", "")).strip()
    expected_doc_type = DOC_TYPE_ID_TO_NAME.get(crawl_doc_type_id, "")
    if expected_doc_type and doc_type and doc_type != expected_doc_type:
        return "doc_type"

    if accepted_doc_types and (not doc_type or doc_type not in accepted_doc_types):
        return "doc_type"

    if skip_doc_types and doc_type in skip_doc_types:
        return "doc_type"

    filters = get_filters(field)
    title = normalize_text(doc.get("title_from_list", ""))
    so_hieu = normalize_text(doc.get("doc_number_from_list", ""))
    url_lower = url.lower()

    for kw in filters.get("exclude_title_keywords", []) or []:
        if kw and kw.lower() in title.lower():
            return "exclude_title_keywords"

    for kw in filters.get("exclude_url_keywords", []) or []:
        if kw and kw.lower() in url_lower:
            return "exclude_url_keywords"

    for kw in filters.get("exclude_so_hieu_keywords", []) or []:
        if kw and kw.lower() in so_hieu.lower():
            return "exclude_so_hieu_keywords"

    return ""


def page_is_error_or_empty(page) -> bool:
    try:
        text = (normalize_text(page.title()) + "\n" + normalize_text(page.locator("body").inner_text(timeout=5000))).lower()
    except Exception:
        return True
    if not text.strip():
        return True
    return any(k in text for k in ["404", "không tìm thấy", "not found", "trang không tồn tại"])


def page_has_updating_message(page) -> bool:
    """Trang không có dữ liệu, chỉ hiển thị 'Dữ liệu đang cập nhật.'"""
    try:
        body = normalize_text(page.locator("body").inner_text(timeout=5000)).lower()
    except Exception:
        return False

    keywords = [
        "dữ liệu đang cập nhật",
        "du lieu dang cap nhat",
    ]
    return any(k in body for k in keywords)


def extract_text_rows_from_page(page, expected_count: int = 0) -> list[dict]:
    body_text = page.locator("body").inner_text(timeout=12000).replace("\xa0", " ")
    raw_lines = [normalize_text(line) for line in body_text.splitlines() if normalize_text(line)]

    start_at = 0
    end_at = len(raw_lines)
    for idx, line in enumerate(raw_lines):
        if "Sắp xếp theo" in line or ("Có tất cả" in line and "văn bản" in line):
            start_at = idx + 1
            break
    for idx in range(start_at, len(raw_lines)):
        if any(k in raw_lines[idx] for k in ["DANH MỤC TRA CỨU", "TIN VĂN BẢN MỚI", "HỎI ĐÁP PHÁP LUẬT"]):
            end_at = idx
            break

    rows, i, lines = [], 0, raw_lines[start_at:end_at]
    while i < len(lines):
        line = lines[i]
        number, title_parts = None, []

        if re.fullmatch(r"\d{1,4}", line):
            number = int(line)
            i += 1
        else:
            m = re.match(r"^(\d{1,4})\s+(.+)$", line)
            if not m:
                i += 1
                continue
            number, i = int(m.group(1)), i + 1
            title_parts.append(m.group(2).strip())

        while i < len(lines):
            current = lines[i]
            if re.fullmatch(r"\d{1,4}", current) or re.match(r"^\d{1,4}\s+.+$", current):
                break
            hit_marker = False
            for marker in ROW_TITLE_STOP_MARKERS:
                pos = current.find(marker)
                if pos >= 0:
                    if pos > 0:
                        title_parts.append(current[:pos].strip())
                    hit_marker = True
                    break
            if hit_marker:
                break
            title_parts.append(current)
            i += 1

        title = normalize_text(" ".join(title_parts))
        if number is not None and title:
            rows.append({"number": number, "title_from_text": title})
        if expected_count > 0 and len(rows) >= expected_count:
            break
        i += 1

    return rows


def extract_dom_document_rows(page, current_url: str, field: dict) -> list[dict]:
    """Parse DOM sâu hơn: group theo từng row và chọn link chính xác của row."""
    raw = page.locator("a[href*='-d'][href*='.html']").evaluate_all(
        """
        (anchors) => {
          const norm = (s) => (s || '').replace(/\\u00a0/g, ' ').replace(/[ \\t]+/g, ' ').replace(/\\n{2,}/g, '\\n').trim();
          const visible = (el) => {
            const rect = el.getBoundingClientRect();
            if (!rect || rect.width <= 0 || rect.height <= 0) return false;
            const st = getComputedStyle(el);
            return st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
          };
          const findRow = (a) => {
            let n = a;
            for (let i = 0; i < 8 && n; i++) {
              if (n.matches && n.matches('li, article, tr, .item, .row, .doc-item, .list-item, .item-news, .item-vanban')) return n;
              n = n.parentElement;
            }
            return a.parentElement || a;
          };
          const nodePath = (el) => {
            const parts = [];
            let n = el;
            let depth = 0;
            while (n && n.tagName && depth < 8) {
              const tag = n.tagName.toLowerCase();
              let idx = 1;
              let p = n;
              while ((p = p.previousElementSibling)) {
                if (p.tagName === n.tagName) idx++;
              }
              parts.unshift(`${tag}:${idx}`);
              n = n.parentElement;
              depth++;
            }
            return parts.join('>');
          };

          return anchors
            .filter(a => visible(a))
            .map(a => {
              const row = findRow(a);
              const ra = a.getBoundingClientRect();
              const rr = row.getBoundingClientRect();
              const rowText = norm(row.innerText || row.textContent || '');
              const anchorText = norm(a.innerText || a.textContent || '');
              const links = Array.from(row.querySelectorAll('a[href]')).map(x => ({
                href: x.href || '',
                text: norm(x.innerText || x.textContent || ''),
              }));

              return {
                href: a.href || '',
                row_key: nodePath(row),
                anchor_text: anchorText,
                row_text: rowText,
                row_top: rr.top + window.scrollY,
                row_left: rr.left + window.scrollX,
                a_top: ra.top + window.scrollY,
                a_left: ra.left + window.scrollX,
                viewport_width: window.innerWidth,
                links,
              };
            });
        }
        """
    )

    by_row = {}
    for item in raw:
        row_key = normalize_text(item.get("row_key", ""))
        if not row_key:
            row_key = f"top:{float(item.get('row_top', 0) or 0):.1f}"
        # Tránh đè nhầm row khi nodePath trùng nhau ở DOM lồng sâu.
        row_top_key = f"{float(item.get('row_top', 0) or 0):.1f}"
        stable_key = f"{row_key}|top:{row_top_key}"
        by_row.setdefault(stable_key, item)

    rows = []
    for item in by_row.values():
        row_text_full = normalize_text(item.get("row_text", ""))
        row_lines = [normalize_text(x) for x in row_text_full.splitlines() if normalize_text(x)]
        first_line = row_lines[0] if row_lines else ""
        viewport_width = float(item.get("viewport_width", 0) or 0)
        row_left = float(item.get("row_left", 0) or 0)

        # Chỉ lấy row chính trong khối kết quả, loại sidebar phải.
        if viewport_width > 0 and row_left > viewport_width * 0.72:
            continue
        has_numbered_line = any(re.match(r"^\d{1,4}\s+", ln) for ln in row_lines)
        has_nav_hint = any(nav in row_text_full for nav in ["Tổng quan", "VB liên quan", "Hiệu lực"])
        # Row kết quả thường có STT hoặc có cụm link điều hướng đặc trưng.
        if not has_numbered_line and not has_nav_hint:
            continue

        # Nếu cấu hình có required_luatvietnam_field_contains thì bắt buộc row phải chứa.
        required_fields = [normalize_text(x).lower() for x in get_required_field_contains(field) if normalize_text(x)]
        if required_fields:
            row_text_lower = row_text_full.lower()
            has_field_marker = "lĩnh vực" in row_text_lower
            if has_field_marker and not any(v in row_text_lower for v in required_fields):
                continue

        row_links = []
        for ln in item.get("links", []):
            href = normalize_url(urljoin(current_url, ln.get("href", "")))
            if not is_luatvietnam_document_url(href):
                continue
            if not url_matches_required_field_path(href, field):
                continue
            txt = normalize_text(ln.get("text", ""))
            row_links.append({"url": href, "text": txt})

        if not row_links:
            continue

        unique_by_url = {}
        for ln in row_links:
            if ln["url"] not in unique_by_url or len(ln["text"]) > len(unique_by_url[ln["url"]]["text"]):
                unique_by_url[ln["url"]] = ln
        row_links = list(unique_by_url.values())

        def link_score(link: dict) -> tuple:
            text = normalize_text(link.get("text", ""))
            nav_penalty = 0 if text not in NAV_LINK_TEXTS else -3
            doc_type = extract_doc_type_from_title(text)
            has_num = 1 if extract_doc_number_from_title(text) else 0
            return (nav_penalty + (2 if doc_type else 0) + has_num, len(text))

        primary = sorted(row_links, key=link_score, reverse=True)[0]
        title = normalize_text(primary.get("text", ""))

        if not title or title in NAV_LINK_TEXTS or len(title) < 10:
            texts = [normalize_text(item.get("anchor_text", ""))]
            for ln in row_links:
                t = normalize_text(ln.get("text", ""))
                if t and t not in texts and t not in NAV_LINK_TEXTS:
                    texts.append(t)
            row_text = normalize_text(item.get("row_text", ""))
            if row_text:
                lines = [normalize_text(x) for x in row_text.splitlines() if normalize_text(x)]
                for ln in lines[:3]:
                    if ln and ln not in NAV_LINK_TEXTS:
                        texts.append(ln)
            title = max(texts, key=len, default="")

        if not title:
            continue

        rows.append(
            {
                "url": primary["url"],
                "title_from_dom": title,
                "doc_type_from_dom": extract_doc_type_from_title(title),
                "doc_number_from_dom": extract_doc_number_from_title(title),
                "row_top": float(item.get("row_top", 0) or 0),
                "row_left": row_left,
            }
        )

    rows.sort(key=lambda x: (x["row_top"], x["row_left"], x["url"]))
    return rows


def pair_rows_with_urls(text_rows: list[dict], dom_rows: list[dict], field: dict) -> list[dict]:
    # Ưu tiên map theo index dòng để đảm bảo title đúng với link chính.
    tx = sorted(text_rows, key=lambda x: int(x.get("number", 10**9)))
    dm = sorted(dom_rows, key=lambda x: (float(x.get("row_top", 0)), float(x.get("row_left", 0))))

    result = []
    used_urls = set()
    for i in range(min(len(tx), len(dm))):
        title = normalize_text(tx[i].get("title_from_text", ""))
        row = dm[i]
        url = row.get("url", "")
        if not title or not url or url in used_urls:
            continue
        if not url_matches_required_field_path(url, field):
            continue

        doc_type = extract_doc_type_from_title(title) or row.get("doc_type_from_dom", "")
        doc_num = extract_doc_number_from_title(title) or row.get("doc_number_from_dom", "")

        result.append(
            {
                "url": url,
                "title_from_list": title,
                "doc_type_from_list": doc_type,
                "doc_number_from_list": doc_num,
                "row_number": tx[i].get("number", ""),
                "row_top": row.get("row_top", 0),
                "row_left": row.get("row_left", 0),
            }
        )
        used_urls.add(url)

    # fallback: thêm các URL còn thiếu từ DOM
    for row in dm:
        if row["url"] in used_urls:
            continue
        title = normalize_text(row.get("title_from_dom", ""))
        if not title:
            continue
        result.append(
            {
                "url": row["url"],
                "title_from_list": title,
                "doc_type_from_list": row.get("doc_type_from_dom", ""),
                "doc_number_from_list": row.get("doc_number_from_dom", ""),
                "row_number": "",
                "row_top": row.get("row_top", 0),
                "row_left": row.get("row_left", 0),
            }
        )

    result.sort(key=lambda x: (int(x.get("row_number", 10**9) or 10**9), x.get("row_top", 0), x["url"]))
    return result


def merge_document_results(document_lists: list[list[dict]], field: dict | None = None) -> list[dict]:
    by_url = {}
    for docs in document_lists:
        for doc in docs:
            url = doc.get("url", "")
            if not url:
                continue
            if field and not url_matches_required_field_path(url, field):
                continue
            if url not in by_url or len(normalize_text(doc.get("title_from_list", ""))) > len(normalize_text(by_url[url].get("title_from_list", ""))):
                by_url[url] = doc

    rows = list(by_url.values())
    rows.sort(key=lambda x: (int(x.get("row_number", 10**9) or 10**9), float(x.get("row_top", 0) or 0), x.get("url", "")))
    return rows


def wait_for_document_anchors(page, timeout_ms: int = 20000):
    try:
        page.wait_for_function(
            """
            () => Array.from(document.querySelectorAll('a[href]'))
              .some(a => /-d\\d+\\.html/i.test(a.href || ''))
            """,
            timeout=timeout_ms,
        )
    except Exception:
        pass


def scroll_page_to_trigger_lazy_load(page):
    try:
        page.evaluate(
            """
            async () => {
              const sleep = (ms) => new Promise(r => setTimeout(r, ms));
              const h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
              for (let y = 0; y <= Math.min(h, 9000); y += 300) {
                window.scrollTo(0, y);
                await sleep(90);
              }
              window.scrollTo(0, 0);
              await sleep(150);
            }
            """
        )
    except Exception:
        pass


def extract_document_links_from_page(page, current_url: str, field: dict) -> list[dict]:
    text_rows = extract_text_rows_from_page(page)
    dom_rows = extract_dom_document_rows(page, current_url, field)
    # Ưu tiên dữ liệu DOM theo row để tránh ghép sai title-url do index lệch.
    if dom_rows:
        result = [
            {
                "url": row.get("url", ""),
                "title_from_list": normalize_text(row.get("title_from_dom", "")),
                "doc_type_from_list": normalize_text(row.get("doc_type_from_dom", "")),
                "doc_number_from_list": normalize_text(row.get("doc_number_from_dom", "")),
                "row_number": "",
                "row_top": row.get("row_top", 0),
                "row_left": row.get("row_left", 0),
            }
            for row in dom_rows
            if row.get("url", "")
        ]
    else:
        result = pair_rows_with_urls(text_rows, dom_rows, field)
    print(f"Số dòng text: {len(text_rows)} | Số row DOM: {len(dom_rows)} | Số ghép được: {len(result)}")
    return result


def extract_document_links_fallback_all_anchors(page, current_url: str, field: dict) -> list[dict]:
    """Fallback: quét toàn bộ anchor document trong cột trái để bù link bị miss."""
    raw = page.locator("a").evaluate_all(
        """
        (elements) => elements.map(a => {
          const r = a.getBoundingClientRect();
          return {
            href: a.href || '',
            text: (a.innerText || a.textContent || '').trim(),
            title: (a.getAttribute('title') || '').trim(),
            aria: (a.getAttribute('aria-label') || '').trim(),
            top: r.top + window.scrollY,
            left: r.left + window.scrollX,
            vw: window.innerWidth,
          };
        })
        """
    )

    result = []
    for item in raw:
        url = normalize_url(urljoin(current_url, item.get("href", "")))
        if not is_luatvietnam_document_url(url):
            continue
        if not url_matches_required_field_path(url, field):
            continue
        left = float(item.get("left", 0) or 0)
        top = float(item.get("top", 0) or 0)
        vw = float(item.get("vw", 0) or 0)
        # Loại sidebar phải và phần header.
        if vw > 0 and left > vw * 0.75:
            continue
        if top < 220:
            continue

        title = normalize_text(item.get("text", "")) or normalize_text(item.get("title", "")) or normalize_text(item.get("aria", ""))
        if not title or title in NAV_LINK_TEXTS:
            continue

        result.append(
            {
                "url": url,
                "title_from_list": title,
                "doc_type_from_list": extract_doc_type_from_title(title),
                "doc_number_from_list": extract_doc_number_from_title(title),
                "row_number": "",
                "row_top": top,
                "row_left": left,
            }
        )

    return merge_document_results([result], field)


def extract_document_links_stable(page, current_url: str, field: dict, expected_count: int = 0, max_attempts: int = 8) -> list[dict]:
    """Chống mất ngẫu nhiên 1 link bằng hội tụ nhiều lần đọc.

    - đọc nhiều snapshot (không chỉ fixed lần),
    - dừng khi số URL ổn định >= 2 lần liên tiếp,
    - luôn merge theo URL thay vì cắt sớm.
    """
    all_attempts = []
    stable_count = 0
    last_len = -1

    for attempt in range(1, max_attempts + 1):
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass

        wait_for_document_anchors(page)
        try:
            scroll_y = max(0, (attempt - 1) * 700)
            page.evaluate("(y) => window.scrollTo(0, y)", scroll_y)
        except Exception:
            pass
        page.wait_for_timeout(500 + attempt * 180)

        docs = extract_document_links_from_page(page, current_url, field)
        all_attempts.append(docs)
        merged = merge_document_results(all_attempts, field)

        merged_len = len(merged)
        if merged_len == last_len:
            stable_count += 1
        else:
            stable_count = 0
        last_len = merged_len

        print(f"  Lần đọc {attempt}: {len(docs)} URL, gộp được {merged_len} URL")

        if expected_count > 0 and merged_len >= expected_count:
            return merged[:expected_count]

        if stable_count >= 2 and attempt >= 4:
            break

    try:
        page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        pass

    merged = merge_document_results(all_attempts, field)
    if expected_count > 0 and len(merged) > expected_count:
        return merged[:expected_count]
    return merged


def crawl_field_by_pageindex(page, field: dict, max_pages: int = 0) -> dict:
    ma_linh_vuc = field.get("ma_linh_vuc", "")
    ten_linh_vuc = field.get("ten_linh_vuc_luatvietnam", "")
    start_url = field.get("list_url", "")
    page_size = int(field.get("page_size", 20) or 20)

    if not start_url:
        return {
            "ma_linh_vuc": ma_linh_vuc,
            "ten_linh_vuc_luatvietnam": ten_linh_vuc,
            "list_url": start_url,
            "status": "skipped",
            "message": "Chưa cấu hình list_url.",
            "total_count_from_first_page": 0,
            "documents": [],
            "pages_crawled": [],
            "debug_pages": [],
        }

    documents, seen_urls, pages_crawled, debug_pages = [], set(), [], []
    filter_debug_stats = {
        "input_links": 0,
        "kept_links": 0,
        "duplicate_url": 0,
        "required_url_path_contains": 0,
        "doc_type": 0,
        "exclude_title_keywords": 0,
        "exclude_url_keywords": 0,
        "exclude_so_hieu_keywords": 0,
        "other": 0,
    }
    total_count_from_first_page = 0
    expected_total_pages = 0
    page_title = ""
    empty_streak = 0
    page_index = 1

    while True:
        if max_pages > 0 and page_index > max_pages:
            break
        if expected_total_pages > 0 and page_index > expected_total_pages + 1:
            break

        current_url = build_page_url(start_url, page_index, page_size)
        print(f"\n--- Trang {page_index}: {current_url}")
        safe_goto(page, current_url)
        page.wait_for_timeout(1500)

        if page_is_error_or_empty(page):
            print("Trang lỗi/rỗng. Dừng.")
            break
        if page_has_updating_message(page):
            print("Trang chỉ hiển thị 'Dữ liệu đang cập nhật.'. Bỏ qua và dừng nhánh crawl này.")
            pages_crawled.append(
                {
                    "page_index": page_index,
                    "url": current_url,
                    "title": page.title(),
                    "document_count": 0,
                    "new_document_count": 0,
                    "total_documents_so_far": len(documents),
                }
            )
            debug_pages.append(
                {
                    "page_index": page_index,
                    "url": current_url,
                    "page_title": page.title(),
                    "page_documents": [],
                    "filter_rejections": {
                        "duplicate_url": 0,
                        "required_url_path_contains": 0,
                        "doc_type": 0,
                        "exclude_title_keywords": 0,
                        "exclude_url_keywords": 0,
                        "exclude_so_hieu_keywords": 0,
                        "other": 0,
                    },
                    "skipped_reason": "du-lieu-dang-cap-nhat",
                }
            )
            break

        if page_index == 1:
            page_title = page.title()
            total_count_from_first_page = extract_total_count_from_page(page)
            if total_count_from_first_page:
                expected_total_pages = (total_count_from_first_page + page_size - 1) // page_size
                print(f"Tổng công bố: {total_count_from_first_page} | Dự kiến trang: {expected_total_pages}")

        expected_count_on_page = 0
        if total_count_from_first_page:
            remaining = total_count_from_first_page - len(documents)
            if remaining > 0:
                expected_count_on_page = min(page_size, remaining)

        page_documents = extract_document_links_stable(
            page,
            current_url,
            field,
            expected_count=expected_count_on_page,
            max_attempts=8,
        )
        if expected_count_on_page > 0 and len(page_documents) < expected_count_on_page:
            fallback_docs = extract_document_links_fallback_all_anchors(page, current_url, field)
            merged_with_fallback = merge_document_results([page_documents, fallback_docs], field)
            if len(merged_with_fallback) > len(page_documents):
                print(
                    f"  Fallback all-anchors: +{len(merged_with_fallback) - len(page_documents)} URL "
                    f"(từ {len(page_documents)} lên {len(merged_with_fallback)})"
                )
                page_documents = merged_with_fallback

        new_count = 0
        page_filter_rejections = {
            "duplicate_url": 0,
            "required_url_path_contains": 0,
            "doc_type": 0,
            "exclude_title_keywords": 0,
            "exclude_url_keywords": 0,
            "exclude_so_hieu_keywords": 0,
            "other": 0,
        }
        filters = get_filters(field)
        accepted_doc_types = filters.get("accepted_doc_types", []) or []
        skip_doc_types = filters.get("skip_doc_types", []) or []
        filter_debug_stats["input_links"] += len(page_documents)

        for doc in page_documents:
            url = doc.get("url", "")
            if not url or url in seen_urls:
                filter_debug_stats["duplicate_url"] += 1
                page_filter_rejections["duplicate_url"] += 1
                continue

            reject_reason = get_filter_reject_reason(
                doc=doc,
                field=field,
                accepted_doc_types=accepted_doc_types,
                skip_doc_types=skip_doc_types,
            )
            if reject_reason:
                if reject_reason in filter_debug_stats:
                    filter_debug_stats[reject_reason] += 1
                else:
                    filter_debug_stats["other"] += 1
                if reject_reason in page_filter_rejections:
                    page_filter_rejections[reject_reason] += 1
                else:
                    page_filter_rejections["other"] += 1
                continue

            doc_type = normalize_text(doc.get("doc_type_from_list", ""))
            if not doc_type:
                doc_type = extract_doc_type_from_title(doc.get("title_from_list", ""))

            seen_urls.add(url)
            documents.append(
                {
                    "ma_linh_vuc": ma_linh_vuc,
                    "ten_linh_vuc_luatvietnam": ten_linh_vuc,
                    "url": url,
                    "title_from_list": doc.get("title_from_list", ""),
                    "doc_type_from_list": doc_type,
                    "doc_number_from_list": normalize_text(doc.get("doc_number_from_list", "")),
                    "source_list_url": current_url,
                    "root_list_url": start_url,
                    "crawl_doc_type_id": field.get("crawl_doc_type_id", ""),
                    "page_index": page_index,
                    "collected_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                }
            )
            new_count += 1
            filter_debug_stats["kept_links"] += 1

        pages_crawled.append(
            {
                "page_index": page_index,
                "url": current_url,
                "title": page_title,
                "document_count": len(page_documents),
                "new_document_count": new_count,
                "total_documents_so_far": len(documents),
            }
        )
        debug_pages.append(
            {
                "page_index": page_index,
                "url": current_url,
                "page_title": page_title,
                "page_documents": page_documents,
                "filter_rejections": page_filter_rejections,
            }
        )

        print(f"Trang này: {len(page_documents)} | mới: {new_count} | lũy kế: {len(documents)}")

        if len(page_documents) == 0:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0

        if total_count_from_first_page and len(documents) >= total_count_from_first_page and page_index >= expected_total_pages + 1:
            break

        page_index += 1

    return {
        "ma_linh_vuc": ma_linh_vuc,
        "ten_linh_vuc_luatvietnam": ten_linh_vuc,
        "list_url": start_url,
        "status": "success",
        "message": "",
        "total_count_from_first_page": total_count_from_first_page,
        "documents": documents,
        "pages_crawled": pages_crawled,
        "debug_pages": debug_pages,
        "filter_debug_stats": filter_debug_stats,
    }


def build_readable_report(result: dict) -> str:
    lines = [
        "=" * 80,
        "BÁO CÁO BƯỚC 07 - CRAWL URL VĂN BẢN THEO LĨNH VỰC",
        "=" * 80,
        "",
        f"Thời gian chạy: {result.get('created_at', '')}",
        f"Run mode: {result.get('run_mode', '')}",
        f"Tổng số lĩnh vực đã xử lý: {len(result.get('fields', []))}",
        f"Tổng số URL văn bản: {result.get('total_documents', 0)}",
        "",
    ]
    for field_result in result.get("fields", []):
        docs = field_result.get("documents", [])
        pages = field_result.get("pages_crawled", [])
        filter_stats = field_result.get("filter_debug_stats", {}) or {}
        lines.extend(
            [
                "-" * 80,
                f"Lĩnh vực: {field_result.get('ten_linh_vuc_luatvietnam', '')}",
                f"Mã lĩnh vực: {field_result.get('ma_linh_vuc', '')}",
                f"Trạng thái: {field_result.get('status', '')}",
                f"Số văn bản công bố trên trang đầu: {field_result.get('total_count_from_first_page', 0)}",
                f"Số trang đã crawl: {len(pages)}",
                f"Số URL văn bản thu được: {len(docs)}",
                "",
            ]
        )
        if filter_stats:
            lines.extend(
                [
                    "THỐNG KÊ FILTER DEBUG",
                    "-" * 80,
                    f"Input links: {filter_stats.get('input_links', 0)}",
                    f"Kept links: {filter_stats.get('kept_links', 0)}",
                    f"Rejected duplicate_url: {filter_stats.get('duplicate_url', 0)}",
                    f"Rejected required_url_path_contains: {filter_stats.get('required_url_path_contains', 0)}",
                    f"Rejected doc_type: {filter_stats.get('doc_type', 0)}",
                    f"Rejected exclude_title_keywords: {filter_stats.get('exclude_title_keywords', 0)}",
                    f"Rejected exclude_url_keywords: {filter_stats.get('exclude_url_keywords', 0)}",
                    f"Rejected exclude_so_hieu_keywords: {filter_stats.get('exclude_so_hieu_keywords', 0)}",
                    f"Rejected other: {filter_stats.get('other', 0)}",
                    "",
                ]
            )
        lines.extend(["CHI TIẾT THEO TRANG", "-" * 80])
        for page_info in pages:
            lines.append(
                f"Trang {page_info.get('page_index')}: {page_info.get('document_count')} URL, {page_info.get('new_document_count')} URL mới, lũy kế {page_info.get('total_documents_so_far')}"
            )
            lines.append(f"URL: {page_info.get('url', '')}")
            lines.append("")

        lines.extend(["DANH SÁCH URL", "-" * 80])
        for idx, doc in enumerate(docs, start=1):
            lines.append(f"{idx}. {doc.get('title_from_list') or '(không có tiêu đề)'}")
            lines.append(f"   Loại nhận diện: {doc.get('doc_type_from_list', '')}")
            lines.append(f"   Số hiệu nhận diện: {doc.get('doc_number_from_list', '')}")
            lines.append(f"   Trang nguồn: {doc.get('page_index', '')}")
            lines.append(f"   URL: {doc.get('url', '')}")
            lines.append("")
    return "\n".join(lines)


def normalize_field_configs(config: dict) -> list[dict]:
    fields = config.get("luatvietnam_fields", [])
    if not fields and config.get("ma_linh_vuc"):
        fields = [config]
    enabled = [field for field in fields if field.get("enabled") is True]

    expanded = []
    for field in enabled:
        filters = field.get("filters", {}) or {}
        doc_type_ids = filters.get("doc_type_ids_to_crawl", []) or []

        # Tự suy ra DocTypeId từ accepted_doc_types nếu chưa khai báo riêng.
        if not doc_type_ids:
            accepted_doc_types = filters.get("accepted_doc_types", []) or []
            inferred = []
            for t in accepted_doc_types:
                v = DOC_TYPE_NAME_TO_ID.get(str(t or "").strip(), "")
                if v and v not in inferred:
                    inferred.append(v)
            doc_type_ids = inferred

        # Nếu có danh sách DocTypeId, tách thành nhiều field con để crawl riêng.
        if doc_type_ids:
            for doc_type_id in doc_type_ids:
                cloned = dict(field)
                cloned["list_url"] = set_query_param(field.get("list_url", ""), "DocTypeId", str(doc_type_id))
                cloned["crawl_doc_type_id"] = str(doc_type_id)
                expanded.append(cloned)
        else:
            expanded.append(field)

    return expanded


def main():
    configure_console_encoding()

    if not AUTH_FILE.exists():
        raise FileNotFoundError("Chưa tìm thấy file auth/luatvietnam_state.json. Hãy chạy 01_save_session.py trước.")

    config = load_json(CONFIG_FILE)
    max_pages = int(config.get("max_pages_per_field", 0) or 0)
    max_documents_per_run = int(config.get("max_documents_per_run", 0) or 0)
    enabled_fields = normalize_field_configs(config)
    if not enabled_fields:
        raise ValueError("Chưa có lĩnh vực nào enabled=true trong config/scan_config.json.")

    all_field_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=80)
        context = browser.new_context(storage_state=str(AUTH_FILE))
        page = context.new_page()

        for field in enabled_fields:
            all_field_results.append(crawl_field_by_pageindex(page=page, field=field, max_pages=max_pages))

        browser.close()

    all_documents, debug_fields = [], []
    for field_result in all_field_results:
        all_documents.extend(field_result.get("documents", []))
        debug_fields.append(
            {
                "ma_linh_vuc": field_result.get("ma_linh_vuc", ""),
                "ten_linh_vuc_luatvietnam": field_result.get("ten_linh_vuc_luatvietnam", ""),
                "filter_debug_stats": field_result.get("filter_debug_stats", {}),
                "debug_pages": field_result.get("debug_pages", []),
            }
        )

    unique_documents, seen_urls = [], set()
    for doc in all_documents:
        url = doc.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_documents.append(doc)

    if max_documents_per_run > 0 and len(unique_documents) > max_documents_per_run:
        unique_documents = unique_documents[:max_documents_per_run]

    public_field_results = []
    for field_result in all_field_results:
        copied = dict(field_result)
        copied.pop("debug_pages", None)
        public_field_results.append(copied)

    result = {
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "run_mode": config.get("run_mode", ""),
        "crawl_strategy": config.get("crawl_strategy", "list_url_pageindex"),
        "max_pages_per_field": max_pages,
        "max_documents_per_run": max_documents_per_run,
        "total_documents": len(unique_documents),
        "documents": unique_documents,
        "fields": public_field_results,
    }

    debug_result = {"created_at": result["created_at"], "fields": debug_fields}
    save_json(OUTPUT_FILE, result)
    save_json(OUTPUT_DEBUG_FILE, debug_result)
    save_text(OUTPUT_READABLE_FILE, build_readable_report(result))

    print("\n" + "=" * 80)
    print("BƯỚC 07 HOÀN THÀNH")
    print("=" * 80)
    print(f"Tổng URL văn bản sau khi lọc trùng: {len(unique_documents)}")
    print(f"Đã lưu JSON vào: {OUTPUT_FILE}")
    print(f"Đã lưu báo cáo dễ đọc vào: {OUTPUT_READABLE_FILE}")
    print(f"Đã lưu debug vào: {OUTPUT_DEBUG_FILE}")


if __name__ == "__main__":
    main()
from pathlib import Path
import json
import math
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

CONFIG_FILE = Path("config/scan_config.json")

OUTPUT_FILE = Path("output/field_document_urls.json")
OUTPUT_READABLE_FILE = Path("output/field_document_urls_readable.txt")
OUTPUT_DEBUG_FILE = Path("output/field_document_urls_debug.json")

BASE_URL = "https://luatvietnam.vn/van-ban-moi.html"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE_URL,
}
REQUEST_TIMEOUT = 30
REQUEST_MAX_ATTEMPTS = 3

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

# Best-effort, CHỈ để gắn nhãn hiển thị — không dùng để loại bỏ văn bản.
# Lý do: 1 văn bản có thể được gắn nhiều FieldIds cùng lúc trong khi URL
# chỉ phản ánh 1 path chính (đã kiểm chứng thực nghiệm 31/07/2026, ví dụ
# văn bản khớp FieldIds=40 Kế toán-Kiểm toán lại nằm ở path /doanh-nghiep/).
FIELD_SLUG_TO_NAME = {
    "dau-tu": "Đầu tư",
    "doanh-nghiep": "Doanh nghiệp",
    "giao-duc": "Giáo dục-Đào tạo-Dạy nghề",
    "ke-toan": "Kế toán-Kiểm toán",
    "lao-dong": "Lao động-Tiền lương",
    "so-huu-tri-tue": "Sở hữu trí tuệ",
    "thue": "Thuế-Phí-Lệ phí",
    "xay-dung": "Xây dựng",
    "y-te": "Y tế-Sức khỏe",
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
    return parsed._replace(fragment="").geturl().rstrip("/")


def extract_doc_number_from_title(title: str) -> str:
    matches = DOC_NUMBER_PATTERN.findall(normalize_text(title))
    return matches[0].strip() if matches else ""


def extract_doc_type_from_title(title: str) -> str:
    title = normalize_text(title)
    title = re.sub(r"^\s*\d{1,4}\s*[\.\)\-:]\s*", "", title)

    for prefix in DOC_TYPE_PREFIXES:
        if title.lower().startswith(prefix.lower()):
            return prefix

    for prefix in DOC_TYPE_PREFIXES:
        if re.search(rf"\b{re.escape(prefix)}\b", title, flags=re.IGNORECASE):
            return prefix
    return ""


def guess_field_from_url(url: str) -> tuple[str, str]:
    path = urlparse(url).path.strip("/").lower()
    slug = path.split("/", 1)[0] if path else ""
    name = FIELD_SLUG_TO_NAME.get(slug, "")
    return (slug if name else "", name)


def build_query_params(ajax_params: dict, page_index: int, page_size: int) -> list[tuple[str, str]]:
    field_ids = ajax_params.get("field_ids", []) or []
    doc_type_ids = ajax_params.get("doc_type_ids", []) or []
    organ_ids = ajax_params.get("organ_ids", []) or []
    effect_status_ids = ajax_params.get("effect_status_ids", []) or []

    # QUAN TRỌNG: FieldIds/DocTypeIds/OrganIds phải nối phẩy 1 tham số duy nhất
    # (server chỉ bind giá trị ĐẦU TIÊN nếu lặp key=value nhiều lần — đã kiểm
    # chứng thực nghiệm: lặp 9 FieldIds cho kết quả giống hệt chỉ truyền 1 ID).
    # Ngược lại, EffectStatusIds PHẢI lặp tham số — nối phẩy bị server bỏ qua
    # hoàn toàn (kết quả xấp xỉ không lọc gì).
    params = [
        ("PageIndex", str(page_index)),
        ("PageSize", str(page_size)),
        ("ShowSapo", str(ajax_params.get("show_sapo", 0))),
        ("orderBy", str(ajax_params.get("order_by", 0))),
        ("OrganIds", ",".join(str(x) for x in organ_ids)),
        ("FieldIds", ",".join(str(x) for x in field_ids)),
        ("DocTypeIds", ",".join(str(x) for x in doc_type_ids)),
    ]
    for status_id in effect_status_ids:
        params.append(("EffectStatusIds", str(status_id)))
    return params


def fetch_page(session: requests.Session, ajax_params: dict, page_index: int, page_size: int) -> str:
    params = build_query_params(ajax_params, page_index, page_size)
    last_error = None
    for attempt in range(1, REQUEST_MAX_ATTEMPTS + 1):
        try:
            resp = session.get(BASE_URL, params=params, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last_error = exc
            print(f"  Lỗi request trang {page_index} (lần {attempt}/{REQUEST_MAX_ATTEMPTS}): {exc}")
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"Không tải được trang {page_index} sau {REQUEST_MAX_ATTEMPTS} lần thử: {last_error}")


def parse_total_record(soup: BeautifulSoup) -> int:
    # Trang đầy đủ van-ban-moi.html dùng data-role="total-record" (không có
    # tiền tố "docs-") và PHẢN ÁNH ĐÚNG tổng số đã lọc theo query hiện tại —
    # đã kiểm chứng thực nghiệm 31/07/2026 (không lọc = 1543, lọc đủ tham số = 28).
    node = soup.select_one('[data-role="total-record"]')
    if not node:
        return 0
    raw = normalize_text(node.get_text()).replace(".", "").replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return 0


def parse_articles(soup: BeautifulSoup, page_index: int) -> list[dict]:
    documents = []
    for article in soup.select("article.doc-article"):
        # Bài đầu tiên dùng <h2 class="doc-title">, các bài sau dùng <h3> — khớp theo class, bỏ ràng buộc tên thẻ.
        link = article.select_one(".doc-title a[href]")
        if not link:
            continue
        url = normalize_url(urljoin(BASE_URL, link.get("href", "")))
        if not url:
            continue

        title = normalize_text(link.get_text()) or normalize_text(link.get("title", ""))
        if not title:
            continue

        ma_linh_vuc, ten_linh_vuc = guess_field_from_url(url)

        documents.append(
            {
                "url": url,
                "title_from_list": title,
                "doc_type_from_list": extract_doc_type_from_title(title),
                "doc_number_from_list": extract_doc_number_from_title(title),
                "ma_linh_vuc": ma_linh_vuc,
                "ten_linh_vuc_luatvietnam": ten_linh_vuc,
                "page_index": page_index,
            }
        )
    return documents


def get_filter_reject_reason(doc: dict, accepted_doc_types: list[str], skip_doc_types: list[str], filters: dict) -> str:
    doc_type = normalize_text(doc.get("doc_type_from_list", ""))
    if accepted_doc_types and (not doc_type or doc_type not in accepted_doc_types):
        return "doc_type"
    if skip_doc_types and doc_type in skip_doc_types:
        return "doc_type"

    title = normalize_text(doc.get("title_from_list", "")).lower()
    url_lower = normalize_text(doc.get("url", "")).lower()
    so_hieu = normalize_text(doc.get("doc_number_from_list", "")).lower()

    for kw in filters.get("exclude_title_keywords", []) or []:
        if kw and kw.lower() in title:
            return "exclude_title_keywords"
    for kw in filters.get("exclude_url_keywords", []) or []:
        if kw and kw.lower() in url_lower:
            return "exclude_url_keywords"
    for kw in filters.get("exclude_so_hieu_keywords", []) or []:
        if kw and kw.lower() in so_hieu:
            return "exclude_so_hieu_keywords"
    return ""


def crawl_ajax(session: requests.Session, config: dict) -> dict:
    ajax_params = config.get("ajax_search_params", {}) or {}
    page_size = int(config.get("page_size", 20) or 20)
    max_pages = int(config.get("max_pages_per_field", 0) or 0)
    filters = config.get("filters", {}) or {}
    accepted_doc_types = filters.get("accepted_doc_types", []) or []
    skip_doc_types = filters.get("skip_doc_types", []) or []
    crawl_doc_type_id = ",".join(str(x) for x in ajax_params.get("doc_type_ids", []) or [])

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
    empty_streak = 0
    page_index = 1

    while True:
        if max_pages > 0 and page_index > max_pages:
            break
        if expected_total_pages > 0 and page_index > expected_total_pages:
            break

        print(f"\n--- Trang {page_index} (FieldIds={ajax_params.get('field_ids')}, DocTypeIds={ajax_params.get('doc_type_ids')})")
        html = fetch_page(session, ajax_params, page_index, page_size)
        soup = BeautifulSoup(html, "lxml")

        if page_index == 1:
            total_count_from_first_page = parse_total_record(soup)
            if total_count_from_first_page:
                expected_total_pages = math.ceil(total_count_from_first_page / page_size)
                print(f"Tổng công bố: {total_count_from_first_page} | Dự kiến trang: {expected_total_pages}")

        page_documents = parse_articles(soup, page_index)
        filter_debug_stats["input_links"] += len(page_documents)

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

        for doc in page_documents:
            url = doc.get("url", "")
            if not url or url in seen_urls:
                filter_debug_stats["duplicate_url"] += 1
                page_filter_rejections["duplicate_url"] += 1
                continue

            reject_reason = get_filter_reject_reason(doc, accepted_doc_types, skip_doc_types, filters)
            if reject_reason:
                filter_debug_stats[reject_reason] = filter_debug_stats.get(reject_reason, 0) + 1
                page_filter_rejections[reject_reason] = page_filter_rejections.get(reject_reason, 0) + 1
                continue

            seen_urls.add(url)
            documents.append(
                {
                    **doc,
                    "source_list_url": BASE_URL,
                    "root_list_url": BASE_URL,
                    "crawl_doc_type_id": crawl_doc_type_id,
                    "collected_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                }
            )
            new_count += 1
            filter_debug_stats["kept_links"] += 1

        pages_crawled.append(
            {
                "page_index": page_index,
                "url": BASE_URL,
                "title": "Văn bản mới",
                "document_count": len(page_documents),
                "new_document_count": new_count,
                "total_documents_so_far": len(documents),
            }
        )
        debug_pages.append(
            {
                "page_index": page_index,
                "url": BASE_URL,
                "page_title": "Văn bản mới",
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

        if not expected_total_pages and len(page_documents) == 0:
            break

        page_index += 1

    return {
        "ma_linh_vuc": config.get("ma_linh_vuc", []),
        "ten_linh_vuc_luatvietnam": config.get("ten_linh_vuc_luatvietnam", []),
        "list_url": BASE_URL,
        "crawl_doc_type_id": crawl_doc_type_id,
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
        "BÁO CÁO BƯỚC 07 - CRAWL URL VĂN BẢN (DocsNewestAjax / van-ban-moi.html)",
        "=" * 80,
        "",
        f"Thời gian chạy: {result.get('created_at', '')}",
        f"Run mode: {result.get('run_mode', '')}",
        f"Tổng số nhánh crawl: {len(result.get('fields', []))}",
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
                f"DocTypeIds: {field_result.get('crawl_doc_type_id', '')}",
                f"Trạng thái: {field_result.get('status', '')}",
                f"Số văn bản công bố (docs-total-record): {field_result.get('total_count_from_first_page', 0)}",
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
        lines.append("")

        lines.extend(["DANH SÁCH URL", "-" * 80])
        for idx, doc in enumerate(docs, start=1):
            lines.append(f"{idx}. {doc.get('title_from_list') or '(không có tiêu đề)'}")
            lines.append(f"   Loại nhận diện: {doc.get('doc_type_from_list', '')}")
            lines.append(f"   Số hiệu nhận diện: {doc.get('doc_number_from_list', '')}")
            lines.append(f"   Lĩnh vực (best-effort theo URL): {doc.get('ten_linh_vuc_luatvietnam', '')}")
            lines.append(f"   Trang nguồn: {doc.get('page_index', '')}")
            lines.append(f"   URL: {doc.get('url', '')}")
            lines.append("")
    return "\n".join(lines)


def main():
    configure_console_encoding()

    config = load_json(CONFIG_FILE)
    if not config.get("enabled", False):
        raise ValueError("enabled=false trong config/scan_config.json — không có gì để crawl.")
    if not config.get("ajax_search_params"):
        raise ValueError("Chưa cấu hình ajax_search_params trong config/scan_config.json.")

    session = requests.Session()
    field_result = crawl_ajax(session, config)

    all_documents = field_result.get("documents", [])
    max_documents_per_run = int(config.get("max_documents_per_run", 0) or 0)

    unique_documents, seen_urls = [], set()
    for doc in all_documents:
        url = doc.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_documents.append(doc)

    if max_documents_per_run > 0 and len(unique_documents) > max_documents_per_run:
        unique_documents = unique_documents[:max_documents_per_run]

    debug_field_result = {
        "ma_linh_vuc": field_result.get("ma_linh_vuc", []),
        "ten_linh_vuc_luatvietnam": field_result.get("ten_linh_vuc_luatvietnam", []),
        "filter_debug_stats": field_result.get("filter_debug_stats", {}),
        "debug_pages": field_result.get("debug_pages", []),
    }
    public_field_result = dict(field_result)
    public_field_result.pop("debug_pages", None)

    result = {
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "run_mode": config.get("run_mode", ""),
        "crawl_strategy": config.get("crawl_strategy", "ajax_docsnewest_pageindex"),
        "max_pages_per_field": int(config.get("max_pages_per_field", 0) or 0),
        "max_documents_per_run": max_documents_per_run,
        "total_documents": len(unique_documents),
        "documents": unique_documents,
        "fields": [public_field_result],
    }

    debug_result = {"created_at": result["created_at"], "fields": [debug_field_result]}
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

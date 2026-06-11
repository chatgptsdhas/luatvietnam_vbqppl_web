from pathlib import Path
import json
import sys
from datetime import datetime
from urllib.parse import urlparse



CONFIG_FILE = Path("config/scan_config.json")

STEP07_FILE = Path("output/field_document_urls.json")
STEP07_DEBUG_FILE = Path("output/field_document_urls_debug.json")

STEP08_FILE = Path("output/vbqppl_nhap_batch_payload.json")
STEP08_REQUEST_DEBUG_FILE = Path("output/apps_script_request_debug.json")

OUTPUT_REPORT_TXT = Path("output/step09_validation_report.txt")
OUTPUT_REPORT_JSON = Path("output/step09_validation_report.json")

MISSING_REFS_SNAPSHOT_FILE = Path("output/step09_missing_refs_snapshot.json")
MISSING_REFS_HISTORY_FILE = Path("output/step09_missing_refs_history.json") 

CONFIRMED_DOC_TYPE_IDS = {"21", "11", "10", "58"}

ALLOWED_DOC_TYPES_DEFAULT = {
    "Bộ luật",
    "Luật",
    "Nghị định",
    "Thông tư",
}

SKIP_DOC_TYPES_DEFAULT = {
    "Chỉ thị",
    "Quyết định",
    "Văn bản hợp nhất",
    "Công văn",
}

BLOCKED_URL_KEYWORDS_DEFAULT = [
    "dat-dai",
    "hinh-su",
    "ke-hoach",
    "quyet-dinh",
    "cong-van",
    "chi-thi",
    "van-ban-hop-nhat",
    "vbhn",
]


def load_json(path: Path, required: bool = True) -> dict:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Không tìm thấy file: {path}")
        return {}

    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def normalize_text(value) -> str:
    return str(value or "").strip()

def setup_utf8_stdio():
    """
    Ép stdout/stderr sang UTF-8 để tránh UnicodeEncodeError
    khi in tiếng Việt trên Windows PowerShell/CMD.
    """
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def normalize_doc_number_for_tracking(value: str) -> str:
    text = normalize_text(value).upper()

    if not text:
        return ""

    replacements = {
        "Đ": "D",
        "đ": "d",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = (
        text.replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace("‐", "-")
    )

    text = text.replace(" ", "")
    text = text.replace(".", "")

    return text

def clean_keyword(value: str) -> str:
    """
    Làm sạch keyword từ config.

    Ví dụ:
    - "ke-hoach;" -> "ke-hoach"
    - "/giao-duc/" -> "giao-duc" nếu dùng cho so sánh token path
    """
    text = normalize_text(value).lower()
    text = text.strip()
    text = text.strip(";")
    return text


def clean_path_token(value: str) -> str:
    text = clean_keyword(value)
    text = text.strip("/")
    return text


def get_filters(config: dict) -> dict:
    return config.get("filters", {}) or {}


def get_accepted_doc_types(config: dict) -> set[str]:
    filters = get_filters(config)
    values = filters.get("accepted_doc_types", []) or []

    result = {
        normalize_text(item)
        for item in values
        if normalize_text(item)
    }

    return result or set(ALLOWED_DOC_TYPES_DEFAULT)


def get_skip_doc_types(config: dict) -> set[str]:
    filters = get_filters(config)
    values = filters.get("skip_doc_types", []) or []

    result = {
        normalize_text(item)
        for item in values
        if normalize_text(item)
    }

    return result or set(SKIP_DOC_TYPES_DEFAULT)


def get_required_path_tokens(config: dict) -> list[str]:
    filters = get_filters(config)

    return [
        clean_path_token(item)
        for item in filters.get("required_url_path_contains", []) or []
        if clean_path_token(item)
    ]


def get_exclude_path_tokens(config: dict) -> list[str]:
    filters = get_filters(config)

    return [
        clean_path_token(item)
        for item in filters.get("exclude_url_path_contains", []) or []
        if clean_path_token(item)
    ]


def get_exclude_url_keywords(config: dict) -> list[str]:
    filters = get_filters(config)

    result = []

    for item in BLOCKED_URL_KEYWORDS_DEFAULT:
        keyword = clean_keyword(item)
        if keyword and keyword not in result:
            result.append(keyword)

    for item in filters.get("exclude_url_keywords", []) or []:
        keyword = clean_keyword(item)
        if keyword and keyword not in result:
            result.append(keyword)

    return result


def get_exclude_title_keywords(config: dict) -> list[str]:
    filters = get_filters(config)

    return [
        clean_keyword(item)
        for item in filters.get("exclude_title_keywords", []) or []
        if clean_keyword(item)
    ]


def get_exclude_so_hieu_keywords(config: dict) -> list[str]:
    filters = get_filters(config)

    return [
        normalize_text(item).upper()
        for item in filters.get("exclude_so_hieu_keywords", []) or []
        if normalize_text(item)
    ]


def get_url_path(url: str) -> str:
    try:
        return urlparse(normalize_text(url)).path.lower()
    except Exception:
        return ""


def normalized_path_with_slashes(url: str) -> str:
    path = get_url_path(url)
    return "/" + path.strip("/") + "/"


def url_matches_required_paths(url: str, config: dict) -> bool:
    required_tokens = get_required_path_tokens(config)

    if not required_tokens:
        return True

    path = normalized_path_with_slashes(url)

    for token in required_tokens:
        if f"/{token}/" in path:
            return True

    return False


def url_matches_excluded_paths(url: str, config: dict) -> str:
    excluded_tokens = get_exclude_path_tokens(config)
    path = normalized_path_with_slashes(url)

    for token in excluded_tokens:
        if f"/{token}/" in path:
            return token

    return ""


def url_contains_blocked_keyword(url: str, config: dict) -> str:
    url_lower = normalize_text(url).lower()

    for keyword in get_exclude_url_keywords(config):
        if keyword and keyword in url_lower:
            return keyword

    return ""


def title_contains_excluded_keyword(title: str, config: dict) -> str:
    title_lower = normalize_text(title).lower()

    for keyword in get_exclude_title_keywords(config):
        if keyword and keyword in title_lower:
            return keyword

    return ""


def so_hieu_contains_excluded_keyword(so_hieu: str, config: dict) -> str:
    value = normalize_text(so_hieu).upper()

    for keyword in get_exclude_so_hieu_keywords(config):
        if keyword and keyword in value:
            return keyword

    return ""


def get_nested(data: dict, keys: list[str], default=None):
    current = data

    for key in keys:
        if not isinstance(current, dict):
            return default

        if key not in current:
            return default

        current = current.get(key)

    return current


def validate_config(config: dict) -> tuple[list[dict], list[dict]]:
    """
    Trả về:
    - config_errors: lỗi cấu hình nên sửa trước khi coi pipeline đạt
    - config_warnings: cảnh báo không nhất thiết làm pipeline fail
    """
    errors = []
    warnings = []

    filters = get_filters(config)

    raw_doc_type_ids = filters.get("doc_type_ids_to_crawl", []) or []
    doc_type_ids = {
        str(item).strip()
        for item in raw_doc_type_ids
        if str(item).strip()
    }

    if doc_type_ids != CONFIRMED_DOC_TYPE_IDS:
        missing = sorted(CONFIRMED_DOC_TYPE_IDS - doc_type_ids)
        extra = sorted(doc_type_ids - CONFIRMED_DOC_TYPE_IDS)

        msg_parts = [
            "doc_type_ids_to_crawl chưa đúng bộ ID đã xác nhận [21, 11, 10, 58]."
        ]

        if missing:
            msg_parts.append(f"Thiếu: {missing}.")

        if extra:
            msg_parts.append(f"Thừa/chưa xác nhận: {extra}.")

        errors.append({
            "code": "CONFIG_DOC_TYPE_IDS_NOT_MATCH_CONFIRMED_SET",
            "message": " ".join(msg_parts),
        })

    accepted_doc_types = get_accepted_doc_types(config)
    missing_doc_types = sorted(ALLOWED_DOC_TYPES_DEFAULT - accepted_doc_types)

    if missing_doc_types:
        errors.append({
            "code": "CONFIG_ACCEPTED_DOC_TYPES_MISSING",
            "message": (
                "accepted_doc_types đang thiếu loại văn bản cần xử lý: "
                + ", ".join(missing_doc_types)
            ),
        })

    for keyword in filters.get("exclude_url_keywords", []) or []:
        raw = normalize_text(keyword)

        if raw.endswith(";"):
            errors.append({
                "code": "CONFIG_EXCLUDE_URL_KEYWORD_HAS_SEMICOLON",
                "message": (
                    f"exclude_url_keywords có dấu ';' ở cuối: {raw}. "
                    f"Hãy sửa thành: {clean_keyword(raw)}"
                ),
            })

    if not config.get("run_mode"):
        warnings.append({
            "code": "CONFIG_RUN_MODE_EMPTY",
            "message": "run_mode đang rỗng hoặc không có. Nên đặt để dễ truy vết log.",
        })

    return errors, warnings


def classify_step07_document(doc: dict, config: dict) -> tuple[list[str], list[str]]:
    """
    Phân loại vấn đề của 1 document từ Step07.

    Return:
    - errors
    - warnings
    """
    errors = []
    warnings = []

    title = normalize_text(doc.get("title_from_list", ""))
    doc_type = normalize_text(doc.get("doc_type_from_list", ""))
    doc_number = normalize_text(doc.get("doc_number_from_list", ""))
    url = normalize_text(doc.get("url", ""))

    accepted_doc_types = get_accepted_doc_types(config)
    skip_doc_types = get_skip_doc_types(config)

    if not url:
        errors.append("Thiếu URL.")
        return errors, warnings

    excluded_path = url_matches_excluded_paths(url, config)
    if excluded_path:
        errors.append(f"URL thuộc path loại trừ: {excluded_path}.")

    if not url_matches_required_paths(url, config):
        errors.append("URL không thuộc required_url_path_contains.")

    blocked_keyword = url_contains_blocked_keyword(url, config)
    if blocked_keyword:
        errors.append(f"URL chứa keyword bị chặn: {blocked_keyword}.")

    title_keyword = title_contains_excluded_keyword(title, config)
    if title_keyword:
        errors.append(f"Tiêu đề chứa keyword loại trừ: {title_keyword}.")

    so_hieu_keyword = so_hieu_contains_excluded_keyword(doc_number, config)
    if so_hieu_keyword:
        errors.append(f"Số hiệu chứa keyword loại trừ: {so_hieu_keyword}.")

    if doc_type in skip_doc_types:
        errors.append(f"Loại văn bản thuộc skip_doc_types: {doc_type}.")

    if doc_type and doc_type not in accepted_doc_types:
        errors.append(f"Loại văn bản không thuộc accepted_doc_types: {doc_type}.")

    if not doc_type:
        warnings.append("Step07 thiếu doc_type_from_list.")

    if not doc_number:
        warnings.append("Step07 thiếu doc_number_from_list.")

    if not title:
        warnings.append("Step07 thiếu title_from_list.")

    return errors, warnings


def summarize_step07(step07_data: dict, step07_debug: dict, config: dict) -> dict:
    documents = step07_data.get("documents", []) or []
    fields = step07_data.get("fields", []) or []

    invalid_items = []
    warning_items = []

    for doc in documents:
        errors, warnings = classify_step07_document(doc, config)

        if errors:
            copied = dict(doc)
            copied["_errors"] = errors
            invalid_items.append(copied)

        if warnings:
            copied = dict(doc)
            copied["_warnings"] = warnings
            warning_items.append(copied)

    filter_stats_by_branch = []

    for field in fields:
        stats = field.get("filter_debug_stats", {}) or {}

        filter_stats_by_branch.append({
            "ma_linh_vuc": field.get("ma_linh_vuc", ""),
            "ten_linh_vuc_luatvietnam": field.get("ten_linh_vuc_luatvietnam", ""),
            "crawl_doc_type_id": field.get("crawl_doc_type_id", ""),
            "total_count_from_first_page": field.get("total_count_from_first_page", 0),
            "documents_count": len(field.get("documents", []) or []),
            "pages_crawled_count": len(field.get("pages_crawled", []) or []),
            "filter_debug_stats": stats,
        })

    debug_pages_count = 0
    debug_page_documents_count = 0
    debug_pages_with_zero_documents = []

    for field in step07_debug.get("fields", []) or []:
        field_debug_pages = field.get("debug_pages", []) or []
        debug_pages_count += len(field_debug_pages)

        for page in field_debug_pages:
            page_documents = page.get("page_documents", []) or []
            debug_page_documents_count += len(page_documents)

            if len(page_documents) == 0:
                debug_pages_with_zero_documents.append({
                    "ma_linh_vuc": field.get("ma_linh_vuc", ""),
                    "ten_linh_vuc_luatvietnam": field.get("ten_linh_vuc_luatvietnam", ""),
                    "page_index": page.get("page_index", ""),
                    "url": page.get("url", ""),
                    "skipped_reason": page.get("skipped_reason", ""),
                })

    return {
        "created_at": step07_data.get("created_at", ""),
        "run_mode": step07_data.get("run_mode", ""),
        "crawl_strategy": step07_data.get("crawl_strategy", ""),
        "total_documents": len(documents),
        "fields_count": len(fields),
        "invalid_items_count": len(invalid_items),
        "warning_items_count": len(warning_items),
        "invalid_items": invalid_items,
        "warning_items": warning_items,
        "filter_stats_by_branch": filter_stats_by_branch,
        "debug_pages_count": debug_pages_count,
        "debug_page_documents_count": debug_page_documents_count,
        "debug_pages_with_zero_documents_count": len(debug_pages_with_zero_documents),
        "debug_pages_with_zero_documents": debug_pages_with_zero_documents,
    }


def classify_payload(payload: dict, config: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []

    doc_type = normalize_text(payload.get("Loại văn bản", ""))
    title = normalize_text(payload.get("Tên văn bản", ""))
    so_hieu = normalize_text(payload.get("Số hiệu", ""))
    url = normalize_text(payload.get("Link Văn bản", ""))

    accepted_doc_types = get_accepted_doc_types(config)
    skip_doc_types = get_skip_doc_types(config)

    if not doc_type:
        errors.append("Payload thiếu Loại văn bản.")
    elif doc_type in skip_doc_types:
        errors.append(f"Payload có loại văn bản bị skip: {doc_type}.")
    elif doc_type not in accepted_doc_types:
        errors.append(f"Payload có loại văn bản không hợp lệ: {doc_type}.")

    if not title:
        errors.append("Payload thiếu Tên văn bản.")

    if not so_hieu:
        errors.append("Payload thiếu Số hiệu.")

    if not url:
        errors.append("Payload thiếu Link Văn bản.")
    else:
        excluded_path = url_matches_excluded_paths(url, config)
        if excluded_path:
            errors.append(f"Payload URL thuộc path loại trừ: {excluded_path}.")

        if not url_matches_required_paths(url, config):
            errors.append("Payload URL không thuộc required_url_path_contains.")

        blocked_keyword = url_contains_blocked_keyword(url, config)
        if blocked_keyword:
            errors.append(f"Payload URL chứa keyword bị chặn: {blocked_keyword}.")

    title_keyword = title_contains_excluded_keyword(title, config)
    if title_keyword:
        errors.append(f"Payload tiêu đề chứa keyword loại trừ: {title_keyword}.")

    so_hieu_keyword = so_hieu_contains_excluded_keyword(so_hieu, config)
    if so_hieu_keyword:
        errors.append(f"Payload số hiệu chứa keyword loại trừ: {so_hieu_keyword}.")

    return errors, warnings


def extract_webapp_response(result_item: dict) -> dict:
    """
    Step08 hiện lưu dạng:
    results[n] = {
      "url": "...",
      "status": "sent",
      "result": <Apps Script response>
    }
    """
    return result_item.get("result", {}) or {}


def summarize_match_report(webapp_response: dict) -> dict:
    """
    Apps Script response kỳ vọng:
    {
      "ok": true,
      "result": {
        "write_result": {...},
        "match_report": {...}
      }
    }
    """
    match_report = get_nested(
        webapp_response,
        ["result", "match_report"],
        {},
    ) or {}

    matched_count = 0
    missing_count = 0

    for heading, report in match_report.items():
        matched_count += len(report.get("matched_ids", []) or [])
        missing_count += len(report.get("missing_items", []) or [])

    return {
        "has_match_report": bool(match_report),
        "matched_relationship_count": matched_count,
        "missing_relationship_count": missing_count,
    }


def summarize_step08(step08_data: dict, request_debug_data: dict, config: dict) -> dict:
    payloads = step08_data.get("payloads", []) or []
    results = step08_data.get("results", []) or []

    status_counts = {}
    for item in results:
        status = normalize_text(item.get("status", "")) or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    payload_invalid_items = []
    payload_warning_items = []

    for payload in payloads:
        errors, warnings = classify_payload(payload, config)

        if errors:
            copied = dict(payload)
            copied["_errors"] = errors
            payload_invalid_items.append(copied)

        if warnings:
            copied = dict(payload)
            copied["_warnings"] = warnings
            payload_warning_items.append(copied)

    result_errors = []
    result_warnings = []
    sent_success_items = []
    sent_webapp_not_ok_items = []
    sent_webapp_skipped_items = []
    sent_without_match_report_items = []
    relationship_missing_items = []

    for item in results:
        status = normalize_text(item.get("status", ""))

        if status == "sent":
            webapp_response = extract_webapp_response(item)

            if webapp_response.get("ok") is not True:
                copied = dict(item)
                copied["_error"] = "Apps Script response ok != true."
                sent_webapp_not_ok_items.append(copied)
                result_errors.append(copied)
                continue

            write_result = get_nested(
                webapp_response,
                ["result", "write_result"],
                {},
            ) or {}

            if write_result.get("action") == "skipped":
                copied = dict(item)
                copied["_error"] = "Apps Script write_result.action = skipped."
                copied["_reason_code"] = write_result.get("reason_code", "")
                copied["_reason_message"] = write_result.get("reason_message", "")
                sent_webapp_skipped_items.append(copied)
                result_errors.append(copied)
                continue

            match_summary = summarize_match_report(webapp_response)

            if not match_summary["has_match_report"]:
                copied = dict(item)
                copied["_warning"] = "Không có result.match_report trong response Apps Script."
                sent_without_match_report_items.append(copied)
                result_warnings.append(copied)

            if match_summary["missing_relationship_count"] > 0:
                copied = dict(item)
                copied["_match_summary"] = match_summary
                relationship_missing_items.append(copied)

            sent_success_items.append(item)
            continue

        if status in {"error", "invalid", "skipped"}:
            copied = dict(item)
            copied["_error"] = f"Step08 status={status}."
            result_errors.append(copied)
            continue

        if status == "dry_run":
            if not bool(step08_data.get("dry_run", False)):
                copied = dict(item)
                copied["_error"] = "Có status=dry_run nhưng step08_data.dry_run=false."
                result_errors.append(copied)
            else:
                copied = dict(item)
                copied["_warning"] = "Dry run: không gửi Apps Script."
                result_warnings.append(copied)
            continue

        copied = dict(item)
        copied["_warning"] = f"Status không nhận diện rõ: {status}."
        result_warnings.append(copied)

    request_debug_rows = request_debug_data.get("rows", []) or []

    return {
        "created_at": step08_data.get("created_at", ""),
        "run_mode": step08_data.get("run_mode", ""),
        "dry_run": bool(step08_data.get("dry_run", False)),
        "apps_script_enabled": bool(step08_data.get("apps_script_enabled", False)),
        "total_input": step08_data.get("total_input", 0),
        "total_payloads": step08_data.get("total_payloads", 0),
        "payloads_count": len(payloads),
        "results_count": len(results),
        "status_counts": status_counts,
        "payload_invalid_count": len(payload_invalid_items),
        "payload_warning_count": len(payload_warning_items),
        "result_error_count": len(result_errors),
        "result_warning_count": len(result_warnings),
        "sent_success_count": len(sent_success_items),
        "sent_webapp_not_ok_count": len(sent_webapp_not_ok_items),
        "sent_webapp_skipped_count": len(sent_webapp_skipped_items),
        "sent_without_match_report_count": len(sent_without_match_report_items),
        "relationship_missing_document_count": len(relationship_missing_items),
        "request_debug_rows_count": len(request_debug_rows),
        "payload_invalid_items": payload_invalid_items,
        "payload_warning_items": payload_warning_items,
        "result_errors": result_errors,
        "result_warnings": result_warnings,
        "sent_webapp_not_ok_items": sent_webapp_not_ok_items,
        "sent_webapp_skipped_items": sent_webapp_skipped_items,
        "sent_without_match_report_items": sent_without_match_report_items,
        "relationship_missing_items": relationship_missing_items,
    }

def iter_match_reports_from_step08(step08_data: dict):
    """
    Duyệt toàn bộ result.match_report từ output Step08.

    Step08 hiện lưu dạng:
    results[n] = {
        "url": "...",
        "status": "sent",
        "result": {
            "ok": true,
            "result": {
                "match_report": {...}
            }
        }
    }
    """
    for item in step08_data.get("results", []) or []:
        if normalize_text(item.get("status", "")) != "sent":
            continue

        webapp_response = item.get("result", {}) or {}

        match_report = get_nested(
            webapp_response,
            ["result", "match_report"],
            {},
        ) or {}

        if not match_report:
            continue

        yield {
            "url": item.get("url", ""),
            "match_report": match_report,
        }
def compute_match_coverage(step08_data: dict) -> dict:
    total_matched = 0
    total_missing = 0

    by_heading = {}

    for row in iter_match_reports_from_step08(step08_data):
        match_report = row["match_report"]

        for heading, report in match_report.items():
            matched_details = report.get("matched_details", []) or []
            missing_items = report.get("missing_items", []) or []

            matched_count = len(matched_details)
            missing_count = len(missing_items)

            total_matched += matched_count
            total_missing += missing_count

            if heading not in by_heading:
                by_heading[heading] = {
                    "matched": 0,
                    "missing": 0,
                    "total": 0,
                    "coverage_percent": 0,
                }

            by_heading[heading]["matched"] += matched_count
            by_heading[heading]["missing"] += missing_count

    total = total_matched + total_missing

    coverage_percent = round(total_matched / total * 100, 2) if total else 100.0

    for heading, stats in by_heading.items():
        heading_total = stats["matched"] + stats["missing"]
        stats["total"] = heading_total
        stats["coverage_percent"] = (
            round(stats["matched"] / heading_total * 100, 2)
            if heading_total
            else 100.0
        )

    return {
        "matched": total_matched,
        "missing": total_missing,
        "total": total,
        "coverage_percent": coverage_percent,
        "by_heading": by_heading,
    }

def collect_missing_refs(step08_data: dict) -> dict:
    """
    Gom missing_items từ toàn bộ match_report.

    Trả về:
    {
      normalized_number: {
        "so_hieu": "...",
        "count": 3,
        "headings": [...],
        "source_urls": [...],
        "examples": [...]
      }
    }
    """
    missing_refs = {}

    for row in iter_match_reports_from_step08(step08_data):
        source_url = row["url"]
        match_report = row["match_report"]

        for heading, report in match_report.items():
            for item in report.get("missing_items", []) or []:
                so_hieu = normalize_text(item.get("so_hieu_tu_luoc_do", ""))
                noi_dung = normalize_text(item.get("noi_dung_luoc_do", ""))

                key = normalize_doc_number_for_tracking(so_hieu)

                if not key:
                    continue

                if key not in missing_refs:
                    missing_refs[key] = {
                        "so_hieu": so_hieu,
                        "normalized_so_hieu": key,
                        "count": 0,
                        "headings": [],
                        "source_urls": [],
                        "examples": [],
                    }

                missing_refs[key]["count"] += 1

                if heading not in missing_refs[key]["headings"]:
                    missing_refs[key]["headings"].append(heading)

                if source_url and source_url not in missing_refs[key]["source_urls"]:
                    missing_refs[key]["source_urls"].append(source_url)

                if noi_dung and len(missing_refs[key]["examples"]) < 5:
                    missing_refs[key]["examples"].append(noi_dung)

    return missing_refs

def load_previous_missing_snapshot() -> dict:
    if not MISSING_REFS_SNAPSHOT_FILE.exists():
        return {}

    try:
        data = json.loads(MISSING_REFS_SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return data.get("missing_refs", {}) or {}


def compute_missing_delta(current_missing_refs: dict, previous_missing_refs: dict) -> dict:
    current_keys = set(current_missing_refs.keys())
    previous_keys = set(previous_missing_refs.keys())

    new_keys = sorted(current_keys - previous_keys)
    resolved_keys = sorted(previous_keys - current_keys)
    persistent_keys = sorted(current_keys & previous_keys)

    return {
        "current_missing_unique_count": len(current_keys),
        "previous_missing_unique_count": len(previous_keys),
        "new_missing_count": len(new_keys),
        "resolved_missing_count": len(resolved_keys),
        "persistent_missing_count": len(persistent_keys),
        "net_delta": len(current_keys) - len(previous_keys),
        "new_missing_refs": [
            current_missing_refs[key]
            for key in new_keys
        ],
        "resolved_missing_refs": [
            previous_missing_refs[key]
            for key in resolved_keys
        ],
    }

def save_missing_refs_snapshot_and_history(report_created_at: str, missing_refs: dict, delta: dict):
    snapshot = {
        "created_at": report_created_at,
        "missing_unique_count": len(missing_refs),
        "missing_refs": missing_refs,
    }

    save_json(MISSING_REFS_SNAPSHOT_FILE, snapshot)

    history = []

    if MISSING_REFS_HISTORY_FILE.exists():
        try:
            history = json.loads(MISSING_REFS_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            history = []

    if not isinstance(history, list):
        history = []

    history.append({
        "created_at": report_created_at,
        "missing_unique_count": len(missing_refs),
        "new_missing_count": delta.get("new_missing_count", 0),
        "resolved_missing_count": delta.get("resolved_missing_count", 0),
        "persistent_missing_count": delta.get("persistent_missing_count", 0),
        "net_delta": delta.get("net_delta", 0),
    })

    save_json(MISSING_REFS_HISTORY_FILE, history)

def determine_pipeline_status(
    config_errors: list[dict],
    step07_summary: dict,
    step08_summary: dict,
    config: dict,
) -> tuple[bool, list[str], list[str]]:
    errors = []
    warnings = []

    if config_errors:
        for item in config_errors:
            errors.append(f"[{item.get('code')}] {item.get('message')}")

    if step07_summary["total_documents"] <= 0:
        errors.append("Step07 không tạo được document nào.")

    if step07_summary["invalid_items_count"] > 0:
        errors.append(
            f"Step07 còn {step07_summary['invalid_items_count']} document không đạt filter."
        )

    if step08_summary["payload_invalid_count"] > 0:
        errors.append(
            f"Step08 còn {step08_summary['payload_invalid_count']} payload không hợp lệ."
        )

    if step08_summary["result_error_count"] > 0:
        errors.append(
            f"Step08 còn {step08_summary['result_error_count']} result lỗi."
        )

    if step08_summary["sent_webapp_not_ok_count"] > 0:
        errors.append(
            f"Apps Script trả ok=false cho {step08_summary['sent_webapp_not_ok_count']} item."
        )

    if step08_summary["sent_webapp_skipped_count"] > 0:
        errors.append(
            f"Apps Script skipped {step08_summary['sent_webapp_skipped_count']} item."
        )

    if step08_summary["sent_without_match_report_count"] > 0:
        errors.append(
            f"Có {step08_summary['sent_without_match_report_count']} item sent nhưng thiếu result.match_report."
        )

    if step08_summary["relationship_missing_document_count"] > 0:
        warnings.append(
            f"Có {step08_summary['relationship_missing_document_count']} văn bản có quan hệ pháp lý chưa có trong danh mục VBQPPL."
        )

    if step07_summary["warning_items_count"] > 0:
        warnings.append(
            f"Step07 có {step07_summary['warning_items_count']} document cảnh báo, ví dụ thiếu số hiệu từ list."
        )

    if step08_summary["result_warning_count"] > 0:
        warnings.append(
            f"Step08 có {step08_summary['result_warning_count']} result cảnh báo."
        )

    return len(errors) == 0, errors, warnings


def short_json(value, limit: int = 1200) -> str:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def write_reports(report: dict):
    save_json(OUTPUT_REPORT_JSON, report)

    lines = []

    lines.append("=" * 100)
    lines.append("BƯỚC 09 - KIỂM ĐỊNH KẾT QUẢ PIPELINE LUATVIETNAM")
    lines.append("=" * 100)
    lines.append(f"Thời gian tạo báo cáo: {report['created_at']}")
    lines.append(f"Kết luận: {'ĐẠT' if report['is_pipeline_ok'] else 'CHƯA ĐẠT'}")
    lines.append("")

    lines.append("CẤU HÌNH")
    lines.append("-" * 100)
    lines.append("")

    if report["config_errors"]:
        lines.append("Lỗi cấu hình:")
        for item in report["config_errors"]:
            lines.append(f"- [{item['code']}] {item['message']}")
    else:
        lines.append("Không phát hiện lỗi cấu hình nghiêm trọng.")

    if report["config_warnings"]:
        lines.append("")
        lines.append("Cảnh báo cấu hình:")
        for item in report["config_warnings"]:
            lines.append(f"- [{item['code']}] {item['message']}")

    lines.append("")
    lines.append("STEP07")
    lines.append("-" * 100)

    s7 = report["step07"]

    lines.append(f"Created at: {s7['created_at']}")
    lines.append(f"Run mode: {s7['run_mode']}")
    lines.append(f"Crawl strategy: {s7['crawl_strategy']}")
    lines.append(f"Tổng documents: {s7['total_documents']}")
    lines.append(f"Số nhánh crawl/fields: {s7['fields_count']}")
    lines.append(f"Số debug_pages: {s7['debug_pages_count']}")
    lines.append(f"Số page_documents trong debug: {s7['debug_page_documents_count']}")
    lines.append(f"Document lỗi filter: {s7['invalid_items_count']}")
    lines.append(f"Document cảnh báo: {s7['warning_items_count']}")
    lines.append(f"Debug pages không có document: {s7['debug_pages_with_zero_documents_count']}")
    lines.append("")

    if s7["filter_stats_by_branch"]:
        lines.append("Thống kê filter theo nhánh crawl:")
        for item in s7["filter_stats_by_branch"]:
            stats = item.get("filter_debug_stats", {}) or {}
            lines.append(
                "- "
                f"crawl_doc_type_id={item.get('crawl_doc_type_id', '')} | "
                f"documents={item.get('documents_count', 0)} | "
                f"pages={item.get('pages_crawled_count', 0)} | "
                f"input={stats.get('input_links', 0)} | "
                f"kept={stats.get('kept_links', 0)} | "
                f"reject_doc_type={stats.get('doc_type', 0)} | "
                f"reject_path={stats.get('required_url_path_contains', 0)} | "
                f"reject_url_kw={stats.get('exclude_url_keywords', 0)}"
            )
        lines.append("")

    if s7["invalid_items"]:
        lines.append("STEP07 - Document không đạt filter:")
        for item in s7["invalid_items"][:40]:
            lines.append(f"- {item.get('title_from_list', '')}")
            lines.append(f"  Loại: {item.get('doc_type_from_list', '')}")
            lines.append(f"  Số hiệu: {item.get('doc_number_from_list', '')}")
            lines.append(f"  URL: {item.get('url', '')}")
            lines.append(f"  Lỗi: {' | '.join(item.get('_errors', []))}")
        lines.append("")

    if s7["warning_items"]:
        lines.append("STEP07 - Document cảnh báo:")
        for item in s7["warning_items"][:30]:
            lines.append(f"- {item.get('title_from_list', '')}")
            lines.append(f"  URL: {item.get('url', '')}")
            lines.append(f"  Cảnh báo: {' | '.join(item.get('_warnings', []))}")
        lines.append("")

    lines.append("STEP08")
    lines.append("-" * 100)

    s8 = report["step08"]

    lines.append(f"Created at: {s8['created_at']}")
    lines.append(f"Run mode: {s8['run_mode']}")
    lines.append(f"Dry run: {s8['dry_run']}")
    lines.append(f"Apps Script enabled: {s8['apps_script_enabled']}")
    lines.append(f"Total input: {s8['total_input']}")
    lines.append(f"Total payloads: {s8['total_payloads']}")
    lines.append(f"Payloads count: {s8['payloads_count']}")
    lines.append(f"Results count: {s8['results_count']}")
    lines.append(f"Status counts: {s8['status_counts']}")
    lines.append(f"Payload lỗi: {s8['payload_invalid_count']}")
    lines.append(f"Payload cảnh báo: {s8['payload_warning_count']}")
    lines.append(f"Result lỗi: {s8['result_error_count']}")
    lines.append(f"Result cảnh báo: {s8['result_warning_count']}")
    lines.append(f"Sent success: {s8['sent_success_count']}")
    lines.append(f"Apps Script ok=false: {s8['sent_webapp_not_ok_count']}")
    lines.append(f"Apps Script skipped: {s8['sent_webapp_skipped_count']}")
    lines.append(f"Sent thiếu match_report: {s8['sent_without_match_report_count']}")
    lines.append(f"Văn bản có quan hệ chưa có trong danh mục: {s8['relationship_missing_document_count']}")
    lines.append(f"Request debug rows: {s8['request_debug_rows_count']}")
    lines.append("")

    if s8["payload_invalid_items"]:
        lines.append("STEP08 - Payload không hợp lệ:")
        for item in s8["payload_invalid_items"][:40]:
            lines.append(f"- {item.get('Số hiệu', '')} | {item.get('Tên văn bản', '')}")
            lines.append(f"  Loại: {item.get('Loại văn bản', '')}")
            lines.append(f"  URL: {item.get('Link Văn bản', '')}")
            lines.append(f"  Lỗi: {' | '.join(item.get('_errors', []))}")
        lines.append("")

    if s8["result_errors"]:
        lines.append("STEP08 - Result lỗi:")
        for item in s8["result_errors"][:40]:
            lines.append(f"- URL: {item.get('url', '')}")
            lines.append(f"  Status: {item.get('status', '')}")
            lines.append(f"  Message: {item.get('message', '')}")
            lines.append(f"  Error: {item.get('_error', '')}")
            if "result" in item:
                lines.append(f"  Response: {short_json(item.get('result', {}))}")
        lines.append("")

    if s8["sent_without_match_report_items"]:
        lines.append("STEP08 - Sent nhưng thiếu match_report:")
        for item in s8["sent_without_match_report_items"][:30]:
            lines.append(f"- URL: {item.get('url', '')}")
            lines.append(f"  Response: {short_json(item.get('result', {}))}")
        lines.append("")

    if s8["relationship_missing_items"]:
        lines.append("STEP08 - Quan hệ pháp lý chưa có trong danh mục:")
        for item in s8["relationship_missing_items"][:40]:
            summary = item.get("_match_summary", {}) or {}
            lines.append(f"- URL: {item.get('url', '')}")
            lines.append(
                f"  Missing relationships: {summary.get('missing_relationship_count', 0)}"
            )
        lines.append("")
        lines.append("CHỈ SỐ PRODUCTION")
    lines.append("-" * 100)

    coverage = report.get("match_coverage", {}) or {}

    lines.append(
        "Match coverage: "
        f"{coverage.get('coverage_percent', 0)}% "
        f"({coverage.get('matched', 0)} matched / "
        f"{coverage.get('total', 0)} total relationships)"
    )

    lines.append(f"Missing relationships: {coverage.get('missing', 0)}")
    lines.append("")

    if coverage.get("by_heading"):
        lines.append("Match coverage theo nhóm quan hệ:")
        for heading, stats in coverage["by_heading"].items():
            lines.append(
                f"- {heading}: "
                f"{stats.get('coverage_percent', 0)}% "
                f"({stats.get('matched', 0)} matched / "
                f"{stats.get('total', 0)} total, "
                f"{stats.get('missing', 0)} missing)"
            )
        lines.append("")

    delta = report.get("missing_delta", {}) or {}

    lines.append("Missing delta so với lần chạy trước:")
    lines.append(f"- Missing hiện tại: {delta.get('current_missing_unique_count', 0)} số hiệu unique")
    lines.append(f"- Missing lần trước: {delta.get('previous_missing_unique_count', 0)} số hiệu unique")
    lines.append(f"- Missing mới: {delta.get('new_missing_count', 0)}")
    lines.append(f"- Missing đã được xử lý: {delta.get('resolved_missing_count', 0)}")
    lines.append(f"- Missing còn tồn tại: {delta.get('persistent_missing_count', 0)}")
    lines.append(f"- Net delta: {delta.get('net_delta', 0)}")
    lines.append("")

    if delta.get("new_missing_refs"):
        lines.append("Missing mới phát sinh:")
        for item in delta["new_missing_refs"][:20]:
            lines.append(
                f"- {item.get('so_hieu', '')} "
                f"| xuất hiện {item.get('count', 0)} lần "
                f"| nhóm: {', '.join(item.get('headings', []))}"
            )
        lines.append("")

    top_missing_refs = report.get("top_missing_refs", []) or []

    if top_missing_refs:
        lines.append("Top missing refs cần ưu tiên bổ sung VBQPPL:")
        for index, item in enumerate(top_missing_refs, start=1):
            lines.append(
                f"{index}. {item.get('so_hieu', '')} "
                f"| thiếu {item.get('count', 0)} lần "
                f"| nhóm: {', '.join(item.get('headings', []))}"
            )

            examples = item.get("examples", []) or []
            if examples:
                lines.append(f"   Ví dụ: {examples[0][:250]}")
        lines.append("")

    lines.append("KẾT LUẬN")
    lines.append("-" * 100)

    if report["pipeline_errors"]:
        lines.append("Lỗi cần xử lý:")
        for item in report["pipeline_errors"]:
            lines.append(f"- {item}")
    else:
        lines.append("Không có lỗi nghiêm trọng.")

    if report["pipeline_warnings"]:
        lines.append("")
        lines.append("Cảnh báo:")
        for item in report["pipeline_warnings"]:
            lines.append(f"- {item}")

    lines.append("")
    lines.append("=" * 100)
    lines.append("KẾT THÚC BƯỚC 09")
    lines.append("=" * 100)

    report_text = "\n".join(lines)

    save_text(OUTPUT_REPORT_TXT, report_text)

    try:
        print(report_text)
    except UnicodeEncodeError:
        print(report_text.encode("ascii", errors="replace").decode("ascii"))

    print()
    print(f"Đã lưu báo cáo TXT: {OUTPUT_REPORT_TXT}")
    print(f"Đã lưu báo cáo JSON: {OUTPUT_REPORT_JSON}")


def main():
    setup_utf8_stdio()
    config = load_json(CONFIG_FILE)
    step07_data = load_json(STEP07_FILE)
    step07_debug = load_json(STEP07_DEBUG_FILE, required=False)
    step08_data = load_json(STEP08_FILE)
    request_debug_data = load_json(STEP08_REQUEST_DEBUG_FILE, required=False)

    config_errors, config_warnings = validate_config(config)

    step07_summary = summarize_step07(
        step07_data=step07_data,
        step07_debug=step07_debug,
        config=config,
    )

    step08_summary = summarize_step08(
        step08_data=step08_data,
        request_debug_data=request_debug_data,
        config=config,
    )
    match_coverage = compute_match_coverage(step08_data)
    current_missing_refs = collect_missing_refs(step08_data)
    previous_missing_refs = load_previous_missing_snapshot()

    missing_delta = compute_missing_delta(
        current_missing_refs=current_missing_refs,
        previous_missing_refs=previous_missing_refs,
    )

    top_missing_refs = sorted(
        current_missing_refs.values(),
        key=lambda x: (-x.get("count", 0), x.get("so_hieu", "")),
    )[:20]
    is_pipeline_ok, pipeline_errors, pipeline_warnings = determine_pipeline_status(
        config_errors=config_errors,
        step07_summary=step07_summary,
        step08_summary=step08_summary,
        config=config,
    )

    report = {
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "is_pipeline_ok": is_pipeline_ok,
        "config_errors": config_errors,
        "config_warnings": config_warnings,
        "pipeline_errors": pipeline_errors,
        "pipeline_warnings": pipeline_warnings,
        "step07": step07_summary,
        "step08": step08_summary,
        "match_coverage": match_coverage,
        "missing_delta": missing_delta,
        "top_missing_refs": top_missing_refs,
    }

    write_reports(report)
    
    save_missing_refs_snapshot_and_history(
        report_created_at=report["created_at"],
        missing_refs=current_missing_refs,
        delta=missing_delta,
    )

    if not is_pipeline_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
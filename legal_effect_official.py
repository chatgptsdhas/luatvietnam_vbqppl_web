"""GD2.03: read-only cross-check of legal-effect proposals against official VBPL text.

The supplied source index must contain real, independently found official document
URLs. There is intentionally NO guessing ItemID from a legal-document number.
Matching an official clause is evidence, not a legal validity determination.

No Apps Script/Planner requests, credentials, authentication cookies or writes.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup
from legal_effect_analysis import analyze_new_document, clean, document_numbers, normalize_number
from legal_effect_content import extract_legal_effect_evidence_from_html

ALLOWED_HOSTS = frozenset(("vbpl.vn", "vbpl.moj.gov.vn"))
FULLTEXT_PATH = re.compile(r"^/[a-zA-Z0-9_-]{2,40}/pages/vbpq-(?:toanvan|print)\.aspx$", re.I)
# VBPL modern details: the trailing numeric ID is an official record ID,
# NOT a legal-document number; do not derive it from an unverified title.
FRIENDLY_DETAIL_PATH = re.compile(
    r"^/van-ban/chi-tiet/[a-z0-9][a-z0-9-]{1,300}--(?P<item_id>[1-9]\d{0,8})/?$", re.I
)
MAX_HTML_BYTES = 5_000_000
SOURCE_NUMBER = re.compile(
    r"(?:^|[\s;])Số\s*[:：]\s*(\d{1,4}\s*/\s*(?:19|20)\d{2}\s*/\s*[A-ZÀ-ỸĐ0-9-]+)",
    re.I,
)
RAW_STATUS = re.compile(r"Hiệu\s+lực\s*[:：]\s*(Còn\s+hiệu\s+lực|"
                        r"Hết\s+hiệu\s+lực(?:\s+(?:toàn\s+bộ|một\s+phần))?|"
                        r"Chưa\s+có\s+hiệu\s+lực)", re.I)


def canonical_official_url(value: Any) -> str:
    """Strict allowlist to prevent SSRF, credential leakage and open redirects."""
    if not isinstance(value, str) or len(value) > 350 or any(ord(c) < 32 for c in value):
        raise ValueError("INVALID_OFFICIAL_URL")
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() != "https" or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("INVALID_OFFICIAL_URL")
    if parsed.hostname not in ALLOWED_HOSTS or parsed.port is not None:
        raise ValueError("INVALID_OFFICIAL_HOST")
    friendly_match = FRIENDLY_DETAIL_PATH.fullmatch(parsed.path)
    if friendly_match:
        # VBPL modern URLs must not carry arbitrary parameters or fragments.
        if parsed.hostname != "vbpl.vn" or parsed.query:
            raise ValueError("INVALID_OFFICIAL_QUERY")
        return f"https://vbpl.vn{parsed.path.rstrip('/')}"
    if not FULLTEXT_PATH.fullmatch(parsed.path):
        raise ValueError("INVALID_OFFICIAL_PATH")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if len(query) != 1 or query[0][0] != "ItemID" or not re.fullmatch(r"[1-9]\d{0,8}", query[0][1]):
        raise ValueError("INVALID_OFFICIAL_QUERY")
    return f"https://{parsed.hostname}{parsed.path}?ItemID={query[0][1]}"


def official_fetch_targets(value: str) -> list[str]:
    """Allowed alternatives derived only from an explicit VBPL record ID.

    The alternate endpoint is *not* trusted until its document identity and
    actual operative clauses match. We never follow redirects to untrusted URLs.
    """
    url = canonical_official_url(value)
    parsed = urlsplit(url)
    match = FRIENDLY_DETAIL_PATH.fullmatch(parsed.path)
    if not match:
        return [url]
    item_id = match.group("item_id")
    return [url,
            f"https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID={item_id}",
            f"https://vbpl.vn/TW/Pages/vbpq-print.aspx?ItemID={item_id}"]


def load_official_sources(path: Path) -> dict[str, str]:
    """Explicit, traceable map: new document number -> official full-text URL."""
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict):
        raise ValueError("OFFICIAL_INDEX_NOT_OBJECT")
    data = obj.get("sources", obj)
    if not isinstance(data, dict):
        raise ValueError("OFFICIAL_INDEX_INVALID_SOURCES")
    output = {}
    for number, url in data.items():
        key = normalize_number(number)
        if not key or document_numbers(key) != [key]:
            raise ValueError("OFFICIAL_INDEX_INVALID_NUMBER")
        if key in output:
            raise ValueError("OFFICIAL_INDEX_DUPLICATED_NUMBER")
        output[key] = canonical_official_url(url)
    return output


def fetch_official_html(url: str, timeout_seconds: int = 15) -> str:
    """Bounded HTTPS fetch; redirects and non-HTML responses are rejected."""
    import requests

    url = canonical_official_url(url)
    try:
        with requests.get(
            url,
            headers={"User-Agent": "HAS-VBQPPL-ReadOnly/1.0 (official-document-check)"},
            timeout=(min(8, timeout_seconds), timeout_seconds),
            stream=True,
            allow_redirects=False,
        ) as response:
            if 300 <= response.status_code < 400:
                raise ValueError("OFFICIAL_REDIRECT_BLOCKED")
            if response.status_code != 200:
                raise ValueError("OFFICIAL_HTTP_ERROR")
            mime_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if mime_type != "text/html":
                raise ValueError("OFFICIAL_NOT_HTML")
            try:
                if int(response.headers.get("Content-Length", "0")) > MAX_HTML_BYTES:
                    raise ValueError("OFFICIAL_DOCUMENT_TOO_LARGE")
            except (TypeError, ValueError) as err:
                if str(err) == "OFFICIAL_DOCUMENT_TOO_LARGE":
                    raise
            data = bytearray()
            for chunk in response.iter_content(chunk_size=32768):
                data.extend(chunk)
                if len(data) > MAX_HTML_BYTES:
                    raise ValueError("OFFICIAL_DOCUMENT_TOO_LARGE")
            encoding = response.encoding or "utf-8"
            return bytes(data).decode(encoding, errors="replace")
    except ValueError:
        raise
    except requests.RequestException as exc:
        # Do not leak server headers, content, credentials or stack traces.
        raise ValueError("OFFICIAL_SOURCE_UNAVAILABLE") from None


def _official_identity(soup: BeautifulSoup) -> str:
    """Only document's own 'Số:' field, not references in articles."""
    # Rendered text contains official document header. Never accept a match
    # drawn from navigation, query fields, citations or a generic number list.
    for el in soup.select("nav, aside, footer, form, script, style, noscript"):
        el.decompose()
    text = clean(soup.get_text(" ", strip=True))
    header = text[:10000]
    numbers = {normalize_number(x) for x in SOURCE_NUMBER.findall(header)}
    return next(iter(numbers)) if len(numbers) == 1 else ""


def official_html_check(event: dict[str, Any], url: str, html: str) -> dict[str, Any]:
    """Pure verification of pair+action against official full-text evidence."""
    url = canonical_official_url(url)
    old = normalize_number(event.get("old_number", ""))
    new = normalize_number(event.get("new_number", ""))
    base = {
        "status": "SOURCE_NOT_VERIFIED", "official_url": url,
        "old_number": old, "new_number": new,
        "source_document_number": "", "official_effect_raw": "",
        "source_clause": "", "source_location": "", "source_section": "",
        "observed_relation": "", "observed_scope": "",
        "observed_date": "", "observed_date_basis": "",
        "source_evidence_sha256": "", "requires_legal_review": True,
    }
    if not old or not new or old == new:
        base["status"] = "DOCUMENT_PAIR_INCOMPLETE"
        return base
    if not isinstance(html, str) or not html.strip():
        base["status"] = "OFFICIAL_EMPTY_DOCUMENT"
        return base
    soup = BeautifulSoup(html, "html.parser")
    found = _official_identity(soup)
    base["source_document_number"] = found
    if found != new:
        base["status"] = "IDENTITY_MISMATCH"
        return base

    raw = RAW_STATUS.search(clean(soup.get_text(" ", strip=True)))
    if raw:
        base["official_effect_raw"] = clean(raw.group(1))  # status of NEW doc only

    extraction = extract_legal_effect_evidence_from_html(html)
    blocks = extraction.get("blocks") or []
    if not blocks:
        base["status"] = "OFFICIAL_TEXT_UNAVAILABLE"
        return base
    candidates = analyze_new_document(
        {"source_doc_number": new, "url": url, "luoc_do_data": []},
        lines=blocks,
    )
    # Require explicit OLD/NEW pairing found in official source clauses.
    matches = [x for x in candidates if x["old_number"] == old and x["new_number"] == new
               and x["evidence_origin"] == "clause"]
    if not matches:
        base["status"] = ("DIRECTION_UNCONFIRMED"
                          if any(x["old_number"] == old for x in candidates)
                          else "NO_RELEVANT_OFFICIAL_ACTION")
        return base
    asked = clean(event.get("relation_type", ""))
    # Do not equate amended/partially repealed with whole-document repeal.
    exact = [x for x in matches if asked == x["relation_type"]]
    if asked == "KHAC":
        base["status"] = "AMBIGUOUS_PROPOSAL"
        return base
    if not exact:
        base["status"] = "OFFICIAL_RELATION_CONFLICT"
        base["observed_relation"] = ",".join(sorted({x["relation_type"] for x in matches}))
        return base
    # A relation can match lexically yet still lack a proven whole-document scope.
    chosen = sorted(exact, key=lambda x: (x["evidence_location"], x["event_key"]))[0]
    base.update({
        "source_clause": chosen["evidence_text"][:800],
        "source_location": chosen["evidence_location"],
        "source_section": chosen["evidence_section_heading"],
        "observed_relation": chosen["relation_type"],
        "observed_scope": chosen["scope_type"],
        "observed_date": chosen["effect_date_candidate"],
        "observed_date_basis": chosen["effect_date_basis"],
    })
    base["source_evidence_sha256"] = hashlib.sha256(
        (chosen["evidence_text"] + "|" + chosen["evidence_section_heading"]).encode("utf-8")
    ).hexdigest()
    if asked in ("BAI_BO_TOAN_BO", "THAY_THE_TOAN_BO") and chosen["scope_type"] == "MOT_PHAN":
        base["status"] = "OFFICIAL_SCOPE_CONFLICT"
    elif (event.get("effect_date_candidate") and chosen.get("effect_date_candidate")
          and event["effect_date_candidate"] != chosen["effect_date_candidate"]):
        base["status"] = "OFFICIAL_DATE_CONFLICT"
    elif (asked in ("BAI_BO_TOAN_BO", "THAY_THE_TOAN_BO")
          and chosen["scope_type"] == "KHONG_RO"):
        base["status"] = "OFFICIAL_SCOPE_NEEDS_REVIEW"
    else:
        base["status"] = "OFFICIAL_ACTION_MATCHED_PENDING_LEGAL"
    return base


def check_official_sources(report: dict, events: list[dict], sources: dict[str, str],
                           fetcher=None) -> dict[str, Any]:
    """Enrich review CSV/JSON in-memory, with a separate conservative audit.

    Does not write any remote system or mark DA_XAC_NHAN. The only input for
    finding official pages is an explicitly provided official source index.
    """
    if fetcher is None:
        fetcher = fetch_official_html
    by_event = {clean(e.get("event_key")): e for e in events if isinstance(e, dict) and e.get("event_key")}
    cache: dict[str, tuple[str, str]] = {}
    audit = []
    for record in report.get("records_review", []):
        event = by_event.get(clean(record.get("Khóa sự kiện"))) or {}
        new = normalize_number(event.get("new_number", ""))
        official_url = sources.get(new, "") if new else ""
        if not official_url:
            result = {"status": "OFFICIAL_SOURCE_NOT_INDEXED", "official_url": "",
                      "requires_legal_review": True}
        else:
            try:
                safe_url = canonical_official_url(official_url)
                if safe_url not in cache:
                    try:
                        cache[safe_url] = ("ok", fetcher(safe_url))
                    except (ValueError, OSError):
                        cache[safe_url] = ("error", "")
                fetch_status, html = cache[safe_url]
                result = (official_html_check(event, safe_url, html) if fetch_status == "ok"
                          else {"status": "OFFICIAL_SOURCE_UNAVAILABLE",
                                "official_url": safe_url, "requires_legal_review": True})
            except (ValueError, TypeError):
                result = {"status": "OFFICIAL_URL_REJECTED", "official_url": "",
                          "requires_legal_review": True}
        status = result["status"]
        if status == "OFFICIAL_ACTION_MATCHED_PENDING_LEGAL":
            record["URL nguồn chính thức"] = result["official_url"]
            # Copy a quote only when matched in the official text.
            record["Trích dẫn điều khoản"] = result.get("source_clause") or record["Trích dẫn điều khoản"]
            record["Mức tin cậy"] = "TRUNG_BINH"
        else:
            if result.get("source_document_number") == new and result.get("official_url"):
                record["URL nguồn chính thức"] = result["official_url"]
            record["Mức tin cậy"] = "THAP"
            record["Trạng thái xác minh"] = "CAN_BO_SUNG_CHUNG_CU"
            record["Lỗi hoặc ngoại lệ"] = "; ".join(filter(None, (
                record.get("Lỗi hoặc ngoại lệ", ""), "GD2_03:" + status
            )))
        record["Ghi chú vận hành"] = "; ".join(filter(None, (
            record.get("Ghi chú vận hành", ""), "Đối chiếu chính thức: " + status
        )))
        audit.append({"review_id": record.get("Mã phiếu rà soát", ""),
                      "event_key": event.get("event_key", ""), **result})
    return {
        "enabled": True, "sources_indexed": len(sources),
        "sources_fetched": len(cache),
        "status_counts": dict(sorted(Counter(x["status"] for x in audit).items())),
        "results": audit,
    }

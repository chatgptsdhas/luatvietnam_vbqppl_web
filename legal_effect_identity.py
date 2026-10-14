"""GD2.04 — read-only source identity reconciliation for VBQPPL / VBQPPL_Nhap.

A normalized legal number is a *candidate join key*, not proof that two
rows represent one legal document. Never write source workbook cells.
Preserve all source IDs, flag conflicts, and prefer a valid source URL
over an editorial text accidentally stored in 'Link Văn bản'.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import unicodedata
from collections import Counter
from urllib.parse import urlsplit, urlunsplit

from legal_effect_analysis import normalize_number, clean

_NUMBER_SHAPE = re.compile(
    r"^\d{1,4}/(?:19|20)\d{2}/[A-ZÀ-ỸĐ0-9]+(?:-[A-ZÀ-ỸĐ0-9]+)*$", re.I
)
BLOCKING_ISSUES = frozenset({
    "MULTIPLE_DOCUMENT_IDS", "DOCUMENT_TYPE_CONFLICT",
    "ISSUING_AUTHORITY_CONFLICT", "NO_VALID_SOURCE_URL",
})


def normalize_identity_text(value) -> str:
    return " ".join(unicodedata.normalize("NFC", str(value or "")).casefold().split())


def safe_document_url(value) -> str:
    """Normalize a source URL without requesting it or relaxing SSRF boundaries.

    Unparseable and editorial labels return "". An HTTP URL remains a
    candidate source, not a verified official legal source.
    """
    if not isinstance(value, str) or len(value) > 3500:
        return ""
    value = value.strip()
    if not value or any(ord(c) < 32 for c in value):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ("http", "https"):
            return ""
        if parsed.username is not None or parsed.password is not None:
            return ""
        hostname = (parsed.hostname or "").lower()
        if not hostname or hostname == "localhost" or hostname.endswith(".localhost"):
            return ""
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            ip = None
        if ip is not None and not ip.is_global:
            return ""
        port = parsed.port
        if port is not None and port != (443 if parsed.scheme.lower() == "https" else 80):
            return ""
        if not parsed.path and not parsed.query:
            return ""
        host = hostname if ":" not in hostname else f"[{hostname}]"
        return urlunsplit((parsed.scheme.lower(), host, parsed.path.rstrip("/") or "/",
                           parsed.query, ""))
    except (ValueError, TypeError):
        return ""


def _url_rank(source: dict) -> tuple:
    url = safe_document_url(source.get("url", ""))
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    domain = 0 if host in ("vbpl.vn", "vbpl.moj.gov.vn") else (
        1 if host == "luatvietnam.vn" or host.endswith(".luatvietnam.vn") else 2
    )
    protocol = 0 if parsed.scheme == "https" else 1
    sheet = 0 if source.get("sheet") == "VBQPPL_Nhap" else 1
    # Stable even when the physical row order differs between snapshots.
    return (domain, protocol, sheet, url)


def _source_fingerprint(code: str, sources: list[dict]) -> str:
    # Physical row numbers are intentionally excluded from identity/fingerprint.
    # Moving a row must not manufacture a new legal document.
    entries = sorted({
        (
            clean(s.get("sheet", "")),
            clean(s.get("id", "")),
            normalize_identity_text(s.get("type", "")),
            normalize_identity_text(s.get("title", "")),
            safe_document_url(s.get("url", "")) or clean(s.get("url", "")),
            clean(s.get("effect_start", "")),
            normalize_identity_text(s.get("issuer", "")),
        )
        for s in sources
    })
    payload = json.dumps([code, entries], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def inspect_catalog(catalog: dict[str, list[dict]]) -> dict:
    """Inspect *all* occurrences of each document number, preserving origin.

    The review report stays within GD1's 28-column schema; source-provenance
    details are placed in a separate read-only identity_audit object.
    """
    by_number: dict[str, dict] = {}
    issue_counts: Counter = Counter()
    issue_rows: list[dict] = []
    non_url_records = 0
    cross_sheet_keys = 0
    for raw_code, sources in sorted(catalog.items()):
        code = normalize_number(raw_code)
        if not code or not sources:
            continue
        source_sheets = {clean(s.get("sheet", "")) for s in sources}
        if len(source_sheets) > 1:
            cross_sheet_keys += 1
        ids = {clean(s.get("id", "")) for s in sources if clean(s.get("id", ""))}
        types = {normalize_identity_text(s.get("type", "")) for s in sources
                 if normalize_identity_text(s.get("type", ""))}
        issuers = {normalize_identity_text(s.get("issuer", "")) for s in sources
                   if normalize_identity_text(s.get("issuer", ""))}
        valid_urls = {safe_document_url(s.get("url", "")) for s in sources}
        valid_urls.discard("")
        non_url_sources = [
            s for s in sources if clean(s.get("url", "")) and not safe_document_url(s.get("url", ""))
        ]
        non_url_records += len(non_url_sources)
        raw_titles = {normalize_identity_text(s.get("title", "")) for s in sources
                      if normalize_identity_text(s.get("title", ""))}
        issues: list[str] = []
        if len(ids) > 1:
            issues.append("MULTIPLE_DOCUMENT_IDS")
        if len(types) > 1:
            issues.append("DOCUMENT_TYPE_CONFLICT")
        if len(issuers) > 1:
            issues.append("ISSUING_AUTHORITY_CONFLICT")
        if len(valid_urls) > 1:
            issues.append("MULTIPLE_VALID_SOURCE_URLS")
        if not valid_urls:
            issues.append("NO_VALID_SOURCE_URL")
        if non_url_sources:
            issues.append("NON_URL_DOCUMENT_LINK")
        if len(raw_titles) > 1:
            issues.append("TITLE_VARIANTS")
        if not _NUMBER_SHAPE.fullmatch(code):
            issues.append("NONSTANDARD_DOCUMENT_NUMBER")
        for item in issues:
            issue_counts[item] += 1
        if issues:
            issue_rows.append({
                "number": code,
                "source_sheets": sorted(source_sheets),
                "source_ids": sorted(ids),
                "source_rows": [
                    {"sheet": s.get("sheet", ""), "row": s.get("row_number", ""),
                     "source_id": clean(s.get("id", ""))}
                    for s in sorted(sources, key=lambda s: (
                        clean(s.get("sheet", "")), str(s.get("row_number", "")), clean(s.get("id", ""))))
                ],
                "issues": issues,
                "valid_url_count": len(valid_urls),
                "source_count": len(sources),
            })
        # Do not manufacture a falsely unique authority when it is absent.
        identity_seed = "|".join((
            code,
            next(iter(types)) if len(types) == 1 else "UNRESOLVED_TYPE",
            next(iter(issuers)) if len(issuers) == 1 else "UNKNOWN_ISSUER",
        ))
        identity_key = "DOC-" + hashlib.sha256(identity_seed.encode("utf-8")).hexdigest()[:20].upper()
        # Always choose a valid link when available; editorial "Link Văn bản"
        # must never be passed off as an official/document URL.
        best_url_record = min(
            (s for s in sources if safe_document_url(s.get("url", ""))),
            key=_url_rank, default=None,
        )
        best_url = safe_document_url(best_url_record.get("url", "")) if best_url_record else ""
        representative = min(
            sources,
            key=lambda s: (0 if s.get("sheet") == "VBQPPL" else 1,
                           0 if clean(s.get("title", "")) else 1,
                           clean(s.get("id", "")), clean(s.get("title", ""))),
        )
        by_number[code] = {
            "document_key": identity_key,
            "representative": representative,
            "preferred_url": best_url,
            "issues": issues,
            "requires_identity_review": any(x in BLOCKING_ISSUES for x in issues),
            "fingerprint": _source_fingerprint(code, sources),
        }
    return {
        "by_number": by_number,
        "summary": {
            "catalog_unique_numbers": len(by_number),
            "cross_sheet_numbers": cross_sheet_keys,
            "non_url_link_records": non_url_records,
            "identity_conflict_numbers": sum(x["requires_identity_review"]
                                             for x in by_number.values()),
            "number_with_multiple_ids": issue_counts.get("MULTIPLE_DOCUMENT_IDS", 0),
            "issue_counts": dict(sorted(issue_counts.items())),
        },
        "issues": issue_rows,
    }

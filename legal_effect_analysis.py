"""Conservative legal-effect candidate extraction from LuatVietnam documents.

No external requests or writes. Output is ONLY a proposal for legal review.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date
from typing import Any

DOC_NUMBER = re.compile(
    r"(?<![\w])\d{1,4}\s*/\s*(?:19|20)\d{2}\s*/\s*[A-ZÀ-ỸĐ0-9]+(?:-[A-ZÀ-ỸĐ0-9]+)*(?![\w])",
    re.IGNORECASE,
)
NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/((?:19|20)\d{2})(?!\d)")
ISO_DATE = re.compile(r"^((?:19|20)\d{2})-(\d{2})-(\d{2})$")
WORD_DATE = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+((?:19|20)\d{2})", re.I)
PARTIAL = re.compile(r"\b(?:một phần|một số điều|điểm\s+[a-zđ]|khoản\s+\d+|điều\s+\d+|phụ lục\s+\w+)\b", re.I)
NEGATED = re.compile(r"\b(?:không|chưa)\s+(?:bị\s+)?(?:bãi bỏ|thay thế|hết hiệu lực|đình chỉ)\b", re.I)
CONTINUED = re.compile(r"(?:tiếp tục|vẫn)\s+(?:được\s+)?(?:có|giữ)\s+hiệu lực", re.I)

# Perspective is always the document currently being parsed.
RELATIONS = {
    "văn bản bị thay thế": ("THAY_THE_TOAN_BO", "listed_old"),
    "văn bản thay thế": ("THAY_THE_TOAN_BO", "current_old"),
    "văn bản hết hiệu lực": ("KHAC", "unknown"),
    "văn bản sửa đổi, bổ sung": ("SUA_DOI_BO_SUNG", "listed_old"),
    "văn bản bị sửa đổi, bổ sung": ("SUA_DOI_BO_SUNG", "current_old"),
}


def clean(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFC", str(value or "")).split())


def normalize_number(value: Any) -> str:
    value = clean(value).upper().replace("‐", "-").replace("‑", "-").replace("–", "-").replace("—", "-")
    value = re.sub(r"\s*/\s*", "/", value)
    return value


def document_numbers(text: Any) -> list[str]:
    return list(dict.fromkeys(normalize_number(m.group(0)) for m in DOC_NUMBER.finditer(clean(text))))


def parse_iso_date(value: Any) -> str:
    """Return YYYY-MM-DD only when one unambiguous date is present."""
    text = clean(value)
    if not text:
        return ""
    iso = ISO_DATE.fullmatch(text)
    if iso:
        year, month, day = (int(x) for x in iso.groups())
    else:
        matches = list(NUMERIC_DATE.finditer(text))
        word_matches = list(WORD_DATE.finditer(text))
        if len(matches) + len(word_matches) != 1:
            return ""
        match = (matches or word_matches)[0]
        day, month, year = (int(x) for x in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def relation_kind(text: str) -> str:
    lower = clean(text).lower()
    if NEGATED.search(lower) or CONTINUED.search(lower):
        return ""
    if "bãi bỏ" in lower:
        return "BAI_BO_MOT_PHAN" if PARTIAL.search(lower) else "BAI_BO_TOAN_BO"
    if "thay thế" in lower:
        return "THAY_THE_TOAN_BO"
    if "sửa đổi" in lower or "bổ sung" in lower:
        return "SUA_DOI_BO_SUNG"
    if "đình chỉ" in lower:
        return "DINH_CHI"
    if "hết hiệu lực" in lower:
        return "HET_THOI_HAN"
    return ""


def candidate(old_number: str, new_number: str, relation: str, source_url: str,
              evidence: str, origin: str, effect_date: str = "", direction: str = "",
              note: str = "") -> dict[str, Any]:
    seed = "|".join([normalize_number(old_number), normalize_number(new_number), relation,
                     effect_date, direction, clean(evidence).lower()])
    return {
        "old_number": normalize_number(old_number),
        "new_number": normalize_number(new_number),
        "relation_type": relation,
        "effect_date_candidate": effect_date,
        "evidence_text": clean(evidence)[:800],
        "evidence_origin": origin,
        "source_url": clean(source_url),
        "direction": direction,
        "note": note,
        "suggested_effect_status": "CHUA_XAC_MINH",
        "verification_status": "CHO_XAC_MINH",
        "confidence": "TRUNG_BINH" if origin == "clause" else "THAP",
        "requires_official_check": True,
        "event_key": hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24],
    }


def analyze_new_document(doc: dict[str, Any], lines: list[str] | None = None) -> list[dict[str, Any]]:
    """Make review candidates without making final legal-effect decisions.

    doc: existing step 08 process_document() output structure. `lines` is
    the on-page body text captured BEFORE opening the relationship tab.
    """
    current_doc = doc.get("current_doc") or {}
    current_number = normalize_number(doc.get("source_doc_number") or current_doc.get("so_hieu"))
    doc_url = clean(doc.get("url"))
    current_date = parse_iso_date(current_doc.get("ngay_hieu_luc", ""))
    result: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add(item: dict[str, Any]) -> None:
        if item["old_number"] and item["old_number"] != item["new_number"]:
            key = (item["old_number"], item["new_number"], item["relation_type"])
            current = result.get(key)
            if current is None or (item["evidence_origin"] == "clause" and current["evidence_origin"] != "clause"):
                result[key] = item

    for row in doc.get("luoc_do_data") or []:
        head = re.sub(r"\s*\(\d+\)\s*$", "", clean(row.get("heading"))).lower()
        if head not in RELATIONS:
            continue
        relation, direction = RELATIONS[head]
        item = clean(row.get("item"))
        for referenced in document_numbers(item):
            if referenced == current_number:
                continue
            old, new = (current_number, referenced) if direction == "current_old" else (referenced, current_number)
            if direction == "unknown":
                # Source does not specify whether the listed document is being
                # acted on by the current text. Keep a manual-review candidate.
                old, new = referenced, current_number
            add(candidate(old, new, relation, doc_url, item, "luoc_do",
                          direction=direction, note=f"Nhóm Lược đồ: {head}; cần xác định chiều quan hệ"))

    for line in lines or []:
        text = clean(line)
        if not text or len(text) > 1400:
            continue
        relation = relation_kind(text)
        if not relation:
            continue
        numbers = document_numbers(text)
        if not numbers:
            continue
        effect_date = parse_iso_date(text) or current_date
        for old_number in numbers:
            if old_number != current_number:
                add(candidate(old_number, current_number, relation, doc_url, text,
                              "clause", effect_date=effect_date,
                              direction="listed_old",
                              note="Trích từ câu có từ khóa; cần kiểm tra ngữ cảnh và điều khoản"))
    return sorted(result.values(), key=lambda x: (x["old_number"], x["relation_type"], x["event_key"]))

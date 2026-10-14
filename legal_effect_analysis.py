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



# GD2.02: relationships are suggestions, never verified legal conclusions.
# Scope references must occur in the action clause, not in "Điều 5." headings.
PARTIAL_SCOPE = re.compile(
    r"\b(?:một\s+phần|một\s+số\s+(?:điều|khoản|điểm|quy\s+định|nội\s+dung)|"
    r"(?:điểm\s+[a-zđ](?:\s+khoản\s+\d+)?|khoản\s+\d+|điều\s+\d+)|"
    r"quy\s+định\s+tại|cụm\s+từ|từ\s+ngữ|biểu\s+mẫu|phụ\s+lục\s+[IVXLCDM\d]+)\b",
    re.IGNORECASE,
)
ACTION_TOKEN = re.compile(
    r"bãi\s+bỏ|thay\s+thế|sửa\s+đổi|bổ\s+sung|đình\s+chỉ|"
    r"chấm\s+dứt\s+hiệu\s+lực|hết\s+hiệu\s+lực", re.IGNORECASE
)
ACTION_DATE = re.compile(
    r"(?:có\s+hiệu\s+lực(?:\s+thi\s+hành)?|hết\s+hiệu\s+lực|"
    r"chấm\s+dứt\s+hiệu\s+lực|bãi\s+bỏ|thay\s+thế|đình\s+chỉ)"
    r".{0,170}?(?:kể\s+)?từ\s+ngày\s+"
    r"(\d{1,2}/\d{1,2}/(?:19|20)\d{2}|"
    r"\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+(?:19|20)\d{2})",
    re.IGNORECASE
)
GENERAL_EFFECT_DATE = re.compile(
    r"(?:luật|bộ\s+luật|thông\s+tư|nghị\s+định|nghị\s+quyết|"
    r"quyết\s+định|pháp\s+lệnh)\s+này\s+có\s+hiệu\s+lực", re.IGNORECASE
)
PASSIVE_ACTION = re.compile(
    r"(?:bị|được)\s+(?:bãi\s+bỏ|thay\s+thế|sửa\s+đổi|bổ\s+sung)", re.IGNORECASE
)
ENUMERATION_CONTEXT = re.compile(
    r"(?:bãi\s+bỏ|thay\s+thế|sửa\s+đổi|bổ\s+sung|"
    r"văn\s+bản\s+bị\s+bãi\s+bỏ).{0,110}?"
    r"(?:các\s+văn\s+bản|văn\s+bản\s+sau\s+đây|danh\s+mục|sau\s+đây|:)|"
    r"danh\s+mục.{0,80}?văn\s+bản.{0,40}?(?:bị\s+)?bãi\s+bỏ",
    re.IGNORECASE,
)
LIST_ITEM = re.compile(r"^(?:(?:[a-zđ]\)|[-+*])\s*|\d+[.)]\s+)", re.IGNORECASE)
NEXT_CLAUSE = re.compile(r"^\d+\.\s+(?!\d{1,4}/)")
ARTICLE_TITLE = re.compile(r"^\s*Điều\s+\d+[a-zđ]?\s*[.:\-–]\s*", re.IGNORECASE)


def _strip_article_title(text: str) -> str:
    return ARTICLE_TITLE.sub("", clean(text), count=1)


def _explicit_date(text: str) -> str:
    """Only dates tied to a legal-effect phrase, never issuance or cited dates."""
    values = set()
    for match in ACTION_DATE.finditer(clean(text)):
        raw = match.group(1)
        parsed = parse_iso_date("ngày " + raw if "tháng" in raw.lower() else raw)
        if parsed:
            values.add(parsed)
    return next(iter(values)) if len(values) == 1 else ""


def _scope(text: str) -> tuple[str, str]:
    # Do not mistake the heading "Điều 5. Bãi bỏ..." for the affected article.
    action_text = _strip_article_title(text)
    verb = ACTION_TOKEN.search(action_text)
    if not verb:
        return "", "KHONG_RO"
    relevant = action_text[verb.end():]
    match = PARTIAL_SCOPE.search(relevant)
    if match:
        return clean(match.group(0)), "MOT_PHAN"
    if re.search(r"\btoàn\s+bộ\b", relevant, re.IGNORECASE):
        return "Toàn bộ văn bản", "TOAN_BO"
    if re.search(r"(?:các\s+)?văn\s+bản\s+sau\s+đây|"
                 r"(?:các\s+)?văn\s+bản\s+được\s+liệt\s+kê|"
                 r"danh\s+mục\s+văn\s+bản", relevant, re.IGNORECASE):
        return "Các văn bản liệt kê", "TOAN_BO_GIA_DINH"
    return "", "KHONG_RO"


def relation_kind(text: str) -> str:
    """Candidate *relation*, not a conclusion of legal validity."""
    content = _strip_article_title(text).lower()
    if NEGATED.search(content) or CONTINUED.search(content):
        return ""
    tokens = set()
    if re.search(r"bãi\s+bỏ", content):
        tokens.add("bai_bo")
    if re.search(r"thay\s+thế", content):
        tokens.add("thay_the")
    if re.search(r"sửa\s+đổi|bổ\s+sung", content):
        tokens.add("sua_doi")
    if re.search(r"đình\s+chỉ", content):
        tokens.add("dinh_chi")
    if re.search(r"hết\s+hiệu\s+lực|chấm\s+dứt\s+hiệu\s+lực", content):
        tokens.add("het_hieu_luc")
    if not tokens:
        return ""
    # Multiple distinct legal actions in one unstructured paragraph are
    # ambiguous: retain a candidate but never interpret as whole repeal.
    if len(tokens) > 1:
        # Updating provisions and replacing a *specified appendix* are
        # cumulative partial amendments, never full-document replacement.
        _, mixed_scope = _scope(content)
        if tokens == {"sua_doi", "thay_the"} and mixed_scope == "MOT_PHAN":
            return "SUA_DOI_BO_SUNG"
        return "KHAC"
    token = next(iter(tokens))
    _, scope_type = _scope(content)
    if token == "bai_bo":
        return "BAI_BO_MOT_PHAN" if scope_type == "MOT_PHAN" else "BAI_BO_TOAN_BO"
    if token == "thay_the":
        return "KHAC" if scope_type == "MOT_PHAN" else "THAY_THE_TOAN_BO"
    if token == "sua_doi":
        return "SUA_DOI_BO_SUNG"
    if token == "dinh_chi":
        return "DINH_CHI"
    return "HET_THOI_HAN"


def candidate(old_number: str, new_number: str, relation: str, source_url: str,
              evidence: str, origin: str, effect_date: str = "", direction: str = "",
              note: str = "", affected_scope: str = "", scope_type: str = "KHONG_RO",
              evidence_location: str = "", evidence_section_heading: str = "",
              effect_date_basis: str = "", direction_confidence: str = "CAN_XAC_MINH") -> dict[str, Any]:
    old_number, new_number = normalize_number(old_number), normalize_number(new_number)
    # Stable across minor changes to editorial wording and paragraph order.
    seed = "|".join([old_number, new_number, relation, clean(affected_scope).lower(),
                     effect_date, direction])
    return {
        "old_number": old_number,
        "new_number": new_number,
        "relation_type": relation,
        "effect_date_candidate": effect_date,
        "effect_date_basis": effect_date_basis,
        "affected_scope": affected_scope,
        "scope_type": scope_type,
        "evidence_text": clean(evidence)[:800],
        "evidence_origin": origin,
        "evidence_location": evidence_location,
        "evidence_section_heading": evidence_section_heading,
        "source_url": clean(source_url),
        "direction": direction,
        "direction_confidence": direction_confidence,
        "note": note,
        "suggested_effect_status": "CHUA_XAC_MINH",
        "verification_status": "CHO_XAC_MINH",
        "confidence": "TRUNG_BINH" if origin == "clause" and direction_confidence == "RO_RANG" else "THAP",
        "requires_official_check": True,
        "event_key": hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24],
    }


def _article_dates(blocks: list[dict[str, str]]) -> dict[str, str]:
    """Default article date only if one explicit general-effect rule, no exceptions."""
    grouped: dict[str, list[str]] = {}
    for block in blocks:
        section = block["section_heading"]
        if section and block["section_kind"] == "article":
            grouped.setdefault(section, []).append(block["text"])
    output = {}
    for section, texts in grouped.items():
        combined = " ".join(texts).lower()
        if re.search(r"\b(?:ngoại\s+trừ|trừ\s+trường\s+hợp|riêng|"
                     r"đối\s+với.{0,40}?(?:kể\s+)?từ\s+ngày)\b", combined):
            continue
        dates = {_explicit_date(t) for t in texts if GENERAL_EFFECT_DATE.search(t)}
        dates.discard("")
        if len(dates) == 1:
            output[section] = next(iter(dates))
    return output


def _number_roles(text: str, current_number: str, kind: str) -> list[tuple[str, str, str]]:
    """Find old/new pairs by grammar, not by the first citation on the page.

    Unknown actors intentionally produce no causal new_number.
    """
    action = ACTION_TOKEN.search(_strip_article_title(text))
    if not action:
        return []
    content = _strip_article_title(text)
    verb = ACTION_TOKEN.search(content)
    prefix, suffix = content[:verb.start()], content[verb.end():]
    before, after = document_numbers(prefix), document_numbers(suffix)
    # A substantive amendment can quote the text that will be inserted.
    # References following "như sau:" within quoted replacement text do
    # not name the direct object of the amending instrument.
    if kind == "SUA_DOI_BO_SUNG":
        quotation = re.search(r"\bnhư\s+sau\s*:", suffix, re.I)
        if quotation:
            after = document_numbers(suffix[:quotation.start()])
    # In an expiry clause, the subjects precede "hết hiệu lực".
    if kind == "HET_THOI_HAN" and before and not after:
        return [(number, current_number, "listed_old")
                for number in before if number != current_number]
    passive = bool(PASSIVE_ACTION.search(content[max(0, verb.start()-16):verb.end()+4]))
    agent = re.search(r"\b(?:bởi|bằng)\b", suffix, re.IGNORECASE)
    output = []
    if passive and before:
        old = before[-1]
        if agent:
            newest = document_numbers(suffix[agent.end():])
            new = newest[0] if newest else ""
        else:
            new = ""
        output.append((old, new, "nguon_cu_bi_tac_dong" if new else "unknown"))
        return output

    # "Bãi bỏ Thông tư A bằng Thông tư B" and similar forms.
    if agent and before == []:
        targets = document_numbers(suffix[:agent.start()])
        newest = document_numbers(suffix[agent.end():])
        if targets and newest:
            for old in targets:
                output.append((old, newest[0], "van_ban_tac_dong_duoc_neu_ro"))
            return output

    # If there is an explicit actor before the verb, and it is not the
    # scanned document, do not attribute this event to the scanned document.
    actor = before[-1] if before else ""
    linked_new = current_number if not actor or actor == current_number else ""
    for old in after:
        if old == actor or old == current_number:
            continue
        output.append((old, linked_new, "listed_old" if linked_new else "unknown"))
    return output


def _as_blocks(lines: list[Any] | None) -> list[dict[str, str]]:
    blocks = []
    for index, raw in enumerate(lines or []):
        item = raw if isinstance(raw, dict) else {"text": raw}
        text = clean(item.get("text", ""))
        if not text:
            continue
        blocks.append({
            "text": text,
            "section_heading": clean(item.get("section_heading", "")),
            "section_kind": clean(item.get("section_kind", "")),
            "location": clean(item.get("location", "")),
            "index": str(index),
        })
    return blocks


def analyze_new_document(doc: dict[str, Any], lines: list[Any] | None = None) -> list[dict[str, Any]]:
    """Build *unverified* candidates from official clauses and Lược đồ.

    Inputs are source-scoped evidence blocks (GD2.01) or legacy strings.
    No final legal statuses, writes, network calls, or unconditional dates.
    """
    current_doc = doc.get("current_doc") or {}
    current_number = normalize_number(doc.get("source_doc_number") or current_doc.get("so_hieu"))
    doc_url = clean(doc.get("url"))
    result: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}

    def add(item: dict[str, Any]) -> None:
        if not item["old_number"] or item["old_number"] == item["new_number"]:
            return
        key = (item["old_number"], item["new_number"], item["relation_type"],
               item["affected_scope"].lower(), item["effect_date_candidate"])
        prev = result.get(key)
        if prev is None or (item["evidence_origin"] == "clause" and prev["evidence_origin"] != "clause"):
            result[key] = item

    heading_relations = {
        "văn bản bị thay thế": ("THAY_THE_TOAN_BO", "listed_old"),
        "văn bản thay thế": ("THAY_THE_TOAN_BO", "current_old"),
        "văn bản bị bãi bỏ": ("BAI_BO_TOAN_BO", "listed_old"),
        "văn bản hết hiệu lực": ("KHAC", "unknown"),
        "văn bản sửa đổi, bổ sung": ("SUA_DOI_BO_SUNG", "listed_old"),
        "văn bản bị sửa đổi, bổ sung": ("SUA_DOI_BO_SUNG", "current_old"),
    }
    for row in doc.get("luoc_do_data") or []:
        heading = re.sub(r"\s*\(\d+\)\s*$", "", clean(row.get("heading"))).lower().strip(": ")
        if heading not in heading_relations:
            continue
        relation, direction = heading_relations[heading]
        item_text = clean(row.get("item"))
        for referenced in document_numbers(item_text):
            if referenced == current_number:
                continue
            if direction == "current_old":
                old, new = current_number, referenced
            elif direction == "listed_old":
                old, new = referenced, current_number
            else:
                old, new = referenced, ""  # no unsupported causality
            add(candidate(old, new, relation, doc_url, item_text, "luoc_do",
                          direction=direction, note=f"Lược đồ: {heading}; cần đối chiếu điều khoản",
                          direction_confidence="CAN_XAC_MINH"))

    blocks = _as_blocks(lines)
    # GD2.03 acceptance: if evidence has locations/section metadata,
    # the page title and preamble are NOT operative legal provisions.
    # Retain legacy string input for existing offline tests and crawlers.
    is_structured = any(
        isinstance(raw, dict) and (
            raw.get("section_kind") or raw.get("section_heading")
        ) for raw in (lines or [])
    )
    default_dates = _article_dates(blocks)
    active_context: tuple[str, str, int] | None = None
    for idx, block in enumerate(blocks):
        text = block["text"]
        section = block["section_heading"]
        if is_structured:
            in_article = (block["section_kind"] == "article"
                          and bool(re.match(r"^\s*Điều\s+\d+", section, re.I)))
            in_annex = (block["section_kind"] == "annex"
                        and bool(re.match(r"^\s*PHỤ\s+LỤC\b", section, re.I)))
            if not (in_article or in_annex):
                # Prevent misleading 'clause' events from the document title
                # (e.g. "Sửa đổi ... Thông tư 15/2020") or editorial prologue.
                active_context = None
                continue
        if NEGATED.search(text) or CONTINUED.search(text) or text.lower().startswith("căn cứ "):
            active_context = None
            continue

        # Never carry an enumerated action across articles or into another
        # numbered paragraph. A list item can still start with "a)" / "-".
        if active_context:
            cue, cue_section, cue_index = active_context
            if section != cue_section or idx - cue_index > 12 or (
                NEXT_CLAUSE.match(text) and not ENUMERATION_CONTEXT.search(text)
            ):
                active_context = None

        kind = relation_kind(text)
        nums = document_numbers(text)
        if (kind and not nums and ENUMERATION_CONTEXT.search(text)
                and not re.search(r"\bnhư\s+sau\s*:", text, re.I)):
            active_context = (text, section, idx)
            continue

        origin_text = text
        if not kind and nums and active_context and (LIST_ITEM.match(text) or
                                                      block["section_kind"] == "annex"):
            kind = relation_kind(active_context[0])
            origin_text = active_context[0] + " " + text
        elif kind and nums:
            active_context = None

        if not kind or not nums:
            continue
        # A referenced legal document in quoted/amended replacement wording
        # is not itself the direct object of the source document's amendment.
        if (kind == "SUA_DOI_BO_SUNG" and text.lstrip().startswith(("-", "“", '"'))
                and not re.search(r"\b(?:sửa\s+đổi|bổ\s+sung)\b", text, re.I)):
            continue
        scope, scope_type = _scope(origin_text)
        # Do not infer full-document replacement from affected "khoản/điều".
        if kind == "THAY_THE_TOAN_BO" and scope_type == "MOT_PHAN":
            kind = "KHAC"
        date_effect = _explicit_date(origin_text)
        basis = "trong_dieu_khoan" if date_effect else ""
        if not date_effect and section in default_dates and kind != "KHAC":
            date_effect = default_dates[section]
            basis = "hieu_luc_chung_cung_dieu"
        # Contextual list items lack a local verb: use the action in the
        # enumerated heading while looking up numbers in the current item.
        if origin_text != text:
            role_text = active_context[0] + " " + text
        else:
            role_text = text
        pairs = _number_roles(role_text, current_number, kind)
        # If a bare enumeration has no ordinary verb/actor, retain a manual
        # candidate with explicitly unknown direction.
        if not pairs and origin_text != text:
            pairs = [(number, current_number, "listed_old") for number in nums if number != current_number]
        for old, new, direction in pairs:
            notes = ["Điều khoản nguồn chưa được xác minh pháp lý"]
            if direction == "unknown":
                notes.append("Chưa chứng minh chiều quan hệ văn bản cũ-mới")
            if kind == "KHAC":
                notes.append("Phạm vi hoặc nhiều hành vi trong cùng đoạn chưa rõ")
            if basis == "hieu_luc_chung_cung_dieu":
                notes.append("Ngày áp dụng được suy ra từ hiệu lực chung cùng điều; cần kiểm tra ngoại lệ")
            add(candidate(
                old, new, kind, doc_url, origin_text, "clause", date_effect,
                direction, "; ".join(notes), affected_scope=scope, scope_type=scope_type,
                evidence_location=block["location"], evidence_section_heading=section,
                effect_date_basis=basis,
                direction_confidence="RO_RANG" if direction != "unknown" else "CAN_XAC_MINH",
            ))
    return sorted(result.values(), key=lambda x: (x["old_number"], x["new_number"],
                                                   x["relation_type"], x["event_key"]))

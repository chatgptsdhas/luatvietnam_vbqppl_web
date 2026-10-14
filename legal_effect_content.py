"""Extract legally relevant paragraphs from the original document, not page chrome.

GD2.01: This module reads the rendered DOM *before* switching to Luoc do.
It is deliberately fail-closed: missing/ambiguous source roots produce no
clause-based legal-effect candidates, never a fallback to the whole <body>.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

# Prefer a tight, documented-content container. More selectors can be added
# only when a real HTML capture is verified; do not default to generic <main>.
DOCUMENT_ROOT_SELECTORS = (
    "#content_van_ban", "#content-van-ban", "#noidungvanban",
    "#noiDungVanBan", "#chinhvan", "#toanvan", "#toan-van",
    "#vb-content", ".content-vb", ".content-vanban",
    ".vanban-content", ".noi-dung-van-ban", ".noidungvanban",
    ".doc-content", ".document-content", ".content-document",
    ".fulltext-content", ".full-text-content", ".law-document-content",
    ".content-vbpl", ".chinh-van", ".toan-van",
)

DROP_TAGS = ("nav", "footer", "aside", "script", "style", "noscript", "iframe", "form", "button")
DROP_CLASS_FRAGMENT = re.compile(
    r"(?:menu|breadcrumb|sidebar|advert|quangcao|share|social|toolbar|tracking|"
    r"luocdo|luoc-do|comment|related|tooltip|popup|newsletter|action[-_]?bar)", re.I,
)
OFFICIAL_MASTHEAD = re.compile(
    r"(?:CỘNG\s+HÒA\s+XÃ\s+HỘI\s+CHỦ\s+NGHĨA|Độc\s+lập\s*[-–]\s*Tự\s+do)", re.I,
)
DOCUMENT_HEADER = re.compile(
    r"(?:CỘNG\s+HÒA\s+XÃ\s+HỘI\s+CHỦ\s+NGHĨA|Độc\s+lập\s*[-–]\s*Tự\s+do|"
    r"(?:Luật|Nghị\s+định|Thông\s+tư|Nghị\s+quyết|Quyết\s+định)\s+số\s*[:：])", re.I,
)
ARTICLE = re.compile(r"^\s*Điều\s+(\d+[a-zđ]?)\s*(?:[.:\-–]\s*|$)", re.I)
ANNEX = re.compile(r"^\s*PHỤ\s+LỤC(?:\s+([IVXLCDM\d]+))?\b", re.I)
RELEVANT = re.compile(
    r"(?:hiệu\s+lực(?:\s+thi\s+hành)?|điều\s+khoản\s+thi\s+hành|"
    r"quy\s+định\s+chuyển\s+tiếp|bãi\s+bỏ|thay\s+thế|sửa\s+đổi|bổ\s+sung|"
    r"chấm\s+dứt\s+hiệu\s+lực|đình\s+chỉ|tổ\s+chức\s+thực\s+hiện)", re.I,
)
DOC_NUMBER = re.compile(r"\b\d{1,4}/(?:19|20)\d{2}/[A-ZÀ-ỸĐ][A-ZÀ-ỸĐ0-9-]+", re.I)
PARAGRAPH_TAGS = {"p", "li", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6"}
# VBPL modern "Nội dung" tab can show HTML without the national masthead.
# A title plus the legal enacting preamble, not the surrounding UI, provides
# the structural boundary; a page title or status badge alone is never proof.
OFFICIAL_DOC_TITLE = re.compile(r"^(?:THÔNG\s+TƯ|NGHỊ\s+ĐỊNH|QUYẾT\s+ĐỊNH|LUẬT|NGHỊ\s+QUYẾT|BỘ\s+LUẬT)$", re.I)
MAX_HTML_BYTES = 8_000_000
MAX_EVIDENCE_BLOCKS = 3000
MAX_PARAGRAPH_CHARS = 2400


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _is_chrome(tag: Tag) -> bool:
    if tag.name in DROP_TAGS:
        return True
    if tag.get("hidden") is not None or tag.get("aria-hidden") == "true":
        return True
    if tag.get("role") in ("navigation", "complementary"):
        return True
    css = " ".join(str(x) for x in tag.get("class", []))
    return bool(DROP_CLASS_FRAGMENT.search(css))


def _sanitized_clone(soup: BeautifulSoup, element: Tag) -> Tag:
    """Destroy chrome only in a detached copy, not in the caller's DOM."""
    fragment = BeautifulSoup(str(element), "html.parser")
    root = fragment.find(element.name)
    for node in list(root.find_all(True)):
        if node.parent is not None and _is_chrome(node):
            node.decompose()
    return root


def _paragraphs(root: Tag) -> list[str]:
    output = []
    # Most official documents use <p>; some HTML/PDF conversions use leaf divs.
    for node in root.find_all(True):
        if node.name in PARAGRAPH_TAGS:
            if any(p.name in PARAGRAPH_TAGS for p in node.parents if p is not root):
                continue
        elif node.name in ("div", "section"):
            if node.find(list(PARAGRAPH_TAGS) + ["div", "section"]):
                continue
        else:
            continue
        text = clean_text(node.get_text(" ", strip=True))
        if text:
            output.append(text)
    return output


def _legal_root_ok(text: str, paragraphs: list[str]) -> bool:
    article_count = sum(bool(ARTICLE.match(p)) for p in paragraphs)
    has_header = bool(DOCUMENT_HEADER.search(text))
    # A genuine official text is much stronger than an editorial summary.
    return len(text) >= 160 and (article_count >= 2 or (has_header and article_count >= 1))


def _choose_root(soup: BeautifulSoup) -> tuple[Tag | None, str]:
    eligible: list[tuple[int, int, Tag, str]] = []
    for rank, selector in enumerate(DOCUMENT_ROOT_SELECTORS):
        for node in soup.select(selector):
            if not isinstance(node, Tag) or _is_chrome(node):
                continue
            cloned = _sanitized_clone(soup, node)
            paragraphs = _paragraphs(cloned)
            text = clean_text(cloned.get_text(" ", strip=True))
            if _legal_root_ok(text, paragraphs):
                eligible.append((rank, len(text), node, selector))
    if eligible:
        # Only explicitly named legal containers may be selected by CSS.
        rank, _, node, selector = min(eligible, key=lambda x: (x[0], x[1]))
        return node, selector

    # Conservative structural fallback: choose the smallest div/section/article
    # with a genuine official header and >=2 article headings. Never body/main.
    structural: list[tuple[int, Tag]] = []
    for node in soup.select("div, section, article"):
        if _is_chrome(node):
            continue
        text = clean_text(node.get_text(" ", strip=True))
        if len(text) < 80 or len(text) > 1_700_000:
            continue
        if not OFFICIAL_MASTHEAD.search(text):
            continue
        sanitized = _sanitized_clone(soup, node)
        paragraphs = _paragraphs(sanitized)
        if sum(bool(ARTICLE.match(p)) for p in paragraphs) >= 2:
            structural.append((len(text), node))
    if structural:
        return min(structural, key=lambda x: x[0])[1], "structural_document_root"

    # VBPL renders the full text directly under its "Nội dung" tab. Some
    # current HTML versions omit the national masthead. Require a genuine
    # legal-document prologue *before* multiple article headings to avoid
    # treating the page menu, summaries and relationship tabs as full text.
    vbpl_roots: list[tuple[int, Tag]] = []
    for node in soup.select("div, section, article, [role='tabpanel']"):
        if _is_chrome(node):
            continue
        sanitized = _sanitized_clone(soup, node)
        paragraphs = _paragraphs(sanitized)
        article_indexes = [i for i, part in enumerate(paragraphs) if ARTICLE.match(part)]
        if len(article_indexes) < 2:
            continue
        prior = paragraphs[:article_indexes[0]]
        preamble = " ".join(prior)
        # An editorial page may mention "Điều 1", but lacks the formal
        # enactment preamble and isolated legal document type heading.
        has_type_heading = any(OFFICIAL_DOC_TITLE.fullmatch(part) for part in prior)
        if not (has_type_heading and re.search(r"\bCăn\s+cứ\b", preamble, re.I)
                and re.search(r"\bban\s+hành\b", preamble, re.I)):
            continue
        text_len = len(sanitized.get_text(" ", strip=True))
        if 250 <= text_len <= 1_700_000:
            vbpl_roots.append((text_len, node))
    if vbpl_roots:
        return min(vbpl_roots, key=lambda x: x[0])[1], "structural_vbpl_rendered_root"
    return None, ""


def extract_legal_effect_evidence_from_html(html: str) -> dict[str, Any]:
    """Return source-positioned paragraphs; never classify legal effect."""
    if not isinstance(html, str) or not html.strip() or len(html.encode("utf-8")) > MAX_HTML_BYTES:
        return {"status": "source_unavailable", "root_selector": "", "blocks": [], "truncated": False}
    soup = BeautifulSoup(html, "html.parser")
    root, root_selector = _choose_root(soup)
    if root is None:
        return {"status": "document_root_not_found", "root_selector": "", "blocks": [], "truncated": False}
    paragraphs = _paragraphs(_sanitized_clone(soup, root))
    # A broad content wrapper may also contain a publisher's synopsis BEFORE
    # the official text. Do not let that synopsis generate clause evidence.
    masthead_index = next((i for i, part in enumerate(paragraphs)
                           if OFFICIAL_MASTHEAD.search(part)), None)
    title_index = next((i for i, part in enumerate(paragraphs)
                        if OFFICIAL_DOC_TITLE.fullmatch(part)), None)
    # For the modern VBPL text panel, omit the page synopsis preceding
    # the actual official "THÔNG TƯ" (or equivalent) document heading.
    if root_selector == "structural_vbpl_rendered_root":
        start_index = title_index if title_index is not None else 0
    else:
        start_index = masthead_index if masthead_index is not None else 0
    evidence: list[dict[str, Any]] = []
    section = ""
    section_kind = ""
    section_relevant = False
    waiting_article_title = False
    truncated = False
    for idx in range(start_index, len(paragraphs)):
        text = paragraphs[idx]
        article = ARTICLE.match(text)
        annex = ANNEX.match(text)
        if article:
            section = text
            section_kind = "article"
            waiting_article_title = bool(re.fullmatch(r"\s*Điều\s+\d+[a-zđ]?\s*[.:\-–]?\s*", text, re.I))
            section_relevant = bool(RELEVANT.search(section))
        elif annex:
            section = text
            section_kind = "annex"
            section_relevant = True
            waiting_article_title = False
        elif waiting_article_title:
            # Some publishers split "Điều 99." and "Hiệu lực thi hành".
            if len(text) <= 160:
                section = section + " " + text
                section_relevant = bool(RELEVANT.search(section))
            waiting_article_title = False

        # Only source paragraphs from the official text root; keep the entire
        # relevant article / appendix so list entries do not lose their context.
        if not (section_relevant or RELEVANT.search(text) and (section_kind == "article" or DOC_NUMBER.search(text))):
            continue
        if len(text) > MAX_PARAGRAPH_CHARS:
            truncated = True
            continue
        if len(evidence) >= MAX_EVIDENCE_BLOCKS:
            truncated = True
            break
        evidence.append({
            "text": text,
            "paragraph_index": idx,
            "location": f"{root_selector}:paragraph[{idx}]",
            "section_heading": section,
            "section_kind": section_kind or "clause",
            "root_selector": root_selector,
        })
    return {
        "status": "ok" if evidence else "no_relevant_clauses",
        "root_selector": root_selector,
        "blocks": evidence,
        "paragraph_count": len(paragraphs),
        "evidence_count": len(evidence),
        "truncated": truncated,
    }


def extract_legal_effect_evidence(page) -> dict[str, Any]:
    """Read rendered HTML while the original 'Nội dung' tab is still open."""
    try:
        return extract_legal_effect_evidence_from_html(page.content())
    except Exception:
        # Deliberately do not leak page HTML, cookies or stack trace to logs.
        return {"status": "source_unavailable", "root_selector": "", "blocks": [], "truncated": False}


def extract_rendered_vbpl_evidence(page, timeout_ms: int = 15000) -> dict[str, Any]:
    """Read VBPL DOM after JavaScript hydration. No bypass for HTTP 403.

    Browser readiness uses body text only as a signal; legal evidence is
    extracted exclusively from a validated *document root* in page.content().
    """
    try:
        result = extract_legal_effect_evidence_from_html(page.content())
        if result.get("status") == "ok":
            return result
        page.wait_for_function(
            r"""() => {
              const content = document.body?.innerText || '';
              return /Điều\s+\d+\s*[.:-]/i.test(content)
                && /(?:Thông\s+tư|Nghị\s+định|Luật|Quyết\s+định)/i.test(content);
            }""",
            timeout=timeout_ms,
        )
        return extract_legal_effect_evidence_from_html(page.content())
    except Exception:
        # The caller decides whether a website refused browser automation.
        # No fallback to headings, metadata or body text as legal evidence.
        return {"status": "rendered_document_unavailable", "root_selector": "",
                "blocks": [], "truncated": False}

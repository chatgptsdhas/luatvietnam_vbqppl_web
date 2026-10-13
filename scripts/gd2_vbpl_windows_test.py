"""GD2.03 Windows/CocCoc read-only LIVE browser acceptance test.

Runs on an operator-controlled Windows desktop with normal site access.
Uses a NEW temporary browser profile. Never reuses/exports real profiles,
cookies, localStorage, tokens, page HTML, or whole-body text. No API writes.
The test does NOT bypass 403, challenges or access controls.

Example:
  python scripts/gd2_vbpl_windows_test.py
  python scripts/gd2_vbpl_windows_test.py --browser-path "C:\Program Files\CocCoc\Browser\Application\browser.exe"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_effect_analysis import analyze_new_document, document_numbers, normalize_number
from legal_effect_content import extract_legal_effect_evidence_from_html
from legal_effect_official import canonical_official_url

TEST_URL = (
    "https://vbpl.vn/van-ban/chi-tiet/"
    "thong-tu-so-05-2021-tt-bgddt-sua-doi-bo-sung-mot-so-dieu-cua-"
    "quy-che-thi-tot-nghiep-trung-hoc-pho-thong-ban-hanh-kem-theo-"
    "thong-tu-so-15-2020-tt-bgddt-ngay-26-thang-5-nam-2020-cua-"
    "bo-truong-bo-giao-duc-va-dao-tao--147477"
)
NEW_NUMBER = "05/2021/TT-BGDĐT"
OLD_NUMBER = "15/2020/TT-BGDĐT"
EXPECTED_RELATION = "SUA_DOI_BO_SUNG"
OUTFILE = Path("output/gd2-windows-vbpl-test.json")


def find_installed_browser() -> Path | None:
    """Prefer local Cốc Cốc; use Chrome/Edge only when Cốc Cốc unavailable."""
    bases = [
        ("LOCALAPPDATA", "CocCoc/Browser/Application/browser.exe"),
        ("PROGRAMFILES", "CocCoc/Browser/Application/browser.exe"),
        ("PROGRAMFILES(X86)", "CocCoc/Browser/Application/browser.exe"),
        ("LOCALAPPDATA", "Google/Chrome/Application/chrome.exe"),
        ("PROGRAMFILES", "Google/Chrome/Application/chrome.exe"),
        ("PROGRAMFILES(X86)", "Microsoft/Edge/Application/msedge.exe"),
        ("PROGRAMFILES", "Microsoft/Edge/Application/msedge.exe"),
    ]
    for env_name, relative in bases:
        base = os.environ.get(env_name)
        if base:
            path = Path(base) / relative
            if path.is_file():
                return path
    return None


def evaluate_rendered_document(html: str, page_title: str, page_url: str,
                               http_status: int | None) -> dict:
    """Offline-pure oracle for the SAME production GD2 document extractor."""
    result = {
        "http_status": http_status,
        "site": urlsplit(page_url).hostname,
        "document_number_expected": NEW_NUMBER,
        "impacted_number_expected": OLD_NUMBER,
        "relation_expected": EXPECTED_RELATION,
        "document_title_matches": NEW_NUMBER in document_numbers(page_title),
        "extraction_status": "not_evaluated",
        "source_root": "",
        "evidence_blocks": 0,
        "matched_events": [],
        "outcome": "UNCONFIRMED",
        "requires_legal_review": True,
        "production_writes": False,
    }
    # Site controls have not been circumvented: a refused browser is failure.
    if http_status is not None and http_status != 200:
        result["outcome"] = "SITE_ACCESS_DENIED" if http_status in (401, 403, 429) else "SITE_HTTP_ERROR"
        return result
    if urlsplit(page_url).hostname != "vbpl.vn":
        result["outcome"] = "UNEXPECTED_SITE"
        return result
    extraction = extract_legal_effect_evidence_from_html(html)
    result["extraction_status"] = extraction["status"]
    result["source_root"] = extraction.get("root_selector", "")
    blocks = extraction.get("blocks", [])
    result["evidence_blocks"] = len(blocks)
    if not blocks:
        result["outcome"] = "DOCUMENT_NOT_RENDERED_OR_PARSER_INCOMPATIBLE"
        return result
    # Page title is an identity cross-check, not a substitute for an
    # authenticated legal clause or full-text document root.
    if not result["document_title_matches"]:
        result["outcome"] = "DOCUMENT_IDENTITY_NEEDS_REVIEW"
        return result
    events = analyze_new_document(
        {"source_doc_number": NEW_NUMBER, "url": page_url, "luoc_do_data": []},
        lines=blocks,
    )
    matches = [
        item for item in events
        if item["old_number"] == OLD_NUMBER
        and item["new_number"] == NEW_NUMBER
        and item["relation_type"] == EXPECTED_RELATION
        and item["evidence_origin"] == "clause"
    ]
    result["matched_events"] = [
        {
            "event_key": event["event_key"],
            "relation_type": event["relation_type"],
            "evidence_location": event["evidence_location"],
            "source_section": event["evidence_section_heading"][:160],
            "scope_type": event["scope_type"],
            "verification_status": event["verification_status"],
        }
        for event in matches[:12]
    ]
    result["outcome"] = ("PROVISIONAL_PASS_PENDING_LEGAL" if matches
                         else "RELATION_CANDIDATE_NOT_FOUND")
    return result


def run_live(url: str, browser_path: Path | None, timeout_seconds: int) -> dict:
    """Use a visible, isolated browser; never attach to the user's real profile."""
    from playwright.sync_api import sync_playwright

    canonical = canonical_official_url(url)
    browser_path = browser_path or find_installed_browser()
    if browser_path is None or not browser_path.is_file():
        return {
            "outcome": "BROWSER_NOT_FOUND",
            "reason": "Install Cốc Cốc or specify --browser-path for the local browser executable.",
            "requires_legal_review": True,
            "production_writes": False,
        }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_path),
            headless=False,
            timeout=30000,
        )
        try:
            context = browser.new_context(accept_downloads=False)
            page = context.new_page()
            response = page.goto(canonical, wait_until="domcontentloaded", timeout=45000)
            response_code = response.status if response else None
            if response_code in (401, 403, 429):
                return evaluate_rendered_document("", page.title(), page.url, response_code)
            # Do not infer success from DOMContentLoaded: modern VBPL
            # hydrates its "Nội dung" panel AFTER the initial HTML response.
            deadline = time.monotonic() + timeout_seconds
            latest = None
            while time.monotonic() < deadline:
                latest = evaluate_rendered_document(
                    page.content(), page.title(), page.url, response_code,
                )
                if latest["outcome"] == "PROVISIONAL_PASS_PENDING_LEGAL":
                    return latest
                # Loading/challenge screens must not be interpreted as data.
                if latest["outcome"] in ("SITE_ACCESS_DENIED", "UNEXPECTED_SITE"):
                    return latest
                page.wait_for_timeout(2000)
            return latest or {
                "outcome": "PAGE_WAIT_TIMEOUT", "production_writes": False,
                "requires_legal_review": True,
            }
        finally:
            browser.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=TEST_URL)
    parser.add_argument("--browser-path", type=Path, help="Path to installed CocCoc/Chrome/Edge exe")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, default=OUTFILE)
    args = parser.parse_args(argv)
    if not 10 <= args.timeout_seconds <= 180:
        parser.error("--timeout-seconds must be between 10 and 180")
    try:
        result = run_live(args.url, args.browser_path, args.timeout_seconds)
    except Exception as exc:
        # Intentionally never print URL query, network content or exception text.
        result = {
            "outcome": "TEST_RUNTIME_ERROR",
            "error_type": type(exc).__name__,
            "requires_legal_review": True,
            "production_writes": False,
        }
    result["test_time_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "outcome": result["outcome"],
        "extraction_status": result.get("extraction_status"),
        "evidence_blocks": result.get("evidence_blocks", 0),
        "matched_events": len(result.get("matched_events", [])),
        "report_file": str(args.output),
    }, ensure_ascii=False))
    return 0 if result["outcome"] == "PROVISIONAL_PASS_PENDING_LEGAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())

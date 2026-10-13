"""Read-only live VBPL probe on a GitHub-hosted runner.

No Apps Script, Planner, secrets, database updates, or browser sessions.
This is a diagnostic only; a passing HTTP response is not legal confirmation.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_effect_official import (
    canonical_official_url,
    fetch_official_html,
    official_fetch_targets,
    official_html_check,
)
from legal_effect_content import extract_legal_effect_evidence_from_html


def run_probe(input_url: str, official_print_url: str, output: Path) -> dict:
    scanned_number = "05/2021/TT-BGDĐT"
    source_number = "15/2020/TT-BGDĐT"
    event = {
        "old_number": source_number,
        "new_number": scanned_number,
        "relation_type": "SUA_DOI_BO_SUNG",
        "event_key": "gd2-03-147477-modification",
    }
    targets = official_fetch_targets(input_url)
    if official_print_url:
        known_print = canonical_official_url(official_print_url)
        if known_print not in targets:
            targets.append(known_print)

    rows = []
    for target in targets:
        result = {"url": target, "http": "UNKNOWN", "official_check": ""}
        try:
            html = fetch_official_html(target, timeout_seconds=15)
            result["http"] = "200_HTML"
            result["bytes_received"] = len(html.encode("utf-8"))
            extraction = extract_legal_effect_evidence_from_html(html)
            result["extraction_status"] = extraction.get("status", "unknown")
            result["evidence_blocks"] = extraction.get("evidence_count", 0)
            checked = official_html_check(event, target, html)
            result["official_check"] = checked["status"]
            result["official_number"] = checked.get("source_document_number", "")
            result["relation_found"] = checked.get("observed_relation", "")
            result["scope_found"] = checked.get("observed_scope", "")
            result["date_found"] = checked.get("observed_date", "")
            result["evidence_digest"] = checked.get("source_evidence_sha256", "")
            result["legal_review_required"] = checked.get("requires_legal_review", True)
        except ValueError as exc:
            # Only internal constant error codes, not raw stack traces/headers/HTML.
            reason = str(exc)
            result["http"] = reason if reason.startswith(("OFFICIAL_", "INVALID_")) else "UNEXPECTED_RETRIEVAL_ERROR"
            result["official_check"] = "NOT_EVALUATED"
        except Exception:
            result["http"] = "UNEXPECTED_RETRIEVAL_ERROR"
            result["official_check"] = "NOT_EVALUATED"
        rows.append(result)
        # Output stays bounded; never print fetched legal text, cookies or URLs with credentials.
        print(json.dumps(result, ensure_ascii=False))

    acceptable = {
        "OFFICIAL_ACTION_MATCHED_PENDING_LEGAL",
        "OFFICIAL_SCOPE_NEEDS_REVIEW",
    }
    matching = [r for r in rows if r.get("official_check") in acceptable]
    retrieved = [r for r in rows if r.get("http") == "200_HTML"]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "READ_ONLY_GITHUB_HOSTED_LIVE_TEST",
        "test_case": "05/2021/TT-BGDĐT amends 15/2020/TT-BGDĐT",
        "test_outcome": (
            "LIVE_RELATION_FOUND_NEEDS_LEGAL_REVIEW" if matching else
            "LIVE_HTML_RETRIEVED_PARSER_UNCONFIRMED" if retrieved else
            "LIVE_SOURCE_UNREACHABLE"
        ),
        "legal_confirmation": False,
        "production_untouched": True,
        "checked_urls": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OVERALL " + report["test_outcome"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--known-print-url", default="")
    parser.add_argument("--output", type=Path, default=Path("output/gd2-server-probe.json"))
    args = parser.parse_args()
    report = run_probe(args.url, args.known_print_url, args.output)
    # The diagnostic job must fail if it cannot substantiate the test case.
    return 0 if report["test_outcome"] == "LIVE_RELATION_FOUND_NEEDS_LEGAL_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())

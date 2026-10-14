"""GD2.05 — read-only multi-document acceptance test on authorized Windows browser.

Separates retrieval/coverage, extraction, provisional relations, and human-
labelled correctness. There are NO official legal conclusions or production
writes. Run only on a machine where VBPL allows ordinary browser access.
Never use existing browser profiles, saved sessions, cookies, or secrets.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from gd2_vbpl_windows_test import find_installed_browser
from legal_effect_analysis import analyze_new_document, document_numbers, normalize_number
from legal_effect_content import extract_legal_effect_evidence_from_html
from legal_effect_official import canonical_official_url

KNOWN_RELATIONS = frozenset((
    "SUA_DOI_BO_SUNG", "BAI_BO_MOT_PHAN", "BAI_BO_TOAN_BO",
    "THAY_THE_TOAN_BO", "HET_THOI_HAN", "KHAC", "DINH_CHI",
))
NUMBER_SHAPE = re.compile(
    r"^\d{1,4}/(?:19|20)\d{2}/[A-ZÀ-ỸĐ0-9]+(?:-[A-ZÀ-ỸĐ0-9]+)*$", re.I
)
MAX_CASES = 30


def load_manifest(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list) or not cases or len(cases) > MAX_CASES:
        raise ValueError("INVALID_CASE_COUNT")
    result = []
    seen = set()
    for row in cases:
        if not isinstance(row, dict):
            raise ValueError("INVALID_CASE_OBJECT")
        case_id = str(row.get("id") or "").strip()
        url = canonical_official_url(row.get("url"))
        new = normalize_number(row.get("new_number"))
        old = normalize_number(row.get("old_number"))
        relation = str(row.get("expected_relation") or "").strip()
        label = str(row.get("label_status") or "PENDING_HUMAN").strip()
        probe_kind = str(row.get("probe_kind") or "POSITIVE_CANDIDATE")
        review_hint = str(row.get("review_hint") or "").strip()
        truth = row.get("expected_present")
        basis = str(row.get("label_basis") or "").strip()
        if not case_id or len(case_id) > 100 or case_id in seen:
            raise ValueError("DUPLICATE_OR_MISSING_CASE_ID")
        if not (NUMBER_SHAPE.fullmatch(new) and NUMBER_SHAPE.fullmatch(old)):
            raise ValueError("INVALID_CASE_NUMBER")
        if old == new or relation not in KNOWN_RELATIONS:
            raise ValueError("INVALID_CASE_RELATION")
        if probe_kind not in ("POSITIVE_CANDIDATE", "NEGATIVE_CONTROL_CANDIDATE"):
            raise ValueError("INVALID_PROBE_KIND")
        if len(review_hint) > 300:
            raise ValueError("REVIEW_HINT_TOO_LONG")
        if label not in ("PENDING_HUMAN", "HUMAN_VERIFIED"):
            raise ValueError("INVALID_CASE_LABEL_STATUS")
        if label == "HUMAN_VERIFIED":
            if not isinstance(truth, bool) or not basis or len(basis) > 300:
                raise ValueError("HUMAN_LABEL_REQUIRES_BOOLEAN_TRUTH_AND_BASIS")
        elif truth is not None or basis:
            # Pending cases must not quietly carry an unreviewed truth value.
            raise ValueError("PENDING_LABEL_MUST_NOT_HAVE_TRUTH")
        seen.add(case_id)
        result.append({
            "id": case_id, "url": url, "new_number": new, "old_number": old,
            "expected_relation": relation, "label_status": label,
            "expected_present": truth, "label_basis": basis,
            "probe_kind": probe_kind, "review_hint": review_hint,
        })
    return result


def evaluate_case(case: dict, html: str, title: str,
                  final_url: str, http_status: int | None) -> dict:
    output = {
        "id": case["id"], "site": urlsplit(final_url).hostname,
        "http_status": http_status, "extraction_status": "not_evaluated",
        "evidence_blocks": 0, "matches": [], "result": "UNCONFIRMED",
        "label_status": case["label_status"],
        "probe_kind": case.get("probe_kind", "POSITIVE_CANDIDATE"),
        "requires_legal_review": True,
    }
    if http_status != 200:
        output["result"] = "ACCESS_DENIED" if http_status in (401, 403, 429) else "HTTP_ERROR"
        return output
    try:
        canonical_official_url(final_url)
    except ValueError:
        output["result"] = "UNTRUSTED_REDIRECT"
        return output
    if case["new_number"] not in document_numbers(title):
        output["result"] = "IDENTITY_UNCONFIRMED"
        return output

    extracted = extract_legal_effect_evidence_from_html(html)
    output["extraction_status"] = extracted.get("status", "unknown")
    blocks = extracted.get("blocks") or []
    output["evidence_blocks"] = len(blocks)
    if not blocks:
        # A legally validated full-text root with no matching action clauses
        # is an admissible negative example, not a failure to read the page.
        if extracted.get("status") == "no_relevant_clauses" and extracted.get("root_selector"):
            output["result"] = "NO_MATCH"
        else:
            output["result"] = "NO_LEGAL_TEXT"
        return output
    events = analyze_new_document(
        {"source_doc_number": case["new_number"], "url": final_url, "luoc_do_data": []},
        lines=blocks,
    )
    matching = [
        e for e in events
        if e["new_number"] == case["new_number"]
        and e["old_number"] == case["old_number"]
        and e["relation_type"] == case["expected_relation"]
        and e["evidence_origin"] == "clause"
        and e.get("evidence_section_heading", "")
        and e.get("evidence_location", "")
    ]
    output["matches"] = [
        {
            "event_key": e["event_key"], "relation": e["relation_type"],
            "scope_type": e["scope_type"], "source_section": e["evidence_section_heading"][:150],
            "location": e["evidence_location"],
            "effect_date_candidate": e.get("effect_date_candidate", ""),
        }
        for e in matching[:12]
    ]
    # 'MATCH_PENDING_HUMAN' means only an observed provisional candidate.
    output["result"] = "MATCH_PENDING_HUMAN" if matching else "NO_MATCH"
    return output


def aggregate(cases: list[dict], results: list[dict]) -> dict:
    """Distinguish retrieval failures, provisional matches and reviewed labels.

    Precision/recall are intentionally hidden until ALL 30 cases have been
    independently labelled, both classes occur and their text was retrieved.
    An unreviewed association is never legal confirmation.
    """
    counts = Counter(r["result"] for r in results)
    by_id = {r["id"]: r for r in results}
    labelled = [c for c in cases if c["label_status"] == "HUMAN_VERIFIED"]
    evaluable = []
    missing = []
    for case in labelled:
        row = by_id.get(case["id"])
        if row is None or row["result"] not in ("MATCH_PENDING_HUMAN", "NO_MATCH"):
            missing.append(case["id"])
        else:
            evaluable.append((case, row))
    tp = sum(c["expected_present"] is True and r["result"] == "MATCH_PENDING_HUMAN"
             for c, r in evaluable)
    tn = sum(c["expected_present"] is False and r["result"] == "NO_MATCH"
             for c, r in evaluable)
    fp = sum(c["expected_present"] is False and r["result"] == "MATCH_PENDING_HUMAN"
             for c, r in evaluable)
    fn = sum(c["expected_present"] is True and r["result"] == "NO_MATCH"
             for c, r in evaluable)
    positive_count = tp + fn
    negative_count = tn + fp
    full_validation = (len(cases) == MAX_CASES
                       and len(labelled) == MAX_CASES
                       and len(evaluable) == MAX_CASES
                       and positive_count > 0 and negative_count > 0)
    return {
        "total_cases": len(cases),
        "cases_run": len(results),
        "http_200": sum(r.get("http_status") == 200 for r in results),
        "legal_text_extracted": sum(
            r.get("extraction_status") in ("ok", "no_relevant_clauses")
            for r in results
        ),
        "provisional_matches": counts["MATCH_PENDING_HUMAN"],
        "positive_candidate_cases": sum(
            c.get("probe_kind", "POSITIVE_CANDIDATE") == "POSITIVE_CANDIDATE"
            for c in cases
        ),
        "negative_control_candidate_cases": sum(
            c.get("probe_kind") == "NEGATIVE_CONTROL_CANDIDATE" for c in cases
        ),
        "negative_controls_without_match": sum(
            c.get("probe_kind") == "NEGATIVE_CONTROL_CANDIDATE"
            and by_id.get(c["id"], {}).get("result") == "NO_MATCH"
            for c in cases
        ),
        "human_labelled_cases": len(labelled),
        "human_labelled_evaluable_cases": len(evaluable),
        "human_labelled_not_evaluable_cases": len(missing),
        "human_labelled_matches": tp,
        "confusion_matrix": {
            "true_positive": tp, "true_negative": tn,
            "false_positive": fp, "false_negative": fn,
        },
        "classification_precision": (
            round(tp / (tp + fp), 4) if full_validation and (tp + fp) else None
        ),
        "classification_recall": (
            round(tp / positive_count, 4) if full_validation else None
        ),
        "match_recall_on_preselected_positive_cases": (
            round(tp / positive_count, 4)
            if positive_count and not missing else None
        ),
        "metrics_eligible": full_validation,
        "result_counts": dict(sorted(counts.items())),
        "legal_confirmation": False,
        "production_writes": False,
    }


def run_batch(cases: list[dict], browser_path: Path, timeout_seconds: int) -> list[dict]:
    from playwright.sync_api import sync_playwright
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_path), headless=False, timeout=30000
        )
        try:
            for case in cases:
                context = browser.new_context(accept_downloads=False)
                try:
                    page = context.new_page()
                    response = page.goto(case["url"], wait_until="domcontentloaded", timeout=45000)
                    status = response.status if response else None
                    deadline = time.monotonic() + timeout_seconds
                    latest = None
                    negative_stable = 0
                    while True:
                        latest = evaluate_case(case, page.content(), page.title(), page.url, status)
                        if latest["result"] in (
                            "MATCH_PENDING_HUMAN", "ACCESS_DENIED",
                            "HTTP_ERROR", "UNTRUSTED_REDIRECT",
                        ):
                            break
                        # A legal text with no match can be a correct negative.
                        # Confirm the rendered document remains stable for
                        # three polls before concluding no candidate exists.
                        if latest["result"] == "NO_MATCH":
                            negative_stable += 1
                            if negative_stable >= 3:
                                break
                        else:
                            negative_stable = 0
                        if time.monotonic() >= deadline:
                            break
                        page.wait_for_timeout(2000)
                    results.append(latest)
                except Exception as exc:
                    results.append({
                        "id": case["id"], "result": "BROWSER_ERROR",
                        "error_type": type(exc).__name__,
                        "site": "vbpl.vn", "http_status": None,
                        "extraction_status": "unknown", "evidence_blocks": 0,
                        "matches": [], "label_status": case["label_status"],
                        "requires_legal_review": True,
                    })
                finally:
                    context.close()
                # Modest read-only request cadence; no automatic retries for blocks.
                time.sleep(2)
        finally:
            browser.close()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path,
                        default=Path("docs/gd205_case_manifest.json"))
    parser.add_argument("--browser-path", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=40)
    parser.add_argument("--output", type=Path, default=Path("output/gd205-validation.json"))
    args = parser.parse_args()
    if not 10 <= args.timeout_seconds <= 180:
        parser.error("Invalid timeout")
    cases = load_manifest(args.manifest)
    executable = args.browser_path or find_installed_browser()
    if executable is None or not executable.is_file():
        parser.error("Browser not found; pass --browser-path")
    results = run_batch(cases, executable, args.timeout_seconds)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "GD2_05_WINDOWS_BROWSER_READONLY",
        "summary": aggregate(cases, results), "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=True))
    by_id = {r["id"]: r for r in results}
    success = True
    for case in cases:
        observed = by_id.get(case["id"])
        if not observed or observed["result"] not in ("MATCH_PENDING_HUMAN", "NO_MATCH"):
            success = False
        elif case["label_status"] == "HUMAN_VERIFIED":
            detected = observed["result"] == "MATCH_PENDING_HUMAN"
            if detected != case["expected_present"]:
                success = False
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())

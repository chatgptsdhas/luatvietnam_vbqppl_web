"""Read-only rendered VBPL test; never save cookies, HTML, or credentials."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from sys import path as syspath
syspath.insert(0, str(Path(__file__).resolve().parents[1]))
from legal_effect_official import canonical_official_url
from legal_effect_content import extract_legal_effect_evidence_from_html


def inspect_rendered(url: str) -> dict:
    url = canonical_official_url(url)
    result = {"url_host": urlsplit(url).hostname, "http_status": None}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(service_workers="block")
        # Only top-level allowed VBPL sources and static first-party assets.
        # Reject navigations/requests to private IPs and non-HTTPS URLs.
        def route_handler(route):
            target = route.request.url
            parts = urlsplit(target)
            host = (parts.hostname or "").lower()
            if parts.scheme == "https" and (host == "vbpl.vn" or host.endswith(".vbpl.vn") or host == "vbpl.moj.gov.vn"):
                route.continue_()
            else:
                route.abort()
        context.route("**/*", route_handler)
        page = context.new_page()
        response = page.goto(url, wait_until="domcontentloaded", timeout=35000)
        result["http_status"] = response.status if response else None
        page.wait_for_timeout(8000)
        result["rendered_host"] = urlsplit(page.url).hostname
        text = page.locator("body").inner_text(timeout=12000)
        result["visible_text_length"] = len(text)
        result["contains_self_number"] = "05/2021/TT-BGDĐT" in text
        result["contains_amended_number"] = "15/2020/TT-BGDĐT" in text
        result["contains_article1"] = bool(re.search(r"Điều\s+1[.:\s]", text, re.I))
        result["contains_official_masthead"] = "CỘNG HÒA XÃ HỘI" in text or "CỘNG HOÀ XÃ HỘI" in text
        html = page.content()
        result["dom_html_length"] = len(html)
        result["extraction"] = {k: v for k, v in extract_legal_effect_evidence_from_html(html).items() if k not in ("blocks",)}
        result["page_title"] = (page.title() or "")[:120]
        # Only bounded structural locations; no HTML content or cookies.
        soup = BeautifulSoup(html, "html.parser")
        nodes = []
        for tag in soup.select("iframe, article, main, [id], [class]"):
            txt = tag.get_text(" ", strip=True)
            if len(txt) > 150 and ("05/2021" in txt or "15/2020" in txt or "Điều 1" in txt):
                nodes.append({
                    "tag": tag.name,
                    "id": str(tag.get("id") or "")[:65],
                    "class": " ".join(tag.get("class") or [])[:90],
                    "len": len(txt),
                    "self_number": "05/2021" in txt,
                    "older_number": "15/2020" in txt,
                    "article1": "Điều 1" in txt,
                })
                if len(nodes) >= 12:
                    break
        result["candidate_nodes"] = nodes
        browser.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", default="output/gd2-playwright-diagnostic.json")
    args = parser.parse_args()
    try:
        report = inspect_rendered(args.url)
    except Exception as exc:
        report = {"error_code": type(exc).__name__, "step": "browser_render"}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("BROWSER_DIAGNOSTIC " + json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

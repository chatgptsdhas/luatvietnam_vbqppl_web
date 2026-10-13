"""Report safe structural signals of official VBPL HTML, never full page content.

Only bounded publicly accessible metadata/DOM structure. No credentials.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

import requests
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin, urlsplit
from pathlib import Path
from sys import path as syspath
syspath.insert(0, str(Path(__file__).resolve().parents[1]))
from legal_effect_official import canonical_official_url


def tag_selector(node: Tag) -> str:
    bits = []
    for el in [node] + list(node.parents)[:3]:
        if el.name in ("html", "body", "[document]"):
            break
        bits.append(
            el.name +
            (("#" + str(el.get("id"))[:65]) if el.get("id") else "") +
            (("." + ".".join(str(x)[:45] for x in el.get("class", [])[:3])) if el.get("class") else "")
        )
    return " > ".join(bits)


def inspect_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    fulltext = soup.get_text(" ", strip=True)
    patterns = ("05/2021", "15/2020", "Điều 1", "Sửa đổi, bổ sung", "CỘNG HÒA", "CỘNG HOÀ")
    found = {}
    for phrase in patterns:
        matches = []
        for t in soup.find_all(string=re.compile(re.escape(phrase), re.I)):
            if t.parent and t.parent.name in ("script", "style", "noscript"):
                continue
            if len(matches) < 10:
                matches.append(tag_selector(t.parent))
        found[phrase] = {
            "in_html": html.lower().count(phrase.lower()),
            "in_visible_dom": len(matches),
            "where": matches[:8],
        }
    elements = []
    for node in soup.select("main, article, section, iframe, [id], [class]"):
        if node.name in ("script", "style"):
            continue
        text = node.get_text(" ", strip=True)
        if not text or len(text) < 200:
            continue
        article_refs = len(re.findall(r"\bĐiều\s+[1-9]\d*", text, re.I))
        if article_refs or "05/2021" in text or "15/2020" in text:
            elements.append({
                "selector": tag_selector(node),
                "text_len": len(text),
                "article_refs": article_refs,
                "has_self_number": "05/2021" in text,
                "has_older_number": "15/2020" in text,
            })
        if len(elements) > 100:
            break
    frames = [
        {"tag": el.name,
         "url_host": urlsplit(urljoin("https://vbpl.vn", el.get("src", "") or el.get("href", ""))).hostname,
         "path_hint": urlsplit(el.get("src", "") or el.get("href", "")).path[:110]}
        for el in soup.find_all(["iframe", "embed", "object"])[:12]
    ]
    page_links = []
    for el in soup.find_all("a"):
        caption = el.get_text(" ", strip=True).lower()
        href = el.get("href") or ""
        if re.search("toàn văn|toan van|bản in|print|văn bản gốc|pdf", caption + " " + href, re.I):
            page_links.append({
                "label": caption[:85],
                "url_host": urlsplit(urljoin("https://vbpl.vn", href)).hostname,
                "url_path": urlsplit(href).path[:120],
            })
        if len(page_links) >= 12:
            break
    return {
        "html_chars": len(html),
        "visible_text_chars": len(fulltext),
        "title": (soup.title.get_text(" ", strip=True)[:100] if soup.title else ""),
        "scripts": len(soup.find_all("script")),
        "scripts_with_next_data": html.count("__NEXT_DATA__"),
        "script_modules": sum(1 for s in soup.find_all("script") if s.get("type") == "module"),
        "visible_matches": found,
        "candidate_containers": sorted(elements, key=lambda e: e["text_len"])[:35],
        "iframe_or_embeds": frames,
        "related_links": page_links,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--output", default="output/gd2-vbpl-dom-diagnostic.json")
    args = ap.parse_args()
    url = canonical_official_url(args.url)
    result = {"requested_host": urlsplit(url).hostname}
    try:
        resp = requests.get(url, timeout=(8, 20), allow_redirects=False)
        result["http_status"] = resp.status_code
        result["redirect_target"] = ""
        if 300 <= resp.status_code < 400:
            target = urljoin(url, resp.headers.get("Location", ""))
            try:
                result["redirect_target"] = canonical_official_url(target)
            except ValueError:
                result["redirect_target"] = "NOT_ALLOWLISTED"
        elif resp.status_code == 200:
            result.update(inspect_html(resp.text[:6_000_000]))
    except requests.RequestException:
        result["http_status"] = "OFFICIAL_SOURCE_UNAVAILABLE"
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STRUCTURE " + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

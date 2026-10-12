"""GD2.03: official-source verification tests, all offline and read-only."""
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from legal_effect_official import (
    canonical_official_url, load_official_sources, official_html_check,
    check_official_sources, fetch_official_html,
)

URL = "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=12345"
OLD = "55/2011/TT-BGDĐT"
NEW = "81/2026/TT-BGDĐT"
HTML = """
<html><body><nav>Bãi bỏ Thông tư 22/2015/TT-BGDĐT.</nav>
<div class="doc-content">
<p>CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM</p>
<p>Số: 81/2026/TT-BGDĐT</p>
<p>Điều 1. Phạm vi điều chỉnh</p><p>Quy định về hoạt động của nhà trường.</p>
<p>Điều 2. Hiệu lực thi hành</p>
<p>Thông tư này thay thế Thông tư 55/2011/TT-BGDĐT.</p>
<p>Thông tư này có hiệu lực thi hành từ ngày 15 tháng 11 năm 2026.</p>
</div></body></html>"""
EVT = {"old_number": OLD, "new_number": NEW, "event_key": "evt-1",
       "relation_type": "THAY_THE_TOAN_BO", "effect_date_candidate": "2026-11-15"}


class OfficialSourceTest(unittest.TestCase):
    def test_allowlisted_url(self):
        self.assertEqual(canonical_official_url(URL), URL)

    def test_reject_untrusted_urls(self):
        for bad in (
            "http://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=12345",
            "https://vbpl.vn.evil.test/TW/Pages/vbpq-toanvan.aspx?ItemID=12345",
            "https://127.0.0.1/TW/Pages/vbpq-toanvan.aspx?ItemID=12345",
            "https://vbpl.vn@evil.test/TW/Pages/vbpq-toanvan.aspx?ItemID=12345",
            "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=1&next=http://bad.test",
            "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=1#fragment",
            "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=1%0d%0a",
        ):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                canonical_official_url(bad)

    def test_explicit_index_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "index.json"
            path.write_text(json.dumps({"sources": {NEW: URL}}), encoding="utf-8")
            self.assertEqual(load_official_sources(path), {NEW: URL})
            path.write_text(json.dumps({"sources": {"bogus": URL}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_official_sources(path)

    def test_exact_document_and_clause(self):
        result = official_html_check(EVT, URL, HTML)
        self.assertEqual(result["status"], "OFFICIAL_SCOPE_NEEDS_REVIEW")
        self.assertEqual(result["source_document_number"], NEW)
        self.assertIn(OLD, result["source_clause"])
        self.assertTrue(result["requires_legal_review"])
        self.assertEqual(result["observed_date"], "2026-11-15")

    def test_mismatched_identity_blocks_matching(self):
        html = HTML.replace("Số: 81/2026/TT-BGDĐT", "Số: 82/2026/TT-BGDĐT")
        result = official_html_check(EVT, URL, html)
        self.assertEqual(result["status"], "IDENTITY_MISMATCH")

    def test_conflicting_relation_blocks(self):
        event = dict(EVT, relation_type="SUA_DOI_BO_SUNG")
        result = official_html_check(event, URL, HTML)
        self.assertEqual(result["status"], "OFFICIAL_RELATION_CONFLICT")

    def test_editorial_nav_is_not_official(self):
        html = HTML.replace("Thông tư này thay thế Thông tư 55/2011/TT-BGDĐT.",
                            "Thông tư này quy định thời gian làm việc.")
        result = official_html_check(EVT, URL, html)
        self.assertEqual(result["status"], "NO_RELEVANT_OFFICIAL_ACTION")

    def test_official_source_missing_never_grants_verification(self):
        row = {"Mã phiếu rà soát": "RV-1", "Khóa sự kiện": "evt-1",
               "Trích dẫn điều khoản": "lược đồ", "Mức tin cậy": "TRUNG_BINH",
               "Trạng thái xác minh": "CHO_XAC_MINH"}
        report = {"records_review": [row]}
        audit = check_official_sources(report, [EVT], {})
        self.assertEqual(audit["status_counts"], {"OFFICIAL_SOURCE_NOT_INDEXED": 1})
        self.assertEqual(row["Trạng thái xác minh"], "CAN_BO_SUNG_CHUNG_CU")
        self.assertEqual(row.get("URL nguồn chính thức", ""), "")

    def test_success_still_requires_legal_review(self):
        row = {"Mã phiếu rà soát": "RV-1", "Khóa sự kiện": "evt-1",
               "Trích dẫn điều khoản": "", "Mức tin cậy": "THAP",
               "Trạng thái xác minh": "CHO_XAC_MINH"}
        report = {"records_review": [row]}
        audit = check_official_sources(report, [EVT], {NEW: URL},
                                       fetcher=lambda url: HTML.replace("Thông tư này thay thế Thông tư", "Thông tư này thay thế toàn bộ Thông tư"))
        self.assertEqual(audit["status_counts"], {"OFFICIAL_ACTION_MATCHED_PENDING_LEGAL": 1})
        self.assertEqual(row["URL nguồn chính thức"], URL)
        self.assertEqual(row["Trạng thái xác minh"], "CHO_XAC_MINH")

    def test_network_failure_is_fail_closed(self):
        row = {"Mã phiếu rà soát": "RV-1", "Khóa sự kiện": "evt-1",
               "Trạng thái xác minh": "CHO_XAC_MINH"}
        def fail(_):
            raise ValueError("OFFICIAL_SOURCE_UNAVAILABLE")
        audit = check_official_sources({"records_review": [row]}, [EVT],
                                       {NEW: URL}, fetcher=fail)
        self.assertEqual(audit["status_counts"], {"OFFICIAL_SOURCE_UNAVAILABLE": 1})
        self.assertEqual(row["Trạng thái xác minh"], "CAN_BO_SUNG_CHUNG_CU")

    def test_http_redirect_blocked(self):
        class FakeResponse:
            status_code = 302
            headers = {"Location": "http://169.254.169.254"}
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch("requests.get", return_value=FakeResponse()) as req:
            with self.assertRaisesRegex(ValueError, "OFFICIAL_REDIRECT_BLOCKED"):
                fetch_official_html(URL)
            self.assertFalse(req.call_args.kwargs["allow_redirects"])


if __name__ == "__main__":
    unittest.main()

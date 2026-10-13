"""Offline tests for headed Windows browser acceptance oracle."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from gd2_vbpl_windows_test import evaluate_rendered_document, TEST_URL

def page(main):
    return "<html><head><title>Thông tư 05/2021/TT-BGDĐT của Bộ Giáo dục</title></head><body>" + main + "</body></html>"

class VBPLWindowsOracleTest(unittest.TestCase):
    def test_javascript_shell_cannot_pass(self):
        r = evaluate_rendered_document(
            page("<div id='app'>Loading</div>"),
            "Thông tư 05/2021/TT-BGDĐT của Bộ Giáo dục", TEST_URL, 200)
        self.assertEqual(r["outcome"], "DOCUMENT_NOT_RENDERED_OR_PARSER_INCOMPATIBLE")

    def test_blocked_site_cannot_pass(self):
        r = evaluate_rendered_document("", "403 Forbidden", TEST_URL, 403)
        self.assertEqual(r["outcome"], "SITE_ACCESS_DENIED")

    def test_rendered_vbpl_document_extracts_modification(self):
        html = page(
            "<section class='document-reader'>"
            "<p>THÔNG TƯ</p>"
            "<p>Sửa đổi, bổ sung một số điều của Quy chế thi tốt nghiệp trung học phổ thông</p>"
            "<p>Căn cứ Luật Giáo dục năm 2019;</p>"
            "<p>Bộ trưởng Bộ Giáo dục và Đào tạo ban hành Thông tư quy định "
            "các nội dung cần thiết trong kỳ thi tốt nghiệp trung học phổ thông.</p>"
            "<p>Điều 1. Sửa đổi, bổ sung một số điều của Quy chế ban hành kèm "
            "theo Thông tư 15/2020/TT-BGDĐT.</p>"
            "<p>1. Sửa đổi, bổ sung quy định về tổ chức thi.</p>"
            "<p>Điều 2. Hiệu lực thi hành</p>"
            "<p>Thông tư này có hiệu lực từ ngày 27/04/2021.</p>"
            "</section>")
        result = evaluate_rendered_document(
            html, "Thông tư 05/2021/TT-BGDĐT của Bộ Giáo dục", TEST_URL, 200)
        self.assertEqual(result["outcome"], "PROVISIONAL_PASS_PENDING_LEGAL")
        self.assertEqual(result["matched_events"][0]["relation_type"], "SUA_DOI_BO_SUNG")
        self.assertTrue(result["requires_legal_review"])

    def test_editorial_summary_only_is_insufficient(self):
        html = page("<section><p>Thông tư 05/2021/TT-BGDĐT "
                    "sửa đổi bổ sung Thông tư 15/2020/TT-BGDĐT</p></section>")
        r = evaluate_rendered_document(
            html, "Thông tư 05/2021/TT-BGDĐT", TEST_URL, 200)
        self.assertNotEqual(r["outcome"], "PROVISIONAL_PASS_PENDING_LEGAL")

if __name__ == "__main__":
    unittest.main()

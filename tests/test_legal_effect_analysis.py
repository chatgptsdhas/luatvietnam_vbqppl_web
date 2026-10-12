"""GD2: offline tests. No network, credentials, Sheets, or Planner writes."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from legal_effect_analysis import analyze_new_document, document_numbers, normalize_number, parse_iso_date

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gd2_step15", ROOT / "15_check_legal_effect.py")
step15 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(step15)


def source(number="81/2026/TT-BGDĐT", relations=()):
    return {"source_doc_number": number,
            "url": "https://luatvietnam.vn/sample.html",
            "current_doc": {"ngay_hieu_luc": "15/11/2026"},
            "luoc_do_data": list(relations)}


class LegalEffectCandidatesTest(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(document_numbers("Số 50/2014/QH13 và 12/2015/NĐ-CP"),
                         ["50/2014/QH13", "12/2015/NĐ-CP"])
        self.assertEqual(normalize_number(" 12 / 2015 / nđ–cp "), "12/2015/NĐ-CP")

    def test_date_parsing_rejects_range(self):
        self.assertEqual(parse_iso_date("01/01/2015 - 01/07/2026"), "")
        self.assertEqual(parse_iso_date("ngày 15 tháng 11 năm 2026"), "2026-11-15")
        self.assertEqual(parse_iso_date("31/02/2026"), "")

    def test_luoc_do_replacement_direction(self):
        c = analyze_new_document(source(relations=[
            {"heading": "Văn bản bị thay thế", "item": "Thông tư 55/2011/TT-BGDĐT"}]))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["old_number"], "55/2011/TT-BGDĐT")
        self.assertEqual(c[0]["new_number"], "81/2026/TT-BGDĐT")
        self.assertEqual(c[0]["relation_type"], "THAY_THE_TOAN_BO")
        self.assertEqual(c[0]["verification_status"], "CHO_XAC_MINH")

    def test_reverse_direction(self):
        c = analyze_new_document(source(relations=[
            {"heading": "Văn bản thay thế", "item": "Thông tư 90/2026/TT-BGDĐT"}]))
        self.assertEqual(c[0]["old_number"], "81/2026/TT-BGDĐT")
        self.assertEqual(c[0]["new_number"], "90/2026/TT-BGDĐT")

    def test_ambiguous_category_never_confirmed(self):
        c = analyze_new_document(source(relations=[
            {"heading": "Văn bản hết hiệu lực", "item": "Thông tư 14/2015/TT-BGDĐT"}]))
        self.assertEqual(c[0]["relation_type"], "KHAC")
        self.assertEqual(c[0]["suggested_effect_status"], "CHUA_XAC_MINH")

    def test_clause_replacement_has_candidate_date(self):
        c = analyze_new_document(source(), [
            "Thông tư này có hiệu lực thi hành từ ngày 15 tháng 11 năm 2026 và thay thế Thông tư 55/2011/TT-BGDĐT."
        ])
        self.assertEqual(c[0]["effect_date_candidate"], "2026-11-15")
        self.assertTrue(c[0]["requires_official_check"])

    def test_partial_does_not_become_whole(self):
        c = analyze_new_document(source(), ["Bãi bỏ khoản 2 Điều 3 của Nghị định 86/2018/NĐ-CP."])
        self.assertEqual(c[0]["relation_type"], "BAI_BO_MOT_PHAN")
        self.assertEqual(c[0]["suggested_effect_status"], "CHUA_XAC_MINH")

    def test_amendment_not_repeal(self):
        c = analyze_new_document(source(), ["Sửa đổi, bổ sung Điều 5 Nghị định 125/2024/NĐ-CP."])
        self.assertEqual(c[0]["relation_type"], "SUA_DOI_BO_SUNG")

    def test_negation_and_continued(self):
        self.assertEqual(analyze_new_document(source(),
            ["Thông tư này không thay thế Thông tư 55/2011/TT-BGDĐT."]), [])
        self.assertEqual(analyze_new_document(source(),
            ["Thông tư 55/2011/TT-BGDĐT tiếp tục có hiệu lực."]), [])

    def test_same_referenced_in_two_sources_one_event(self):
        doc = source(relations=[{"heading": "Văn bản bị thay thế",
                                 "item": "Thông tư 55/2011/TT-BGDĐT"}])
        c = analyze_new_document(doc, ["Thông tư này thay thế Thông tư 55/2011/TT-BGDĐT."])
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["evidence_origin"], "clause")


class BackfillTests(unittest.TestCase):
    @staticmethod
    def entry(sheet="VBQPPL", kind="Thông tư", url="https://luatvietnam.vn/sample.html"):
        return {"sheet": sheet, "id": "VB123", "type": kind, "title": "Văn bản thử",
                "url": url, "effect_start": "01/01/2015"}

    def test_two_sheets_one_review(self):
        cat = {"55/2011/TT-BGDĐT": [self.entry(), self.entry(sheet="VBQPPL_Nhap")]}
        report = step15.build_review(cat, [], "baseline")
        self.assertEqual(report["summary"]["catalog_records"], 2)
        self.assertEqual(report["summary"]["review_rows"], 1)
        self.assertEqual(report["records_review"][0]["Nguồn xuất hiện"],
                         "VBQPPL, VBQPPL_Nhap")

    def test_collision_blocks_verification(self):
        cat = {"55/2011/TT-BGDĐT": [
            self.entry(),
            self.entry(sheet="VBQPPL_Nhap", kind="Nghị định", url="https://luatvietnam.vn/other")
        ]}
        report = step15.build_review(cat, [], "baseline")
        self.assertEqual(report["records_review"][0]["Trạng thái xác minh"], "CAN_BO_SUNG_CHUNG_CU")

    def test_retry_event_idempotent(self):
        event = {"old_number": "55/2011/TT-BGDĐT", "new_number": "81/2026/TT-BGDĐT",
                 "event_key": "same", "relation_type": "THAY_THE_TOAN_BO"}
        report = step15.build_review({"55/2011/TT-BGDĐT": [self.entry()]},
                                     [event, event], "events")
        self.assertEqual(report["summary"]["review_rows"], 1)
        self.assertEqual(report["records_review"][0]["Tình trạng hiệu lực đề xuất"], "CHUA_XAC_MINH")

    def test_unmatched_event_is_reported_not_inserted(self):
        report = step15.build_review({}, [{"old_number": "1/2020/TT-BGDĐT"}], "events")
        self.assertEqual(report["summary"]["review_rows"], 0)
        self.assertEqual(report["summary"]["unmatched_events"], 1)

    def test_workbook_uses_live_sheet_names(self):
        from openpyxl import Workbook
        wb = Workbook()
        wb.active.title = "VBQPPL"
        wb.create_sheet("VBQPPL_Nhap")
        for sheet in ("VBQPPL", "VBQPPL_Nhap"):
            wb[sheet].append(["Số hiệu", "Loại văn bản", "Tên văn bản", "Link Văn bản", "ID VĂN BẢN"])
            wb[sheet].append(["55/2011/TT-BGDĐT", "Thông tư", "Văn bản thử",
                              "https://luatvietnam.vn/sample.html", "VB123"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.xlsx"
            wb.save(path)
            cat = step15.catalog_from_workbook(path)
            self.assertEqual(len(cat), 1)
            self.assertEqual(len(cat["55/2011/TT-BGDĐT"]), 2)


if __name__ == "__main__":
    unittest.main()

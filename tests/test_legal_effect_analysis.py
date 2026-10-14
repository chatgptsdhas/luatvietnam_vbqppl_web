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



class LegalEffectDisambiguationTest(unittest.TestCase):
    def test_partial_replacement_is_not_whole(self):
        c = analyze_new_document(source(), ["Thay thế khoản 2 Điều 3 của Thông tư 55/2011/TT-BGDĐT."])
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["relation_type"], "KHAC")
        self.assertEqual(c[0]["scope_type"], "MOT_PHAN")

    def test_general_effect_date_not_assigned_to_unrelated_clause(self):
        doc = source()
        items = [
            {"text": "Bãi bỏ Nghị định 12/2015/NĐ-CP.", "section_heading": "Điều 5. Quy định chuyển tiếp",
             "section_kind": "article", "location": "doc:p[25]"},
            {"text": "Nghị định này có hiệu lực từ ngày 01/11/2026.", "section_heading": "Điều 6. Hiệu lực",
             "section_kind": "article", "location": "doc:p[30]"},
        ]
        c = analyze_new_document(doc, items)
        self.assertEqual(c[0]["effect_date_candidate"], "")
        self.assertEqual(c[0]["evidence_location"], "doc:p[25]")

    def test_same_article_general_date_marked_as_inferred(self):
        doc = source()
        items = [
            {"text": "Bãi bỏ Nghị định 12/2015/NĐ-CP.", "section_heading": "Điều 6. Hiệu lực",
             "section_kind": "article", "location": "doc:p[23]"},
            {"text": "Nghị định này có hiệu lực từ ngày 01/11/2026.", "section_heading": "Điều 6. Hiệu lực",
             "section_kind": "article", "location": "doc:p[24]"},
        ]
        c = analyze_new_document(doc, items)
        self.assertEqual(c[0]["effect_date_candidate"], "2026-11-01")
        self.assertEqual(c[0]["effect_date_basis"], "hieu_luc_chung_cung_dieu")

    def test_passive_clause_actor_unknown(self):
        c = analyze_new_document(source(), [
            "Thông tư 55/2011/TT-BGDĐT bị thay thế theo quy định mới."
        ])
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["old_number"], "55/2011/TT-BGDĐT")
        self.assertEqual(c[0]["new_number"], "")
        self.assertEqual(c[0]["direction"], "unknown")

    def test_list_after_repeal_clause_keeps_source_heading(self):
        doc = source()
        lines = [
            {"text": "Bãi bỏ các văn bản sau đây:", "section_heading": "Điều 9. Bãi bỏ",
             "section_kind": "article", "location": "doc:p[10]"},
            {"text": "a) Thông tư 55/2011/TT-BGDĐT.", "section_heading": "Điều 9. Bãi bỏ",
             "section_kind": "article", "location": "doc:p[11]"},
        ]
        c = analyze_new_document(doc, lines)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["old_number"], "55/2011/TT-BGDĐT")
        self.assertEqual(c[0]["relation_type"], "BAI_BO_TOAN_BO")
        self.assertEqual(c[0]["evidence_location"], "doc:p[11]")

    def test_gd205_002_mixed_amendment_and_annex_replacement(self):
        """Official Article 1 amends Article 7 and replaces annexes, not the entire Circular."""
        doc = source(number="07/2024/TT-BGDĐT")
        section = ("Điều 1. Sửa đổi, bổ sung Điều 7 và thay thế Phụ lục II, "
                   "Phụ lục III của Thông tư số 13/2021/TT-BGDĐT ngày 15 tháng 4 năm 2021")
        events = analyze_new_document(doc, [
            {"text": section, "section_heading": section, "section_kind": "article",
             "location": "official:p[12]"},
        ])
        matching = [e for e in events if e["old_number"] == "13/2021/TT-BGDĐT"
                    and e["new_number"] == "07/2024/TT-BGDĐT"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["relation_type"], "SUA_DOI_BO_SUNG")
        self.assertEqual(matching[0]["scope_type"], "MOT_PHAN")
        self.assertEqual(matching[0]["verification_status"], "CHO_XAC_MINH")

    def test_gd205_016_multiple_circulars_expire_before_action_verb(self):
        """A cited list before 'hết hiệu lực' must not disappear."""
        doc = source(number="02/2024/TT-BTTTT")
        section = "Điều 7. Hiệu lực thi hành"
        clause = ("2. Thông tư số 04/2023/TT-BTTTT ngày 31 tháng 5 năm 2023 "
                  "và Thông tư số 10/2023/TT-BTTTT ngày 05 tháng 9 năm 2023 "
                  "hết hiệu lực thi hành kể từ ngày Thông tư này có hiệu lực thi hành.")
        events = analyze_new_document(doc, [
            {"text": clause, "section_heading": section, "section_kind": "article",
             "location": "official:p[71]"},
        ])
        matched = {(e["old_number"], e["new_number"], e["relation_type"])
                   for e in events}
        self.assertIn(("04/2023/TT-BTTTT", "02/2024/TT-BTTTT", "HET_THOI_HAN"), matched)
        self.assertIn(("10/2023/TT-BTTTT", "02/2024/TT-BTTTT", "HET_THOI_HAN"), matched)
        self.assertTrue(all(not e["effect_date_candidate"] for e in events))

    def test_gd205_018_quoted_decree_citation_not_a_direct_amendment(self):
        """The amended Circular is 34/2016; salary decree 204/2004 is only referenced."""
        doc = source(number="12/2024/TT-BLĐTBXH")
        heading = ("Điều 3. Sửa đổi, bổ sung một số điều của "
                   "Thông tư số 34/2016/TT-BLĐTBXH")
        quote = ("2. Sửa đổi, bổ sung điểm c khoản 3 Điều 5 như sau: "
                 "“c) Doanh thu không bù đắp được chi phí thì phải giảm mức tiền lương, "
                 "thấp nhất theo Nghị định số 204/2004/NĐ-CP nhân với mức lương cơ sở.”")
        events = analyze_new_document(doc, [
            {"text": heading, "section_heading": heading, "section_kind": "article",
             "location": "official:p[38]"},
            {"text": quote, "section_heading": heading, "section_kind": "article",
             "location": "official:p[42]"},
        ])
        self.assertTrue(any(e["old_number"] == "34/2016/TT-BLĐTBXH" for e in events))
        self.assertFalse(any(e["old_number"] == "204/2004/NĐ-CP" for e in events))

    def test_gd205_009_some_program_content_is_partial_scope(self):
        doc = source(number="17/2025/TT-BGDĐT")
        heading = ("Điều 1. Sửa đổi, bổ sung một số nội dung trong Chương trình "
                   "giáo dục phổ thông ban hành kèm theo Thông tư số 32/2018/TT-BGDĐT")
        events = analyze_new_document(doc, [
            {"text": heading, "section_heading": heading, "section_kind": "article",
             "location": "official:p[12]"},
        ])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["scope_type"], "MOT_PHAN")

    def test_ambiguous_mixed_actions_unverified(self):
        c = analyze_new_document(source(), ["Bãi bỏ và sửa đổi Thông tư 55/2011/TT-BGDĐT."])
        self.assertEqual(c[0]["relation_type"], "KHAC")
        self.assertEqual(c[0]["suggested_effect_status"], "CHUA_XAC_MINH")

    def test_unrelated_date_never_assigned(self):
        c = analyze_new_document(source(), [
            "Bãi bỏ Thông tư 55/2011/TT-BGDĐT ban hành ngày 01/01/2011."
        ])
        self.assertEqual(c[0]["effect_date_candidate"], "")

    def test_unrelated_references_do_not_imply_repeal(self):
        self.assertEqual(analyze_new_document(source(), [
            "Căn cứ Thông tư 55/2011/TT-BGDĐT ngày 01/01/2011."
        ]), [])

    def test_partial_annex_event_not_full(self):
        c = analyze_new_document(source(), [
            "Bãi bỏ Phụ lục I của Thông tư 55/2011/TT-BGDĐT."
        ])
        self.assertEqual(c[0]["scope_type"], "MOT_PHAN")
        self.assertEqual(c[0]["relation_type"], "BAI_BO_MOT_PHAN")



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

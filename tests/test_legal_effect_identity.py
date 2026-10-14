"""GD2.04: source identity regression tests. All offline."""
import unittest

from legal_effect_identity import inspect_catalog, safe_document_url
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("gd2_step15_identity", ROOT/"15_check_legal_effect.py")
step15=importlib.util.module_from_spec(spec)
spec.loader.exec_module(step15)

def entry(sheet, id, url, title="Thông tư thử", kind="Thông tư", row=2):
    return {"sheet":sheet,"id":id,"url":url,"title":title,"type":kind,
            "effect_start":"2026-01-01","row_number":row}

N="55/2011/TT-BGDĐT"
L="https://luatvietnam.vn/giao-duc/thong-tu-55-2011.html"

class IdentityTests(unittest.TestCase):
    def test_two_sources_preserve_ids_and_pick_real_url(self):
        cat={N:[entry("VBQPPL","VB014","Thông tư 55/2011/TT-BGDĐT"),
                entry("VBQPPL_Nhap","VB014",L)]}
        audit=inspect_catalog(cat)
        self.assertEqual(audit["by_number"][N]["preferred_url"],L)
        self.assertFalse(audit["by_number"][N]["requires_identity_review"])
        report=step15.build_review(cat, [], "baseline")
        row=report["records_review"][0]
        self.assertEqual(row["URL văn bản gốc"],L)
        self.assertEqual(row["ID nguồn VBQPPL"],"VB014")
        self.assertEqual(row["ID nguồn VBQPPL_Nhap"],"VB014")
        self.assertIn("NON_URL_DOCUMENT_LINK",row["Lỗi hoặc ngoại lệ"])
        self.assertEqual(row["Trạng thái xác minh"],"CHO_XAC_MINH")

    def test_multiple_ids_fail_closed(self):
        cat={N:[entry("VBQPPL","VB014",L,row=12),
                entry("VBQPPL_Nhap","VB080",L,row=65)]}
        report=step15.build_review(cat, [], "baseline")
        row=report["records_review"][0]
        self.assertEqual(row["Trạng thái xác minh"],"CAN_BO_SUNG_CHUNG_CU")
        self.assertIn("MULTIPLE_DOCUMENT_IDS",row["Lỗi hoặc ngoại lệ"])

    def test_reordering_does_not_affect_stable_fingerprint(self):
        src=[entry("VBQPPL","VB014",L,row=12),
             entry("VBQPPL_Nhap","VB014",L,row=65)]
        first=inspect_catalog({N:src})["by_number"][N]
        other=[dict(src[1],row_number=80),dict(src[0],row_number=250)]
        second=inspect_catalog({N:other})["by_number"][N]
        self.assertEqual(first["document_key"],second["document_key"])
        self.assertEqual(first["fingerprint"],second["fingerprint"])

    def test_separate_relations_and_scope_not_direction(self):
        events=[{"old_number":N,"new_number":"81/2026/TT-BGDĐT",
                 "event_key":"evt1","relation_type":"BAI_BO_MOT_PHAN",
                 "affected_scope":"Khoản 2 Điều 3","direction":"listed_old"}]
        report=step15.build_review({N:[entry("VBQPPL","VB014",L)]},events,"events")
        self.assertEqual(report["records_review"][0]["Phạm vi tác động"],"Khoản 2 Điều 3")

    def test_source_url_not_legal_identity(self):
        self.assertEqual(safe_document_url("Luật số 55/2011/TT-BGDĐT"),"")
        self.assertEqual(safe_document_url("https://127.0.0.1/private"),"")
        self.assertEqual(safe_document_url("https://vbpl.vn.evil.test/doc"),"https://vbpl.vn.evil.test/doc")
        self.assertEqual(safe_document_url("https://user:pass@vbpl.vn/doc"),"")
        self.assertEqual(safe_document_url("https://vbpl.vn/doc#unused"),"https://vbpl.vn/doc")

    def test_conflicting_titles_are_flagged_but_not_discarded(self):
        cat={N:[entry("VBQPPL","VB014",L,title="Luật A"),
                entry("VBQPPL_Nhap","VB014",L,title="Luật B")]}
        r=step15.build_review(cat,[],"baseline")
        self.assertEqual(r["summary"]["review_rows"],1)
        self.assertIn("TITLE_VARIANTS",r["records_review"][0]["Lỗi hoặc ngoại lệ"])

    def test_retry_and_new_document_event_do_not_duplicate_review(self):
        e={"old_number":N,"new_number":"81/2026/TT-BGDĐT",
           "relation_type":"SUA_DOI_BO_SUNG","event_key":"stable"}
        r=step15.build_review({N:[entry("VBQPPL","VB014",L)]},[e,e],"events")
        self.assertEqual(r["summary"]["review_rows"],1)
        self.assertEqual(r["records_review"][0]["Trạng thái xác minh"],"CHO_XAC_MINH")

if __name__=="__main__":
    unittest.main()

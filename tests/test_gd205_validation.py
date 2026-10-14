"""GD2.05: offline acceptance rubric tests, no browser/network/secrets."""
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from gd205_validate_official_samples import load_manifest, evaluate_case, aggregate, MAX_CASES

URL = "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=147477"
GOOD_HTML = """
<html><head><title>Thông tư 05/2021/TT-BGDĐT | VBPL</title></head><body>
<section class="doc-content">
<p>CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM</p>
<p>Số: 05/2021/TT-BGDĐT</p>
<p>Điều 1. Sửa đổi, bổ sung một số điều của Quy chế thi tốt nghiệp</p>
<p>Sửa đổi, bổ sung các điều của Quy chế ban hành kèm theo Thông tư 15/2020/TT-BGDĐT.</p>
<p>Điều 2. Hiệu lực thi hành</p>
<p>Có hiệu lực từ ngày 27/04/2021.</p>
</section>
</body></html>
"""

def case(label="PENDING_HUMAN", truth=True):
    row = {"id":"GD205-test","new_number":"05/2021/TT-BGDĐT",
           "old_number":"15/2020/TT-BGDĐT",
           "expected_relation":"SUA_DOI_BO_SUNG",
           "url":URL,"label_status":label}
    if label == "HUMAN_VERIFIED":
        row["expected_present"] = truth
        row["label_basis"] = "Reviewed source clause at Article 1"
    return row

class GD205Tests(unittest.TestCase):
    def test_provisional_match_not_a_legal_conclusion(self):
        r=evaluate_case(case(),GOOD_HTML,"Thông tư 05/2021/TT-BGDĐT",URL,200)
        self.assertEqual(r["result"],"MATCH_PENDING_HUMAN")
        self.assertTrue(r["requires_legal_review"])
        self.assertTrue(r["matches"][0]["source_section"].startswith("Điều 1"))
        summ=aggregate([case()],[r])
        self.assertIsNone(summ["classification_precision"])
        self.assertIsNone(summ["classification_recall"])
        self.assertEqual(summ["human_labelled_cases"],0)

    def test_labelled_positive_reports_only_targeted_recall(self):
        c=case("HUMAN_VERIFIED")
        result=evaluate_case(c,GOOD_HTML,"Thông tư 05/2021/TT-BGDĐT",URL,200)
        summ=aggregate([c],[result])
        self.assertEqual(summ["human_labelled_cases"],1)
        self.assertEqual(summ["match_recall_on_preselected_positive_cases"],1)
        self.assertIsNone(summ["classification_precision"])

    def test_human_verified_negative_does_not_count_as_failure(self):
        negative = case("HUMAN_VERIFIED", truth=False)
        text = GOOD_HTML.replace(
            "Sửa đổi, bổ sung các điều của Quy chế ban hành kèm theo Thông tư 15/2020/TT-BGDĐT.",
            "Quy định về kỳ thi.")
        observed = evaluate_case(negative, text, "Thông tư 05/2021/TT-BGDĐT", URL, 200)
        self.assertEqual(observed["result"], "NO_MATCH")
        totals = aggregate([negative], [observed])
        self.assertEqual(totals["confusion_matrix"]["true_negative"], 1)
        self.assertIsNone(totals["classification_precision"])

    def test_false_positive_stays_visible_without_claimed_precision(self):
        negative = case("HUMAN_VERIFIED", truth=False)
        observed = evaluate_case(negative, GOOD_HTML, "Thông tư 05/2021/TT-BGDĐT", URL, 200)
        totals = aggregate([negative], [observed])
        self.assertEqual(totals["confusion_matrix"]["false_positive"], 1)
        self.assertIsNone(totals["classification_precision"])

    def test_30_case_metrics_require_both_classes(self):
        cases = [dict(case("HUMAN_VERIFIED", truth=i%2==0), id=str(i)) for i in range(30)]
        rows = [{"id":c["id"],"result":"MATCH_PENDING_HUMAN" if c["expected_present"] else "NO_MATCH",
                 "http_status":200, "extraction_status":"ok"} for c in cases]
        totals = aggregate(cases, rows)
        self.assertEqual(totals["classification_precision"], 1)
        self.assertEqual(totals["classification_recall"], 1)
        self.assertTrue(totals["metrics_eligible"])

    def test_missing_human_label_cannot_be_hidden(self):
        cases = [dict(case("HUMAN_VERIFIED", truth=True), id=str(i)) for i in range(30)]
        rows = [{"id":c["id"],"result":"NO_LEGAL_TEXT",
                 "http_status":200,"extraction_status":"document_root_not_found"} for c in cases]
        totals = aggregate(cases, rows)
        self.assertEqual(totals["human_labelled_not_evaluable_cases"], 30)
        self.assertIsNone(totals["classification_recall"])

    def test_no_article_no_success(self):
        html=GOOD_HTML.replace(
            "Sửa đổi, bổ sung các điều của Quy chế ban hành kèm theo Thông tư 15/2020/TT-BGDĐT.",
            "Quy định về kỳ thi.")
        r=evaluate_case(case(),html,"Thông tư 05/2021/TT-BGDĐT",URL,200)
        self.assertEqual(r["result"],"NO_MATCH")

    def test_wrong_title_does_not_count(self):
        r=evaluate_case(case(),GOOD_HTML,"Thông tư 07/2021/TT-BGDĐT",URL,200)
        self.assertEqual(r["result"],"IDENTITY_UNCONFIRMED")

    def test_403_no_bypass(self):
        r=evaluate_case(case(),"","Forbidden",URL,403)
        self.assertEqual(r["result"],"ACCESS_DENIED")

    def test_source_index_rejects_arbitrary_hosts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"cases.json"
            d={"cases":[dict(case(),url="https://evil.example/TW/Pages/vbpq-toanvan.aspx?ItemID=147477")]}
            path.write_text(json.dumps(d),encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manifest(path)

    def test_duplicate_ids_and_over_limit_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"cases.json"
            path.write_text(json.dumps({"cases":[case(),case()]}),encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manifest(path)
            path.write_text(json.dumps({"cases":[dict(case(),id=str(i)) for i in range(MAX_CASES+1)]}),
                            encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manifest(path)

    def test_actual_manifest_exists_and_is_explicitly_unverified(self):
        path=Path(__file__).resolve().parents[1]/"docs/gd205_case_manifest.json"
        items=load_manifest(path)
        self.assertEqual(len(items),30)
        self.assertEqual(len({x["url"] for x in items}),30)
        self.assertEqual(sum(x["probe_kind"] == "NEGATIVE_CONTROL_CANDIDATE" for x in items),19)
        self.assertEqual(items[0]["label_status"],"PENDING_HUMAN")

if __name__=="__main__":
    unittest.main()

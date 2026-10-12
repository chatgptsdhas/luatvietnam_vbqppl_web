"""GD2.01 source-scoped legal text tests (offline)."""
import unittest
from legal_effect_content import extract_legal_effect_evidence_from_html as extract

HEAD = '<p>CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM</p>'
A1 = '<p>Điều 1. Phạm vi điều chỉnh</p><p>Quy định nguyên tắc thực hiện.</p>'
A2 = '<p>Điều 2. Hiệu lực thi hành</p><p>Có hiệu lực từ ngày 01/01/2027.</p>'

class ExtractionTests(unittest.TestCase):
    def test_exclude_navigation_editorial_and_footer(self):
        html = ('<nav><p>Bãi bỏ 99/2019/NĐ-CP</p></nav>'
                '<aside><p>Thay thế 88/2019/NĐ-CP</p></aside>'
                '<div class="doc-content"><h2>TÓM TẮT</h2>'
                '<p>Thay thế 77/2020/NĐ-CP</p>' + HEAD + A1 + A2 +
                '<p>Điều 3. Bãi bỏ</p><p>Bãi bỏ Nghị định 12/2015/NĐ-CP.</p>'
                '<footer><p>Thay thế 66/2020/NĐ-CP</p></footer></div>')
        r = extract(html)
        self.assertEqual(r['status'], 'ok')
        texts = ' '.join(x['text'] for x in r['blocks'])
        self.assertIn('12/2015/NĐ-CP', texts)
        for wrong in ('99/2019/NĐ-CP','88/2019/NĐ-CP','77/2020/NĐ-CP','66/2020/NĐ-CP'):
            self.assertNotIn(wrong, texts)
        self.assertTrue(all('paragraph[' in x['location'] for x in r['blocks']))

    def test_fail_closed_without_document_root(self):
        r = extract('<html><body><nav>Bãi bỏ 12/2015/NĐ-CP</nav>'
                    '<main><p>Tóm tắt: thay thế 65/2013/NĐ-CP</p></main></body></html>')
        self.assertEqual(r['status'],'document_root_not_found')
        self.assertEqual(r['blocks'],[])

    def test_split_heading_keeps_enumerated_list(self):
        html = ('<section class="law-document-content">' + HEAD + A1 +
                '<p>Điều 4.</p><p>Hiệu lực thi hành</p>'
                '<p>1. Bãi bỏ các văn bản:</p><p>a) Thông tư 55/2011/TT-BGDĐT.</p>'
                '<p>b) Thông tư 88/2020/TT-BGDĐT.</p><p>Điều 5. Khác</p>'
                '<p>Nội dung không liên quan.</p></section>')
        r = extract(html)
        self.assertEqual(r['status'],'ok')
        texts = [x['text'] for x in r['blocks']]
        self.assertIn('a) Thông tư 55/2011/TT-BGDĐT.',texts)
        self.assertIn('b) Thông tư 88/2020/TT-BGDĐT.',texts)
        self.assertNotIn('Nội dung không liên quan.',texts)
        self.assertTrue(any('Điều 4. Hiệu lực thi hành' in x['section_heading'] for x in r['blocks']))

    def test_annex_preserved(self):
        html = ('<div id="content_van_ban">' + HEAD + A1 + A2 +
                '<h3>PHỤ LỤC I</h3><p>Danh mục văn bản bị bãi bỏ</p>'
                '<p>Thông tư 55/2011/TT-BGDĐT</p></div>')
        r = extract(html)
        self.assertTrue(any(x['section_kind']=='annex' and
                            x['text']=='Thông tư 55/2011/TT-BGDĐT' for x in r['blocks']))

    def test_structural_fallback_requires_official_masthead(self):
        doc = '<article>'+HEAD+A1+A2+'</article>'
        self.assertEqual(extract(doc)['root_selector'],'structural_document_root')
        self.assertEqual(extract('<article>'+A1+A2+'</article>')['status'],
                         'document_root_not_found')

    def test_missing_or_empty(self):
        self.assertEqual(extract('')['status'],'source_unavailable')
        self.assertEqual(extract('<div></div>')['status'],'document_root_not_found')

if __name__ == '__main__':
    unittest.main()

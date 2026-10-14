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

    def test_long_source_does_not_cut_evidence_at_250(self):
        html = ('<div class="doc-content"><p>CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM</p>'
                '<p>Điều 1. Sửa đổi, bổ sung quy định</p>'
                + ''.join('<p>Sửa đổi khoản 2 Thông tư 55/2011/TT-BGDĐT.</p>'
                          for _ in range(310))
                + '<p>Điều 2. Hiệu lực thi hành</p>'
                + '<p>Thông tư có hiệu lực từ ngày 01/01/2027.</p></div>')
        r = extract(html)
        self.assertGreater(r["evidence_count"], 250)
        self.assertFalse(r["truncated"])

    def test_missing_or_empty(self):
        self.assertEqual(extract('')['status'],'source_unavailable')
        self.assertEqual(extract('<div></div>')['status'],'document_root_not_found')


    def test_rendered_vbpl_content_without_masthead(self):
        html = ('<nav><p>Thông tư đã hết hiệu lực toàn bộ</p></nav>'
                '<div class="app-page"><p>Tóm tắt: Bãi bỏ Thông tư 01/2020/TT-BGDĐT</p>'
                '<section class="document-reader"><p>THÔNG TƯ</p>'
                '<p>Sửa đổi, bổ sung một số điều của Quy chế thi tốt nghiệp THPT</p>'
                '<p>Căn cứ Luật Giáo dục năm 2019;</p>'
                '<p>Bộ trưởng Bộ Giáo dục và Đào tạo ban hành Thông tư:</p>'
                '<p>Điều 1. Sửa đổi, bổ sung quy chế ban hành kèm Thông tư 15/2020/TT-BGDĐT</p>'
                '<p>1. Sửa đổi khoản 2 của quy chế.</p>'
                '<p>Điều 2. Hiệu lực thi hành</p>'
                '<p>Thông tư này có hiệu lực từ ngày 27/04/2021.</p>'
                '</section></div>')
        result = extract(html)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['root_selector'], 'structural_vbpl_rendered_root')
        evidence = ' '.join(x['text'] for x in result['blocks'])
        self.assertIn('15/2020/TT-BGDĐT', evidence)
        self.assertNotIn('01/2020/TT-BGDĐT', evidence)

    def test_rendered_vbpl_summary_alone_not_source(self):
        html = ('<nav>Thông tư 05/2021/TT-BGDĐT</nav><div><p>THÔNG TƯ</p>'
                '<p>Thông tư sửa đổi quy chế</p><p>Điều 1. Nội dung</p>'
                '<p>Điều 2. Hiệu lực</p></div>')
        result = extract(html)
        self.assertEqual(result['status'], 'document_root_not_found')

    def test_rendered_reader_waits_then_extracts(self):
        from legal_effect_content import extract_rendered_vbpl_evidence
        class FakePage:
            waited = False
            def content(self):
                if not self.waited:
                    return '<div id="app">Loading...</div>'
                return ('<div><p>THÔNG TƯ</p><p>Căn cứ Luật Giáo dục;</p>'
                        '<p>Bộ trưởng ban hành Thông tư quy định cụ thể về nội dung thi tốt nghiệp trung học phổ thông, trách nhiệm tổ chức thi, công tác chấm thi và quản lý kết quả thi.</p>'
                        '<p>Điều 1. Sửa đổi Thông tư 15/2020/TT-BGDĐT.</p>'
                        '<p>Điều 2. Hiệu lực thi hành</p>'
                        '<p>Có hiệu lực từ ngày 27/04/2021.</p></div>')
            def wait_for_function(self, expression, timeout):
                self.waited = True
        result = extract_rendered_vbpl_evidence(FakePage())
        self.assertEqual(result['status'], 'ok')

if __name__ == '__main__':
    unittest.main()

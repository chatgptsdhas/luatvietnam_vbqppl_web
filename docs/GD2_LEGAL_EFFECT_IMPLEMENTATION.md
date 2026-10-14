# GD2 - Cong cu phat hien va de xuat ra soat hieu luc (ban dau)

Trang thai: **Da co code va test; chua kiem thu website that / chua deploy pipeline theo lich / khong ghi production**.

## File

- `legal_effect_analysis.py`: bo phan tich theo ngu canh van ban moi, doc dieu khoan va Luoc do do Step08 thu thap. Luon tra `CHUA_XAC_MINH` va `CHO_XAC_MINH`; KHONG tu ket luan da het hieu luc.
- `08_process_field_documents_batch.py`: giu nguyen API import; them `legal_effect_candidates` vao file JSON dau ra Step08. Khong truyen candidate vao Apps Script.
- `15_check_legal_effect.py`: doc workbook offline gom 2 sheet `VBQPPL` / `VBQPPL_Nhap`, doi chieu so hieu chuan hoa, tao report CSV/JSON phu hop 28 cot staging GD1. Ho tro `baseline` va `events`.
- `tests/test_legal_effect_analysis.py`: unit test; chay qua GitHub Actions.
- `requirements-legal-effect.txt`: openpyxl cho cong doan doc snapshot.

## Lenh chay tren may Windows

Dau vao la mot **ban sao .xlsx** cua Google Sheets, KHONG chinh sua file nguon.

```powershell
python -m pip install -r requirements-legal-effect.txt
python -m unittest discover -s tests -p "test_legal_effect_analysis.py" -v

# Khoi tao danh sach ra soat tat ca so hieu (khong tu ket luan)
python 15_check_legal_effect.py --mode baseline --workbook "backup.xlsx" --output-dir "output/gd2-baseline"

# Khi Step08 da chay phien ban moi va xuat legal_effect_candidates
python 15_check_legal_effect.py --mode events --workbook "backup.xlsx" --step08-json "output/vbqppl_nhap_batch_payload.json" --output-dir "output/gd2-events"
```

Dau ra: `legal_effect_review.csv`, `legal_effect_review.json` co cot theo dac ta GD1. Du lieu theo nguon tu dong la **ung vien can xac minh**, khong phai ho so duoc xac nhan het hieu luc.

## Gioi han an toan

- Chi doc file local va tao report local, khong su dung token, khong goi API ghi Sheets, khong goi Planner.
- Luoc do cho biet quan he goi y; can kiem tra chieu quan he, pham vi bi tac dong va quy dinh chuyen tiep. Tu khoa khong du ket luan het hieu luc.
- Nhan dien `event_key` co tinh lap lai; so hieu co the trung/khac nguon, can review va xac minh dinh danh khi migration.
- Trang thai `SAP_HET_HIEU_LUC` chua duoc ket luan tu dong vi thieu ngay ket thuc duoc chung minh.
- Ma so va ngay theo nguon co the sai; khoi tao baseline khong dong nghia rang van ban da duoc xac minh phap ly.
- Chua co bo doi chieu trang thai voi CSDL VBPL chinh thuc, OCR/PDF, trinh duyet tren may Windows, hay test E2E cua crawl 07->08->09. Can thuc hien tiep va danh gia do phu truoc khi tu dong chay theo lich.
- Chua co action service tiep nhan ket qua vao `VBQPPL_RaSoatHieuLuc`; phan nay thuoc GD3. Khong su dung public token de ghi.
- Hoan toan khong dong cham toi Google Sheets production, WebApp, Dashboard, MS Planner hoac Task Scheduler.

## Nghiem thu GD2 - hạng muc

1. Parser xu ly duoc luoc do thay the / het hieu luc / sua doi, dieu khoan va ngay du kien, khong auto-classify.
2. Baseline 531 ban ghi, 339 so hieu (tai snapshot 12/10/2026) -> 339 phieu cho ra soat, khong nhan doi.
3. Unit tests va CI qua; thu nghem E2E tren 30 van ban da duoc nguoi duyet danh gia, xac dinh precision/recall va cot loi.
4. Thong nhat nguon chinh thuc va phuong an quet dinh ky an toan.
5. Chi sau khi GD2 duoc nghiem thu moi chuyen GD3 (Apps Script service API + Dashboard admin).

## GD2.01 — Tach noi dung phap ly khoi thanh phan trang (12/10/2026)

- Tao `legal_effect_content.py` doc DOM duoc Playwright render **truoc khi mo Luoc do**. Uu tien cac content container co dau hieu van ban; fallback co kiem soat khi co quoc hieu va >=2 dieu; khong fallback sang `body` hoac menu/tom tat.
- Loc nav/footer/aside/share/menu; bat canh dieu hieu luc, chuyen tiep, bai bo, thay the, sua doi/bo sung va phu luc. Moi doan co `paragraph_index`, `location`, `section_heading`, `section_kind`, `root_selector` de doi chieu.
- Step08 giu `get_body_lines()` **chi cho luong trich thong tin chung cu** va payload import hien tai; cac de xuat `legal_effect_candidates` **chi duoc nhan bang chung tu legal_effect_evidence**. Khong thay doi API import.
- Neu khong tim thay can cu trong nguyen ban, `legal_content_extraction_meta.status` tra `document_root_not_found` / `source_unavailable` / `no_relevant_clauses` va **khong dung `body` doan thay**; quan he Luoc do van chi la goi y cho Phap che.
- Test `tests/test_legal_effect_content.py` bao gom: navigation/tom tat/noi dung trang phai bi loai, chia dong ten dieu, phu luc, loai website khong co nguyen ban, ranh gioi fallback.
- **Chua kiem thu tren website that**: selector va cau truc van ban co the thay doi; GD2.05 chay 30 van ban that truoc khi xem la hoan thanh van hanh.
- Co the khong doc duoc noi dung khi trang dung anh/PDF hoac HTML khong co cau truc dieu; truong hop nay can manual review, khong suy dien hieu luc.

## GD2.02 — Xu ly chieu quan he, pham vi, ngay ap dung (12/10/2026)

- `legal_effect_analysis.py`: tach phan loai hanh vi (thay the/bai bo/sua doi/dinh chi), pham vi dieu/khoan/phu luc, va nguon chung cu. Mac dinh `CHUA_XAC_MINH` va `CHO_XAC_MINH`; khong suy ra hieu luc tu dong.
- `effect_date_candidate` chi dien khi co ngay duoc gan truc tiep voi dieu khoan, hoac `hieu_luc_chung_cung_dieu` co chung cu ro rang khong co ngoai le; khong lay ngay van ban moi mac dinh neu khong co ngay dieu khoan lien quan.
- Cung cap `effect_date_basis`, `affected_scope`, `scope_type`, `direction_confidence`, `evidence_location`, `evidence_section_heading` de phuc vu GD3/GD2.03.
- Nhan dien cau chu dong/bi dong; khi van ban tac dong khong duoc noi ro, de `new_number` rong va `direction=unknown`. Loai bo cau phu dinh/van ban tiep tuc co hieu luc. Hanh vi phuc tap/tron nhieu quan he -> `KHAC` de kiem tra.
- `08_process_field_documents_batch.py` nay truyen danh sach `legal_effect_evidence` co vi tri va dieu khoan thay vi chuoi phang de parser khong danh mat ngu canh.
- Them 9 test trong `tests/test_legal_effect_analysis.py` ve thay the mot phan, phu luc, cau bi dong, danh sach gạch dau dong, ngay khong lien quan, ngay chung cung dieu, chung cu.
- Sua nguong de nhan van ban ngan co quoc hieu va >=2 dieu trong `legal_effect_content.py` (loi test GD2.01).
- Chua xu ly duoc moi mau dien dat thuc te; kiem thu 30 van ban web va doi chieu nguon chinh thuc trong GD2.03/GD2.05 van bat buoc. Khong write production, khong dong den Planner.

## GD2.03 — Đối chiếu nguồn VBPL chính thức (12/10/2026)

- Mã: `legal_effect_official.py`, chỉ đọc nguồn HTML chính thức được cấu hình tường minh, so số hiệu văn bản **mới** với số hiệu tại chính trang chính thức, sau đó đối chiếu **văn bản cũ**, loại quan hệ, phạm vi và ngày áp dụng từ điều khoản gốc.
- Nguồn ưu tiên: Cơ sở dữ liệu quốc gia về văn bản pháp luật (VBPL). KHÔNG suy ra `ItemID` từ số hiệu, KHÔNG coi URL LuatVietnam là URL pháp luật chính thức, KHÔNG tự suy diễn trạng thái từ nhãn website.
- Chống SSRF: chỉ HTTPS, danh sách host được cho phép, đúng đường dẫn fulltext `/TW/Pages/vbpq-toanvan.aspx?ItemID=N` và biến thể đơn vị ban hành, không redirect, giới hạn tải 5 MB và timeout. Không sử dụng token nào.
- Nếu HTML không truy xuất được, trang chỉ có PDF, kết cấu DOM khác, số hiệu mâu thuẫn, không có điều khoản, phạm vi/chiều/ngày xung đột: giữ `CHUA_XAC_MINH`, đánh dấu `CAN_BO_SUNG_CHUNG_CU` và ghi mã lỗi kiểm soát.
- Đầu ra `official_verification` trong `legal_effect_review.json`: mã phiếu, mã sự kiện, trạng thái đối chiếu, URL gốc, số hiệu tài liệu, chứng cứ có vị trí, phạm vi, ngày, SHA256 đoạn trích. CSV vẫn giữ đúng 28 cột GD1, thêm URL nguồn chính thức + trích dẫn khi đủ điều kiện.
- Trạng thái `OFFICIAL_ACTION_MATCHED_PENDING_LEGAL` chỉ được ghi khi **đúng cặp số hiệu và hành vi, có phạm vi rõ**. Đây là chứng cứ tự động, KHÔNG phải quyết định xác nhận hết hiệu lực. Không nâng thành `DA_XAC_NHAN` hoặc đưa vào kho lưu trữ.
- `OFFICIAL_SCOPE_NEEDS_REVIEW` cho trường hợp văn bản nguồn có câu thay thế/bãi bỏ nhưng chưa rõ phạm vi. Không coi toàn bộ một cách mặc định.
- Tạo `official_sources.json` ở máy chạy, cấu trúc:

```json
{
  "sources": {
    "81/2026/TT-BGDĐT": "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=12345"
  }
}
```

**Ví dụ URL nêu trên chỉ minh họa cấu trúc, tuyệt đối không dùng ItemID=12345 như nguồn đã xác thực.** Phải thay bằng URL toàn văn thực tế đã được kiểm tra bằng tay, đúng số hiệu tài liệu. Có thể lưu file index ở thư mục cục bộ (không commit thông tin cá nhân).

Chạy:

```powershell
python 15_check_legal_effect.py --mode events --workbook "backup.xlsx" --step08-json "output/vbqppl_nhap_batch_payload.json" --official-index "official_sources.json" --output-dir "output/gd2-events"
```

Nếu không truyền `--official-index`, script vẫn chạy như trước và tất cả phiếu chỉ là gợi ý chưa xác minh. Không ghi Google Sheet production hoặc MS Planner.

**Giới hạn hiện tại:** chưa xác minh kết nối HTTP/DOM trên cổng VBPL thật trong môi trường này (kết nối trực tiếp bị hạn chế); bộ test CI chỉ kiểm thử HTML giả lập và hành vi lỗi mạng/URL không tin cậy. Cần chạy E2E GD2.05 trên máy Windows được phép kết nối, bổ sung parser từ PDF chính thức khi cần, và kiểm tra 30 văn bản trước khi nghiệm thu GD2.

## GD2.03 — Test case thực tế: 05/2021/TT-BGDĐT (13/10/2026)

- URL người dùng cung cấp: `https://vbpl.vn/van-ban/chi-tiet/thong-tu-so-05-2021-tt-bgddt-sua-doi-bo-sung-mot-so-dieu-cua-quy-che-thi-tot-nghiep-trung-hoc-pho-thong-ban-hanh-kem-theo-thong-tu-so-15-2020-tt-bgddt-ngay-26-thang-5-nam-2020-cua-bo-truong-bo-giao-duc-va-dao-tao--147477`.
- Khóa tra cứu dự kiến: `05/2021/TT-BGDĐT`. Văn bản này sửa đổi, bổ sung Quy chế ban hành kèm `15/2020/TT-BGDĐT`. Chỉ quan hệ sửa đổi, không được coi là thay thế toàn bộ văn bản gốc.
- Đã mở rộng URL allowlist cho `/van-ban/chi-tiet/<slug>--<id>` của `vbpl.vn`. Có thể thử URL toàn văn/print cũ dựa trên **ID thực sự nằm trong URL đã được cung cấp**; không suy ra ID từ số hiệu.
- Phải kiểm tra số hiệu tại đầu văn bản sau khi tải, điều khoản nguyên văn, chiều quan hệ và điều khoản chuyển tiếp. Trường hợp không chắc chắn → `CAN_BO_SUNG_CHUNG_CU`, không tự xác nhận.
- GitHub CI kiểm thử URL của chính case này dưới dạng offline; **máy container hiện không phân giải được DNS vbpl.vn**, nên chưa có kết quả Python E2E trực tiếp trên VBPL. Không được gọi đây là test truy cập thực tế đã thành công.
- Bộ kiểm chứng `official_html_check` hiện phục vụ mô hình *văn bản mới tác động đến văn bản cũ*; không sử dụng trang thông tư 05 để thay thế việc kiểm tra văn bản bãi bỏ nó sau này. Các điều khoản chuyển tiếp phải được kiểm tra thủ công trước khi xác nhận hết hiệu lực.

## GD2.03 — Kết quả kiểm thử máy chủ thực tế (13/10/2026)

GitHub Actions live probe run 38336187228 (artifact `gd2-vbpl-probe-report`):

- Link `/van-ban/chi-tiet/...--147477`: HTTP 200; 83,287 byte HTML.
- `official_check=IDENTITY_MISMATCH` (parser không tìm thấy số hiệu), `extraction_status=document_root_not_found`, `evidence_blocks=0`.
- Các endpoint VBPL legacy `/TW/Pages/vbpq-toanvan.aspx?ItemID=147477`, `/TW/Pages/vbpq-print.aspx?ItemID=147477` và `/botuphap/Pages/vbpq-print.aspx?ItemID=147477` trả redirect; crawler hiện chặn redirect để bảo vệ SSRF.
- `OVERALL LIVE_HTML_RETRIEVED_PARSER_UNCONFIRMED`; job fail exit 2 theo thiết kế, **chưa nghiệm thu E2E**.
- Việc tiếp theo: phân tích DOM HTML thực (chỉ lưu trích mẫu cấu trúc/selector an toàn); cập nhật parser cho trang hiện hành; kiểm soát redirect cùng host bằng re-validation từng URL; chạy lại và phải nhận đúng 05/2021/TT-BGDĐT, quan hệ sửa đổi 15/2020/TT-BGDĐT. Không bỏ qua xác minh danh tính nguồn để pass test.
- Không ghi dữ liệu production, không sync Planner, PR #16 vẫn Draft.

## GD2.03 FIX — Kết quả điều tra trên server 13/10/2026

- Đã chạy Live Probe ở GitHub Actions: URL VBPL mới có thể trả HTML 200 nhưng BODY chỉ 334 ký tự, không có quốc hiệu/Điều 1, dù tiêu đề và script chứa tham chiếu số hiệu. Đây là trang khung SPA, **không phải toàn văn**.
- Đã chạy Playwright Chromium độc lập: trang VBPL trả HTTP 403 với trình duyệt tự động từ GitHub-hosted runner. **Không tìm cách vượt cơ chế bảo vệ website**.
- Đã cập nhật `fetch_official_html()` theo tối đa 2 lần redirect, từng đích yêu cầu HTTPS + đúng whitelist/đường dẫn cấu trúc VBPL; không redirect tự động tới host khác.
- Parser phân biệt `CLIENT_RENDER_REQUIRED` (khung JavaScript có số hiệu trong title nhưng không có toàn văn) với `IDENTITY_MISMATCH` (sai số hiệu); cả hai đều **không phải** chứng cứ xác minh.
- Có test đảm bảo khung HTML có tiêu đề đúng **không** tạo kết luận; test redirect cùng host cho phép và redirect ra ngoài chặn. Các báo cáo kiểm thử chỉ lưu metadata, không lưu HTML toàn trang hoặc token.
- Giới hạn: Mặc dù đã kiểm thử máy chủ thực tế và sửa cơ chế, **chưa thể E2E xác nhận điều khoản 05/2021 sửa đổi 15/2020** khi VBPL không trả toàn văn cho HTTP client và chặn Playwright. Để nghiệm thu cần nguồn chính thức truy cập được (PDF/tải hợp lệ, endpoint công bố hoặc truy cập trình duyệt thủ công xuất file) hoặc môi trường được VBPL cho phép, sau đó kiểm thử lại. Tránh gán trạng thái hết hiệu lực chỉ từ tiêu đề.
- PR #16 vẫn Draft, không ghi Apps Script, Google Sheets hay Planner.

## GD2.03 — Kiểm thử trên máy Windows có trình duyệt hợp lệ

GitHub-hosted runner không điều khiển trực tiếp được phiên Cốc Cốc của người dùng. Đã bổ sung `scripts/gd2_vbpl_windows_test.py`: chạy foreground, mở profile mới cô lập, sử dụng trình duyệt được cài trên chính Windows người vận hành; KHÔNG lấy cookie/session của profile thực, KHÔNG ghi Apps Script/Sheets/Planner. Đây là bài test chờ người vận hành chạy, KHÔNG phải kết quả E2E đã xác nhận.

```powershell
git fetch origin
git switch feat/gd2-legal-effect-analysis-20261012
python -m pip install beautifulsoup4 playwright
python scripts/gd2_vbpl_windows_test.py
```

Có thể truyền `--browser-path "C:\Program Files\CocCoc\Browser\Application\browser.exe"` nếu không dò được Cốc Cốc, hoặc cài Chromium do Playwright phân phối. Bài test dùng `headless=False`, không gắn vào profile đang đăng nhập; website từ chối truy cập phải báo `SITE_ACCESS_DENIED`, không tìm cách vượt chặn. File báo cáo tại `output/gd2-windows-vbpl-test.json` chỉ ghi trạng thái, mã phiếu, vị trí chứng cứ, không ghi HTML/token.

Điều kiện đạt: `outcome=PROVISIONAL_PASS_PENDING_LEGAL`, `extraction_status=ok`, đúng số hiệu 05/2021/TT-BGDĐT, relation `SUA_DOI_BO_SUNG` tác động tới 15/2020/TT-BGDĐT; kết luận cuối vẫn đợi Pháp chế. Nếu thất bại, lưu báo cáo và điều chỉnh selector theo dữ liệu nguồn được phép chia sẻ; không kết luận chưa có hiệu lực chỉ vì không tải được trang.

Lưu ý: việc chuyển nhánh của máy vận hành cần do người vận hành thực hiện ở một bản checkout thử nghiệm tách biệt, tránh làm xáo trộn pipeline Windows hiện chạy production. Không bật scheduler cho script này.

## GD2.03 — Nghiệm thu thực tế ca VBPL 05/2021 trên Windows (13/10/2026)

**Nguồn báo cáo:** Người vận hành cung cấp trực tiếp JSON từ `output/gd2-windows-vbpl-test.json`, chạy bằng `scripts/gd2_vbpl_windows_test.py` trên bản checkout riêng; đây là bằng chứng do người vận hành cung cấp, **không phải phiên chạy Windows do GitHub Actions hoặc trợ lý trực tiếp quan sát**.

- Giờ báo cáo: `2026-10-13T08:15:32+00:00` (15:15:32 giờ Việt Nam).
- HTTP `200`, hostname `vbpl.vn`; `document_title_matches=true`.
- `extraction_status=ok`; vùng nguồn `structural_vbpl_rendered_root`; `evidence_blocks=119`.
- Văn bản tác động: `05/2021/TT-BGDĐT`; văn bản chịu tác động: `15/2020/TT-BGDĐT`.
- Quan hệ phát hiện: `SUA_DOI_BO_SUNG`; `scope_type=MOT_PHAN`.
- Chứng cứ: `structural_vbpl_rendered_root:paragraph[7]`, thuộc `Điều 1. Sửa đổi, bổ sung một số điều của Quy chế...`. Mã sự kiện `735c1058fb624b560fdf9d1b`.
- `outcome=PROVISIONAL_PASS_PENDING_LEGAL`; `verification_status=CHO_XAC_MINH`; `requires_legal_review=true`; `production_writes=false`.

**Phán định:** ĐẠT bài kiểm thử tích hợp kỹ thuật **một ca** cho phép truy cập và trích xuất trên môi trường Windows đã được người vận hành thử; khắc phục lỗi trước đây `source_section` rỗng. **Không** chứng minh độ chính xác trên mọi văn bản, không phải xác minh pháp lý hoàn tất, không có ghi/sync dữ liệu production.

**Điểm cần rà soát:** `paragraph[7]` có thể chính là tiêu đề Điều 1; cần đối chiếu `evidence_text` của sự kiện với nội dung khoản sửa đổi dưới Điều 1 để xác nhận chính xác phần nội dung tác động và mức độ chi tiết. Trước khi triển khai tự động, nên kiểm thử thêm văn bản thay thế toàn bộ, bãi bỏ một phần, chuyển tiếp, hết hiệu lực trong tương lai và văn bản không có quan hệ.

**Quyết định vận hành:** Giữ PR #16 Draft; chuyển sang GD2.04 đối soát định danh/khử trùng dữ liệu, sau đó GD2.05 kiểm thử E2E đủ nhiều trường hợp và Pháp chế xác minh.

## GD2.04 — Đối chiếu định danh nguồn và chống trùng (13/10/2026)

Tình trạng: **mã nguồn và kiểm thử tự động đã bổ sung, chưa chạy migration hoặc ghi production**.

- `legal_effect_identity.py`: đối chiếu hai sheet theo số hiệu chuẩn hóa, **không** coi số hiệu tự nó là bằng chứng duy nhất. Bảo toàn ID của hai nguồn, flag `MULTIPLE_DOCUMENT_IDS`, `DOCUMENT_TYPE_CONFLICT`, `ISSUING_AUTHORITY_CONFLICT`, `MULTIPLE_VALID_SOURCE_URLS`, `NON_URL_DOCUMENT_LINK`, `TITLE_VARIANTS`, `NONSTANDARD_DOCUMENT_NUMBER`. Trường URL chỉ chấp nhận URL HTTP(S) công khai hợp lệ, không biến nhãn văn bản thành URL.
- `15_check_legal_effect.py`: gắn `identity_audit` trong báo cáo JSON; giữ **28 cột GD1** trong CSV; `ID nguồn VBQPPL` / `ID nguồn VBQPPL_Nhap` vẫn lưu đủ; `Dấu vân tay nguồn` ổn định khi thay thứ tự dòng; `Phạm vi tác động` lấy đúng `affected_scope`, không lấy `direction` như trước. Các khóa có xung đột định danh nghiêm trọng chuyển sang `CAN_BO_SUNG_CHUNG_CU`.
- **Đối chiếu bản sao offline** `BACKUP_FULL_Data_TraCuuVanBan_PRE_PHASE0_2026-10-12.xlsx` do người vận hành cung cấp: 190 VBQPPL + 341 VBQPPL_Nhap = 531 bản ghi có số hiệu, 339 số hiệu chuẩn hóa; 188 số hiệu ở cả hai nguồn; 54 link tại `VBQPPL` thực chất là nhãn/văn bản, không phải URL; có 2 số hiệu với nhiều mã ID là `32/2025/TT-BTC` và `46/2014/QH13`. Riêng trường hợp `46/2014/QH13` có tiêu đề Luật Sở hữu trí tuệ ở một ID nhưng URL gắn Luật Bảo hiểm y tế: **cảnh báo mâu thuẫn nguồn, cần Pháp chế xác nhận**; không tự sửa.
- `339` là số khóa số hiệu, KHÔNG được mặc nhiên kết luận có đúng 339 thực thể pháp lý độc lập. Không thay đổi ID gốc, bảo vệ các trường thủ công và không tạo/xóa Planner.
- Chưa thể xác nhận cơ quan ban hành cho toàn bộ nguồn vì nguồn snapshot không có cột `Cơ quan ban hành`; đánh dấu chưa biết, không tự suy ra từ số hiệu hoặc tên đơn vị.

## GD2.05 — Bộ kiểm thử đa văn bản trên Windows (13/10/2026)

Tình trạng: **đã triển khai runner và test offline, chưa có dữ liệu đối chứng pháp chế đủ 30 ca thực tế**.

- `scripts/gd205_validate_official_samples.py`: đọc tối đa 30 ca từ `docs/gd205_case_manifest.json`, mỗi ca gồm `id`, URL nguồn VBPL chính thức, số hiệu văn bản mới, số hiệu văn bản cũ, quan hệ dự kiến và `label_status`. Chỉ mở trình duyệt Windows với profile mới, *headless=False*, không tái sử dụng cookie phiên cá nhân và không bypass HTTP 403. Chỉ ghi mã trạng thái, vị trí điều khoản, phạm vi, kết quả và metadata vào `output/gd205-validation.json`.
- Manifest hiện có **1 ca đã kiểm thử kỹ thuật trên Windows**: TT 05/2021/TT-BGDĐT sửa đổi TT 15/2020/TT-BGDĐT. Để `PENDING_HUMAN` vì **được xác nhận kỹ thuật không đồng nghĩa được Pháp chế dán nhãn chuẩn**.
- Đánh giá tách biệt 3 lớp: tỷ lệ tải thành công, tỷ lệ lấy toàn văn, tỷ lệ phát hiện khớp quan hệ dự kiến. Không báo precision/recall pháp lý khi chưa có đầy đủ ground-truth gồm cả ví dụ âm tính; cột chỉ tiêu này trả `null`. Với các ca dán nhãn `HUMAN_VERIFIED`, chỉ thống kê **khả năng tìm lại trên tập ca dương tính đã lựa chọn**, không gọi đó là precision tổng thể.
- Không tự bịa 29 link hoặc gắn nhãn căn cứ pháp luật chưa kiểm tra. Ở giai đoạn thí điểm có thể bổ sung dần các ca thay thế toàn bộ, bãi bỏ một phần, sửa đổi, ngày tương lai, ngoại lệ chuyển tiếp, và ca không có quan hệ; muốn đánh giá false positive cần mở rộng manifest riêng với nhãn âm tính.
- Lệnh trên **checkout thử nghiệm riêng** của máy Windows đã xác nhận truy cập được vbpl.vn:

```powershell
git pull origin feat/gd2-legal-effect-analysis-20261012
python scripts/gd205_validate_official_samples.py
```

- Nếu báo `MATCH_PENDING_HUMAN` đây là phát hiện kỹ thuật **cần xác minh**, không phải `DA_XAC_NHAN` hay `HET_HIEU_LUC_TOAN_BO`. Không triển khai lịch chạy tự động vào production và không merge PR #16 khi chưa nghiệm thu đủ bộ mẫu.

## GD2.05 — Kết quả Windows một ca và mở rộng đối chứng (13/10/2026)

Người vận hành gửi kết quả `output/gd205-validation.json` (chỉ báo cáo tóm tắt): `total_cases=1`, `cases_run=1`, `http_200=1`, `legal_text_extracted=1`, `provisional_matches=1`, `MATCH_PENDING_HUMAN=1`, `human_labelled_cases=0`, `legal_confirmation=false`, `production_writes=false`. **Kết luận: PASS kỹ thuật một ca, chưa đạt nghiệm thu 30 ca và chưa có kết luận pháp chế.**

Đã mở rộng `scripts/gd205_validate_official_samples.py` cho nhãn đối chứng:
- `label_status=PENDING_HUMAN`: chưa có nhãn sự thật, không kèm `expected_present`/`label_basis`.
- `label_status=HUMAN_VERIFIED`: phải có `expected_present=true|false` (tác động đúng loại quan hệ có/không) và `label_basis` là căn cứ kiểm tra độc lập. Không đưa URL/trích dẫn chưa rà soát thành ground truth.
- `NO_MATCH` được xử lý như dự đoán âm tính hợp lệ khi toàn văn nguồn được nhận diện đầy đủ; riêng lỗi mạng/không có DOM không bị gán âm tính và không được che khỏi báo cáo.
- Báo cáo lưu TP/TN/FP/FN và số ca chưa đủ điều kiện đánh giá. **Precision/recall chỉ hiện số** khi đã đủ 30 trường hợp có nhãn, cả hai lớp dương và âm và đều kiểm tra được. Nếu chưa đủ thì `null`.
- Bộ thử offline bổ sung trường hợp âm tính thật, dương tính giả, lỗi nguồn và tập đã gắn nhãn đủ 30. Các phép thử này mô phỏng, không chứng minh độ chính xác pháp lý.

**Mức độ sẵn sàng:** PR #16 Draft; thí điểm 1 trường hợp Windows thành công; chờ bổ sung 29 URL hợp lệ và nhãn được rà soát. Không ghi Google Sheets/Planner, không deploy production.

## GD2.05 — Bộ 30 trang VBPL kiểm thử (14/10/2026)

- Đã tạo **30 ca trên 30 hồ sơ VBPL có ID URL khác nhau** tại `docs/gd205_case_manifest.json`. Gồm **11 ca dự kiến dương tính** (`POSITIVE_CANDIDATE`) và **19 ca thăm dò kiểm soát âm tính** (`NEGATIVE_CONTROL_CANDIDATE`).
- URL được đối chiếu theo kết quả tìm kiếm nguồn VBPL công khai; trạng thái `PENDING_HUMAN` áp dụng đồng loạt. **Chưa phải 30 ca kết quả pháp chế đã xác minh**; các mẫu âm tính có thể có quan hệ khác trong điều khoản và cần được Pháp chế phân xử.
- Mỗi ca có URL cụ thể, số hiệu văn bản đang quét, số hiệu cặp tham chiếu, loại quan hệ thăm dò và `review_hint` cho người rà soát. Không gán `expected_present=true/false` trước khi đối chứng pháp chế.
- Các ca quan trọng: TT 05/2021/TT-BGDĐT sửa đổi 15/2020/TT-BGDĐT; TT 07/2024/TT-BGDĐT sửa đổi 13/2021/TT-BGDĐT; TT 02/2024/TT-BTTTT có khoản hết hiệu lực và chuyển tiếp; TT 08/2024/TT-BYT bãi bỏ một phần; TT 15/2024/TT-BLĐTBXH bãi bỏ văn bản; TT 104/2024/TT-BQP thay thế/bãi bỏ mẫu biểu. Các trường hợp chỉ nêu nghị định tại phần căn cứ làm ca âm tính thăm dò, không khẳng định không có tác động nếu chưa rà soát toàn văn.
- Lưu ý: `HET_THOI_HAN` là nhãn thăm dò cho TT 02/2024/TT-BTTTT với quy định hết hiệu lực văn bản cũ; cần đối chiếu phân loại nghiệp vụ khi có bằng chứng, tránh suy luận hết thời hạn đồng nghĩa bãi bỏ.
- Chạy **chỉ đọc**, chỉ trên bản clone thử nghiệm Windows đã hoạt động: `git pull origin feat/gd2-legal-effect-analysis-20261012`, sau đó `python scripts/gd205_validate_official_samples.py`. Đầu ra `output/gd205-validation.json`, bao gồm tất cả trạng thái đọc, quan hệ, lỗi truy cập và thống kê chưa được xác nhận.
- Không ghi production, không sửa token, không deploy, không gộp PR #16. Giai đoạn tiếp theo: kiểm tra đủ 30 ca Windows; căn cứ trích từ điều khoản, nhãn đối chứng Pháp chế; sửa parser nếu có lỗi; kiểm tra tỷ lệ đạt tối thiểu được phê duyệt.

## GD2.05 — Windows 30 ca, sự cố legacy redirects (14/10/2026)

Người vận hành chạy manifest 30 ca trên bản checkout Windows, báo cáo: `total_cases=30`, `http_200=30`, `legal_text_extracted=1`, `provisional_matches=1`, `UNTRUSTED_REDIRECT=29`, `human_labelled_cases=0`. **Không được tính 29 trường hợp là âm tính pháp lý** hoặc kết luận có toàn văn truy xuất được chỉ dựa trên HTTP 200.

Nguyên nhân kỹ thuật xác định từ logic runner: 29 ca sử dụng địa chỉ legacy `/TW/Pages/vbpq-toanvan.aspx?ItemID=...`; browser đã chuyển đến URL khác, `canonical_official_url(page.url)` không cho phép, trước khi kiểm tra HTML. **Chưa biết trang cuối cùng của cả 29 ca** do báo cáo cũ không lưu loại điểm đến; có thể là trang chủ portal, đường dẫn mới, hoặc luồng khác. Không nới allowlist để chấp nhận trang chủ, URL khác host, hoặc thay đổi ID.

Đã bổ sung diagnostic `navigation` chỉ gồm loại đường dẫn đích (`PORTAL_HOME`, `MODERN_DETAIL`, `LEGACY_DOCUMENT`, `UNRECOGNIZED_OFFICIAL_PATH`, `EXTERNAL_OR_INSECURE`), host đã giới hạn, khớp ID hoặc không. Không lưu URL cuối, cookie, HTML. Mã trạng thái mới `LEGACY_REDIRECT_TO_HOME` và `SOURCE_ID_CHANGED` là lỗi nguồn, không phải `NO_MATCH`. Có thể chạy chọn ca `--case-indexes 2,3,12` để chẩn đoán mà không quét lại 30 trang.

Bước tiếp theo: người vận hành chạy 3 ca, gửi `results[].navigation`; sửa các URL legacy chỉ khi có URL hiện đại, ID và **số hiệu nội dung** khớp, xác minh từng nguồn. Nếu chuyển về trang chủ, phải thay URL nguồn, không coi đường chuyển hướng là toàn văn. PR #16 tiếp tục Draft; không ghi production.

## GD2.05 — Chẩn đoán URL chuyển về trang chủ và phép thử URL mới (14/10/2026)

Người vận hành đã chạy 3 ca đại diện: **GD205-002, GD205-003 và GD205-012 đều có HTTP 200 nhưng `LEGACY_REDIRECT_TO_HOME`**, đường dẫn cuối `PORTAL_HOME`, số đoạn chứng cứ bằng 0. Điều này xác nhận **trang chủ không phải toàn văn**, và phương pháp dùng URL VBPL legacy `/TW/Pages/vbpq-toanvan.aspx?ItemID=...` không phù hợp với các ca được thử. Không được coi các trường hợp này là kết quả âm tính pháp lý.

Đã bổ sung phương án thăm dò `--probe-same-id-modern` trong `scripts/gd205_validate_official_samples.py`: chỉ khi URL legacy chuyển về trang chủ, dựng **URL ứng viên chưa xác minh** thuộc `/van-ban/chi-tiet/` bằng ID hồ sơ `ItemID` đã có và slug tên số hiệu, sau đó mở trang trên Windows. Ứng viên này **không tự động được coi là URL chính thức**. Chỉ đề xuất `proposed_source_url` nếu đường dẫn cuối nằm trong allowlist HTTPS, có **cùng ID**, tiêu đề **khớp số hiệu mới**, bộ tách nội dung xác định được toàn văn và trả `MATCH_PENDING_HUMAN` hoặc `NO_MATCH`. Nếu trang chủ hoặc sai ID, dừng ở lỗi. Không tự ghi lại manifest, không nới whitelist, không thao tác Sheet/Planner.

Lệnh chạy thử **3 ca trước** trên clone Windows riêng:
```powershell
git pull origin feat/gd2-legal-effect-analysis-20261012
python scripts/gd205_validate_official_samples.py --case-indexes 2,3,12 --probe-same-id-modern --output output/gd205-modern-probe.json
```
Chỉ sau khi người vận hành cung cấp kết quả mới được đánh giá xem có thể cập nhật URL nguồn không. Các ca còn lại chưa có URL hiện đại đã được kiểm chứng.

## GD2.05 — Kết quả thử đường dẫn hiện đại trên Windows, 3 ca (14/10/2026)

**Nguồn bằng chứng:** JSON summary do người vận hành cung cấp sau lệnh `python scripts/gd205_validate_official_samples.py --case-indexes 2,3,12 --probe-same-id-modern --output output/gd205-modern-probe.json`. Đây là kết quả người vận hành báo lại; **chưa có JSON chi tiết `results[]` để xác định từng ca thành công hay không và URL nào có thể được xác nhận**.

- `total_cases=3`, `cases_run=3`, `http_200=3`, `legal_text_extracted=3`.
- `provisional_matches=1`, `result_counts={MATCH_PENDING_HUMAN:1, NO_MATCH:2}`.
- Bộ thử gồm `positive_candidate_cases=2`, `negative_control_candidate_cases=1`. **Không thể từ summary xác định `MATCH_PENDING_HUMAN` thuộc ca nào**; phải xem `results[].id` trước khi kết luận ca dương/âm được nhận diện đúng.
- `negative_controls_without_match=1` theo bộ đếm, nhưng **chưa có nhãn Pháp chế**, nên không được tính là true negative đã nghiệm thu.
- `human_labelled_cases=0`, `classification_precision=null`, `classification_recall=null`, `legal_confirmation=false`, `production_writes=false`.
- Kết quả khẳng định cơ chế probe có thể lấy được nội dung 3/3 ca vừa thử, cải thiện so với `LEGACY_REDIRECT_TO_HOME` cho cả 3 ca ở lượt trước. **Không** khẳng định cả 29 URL legacy còn lại sẽ được xử lý thành công; không tự động thay thế các URL trong manifest dựa trên summary.

**Bước tiếp:** chạy 30 ca với `--probe-same-id-modern`, lưu JSON đầy đủ ở `output/gd205-modern-30.json`; đối chiếu `results[].id/result/navigation/proposed_source_url/matches` trước khi cập nhật manifest. Mọi ca `NO_MATCH` trên nhóm dương tính dự kiến phải rà soát chứng cứ Điều/Khoản, không tự đổi nhãn âm tính. PR #16 giữ Draft; không ghi production.

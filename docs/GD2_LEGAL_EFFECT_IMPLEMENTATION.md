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

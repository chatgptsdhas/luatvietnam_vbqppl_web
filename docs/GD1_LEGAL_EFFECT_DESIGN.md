# GD1 — Đặc tả rà soát và lưu trữ hiệu lực VBQPPL (đề xuất)

Ngày: 12/10/2026. Trạng thái: **BẢN THIẾT KẾ, chưa triển khai production**.

Bản mẫu dữ liệu độc lập: https://docs.google.com/spreadsheets/d/1TBv7pX52AVAurH72ikkA3OGSKRPSpV9y0OsCoOTkTnY/edit

## 1. Phạm vi và nguyên tắc

- Nguồn: `VBQPPL` (26 cột) và `VBQPPL_Nhap` (26 cột khác thứ tự và ngữ nghĩa).
- Dữ liệu rà soát ban đầu: 190 + 341 dòng dữ liệu, 339 số hiệu chuẩn hóa phân biệt. 339 chỉ là số khóa sơ bộ, không mặc nhiên tương đương 339 văn bản pháp lý duy nhất.
- Đích: `VBQPPL_RaSoatHieuLuc` (máy đề xuất, người duyệt), `VBQPPL_HetHieuLuc` (kho xác nhận hết hiệu lực toàn bộ).
- Tuyệt đối không tự xóa dòng nguồn hoặc thay đổi dữ liệu Planner. Không coi điều khoản sửa đổi/bổ sung là bằng chứng hết hiệu lực toàn bộ.
- Chỉ tiêu nghiệp vụ: không mất bản ghi; không nhân đôi hồ sơ lưu trữ; lưu trữ có bằng chứng và định danh người phê duyệt; khả năng hoàn tác bằng trạng thái.

## 2. CV04 — Chính sách xác định tình trạng hiệu lực

### 2.1 Trường tình trạng (enum)

- `CHUA_XAC_MINH`: thiếu chứng cứ/không truy cập nguồn/nguồn xung đột.
- `CHUA_CO_HIEU_LUC`: văn bản đã ban hành nhưng chưa đến ngày bắt đầu áp dụng.
- `CON_HIEU_LUC`: đã xác minh còn hiệu lực, không có thay đổi hết hiệu lực được xác nhận.
- `HET_HIEU_LUC_MOT_PHAN`: căn cứ pháp lý xác định phạm vi hết hiệu lực một phần.
- `HET_HIEU_LUC_TOAN_BO`: căn cứ pháp lý xác định toàn bộ nội dung hết hiệu lực và thời điểm đã đến.
- `DINH_CHI_MOT_PHAN`, `DINH_CHI_TOAN_BO`: đình chỉ, KHÔNG đồng nghĩa hết hiệu lực; xử lý riêng.

`SAP_HET_HIEU_LUC` chỉ là **nhãn cảnh báo có tính thời gian** sinh từ ngày hết hiệu lực đã xác minh, không là tình trạng pháp lý cuối cùng; ngày chưa đến thì không lưu trữ.

### 2.2 Quan hệ tác động

`THAY_THE_TOAN_BO`, `BAI_BO_TOAN_BO`, `BAI_BO_MOT_PHAN`, `SUA_DOI_BO_SUNG`, `HET_THOI_HAN`, `HET_HIEU_LUC_VB_CHI_TIET`, `DINH_CHI`, `KHAC`.

Quan hệ là dữ liệu đầu vào **không tự suy ra** tình trạng toàn bộ/một phần khi thiếu điều khoản cụ thể. Đặc biệt kiểm tra ngoại lệ văn bản quy định chi tiết được công bố tiếp tục có hiệu lực.

### 2.3 Quyết định

- Python thu thập nội dung văn bản mới (Lược đồ, điều khoản thi hành, văn bản bị thay thế, bị bãi bỏ), rà soát lại văn bản cũ định kỳ; ghi đề xuất và trích dẫn/URL nguồn.
- Pháp chế xác minh văn bản cũ, ngày tác động, phạm vi điều/khoản, chuyển tiếp, văn bản giữ hiệu lực và độ tin cậy.
- Chỉ chuyển kho khi **`Trạng thái xác minh=DA_XAC_NHAN` + `Tình trạng hiệu lực=HET_HIEU_LUC_TOAN_BO` + ngày hết hiệu lực <= ngày hệ thống + có căn cứ chính thức**.
- Trường hợp nguồn hỏng/xung đột => `CAN_BO_SUNG_CHUNG_CU`; không cho phép lưu kho.
- Các trường hợp chỉ hết hiệu lực một phần hoặc đình chỉ: giữ tại nguồn, hiển thị chú thích và căn cứ, không chuyển lưu trữ toàn bộ.

Nguồn pháp lý nền: Luật Ban hành văn bản quy phạm pháp luật 64/2025/QH15, sửa đổi/bổ sung 87/2025/QH15. Phải xác minh chính văn bản hiện hành và điều khoản liên quan trong từng trường hợp, ưu tiên CSDL quốc gia vbpl.vn; LuatVietnam là nguồn trích xuất hỗ trợ, không thay chứng cứ chính thức.

## 3. CV05 — Hợp đồng dữ liệu

### 3.1 Sheet rà soát (28 cột)

`Mã phiếu rà soát`, `Khóa văn bản chuẩn`, `Số hiệu`, `Loại văn bản`, `Tên văn bản`, `Nguồn xuất hiện`, `ID nguồn VBQPPL`, `ID nguồn VBQPPL_Nhap`, `URL văn bản gốc`, `Ngày bắt đầu hiệu lực`, `Tình trạng hiệu lực đề xuất`, `Loại quan hệ`, `Văn bản tác động`, `Ngày hiệu lực tác động`, `Phạm vi tác động`, `Trích dẫn điều khoản`, `URL nguồn chính thức`, `URL nguồn bổ trợ`, `Mức tin cậy`, `Trạng thái xác minh`, `Người xác minh`, `Thời gian xác minh`, `Kết luận pháp chế`, `Thời gian quét`, `Khóa sự kiện`, `Dấu vân tay nguồn`, `Lỗi hoặc ngoại lệ`, `Ghi chú vận hành`.

### 3.2 Kho hết hiệu lực (33 cột)

`Mã hồ sơ lưu trữ`, `Khóa văn bản chuẩn`, `Số hiệu`, `Loại văn bản`, `Tên văn bản`, `Lĩnh vực`, `Chủ đề`, `Mục`, `Ngày bắt đầu hiệu lực`, `Ngày hết hiệu lực`, `Tình trạng hiệu lực xác nhận`, `Văn bản tác động`, `Loại quan hệ`, `Phạm vi hết hiệu lực`, `Điều khoản căn cứ`, `URL căn cứ chính thức`, `URL văn bản gốc`, `Nguồn xuất hiện`, `ID nguồn VBQPPL`, `ID nguồn VBQPPL_Nhap`, `Mã phiếu rà soát`, `Người xác nhận`, `Thời gian xác nhận`, `Thời gian lưu trữ`, `Trạng thái lưu trữ`, `Planner Task ID`, `Planner Sync Status`, `Bộ phận chủ trì`, `Mức độ tác động`, `Khóa idempotency`, `Dấu vân tay nguồn`, `Snapshot nguồn JSON`, `Ghi chú lịch sử`.

Dữ liệu ngày mới trao đổi qua ISO `YYYY-MM-DD` tại API; hiển thị `dd/MM/yyyy` trên Dashboard. Không đổi cách ghi các cột ngày hiện hữu trong nguồn.

### 3.3 Định danh và quan hệ

- `_rowNumber` chỉ là địa chỉ vật lý tức thời; **không làm khóa nghiệp vụ hoặc idempotency**.
- `Số hiệu` chuẩn hóa chữ hoa, khoảng trắng, Unicode dấu gạch; để tránh nhập nhằng, khóa văn bản xác định từ số hiệu + loại + cơ quan ban hành khi có, đối chiếu nguồn URL và ID; cần xử lý trường hợp số hiệu xung đột thủ công.
- Phiếu rà soát có `review_id` bất biến, sự kiện có `event_key` theo văn bản cũ + văn bản tác động + loại quan hệ + phạm vi/điều khoản + ngày tác động; cùng sự kiện chỉ update một phiếu.
- Kho có `archive_id`/khóa idempotency duy nhất theo `document_key`, **chỉ 1 hồ sơ hiệu lực toàn bộ tại một thời điểm**; giữ dấu vết tất cả vị trí xuất hiện nguồn.
- Lưu `source snapshot` để phục hồi và đối chiếu. Nếu JSON có dữ liệu nhạy cảm, áp dụng hạn chế truy cập và không ghi vào client/log.
- Cột source status nên là chỉ mục nghiệp vụ tách biệt; không tự thêm giá trị mới vào `Trạng thái duyệt` hay `Trạng thái xử lý` cũ khi chưa cập nhật cả validation, pipeline và Dashboard.

### 3.4 Di trú

- Bảy bản ghi `Lỗi tải link` tại `VBQPPL_HetHieuLuc` cũ là **nhật ký lỗi**, không được đưa vào danh sách đã hết hiệu lực.
- Sao lưu và chuyển chúng sang sheet log riêng trước khi áp dụng schema mới.
- Trong sandbox GD1: `GD1_LogQuetCu_7Dong` giữ nguyên 7 dòng; tạo mới `VBQPPL_RaSoatHieuLuc`, `VBQPPL_HetHieuLuc` trên bản sao; chưa thay đổi production.
- Migration production phải kèm backup, checksum/row counts, preflight validation, dry run, idempotent upsert, đối soát sau ghi và rollback.
- Hệ thống `get_expired_records` hiện đọc sheet theo tên, nên **KHÔNG triển khai sheet schema mới trước khi cập nhật WebApp và Dashboard tương thích**.

## 4. CV06 — Quy trình xác nhận, lưu trữ và hoàn tác

1. Python quét sự kiện mới / danh mục tồn đọng -> gửi kết quả bằng service action nhóm B (service token riêng, không fallback), chỉ được ghi vào *staging review*.
2. Backend chuẩn hóa số hiệu + đối chiếu IDs trong 2 nguồn, dùng `event_key` chống nhân bản, không viết đè cột được bảo vệ thủ công.
3. Dashboard đọc danh sách rà soát (nhóm C nếu chứa dữ liệu chỉ admin); người quản trị xem trích dẫn và nguồn, xác nhận/từ chối/bổ sung chứng cứ.
4. Backend bắt buộc `requireAdminSession_()` cho xác nhận và chuyển lưu kho; xác minh `review_id`, trạng thái, ngày, căn cứ; khóa giao dịch, kiểm tra lại nguồn trước khi ghi.
5. Ghi hồ sơ lưu trữ/nhật ký bất biến trước; đọc đối soát; **sau đó** đánh dấu hồ sơ nguồn là lưu trữ trong chỉ mục độc lập; không xóa vật lý, không sửa `Planner Task ID`.
6. Nếu một bước lỗi, giữ trạng thái `CAN_DOI_SOAT`, retry theo cùng idempotency key; không giả định multi-sheet transaction nguyên tử.
7. Hoàn tác: yêu cầu admin, ghi lý do + người + thời gian, đánh dấu archive `DA_HOAN_TAC`, phục hồi chỉ mục active có kiểm tra xung đột; không xóa audit trail.
8. Trường hợp văn bản được xác minh còn hiệu lực một phần, ghi kết quả tại review/index; không lưu vào kho hết hiệu lực toàn bộ.

### Trạng thái nghiệp vụ

Review: `CHO_XAC_MINH` -> `DANG_RA_SOAT` -> `DA_XAC_NHAN` | `TU_CHOI` | `CAN_BO_SUNG_CHUNG_CU`.

Archive: `DA_LUU` | `CAN_DOI_SOAT` | `DA_HOAN_TAC`.

## 5. Biên an toàn, kiểm thử và điểm còn mở

- Không sửa token công khai/service; action C luôn qua admin session, action B luôn qua service token; không tiết lộ secret/stack trace.
- `apps_script/Module_HetHieuLuc.js` logic xóa cũ phải được vô hiệu hóa trên Apps Script thực tế theo GD0; PR #14 chỉ là bản vá trên GitHub, **không đồng nghĩa đã deploy**.
- Dashboard tĩnh `index.html` không thêm framework/build step. Planner không bị tự động đóng/xóa chỉ vì văn bản hết hiệu lực.
- Unit/integration tests: một văn bản xuất hiện hai nguồn; số hiệu cùng nhưng văn bản khác; thay thế toàn bộ; bãi bỏ một phần; sửa đổi/bổ sung; văn bản có ngày hiệu lực tương lai; văn bản được công bố tiếp tục hiệu lực; thiếu chứng cứ; mất mạng; retry idempotent; thất bại giữa lúc ghi hai sheet; khôi phục; quyền public/service/admin.
- Cần xác nhận người có thẩm quyền và tiêu chí chứng cứ tối thiểu khi đóng phiếu. Việc rà soát 339 số hiệu chưa có kết luận pháp lý đầy đủ và không nằm trong giai đoạn 1.
- Cần xác minh production deployment / trigger từ GD0 trước khi migration.

## 6. Nghiệm thu giai đoạn 1

- [x] CV04: tập trạng thái, phân loại quan hệ, quy tắc pháp chế xác nhận.
- [x] CV05: đặc tả schema 28 và 33 cột, migration sandbox và tương thích ngược.
- [x] CV06: khóa/idempotency, luồng review -> archive -> revert, bảo vệ Planner.
- [ ] Nghiệm thu của chủ hệ thống/Pháp chế để dùng làm data contract sản xuất.
- [ ] Triển khai/đóng GD0 trên production (mục riêng, không nhập nhằng với GĐ1).

**Không có migration hoặc thao tác ghi lên file Google Sheets production trong tài liệu này.**

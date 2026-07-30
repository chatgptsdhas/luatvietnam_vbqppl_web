# Decisions and Open Issues

## 1. Mục đích

Tài liệu này lưu các quyết định kiến trúc/nghiệp vụ đã thống nhất và các vấn đề còn mở. Chỉ ghi quyết định đã được người có thẩm quyền xác nhận; không biến đề xuất của AI thành quyết định mặc nhiên.

## 2. Quyết định hiện hành

### ADR-001 — GitHub là nguồn sự thật của mã nguồn

- Trạng thái: Áp dụng.
- Quyết định: Code phải được nghiên cứu từ repository và ref cụ thể. Không dùng bản sao code đã tải vào ChatGPT Project làm nguồn ưu tiên.
- Hệ quả: Không tải toàn bộ source code hoặc ZIP repo vào mục Nguồn của Project.

### ADR-002 — Apps Script là API và lớp nghiệp vụ trung tâm

- Trạng thái: Áp dụng theo kiến trúc hiện tại.
- Quyết định: Dashboard không ghi trực tiếp Google Sheets; mọi thao tác đi qua Apps Script và kiểm tra quyền backend.
- Không được tự ý: bỏ backend authorization hoặc dùng UI state làm quyền.

### ADR-003 — Tách ba nhóm quyền A/B/C

- Trạng thái: Áp dụng.
- Quyết định:
  - A: public read;
  - B: service/machine-to-machine;
  - C: admin/write.
- Hệ quả: Mỗi action mới phải được phân loại và kiểm thử ranh giới quyền.

### ADR-004 — Planner Sync Server tiếp tục chạy cục bộ

- Trạng thái: Áp dụng cho đến khi có quyết định thay đổi kiến trúc.
- Quyết định: Server bind localhost, được duy trì qua Windows Scheduled Task, request ghi bắt buộc HMAC.
- Không được tự ý: expose ra Internet hoặc đưa Microsoft credential xuống frontend.

### ADR-005 — Frontend không được giữ secret

- Trạng thái: Áp dụng.
- Quyết định: Project token trong Dashboard chỉ là nhận diện ứng dụng và được coi là public. Service token, shared secret, password hash material và Microsoft token không được đưa xuống browser.

### ADR-006 — Không suy ra production từ `main`

- Trạng thái: Áp dụng.
- Quyết định: Khi phân tích production phải xác nhận commit/deployment/version/process thực tế.

## 3. Các giới hạn/technical debt đã biết

- Dashboard và WebApp vẫn là file lớn, coupling cao.
- Apps Script Web App dùng mô hình `ANYONE_ANONYMOUS` cho frontend tĩnh.
- Planner Sync Server phụ thuộc máy cục bộ và phiên Microsoft.
- Google Sheets phụ thuộc chặt vào tên header và trạng thái chuỗi.
- Chưa triển khai outbox/worker architecture.
- Chưa UUID hóa toàn bộ bản ghi.
- Chưa chuẩn hóa toàn bộ status theo enum/schema tập trung.
- Trạng thái deploy có thể lệch với branch nếu không cập nhật runbook.

## 4. Vấn đề mở cần người quản trị cập nhật

| ID | Vấn đề | Ảnh hưởng | Người quyết định | Hạn/Trạng thái |
|---|---|---|---|---|
| OPEN-001 | Commit/version production hiện tại chưa được ghi nhận trong repo | Khó xác định code đang chạy | Người quản trị hệ thống | Mở |
| OPEN-002 | Cần xác nhận chiến lược lưu và dọn `WEBAPP_DEBUG_LOG` | Hiệu năng và truy vết | Pháp chế/IT | Mở |
| OPEN-003 | Cần rà soát các log lịch sử từng được Git track | Bảo mật và repository hygiene | Người quản trị repo | Mở |
| OPEN-004 | Cần xác định source of truth cho từng trường khi Planner và Sheet mâu thuẫn | Sai lệch đồng bộ | Chủ hệ thống | Mở |
| OPEN-005 | Cần xác định lộ trình tách nhỏ Dashboard/WebApp | Khả năng bảo trì | Chủ hệ thống/IT | Mở |

## 5. Mẫu ghi quyết định mới

```markdown
### ADR-XXX — Tên quyết định

- Ngày:
- Trạng thái: Đề xuất / Đã phê duyệt / Thay thế / Hủy bỏ
- Bối cảnh:
- Quyết định:
- Phương án đã xem xét:
- Lý do:
- Ảnh hưởng code:
- Ảnh hưởng dữ liệu:
- Ảnh hưởng bảo mật:
- Triển khai/migration:
- Rollback:
- Người xác nhận:
```

## 6. Mẫu ghi vấn đề mở

```markdown
### OPEN-XXX — Tên vấn đề

- Hiện trạng:
- Bằng chứng:
- Ảnh hưởng:
- Các phương án:
- Dữ liệu còn thiếu:
- Người quyết định:
- Thời hạn:
- Kết quả cuối cùng:
```

## 7. Quy tắc cập nhật

- Không ghi secret, dữ liệu cá nhân hoặc thông tin máy nội bộ nhạy cảm.
- Khi quyết định thay thế quyết định cũ, không xóa lịch sử; đánh dấu trạng thái và liên kết ADR mới.
- Mọi quyết định làm thay đổi ranh giới bảo mật phải cập nhật `SECURITY.md`, test và tài liệu kiến trúc.
- Mọi quyết định đổi data contract phải cập nhật migration và `03_BUSINESS_RULES_AND_DATA_CONTRACT.md`.
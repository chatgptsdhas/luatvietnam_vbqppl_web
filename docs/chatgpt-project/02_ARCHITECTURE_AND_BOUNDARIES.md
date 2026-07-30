# Architecture and Boundaries

## 1. Kiến trúc tổng thể

```text
LuatVietnam / nguồn dữ liệu
        |
        v
Python pipeline
        |
        | HTTPS JSON + project token + service token
        v
Google Apps Script Web App
        |
        +--> Google Sheets
        |    - VBQPPL_Nhap
        |    - VBQPPL
        |    - WEBAPP_DEBUG_LOG
        |
        +<-- Dashboard HTML/JavaScript trên Vercel
        |
        | signed envelope HMAC
        v
Planner Sync Server cục bộ (127.0.0.1:8765)
        |
        v
Microsoft Graph / Microsoft Planner
```

## 2. Vai trò từng thành phần

### Python pipeline

Thu thập, chuẩn hóa, kiểm tra sơ bộ và gửi dữ liệu vào Apps Script; đồng bộ hai chiều với Planner; tạo báo cáo và cảnh báo.

### Google Apps Script Web App

API và lớp nghiệp vụ trung tâm. Thành phần này kiểm tra quyền, định tuyến action, đọc/ghi Sheet, tạo signed envelope và chuẩn hóa response.

### Google Sheets

Kho dữ liệu nghiệp vụ. Cấu trúc phụ thuộc mạnh vào tên sheet, header và trạng thái.

### Dashboard

Giao diện đọc, rà soát và thực hiện thao tác quản trị. Dashboard không phải biên bảo mật; backend phải xác minh mọi quyền ghi dữ liệu.

### Planner Sync Server

Cầu nối cục bộ tới Microsoft Planner. Server chỉ nên bind localhost, xác minh HMAC và chống replay trước khi chạy logic sync/delete.

### Microsoft Graph / Planner

Hệ thống quản lý nhiệm vụ. Credential và session Microsoft chỉ được giữ ở môi trường vận hành được kiểm soát.

## 3. Phân loại action Apps Script

- **A — Public read**: chỉ đọc; yêu cầu project token.
- **B — Service**: máy–máy; yêu cầu service token riêng, không fallback về project token.
- **C — Admin/write**: thay đổi dữ liệu từ Dashboard; yêu cầu admin session được backend xác minh.

Khi thêm action mới, phải phân loại trước khi merge và bổ sung test chứng minh không thể gọi bằng quyền thấp hơn.

## 4. Ranh giới bắt buộc

Không được tự ý:

1. Đưa password, service token, shared secret, Microsoft token hoặc session vào frontend.
2. Dùng project token công khai làm quyền admin hoặc service.
3. Dựa vào việc ẩn nút hoặc cờ `localStorage` để cấp quyền.
4. Bỏ `requireAdminSession_` cho action ghi dữ liệu.
5. Bỏ `APPS_SCRIPT_SERVICE_TOKEN` cho action máy–máy.
6. Bỏ HMAC, TTL hoặc replay protection của Planner Sync Server.
7. Mở cổng Planner Sync Server ra Internet khi chưa có thiết kế bảo mật mới được phê duyệt.
8. Trả stack trace, đường dẫn file, biến môi trường hoặc secret cho client.
9. Ghi token/session/signature vào log.
10. Đổi tên sheet, header, trạng thái hoặc khóa liên kết mà không có migration.
11. Coi code đã merge là code đã deploy.
12. Sửa production trực tiếp mà không đồng bộ lại GitHub.

## 5. Luồng tạo Planner Task

1. Người dùng thực hiện thao tác từ Dashboard.
2. Dashboard gửi action cần quyền admin tới Apps Script.
3. Apps Script xác minh admin session.
4. Apps Script lọc payload theo schema whitelist và tạo signed envelope.
5. Dashboard chuyển tiếp envelope tới Planner Sync Server cục bộ.
6. Server kiểm tra Origin nếu có, Content-Type, body size, timestamp, request ID và chữ ký HMAC.
7. Server gọi module đồng bộ.
8. Module kiểm tra điều kiện idempotency trước khi tạo task.
9. Kết quả được ghi ngược về Sheet.

## 6. Luồng import văn bản

1. Pipeline lấy và chuẩn hóa dữ liệu.
2. Pipeline gửi `import_vbqppl_nhap` kèm project token và service token.
3. Apps Script kiểm tra nhóm B.
4. Dữ liệu được đối chiếu và ghi vào `VBQPPL_Nhap`.
5. Người có quyền kiểm tra và quyết định chuyển hoặc cập nhật bản ghi.

## 7. Giới hạn kiến trúc hiện tại

- Dashboard là trang tĩnh gọi Apps Script Web App ở chế độ công khai; project token trong frontend không phải secret.
- Planner Sync Server phụ thuộc máy Windows cục bộ và Scheduled Task.
- Apps Script và Dashboard còn là các file lớn, có mức độ coupling cao.
- Google Sheets là datastore nghiệp vụ nên thay đổi schema có rủi ro hồi quy lớn.
- Production deployment không được suy ra chỉ từ branch `main`.

## 8. Khi đề xuất thay đổi kiến trúc

Phải nêu:

- vấn đề hiện tại;
- phạm vi thành phần bị ảnh hưởng;
- data migration;
- thay đổi xác thực/phân quyền;
- khả năng tương thích ngược;
- test;
- cách triển khai theo giai đoạn;
- rollback;
- quyết định cần người có thẩm quyền phê duyệt.
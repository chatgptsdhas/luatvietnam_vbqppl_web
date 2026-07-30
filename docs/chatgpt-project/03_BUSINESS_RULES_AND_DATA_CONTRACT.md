# Business Rules and Data Contract

## 1. Mục đích

Tài liệu này mô tả các quy tắc nghiệp vụ và hợp đồng dữ liệu mà mọi thay đổi code phải tôn trọng. Khi code và tài liệu mâu thuẫn, phải kiểm tra trạng thái repo hiện tại và cập nhật lại tài liệu trong cùng thay đổi.

## 2. Sheet chính

### `VBQPPL_Nhap`

Vùng tiếp nhận và rà soát dữ liệu trước khi chuyển sang danh mục chính thức.

### `VBQPPL`

Danh mục văn bản chính thức trong hệ thống H.A.S và là nguồn để đồng bộ thông tin Planner.

### `WEBAPP_DEBUG_LOG`

Nhật ký kỹ thuật để truy vết request. Log không phải dữ liệu nghiệp vụ chính thức và không được chứa secret.

## 3. Định danh và khóa liên kết

Các trường thường dùng để định danh/liên kết:

- `_rowNumber`: số dòng vật lý phục vụ cập nhật đúng bản ghi.
- `ID VĂN BẢN`: định danh nghiệp vụ nếu đã được cấp.
- `Số hiệu`: định danh pháp lý dễ đọc nhưng không được giả định luôn duy nhất trong mọi tình huống.
- `Planner Task ID`: khóa liên kết với Microsoft Planner.

Không thay một loại khóa bằng loại khác nếu chưa rà soát toàn bộ Python, Apps Script, Dashboard và dữ liệu cũ.

## 4. Trường bắt buộc khi chuyển văn bản

Theo cấu hình hiện tại, tối thiểu gồm:

- `Lĩnh vực`
- `Mức độ tác động`
- `Loại văn bản`
- `Tên văn bản`
- `Số hiệu`
- `Link Văn bản`
- `Bộ phận chủ trì`

Khi thay đổi danh sách này phải cập nhật validation, UI, test và tài liệu.

## 5. Cột được bảo vệ thủ công

Các cột hiện được coi là dữ liệu cần kiểm soát khi cập nhật tự động:

- `ID VĂN BẢN`
- `Lĩnh vực`
- `Chủ đề`
- `Mục`
- `Mức độ tác động`
- `Bộ phận chủ trì`
- `Trạng thái duyệt`

Pipeline hoặc luồng đồng bộ không được ghi đè các cột này ngoài đúng use case đã được xác nhận.

## 6. Trạng thái quan trọng

Các giá trị hiện được code sử dụng gồm:

- `Chờ kiểm tra`
- `Không liên quan`
- `Đã tạo task Planner`
- `Đã xóa task Planner`
- trạng thái có nội dung `Đã chuyển`
- trạng thái có nội dung `Đã kiểm tra`

Không tự thêm biến thể chữ hoa/thường, dấu cách hoặc từ đồng nghĩa. Nếu chuẩn hóa trạng thái, phải có mapping và migration dữ liệu lịch sử.

## 7. Quy tắc tạo Planner Task

Một bản ghi chỉ đủ điều kiện tạo task khi tối thiểu:

1. Có `_rowNumber`.
2. Có `Số hiệu`.
3. Có `Tên văn bản`.
4. Chưa có `Planner Task ID`.
5. `Planner Sync Status` chưa là `Đã tạo task Planner`.
6. Ngày bản ghi không trước `PLANNER_CREATE_FROM_DATE`, nếu bộ lọc này được cấu hình.
7. Bản ghi đã chuyển hoặc đã kiểm tra theo logic nghiệp vụ hiện hành.

Việc retry phải idempotent: không tạo thêm task nếu lần trước đã thành công nhưng response bị gián đoạn.

## 8. Quy tắc ngày tháng

Định dạng ưu tiên:

- `dd/MM/yyyy`
- `dd/MM/yyyy HH:mm:ss`

Code có thể đọc thêm ISO 8601 hoặc `yyyy-MM-dd` khi được hỗ trợ rõ ràng. Không đổi định dạng ghi ra nếu chưa đánh giá các công thức, filter và giao diện đang phụ thuộc.

Các trường ngày đang được thử để xác định thời điểm bản ghi gồm:

- `Ngày chuyển trạng thái`
- `Ngày Python quét`
- `Planner Last Sync`

## 9. Hợp đồng request Apps Script

Request JSON điển hình:

```json
{
  "token": "<project-token>",
  "service_token": "<service-token-if-required>",
  "admin_session": "<admin-session-if-required>",
  "action": "<action-name>",
  "payload": {}
}
```

Quy tắc:

- Nhóm A: cần project token.
- Nhóm B: cần project token và service token.
- Nhóm C: cần project token và admin session.
- Không dùng token của nhóm này để thay thế token/session của nhóm khác.

## 10. Hợp đồng response

Response nên là JSON object, tối thiểu có:

- `ok`: boolean;
- `data` hoặc `result` khi thành công;
- `error`/`message` khi thất bại;
- `correlationId` để truy vết khi có thể.

HTTP 2xx không đồng nghĩa nghiệp vụ thành công. Client phải kiểm tra `ok`.

## 11. Signed envelope Planner

Chỉ các path được whitelist mới được ký. Payload phải được lọc theo schema, không ký tùy ý.

Các path hiện hành:

- `/sync-webapp-to-planner`
- `/delete-planner-task`

Frontend chỉ chuyển tiếp envelope; không biết và không tự sử dụng shared secret.

## 12. Logging

- Mỗi request cần correlation ID.
- Redact password, token, secret, session, cookie, authorization, signature, access token và refresh token.
- Giới hạn kích thước log.
- Lỗi ghi log không được làm hỏng nghiệp vụ.
- Không dùng log để khôi phục trạng thái nghiệp vụ nếu chưa kiểm tra nguồn dữ liệu chính.

## 13. Checklist khi sửa data contract

- [ ] Xác định tất cả file đọc/ghi trường bị thay đổi.
- [ ] Kiểm tra dữ liệu hiện hữu và giá trị ngoại lệ.
- [ ] Chuẩn bị mapping/migration.
- [ ] Cập nhật validation backend.
- [ ] Cập nhật Dashboard.
- [ ] Cập nhật Python pipeline và sync.
- [ ] Cập nhật test.
- [ ] Cập nhật tài liệu này.
- [ ] Có rollback và bản sao dữ liệu trước migration.
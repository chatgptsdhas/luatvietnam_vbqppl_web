# Repository Map and Change Guide

## 1. Mục đích

Tài liệu này giúp ChatGPT và người phát triển xác định đúng file cần đọc trước khi kết luận hoặc sửa code.

## 2. Bản đồ thành phần

| Thành phần | File/thư mục chính | Vai trò |
|---|---|---|
| Xử lý văn bản theo lô | `08_process_field_documents_batch.py` | Chuẩn hóa, kiểm tra và gửi dữ liệu vào Apps Script |
| Kiểm tra kết quả | `09_validate_pipeline_result.py` | Validate đầu ra pipeline |
| Tạo task từ bản ghi | `10_create_planner_task_from_webapp.py` | Chuyển record thành Planner Task |
| Web App → Planner | `11_sync_webapp_to_planner.py` | Đọc Sheet qua API, lọc điều kiện và tạo/xóa task |
| Planner → Web App | `12_sync_planner_to_webapp.py` | Ghi trạng thái Planner ngược về hệ thống |
| Báo cáo Planner | `13_generate_planner_reports.py` | Tổng hợp báo cáo |
| Escalation | `14_notify_planner_escalation.py` | Cảnh báo nhiệm vụ |
| Planner client | `ms_planner.py` | Gọi Microsoft Graph và xử lý dữ liệu Planner |
| Xác thực Microsoft | `get_token_browser.py`, `graph_auth.py`, `ms_auth_init.py` | Lấy và quản lý phiên/token Microsoft |
| API Apps Script | `apps_script/WebApp.js` | Định tuyến action và nghiệp vụ Sheet |
| Bảo mật Apps Script | `apps_script/Security.js` | Service token, PBKDF2, admin session, HMAC envelope |
| Cấu hình Apps Script | `apps_script/appsscript.json` | Runtime và deployment settings |
| Dashboard | `Dashboard/index.html` | Giao diện web quản trị |
| Local sync server | `planner_sync_server.py` | HTTP server cục bộ gọi module sync |
| HMAC/replay | `planner_sync_security.py` | Xác minh request Planner server |
| Scheduled Task | `install_planner_sync_task.ps1` | Cài task Windows |
| Khởi động server | `run_planner_sync_server*.ps1/.bat/.vbs` | Chạy server nền |
| Health check | `check_planner_sync_health.ps1` | Kiểm tra server |
| CI bảo mật | `.github/workflows/security.yml` | Compile, syntax, unit test, secret scan |
| Unit/security tests | `tests/` | Test hành vi và ranh giới bảo mật |
| Tài liệu bảo mật | `SECURITY.md` | Quy tắc bảo mật và xử lý sự cố |
| Hành động thủ công | `P0_MANUAL_ACTIONS.md` | Deploy/configuration P0 |

## 3. Trình tự đọc theo loại yêu cầu

### Lỗi import văn bản

Đọc theo thứ tự:

1. `08_process_field_documents_batch.py`
2. `config/scan_config.json`
3. `apps_script/WebApp.js`
4. `apps_script/Security.js`
5. log có correlation ID hoặc output runtime được người dùng cung cấp

### Lỗi tạo Planner Task

1. `Dashboard/index.html` nếu thao tác bắt đầu từ UI
2. `apps_script/WebApp.js`
3. `apps_script/Security.js`
4. `planner_sync_server.py`
5. `planner_sync_security.py`
6. `11_sync_webapp_to_planner.py`
7. `10_create_planner_task_from_webapp.py`
8. `ms_planner.py`

### Lỗi đồng bộ ngược

1. `12_sync_planner_to_webapp.py`
2. `ms_planner.py`
3. `apps_script/WebApp.js`
4. dữ liệu thực tế của `Planner Task ID` và trạng thái liên quan

### Lỗi đăng nhập/quyền

1. `Dashboard/index.html`
2. `apps_script/WebApp.js`
3. `apps_script/Security.js`
4. `SECURITY.md`
5. test security boundary

### Lỗi server cục bộ

1. `planner_sync_server.py`
2. `planner_sync_security.py`
3. `.env.example`
4. script cài/chạy Scheduled Task
5. health check và log runtime

## 4. Quy tắc phân tích thay đổi

Trước khi đề xuất sửa:

1. Xác định branch/commit đang kiểm tra.
2. Tìm entrypoint thực tế.
3. Truy vết call chain đến nơi ghi dữ liệu hoặc gọi dịch vụ ngoài.
4. Xác định data contract và điều kiện quyền.
5. Phân biệt nguyên nhân gốc với triệu chứng.
6. Kiểm tra test hiện có.
7. Xác định deploy/migration cần thiết.

## 5. Ma trận ảnh hưởng thường gặp

| Thay đổi | Phải kiểm tra thêm |
|---|---|
| Tên cột hoặc trạng thái Sheet | Apps Script, Dashboard, Python sync, dữ liệu cũ, báo cáo |
| Action Apps Script | Security group, client gọi action, test boundary |
| Payload Planner | Envelope schema, Dashboard, local server, sync module |
| Token/secret | Script Properties, `.env`, deployment, restart server |
| Logic tạo task | Idempotency, Planner Task ID, retry, sync ngược |
| Dashboard | Backend authorization, browser storage, CORS/HMAC |
| Scheduled Task | quyền user, working directory, pythonw, log, health |

## 6. Nội dung phải có trong một đề xuất sửa code

- Kết luận ngắn.
- Hiện trạng có dẫn chứng file/hàm.
- Nguyên nhân gốc.
- Phạm vi file và dữ liệu ảnh hưởng.
- Patch hoặc yêu cầu chỉnh sửa cụ thể.
- Test cần chạy.
- Deploy/migration.
- Rollback.

## 7. Không được làm

- Không chỉ sửa nơi phát sinh lỗi UI mà bỏ qua backend.
- Không thêm fallback token để chữa lỗi cấu hình.
- Không bắt exception rồi coi là thành công.
- Không đổi status bằng chuỗi mới mà không kiểm tra dữ liệu cũ.
- Không tạo task trước rồi bỏ qua bước ghi lại `Planner Task ID`.
- Không khẳng định production đã nhận thay đổi chỉ vì PR đã merge.
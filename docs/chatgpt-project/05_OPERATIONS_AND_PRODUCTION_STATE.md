# Operations and Production State

## 1. Mục đích

Tài liệu này vừa là runbook tối thiểu, vừa là nơi ghi nhận trạng thái production đã được người quản trị xác nhận. Không được tự động coi các giá trị mẫu bên dưới là trạng thái thực tế.

## 2. Trạng thái production cần cập nhật

> Người quản trị phải cập nhật phần này sau mỗi lần deploy quan trọng.

- Ngày xác nhận: `CHƯA XÁC NHẬN`
- Repository: `chatgptsdhas/luatvietnam_vbqppl_web`
- Production branch: `main`
- Commit đang chạy: `CHƯA XÁC NHẬN`
- Apps Script deployment ID/version: `CHƯA XÁC NHẬN`
- Dashboard production URL: `https://tracuuphaply.vercel.app`
- Dashboard commit đang deploy: `CHƯA XÁC NHẬN`
- Máy chạy Planner Sync Server: `KHÔNG GHI THÔNG TIN NHẠY CẢM TRONG GIT`
- Scheduled Task: `HAS_Planner_Sync_Server`
- Health check gần nhất: `CHƯA XÁC NHẬN`
- P0 Script Properties audit: `CHƯA XÁC NHẬN`
- Microsoft Graph session: `CHỈ GHI TRẠNG THÁI, KHÔNG GHI TOKEN/SESSION`

## 3. Cấu hình bắt buộc

### Python và Planner Sync Server (`.env` cục bộ)

- `APPS_SCRIPT_WEBAPP_URL`
- `APPS_SCRIPT_TOKEN`
- `APPS_SCRIPT_SERVICE_TOKEN`
- `PLANNER_SYNC_SHARED_SECRET`
- `PLANNER_SYNC_ALLOWED_ORIGINS`
- `PLANNER_SYNC_REQUEST_TTL_SECONDS`
- `PLANNER_SYNC_MAX_BODY_BYTES`
- các ID Planner và cấu hình Microsoft cần thiết

Không ghi giá trị thật vào Git, ChatGPT Project, tài liệu hoặc log.

### Apps Script Properties

- `APPS_SCRIPT_TOKEN`
- `APPS_SCRIPT_SERVICE_TOKEN`
- `ADMIN_PASSWORD_SALT`
- `ADMIN_PASSWORD_HASH`
- `ADMIN_PASSWORD_ITERATIONS`
- `ADMIN_SESSION_SECRET`
- `ADMIN_SESSION_TTL_SECONDS`
- `PLANNER_SYNC_SHARED_SECRET`
- `PLANNER_SYNC_REQUEST_TTL_SECONDS`
- `WEBAPP_LOG_VERBOSE_DEBUG`

Trước deploy phải chạy thủ công:

1. `installP0ScriptPropertyDefaults()` nếu cần.
2. Nhập các secret bắt buộc.
3. `auditP0ScriptProperties()`.
4. Chỉ tiếp tục khi audit báo hợp lệ.

## 4. Deploy Apps Script

1. Kiểm tra branch và commit dự kiến deploy.
2. Chạy test/CI.
3. Từ thư mục `apps_script/`, chạy `clasp push`.
4. Xác nhận `WebApp.js`, `Security.js` và manifest được đồng bộ.
5. Tạo New version trong deployment hiện tại để giữ Web App URL nếu phù hợp.
6. Chạy smoke test đọc dữ liệu, đăng nhập admin, cập nhật và chuyển bản ghi.
7. Cập nhật commit/version trong mục trạng thái production.

## 5. Deploy Dashboard

1. Xác nhận Web App URL và public project token phù hợp.
2. Deploy theo quy trình Vercel đang áp dụng.
3. Kiểm tra các trang đọc dữ liệu.
4. Kiểm tra đăng nhập/đăng xuất admin.
5. Kiểm tra response `ADMIN_SESSION_REQUIRED` khi session hết hạn.
6. Kiểm tra luồng tạo/xóa Planner Task trên máy có local server.
7. Ghi nhận commit đã deploy.

## 6. Planner Sync Server

Mặc định:

- Host: `127.0.0.1`
- Port: `8765`
- Health endpoint: `http://127.0.0.1:8765/health`

Sau khi đổi code hoặc `.env`, phải restart tiến trình/Scheduled Task để nạp lại cấu hình.

Kiểm tra:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
Get-ScheduledTask -TaskName 'HAS_Planner_Sync_Server' | Get-ScheduledTaskInfo
Get-Process pythonw -ErrorAction SilentlyContinue
```

Không expose cổng 8765 ra Internet.

## 7. Smoke test tối thiểu

- [ ] `get_pending_records` đọc được dữ liệu.
- [ ] Public token không gọi được action service/admin.
- [ ] Admin đăng nhập và nhận session hợp lệ.
- [ ] Request ghi thiếu admin session bị từ chối.
- [ ] Python service action thiếu/sai service token bị từ chối.
- [ ] Chuyển một bản ghi thử nghiệm thành công.
- [ ] Không tạo trùng Planner Task.
- [ ] Planner Task ID được ghi ngược.
- [ ] Local server từ chối signature sai/replay.
- [ ] Response lỗi có correlation ID và không lộ stack trace.
- [ ] Log không chứa secret.

## 8. Monitoring

Theo dõi tối thiểu:

- GitHub Actions;
- Apps Script executions;
- `WEBAPP_DEBUG_LOG` theo correlation ID;
- Planner Sync Server log;
- health endpoint;
- LastTaskResult của Scheduled Task;
- bản ghi thiếu `Planner Task ID` nhưng đã báo tạo task;
- lỗi service token, admin session, HMAC hoặc replay;
- thời hạn phiên Microsoft.

## 9. Rollback

Rollback phải xác định riêng cho:

- Git commit;
- Apps Script deployment version;
- Vercel deployment;
- `.env`/Script Properties;
- migration dữ liệu;
- Scheduled Task/server process.

Không rollback code nếu dữ liệu đã migration mà chưa có phương án tương thích ngược.

## 10. Xử lý sự cố bảo mật

Tuân thủ `SECURITY.md`:

1. Ngừng dùng credential nghi bị lộ.
2. Xác định phạm vi.
3. Rotate đúng nơi cấu hình.
4. Restart thành phần đọc secret lúc khởi động.
5. Không chỉ xóa log/commit và tiếp tục dùng credential cũ.
6. Ghi nhận sự cố nhưng không ghi secret thật.
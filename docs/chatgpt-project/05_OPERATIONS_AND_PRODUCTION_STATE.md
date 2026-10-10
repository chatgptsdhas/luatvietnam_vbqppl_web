# Operations and Production State

## 1. Mục đích

Tài liệu này vừa là runbook tối thiểu, vừa là nơi ghi nhận trạng thái production đã được người quản trị xác nhận. Không được tự động coi các giá trị mẫu bên dưới là trạng thái thực tế.

## 2. Trạng thái production cần cập nhật

> Người quản trị phải cập nhật phần này sau mỗi lần deploy quan trọng.

- Ngày xác nhận: `10/10/2026`
- Repository: `chatgptsdhas/luatvietnam_vbqppl_web`
- Production branch: `main`
- Apps Script code đang deploy: `1554ff2abd375706ac9e5aa7a1eb028783f0961a`
- Apps Script không thay đổi trong PR `#10` và không deploy lại cho release này.
- Apps Script deployment ID/version: deployment đã được cập nhật sau `clasp push` ngày `09/10/2026`; số deployment version chưa được ghi nhận.
- Dashboard production URL: `https://tracuuphaply.vercel.app`
- Dashboard commit đang deploy: `13c957c4255520bc162fa2977cc6b8f534f17f96`
- Local repository `main` trên máy vận hành đã được cập nhật tới: `13c957c4255520bc162fa2977cc6b8f534f17f96`
- Máy chạy Planner Sync Server: `KHÔNG GHI THÔNG TIN NHẠY CẢM TRONG GIT`
- Scheduled Task: `HAS_Planner_Sync_Server`
- Health check gần nhất: `CHƯA XÁC NHẬN`
- P0 Script Properties audit: `CHƯA XÁC NHẬN`
- Microsoft Graph session: `CHỈ GHI TRẠNG THÁI, KHÔNG GHI TOKEN/SESSION`

### Xác nhận hotfix Planner UTF-8 HMAC

- PR: `#9` — `fix: support UTF-8 Planner envelope hashing`.
- Hotfix commit: `44e6214c37dac7ce65b302a173036303ec8a7c1a`; merge commit trên `main`: `1554ff2abd375706ac9e5aa7a1eb028783f0961a`.
- Smoke test ASCII: **PASS** — row `189`, `14/2026/TT-BNV`, `dry_run: true`, HTTP `200`, `Planner sync completed.`, `summary.ok: true`.
- Smoke test Unicode HMAC: **PASS** — envelope `288/2026/NĐ-CP` trả HTTP `200`, không còn `SIGNATURE_INVALID`. `summary.ok: false` chỉ vì không có bản ghi tương ứng trong VBQPPL, không phải lỗi HMAC.
- Smoke test Unicode body với bản ghi thật: **PASS** — source `dashboard-kiểm-thử-UTF8`, row `189`, `14/2026/TT-BNV`, `dry_run: true`, HTTP `200`, `summary.ok: true`.
- Live candidate check: `PENDING_TOTAL: 199`, `MISSING_REQUIRED: 22`, `DUPLICATE_IN_VBQPPL: 178`, `READY_FOR_TRANSFER: 0`.
- Live E2E chưa chạy vì không có record tự nhiên đủ điều kiện (`READY_FOR_TRANSFER = 0`). Đây không phải failure; kiểm thử được defer tới lần chuyển văn bản đủ điều kiện tiếp theo. Không tạo dữ liệu giả trên Production.

### Xác nhận release trạng thái Planner task đã xóa

- PR: `#10` — `fix: handle deleted Planner task state`.
- Feature commit: `02eb3e54f1487e04487da479ef513cb96d17e0b9`.
- Merge commit trên `main`: `13c957c4255520bc162fa2977cc6b8f534f17f96`.
- GitHub Security Checks: **PASS**.
- Python regression tests: `74 passed, 49 subtests passed`.
- Node/static suites trước merge: `27/27 PASS`; `20/20 PASS`.
- `git diff --check`: **PASS**.

Khi Microsoft Graph trả `404` cho Planner task, release cập nhật `Planner Sync Status = Đã xóa task Planner`, cập nhật `Planner Last Sync`, và clear `Current PIC`, `Current Checkpoint`, `Next Response Due`.

Với record lịch sử đã có `Planner Sync Status = Đã xóa task Planner` nhưng còn workflow stale, self-heal không gọi Microsoft Graph. Self-heal giữ `Planner Task ID`, `Planner Plan ID`, `Planner Bucket ID`, `Planner Bucket Name`, `Planner Task URL`, `Planner Last Sync`, và chỉ clear ba workflow fields hiện hành.

Dashboard không coi deleted Planner task là active: không tạo link tới task đã xóa, không hiển thị PIC/checkpoint/hạn cũ, restore không yêu cầu hoặc gọi xóa lại task đã biết là deleted, và workload/overdue không tính task deleted.

#### Production self-heal

Đã xử lý có kiểm soát:

- Row `176` — Số hiệu `38/2026/TT-BGDĐT`; Planner Task ID `SeuF5plrN0m_5B0T9_zMOckAFJAG`; Planner Last Sync giữ nguyên `2026-06-11T02:06:03.000Z`.
- Row `186` — Số hiệu `360/2026/NĐ-CP`; Planner Task ID `TNTgs6ILAkOoRuNSn2_QXckAEEs-`; Planner Last Sync giữ nguyên `2026-10-09T08:12:39.000Z`.

Sau self-heal, cả hai row có `Current PIC = ""`, `Current Checkpoint = ""`, `Next Response Due = ""`.

Trong lúc cleanup row `186`, client Python nhận response không phải JSON sau khi request đã được xử lý. Đọc lại dữ liệu sau đó xác nhận row đã cập nhật thành công; không thực hiện write lại.

#### Post-cleanup verification

Dry-run cuối sau self-heal:

- `ok = true`
- `dry_run = true`
- `total_records = 189`
- `records_to_process = 12`
- `skipped_records = 177`
- `deleted_cleanup_candidates = 0`
- `deleted_cleanup_to_process = 0`
- `deleted_cleanup_updated = 0`
- `deleted_cleanup_failed = 0`
- `updated_records = 0`
- `failed_records = 0`

Kết luận: self-heal đã idempotent; không còn deleted record cần cleanup tại thời điểm kiểm tra.

#### Dashboard Production deploy

- Vercel deployment cho merge commit `13c957c4255520bc162fa2977cc6b8f534f17f96` có status **SUCCESS**.
- Production URL: `https://tracuuphaply.vercel.app`.
- Smoke verification: HTTP status `200`; production HTML có `function isDeletedPlannerTaskStatus(status)`.

Xác nhận production alias đã nhận Dashboard của PR `#10`.

#### Deployment impact

- Apps Script deploy: **KHÔNG CẦN** cho release `#10`.
- `planner_sync_server.py` restart: **KHÔNG CẦN** cho release `#10`.
- Dashboard đã được Vercel deploy thành công qua Git integration.

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

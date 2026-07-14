# MANUAL ACTION REQUIRED — BẮT BUỘC NGƯỜI QUẢN TRỊ THỰC HIỆN

P0 security hardening đã sửa code trên nhánh `security/p0-hardening` nhưng **chưa deploy, chưa
tạo secret thật, chưa commit**. Hệ thống sẽ **không hoạt động đúng** (đăng nhập admin, chuyển văn
bản, đồng bộ Planner) cho tới khi hoàn tất các bước dưới đây, **theo đúng thứ tự**.

Không ghi giá trị secret thật vào file này, vào Git, chat, email, Word hay Excel — chỉ dán vào
`.env` cục bộ, Script Properties của Apps Script, hoặc password manager.

---

## 1. Chạy `scripts/generate_p0_secrets.py`

```
python scripts/generate_p0_secrets.py
```

Script sẽ hỏi mật khẩu admin mới (nhập 2 lần để xác nhận) rồi in ra 5 giá trị:
`APPS_SCRIPT_SERVICE_TOKEN`, `PLANNER_SYNC_SHARED_SECRET`, `ADMIN_SESSION_SECRET`,
`ADMIN_PASSWORD_SALT`, `ADMIN_PASSWORD_HASH`. Chạy trong terminal cục bộ, không chia sẻ output.

## 2. Giá trị nào phải lưu trong password manager

Lưu cả 5 giá trị ở bước 1, **cộng thêm** mật khẩu admin plaintext bạn vừa nhập (script không lưu
lại mật khẩu plaintext — nếu quên, phải chạy lại script để tạo mật khẩu/hash mới).

## 3. Biến nào phải điền vào `.env`

Trong `.env` (file cục bộ, không commit — nếu chưa có, copy từ `.env.example`) — dùng CHUNG cho
cả pipeline Python (`08_*.py`, `11_*.py`, `12_*.py`) và `planner_sync_server.py` nếu chạy trên
cùng máy, hoặc điền đúng phần liên quan nếu chạy trên máy khác nhau:

```
APPS_SCRIPT_SERVICE_TOKEN=<giá trị bước 1>
PLANNER_SYNC_SHARED_SECRET=<giá trị bước 1>
PLANNER_SYNC_ALLOWED_ORIGINS=https://tracuuphaply.vercel.app,http://localhost:5500,http://127.0.0.1:5500
PLANNER_SYNC_REQUEST_TTL_SECONDS=300
PLANNER_SYNC_MAX_BODY_BYTES=1048576
```

**QUAN TRỌNG (khác với bản trước):** `APPS_SCRIPT_SERVICE_TOKEN` giờ **bắt buộc** phải có trong
`.env` của máy chạy `08_process_field_documents_batch.py`, `11_sync_webapp_to_planner.py`,
`12_sync_planner_to_webapp.py` — không còn fallback về `APPS_SCRIPT_TOKEN` nữa, thiếu biến này
các script sẽ dừng ngay hoặc bị Apps Script từ chối `SERVICE_TOKEN_INVALID`. `ADMIN_*` vẫn KHÔNG
cần trong bất kỳ `.env` nào — chỉ cần trong Script Properties của Apps Script (bước 4).

## 4. Script Properties nào phải tạo (Apps Script Editor → Project Settings → Script Properties)

| Key | Giá trị |
|---|---|
| `APPS_SCRIPT_TOKEN` | Token dự án hiện có (giữ nguyên nếu chưa muốn đổi — xem `SECURITY.md` mục 5.1 nếu muốn rotate) |
| `APPS_SCRIPT_SERVICE_TOKEN` | Giá trị sinh ở bước 1 |
| `ADMIN_PASSWORD_SALT` | Giá trị sinh ở bước 1 |
| `ADMIN_PASSWORD_HASH` | Giá trị sinh ở bước 1 |
| `ADMIN_PASSWORD_ITERATIONS` | `210000` (hoặc số bạn chọn khi chạy script với `--iterations`) |
| `ADMIN_SESSION_SECRET` | Giá trị sinh ở bước 1 |
| `ADMIN_SESSION_TTL_SECONDS` | `900` (tùy chọn, mặc định 900 nếu bỏ trống) |
| `PLANNER_SYNC_SHARED_SECRET` | **Giống hệt** giá trị đã điền vào `.env` ở bước 3 |
| `PLANNER_SYNC_REQUEST_TTL_SECONDS` | `300` (tùy chọn) |

Có thể set qua code: `setupWebAppToken('<token>')` chạy 1 lần trong Apps Script Editor cho
`APPS_SCRIPT_TOKEN`; các Script Property còn lại set thủ công qua giao diện Script Properties
(chưa có hàm setup riêng cho các key này — set trực tiếp trên UI).

## 5. Secret nào phải giống nhau giữa Apps Script và `.env`

**Hai** giá trị phải giống hệt nhau giữa Script Property (bước 4) và `.env` tương ứng (bước 3):

- `PLANNER_SYNC_SHARED_SECRET` — giữa Apps Script và `.env` của máy chạy `planner_sync_server.py`.
  Nếu lệch: mọi request tạo/xóa Planner task bị từ chối 401 `SIGNATURE_INVALID`.
- `APPS_SCRIPT_SERVICE_TOKEN` — giữa Apps Script và `.env` của máy chạy `08_*.py`/`11_*.py`/
  `12_*.py`. Nếu lệch (hoặc thiếu ở phía script): `import_vbqppl_nhap`/`update_vbqppl_record` bị
  từ chối 401 `SERVICE_TOKEN_INVALID` — **không còn** fallback về `APPS_SCRIPT_TOKEN` để "chữa
  cháy" tạm thời như bản trước.

## 6. Cách đồng bộ source Apps Script

Từ thư mục `apps_script/` (cần đã cài `clasp` và đăng nhập `clasp login`):

```
cd apps_script
clasp push
```

Xác nhận `Security.js` có trong danh sách file được push (không bị `.claspignore` loại trừ — đã
kiểm tra, không bị loại).

## 7. Cách tạo New version và cập nhật deployment

Trong Apps Script Editor: **Deploy → Manage deployments** → chọn deployment Web App hiện tại →
biểu tượng bút chì (Edit) → **Version: New version** → mô tả ngắn (ví dụ "P0 security hardening")
→ **Deploy**. Không tạo deployment ID mới nếu muốn giữ nguyên URL `WEBAPP_URL` đang dùng trong
`Dashboard/index.html`.

## 8. Cách deploy frontend Vercel

Deploy `Dashboard/index.html` (và các asset liên quan) lên project Vercel hiện tại
(`tracuuphaply.vercel.app`) theo quy trình deploy thông thường của project (git push lên nhánh
Vercel theo dõi, hoặc `vercel --prod` nếu dùng CLI cục bộ) — **không nằm trong phạm vi P0 tự động
thực hiện**, người quản trị tự chạy khi đã sẵn sàng.

## 9. Cách restart Planner Sync Server

Sau khi đã điền `.env` (bước 3):

```
Stop-ScheduledTask -TaskName 'HAS_Planner_Sync_Server'
Start-Sleep -Seconds 2
Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Start-ScheduledTask -TaskName 'HAS_Planner_Sync_Server'
```

Kiểm tra lại: `Invoke-RestMethod http://127.0.0.1:8765/health` phải trả `ok: true`.

## 10. Cách kiểm tra Windows Task Scheduler

```
Get-ScheduledTask -TaskName 'HAS_Planner_Sync_Server' | Get-ScheduledTaskInfo
```

Xác nhận `LastTaskResult` không phải mã lỗi, và tiến trình `pythonw.exe planner_sync_server.py`
đang chạy (`Get-Process pythonw`). P0 **không thay đổi** cấu hình Task Scheduler — chỉ restart
tiến trình để nạp `.env` mới (bước 9).

## 11. Credential nào cần rotate

- `APPS_SCRIPT_TOKEN` — **khuyến nghị** rotate vì giá trị cũ đã từng nằm trong mã nguồn (dù
  không phải secret thật sự bí mật do kiến trúc frontend công khai — xem `SECURITY.md`).
- Mật khẩu admin cũ (`HASEDU2019@`, đã xóa khỏi code) — **bắt buộc coi là đã lộ**, đặt mật khẩu
  mới qua bước 1 (không dùng lại mật khẩu cũ).
- Các secret mới (`APPS_SCRIPT_SERVICE_TOKEN`, `ADMIN_SESSION_SECRET`, `PLANNER_SYNC_SHARED_SECRET`)
  không cần rotate ngay (mới sinh lần đầu) — chỉ rotate sau này nếu nghi ngờ lộ (xem `SECURITY.md`
  mục 4–5).

## 12. Phiên Microsoft nào cần thu hồi

**Không cần thu hồi ngay** do P0 lần này — P0 không đụng tới luồng Microsoft Graph/MSAL. Chỉ thu
hồi phiên `legal@has.edu.vn` (theo `SECURITY.md` mục 5.5) nếu có lý do cụ thể nghi ngờ lộ (ví dụ
`config/browser_session.json` từng bị chia sẻ ngoài ý muốn) — việc này luôn là thao tác thủ công,
không tự động.

## 13. File local nào cần xóa/tạo lại sau khi xác minh

- Không cần xóa file local nào theo P0 lần này.
- **Cần điều tra** (không tự xử lý): `logs/pipeline_20260513_081029.log` đã biến mất khỏi
  `logs/` trong lúc chạy P0 (không phải do P0 gây ra — xem
  `P0_SECURITY_IMPLEMENTATION_REPORT.md` mục 8). Xác nhận đây có phải hành vi dọn log bình
  thường của pipeline hay không; nếu cần khôi phục: `git checkout -- logs/pipeline_20260513_081029.log`.

## 14. File nào cần `git rm --cached`

**5 file** log đang bị Git track VÀ vẫn còn trên đĩa (thuộc diện bị ignore từ P0) — xem báo cáo
mục 8 để có lệnh đầy đủ:

```
git rm --cached logs/pipeline_20260513_100001.log logs/pipeline_20260513_153002.log logs/pipeline_20260514_100001.log logs/pipeline_20260514_153001.log logs/pipeline_20260515_100001.log
```

Lệnh này **không xóa file trên đĩa**, chỉ ngừng theo dõi trong Git. Chỉ chạy sau khi tự xác nhận
không cần các file này trong lịch sử Git nữa.

Riêng `logs/pipeline_20260513_081029.log` (file thứ 6, **trạng thái khác** — đã biến mất khỏi
đĩa, không phải chỉ đang bị track) **không** dùng lệnh trên — xem mục 13.

## 15. Git history cleanup cần quyền Admin

Nếu quyết định cần xóa hẳn secret/log cũ khỏi **lịch sử** Git (không chỉ khỏi commit hiện tại),
đây là thao tác riêng, rủi ro cao (`git filter-repo`/BFG, cần force-push, ảnh hưởng mọi clone) —
**chỉ thực hiện bởi người có quyền Admin trên repository**, sau khi đã rotate toàn bộ credential
liên quan (mục 11). Không nằm trong phạm vi P0 tự động.

## 16. Test production cần thực hiện

Sau khi hoàn tất bước 1–10 trên môi trường thật:

1. Mở Dashboard, đăng nhập admin bằng mật khẩu mới → phải thành công, không còn lỗi liên quan
   session.
2. Thử "Chuyển" 1 văn bản → phải thành công VÀ tạo được task Planner (kiểm tra toast "Đã tạo
   task Planner").
3. Đăng xuất, thử gọi lại action ghi dữ liệu (ví dụ mở DevTools gọi `transfer_record` không kèm
   `admin_session`) → phải bị từ chối `ADMIN_SESSION_REQUIRED`.
4. Kiểm tra `WEBAPP_DEBUG_LOG` không chứa mật khẩu/token dạng plaintext ở các dòng log gần nhất.
5. `Invoke-RestMethod http://127.0.0.1:8765/health` → chỉ thấy `ok/service/version/server_time`,
   không còn liệt kê `sync_endpoint`/`delete_endpoint`.
6. Xác nhận token công khai KHÔNG gọi được action nhóm B/C: gửi thẳng 1 request tới
   `APPS_SCRIPT_WEBAPP_URL` chỉ kèm `token` (không kèm `service_token`/`admin_session`) với
   `action: "import_vbqppl_nhap"` hoặc `action: "update_vbqppl_record"` → phải nhận
   `{"ok": false, "error": "SERVICE_TOKEN_INVALID"}`. Tương tự với `action: "transfer_record"`
   (không kèm `admin_session`) → phải nhận `{"ok": false, "error": "ADMIN_SESSION_REQUIRED"}`.
7. Chạy thử `08_process_field_documents_batch.py`/`11_sync_webapp_to_planner.py`/
   `12_sync_planner_to_webapp.py` với `.env` đã điền `APPS_SCRIPT_SERVICE_TOKEN` → phải thành
   công (không còn lỗi `SERVICE_TOKEN_INVALID`/"Thiếu APPS_SCRIPT_SERVICE_TOKEN").

## 17. Rollback khi có lỗi

Xem `SECURITY.md` mục 8 và `P0_SECURITY_IMPLEMENTATION_REPORT.md` mục 11. Tóm tắt: Apps Script
dùng "Manage deployments" quay lại version cũ; Vercel dùng "Instant Rollback"; Planner Sync
Server: dừng tiến trình, `git checkout <commit-cũ> -- planner_sync_server.py
planner_sync_security.py`, khởi động lại.

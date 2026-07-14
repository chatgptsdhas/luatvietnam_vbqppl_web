# SECURITY.md — Hệ thống VBQPPL (luatvietnam_vbqppl)

Tài liệu này mô tả phạm vi bảo mật P0 đã triển khai trên nhánh `security/p0-hardening`,
cách vận hành an toàn, và quy trình xử lý khi có sự cố lộ credential.

## 1. Phạm vi bảo mật

P0 hardening (nhánh này) bao gồm:

- Xóa mật khẩu admin viết cứng (`REAL_PASSWORD`) và token mặc định (`defaultToken`) khỏi
  `apps_script/WebApp.js`. **Không** xóa token khỏi `Dashboard/index.html` — hằng số `TOKEN` vẫn
  còn đó (xem "Giới hạn kiến trúc đã biết" bên dưới), chỉ KHÔNG còn dùng làm bằng chứng phân
  quyền cho bất kỳ action ghi dữ liệu/máy-máy nào nữa.
- Xác thực mật khẩu admin bằng PBKDF2-HMAC-SHA256 (không còn so sánh chuỗi thuần), session
  admin được ký HMAC (TTL mặc định 900 giây) thay vì chuỗi `AUTHORIZED_<timestamp>` đoán được.
- Mọi action **ghi dữ liệu** (chuyển văn bản, sửa, bỏ qua...) bắt buộc `requireAdminSession_()`
  ở **backend** (Apps Script) — không còn dựa vào việc frontend ẩn/hiện nút, và **không** có
  đường nào dùng service token hay token công khai để thay thế admin session.
- Action **máy-máy** (import từ Python, ghi lại thông tin Planner) yêu cầu service token riêng
  (`APPS_SCRIPT_SERVICE_TOKEN`) — **KHÔNG còn fallback** sang token công khai
  (`APPS_SCRIPT_TOKEN`) trong bất kỳ trường hợp nào; thiếu hoặc sai `APPS_SCRIPT_SERVICE_TOKEN`
  bị từ chối thẳng `SERVICE_TOKEN_INVALID`.
- Planner Sync Server cục bộ (`planner_sync_server.py`) chuyển từ xác thực **chỉ dựa vào CORS
  Origin** sang **bắt buộc chữ ký HMAC-SHA256** (`planner_sync_security.py`) cho mọi request ghi
  dữ liệu, có chống replay, giới hạn kích thước body, kiểm tra Content-Type.
- Envelope ký HMAC cho Planner Sync Server do Apps Script tạo (`createPlannerSyncEnvelope_`) —
  **frontend không bao giờ biết** `PLANNER_SYNC_SHARED_SECRET`.
- Không trả `stack trace` ra client ở bất kỳ endpoint nào (Apps Script lẫn Planner Sync Server).
  Mọi response lỗi có `correlationId` để tra log server-side.
- Redact đệ quy các trường nhạy cảm (`password, token, secret, session, cookie, authorization,
  signature, access_token, refresh_token`...) trước khi ghi vào `WEBAPP_DEBUG_LOG` hoặc log CI.

**Không thuộc phạm vi P0** (xem `P0_SECURITY_IMPLEMENTATION_REPORT.md` mục "Nội dung chưa hoàn
thành"): Outbox pattern, kiến trúc worker mới, UUID hoá văn bản, chuẩn hoá toàn bộ trạng thái,
tách nhỏ `Dashboard/index.html`/`WebApp.js`, hợp nhất toàn bộ luồng xác thực Microsoft, đổi cấu
trúc Sheet/Planner, xoá Planner Server cục bộ, đổi framework frontend.

### Giới hạn kiến trúc đã biết (không thể khắc phục hoàn toàn trong P0)

`Dashboard/index.html` là 1 trang tĩnh gọi thẳng Apps Script Web App triển khai ở chế độ
`ANYONE_ANONYMOUS` (không có đăng nhập Google). Vì vậy **luôn cần một token nhận diện ứng dụng**
nhúng trong mã nguồn client (`const TOKEN` trong `Dashboard/index.html`) — token này về bản chất
là public, ai xem mã nguồn trang cũng thấy được. P0 **không cố xoá token này** (không khả thi
nếu không xây dựng một backend proxy — nằm ngoài phạm vi P0) mà thay vào đó **ngừng dùng nó làm
bằng chứng phân quyền**: mọi thao tác ghi dữ liệu giờ đòi hỏi thêm admin session đã ký, được
backend xác minh độc lập với token này.

## 2. File không được commit

Đã khai báo trong `.gitignore` (xem file để có danh sách đầy đủ), quan trọng nhất:

- `.env`, `.env.*` (trừ `.env.example`)
- `auth/`, `credentials/`, `config/browser_session*.json`, `config/*token*.json`,
  `msal_device_flow.json`, `luatvietnam_state.json`
- `*.pem`, `*.key`, `*.pfx`
- `logs/`, `output/`, `__pycache__/`, `*.pyc`
- `apps_script/.clasp.json`

**Đã phát hiện (chưa xử lý tự động — xem P0_SECURITY_IMPLEMENTATION_REPORT.md):** một số file
`logs/pipeline_*.log` hiện đang được Git track dù thuộc nhóm bị ignore từ P0. Không tự động
`git rm --cached` các file này trong lúc chạy P0 — lệnh cụ thể được chuẩn bị sẵn trong
`P0_MANUAL_ACTIONS.md` để người quản trị tự xác nhận và chạy.

## 3. Quy trình báo cáo sự cố bảo mật

1. **Không** thảo luận chi tiết lỗ hổng trên kênh chat công khai của toàn trường/công ty.
2. Báo trực tiếp cho người quản trị hệ thống VBQPPL (phụ trách pháp chế / IT) qua kênh riêng
   tư (gặp trực tiếp, gọi điện, hoặc tin nhắn 1-1).
3. Ghi lại: thời điểm phát hiện, hành vi/triệu chứng quan sát được, phạm vi ảnh hưởng nghi ngờ
   (ví dụ: "token lộ trong ảnh chụp màn hình đã gửi nhóm chat ngày X").
4. Không tự ý "vá" bằng cách xoá dữ liệu/sheet/log — có thể làm mất bằng chứng điều tra.

## 4. Quy trình khi lộ credential

Khi nghi ngờ hoặc xác nhận một credential đã bị lộ (token, mật khẩu, secret, session):

1. **Ngừng sử dụng ngay** credential đó ở mọi nơi đang cấu hình (không đợi rotate xong mới dừng).
2. Xác định phạm vi: credential nào, ai/hệ thống nào đang dùng, lộ ở đâu (chat, email, log, Git).
3. Rotate credential đó theo hướng dẫn ở mục 5 bên dưới.
4. Nếu lộ qua log/Git: coi log/commit đó là đã "cháy" — rotate credential, không chỉ xoá dòng log.
   Việc dọn lịch sử Git (nếu credential từng bị commit) là thao tác quản trị riêng (mục 10).
5. Nếu lộ qua phiên đăng nhập Microsoft (session Playwright/MSAL của `legal@has.edu.vn`): thu hồi
   phiên theo mục 5.5 — **việc này KHÔNG được thực hiện tự động trong lúc chạy P0 hardening**,
   chỉ người quản trị được uỷ quyền mới thực hiện.
6. Ghi lại sự cố (thời điểm, credential nào, hành động đã thực hiện) để tham chiếu sau này.

## 5. Cách rotate credential

Dùng `python scripts/generate_p0_secrets.py` để sinh giá trị mới cho mục 5.1–5.4. Xem
`P0_MANUAL_ACTIONS.md` để biết chính xác biến nào điền vào đâu.

**Thiết lập/kiểm tra Script Properties:** `apps_script/Security.js` có `P0_SCRIPT_PROPERTY_SCHEMA_`
liệt kê đủ 10 Script Property P0 (6 secret bắt buộc + 4 giá trị mặc định an toàn), cùng 2 hàm chỉ
chạy thủ công trong Apps Script Editor (KHÔNG gọi được qua `doPost`):
`installP0ScriptPropertyDefaults()` (tự tạo 4 giá trị mặc định — `ADMIN_PASSWORD_ITERATIONS`,
`ADMIN_SESSION_TTL_SECONDS`, `PLANNER_SYNC_REQUEST_TTL_SECONDS`, `WEBAPP_LOG_VERBOSE_DEBUG` — chỉ
khi property đó chưa tồn tại, không bao giờ ghi đè, không đụng `INTRO_*`/property khác, không
tạo placeholder cho secret) và `auditP0ScriptProperties()` (báo cáo SET/MISSING và validate định
dạng cho 4 property có giá trị mặc định — không bao giờ trả về hay log giá trị secret thật, chỉ
tên property). Xem hướng dẫn thao tác từng bước ở `P0_MANUAL_ACTIONS.md` mục 4a.

### 5.1 Apps Script service token (`APPS_SCRIPT_SERVICE_TOKEN`) / token dự án (`APPS_SCRIPT_TOKEN`)

Đây là 2 secret độc lập, không thay thế cho nhau — `APPS_SCRIPT_SERVICE_TOKEN` KHÔNG còn
fallback về `APPS_SCRIPT_TOKEN` (đã gỡ bỏ hoàn toàn khỏi `Security.js`).

1. Sinh token mới bằng `scripts/generate_p0_secrets.py`.
2. Cập nhật Script Property tương ứng trong Apps Script Editor (Project Settings → Script
   Properties).
3. Với `APPS_SCRIPT_SERVICE_TOKEN`: cập nhật thêm biến môi trường cùng tên trong `.env` của máy
   chạy `08_process_field_documents_batch.py`, `11_sync_webapp_to_planner.py`,
   `12_sync_planner_to_webapp.py` — cả 3 script sẽ dừng hoạt động (service action) nếu giá trị
   không khớp Script Property.
4. Với `APPS_SCRIPT_TOKEN` (token công khai, chỉ còn dùng cho action đọc): cập nhật thêm hằng số
   `TOKEN` trong `Dashboard/index.html` và biến môi trường `APPS_SCRIPT_TOKEN` mà các script
   Python đang dùng làm cổng nhận diện ứng dụng ở tầng ngoài cùng.
5. Deploy lại theo mục 6–7.

### 5.2 Mật khẩu admin (`ADMIN_PASSWORD_SALT` / `ADMIN_PASSWORD_HASH`)

1. Chạy `scripts/generate_p0_secrets.py`, nhập mật khẩu mới khi được hỏi.
2. Cập nhật `ADMIN_PASSWORD_SALT`, `ADMIN_PASSWORD_HASH`, `ADMIN_PASSWORD_ITERATIONS` trong
   Script Properties của Apps Script.
3. Toàn bộ session admin đang hoạt động (ký bằng `ADMIN_SESSION_SECRET`) **không tự động mất
   hiệu lực** khi đổi mật khẩu — nếu cần thu hồi ngay lập tức, rotate luôn `ADMIN_SESSION_SECRET`
   (mục 5.3) để mọi session cũ (kể cả chưa hết TTL 900s) bị vô hiệu ngay.

### 5.3 Admin session secret (`ADMIN_SESSION_SECRET`)

1. Sinh secret mới bằng `scripts/generate_p0_secrets.py`.
2. Cập nhật Script Property `ADMIN_SESSION_SECRET`.
3. Hiệu lực: **mọi session admin đã cấp trước đó lập tức không hợp lệ** (chữ ký HMAC không còn
   khớp) — mọi người dùng admin phải đăng nhập lại. Dùng biện pháp này để thu hồi khẩn cấp.

### 5.4 Planner Sync shared secret (`PLANNER_SYNC_SHARED_SECRET`)

1. Sinh secret mới bằng `scripts/generate_p0_secrets.py`.
2. Cập nhật cả hai nơi PHẢI giống nhau tuyệt đối:
   - Script Property `PLANNER_SYNC_SHARED_SECRET` trong Apps Script.
   - Biến `PLANNER_SYNC_SHARED_SECRET` trong `.env` cục bộ (nơi chạy `planner_sync_server.py`).
3. Khởi động lại Planner Sync Server (xem `P0_MANUAL_ACTIONS.md`) để nạp secret mới — server chỉ
   đọc `.env` lúc khởi động.

### 5.5 Phiên đăng nhập Microsoft (Graph API — `legal@has.edu.vn`)

1. Thu hồi phiên hiện tại: đăng nhập https://myaccount.microsoft.com bằng tài khoản
   `legal@has.edu.vn` (hoặc nhờ quản trị viên Microsoft 365 của tổ chức) → **Security info** /
   **Sign out everywhere** (hoặc thu hồi refresh token qua Entra ID admin center nếu có quyền).
2. Xoá session/token cache cục bộ: `config/browser_session.json`, `config/browser_session_*.json`,
   `config/token_cache.json` (nếu tồn tại) trên MÁY đang chạy pipeline.
3. Chạy lại `python auth_init.py` hoặc `python get_token_browser.py` để đăng nhập lại từ đầu.
4. **Việc thu hồi phiên Microsoft KHÔNG được thực hiện tự động trong quá trình chạy P0
   hardening** — đây luôn là thao tác thủ công, có chủ đích, do người quản trị thực hiện.

## 6. Phân quyền deploy

- **Apps Script (`clasp push` + tạo deployment mới):** chỉ người có quyền Editor trên Apps Script
  project (đồng thời biết `ADMIN_PASSWORD_*`/`ADMIN_SESSION_SECRET`/`PLANNER_SYNC_SHARED_SECRET`
  cần thiết) mới được deploy.
- **Vercel (frontend `Dashboard/index.html` qua `tracuuphaply.vercel.app`):** chỉ thành viên có
  quyền trên project Vercel tương ứng.
- **Planner Sync Server / Windows Task Scheduler:** chỉ người có quyền truy cập máy chạy server
  (hiện là máy cục bộ của người phụ trách pháp chế).
- Không chia sẻ các quyền trên qua tài khoản dùng chung.

## 7. Kiểm tra trước deploy

Trước khi tạo deployment mới cho Apps Script hoặc deploy frontend:

1. `python -m compileall .` và `python -m unittest discover -s tests -p "test_*.py"` phải PASS.
2. `node --check apps_script/WebApp.js` và `node --check apps_script/Security.js` phải không lỗi
   cú pháp; `node tests/test_webapp_security_boundaries.js` và
   `node tests/test_p0_script_property_management.js` phải PASS (không cần cài Node trên máy
   production, chỉ cần lúc review/CI).
3. Trong Apps Script Editor, chạy thủ công `installP0ScriptPropertyDefaults` rồi
   `auditP0ScriptProperties` (xem `P0_MANUAL_ACTIONS.md` mục 4a) — chỉ tiếp tục deploy khi kết quả
   `auditP0ScriptProperties` trả `ok: true` (đủ cả 10 Script Property: `APPS_SCRIPT_TOKEN`,
   `APPS_SCRIPT_SERVICE_TOKEN`, `ADMIN_PASSWORD_SALT`, `ADMIN_PASSWORD_HASH`,
   `ADMIN_PASSWORD_ITERATIONS`, `ADMIN_SESSION_SECRET`, `ADMIN_SESSION_TTL_SECONDS`,
   `PLANNER_SYNC_SHARED_SECRET`, `PLANNER_SYNC_REQUEST_TTL_SECONDS`, `WEBAPP_LOG_VERBOSE_DEBUG`,
   đúng định dạng). Thiếu property sẽ khiến các action liên quan trả lỗi
   `MISSING_SCRIPT_PROPERTY`/`SERVICE_TOKEN_INVALID`/`SERVER_NOT_CONFIGURED` thay vì mở khoá
   bằng giá trị mặc định hay fallback (đây là hành vi fail-closed CÓ CHỦ ĐÍCH).
4. Đăng nhập thử với tài khoản admin thật, xác nhận các action ghi dữ liệu (chuyển văn bản, sửa,
   bỏ qua) hoạt động bình thường sau khi đăng nhập, và bị từ chối khi CHƯA đăng nhập.
5. Xác nhận `08_process_field_documents_batch.py`/`11_sync_webapp_to_planner.py`/
   `12_sync_planner_to_webapp.py` đã có `APPS_SCRIPT_SERVICE_TOKEN` trong `.env` — chạy thử 1 lần
   (hoặc `--dry-run` nếu script hỗ trợ) để xác nhận không bị `SERVICE_TOKEN_INVALID`.
6. Kiểm tra `git status`/`git diff --stat` — không có file nhạy cảm mới được thêm vào staging.

## 8. Rollback

- **Apps Script:** dùng tính năng "Manage deployments" → chọn lại phiên bản deployment trước đó
  (Apps Script giữ lịch sử version, không cần rollback qua Git).
- **Frontend Vercel:** dùng "Instant Rollback" trên Vercel dashboard về deployment trước.
- **Planner Sync Server:** dừng server (`Stop-ScheduledTask` nếu chạy qua Task Scheduler, hoặc
  đóng cửa sổ tiến trình), khôi phục file `.py` từ commit trước đó (`git checkout <commit> --
  planner_sync_server.py planner_sync_security.py`), khởi động lại.
- **Git (nhánh `security/p0-hardening`):** vì P0 chủ động không tạo commit trong lúc chạy (mọi
  thay đổi để ở working tree cho người dùng tự review/commit), rollback đơn giản là không commit
  / `git restore` các file muốn hoàn tác — xem thêm hướng dẫn review trong
  `P0_SECURITY_IMPLEMENTATION_REPORT.md`.

## 9. Không lưu credential trong email, chat, Word hoặc Excel

Mọi secret sinh ra từ `scripts/generate_p0_secrets.py` (token, salt, hash, session secret...) chỉ
được:

- Dán trực tiếp vào `.env` (không commit) hoặc Script Properties, HOẶC
- Lưu trong password manager có kiểm soát truy cập (ví dụ Bitwarden/1Password của tổ chức).

**Không** dán vào Zalo, Teams, email, Google Docs/Sheets, Word, Excel — kể cả ở dạng "tạm" — vì
các kênh này thường không có audit log xoá vĩnh viễn và dễ bị chuyển tiếp ngoài ý muốn.

## 10. Dọn lịch sử Git (git history cleanup)

Nếu một secret từng bị **commit** vào Git (kể cả đã xoá ở commit sau), secret đó vẫn còn trong
lịch sử Git và coi như đã lộ vĩnh viễn cho đến khi:

1. Secret đó được **rotate** (mục 5) — đây là bước bắt buộc, làm trước tiên và luôn luôn cần làm.
2. (Tuỳ chọn, chỉ khi thực sự cần) lịch sử Git được viết lại (`git filter-repo`/BFG Repo-Cleaner)
   để xoá secret khỏi các commit cũ.

Bước 2 là **thao tác quản trị riêng, có rủi ro cao** (ảnh hưởng mọi clone/fork hiện có, cần
force-push, cần phối hợp với mọi người đang có bản sao repo) — **không nằm trong phạm vi P0
hardening tự động**, không được thực hiện mà không có sự đồng ý rõ ràng của chủ repository, và
luôn thực hiện sau khi đã rotate xong secret liên quan (bước 1).

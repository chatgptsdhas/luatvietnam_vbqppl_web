# P0 Security Implementation Report

Nhánh: `security/p0-hardening`
Ngày thực hiện: 2026-07-13

## 1. Trạng thái trước P0

- Nhánh `security/p0-hardening` đã tồn tại sẵn, HEAD tại commit `ae396d6` ("Cập nhật lại lỗi
  không tạo task"), rẽ ra từ `main`.
- Trước khi bắt đầu sửa gì, `git status --short` chỉ có **1 file untracked**:
  `logs/planner_sync_server.log` (log, không phải mã nguồn). Không có thay đổi nào khác đang
  chờ (working tree sạch so với HEAD).
- **Lưu ý quan trọng:** `apps_script/WebApp.js` tại HEAD là một phiên bản **gọn hơn nhiều** so
  với những gì có thể đã được thảo luận ở phiên làm việc trước đó trong cùng hội thoại (không có
  các action `restore_transferred_record`, `log_page_access`, `get_intro_content`,
  `save_intro_content`, cũng như hệ thống retention/archive log). Đây là trạng thái **thật** của
  Git tại thời điểm chạy P0 — báo cáo này mô tả đúng những gì đã sửa trên nền tảng đó, không giả
  định lại nội dung từ trí nhớ hội thoại.
- File `apps_script/MultiSelectSidebar.html` được IDE báo là đang mở nhưng **không tồn tại**
  trong working directory tại thời điểm chạy P0 (`git ls-files` không thấy, đọc file báo lỗi
  not-found). Không có gì để stage cho file này — đã bỏ qua đúng theo hướng dẫn mục IV.

## 2. Commit nền đã tạo

**Không tạo commit nền.** Vì tại thời điểm bắt đầu, `.env.example`, `apps_script/WebApp.js`,
`apps_script/Module_HetHieuLuc.js`, `apps_script/appsscript.json` đều **không có thay đổi nào**
so với HEAD (đã xác nhận bằng `git diff --stat -- <từng file>` — tất cả trống), và
`apps_script/MultiSelectSidebar.html` không tồn tại. Không có gì để tách khỏi P0, nên bước tạo
"commit nền trước P0" không áp dụng được — đã bỏ qua có chủ đích, không tạo commit rỗng.

## 3. File đã sửa

| File | Nội dung sửa |
|---|---|
| `.gitignore` | Bổ sung block P0 (secrets, session, credentials, runtime files, `apps_script/.clasp.json`) — giữ nguyên 9 dòng gốc. |
| `.env.example` | Thêm `APPS_SCRIPT_SERVICE_TOKEN`, `PLANNER_SYNC_SHARED_SECRET`, `PLANNER_SYNC_ALLOWED_ORIGINS`, `PLANNER_SYNC_REQUEST_TTL_SECONDS`, `PLANNER_SYNC_MAX_BODY_BYTES`, `ADMIN_SESSION_TTL_SECONDS`, `ADMIN_PASSWORD_SALT`, `ADMIN_PASSWORD_HASH`, `ADMIN_PASSWORD_ITERATIONS`, `ADMIN_SESSION_SECRET`, `WEBAPP_LOG_VERBOSE_DEBUG` (tất cả để trống, không có giá trị thật). |
| `apps_script/WebApp.js` | Xóa token mặc định (`setupWebAppToken`); `verify_admin` dùng PBKDF2 + session ký HMAC qua `Security.js` thay vì mật khẩu plaintext + `AUTHORIZED_<timestamp>`; phân loại action A(đọc)/B(service)/C(admin-write) và enforce `validateServiceToken_`/`requireAdminSession_` trong `doPost`; `appendDebugLog_` redact dữ liệu nhạy cảm + không throw ra ngoài; thêm correlation ID cho mọi request/response; lỗi trả về client qua `sanitizeErrorForClient_` (không còn `stack`); thêm action `request_planner_sync_envelope` (nhóm C, schema whitelist); thêm `installWebAppDebugLogMaintenanceTrigger()`/`removeWebAppDebugLogMaintenanceTrigger()` (bản tối thiểu — xem mục 10). |
| `Dashboard/index.html` | Thêm khối quản lý admin session bằng `sessionStorage` (`getAdminSessionToken`, `isAdminLoggedIn`, `setAdminSession`, `clearAdminSession`, `withAdminSession`, `handleAdminSessionResponse`); thay toàn bộ 10 chỗ đọc `localStorage.isAdminAccess` bằng `isAdminLoggedIn()`; đăng nhập/đăng xuất dùng `sessionStorage` + dọn key `localStorage` cũ; đính kèm `admin_session` vào 8 request ghi dữ liệu (`transfer_record` ×3, `update_record` ×5); phát hiện `ADMIN_SESSION_REQUIRED` để tự đăng xuất; luồng Planner sync (tạo task + xóa task) chuyển sang xin **signed envelope** từ Apps Script (`fetchPlannerSyncEnvelope_`) rồi mới gọi Planner Sync Server cục bộ kèm header `X-P0-*`, thay vì gửi thẳng payload không chữ ký. |
| `planner_sync_server.py` | Tích hợp `planner_sync_security.py`: bắt buộc HMAC (`verify_signed_request`) trước khi chạy sync/delete; bỏ `null` khỏi `DEFAULT_ALLOWED_ORIGINS`; `is_origin_allowed(None)` trả `False` (không còn mặc định cho qua); Origin sai bị chặn sớm (403) nhưng Origin thiếu vẫn phải qua HMAC; giới hạn body theo `PLANNER_SYNC_MAX_BODY_BYTES`; kiểm tra `Content-Type: application/json`; `/health` chỉ trả `ok/service/version/server_time`; lỗi nội bộ không lộ chi tiết ra client (chỉ log server-side); mọi response có `correlationId`. |
| `apps_script/Security.js` | **Gỡ bỏ hoàn toàn** fallback `legacy_token_fallback` trong `validateServiceToken_` — chỉ còn chấp nhận đúng `APPS_SCRIPT_SERVICE_TOKEN` (Script Property bắt buộc, không optional nữa). Bổ sung `P0_SCRIPT_PROPERTY_SCHEMA_` (khai báo đủ 10 Script Property P0, phân loại secret bắt buộc vs. có giá trị mặc định an toàn) cùng 3 hàm quản lý: `installP0ScriptPropertyDefaults()` (tự set 4 giá trị mặc định nếu property chưa tồn tại, không bao giờ ghi đè/tạo placeholder cho secret), `auditP0ScriptProperties()` (báo cáo SET/MISSING + validate định dạng, không log/trả giá trị secret), `requireP0ScriptProperties_()` (throw `P0_SCRIPT_PROPERTIES_INVALID` nếu thiếu/sai — chỉ liệt kê tên property). Cả 3 hàm **không có case nào trong `doPost`** — chỉ chạy thủ công trong Apps Script Editor. |
| `apps_script/WebApp.js` (P0 tiếp theo) | Sửa comment mô tả nhóm B trong `ACTION_SECURITY_GROUP_` — comment cũ còn nhắc "tạm fallback về token dự án cũ" dù fallback đã bị xóa từ trước, gây hiểu nhầm; đã cập nhật cho khớp hành vi thật của `validateServiceToken_`. |
| `08_process_field_documents_batch.py` | Thêm `resolve_apps_script_service_token()`; `send_to_apps_script()` bắt buộc `service_token` (lỗi rõ ràng nếu thiếu) và gửi kèm trong body `import_vbqppl_nhap`. |
| `11_sync_webapp_to_planner.py` | `webapp_post()` bắt buộc `APPS_SCRIPT_SERVICE_TOKEN` qua `get_required_env`, gửi kèm `service_token` cho cả `get_all_records` lẫn `update_vbqppl_record` (dùng chung 1 hàm gọi API). |
| `12_sync_planner_to_webapp.py` | Tương tự `11_sync_webapp_to_planner.py`. |

## 4. File đã tạo

- `apps_script/Security.js` — module bảo mật Apps Script (PBKDF2, session HMAC, service token, redact, signed envelope Planner).
- `planner_sync_security.py` — HMAC canonical request/verify + `ReplayCache` thread-safe cho Planner Sync Server.
- `scripts/generate_p0_secrets.py` — sinh token/salt/hash bằng `secrets`/`hashlib.pbkdf2_hmac` (standard library), không tự ghi file.
- `scripts/ci_secret_scan.py` — quét mẫu secret viết cứng cho CI (giá trị phát hiện được che ≥80%).
- `tests/test_planner_sync_security.py` — 27 test (signing, verify, replay cache thread-safety, cross-language JS↔Python, HTTP server thật).
- `tests/test_p0_static_checks.py` — 35 test tĩnh (không còn default token/password/fallback, redact, admin session bắt buộc, script Python gửi service_token, schema/visibility/không lộ qua doPost của `installP0ScriptPropertyDefaults`/`auditP0ScriptProperties`/`requireP0ScriptProperties_`...).
- `tests/test_webapp_security_boundaries.js` — 24 test **hành vi thật** (chạy `doPost()` mô phỏng qua Node vm): chứng minh token công khai không gọi được bất kỳ action nhóm B/C hay hàm bảo trì nào.
- `tests/test_p0_script_property_management.js` — 18 test **hành vi thật** (Node vm) cho `installP0ScriptPropertyDefaults`/`auditP0ScriptProperties`/`requireP0ScriptProperties_`: không ghi đè property có sẵn, không tạo placeholder cho secret, không đụng `INTRO_*`, idempotent, validate định dạng 4 property có default, không bao giờ trả/log giá trị secret thật, và không gọi được qua `doPost`.
- `.github/workflows/security.yml` — compile check + syntax check Apps Script + unit test Python + 2 test hành vi Node + chặn file cấm + quét secret khi push/PR.
- `SECURITY.md` — phạm vi bảo mật, rotate credential, rollback, quy trình sự cố.
- `P0_SECURITY_IMPLEMENTATION_REPORT.md`, `P0_MANUAL_ACTIONS.md` — 2 báo cáo này.

## 5. Lỗ hổng đã xử lý

| # | Lỗ hổng (mục V) | Xử lý |
|---|---|---|
| 1 | Token viết cứng (`setupWebAppToken`) | Xóa default, bắt buộc truyền token thật. |
| 2 | Mật khẩu viết cứng (`REAL_PASSWORD = "HASEDU2019@"`) | Thay bằng PBKDF2-HMAC-SHA256 so khớp `ADMIN_PASSWORD_HASH`. |
| 6 | Token công khai (`const TOKEN` trong `Dashboard/index.html`) | **Không xóa khỏi frontend được** — giới hạn kiến trúc đã ghi rõ trong `SECURITY.md` (Apps Script Web App `ANYONE_ANONYMOUS`). Đã xử lý dứt điểm phần quan trọng hơn: token này **không bao giờ** mở khoá được action nhóm B (service — chặn bởi `validateServiceToken_`, không còn fallback) hay nhóm C (admin/write — chặn bởi `requireAdminSession_`, độc lập hoàn toàn với mọi loại token). Chứng minh bằng test hành vi `tests/test_webapp_security_boundaries.js`. |
| 7 | `localStorage.isAdminAccess` là bằng chứng quyền admin | Thay bằng session ký HMAC lưu `sessionStorage`, backend xác minh độc lập. |
| 8 | API ghi dữ liệu không kiểm tra admin session | `requireAdminSession_()` bắt buộc cho `transfer_record`, `update_record`, `request_planner_sync_envelope`. |
| 9 | API trả stack trace ra client | `sanitizeErrorForClient_()` (Apps Script) + `write_internal_error()` (Planner Server) — không còn `stack` trong response. |
| 10 | Planner Sync Server chỉ dựa CORS | Bắt buộc HMAC-SHA256 (`planner_sync_security.verify_request`) trước khi chạy sync/delete. |
| 11 | Request không Origin vẫn được chấp nhận | `is_origin_allowed(None)` nay trả `False`; nhưng request không Origin vẫn được xử lý tiếp **chỉ nếu HMAC hợp lệ** (đúng yêu cầu mục XIII.8). |
| 12 | Origin `null` trong danh sách mặc định | Đã xóa khỏi `DEFAULT_ALLOWED_ORIGINS`. |
| 13 | File nhạy cảm được Git track | Phát hiện 5 file `logs/pipeline_*.log` đang được track (còn trên đĩa) + 1 file cùng dạng đã bị xóa khỏi đĩa ngoài ý muốn (không cùng trạng thái, xem mục 8 để phân biệt) — chưa xử lý tự động. |
| 14 | Log ghi token/password/session | `redactSensitiveData_()` (Apps Script, đệ quy) áp dụng cho mọi `appendDebugLog_`; `log_event()` (Planner Server) chỉ nhận field nghiệp vụ, không bao giờ nhận secret/signature/header thô. |
| 15 | Không có cách thiết lập/kiểm tra nhất quán 10 Script Property P0 (dễ deploy thiếu secret hoặc để giá trị mặc định sai định dạng mà không biết) — bổ sung theo yêu cầu tiếp theo, ngoài mục V gốc | `P0_SCRIPT_PROPERTY_SCHEMA_` + `installP0ScriptPropertyDefaults()`/`auditP0ScriptProperties()`/`requireP0ScriptProperties_()` trong `apps_script/Security.js` — chỉ chạy thủ công trong Apps Script Editor, không qua `doPost`; không tạo placeholder cho secret; không log/trả giá trị secret; không đụng `INTRO_*`/property khác ngoài schema. |

Chưa xử lý / xử lý một phần: mục 3 "Access token/refresh token" và mục 4 "Cookie/browser
session" (Microsoft Graph) — các file này (`config/browser_session*.json`,
`config/token_cache.json`) vốn đã nằm ngoài Git từ trước (không track), P0 chỉ bổ sung rule
`.gitignore` tường minh hơn, không thay đổi cơ chế lưu trữ của `get_token_browser.py`/`ms_auth_init.py`
(nằm ngoài phạm vi P0 theo mục XX).

## 6. Test đã chạy (lần chạy cuối cùng, sau khi bổ sung quản lý Script Properties P0)

```
python -m compileall .
python -m unittest discover -s tests -p "test_*.py" -v
node --check apps_script/WebApp.js
node --check apps_script/Security.js
node tests/test_webapp_security_boundaries.js
node tests/test_p0_script_property_management.js
python scripts/ci_secret_scan.py
```

`python -m pytest` — bỏ qua (repo chưa có pytest trong `requirements.txt`, đúng điều kiện "nếu
repo đã có pytest" ở mục XIX).

## 7. Kết quả test

- `python -m compileall .` → **PASS**, không lỗi cú pháp Python trong toàn repo (bao gồm
  `08_process_field_documents_batch.py`, `11_sync_webapp_to_planner.py`,
  `12_sync_planner_to_webapp.py` sau khi sửa).
- `python -m unittest discover -s tests -p "test_*.py"` → **62/62 PASS** (`Ran 62 tests ... OK`):
  - 27 test HMAC/replay/timestamp/body-size/content-type/cross-language JS↔Python/HTTP server thật (`test_planner_sync_security.py`).
  - 35 test tĩnh cho `WebApp.js`, `Security.js`, `Dashboard/index.html`, `planner_sync_server.py`,
    3 script Python gửi `service_token`, và cơ chế quản lý Script Properties P0
    (`test_p0_static_checks.py`, gồm test mới `test_no_service_token_fallback_to_legacy_token`,
    `TestPythonServiceScriptsSendServiceToken`,
    `test_p0_script_property_schema_covers_all_10_properties`,
    `test_p0_property_management_functions_present_with_correct_visibility`,
    `test_install_never_sets_secret_properties_directly`,
    `test_audit_and_require_do_not_return_raw_property_values`,
    `test_p0_property_management_functions_not_exposed_via_doPost`).
  - Trong đó `test_js_signed_envelope_is_accepted_by_python_verifier` chạy **thật** qua Node.js
    để tạo envelope bằng `Security.js`, rồi xác nhận `planner_sync_security.py` (Python) chấp
    nhận đúng chữ ký đó — xác nhận công thức canonical message khớp byte-for-byte giữa 2 ngôn ngữ.
- `node --check apps_script/WebApp.js` / `Security.js` → **PASS**.
- **`node tests/test_webapp_security_boundaries.js` → 24/24 PASS** — test hành vi thật (chạy
  `doPost()` mô phỏng), chứng minh trực tiếp: token công khai (`APPS_SCRIPT_TOKEN`) một mình
  KHÔNG gọi được `import_vbqppl_nhap`, `update_vbqppl_record`, `request_planner_sync_envelope`,
  bất kỳ action nào khác trong `ACTION_SECURITY_GROUP_` nhóm B/C (quét toàn bộ map, không
  cherry-pick), lẫn các hàm bảo trì (`installWebAppDebugLogMaintenanceTrigger`,
  `removeWebAppDebugLogMaintenanceTrigger`, `executeWebAppDebugLogMaintenance_`,
  `cleanupIrrelevantRowsAfter90Days`, `createDailyIrrelevantCleanupTrigger` — tất cả trả
  `ACTION_NOT_SUPPORTED` vì không hề có trong switch của `doPost`, không phụ thuộc token nào).
  Đồng thời xác nhận `service_token` không thể thay thế `admin_session` cho action nhóm C, và
  action nhóm A vẫn hoạt động bình thường chỉ với token công khai.
- **`node tests/test_p0_script_property_management.js` → 18/18 PASS** — test hành vi thật cho
  `installP0ScriptPropertyDefaults`/`auditP0ScriptProperties`/`requireP0ScriptProperties_`:
  install chỉ set 4 default an toàn khi property chưa tồn tại, không ghi đè giá trị tuỳ chỉnh đã
  có, không đụng property ngoài schema (kiểm thử cả với `INTRO_LOGIN` giả lập), idempotent qua 2
  lần chạy, không bao giờ set 6 secret bắt buộc; audit phát hiện đúng property thiếu/sai định
  dạng (`ADMIN_PASSWORD_ITERATIONS` < 100000, `WEBAPP_LOG_VERBOSE_DEBUG` không phải
  `true`/`false`, TTL không phải số nguyên dương) và **không bao giờ** làm lộ giá trị secret thật
  trong kết quả trả về (kiểm thử bằng cách set secret thành giá trị đặc trưng rồi assert không
  xuất hiện trong `JSON.stringify` kết quả); `requireP0ScriptProperties_` throw đúng mã lỗi với
  message chỉ chứa tên property; cả 3 hàm được xác nhận **không gọi được qua `doPost`** dù dùng
  token công khai hay service token đúng.
- `python scripts/ci_secret_scan.py` → **PASS** (không phát hiện mẫu secret viết cứng nào).
- `.github/workflows/security.yml` đã được xác thực cú pháp YAML hợp lệ (parse bằng PyYAML,
  11 step — bổ sung Setup Node.js + syntax check Apps Script + chạy
  `test_webapp_security_boundaries.js` + `test_p0_script_property_management.js` — trigger đúng
  `push`/`pull_request`) — **chưa** được chạy thật trên GitHub (không push).

## 8. File nhạy cảm đang được Git track (chỉ đường dẫn, không in nội dung)

**5 file sau đang được Git track VÀ vẫn còn trên đĩa** (cùng trạng thái — chỉ cần `git rm
--cached` nếu muốn ngừng track mà vẫn giữ file local):

- `logs/pipeline_20260513_100001.log`
- `logs/pipeline_20260513_153002.log`
- `logs/pipeline_20260514_100001.log`
- `logs/pipeline_20260514_153001.log`
- `logs/pipeline_20260515_100001.log`

(Đã quét nhanh bằng `grep -ci` các từ khóa token/password/secret/authorization/access_token/
refresh_token/cookie trong 5 file trên — **0 match** ở cả 5 file, tức KHÔNG phát hiện dấu hiệu rò
rỉ credential cụ thể trong nội dung, nhưng các file này vẫn không nên được track theo policy mới.)

Lệnh gỡ khỏi Git (KHÔNG xóa file local) — chỉ chạy nếu người quản trị xác nhận đồng ý:

```
git rm --cached logs/pipeline_20260513_100001.log logs/pipeline_20260513_153002.log logs/pipeline_20260514_100001.log logs/pipeline_20260514_153001.log logs/pipeline_20260515_100001.log
```

**File thứ 6, trạng thái KHÁC hẳn 5 file trên — phát hiện ngoài phạm vi P0 (không do quá trình
chạy P0 gây ra):** file `logs/pipeline_20260513_081029.log` — cũng từng được Git track từ "first
commit" — hiện **đã bị xóa khỏi ổ đĩa** (không còn trong `logs/`, `git status` báo
`D logs/pipeline_20260513_081029.log`, KHÔNG phải `??`/tracked-and-present như 5 file kia).
Đã xác nhận qua bản backup tại bước III (`git_status_before_p0.txt`, chụp TRƯỚC khi P0 sửa bất kỳ
file nào): tại thời điểm đó file này còn nguyên, chưa bị xóa — nghĩa là việc xóa xảy ra **trong
lúc** phiên P0 đang chạy nhưng **không phải do bất kỳ lệnh nào của P0 gây ra** (không có lệnh nào
trong toàn bộ phiên này động tới đường dẫn đó). Khả năng cao nhất là một tiến trình pipeline tự
động khác (ví dụ `run_luatvietnam_pipeline.ps1` / dọn log định kỳ) đã xoay vòng/xóa file trong lúc
P0 đang chạy song song. **Không tự phục hồi file này** — để nguyên trong working tree cho người
dùng tự quyết định (`git checkout -- logs/pipeline_20260513_081029.log` nếu muốn khôi phục từ
Git, hoặc xác nhận đây là hành vi dọn log bình thường rồi bỏ qua).

## 9. Rủi ro tương thích

- **Toàn bộ action ghi dữ liệu sẽ NGỪNG hoạt động** cho tới khi Script Properties
  `ADMIN_PASSWORD_SALT`, `ADMIN_PASSWORD_HASH`, `ADMIN_SESSION_SECRET` được tạo (xem
  `P0_MANUAL_ACTIONS.md`) — đây là hành vi fail-closed **có chủ đích**, không phải lỗi.
- **Planner Sync Server sẽ từ chối mọi request tạo/xóa task** cho tới khi
  `PLANNER_SYNC_SHARED_SECRET` được cấu hình **giống nhau** ở cả Apps Script Script Property và
  `.env` cục bộ.
- **Không còn fallback.** `08_process_field_documents_batch.py`, `11_sync_webapp_to_planner.py`,
  `12_sync_planner_to_webapp.py` (3 script duy nhất gọi action nhóm B) nay **bắt buộc** gửi
  `service_token` lấy từ `APPS_SCRIPT_SERVICE_TOKEN`, và `Security.js::validateServiceToken_`
  không còn nhánh nào chấp nhận `APPS_SCRIPT_TOKEN` thay thế. Thiếu biến môi trường này, 3 script
  trên sẽ dừng ngay (08, báo lỗi rõ ràng cục bộ) hoặc bị Apps Script từ chối `SERVICE_TOKEN_INVALID`
  (11, 12). `13_generate_planner_reports.py`/`14_notify_planner_escalation.py` chỉ gọi
  `get_all_records` (nhóm A, đọc công khai) nên không cần sửa, không bị ảnh hưởng;
  `10_create_planner_task_from_webapp.py`/`09_validate_pipeline_result.py` không gọi WebApp API.
  Đã kiểm chứng bằng `tests/test_webapp_security_boundaries.js` (24/24 pass) và
  `tests/test_p0_static_checks.py::TestPythonServiceScriptsSendServiceToken`.
- `Dashboard/index.html` tham chiếu một số action **không tồn tại** trong `WebApp.js` hiện tại
  (`restore_transferred_record`, `save_intro_content`, `get_intro_content`, `log_page_access`,
  `log_doc_view`, `get_access_analytics`, `get_docview_analytics`) — đây là bất tương thích **có
  từ trước P0** (không phải do P0 gây ra), các action này sẽ nhận `ACTION_NOT_SUPPORTED` như
  trước khi chạy P0. Không nằm trong phạm vi sửa của P0.
- Đăng nhập admin cũ (`localStorage.isAdminAccess`/`adminSessionToken`) sẽ bị coi là đăng xuất
  ngay sau khi deploy bản mới (khác cơ chế lưu trữ) — người dùng cần đăng nhập lại 1 lần.

## 10. Nội dung chưa hoàn thành

- **Hệ thống retention/archive/summary log đầy đủ** (giống bản đã thảo luận ở phiên trước, nếu
  có) — KHÔNG được xây dựng lại trong P0 này vì đó là tính năng vận hành/log-hygiene, không phải
  bảo mật, và nằm ngoài phạm vi P0 theo mục XX. Thay vào đó, `installWebAppDebugLogMaintenanceTrigger()`
  /`removeWebAppDebugLogMaintenanceTrigger()` chỉ cài một trigger tối giản
  (`executeWebAppDebugLogMaintenance_`) giới hạn `WEBAPP_DEBUG_LOG` dưới 5000 dòng bằng cách xóa
  block dòng cũ nhất — không có archive CSV/Drive, không có phân loại theo tier.
- `Dashboard/index.html` chưa gọi kiểm tra session admin **chủ động** khi tải trang (chỉ phát
  hiện phản ứng khi 1 action ghi dữ liệu bị từ chối `ADMIN_SESSION_REQUIRED`) — nghĩa là nếu
  session hết hạn trong lúc không thao tác gì, giao diện admin có thể vẫn hiển thị "đã mở khóa"
  cho tới lần thao tác ghi tiếp theo. Không phải lỗ hổng bảo mật (backend vẫn chặn đúng), chỉ là
  trải nghiệm chưa tối ưu.
- `redactSensitiveData_`/`sanitizeDebugLogData_` chỉ redact theo **tên field**, không quét nội
  dung chuỗi tự do (ví dụ `err.stack` ghi server-side có thể vô tình chứa một giá trị nhạy cảm
  nằm trong text thay vì nằm trong 1 field riêng — rủi ro thấp, chỉ ảnh hưởng log server-side).
- Việc "gỡ" `logs/pipeline_*.log` khỏi Git (mục 8) và điều tra file bị xóa ngoài ý muốn
  (`pipeline_20260513_081029.log`) cần người quản trị xác nhận thủ công, chưa tự thực hiện.

## 11. Hướng dẫn rollback

Xem `SECURITY.md` mục 8. Tóm tắt nhanh cho riêng nhánh này:

- Chưa có gì được commit trong phiên P0 này → rollback = không commit / `git restore <file>` cho
  từng file muốn hoàn tác, hoặc `git checkout security/p0-hardening -- .` để bỏ toàn bộ thay đổi
  P0 còn ở working tree (**cẩn thận**: lệnh này cũng sẽ khôi phục lại file log đã bị xóa ngoài ý
  muốn ở mục 8, hãy kiểm tra `git status` trước).
- Sau khi đã deploy (ngoài phạm vi phiên này): dùng "Manage deployments" của Apps Script để quay
  lại version trước, "Instant Rollback" trên Vercel cho frontend.

## 12. Checklist review trước commit

- [ ] Đã đọc kỹ `git diff` cho từng file (`apps_script/WebApp.js`, `apps_script/Security.js`,
      `Dashboard/index.html`, `planner_sync_server.py`, `planner_sync_security.py`).
- [ ] Đã chạy `python scripts/generate_p0_secrets.py` và điền đủ Script Properties +
      `.env` theo `P0_MANUAL_ACTIONS.md` (mục 4a: `installP0ScriptPropertyDefaults` rồi
      `auditP0ScriptProperties` phải trả `ok: true`) trên môi trường **test** trước, xác nhận
      đăng nhập admin + transfer/update + Planner sync hoạt động đúng.
- [ ] Đã xác nhận KHÔNG có secret thật nào trong diff (đặc biệt `.env.example`,
      `.github/workflows/security.yml`).
- [ ] Đã quyết định có `git rm --cached` các file log ở mục 8 hay không.
- [ ] Đã điều tra file `logs/pipeline_20260513_081029.log` bị xóa ngoài ý muốn (mục 8) — xác
      nhận đây là hành vi dọn log bình thường của pipeline, hay cần khôi phục.
- [ ] Đã kiểm tra `apps_script/MultiSelectSidebar.html` — nếu đây là source hợp lệ đã bị mất do
      nguyên nhân khác (không phải do phiên P0 này), cần khôi phục riêng, không liên quan P0.
- [ ] Chỉ `git add` từng file cụ thể (không `git add -A`/`git add .`), review `git diff --cached`
      lần cuối trước khi commit.
- [ ] Không commit `.env`, `logs/`, `output/`, `auth/`, `credentials/`,
      `config/browser_session*.json`, token cache, `.pyc`, `__pycache__/`.

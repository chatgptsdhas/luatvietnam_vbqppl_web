"""
Static checks cho P0 security hardening — quét mã nguồn để đảm bảo các bất biến bảo mật
KHÔNG bị hồi quy trong tương lai (không cần chạy Apps Script/Planner Server thật).

Chạy:
    python -m unittest discover -s tests -p "test_*.py"
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
WEBAPP_JS = PROJECT_DIR / "apps_script" / "WebApp.js"
SECURITY_JS = PROJECT_DIR / "apps_script" / "Security.js"
DASHBOARD_HTML = PROJECT_DIR / "Dashboard" / "index.html"
PLANNER_SYNC_SERVER_PY = PROJECT_DIR / "planner_sync_server.py"

# Giá trị lịch sử (đã bị xóa ở P0) — chỉ dùng để phát hiện hồi quy, KHÔNG phải secret đang dùng.
OLD_HARDCODED_TOKEN = "T2j_crJJ10h8RSuhPzJT4ERCF3jNfNHSVsAcw1LZXq0"
OLD_HARDCODED_PASSWORD = "HASEDU2019@"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestWebAppJsStaticChecks(unittest.TestCase):
    def setUp(self):
        self.src = read(WEBAPP_JS)

    def test_no_default_token_fallback(self):
        self.assertNotIn(OLD_HARDCODED_TOKEN, self.src, "Token cứng cũ không được còn xuất hiện trong WebApp.js")
        self.assertNotIn("defaultToken", self.src, "setupWebAppToken không được còn khái niệm defaultToken")

    def test_no_plaintext_admin_password(self):
        self.assertNotIn(OLD_HARDCODED_PASSWORD, self.src)
        self.assertNotIn("REAL_PASSWORD", self.src)

    def test_no_predictable_authorized_session_token(self):
        self.assertNotIn('"AUTHORIZED_"', self.src)

    def test_verify_admin_uses_security_module(self):
        self.assertIn("verifyAdminPassword_(", self.src)
        self.assertIn("createAdminSession_(", self.src)

    def test_client_error_response_never_includes_stack_field(self):
        # Chỉ cho phép "stack: err.stack" xuất hiện bên trong lệnh gọi appendDebugLog_ (server-side).
        for match in re.finditer(r"stack:\s*err\.stack", self.src):
            window_start = max(0, match.start() - 200)
            preceding = self.src[window_start:match.start()]
            self.assertIn(
                "appendDebugLog_(", preceding,
                "Mọi 'stack: err.stack' phải nằm trong appendDebugLog_ (server-side), không được lộ ra client",
            )

    def test_jsonresponse_return_stack_removed_from_catch(self):
        self.assertNotIn("jsonResponse_({ ok: false, error: err.name || 'ERROR', message: err.message || String(err), stack: err.stack || '' })", self.src)

    def test_write_actions_require_admin_session(self):
        self.assertIn("requireAdminSession_(request)", self.src)
        self.assertIn("transfer_record: 'C'", self.src)
        self.assertIn("update_record: 'C'", self.src)

    def test_service_actions_require_service_token(self):
        self.assertIn("validateServiceToken_(", self.src)
        self.assertIn("import_vbqppl_nhap: 'B'", self.src)

    def test_admin_password_logging_key_is_redacted(self):
        # verify_admin nhận payload.password nhưng KHÔNG được có đường log riêng nào in ra password.
        self.assertNotIn("console.log(inputPass", self.src)
        self.assertNotIn("Logger.log(inputPass", self.src)

    def test_p0_property_management_functions_not_exposed_via_doPost(self):
        # 3 hàm quản lý Script Properties chỉ được chạy thủ công trong Apps Script Editor — WebApp.js
        # (nơi định nghĩa doPost/switch action) không được nhắc tới tên chúng dưới bất kỳ hình thức
        # nào, nghĩa là không có case nào trong doPost có thể gọi tới.
        for fn_name in ("installP0ScriptPropertyDefaults", "auditP0ScriptProperties", "runAuditP0ScriptProperties", "requireP0ScriptProperties_",):
            with self.subTest(function=fn_name):
                self.assertNotIn(fn_name, self.src)


class TestSecurityJsStaticChecks(unittest.TestCase):
    def setUp(self):
        self.src = read(SECURITY_JS)

    def test_no_hardcoded_secrets(self):
        self.assertNotIn(OLD_HARDCODED_TOKEN, self.src)
        self.assertNotIn(OLD_HARDCODED_PASSWORD, self.src)

    def test_required_functions_present(self):
        required_functions = [
            "getRequiredScriptProperty_", "getOptionalScriptProperty_", "constantTimeEquals_",
            "validateServiceToken_", "verifyAdminPassword_", "createAdminSession_",
            "validateAdminSession_", "requireAdminSession_", "redactSensitiveData_",
            "sanitizeErrorForClient_", "generateCorrelationId_", "createPlannerSyncEnvelope_",
        ]
        for fn in required_functions:
            with self.subTest(function=fn):
                self.assertIn(f"function {fn}(", self.src)

    def test_redact_key_list_covers_required_keys(self):
        required_keys = [
            "password", "token", "secret", "session", "cookie", "authorization",
            "signature", "access_token", "refresh_token",
        ]
        for key in required_keys:
            with self.subTest(key=key):
                self.assertIn(f"'{key}'", self.src)

    def test_no_service_token_fallback_to_legacy_token(self):
        # validateServiceToken_ KHÔNG được còn đường nào chấp nhận APPS_SCRIPT_TOKEN (token công
        # khai) thay cho APPS_SCRIPT_SERVICE_TOKEN — đã xóa dứt điểm theo yêu cầu hardening tiếp.
        self.assertNotIn("legacy_token_fallback", self.src)
        self.assertNotIn("getRequiredScriptProperty_('APPS_SCRIPT_TOKEN')", self.src)
        match = re.search(r"function validateServiceToken_\(.*?\n\}", self.src, re.S)
        self.assertIsNotNone(match, "Không tìm thấy function validateServiceToken_")
        body = match.group(0)
        # Thân hàm không được so sánh providedLegacyToken với bất kỳ token nào để cấp quyền.
        self.assertNotIn("constantTimeEquals_(providedLegacyToken", body)

    def test_session_ttl_default_900(self):
        self.assertIn("ADMIN_SESSION_TTL_SECONDS", self.src)
        self.assertIn("'900'", self.src)

    def test_p0_script_property_schema_covers_all_10_properties(self):
        required_keys = [
            "APPS_SCRIPT_TOKEN", "APPS_SCRIPT_SERVICE_TOKEN", "ADMIN_PASSWORD_SALT",
            "ADMIN_PASSWORD_HASH", "ADMIN_PASSWORD_ITERATIONS", "ADMIN_SESSION_SECRET",
            "ADMIN_SESSION_TTL_SECONDS", "PLANNER_SYNC_SHARED_SECRET",
            "PLANNER_SYNC_REQUEST_TTL_SECONDS", "WEBAPP_LOG_VERBOSE_DEBUG",
        ]
        self.assertIn("P0_SCRIPT_PROPERTY_SCHEMA_", self.src)
        match = re.search(r"P0_SCRIPT_PROPERTY_SCHEMA_\s*=\s*\{.*?\n\};", self.src, re.S)
        self.assertIsNotNone(match, "Không tìm thấy khai báo P0_SCRIPT_PROPERTY_SCHEMA_")
        body = match.group(0)
        for key in required_keys:
            with self.subTest(key=key):
                self.assertIn(key, body)

    def test_p0_property_management_functions_present_with_correct_visibility(self):
        # Public (không dấu gạch dưới ở cuối) — được phép chạy thủ công trong Apps Script Editor.
        self.assertIn("function installP0ScriptPropertyDefaults()", self.src)
        self.assertIn("function auditP0ScriptProperties()", self.src)
        # Private (dấu gạch dưới ở cuối theo quy ước file này).
        self.assertIn("function requireP0ScriptProperties_()", self.src)

    def test_install_never_sets_secret_properties_directly(self):
        # install chỉ được set qua vòng lặp theo schema (schema.defaultValue), không được có bất kỳ
        # lệnh setProperty('<SECRET_KEY>', ...) hardcode nào cho 6 secret bắt buộc.
        secret_keys = [
            "APPS_SCRIPT_TOKEN", "APPS_SCRIPT_SERVICE_TOKEN", "ADMIN_PASSWORD_SALT",
            "ADMIN_PASSWORD_HASH", "ADMIN_SESSION_SECRET", "PLANNER_SYNC_SHARED_SECRET",
        ]
        for key in secret_keys:
            with self.subTest(key=key):
                self.assertNotIn(f"setProperty('{key}'", self.src)
                self.assertNotIn(f'setProperty("{key}"', self.src)

    def test_audit_and_require_do_not_return_raw_property_values(self):
        match = re.search(r"function auditP0ScriptProperties\(\)\s*\{.*?\n\}", self.src, re.S)
        self.assertIsNotNone(match, "Không tìm thấy function auditP0ScriptProperties")
        body = match.group(0)
        # Không được trả field "value"/"values" chứa giá trị thật của property.
        self.assertNotIn("value:", body)
        self.assertNotIn("values:", body)


class TestDashboardFrontendStaticChecks(unittest.TestCase):
    def setUp(self):
        self.src = read(DASHBOARD_HTML)

    def test_no_planner_shared_secret_in_frontend(self):
        self.assertNotIn("PLANNER_SYNC_SHARED_SECRET", self.src)

    def test_no_apps_script_service_token_in_frontend(self):
        self.assertNotIn("APPS_SCRIPT_SERVICE_TOKEN", self.src)

    def test_no_plaintext_admin_password_in_frontend(self):
        self.assertNotIn(OLD_HARDCODED_PASSWORD, self.src)

    def test_admin_flag_not_used_as_sole_authorization(self):
        # localStorage.isAdminAccess không còn được ĐỌC trực tiếp để quyết định quyền —
        # chỉ còn xuất hiện trong danh sách dọn dẹp legacy khi logout.
        self.assertNotIn("localStorage.getItem('isAdminAccess')", self.src)

    def test_admin_session_stored_in_sessionstorage(self):
        self.assertIn("sessionStorage.setItem(ADMIN_SESSION_STORAGE_KEY", self.src)
        self.assertIn("sessionStorage.getItem(ADMIN_SESSION_STORAGE_KEY", self.src)

    def test_write_actions_attach_admin_session(self):
        self.assertIn("withAdminSession(", self.src)
        write_action_count = self.src.count("withAdminSession(")
        self.assertGreaterEqual(write_action_count, 8, "Phải có ít nhất 8 chỗ đính kèm admin_session cho action ghi dữ liệu")

    def test_planner_sync_uses_signed_local_envelope(self):
        self.assertIn('const WEBAPP_URL = "/api/webapp"', self.src)
        self.assertIn("fetchPlannerSyncEnvelope_('/sync-webapp-to-planner'", self.src)
        self.assertIn("fetchPlannerSyncEnvelope_('/delete-planner-task'", self.src)
        self.assertIn("X-P0-Signature", self.src)
        self.assertIn("127.0.0.1:8765", self.src)
        self.assertNotIn("transferAndCreatePlannerTask(", self.src)
        self.assertNotIn("/api/transfer-and-create-planner", self.src)
        self.assertNotIn("/api/delete-planner-task", self.src)

    def test_planner_browser_client_has_no_microsoft_credentials(self):
        self.assertNotIn("MS_GRAPH_CLIENT_SECRET", self.src)
        self.assertNotIn("client_credentials", self.src)

    def test_no_stack_trace_rendered_in_ui(self):
        self.assertNotIn("result.stack", self.src)

    def test_no_sensitive_console_log_of_session_or_password(self):
        self.assertNotIn("console.log(\"Kết quả xác thực:\", result)", self.src)

    def test_deleted_planner_task_is_not_rendered_or_restored_as_active(self):
        self.assertIn("function isDeletedPlannerTaskStatus(status)", self.src)
        self.assertIn("return !isDeletedPlannerTaskStatus(row?.['Planner Sync Status']);", self.src)
        self.assertIn("const plannerTaskUrl = plannerTaskDeleted\n            ? ''", self.src)
        self.assertIn("Task Planner đã bị xóa", self.src)
        self.assertIn("const plannerOptionHtml = plannerTaskId && !plannerTaskDeleted", self.src)
        self.assertIn("deletePlannerTask: !plannerTaskDeleted && shouldDeletePlannerTask", self.src)
        self.assertIn("if (deletePlannerTask && !plannerTaskDeleted)", self.src)

    def test_transfer_modal_resets_save_button_and_department_state_from_record(self):
        open_modal = self.src.split("function openModal(rowNum, isTransfer = false) {", 1)[1].split(
            "async function saveEdit()", 1
        )[0]
        self.assertIn("const btnSave = document.getElementById('btnSaveEdit');", open_modal)
        self.assertIn("btnSave.disabled = false;", open_modal)
        self.assertLess(
            open_modal.index("btnSave.disabled = false;"),
            open_modal.index("if (isTransferMode) {"),
        )
        self.assertIn(
            "danhSachBoPhanDaChon = parseBoPhanDaChon(rowData['Bộ phận chủ trì']);",
            open_modal,
        )
        self.assertIn("capNhatGiaoDienBoPhan();", open_modal)
        self.assertNotIn("document.getElementById('editBoPhan').value =", open_modal)
        self.assertIn("function parseBoPhanDaChon(chuoiBoPhan)", self.src)
        self.assertIn(".filter(Boolean)", self.src)
        self.assertIn("new Set(", self.src)

    def test_save_edit_reenables_button_after_admin_session_response(self):
        save_edit = self.src.split("async function saveEdit() {", 1)[1].split(
            "// =====================================================================\n    // HÀM transferRow", 1
        )[0]
        self.assertIn("if (handleAdminSessionResponse(result)) return;", save_edit)
        self.assertRegex(save_edit, r"finally\s*\{\s*btnSave\.disabled = false;")


class TestPlannerSyncServerStaticChecks(unittest.TestCase):
    def setUp(self):
        self.src = read(PLANNER_SYNC_SERVER_PY)

    def test_no_null_in_default_allowed_origins(self):
        match = re.search(r"DEFAULT_ALLOWED_ORIGINS\s*=\s*\((.*?)\)", self.src, re.S)
        self.assertIsNotNone(match, "Không tìm thấy DEFAULT_ALLOWED_ORIGINS")
        origins_block = match.group(1)
        self.assertNotIn('"null,"', origins_block)
        self.assertNotIn("'null,'", origins_block)

    def test_no_default_shared_secret(self):
        self.assertNotIn('PLANNER_SYNC_SHARED_SECRET", "', self.src.replace(" ", ""))
        # get_shared_secret() phải trả "" mặc định, không phải chuỗi bí mật cố định nào khác.
        self.assertIn('os.getenv("PLANNER_SYNC_SHARED_SECRET", "")', self.src)

    def test_hmac_verification_integrated(self):
        self.assertIn("from planner_sync_security import", self.src)
        self.assertIn("verify_signed_request(", self.src)
        self.assertIn("verify_request(", self.src)

    def test_health_endpoint_does_not_leak_endpoint_list(self):
        health_match = re.search(r"def do_GET.*?(?=\n    def )", self.src, re.S)
        self.assertIsNotNone(health_match)
        health_body = health_match.group(0)
        self.assertNotIn("sync_endpoint", health_body)
        self.assertNotIn("delete_endpoint", health_body)

    def test_no_origin_alone_does_not_bypass_auth(self):
        # is_origin_allowed(None) phải là False (không còn "if not origin: return True").
        self.assertIn("if not origin:\n        return False", self.src)

    def test_server_rejects_non_loopback_bind_override(self):
        self.assertIn("if args.host != DEFAULT_HOST:", self.src)
        self.assertIn("localhost-only", self.src)


class TestVercelProxyStaticChecks(unittest.TestCase):
    def test_webapp_allows_only_admin_envelope_and_still_blocks_service_actions(self):
        src = read(PROJECT_DIR / "api" / "webapp.py")
        self.assertIn("if action in SERVICE_ONLY_ACTIONS:", src)
        self.assertNotIn('or action == "request_planner_sync_envelope"', src)
        self.assertIn("if action in ADMIN_ACTIONS and not admin_session:", src)

    def test_vercel_has_no_graph_application_backend(self):
        backend = read(PROJECT_DIR / "api" / "_planner_backend.py")
        self.assertNotIn("MS_GRAPH_CLIENT_SECRET", backend)
        self.assertNotIn("client_credentials", backend)
        self.assertNotIn("GraphPlannerClient", backend)
        self.assertFalse((PROJECT_DIR / "api" / "transfer-and-create-planner.py").exists())
        self.assertFalse((PROJECT_DIR / "api" / "delete-planner-task.py").exists())


class TestPythonServiceScriptsSendServiceToken(unittest.TestCase):
    """
    Xác nhận các script Python gọi action nhóm B (service — import_vbqppl_nhap,
    update_vbqppl_record) gửi kèm service_token lấy từ APPS_SCRIPT_SERVICE_TOKEN, vì
    Security.js::validateServiceToken_ không còn fallback về APPS_SCRIPT_TOKEN nữa — thiếu
    service_token là các script này sẽ luôn bị từ chối SERVICE_TOKEN_INVALID.
    """

    SCRIPTS_CALLING_SERVICE_ACTION = [
        PROJECT_DIR / "08_process_field_documents_batch.py",
        PROJECT_DIR / "11_sync_webapp_to_planner.py",
        PROJECT_DIR / "12_sync_planner_to_webapp.py",
    ]

    def test_each_script_reads_and_sends_service_token(self):
        for path in self.SCRIPTS_CALLING_SERVICE_ACTION:
            with self.subTest(file=path.name):
                src = read(path)
                self.assertIn(
                    "APPS_SCRIPT_SERVICE_TOKEN", src,
                    f"{path.name} gọi action nhóm B nhưng không đọc APPS_SCRIPT_SERVICE_TOKEN",
                )
                self.assertIn(
                    '"service_token"', src,
                    f"{path.name} không gửi field service_token trong body request",
                )

    def test_service_token_not_silently_optional_in_shared_helper(self):
        # Ở 08: bắt buộc qua kiểm tra "if not service_token: return {...}".
        src_08 = read(PROJECT_DIR / "08_process_field_documents_batch.py")
        self.assertIn("if not service_token:", src_08)

        # Ở 11 và 12: bắt buộc qua get_required_env (raise nếu thiếu), không phải get_optional_env.
        for filename in ("11_sync_webapp_to_planner.py", "12_sync_planner_to_webapp.py"):
            with self.subTest(file=filename):
                src = read(PROJECT_DIR / filename)
                self.assertIn('get_required_env("APPS_SCRIPT_SERVICE_TOKEN")', src)


if __name__ == "__main__":
    unittest.main()

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

    def test_planner_sync_uses_signed_envelope_not_raw_payload(self):
        self.assertIn("fetchPlannerSyncEnvelope_(", self.src)
        self.assertIn("X-P0-Signature", self.src)

    def test_no_stack_trace_rendered_in_ui(self):
        self.assertNotIn("result.stack", self.src)

    def test_no_sensitive_console_log_of_session_or_password(self):
        self.assertNotIn("console.log(\"Kết quả xác thực:\", result)", self.src)


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

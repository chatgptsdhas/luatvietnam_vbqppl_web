"""
Test cho P0 security hardening — planner_sync_security.py (HMAC request signing/verification)
và tích hợp HTTP thật trong planner_sync_server.py.

Chạy:
    python -m unittest discover -s tests -p "test_*.py"
    python -m pytest tests/test_planner_sync_security.py -q

KHÔNG dùng secret production — mọi secret trong file này chỉ là giá trị test cục bộ.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from planner_sync_security import (  # noqa: E402
    ReplayCache,
    SecurityValidationError,
    build_canonical_request,
    calculate_body_hash,
    sign_request,
    verify_request,
)

TEST_SECRET = "unit-test-shared-secret-do-not-use-in-prod"
TEST_PATH = "/sync-webapp-to-planner"


def make_headers(timestamp: str, request_id: str, signature: str) -> dict:
    return {"X-P0-Timestamp": timestamp, "X-P0-Request-Id": request_id, "X-P0-Signature": signature}


def build_signed_headers(path: str, body: bytes, secret: str = TEST_SECRET, timestamp: float | None = None, request_id: str | None = None) -> dict:
    ts = str(int(timestamp if timestamp is not None else time.time()))
    rid = request_id or uuid.uuid4().hex
    sig = sign_request(ts, rid, path, body, secret)
    return make_headers(ts, rid, sig)


class TestCanonicalAndSigning(unittest.TestCase):
    def test_calculate_body_hash_matches_hashlib(self):
        import hashlib

        body = b'{"so_hieu":"12/2026/TT-BNV"}'
        self.assertEqual(calculate_body_hash(body), hashlib.sha256(body).hexdigest())

    def test_build_canonical_request_format(self):
        canonical = build_canonical_request("1700000000", "req-1", "/sync-webapp-to-planner", b"{}")
        parts = canonical.split("\n")
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0], "1700000000")
        self.assertEqual(parts[1], "req-1")
        self.assertEqual(parts[2], "/sync-webapp-to-planner")
        self.assertEqual(len(parts[3]), 64)  # sha256 hex digest length

    def test_sign_request_deterministic(self):
        sig1 = sign_request("1700000000", "req-1", TEST_PATH, b"{}", TEST_SECRET)
        sig2 = sign_request("1700000000", "req-1", TEST_PATH, b"{}", TEST_SECRET)
        self.assertEqual(sig1, sig2)

    def test_sign_request_changes_with_secret(self):
        sig1 = sign_request("1700000000", "req-1", TEST_PATH, b"{}", "secret-a")
        sig2 = sign_request("1700000000", "req-1", TEST_PATH, b"{}", "secret-b")
        self.assertNotEqual(sig1, sig2)


class TestVerifyRequest(unittest.TestCase):
    def setUp(self):
        self.cache = ReplayCache(ttl_seconds=300)
        self.body = b'{"so_hieu":"12/2026/TT-BNV","limit":1}'

    # 1. Signature hợp lệ
    def test_valid_signature_passes(self):
        headers = build_signed_headers(TEST_PATH, self.body)
        verify_request(
            headers=headers, path=TEST_PATH, raw_body=self.body, secret=TEST_SECRET,
            replay_cache=self.cache, max_body_bytes=1_000_000, ttl_seconds=300,
        )  # không raise nghĩa là pass

    # 2. Thiếu signature (thiếu từng header một)
    def test_missing_signature_header_rejected(self):
        headers = build_signed_headers(TEST_PATH, self.body)
        for missing_key in ("X-P0-Timestamp", "X-P0-Request-Id", "X-P0-Signature"):
            with self.subTest(missing=missing_key):
                partial = dict(headers)
                del partial[missing_key]
                with self.assertRaises(SecurityValidationError) as ctx:
                    verify_request(
                        headers=partial, path=TEST_PATH, raw_body=self.body, secret=TEST_SECRET,
                        replay_cache=ReplayCache(300), max_body_bytes=1_000_000, ttl_seconds=300,
                    )
                self.assertEqual(ctx.exception.code, "MISSING_SIGNATURE_HEADERS")
                self.assertEqual(ctx.exception.status_code, 401)

    # 3. Sai secret
    def test_wrong_secret_rejected(self):
        headers = build_signed_headers(TEST_PATH, self.body, secret=TEST_SECRET)
        with self.assertRaises(SecurityValidationError) as ctx:
            verify_request(
                headers=headers, path=TEST_PATH, raw_body=self.body, secret="a-completely-different-secret",
                replay_cache=self.cache, max_body_bytes=1_000_000, ttl_seconds=300,
            )
        self.assertEqual(ctx.exception.code, "SIGNATURE_INVALID")
        self.assertEqual(ctx.exception.status_code, 401)

    # 4. Body bị sửa sau khi ký
    def test_tampered_body_rejected(self):
        headers = build_signed_headers(TEST_PATH, self.body)
        tampered_body = self.body.replace(b"12/2026", b"99/2099")
        with self.assertRaises(SecurityValidationError) as ctx:
            verify_request(
                headers=headers, path=TEST_PATH, raw_body=tampered_body, secret=TEST_SECRET,
                replay_cache=self.cache, max_body_bytes=1_000_000, ttl_seconds=300,
            )
        self.assertEqual(ctx.exception.code, "SIGNATURE_INVALID")

    # 5. Timestamp hết hạn
    def test_expired_timestamp_rejected(self):
        old_ts = time.time() - 3600
        headers = build_signed_headers(TEST_PATH, self.body, timestamp=old_ts)
        with self.assertRaises(SecurityValidationError) as ctx:
            verify_request(
                headers=headers, path=TEST_PATH, raw_body=self.body, secret=TEST_SECRET,
                replay_cache=self.cache, max_body_bytes=1_000_000, ttl_seconds=300,
            )
        self.assertEqual(ctx.exception.code, "TIMESTAMP_EXPIRED")
        self.assertEqual(ctx.exception.status_code, 401)

    # 6. Timestamp tương lai quá mức
    def test_future_timestamp_rejected(self):
        future_ts = time.time() + 600
        headers = build_signed_headers(TEST_PATH, self.body, timestamp=future_ts)
        with self.assertRaises(SecurityValidationError) as ctx:
            verify_request(
                headers=headers, path=TEST_PATH, raw_body=self.body, secret=TEST_SECRET,
                replay_cache=self.cache, max_body_bytes=1_000_000, ttl_seconds=300, max_future_skew_seconds=30,
            )
        self.assertEqual(ctx.exception.code, "TIMESTAMP_FUTURE")

    # 7. Request ID replay
    def test_replayed_request_id_rejected(self):
        headers = build_signed_headers(TEST_PATH, self.body, request_id="fixed-request-id")
        verify_request(
            headers=headers, path=TEST_PATH, raw_body=self.body, secret=TEST_SECRET,
            replay_cache=self.cache, max_body_bytes=1_000_000, ttl_seconds=300,
        )
        with self.assertRaises(SecurityValidationError) as ctx:
            verify_request(
                headers=headers, path=TEST_PATH, raw_body=self.body, secret=TEST_SECRET,
                replay_cache=self.cache, max_body_bytes=1_000_000, ttl_seconds=300,
            )
        self.assertEqual(ctx.exception.code, "REPLAY_DETECTED")
        self.assertEqual(ctx.exception.status_code, 409)

    # 8. Request ID khác được chấp nhận
    def test_different_request_id_accepted(self):
        headers1 = build_signed_headers(TEST_PATH, self.body, request_id="req-a")
        headers2 = build_signed_headers(TEST_PATH, self.body, request_id="req-b")
        verify_request(
            headers=headers1, path=TEST_PATH, raw_body=self.body, secret=TEST_SECRET,
            replay_cache=self.cache, max_body_bytes=1_000_000, ttl_seconds=300,
        )
        verify_request(
            headers=headers2, path=TEST_PATH, raw_body=self.body, secret=TEST_SECRET,
            replay_cache=self.cache, max_body_bytes=1_000_000, ttl_seconds=300,
        )  # không raise nghĩa là request_id khác nhau đều được chấp nhận

    # 9. Body vượt giới hạn
    def test_body_too_large_rejected(self):
        big_body = b"x" * 2000
        headers = build_signed_headers(TEST_PATH, big_body)
        with self.assertRaises(SecurityValidationError) as ctx:
            verify_request(
                headers=headers, path=TEST_PATH, raw_body=big_body, secret=TEST_SECRET,
                replay_cache=self.cache, max_body_bytes=1000, ttl_seconds=300,
            )
        self.assertEqual(ctx.exception.code, "BODY_TOO_LARGE")
        self.assertEqual(ctx.exception.status_code, 413)

    def test_invalid_timestamp_format_rejected(self):
        headers = make_headers("not-a-number", "req-x", "deadbeef")
        with self.assertRaises(SecurityValidationError) as ctx:
            verify_request(
                headers=headers, path=TEST_PATH, raw_body=self.body, secret=TEST_SECRET,
                replay_cache=self.cache, max_body_bytes=1_000_000, ttl_seconds=300,
            )
        self.assertEqual(ctx.exception.code, "INVALID_TIMESTAMP")
        self.assertEqual(ctx.exception.status_code, 400)


# 11. Thread safety của ReplayCache
class TestReplayCacheThreadSafety(unittest.TestCase):
    def test_concurrent_same_request_id_only_accepted_once(self):
        cache = ReplayCache(ttl_seconds=300)
        request_id = "concurrent-request-id"
        results = []
        barrier = threading.Barrier(20)

        def worker():
            barrier.wait()
            results.append(cache.check_and_remember(request_id))

        with ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(lambda _: worker(), range(20)))

        self.assertEqual(sum(1 for r in results if r is True), 1, "chỉ đúng 1 thread được coi là request_id mới")
        self.assertEqual(sum(1 for r in results if r is False), 19)

    def test_concurrent_different_request_ids_all_accepted(self):
        cache = ReplayCache(ttl_seconds=300)
        results = []
        barrier = threading.Barrier(30)

        def worker(idx):
            barrier.wait()
            results.append(cache.check_and_remember(f"req-{idx}"))

        with ThreadPoolExecutor(max_workers=30) as pool:
            list(pool.map(worker, range(30)))

        self.assertTrue(all(results))
        self.assertEqual(len(cache), 30)

    def test_cleanup_expired_removes_old_entries(self):
        cache = ReplayCache(ttl_seconds=10)
        now = 1_000_000.0
        cache.check_and_remember("old-1", now=now - 100)
        cache.check_and_remember("old-2", now=now - 100)
        # check_and_remember tự dọn opportunistic ngay khi gọi tiếp — "old-1"/"old-2" đã quá
        # hạn 10s nên bị dọn NGAY trong lệnh insert "fresh-1" này (đúng theo thiết kế).
        cache.check_and_remember("fresh-1", now=now)
        self.assertEqual(len(cache), 1)

        # Gọi cleanup_expired tường minh khi không còn gì quá hạn -> trả về 0, không lỗi.
        removed = cache.cleanup_expired(now=now)
        self.assertEqual(removed, 0)
        self.assertEqual(len(cache), 1)

        # Dọn tường minh khi entry còn lại cũng đã quá hạn.
        removed_later = cache.cleanup_expired(now=now + 20)
        self.assertEqual(removed_later, 1)
        self.assertEqual(len(cache), 0)


@unittest.skipUnless(shutil.which("node"), "Node.js không có sẵn trong môi trường này — bỏ qua test cross-language")
class TestCrossLanguageEnvelopeCompat(unittest.TestCase):
    """
    Xác nhận chữ ký do apps_script/Security.js::createPlannerSyncEnvelope_ tạo ra (chạy thật
    qua Node.js) được planner_sync_security.verify_request CHẤP NHẬN — đây là bài test quan
    trọng nhất vì 2 phía (Apps Script và Planner Sync Server) độc lập triển khai cùng 1 công thức
    canonical message; nếu lệch dù 1 ký tự, toàn bộ luồng đồng bộ Planner sẽ không hoạt động.
    """

    def test_js_signed_envelope_is_accepted_by_python_verifier(self):
        secret = "cross-lang-shared-secret-test"
        node_script = r"""
const vm = require('vm');
const fs = require('fs');
const crypto = require('crypto');

const source = fs.readFileSync(process.argv[1], 'utf8');

function computeHmacSha256Signature(messageBytesOrStr, keyBytesOrStr) {
  const msgBuf = Array.isArray(messageBytesOrStr) ? Buffer.from(messageBytesOrStr.map(b => b < 0 ? b + 256 : b)) : Buffer.from(String(messageBytesOrStr), 'utf8');
  const keyBuf = Array.isArray(keyBytesOrStr) ? Buffer.from(keyBytesOrStr.map(b => b < 0 ? b + 256 : b)) : Buffer.from(String(keyBytesOrStr), 'utf8');
  const digest = crypto.createHmac('sha256', keyBuf).update(msgBuf).digest();
  return Array.from(digest).map(b => (b > 127 ? b - 256 : b));
}
function computeDigest(algorithm, messageStr) {
  const digest = crypto.createHash('sha256').update(Buffer.from(String(messageStr), 'utf8')).digest();
  return Array.from(digest).map(b => (b > 127 ? b - 256 : b));
}
const scriptProps = { PLANNER_SYNC_SHARED_SECRET: process.argv[2] };
const ctx = {
  console,
  Utilities: {
    newBlob(input) {
      const buf = Array.isArray(input) ? Buffer.from(input.map(b => (b < 0 ? b + 256 : b))) : Buffer.from(String(input), 'utf8');
      return { getBytes() { return Array.from(buf).map(b => (b > 127 ? b - 256 : b)); }, getDataAsString() { return buf.toString('utf8'); } };
    },
    computeHmacSha256Signature, computeDigest,
    DigestAlgorithm: { SHA_256: 'SHA_256' },
    getUuid() { return 'js-uuid-' + crypto.randomBytes(8).toString('hex'); },
    base64EncodeWebSafe(str) { return Buffer.from(String(str), 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_'); },
    base64DecodeWebSafe(str) {
      let s = String(str).replace(/-/g, '+').replace(/_/g, '/');
      return Array.from(Buffer.from(s, 'base64')).map(b => (b > 127 ? b - 256 : b));
    },
    Charset: { UTF_8: 'UTF_8' }
  },
  PropertiesService: { getScriptProperties() { return { getProperty(k) { return scriptProps[k] || null; } }; } }
};
ctx.global = ctx;
vm.createContext(ctx);
vm.runInContext(source, ctx, { filename: 'Security.js' });

const envelope = ctx.createPlannerSyncEnvelope_('/sync-webapp-to-planner', { so_hieu: '12/2026/TT-BNV', limit: 1 }, 300);
process.stdout.write(JSON.stringify(envelope));
"""
        security_js_path = str(PROJECT_DIR / "apps_script" / "Security.js")
        proc = subprocess.run(
            ["node", "-e", node_script, security_js_path, secret],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, f"Node script thất bại: {proc.stderr}")
        envelope = json.loads(proc.stdout)

        headers = make_headers(envelope["timestamp"], envelope["requestId"], envelope["signature"])
        raw_body = envelope["body"].encode("utf-8")

        # Không raise => Python chấp nhận chữ ký do Apps Script (JS) tạo ra.
        verify_request(
            headers=headers, path=envelope["path"], raw_body=raw_body, secret=secret,
            replay_cache=ReplayCache(300), max_body_bytes=1_000_000, ttl_seconds=300,
        )

        # Đối chứng thêm: sign_request phía Python phải tính RA CÙNG signature với JS.
        python_signature = sign_request(envelope["timestamp"], envelope["requestId"], envelope["path"], raw_body, secret)
        self.assertEqual(python_signature, envelope["signature"])


class TestLiveHttpServer(unittest.TestCase):
    """Kiểm thử tích hợp thật qua HTTP với planner_sync_server.PlannerSyncHandler."""

    @classmethod
    def setUpClass(cls):
        os.environ["PLANNER_SYNC_SHARED_SECRET"] = TEST_SECRET
        os.environ["PLANNER_SYNC_MAX_BODY_BYTES"] = "2000"
        os.environ["PLANNER_SYNC_REQUEST_TTL_SECONDS"] = "300"

        import planner_sync_server as pss
        cls.pss = pss

        # Không đụng tới business logic Planner/Sheet thật trong test — thay get_sync_module
        # bằng module giả để các request có chữ ký HỢP LỆ vẫn trả 200 mà không gọi Graph/Sheets.
        class FakeSyncModule:
            @staticmethod
            def sync_single_webapp_record_to_planner(row_number=None, so_hieu="", dry_run=False):
                return {"ok": True, "created_tasks": 1, "failed_records": 0}

            @staticmethod
            def sync_webapp_to_planner(limit=1, dry_run=False):
                return {"ok": True, "created_tasks": 0, "failed_records": 0}

        pss.sync_module = FakeSyncModule()

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), pss.PlannerSyncHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path: str, body: bytes, headers: dict, content_type: str = "application/json"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            full_headers = {"Content-Type": content_type, **headers}
            conn.request("POST", path, body=body, headers=full_headers)
            resp = conn.getresponse()
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, data
        finally:
            conn.close()

    def test_health_endpoint_minimal_fields_only(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()

        self.assertEqual(resp.status, 200)
        self.assertEqual(data.get("ok"), True)
        self.assertIn("service", data)
        self.assertIn("version", data)
        self.assertIn("server_time", data)
        # P0: /health không được liệt kê endpoint nhạy cảm nữa.
        self.assertNotIn("sync_endpoint", data)
        self.assertNotIn("delete_endpoint", data)

    def test_valid_signed_request_returns_200(self):
        body = json.dumps({"so_hieu": "12/2026/TT-BNV", "limit": 1}).encode("utf-8")
        headers = build_signed_headers(TEST_PATH, body)
        status, data = self._post(TEST_PATH, body, headers)
        self.assertEqual(status, 200, data)
        self.assertTrue(data.get("ok"))
        self.assertIn("correlationId", data)

    def test_missing_signature_returns_401(self):
        body = json.dumps({"so_hieu": "12/2026/TT-BNV"}).encode("utf-8")
        status, data = self._post(TEST_PATH, body, {})
        self.assertEqual(status, 401)
        self.assertEqual(data.get("error"), "MISSING_SIGNATURE_HEADERS")
        self.assertNotIn("stack", data)

    def test_wrong_content_type_returns_415(self):
        body = json.dumps({"so_hieu": "12/2026/TT-BNV"}).encode("utf-8")
        headers = build_signed_headers(TEST_PATH, body)
        status, data = self._post(TEST_PATH, body, headers, content_type="text/plain")
        self.assertEqual(status, 415)
        self.assertEqual(data.get("error"), "UNSUPPORTED_CONTENT_TYPE")

    def test_body_too_large_returns_413(self):
        body = json.dumps({"so_hieu": "x" * 3000}).encode("utf-8")
        headers = build_signed_headers(TEST_PATH, body)
        status, data = self._post(TEST_PATH, body, headers)
        self.assertEqual(status, 413)
        self.assertEqual(data.get("error"), "BODY_TOO_LARGE")

    def test_disallowed_origin_returns_403_even_with_valid_signature(self):
        body = json.dumps({"so_hieu": "12/2026/TT-BNV"}).encode("utf-8")
        headers = build_signed_headers(TEST_PATH, body)
        headers["Origin"] = "https://evil-attacker.example"
        status, data = self._post(TEST_PATH, body, headers)
        self.assertEqual(status, 403)
        self.assertEqual(data.get("error"), "ORIGIN_FORBIDDEN")

    def test_no_origin_request_still_requires_valid_signature(self):
        # Request KHÔNG có Origin (giống curl/script nội bộ) KHÔNG được miễn HMAC.
        body = json.dumps({"so_hieu": "12/2026/TT-BNV"}).encode("utf-8")
        status, data = self._post(TEST_PATH, body, {})  # không header ký -> phải bị chặn
        self.assertEqual(status, 401)

    def test_replay_returns_409(self):
        body = json.dumps({"so_hieu": "77/2026/TT-BNV"}).encode("utf-8")
        headers = build_signed_headers(TEST_PATH, body, request_id="replay-http-test")
        status1, data1 = self._post(TEST_PATH, body, headers)
        self.assertEqual(status1, 200, data1)
        status2, data2 = self._post(TEST_PATH, body, headers)
        self.assertEqual(status2, 409)
        self.assertEqual(data2.get("error"), "REPLAY_DETECTED")

    def test_error_response_never_contains_stack_field(self):
        status, data = self._post(TEST_PATH, b"not-json", {})
        self.assertNotIn("stack", data)


if __name__ == "__main__":
    unittest.main()

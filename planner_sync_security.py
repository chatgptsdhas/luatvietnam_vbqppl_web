"""
P0 security hardening — xác thực HMAC-SHA256 cho request gọi Planner Sync Server cục bộ
(planner_sync_server.py). Trước P0, server chỉ dựa vào CORS Origin header (dễ giả mạo từ
process không phải trình duyệt, và mặc định chấp nhận cả request không có Origin). Từ P0,
Apps Script (apps_script/Security.js::createPlannerSyncEnvelope_) ký sẵn một envelope ngắn
hạn cho Dashboard chuyển tiếp — module này xác thực chữ ký đó ở phía server.

QUAN TRỌNG: canonical message PHẢI khớp byte-for-byte với phía Apps Script:

    canonical = timestamp + "\\n" + request_id + "\\n" + path + "\\n" + sha256_hex(raw_body)
    signature = HMAC-SHA256(canonical, PLANNER_SYNC_SHARED_SECRET) dạng hex

Header bắt buộc trên mỗi request cần xác thực:
    X-P0-Timestamp    — epoch giây (chuỗi số)
    X-P0-Request-Id   — UUID duy nhất cho mỗi request (chống replay)
    X-P0-Signature    — hex HMAC-SHA256 theo canonical message ở trên

Chỉ dùng Python standard library.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from typing import Dict, Optional


class SecurityValidationError(Exception):
    """
    Lỗi xác thực request. `code` là mã lỗi ổn định (không đổi giữa các lần chạy) để caller
    ánh xạ sang HTTP status; `status_code` là gợi ý status HTTP mặc định cho lỗi đó.
    KHÔNG bao giờ đưa secret/signature vào message của exception này.
    """

    def __init__(self, code: str, message: str, status_code: int = 401):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def calculate_body_hash(raw_body: bytes) -> str:
    """SHA-256 hex digest của body thô (bytes), dùng làm 1 phần canonical message."""
    return hashlib.sha256(raw_body or b"").hexdigest()


def build_canonical_request(timestamp: str, request_id: str, path: str, raw_body: bytes) -> str:
    """
    Dựng canonical message để ký/xác thực. PHẢI khớp chính xác thứ tự và ký tự phân tách
    ("\\n") với apps_script/Security.js::createPlannerSyncEnvelope_.
    """
    body_hash = calculate_body_hash(raw_body)
    return f"{timestamp}\n{request_id}\n{path}\n{body_hash}"


def sign_request(timestamp: str, request_id: str, path: str, raw_body: bytes, secret: str) -> str:
    """HMAC-SHA256 (hex) của canonical message — dùng cả khi ký (test/tool) lẫn khi xác thực."""
    canonical = build_canonical_request(timestamp, request_id, path, raw_body)
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


class ReplayCache:
    """
    Lưu tạm các request_id đã xác thực thành công trong cửa sổ ttl_seconds để chặn replay.
    Thread-safe bằng threading.RLock (ThreadingHTTPServer xử lý request trên nhiều thread).
    """

    def __init__(self, ttl_seconds: int = 300):
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._lock = threading.RLock()
        self._seen: Dict[str, float] = {}

    def check_and_remember(self, request_id: str, now: Optional[float] = None) -> bool:
        """
        Trả True nếu request_id CHƯA từng thấy trong cửa sổ TTL (và ghi nhận lại ngay,
        atomic trong cùng 1 lock để tránh race condition giữa các thread).
        Trả False nếu request_id đã được dùng trước đó (replay).
        """
        now = now if now is not None else time.time()
        with self._lock:
            self._cleanup_locked(now)
            if request_id in self._seen:
                return False
            self._seen[request_id] = now
            return True

    def cleanup_expired(self, now: Optional[float] = None) -> int:
        """Dọn thủ công các request_id đã hết hạn TTL — trả về số lượng đã dọn."""
        now = now if now is not None else time.time()
        with self._lock:
            return self._cleanup_locked(now)

    def _cleanup_locked(self, now: float) -> int:
        expired_ids = [rid for rid, seen_at in self._seen.items() if (now - seen_at) > self._ttl_seconds]
        for rid in expired_ids:
            del self._seen[rid]
        return len(expired_ids)

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen)


def verify_request(
    *,
    headers: Dict[str, str],
    path: str,
    raw_body: bytes,
    secret: str,
    replay_cache: ReplayCache,
    max_body_bytes: int,
    ttl_seconds: int,
    max_future_skew_seconds: int = 30,
    now: Optional[float] = None,
) -> None:
    """
    Xác thực đầy đủ 1 request HTTP theo header X-P0-*. Không trả gì nếu hợp lệ; raise
    SecurityValidationError với code ổn định nếu không hợp lệ. KHÔNG log secret/signature
    ở đây — caller (planner_sync_server.py) cũng không được log các giá trị này.

    Thứ tự kiểm tra (dừng ở lỗi đầu tiên gặp phải):
      1) body không vượt max_body_bytes
      2) đủ 3 header X-P0-Timestamp / X-P0-Request-Id / X-P0-Signature
      3) timestamp parse được, chưa hết hạn (age <= ttl_seconds), không ở tương lai quá mức
      4) chữ ký khớp (hmac.compare_digest, constant-time)
      5) request_id chưa từng dùng (chống replay)
    """
    now = now if now is not None else time.time()

    if raw_body is not None and len(raw_body) > max_body_bytes:
        raise SecurityValidationError("BODY_TOO_LARGE", "Request body vượt giới hạn cho phép.", 413)

    timestamp = headers.get("X-P0-Timestamp")
    request_id = headers.get("X-P0-Request-Id")
    signature = headers.get("X-P0-Signature")

    if not timestamp or not request_id or not signature:
        raise SecurityValidationError(
            "MISSING_SIGNATURE_HEADERS",
            "Thiếu header X-P0-Timestamp / X-P0-Request-Id / X-P0-Signature.",
            401,
        )

    try:
        timestamp_value = float(timestamp)
    except (TypeError, ValueError):
        raise SecurityValidationError("INVALID_TIMESTAMP", "X-P0-Timestamp không hợp lệ.", 400)

    age_seconds = now - timestamp_value
    if age_seconds > ttl_seconds:
        raise SecurityValidationError("TIMESTAMP_EXPIRED", "Chữ ký đã hết hạn.", 401)
    if age_seconds < -max_future_skew_seconds:
        raise SecurityValidationError("TIMESTAMP_FUTURE", "Timestamp ở tương lai vượt ngưỡng cho phép.", 401)

    expected_signature = sign_request(timestamp, request_id, path, raw_body, secret)
    if not hmac.compare_digest(expected_signature, signature):
        raise SecurityValidationError("SIGNATURE_INVALID", "Chữ ký không hợp lệ.", 401)

    if not replay_cache.check_and_remember(request_id, now=now):
        raise SecurityValidationError("REPLAY_DETECTED", "Request ID đã được sử dụng trước đó.", 409)

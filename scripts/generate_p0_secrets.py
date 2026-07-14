"""
Sinh secret cho P0 security hardening (Apps Script service token, Planner Sync shared
secret, admin session secret, admin password salt/hash).

CHỈ dùng Python standard library — không cần cài thêm gói nào.

Cách chạy:

    python scripts/generate_p0_secrets.py
    python scripts/generate_p0_secrets.py --iterations 300000

Script KHÔNG tự ghi vào .env hoặc bất kỳ file nào — chỉ in ra màn hình để người quản trị
tự sao chép thủ công vào .env / Script Properties / password manager.

CẢNH BÁO: Output của script này (đặc biệt ADMIN_PASSWORD_HASH, ADMIN_PASSWORD_SALT và các
secret khác) KHÔNG ĐƯỢC lưu vào Git, chat (Slack/Teams/Zalo...), email, Word hoặc Excel.
Chỉ lưu trong password manager hoặc trực tiếp vào .env / Script Properties trên máy/server
được cấp quyền.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import secrets
import sys

DEFAULT_ITERATIONS = 210000
TOKEN_BYTES = 32
SALT_BYTES = 16


def _setup_utf8_stdio() -> None:
    # Console Windows mặc định dùng cp1252, không encode được tiếng Việt có dấu.
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_setup_utf8_stdio()


def generate_token(num_bytes: int = TOKEN_BYTES) -> str:
    return secrets.token_urlsafe(num_bytes)


def derive_password_hash(password: str, salt_bytes: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, iterations)


def prompt_admin_password() -> str:
    for attempt in range(3):
        password = getpass.getpass("Nhập mật khẩu admin mới: ")
        if not password:
            print("Mật khẩu rỗng, vui lòng nhập lại.", file=sys.stderr)
            continue

        confirm = getpass.getpass("Nhập lại mật khẩu admin để xác nhận: ")
        if password != confirm:
            print("Hai lần nhập không khớp, vui lòng thử lại.", file=sys.stderr)
            continue

        return password

    raise SystemExit("Nhập mật khẩu thất bại sau 3 lần thử. Dừng script.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sinh secret cho P0 security hardening (APPS_SCRIPT_SERVICE_TOKEN, "
        "PLANNER_SYNC_SHARED_SECRET, ADMIN_SESSION_SECRET, ADMIN_PASSWORD_SALT/HASH)."
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"Số vòng PBKDF2-HMAC-SHA256 cho mật khẩu admin (mặc định {DEFAULT_ITERATIONS}).",
    )
    parser.add_argument(
        "--skip-password",
        action="store_true",
        help="Bỏ qua bước nhập mật khẩu admin (chỉ sinh các token/secret ngẫu nhiên khác).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.iterations <= 0:
        raise SystemExit("--iterations phải là số nguyên dương.")

    print("=" * 78)
    print("SINH SECRET CHO P0 SECURITY HARDENING")
    print("=" * 78)
    print(
        "CẢNH BÁO: KHÔNG lưu output bên dưới vào Git, chat, email, Word hoặc Excel.\n"
        "Chỉ lưu trong password manager hoặc điền trực tiếp vào .env / Script Properties."
    )
    print("-" * 78)

    apps_script_service_token = generate_token()
    planner_sync_shared_secret = generate_token()
    admin_session_secret = generate_token()

    print("\n# Dán vào .env (local, KHÔNG commit) và Apps Script Script Properties tương ứng:\n")
    print(f"APPS_SCRIPT_SERVICE_TOKEN={apps_script_service_token}")
    print(f"PLANNER_SYNC_SHARED_SECRET={planner_sync_shared_secret}")
    print(f"ADMIN_SESSION_SECRET={admin_session_secret}")

    if args.skip_password:
        print(
            "\n(Đã bỏ qua bước sinh ADMIN_PASSWORD_SALT/ADMIN_PASSWORD_HASH theo --skip-password.)"
        )
        print(f"\nADMIN_PASSWORD_ITERATIONS={args.iterations}")
        return

    print("-" * 78)
    password = prompt_admin_password()

    salt_bytes = secrets.token_bytes(SALT_BYTES)
    salt_hex = salt_bytes.hex()
    password_hash_hex = derive_password_hash(password, salt_bytes, args.iterations).hex()

    # Xóa tham chiếu tới mật khẩu plaintext càng sớm càng tốt — không log/in ra bất kỳ đâu.
    password = "\x00" * len(password)
    del password

    print(f"\nADMIN_PASSWORD_SALT={salt_hex}")
    print(f"ADMIN_PASSWORD_HASH={password_hash_hex}")
    print(f"ADMIN_PASSWORD_ITERATIONS={args.iterations}")

    print("\n" + "=" * 78)
    print(
        "Nhắc lại: các giá trị trên là secret thật. KHÔNG dán vào Git, chat, email, Word, "
        "Excel. Chỉ lưu trong password manager hoặc .env / Script Properties."
    )
    print("=" * 78)


if __name__ == "__main__":
    main()

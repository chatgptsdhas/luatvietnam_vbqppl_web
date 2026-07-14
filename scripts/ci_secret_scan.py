"""
CI: quét sơ bộ các mẫu secret viết cứng phổ biến trong mã nguồn đang được Git track.

Đây KHÔNG phải một secret scanner chuyên dụng (không thay thế gitleaks/trufflehog...) — chỉ
là lưới an toàn tối thiểu cho P0, chạy trong .github/workflows/security.yml. Không cần
secret production để chạy; chỉ đọc nội dung file đã track trong Git.

QUAN TRỌNG: KHÔNG BAO GIỜ in đầy đủ giá trị nghi ngờ ra log CI (log CI có thể public trên
PR từ fork) — chỉ in file:line + nhãn + giá trị đã che (che >= 80%).
"""

from __future__ import annotations

import re
import subprocess
import sys


def _setup_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_setup_utf8_stdio()

PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", "Private key block"),
    (r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{20,}[\"']", "Chuỗi giống secret/token viết cứng (>=20 ký tự)"),
    (r"xox[baprs]-[0-9A-Za-z-]{10,}", "Slack token"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub personal access token"),
]

# Các cụm loại trừ đã được rà soát thủ công — KHÔNG phải secret thật hoặc là placeholder rỗng.
ALLOWLIST_SUBSTRINGS = [
    "os.getenv(",
    "process.env",
    "getScriptProperties",
    "getOptionalScriptProperty_",
    "getRequiredScriptProperty_",
    "PLACEHOLDER",
    "example",
    "unit-test",
    "dummy",
    "YOUR_",
    "sinh bằng scripts/generate_p0_secrets.py",
    # apps_script/Dashboard: TOKEN dự án (APPS_SCRIPT_TOKEN) vốn PHẢI nhúng vào frontend công
    # khai do kiến trúc Apps Script Web App (ANYONE_ANONYMOUS) — đã ghi trong SECURITY.md mục
    # "Giới hạn kiến trúc đã biết". Đây không phải secret mới phát sinh, không phải hồi quy.
    "const TOKEN =",
]

EXCLUDED_PATH_PREFIXES = ("tests/", ".git/", "node_modules/")


def redact(value: str) -> str:
    if len(value) <= 6:
        return "*" * len(value)
    visible = max(2, int(len(value) * 0.2))
    return value[:visible] + "*" * (len(value) - visible)


def list_tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line.strip()]


def main() -> int:
    findings = []
    scannable_suffixes = (".py", ".js", ".html", ".ps1", ".yml", ".yaml", ".json")

    for path in list_tracked_files():
        if path.startswith(EXCLUDED_PATH_PREFIXES):
            continue
        if not path.endswith(scannable_suffixes):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            continue

        for lineno, line in enumerate(lines, start=1):
            if any(allow in line for allow in ALLOWLIST_SUBSTRINGS):
                continue
            for pattern, label in PATTERNS:
                match = re.search(pattern, line)
                if match:
                    findings.append((path, lineno, label, redact(match.group(0))))

    if findings:
        print("Phát hiện mẫu nghi ngờ là secret viết cứng (giá trị đã được che):")
        for path, lineno, label, redacted in findings:
            print(f"  {path}:{lineno} [{label}] {redacted}")
        print(
            "\nNếu là false positive (chuỗi test/mẫu/placeholder), thêm cụm từ nhận diện vào "
            "ALLOWLIST_SUBSTRINGS trong scripts/ci_secret_scan.py kèm giải thích lý do."
        )
        return 1

    print("OK: không phát hiện mẫu secret viết cứng nào trong các file đang được Git track.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Script chan doan doc lap cho loi HTTPError 401 khi goi Apps Script WebApp.
KHONG dung chung logic voi 08_process_field_documents_batch.py, khong sua gi
trong pipeline chinh. Chi doc .env, goi thang APPS_SCRIPT_WEBAPP_URL bang
action "get_all_records", in ra status code + 500 ky tu dau response.
Chay 3 lan lien tiep cach nhau 2s de xem loi co nhat quan 100% hay ngau nhien.

Usage:
    python scripts/diagnose_apps_script_401.py
"""
from pathlib import Path
import json
import os
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def load_env_file(path: Path) -> dict:
    env = {}
    if not path.exists():
        print(f"[WARN] Khong tim thay {path}")
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env[key] = value
    return env


def mask(value: str, keep: int = 6) -> str:
    if not value:
        return "(empty)"
    return value[:keep] + "..." if len(value) > keep else value


def call_once(url: str, token: str, service_token: str, run_index: int):
    body = {
        "token": token,
        "service_token": service_token,
        "action": "get_all_records",
    }
    request_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=request_bytes,
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    print(f"\n=== Lan goi {run_index} ===")
    try:
        with urlopen(req, timeout=30) as res:
            status = res.status
            content = res.read().decode("utf-8", errors="replace")
        print(f"Status: {status}")
        print(f"Body (500 ky tu dau):\n{content[:500]}")
    except HTTPError as exc:
        content = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        print(f"Status: {exc.code} {exc.reason} (HTTPError)")
        print(f"Body (500 ky tu dau):\n{content[:500]}")
    except URLError as exc:
        print(f"URLError: {exc.reason}")


def main():
    env = load_env_file(ENV_FILE)
    url = env.get("APPS_SCRIPT_WEBAPP_URL", "") or os.getenv("APPS_SCRIPT_WEBAPP_URL", "")
    token = env.get("APPS_SCRIPT_TOKEN", "") or os.getenv("APPS_SCRIPT_TOKEN", "")
    service_token = env.get("APPS_SCRIPT_SERVICE_TOKEN", "") or os.getenv("APPS_SCRIPT_SERVICE_TOKEN", "")

    print(f"APPS_SCRIPT_WEBAPP_URL: {url or '(MISSING)'}")
    print(f"APPS_SCRIPT_TOKEN: {mask(token)}")
    print(f"APPS_SCRIPT_SERVICE_TOKEN: {mask(service_token)}")

    if not url:
        print("[ERROR] Thieu APPS_SCRIPT_WEBAPP_URL trong .env, dung lai.")
        return

    for i in range(1, 4):
        call_once(url, token, service_token, i)
        if i < 3:
            time.sleep(2)


if __name__ == "__main__":
    main()

"""
Lấy Microsoft Graph access token từ Graph Explorer (Playwright).
Thay thế MSAL Python khi tenant chặn OAuth flows.

Lần đầu: mở browser, đăng nhập legal@has.edu.vn, lưu session.
Lần sau: dùng session đã lưu, tự silent-refresh qua MSAL.js — không cần đăng nhập lại.

Yêu cầu: Graph Explorer phải được cấp quyền Tasks.ReadWrite, Group.Read.All
(Modify permissions → thêm scope → Accept).

    python get_token_browser.py
"""

import base64
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


def _setup_utf8() -> None:
    for s in ("stdout", "stderr"):
        stream = getattr(sys, s, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_setup_utf8()
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

load_dotenv()

GRAPH_EXPLORER_URL = "https://developer.microsoft.com/en-us/graph/graph-explorer"
BROWSER_SESSION_PATH = Path(os.getenv("BROWSER_SESSION_PATH", "config/browser_session.json"))
RUN_AS_EMAIL = os.getenv("PLANNER_RUN_AS_EMAIL", "legal@has.edu.vn")
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "true").strip().lower() not in {"0", "false", "no", "off"}
MIN_TOKEN_LIFETIME_SECONDS = 300
_token_cache: dict[str, str] = {}


def _get_session_path(login_hint: str) -> Path:
    if not login_hint or login_hint.lower().strip() == RUN_AS_EMAIL.lower().strip():
        return BROWSER_SESSION_PATH
    safe_name = login_hint.strip().replace("@", "_at_").replace(".", "_")
    return BROWSER_SESSION_PATH.parent / f"browser_session_{safe_name}.json"


def _is_valid_jwt(token: str) -> bool:
    """JWT hợp lệ bắt đầu bằng 'eyJ' và có ít nhất 2 dấu chấm."""
    return bool(token) and token.startswith("eyJ") and token.count(".") >= 2


def _decode_jwt_payload(token: str) -> dict:
    if not _is_valid_jwt(token):
        return {}
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}


def _get_jwt_exp(token: str) -> int:
    payload = _decode_jwt_payload(token)
    try:
        return int(payload.get("exp") or 0)
    except (TypeError, ValueError):
        return 0


def _token_has_min_lifetime(token: str) -> bool:
    exp = _get_jwt_exp(token)
    return bool(exp and exp - int(time.time()) > MIN_TOKEN_LIFETIME_SECONDS)


def _read_token_from_localstorage(page) -> str:
    """Đọc access token JWT chưa hết hạn từ MSAL.js cache trong localStorage."""
    return page.evaluate(
        """
        () => {
            const now = Math.floor(Date.now() / 1000);
            for (const k of Object.keys(localStorage)) {
                if (!k.toLowerCase().includes('accesstoken')) continue;
                try {
                    const v = JSON.parse(localStorage.getItem(k));
                    if (!v || v.credentialType !== 'AccessToken') continue;
                    const secret = v.secret || '';
                    // Chỉ lấy JWT hợp lệ (bắt đầu bằng eyJ)
                    if (!secret.startsWith('eyJ')) continue;
                    const exp = parseInt(v.expiresOn || v.extendedExpiresOn || '0', 10);
                    if (exp && exp - now <= 300) continue;
                    return secret;
                } catch {}
            }
            return null;
        }
    """
    ) or ""


def get_token(login_hint: str = "") -> str:
    """
    Trả về Microsoft Graph access token hợp lệ cho account chỉ định.
    Nếu login_hint rỗng hoặc là PLANNER_RUN_AS_EMAIL, dùng session mặc định.
    Mỗi account có session file riêng để refresh độc lập.
    """
    global _token_cache

    cache_key = login_hint.lower().strip()
    if _token_has_min_lifetime(_token_cache.get(cache_key, "")):
        return _token_cache[cache_key]

    session_path = _get_session_path(login_hint)
    display_account = login_hint.strip() if login_hint.strip() else RUN_AS_EMAIL
    captured: list[str] = []

    with sync_playwright() as p:
        storage_state = str(session_path) if session_path.exists() else None
        browser = p.chromium.launch(headless=BROWSER_HEADLESS)
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()

        def on_request(request):
            if captured:
                return
            if "graph.microsoft.com" in request.url:
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer "):
                    token_val = auth[7:]
                    if _token_has_min_lifetime(token_val):
                        captured.append(token_val)

        page.on("request", on_request)

        print(f"Mở Graph Explorer ({display_account})...")
        try:
            page.goto(GRAPH_EXPLORER_URL, wait_until="networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(3000)

        if not captured and not BROWSER_HEADLESS:
            print()
            print("=" * 60)
            print(f"Graph Explorer da mo tren browser.")
            print(f"Thuc hien trong browser:")
            print(f"  1. Dang nhap tai khoan {display_account}")
            print(f"  (Lan dau) Modify permissions -> them Tasks.ReadWrite,")
            print(f"            Group.Read.All -> Accept")
            print(f"  2. Click nut [Run query]")
            print(f"  Script tu dong tiep tuc sau khi nhan duoc token.")
            print("=" * 60)
            print()

            for _ in range(120):
                if captured:
                    break
                page.wait_for_timeout(1000)

        if not captured:
            token = _read_token_from_localstorage(page)
            if _token_has_min_lifetime(token):
                captured.append(token)

        session_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(session_path))
        print(f"Session da luu: {session_path}")

        browser.close()

    if not captured:
        if BROWSER_HEADLESS:
            raise RuntimeError(
                f"Session expired cho {display_account}. Run with BROWSER_HEADLESS=false."
            )
        raise RuntimeError(
            f"Không lấy được access token từ Graph Explorer ({display_account}).\n"
            "Đảm bảo đã đăng nhập đúng tài khoản và Graph Explorer "
            "đã được cấp quyền Tasks.ReadWrite, Group.Read.All "
            "(Modify permissions → Accept)."
        )

    _token_cache[cache_key] = captured[0]
    return _token_cache[cache_key]


if __name__ == "__main__":
    import argparse as _argparse
    _parser = _argparse.ArgumentParser(description="Lấy Microsoft Graph token cho một account.")
    _parser.add_argument("--login-hint", default="", help="Email account cần lấy token (mặc định dùng PLANNER_RUN_AS_EMAIL).")
    _args = _parser.parse_args()
    token = get_token(login_hint=_args.login_hint)
    exp = time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(_get_jwt_exp(token)))
    print(f"Lấy token thành công. Hết hạn lúc: {exp}")

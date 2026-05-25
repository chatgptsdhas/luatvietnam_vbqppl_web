import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, date
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

# Imports từ các file hiện hữu
from get_token_browser import get_token
from ms_planner import graph_request
from typing import Any

# Từ 12_sync_planner_to_webapp.py
def setup_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Thiếu biến môi trường {name} trong .env")
    return value

def get_optional_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()

def webapp_post(action: str, payload: dict) -> dict:
    url = get_required_env("APPS_SCRIPT_WEBAPP_URL")
    token = get_required_env("APPS_SCRIPT_TOKEN")
    body = {
        "token": token,
        "action": action,
        "payload": payload or {},
    }

    response = requests.post(url, json=body, timeout=60)
    if not response.ok:
        print(f"WebApp API error URL: {url}")
        print(f"status_code: {response.status_code}")
        print(response.text)
        response.raise_for_status()

    try:
        data = response.json()
    except ValueError as exc:
        print(f"WebApp API returned non-JSON. URL: {url}")
        print(f"status_code: {response.status_code}")
        print(response.text)
        raise RuntimeError("WebApp API không trả JSON hợp lệ.") from exc

    if data.get("ok") is False:
        print(f"WebApp API logical error URL: {url}")
        print(f"status_code: {response.status_code}")
        print(response.text)
        message = data.get("message") or data.get("error") or "WebApp API trả ok=false."
        raise RuntimeError(str(message))

    return data

def extract_records(response: Any) -> list[dict]:
    if isinstance(response, list):
        return [row for row in response if isinstance(row, dict)]
    if not isinstance(response, dict):
        return []
    for key in ("data", "result"):
        value = response.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = value.get("data")
            if isinstance(nested, list):
                return [row for row in nested if isinstance(row, dict)]
    return []

def now_text() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")

# Từ 13_generate_planner_reports.py
def clean_text(value: Any) -> str:
    return str(value or "").strip()

def parse_ddmmyyyy(value: str) -> date | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d/%m/%Y").date()
    except ValueError:
        return None

def parse_date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = clean_text(value)
    if not text:
        return None

    # dd/MM/yyyy
    parsed = parse_ddmmyyyy(text)
    if parsed:
        return parsed

    # ISO: 2026-05-18T17:00:00.000Z hoặc 2026-05-18
    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        from datetime import timezone
        parsed_dt = datetime.fromisoformat(iso_text)
        if parsed_dt.tzinfo is not None:
            from zoneinfo import ZoneInfo
            parsed_dt = parsed_dt.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
        return parsed_dt.date()
    except ValueError:
        return None

def parse_checklist_title(value: Any) -> dict | None:
    import re
    text = clean_text(value)
    if not text or "|" not in text:
        return None

    parts = [part.strip() for part in text.split("|")]
    if len(parts) < 4:
        return None

    due_match = re.search(r"Hạn hoàn thành\s*:\s*(\d{1,2}/\d{1,2}/\d{4})", parts[2], flags=re.IGNORECASE)
    due_text = due_match.group(1) if due_match else ""

    return {
        "department": parts[0],
        "pic": parts[1],
        "due_text": due_text,
        "due_date": parse_ddmmyyyy(due_text),
        "checkpoint": " | ".join(parts[3:]).strip(),
    }

def enrich_record(record: dict) -> dict:
    current_pic = clean_text(record.get("Current PIC"))
    current_checkpoint = clean_text(record.get("Current Checkpoint"))
    next_response_due = clean_text(record.get("Next Response Due"))

    parsed = parse_checklist_title(current_checkpoint) or parse_checklist_title(current_pic)
    if parsed:
        department = parsed["department"]
        pic = parsed["pic"] or current_pic
        checkpoint = parsed["checkpoint"] or current_checkpoint
        due_date = parsed["due_date"] or parse_date_value(next_response_due)
    else:
        department = ""
        pic = current_pic
        checkpoint = current_checkpoint
        due_date = parse_date_value(next_response_due)

    sync_status = clean_text(record.get("Planner Sync Status"))
    COMPLETED_STATUSES = {"Đã hoàn thành checkpoint", "Đã hoàn thành task"}
    is_completed = sync_status in COMPLETED_STATUSES
    today = datetime.now().date()
    is_overdue = bool(due_date and due_date < today and not is_completed)
    days_overdue = (today - due_date).days if is_overdue and due_date else 0

    return {
        "Số hiệu": clean_text(record.get("Số hiệu")),
        "Tên văn bản": clean_text(record.get("Tên văn bản")),
        "Planner Task ID": clean_text(record.get("Planner Task ID")),
        "Planner Task URL": clean_text(record.get("Planner Task URL")),
        "Planner Sync Status": sync_status,
        "Planner Last Sync": clean_text(record.get("Planner Last Sync")),
        "Current PIC": pic,
        "Current Checkpoint": checkpoint,
        "Next Response Due": next_response_due,
        "Bộ phận": department,
        "Ngày hạn": due_date.strftime("%d/%m/%Y") if due_date else "",
        "Số ngày quá hạn": days_overdue,
        "_due_date": due_date,
        "_is_overdue": is_overdue,
        "_is_completed": is_completed,
    }

# Constants
COMPLETED_STATUSES = {"Đã xóa task Planner", "Đã hoàn thành checkpoint", "Đã hoàn thành task"}
_uid_cache: Dict[str, Optional[str]] = {}

def resolve_user_id(token: str, email: str) -> Optional[str]:
    if email in _uid_cache:
        return _uid_cache[email]

    try:
        response = graph_request(token, "GET", f"/users/{email}?$select=id")
        if response and "id" in response:
            uid = response["id"]
            _uid_cache[email] = uid
            return uid
    except Exception as e:
        print(f"WARN: Không resolve được userId cho {email}: {e}")

    _uid_cache[email] = None
    return None

def send_teams_chat(token: str, sender_uid: str, recipient_uid: str, html: str) -> bool:
    try:
        # Tạo chat oneOnOne
        chat_body = {
            "chatType": "oneOnOne",
            "members": [
                {"@odata.type": "#microsoft.graph.aadUserConversationMember", "roles": ["owner"], "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{sender_uid}')"},
                {"@odata.type": "#microsoft.graph.aadUserConversationMember", "roles": ["owner"], "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{recipient_uid}')"}
            ]
        }
        chat_response = graph_request(token, "POST", "/chats", chat_body)
        if not chat_response or "id" not in chat_response:
            print(f"Không tạo được chat giữa {sender_uid} và {recipient_uid}")
            return False
        chat_id = chat_response["id"]

        # Gửi message
        message_body = {
            "body": {
                "contentType": "html",
                "content": html
            }
        }
        graph_request(token, "POST", f"/chats/{chat_id}/messages", message_body)
        return True
    except Exception as e:
        print(f"Lỗi gửi Teams chat: {e}")
        return False

def send_email(token: str, sender: str, to: str, subject: str, html: str, cc: List[str] = []) -> bool:
    try:
        body = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "html",
                    "content": html
                },
                "toRecipients": [{"emailAddress": {"address": to}}],
                "ccRecipients": [{"emailAddress": {"address": cc_email}} for cc_email in cc]
            },
            "saveToSentItems": True
        }
        graph_request(token, "POST", f"/users/{sender}/sendMail", body)
        return True
    except Exception as e:
        print(f"Lỗi gửi email: {e}")
        return False

def load_state() -> dict:
    state_file = get_optional_env("NOTIFY_STATE_FILE", "config/notify_state.json")
    if not os.path.exists(state_file):
        return {}
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"WARN: Không đọc được state file {state_file}: {e}")
        return {}

def save_state(state: dict, processed_tasks: List[dict]) -> None:
    today_str = date.today().strftime("%Y-%m-%d")
    if today_str not in state:
        state[today_str] = {}

    for task in processed_tasks:
        task_id = task["Planner Task ID"]
        state[today_str][task_id] = {
            "pic": task["Current PIC"],
            "days": task["Số ngày quá hạn"]
        }

    # Giữ tối đa 30 ngày
    keys = sorted(state.keys())
    if len(keys) > 30:
        for old_key in keys[:-30]:
            del state[old_key]

    state_file = get_optional_env("NOTIFY_STATE_FILE", "config/notify_state.json")
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"ERROR: Không ghi được state file {state_file}: {e}")

def already_sent_today(state: dict, task_id: str) -> bool:
    today_str = date.today().strftime("%Y-%m-%d")
    return today_str in state and task_id in state[today_str]

def build_overdue_list(records: List[dict]) -> List[dict]:
    overdue = []
    threshold = int(get_optional_env("NOTIFY_OVERDUE_THRESHOLD_DAYS", "1"))

    for r in records:
        if not clean_text(r.get("Planner Task ID")):
            continue
        if clean_text(r.get("Planner Sync Status")) in COMPLETED_STATUSES:
            continue

        e = enrich_record(r)
        if e["_is_overdue"] and e["Số ngày quá hạn"] >= threshold:
            overdue.append(e)

    return overdue

def get_alert_level(days: int) -> dict:
    if days >= 7:
        return {"icon": "🔴", "row_bg": "#ffebee", "days_color": "#b71c1c", "level": "critical"}
    elif days >= 3:
        return {"icon": "🟡", "row_bg": "#fff8e1", "days_color": "#e65100", "level": "warning"}
    else:
        return {"icon": "🔵", "row_bg": "#f1f8e9", "days_color": "#2e7d32", "level": "info"}

def build_html_pic(tasks: List[dict]) -> str:
    ngay = date.today().strftime("%d/%m/%Y")
    items = []
    for t in tasks:
        alert = get_alert_level(t["Số ngày quá hạn"])
        items.append(f'<li><a href="{t["Planner Task URL"]}">{t["Số hiệu"]}</a> | {t["Current Checkpoint"]} | Hạn: {t["Ngày hạn"]} | Quá <b style="color:{alert["days_color"]}">{t["Số ngày quá hạn"]} ngày</b></li>')

    return f"""<h3>⚠️ Bạn có {len(tasks)} văn bản quá hạn trên Planner ({ngay})</h3>
<ul>
{"".join(items)}
</ul>
<p>Vui lòng vào Planner cập nhật tiến độ.</p>"""

def build_html_summary(pending: List[dict], by_pic: Dict[str, List[dict]]) -> str:
    ngay = date.today().strftime("%d/%m/%Y")
    critical = sum(1 for t in pending if t["Số ngày quá hạn"] >= 7)
    warning = sum(1 for t in pending if 3 <= t["Số ngày quá hạn"] < 7)
    info = sum(1 for t in pending if 1 <= t["Số ngày quá hạn"] < 3)

    html = f"""<div style="font-family: Arial, sans-serif; max-width: 800px;">
<h2 style="background-color: #c00; color: white; padding: 10px;">⚠️ BÁO CÁO PLANNER QUÁ HẠN — {ngay}</h2>
<table style="border-collapse: collapse; width: 100%;">
<tr><td style="border: 1px solid #ddd; padding: 8px;"><b>Tổng task quá hạn</b></td><td style="border: 1px solid #ddd; padding: 8px;">{len(pending)}</td></tr>
<tr><td style="border: 1px solid #ddd; padding: 8px;"><b>PIC bị chậm</b></td><td style="border: 1px solid #ddd; padding: 8px;">{len(by_pic)}</td></tr>
<tr><td style="border: 1px solid #ddd; padding: 8px;"><b>🔴 Nghiêm trọng (≥7 ngày)</b></td><td style="border: 1px solid #ddd; padding: 8px;">{critical}</td></tr>
<tr><td style="border: 1px solid #ddd; padding: 8px;"><b>🟡 Cảnh báo (3–6 ngày)</b></td><td style="border: 1px solid #ddd; padding: 8px;">{warning}</td></tr>
</table>
"""

    for pic_email, tasks in sorted(by_pic.items(), key=lambda x: sum(t["Số ngày quá hạn"] for t in x[1]), reverse=True):
        bo_phan = tasks[0]["Bộ phận"] if tasks else ""
        html += f'<div style="background-color: #1565c0; color: white; padding: 8px; margin-top: 20px;"><b>👤 {pic_email} | {bo_phan} | {len(tasks)} task quá hạn</b></div>'
        html += '<table style="border-collapse: collapse; width: 100%;"><tr><th style="border: 1px solid #ddd; padding: 8px;">Số hiệu</th><th style="border: 1px solid #ddd; padding: 8px;">Tên văn bản</th><th style="border: 1px solid #ddd; padding: 8px;">Checkpoint</th><th style="border: 1px solid #ddd; padding: 8px;">Hạn</th><th style="border: 1px solid #ddd; padding: 8px;">Quá hạn</th><th style="border: 1px solid #ddd; padding: 8px;">Mức</th></tr>'

        for t in sorted(tasks, key=lambda x: x["Số ngày quá hạn"], reverse=True):
            alert = get_alert_level(t["Số ngày quá hạn"])
            ten_ngan = t["Tên văn bản"][:40] + "..." if len(t["Tên văn bản"]) > 40 else t["Tên văn bản"]
            html += f'<tr style="background-color: {alert["row_bg"]};">'
            html += f'<td style="border: 1px solid #ddd; padding: 8px;"><a href="{t["Planner Task URL"]}">{t["Số hiệu"]}</a></td>'
            html += f'<td style="border: 1px solid #ddd; padding: 8px; font-size: 13px;">{ten_ngan}</td>'
            html += f'<td style="border: 1px solid #ddd; padding: 8px; font-size: 13px;">{t["Current Checkpoint"]}</td>'
            html += f'<td style="border: 1px solid #ddd; padding: 8px;">{t["Ngày hạn"]}</td>'
            html += f'<td style="border: 1px solid #ddd; padding: 8px;"><b style="color: {alert["days_color"]}">{t["Số ngày quá hạn"]}</b></td>'
            html += f'<td style="border: 1px solid #ddd; padding: 8px;">{alert["icon"]}</td>'
            html += '</tr>'

        html += '</table>'

    html += f'<p style="margin-top: 20px;"><i>Email tự động từ Hệ thống Quản lý VBQPPL · {now_text()}<br/>Dữ liệu đồng bộ từ Microsoft Planner qua Graph API.</i></p></div>'
    return html

def build_teams_summary(pending: List[dict], by_pic: Dict[str, List[dict]]) -> str:
    ngay = date.today().strftime("%d/%m/%Y")
    critical = sum(1 for t in pending if t["Số ngày quá hạn"] >= 7)
    warning = sum(1 for t in pending if 3 <= t["Số ngày quá hạn"] < 7)
    info = sum(1 for t in pending if 1 <= t["Số ngày quá hạn"] < 3)

    html = f"""<h3>⚠️ BÁO CÁO PLANNER QUÁ HẠN — {ngay}</h3>
<p>Tổng: <b>{len(pending)} task</b> / <b>{len(by_pic)} PIC</b> bị chậm | 🔴 {critical} 🟡 {warning} 🔵 {info}</p>
<hr/>
"""

    for pic_email, tasks in sorted(by_pic.items(), key=lambda x: sum(t["Số ngày quá hạn"] for t in x[1]), reverse=True):
        bo_phan = tasks[0]["Bộ phận"] if tasks else ""
        html += f'<p><b>👤 {pic_email} ({bo_phan}) — {len(tasks)} task</b></p><ul>'

        for t in sorted(tasks, key=lambda x: x["Số ngày quá hạn"], reverse=True):
            alert = get_alert_level(t["Số ngày quá hạn"])
            ten_ngan = t["Tên văn bản"][:40] + "..." if len(t["Tên văn bản"]) > 40 else t["Tên văn bản"]
            html += f'<li>{alert["icon"]} <a href="{t["Planner Task URL"]}">{t["Số hiệu"]}</a> | {ten_ngan} | {t["Current Checkpoint"]} | Hạn {t["Ngày hạn"]} | Quá <b>{t["Số ngày quá hạn"]} ngày</b></li>'

        html += '</ul><hr/>'

    html += f'<i>Gửi tự động lúc {now_text()}</i>'
    return html

def main():
    parser = argparse.ArgumentParser(description="Gửi thông báo leo thang cho task Planner quá hạn")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in danh sách sẽ gửi, không gửi thật")
    parser.add_argument("--force", action="store_true", help="Gửi lại dù đã gửi trong ngày")
    parser.add_argument("--no-email", action="store_true", help="Tắt email")
    parser.add_argument("--no-teams", action="store_true", help="Tắt Teams")
    args = parser.parse_args()

    setup_utf8_stdio()
    load_dotenv()

    sender = get_required_env("NOTIFY_SENDER_EMAIL")
    summary_recipients = [email.strip() for email in get_required_env("NOTIFY_SUMMARY_RECIPIENTS").split(",") if email.strip()]

    token = get_token(login_hint=sender)
    sender_uid = resolve_user_id(token, sender)

    records = extract_records(webapp_post("get_all_records", {}))
    overdue = build_overdue_list(records)

    state = load_state()
    pending = [t for t in overdue if args.force or not already_sent_today(state, t["Planner Task ID"])]

    if not pending:
        print("Không có task nào cần thông báo.")
        sys.exit(0)

    if args.dry_run:
        print(f"DRY RUN: {len(pending)} task sẽ được thông báo")
        by_pic = defaultdict(list)
        for t in pending:
            pic = t["Current PIC"]
            if pic not in summary_recipients:
                by_pic[pic].append(t)
        print(f"PIC sẽ nhận per-PIC: {list(by_pic.keys())}")
        print(f"Summary recipients: {summary_recipients}")
        critical = sum(1 for t in pending if t["Số ngày quá hạn"] >= 7)
        warning = sum(1 for t in pending if 3 <= t["Số ngày quá hạn"] < 7)
        info = sum(1 for t in pending if 1 <= t["Số ngày quá hạn"] < 3)
        print(f"KPI: Tổng {len(pending)}, PIC {len(by_pic)}, 🔴 {critical}, 🟡 {warning}, 🔵 {info}")
        sys.exit(0)

    # Gom nhóm
    by_pic = defaultdict(list)
    for t in pending:
        pic = t["Current PIC"]
        if pic not in summary_recipients:
            by_pic[pic].append(t)

    sent = []
    failed = []

    # Gửi per-PIC
    for pic_email, tasks in by_pic.items():
        tasks_sorted = sorted(tasks, key=lambda x: x["Số ngày quá hạn"], reverse=True)
        html = build_html_pic(tasks_sorted)
        subj = f"[PLANNER QUÁ HẠN] {len(tasks_sorted)} văn bản cần xử lý"

        success_teams = True
        if not args.no_teams and sender_uid:
            pic_uid = resolve_user_id(token, pic_email)
            if pic_uid:
                success_teams = send_teams_chat(token, sender_uid, pic_uid, html)
            else:
                print(f"SKIP Teams cho {pic_email}: không resolve userId")

        success_email = True
        if not args.no_email:
            success_email = send_email(token, sender, pic_email, subj, html)

        if success_teams and success_email:
            sent.append(f"per-PIC {pic_email}")
        else:
            failed.append(f"per-PIC {pic_email}")
            if not success_teams:
                failed.append(f"  - Teams failed")
            if not success_email:
                failed.append(f"  - Email failed")

    # Gửi summary
    summary_html = build_html_summary(pending, by_pic)
    summary_teams = build_teams_summary(pending, by_pic)
    summary_subj = f"[PLANNER QUÁ HẠN] Tổng hợp {len(pending)} task — {date.today().strftime('%d/%m/%Y')}"

    for recipient in summary_recipients:
        success_teams = True
        if not args.no_teams and sender_uid:
            recipient_uid = resolve_user_id(token, recipient)
            if recipient_uid:
                success_teams = send_teams_chat(token, sender_uid, recipient_uid, summary_teams)
            else:
                print(f"SKIP Teams cho {recipient}: không resolve userId")

        success_email = True
        if not args.no_email:
            success_email = send_email(token, sender, recipient, summary_subj, summary_html)

        if success_teams and success_email:
            sent.append(f"summary {recipient}")
        else:
            failed.append(f"summary {recipient}")
            if not success_teams:
                failed.append(f"  - Teams failed")
            if not success_email:
                failed.append(f"  - Email failed")

    save_state(state, pending)

    print(f"Đã gửi thành công: {len(sent)}")
    for s in sent:
        print(f"  ✓ {s}")
    if failed:
        print(f"Thất bại: {len(failed)}")
        for f in failed:
            print(f"  ✗ {f}")
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
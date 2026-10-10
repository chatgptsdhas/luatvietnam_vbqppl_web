import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any

import requests
from requests.exceptions import HTTPError
from dotenv import load_dotenv
from get_token_browser import get_token
from ms_planner import graph_request


WEBAPP_TIMEOUT_SECONDS = 60
DEFAULT_RECORD_ACTION = "get_all_records"
VBQPPL_UPDATE_ACTION = "update_vbqppl_record"
DELETED_SYNC_STATUS = "Đã xóa task Planner"
DELETED_WORKFLOW_FIELDS = ("Current PIC", "Current Checkpoint", "Next Response Due")


def setup_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


setup_utf8_stdio()
load_dotenv()


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Thiếu biến môi trường {name} trong .env")
    return value


def get_optional_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def now_text() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def webapp_post(action: str, payload: dict) -> dict:
    url = get_required_env("APPS_SCRIPT_WEBAPP_URL")
    token = get_required_env("APPS_SCRIPT_TOKEN")
    # P0: update_vbqppl_record là action máy-máy (nhóm B) — WebApp.js chỉ còn chấp nhận đúng
    # APPS_SCRIPT_SERVICE_TOKEN cho nhóm này (đã bỏ fallback về APPS_SCRIPT_TOKEN cũ).
    service_token = get_required_env("APPS_SCRIPT_SERVICE_TOKEN")
    body = {"token": token, "service_token": service_token, "action": action, "payload": payload or {}}
    response = requests.post(url, json=body, timeout=WEBAPP_TIMEOUT_SECONDS)
    if not response.ok:
        print(f"WebApp API error status_code={response.status_code}")
        print(response.text)
        response.raise_for_status()
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("WebApp API không trả JSON hợp lệ.") from exc
    if data.get("ok") is False:
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


def get_records() -> list[dict]:
    return extract_records(webapp_post(DEFAULT_RECORD_ACTION, {}))


def should_sync_from_planner(record: dict) -> tuple[bool, str]:
    if not str(record.get("Planner Task ID", "") or "").strip():
        return False, "no Planner Task ID"
    if str(record.get("Planner Sync Status", "") or "").strip() == DELETED_SYNC_STATUS:
        return False, "task đã xóa"
    return True, ""


def is_deleted_planner_task(record: dict) -> bool:
    return str(record.get("Planner Sync Status", "") or "").strip() == DELETED_SYNC_STATUS


def needs_deleted_task_cleanup(record: dict) -> bool:
    """Return True only when a previously deleted task still has current workflow data."""
    return is_deleted_planner_task(record) and any(
        str(record.get(field, "") or "").strip() for field in DELETED_WORKFLOW_FIELDS
    )


def deleted_task_workflow_updates() -> dict:
    """Clear only current workflow fields; keep historical Planner identifiers untouched."""
    return {field: "" for field in DELETED_WORKFLOW_FIELDS}


def deleted_task_not_found_updates() -> dict:
    """Mark a newly discovered Graph 404 and clear its current workflow state."""
    return {
        "Planner Sync Status": DELETED_SYNC_STATUS,
        "Planner Last Sync": now_text(),
        **deleted_task_workflow_updates(),
    }


def parse_checklist_item(title: str) -> dict | None:
    """Parse: 'department | email | Hạn hoàn thành: dd/MM/YYYY | checkpoint'"""
    parts = [p.strip() for p in title.split("|")]
    if len(parts) < 4:
        return None
    due_date = ""
    if ":" in parts[2]:
        due_date = parts[2].split(":", 1)[1].strip()
    return {
        "department": parts[0],
        "pic_email": parts[1],
        "due_date": due_date,
        "checkpoint": parts[3],
    }


def get_active_checklist_item(checklist: dict) -> tuple[dict | None, bool]:
    """
    Trả về (item, all_checked).
    item = mục đầu tiên chưa tick; nếu tất cả đã tick thì trả mục cuối cùng.
    all_checked = True khi toàn bộ mục có thể parse đều đã tick.
    Trả (None, False) nếu không có mục nào đúng định dạng.
    """
    parsed_items = []
    for item_data in checklist.values():
        parsed = parse_checklist_item(str(item_data.get("title", "") or ""))
        if parsed is None:
            continue
        parsed["isChecked"] = bool(item_data.get("isChecked", False))
        parsed["orderHint"] = str(item_data.get("orderHint", "") or "")
        parsed_items.append(parsed)

    if not parsed_items:
        return None, False

    parsed_items.sort(key=lambda x: x["orderHint"])

    for item in parsed_items:
        if not item["isChecked"]:
            return item, False

    return parsed_items[-1], True


def build_updates(task: dict, details: dict) -> dict:
    updates: dict[str, Any] = {"Planner Last Sync": now_text()}

    if int(task.get("percentComplete", 0) or 0) == 100:
        updates["Planner Sync Status"] = "Đã hoàn thành task"
        updates["Current Checkpoint"] = "Đã hoàn thành toàn bộ"
        return updates

    active_item, all_checked = get_active_checklist_item(details.get("checklist") or {})

    if active_item is None:
        updates["Planner Sync Status"] = "Đang chờ PIC xử lý"
        return updates

    department = active_item["department"]
    pic_email = active_item["pic_email"]
    updates["Current PIC"] = f"{department} | {pic_email}" if department else pic_email
    updates["Next Response Due"] = active_item["due_date"]

    if not all_checked:
        updates["Planner Sync Status"] = "Đang chờ PIC xử lý"
        updates["Current Checkpoint"] = active_item["checkpoint"]
    else:
        updates["Planner Sync Status"] = "Đã hoàn thành checkpoint"
        updates["Current Checkpoint"] = f"Đã hoàn thành: {active_item['checkpoint']}"

    return updates


def sync_planner_to_webapp(limit: int = 0, dry_run: bool = False) -> dict:
    records = get_records()
    records_to_process: list[dict] = []
    skipped: list[dict] = []
    deleted_cleanup_candidates: list[dict] = []

    for record in records:
        if needs_deleted_task_cleanup(record):
            deleted_cleanup_candidates.append(record)
            continue
        ok, reason = should_sync_from_planner(record)
        if ok:
            records_to_process.append(record)
        else:
            skipped.append({"row_number": record.get("_rowNumber"), "reason": reason})

    if limit > 0:
        records_to_process = records_to_process[:limit]
        deleted_cleanup_to_process = deleted_cleanup_candidates[:max(limit - len(records_to_process), 0)]
    else:
        deleted_cleanup_to_process = deleted_cleanup_candidates

    if dry_run:
        print("DRY RUN - records sẽ đồng bộ từ Planner:")
        print(json.dumps(
            [{"row_number": r.get("_rowNumber"), "task_id": str(r.get("Planner Task ID", "") or "")}
             for r in records_to_process],
            ensure_ascii=False, indent=2,
        ))
        print("DRY RUN - deleted task cleanup candidates:")
        print(json.dumps(
            [{"row_number": r.get("_rowNumber"), "so_hieu": str(r.get("Số hiệu", "") or "")}
             for r in deleted_cleanup_candidates],
            ensure_ascii=False, indent=2,
        ))
        print("DRY RUN - deleted task cleanup sẽ xử lý trong write budget:")
        print(json.dumps(
            [{"row_number": r.get("_rowNumber"), "so_hieu": str(r.get("Số hiệu", "") or "")}
             for r in deleted_cleanup_to_process],
            ensure_ascii=False, indent=2,
        ))
        summary = {
            "ok": True,
            "dry_run": True,
            "total_records": len(records),
            "records_to_process": len(records_to_process),
            "skipped_records": len(skipped),
            "deleted_cleanup_candidates": len(deleted_cleanup_candidates),
            "deleted_cleanup_to_process": len(deleted_cleanup_to_process),
            "deleted_cleanup_updated": 0,
            "deleted_cleanup_failed": 0,
            "updated_records": 0,
            "failed_records": 0,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    updated: list[dict] = []
    not_found: list[dict] = []
    failed: list[dict] = []
    deleted_cleanup_updated: list[dict] = []
    deleted_cleanup_failed: list[dict] = []

    for record in deleted_cleanup_to_process:
        row_number = record.get("_rowNumber")
        so_hieu = str(record.get("Số hiệu", "") or "")
        updates = deleted_task_workflow_updates()
        try:
            print(f"Dọn workflow stale của task Planner đã xóa row={row_number} | so_hieu={so_hieu}")
            webapp_post(VBQPPL_UPDATE_ACTION, {"row_number": row_number, "updates": updates})
            deleted_cleanup_updated.append({"row_number": row_number, "so_hieu": so_hieu, "updates": updates})
        except Exception as exc:
            print(f"  Không thể dọn workflow stale: {exc}")
            deleted_cleanup_failed.append({"row_number": row_number, "so_hieu": so_hieu, "message": str(exc)})

    token = get_token() if records_to_process else ""

    for record in records_to_process:
        task_id = str(record.get("Planner Task ID", "") or "").strip()
        row_number = record.get("_rowNumber")
        try:
            print(f"Đồng bộ row={row_number} | task_id={task_id}")
            task = graph_request(token, "GET", f"/planner/tasks/{task_id}") or {}
            details = graph_request(token, "GET", f"/planner/tasks/{task_id}/details") or {}
            updates = build_updates(task, details)
            webapp_post(VBQPPL_UPDATE_ACTION, {"row_number": row_number, "updates": updates})
            updated.append({"row_number": row_number, "task_id": task_id, "updates": updates})
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                print(f"  Task không tìm thấy trên Planner (404), đánh dấu đã xóa.")
                updates = deleted_task_not_found_updates()
                try:
                    webapp_post(VBQPPL_UPDATE_ACTION, {
                        "row_number": row_number,
                        "updates": updates,
                    })
                    not_found.append({"row_number": row_number, "task_id": task_id, "updates": updates})
                except Exception as update_exc:
                    print(f"  Không thể cập nhật trạng thái đã xóa: {update_exc}")
                    failed.append({"row_number": row_number, "task_id": task_id, "message": str(update_exc)})
            else:
                print(f"  Lỗi HTTP {exc.response.status_code if exc.response else '?'}: {exc}")
                failed.append({"row_number": row_number, "task_id": task_id, "message": str(exc)})
        except Exception as exc:
            print(f"  Lỗi: {exc}")
            failed.append({"row_number": row_number, "task_id": task_id, "message": str(exc)})

    summary = {
        "ok": len(failed) == 0 and len(deleted_cleanup_failed) == 0,
        "dry_run": False,
        "total_records": len(records),
        "records_to_process": len(records_to_process),
        "skipped_records": len(skipped),
        "updated_records": len(updated),
        "not_found_records": len(not_found),
        "deleted_cleanup_candidates": len(deleted_cleanup_candidates),
        "deleted_cleanup_to_process": len(deleted_cleanup_to_process),
        "deleted_cleanup_updated": len(deleted_cleanup_updated),
        "deleted_cleanup_failed": len(deleted_cleanup_failed),
        "failed_records": len(failed) + len(deleted_cleanup_failed),
        "updated_items": updated,
        "not_found_items": not_found,
        "failed_items": failed,
        "deleted_cleanup_updated_items": deleted_cleanup_updated,
        "deleted_cleanup_failed_items": deleted_cleanup_failed,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Đồng bộ trạng thái Planner task về sheet VBQPPL.")
    parser.add_argument("--limit", type=int, default=0, help="Giới hạn số record xử lý. 0 = không giới hạn.")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in dữ liệu sẽ cập nhật, không ghi thật.")
    args = parser.parse_args()
    sync_planner_to_webapp(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

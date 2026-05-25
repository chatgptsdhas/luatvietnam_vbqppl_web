import argparse
import json
import os
import sys
from datetime import date, datetime
from typing import Any

import requests
from dotenv import load_dotenv
from ms_planner import create_planner_task_from_record, delete_planner_task, parse_ddmmyyyy


WEBAPP_TIMEOUT_SECONDS = 60
DEFAULT_RECORD_ACTION = "get_all_records"
VBQPPL_UPDATE_ACTION = "update_vbqppl_record"
CREATED_SYNC_STATUS = "Đã tạo task Planner"
DELETED_SYNC_STATUS = "Đã xóa task Planner"
DEBUG_SKIP_UNKNOWN = "unknown"


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
    body = {
        "token": token,
        "action": action,
        "payload": payload or {},
    }

    response = requests.post(url, json=body, timeout=WEBAPP_TIMEOUT_SECONDS)
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

    data = response.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]

    result = response.get("result")
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]

    if isinstance(result, dict):
        nested_data = result.get("data")
        if isinstance(nested_data, list):
            return [row for row in nested_data if isinstance(row, dict)]

    return []


def get_records(action: str = DEFAULT_RECORD_ACTION) -> list[dict]:
    response = webapp_post(action, {})
    return extract_records(response)


_RECORD_DATE_FIELDS_TO_TRY = [
    "Ngày chuyển trạng thái",
    "Ngày Python quét",
    "Planner Last Sync",
]


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def _parse_date_flexible(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value or "").strip()
    if not text:
        return None

    for fmt in ("%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date()
        except ValueError:
            continue

    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(iso).date()
    except ValueError:
        return None


def get_create_from_date() -> date | None:
    value = get_optional_env("PLANNER_CREATE_FROM_DATE")
    if not value:
        return None
    try:
        return parse_ddmmyyyy(value)
    except ValueError:
        print(f"PLANNER_CREATE_FROM_DATE='{value}' không đúng định dạng dd/MM/YYYY, bỏ qua filter ngày.")
        return None


def get_create_from_date_debug() -> tuple[str, date | None, bool]:
    value = get_optional_env("PLANNER_CREATE_FROM_DATE")
    if not value:
        return "", None, True
    try:
        return value, parse_ddmmyyyy(value), True
    except ValueError:
        return value, None, False


def get_record_date(record: dict) -> date | None:
    parsed, _, _ = get_record_date_debug_state(record)
    return parsed


def get_record_date_debug_state(record: dict) -> tuple[date | None, str, str]:
    first_raw_date = ""
    for field in _RECORD_DATE_FIELDS_TO_TRY:
        raw = clean_text(record.get(field))
        if not raw:
            continue
        if not first_raw_date:
            first_raw_date = raw
        parsed = _parse_date_flexible(raw)
        if parsed:
            return parsed, raw, "ok"
    return None, first_raw_date, "invalid" if first_raw_date else "missing"


def should_create_planner_task(record: dict) -> tuple[bool, str]:
    if not record.get("_rowNumber"):
        return False, "missing _rowNumber"
    if not clean_text(record.get("Số hiệu")):
        return False, "missing Số hiệu"
    if not clean_text(record.get("Tên văn bản")):
        return False, "missing Tên văn bản"
    if clean_text(record.get("Planner Task ID")):
        return False, "already has Planner Task ID"
    if clean_text(record.get("Planner Sync Status")) == CREATED_SYNC_STATUS:
        return False, "Planner Sync Status already created"
    create_from = get_create_from_date()
    if create_from is not None:
        record_date = get_record_date(record)
        if record_date is None:
            return False, "không xác định được ngày của record"
        if record_date < create_from:
            return False, f"ngày record {record_date} < PLANNER_CREATE_FROM_DATE {create_from}"
    return True, ""


def is_record_transferred_or_eligible(record: dict) -> bool:
    process_status = clean_text(record.get("Trạng thái xử lý")).lower()
    approval_status = clean_text(record.get("Trạng thái duyệt")).lower()
    if "đã chuyển" in process_status:
        return True
    if "đã kiểm tra" in approval_status:
        return True
    return False


def classify_skip_reason(record: dict, raw_reason: str) -> str:
    sync_status = clean_text(record.get("Planner Sync Status"))

    if raw_reason.startswith("missing "):
        return "missing_required_field"
    if raw_reason == "already has Planner Task ID":
        if sync_status == DELETED_SYNC_STATUS:
            return "deleted_planner_task"
        return "has_planner_task_id"
    if raw_reason.startswith("ngày record "):
        return "before_create_from_date"
    if raw_reason == "không xác định được ngày của record":
        _, _, date_state = get_record_date_debug_state(record)
        if date_state == "missing":
            return "missing_create_date"
        if date_state == "invalid":
            return "invalid_create_date"
    if raw_reason in ("status_not_eligible", "not_transferred_or_not_eligible"):
        return "status_not_eligible"
    if raw_reason == "Planner Sync Status already created":
        return DEBUG_SKIP_UNKNOWN
    if sync_status == DELETED_SYNC_STATUS:
        return "deleted_planner_task"
    if clean_text(record.get("Planner Task ID")):
        return "has_planner_task_id"
    if not is_record_transferred_or_eligible(record):
        return "status_not_eligible"
    return DEBUG_SKIP_UNKNOWN


def build_skip_debug_row(record: dict, raw_reason: str) -> dict:
    create_from_raw, _, _ = get_create_from_date_debug()
    parsed_record_date, raw_record_date, _ = get_record_date_debug_state(record)
    return {
        "row_number": record.get("_rowNumber"),
        "Số hiệu": clean_text(record.get("Số hiệu")),
        "Tên văn bản": clean_text(record.get("Tên văn bản")),
        "Planner Task ID": clean_text(record.get("Planner Task ID")),
        "Planner Sync Status": clean_text(record.get("Planner Sync Status")),
        "Ngày hiệu lực": clean_text(record.get("Ngày hiệu lực")),
        "Ngày chuyển trạng thái": clean_text(record.get("Ngày chuyển trạng thái")),
        "raw_record_date": raw_record_date,
        "parsed_record_date": parsed_record_date.isoformat() if parsed_record_date else "",
        "PLANNER_CREATE_FROM_DATE": create_from_raw,
        "skip_reason": classify_skip_reason(record, raw_reason),
        "raw_skip_reason": raw_reason,
        "record_keys": list(record.keys()),
    }


def print_skip_debug(skipped_records: list[dict]) -> None:
    debug_rows = [
        build_skip_debug_row(item["record"], item["reason"])
        for item in skipped_records
    ]
    print("SKIP DEBUG - records bị skip:")
    print(json.dumps(debug_rows, ensure_ascii=False, indent=2))


def update_record_with_planner_info(record: dict, task_result: dict) -> dict:
    row_number = record.get("_rowNumber")
    if not row_number:
        raise ValueError("Record thiếu _rowNumber, không thể update Google Sheet.")

    updates = {
        "Planner Task ID": task_result["task_id"],
        "Planner Plan ID": get_required_env("PLANNER_PLAN_ID"),
        "Planner Bucket ID": get_required_env("PLANNER_BUCKET_ID_PHAP_CHE"),
        "Planner Bucket Name": "Pháp chế",
        "Planner Task URL": task_result.get("planner_web_url", ""),
        "Planner Sync Status": "Đã tạo task Planner",
        "Planner Last Sync": now_text(),
        "Current PIC": get_optional_env("PLANNER_INITIAL_ASSIGNEE_EMAILS"),
        "Current Checkpoint": "Phân tích sơ bộ",
        "Next Response Due": task_result["next_response_due"],
    }

    return webapp_post(
        VBQPPL_UPDATE_ACTION,
        {
            "row_number": row_number,
            "updates": updates,
        },
    )


def summarize_record(record: dict) -> dict:
    return {
        "_rowNumber": record.get("_rowNumber"),
        "Số hiệu": record.get("Số hiệu", ""),
        "Tên văn bản": record.get("Tên văn bản", ""),
        "Planner Task ID": record.get("Planner Task ID", ""),
        "Planner Sync Status": record.get("Planner Sync Status", ""),
    }


def find_record_for_planner_sync(
    records: list[dict],
    row_number: int | str | None = None,
    so_hieu: str = "",
) -> dict | None:
    target_row_number = clean_text(row_number)
    target_so_hieu = clean_text(so_hieu)

    if target_row_number:
        for record in records:
            if clean_text(record.get("_rowNumber")) == target_row_number:
                return record

    if target_so_hieu:
        for record in records:
            if clean_text(record.get("Số hiệu")) == target_so_hieu:
                return record

    return None


def sync_single_webapp_record_to_planner(
    row_number: int | str | None = None,
    so_hieu: str = "",
    dry_run: bool = False,
) -> dict:
    if not clean_text(row_number) and not clean_text(so_hieu):
        raise ValueError("Cần truyền row_number hoặc so_hieu để đồng bộ đúng record.")

    records = get_records(DEFAULT_RECORD_ACTION)
    record = find_record_for_planner_sync(records, row_number=row_number, so_hieu=so_hieu)

    if not record:
        summary = {
            "ok": False,
            "dry_run": dry_run,
            "action": DEFAULT_RECORD_ACTION,
            "target_row_number": clean_text(row_number),
            "target_so_hieu": clean_text(so_hieu),
            "total_records": len(records),
            "created_tasks": 0,
            "failed_records": 1,
            "message": "Không tìm thấy record trong sheet VBQPPL.",
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    should_create, reason = should_create_planner_task(record)
    if not should_create:
        summary = {
            "ok": True,
            "dry_run": dry_run,
            "action": DEFAULT_RECORD_ACTION,
            "target_row_number": record.get("_rowNumber"),
            "target_so_hieu": clean_text(record.get("Số hiệu")),
            "total_records": len(records),
            "skipped_records": 1,
            "created_tasks": 0,
            "failed_records": 0,
            "skip_reason": classify_skip_reason(record, reason),
            "raw_skip_reason": reason,
            "record": summarize_record(record),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    if dry_run:
        summary = {
            "ok": True,
            "dry_run": True,
            "action": DEFAULT_RECORD_ACTION,
            "target_row_number": record.get("_rowNumber"),
            "target_so_hieu": clean_text(record.get("Số hiệu")),
            "total_records": len(records),
            "records_to_process": 1,
            "created_tasks": 0,
            "failed_records": 0,
            "record": summarize_record(record),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    row_number = record.get("_rowNumber")
    task_result: dict = {}
    try:
        print(f"Tạo Planner task cho row={row_number} | {record.get('Số hiệu', '')}")
        task_result = create_planner_task_from_record(record)
        if not task_result.get("ok"):
            summary = {
                "ok": False,
                "dry_run": False,
                "action": DEFAULT_RECORD_ACTION,
                "target_row_number": row_number,
                "target_so_hieu": clean_text(record.get("Số hiệu")),
                "total_records": len(records),
                "created_tasks": 0,
                "failed_records": 1,
                "failed_items": [
                    {
                        "row_number": row_number,
                        "so_hieu": record.get("Số hiệu", ""),
                        "message": task_result.get("message", "create_planner_task_from_record failed"),
                    }
                ],
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return summary

        update_result = update_record_with_planner_info(record, task_result)
        summary = {
            "ok": True,
            "dry_run": False,
            "action": DEFAULT_RECORD_ACTION,
            "target_row_number": row_number,
            "target_so_hieu": clean_text(record.get("Số hiệu")),
            "total_records": len(records),
            "created_tasks": 1,
            "failed_records": 0,
            "created_items": [
                {
                    "row_number": row_number,
                    "task_id": task_result.get("task_id", ""),
                    "title": task_result.get("title", ""),
                    "update_result": update_result,
                }
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary
    except Exception as exc:
        rollback_result = None
        if task_result.get("ok") and task_result.get("task_id"):
            rollback_result = delete_planner_task(task_result["task_id"])
        summary = {
            "ok": False,
            "dry_run": False,
            "action": DEFAULT_RECORD_ACTION,
            "target_row_number": row_number,
            "target_so_hieu": clean_text(record.get("Số hiệu")),
            "total_records": len(records),
            "created_tasks": 0,
            "failed_records": 1,
            "failed_items": [
                    {
                        "row_number": row_number,
                        "so_hieu": record.get("Số hiệu", ""),
                        "task_id": task_result.get("task_id", ""),
                        "message": str(exc),
                        "rollback_result": rollback_result,
                    }
                ],
            }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary


def sync_webapp_to_planner(
    limit: int = 1,
    dry_run: bool = False,
    action: str = DEFAULT_RECORD_ACTION,
    debug_skip: bool = False,
) -> dict:
    if action != DEFAULT_RECORD_ACTION and not dry_run:
        raise ValueError(f"Action {action} chỉ được dùng với --dry-run; tạo Planner task chỉ lấy từ sheet VBQPPL.")

    records = get_records(action)
    skipped_records: list[dict] = []
    candidate_records: list[dict] = []
    created_tasks: list[dict] = []
    failed_records: list[dict] = []

    for record in records:
        should_create, reason = should_create_planner_task(record)
        if not should_create:
            skipped_records.append({"record": record, "reason": reason})
            continue
        candidate_records.append(record)

    if limit and limit > 0:
        records_to_process = candidate_records[:limit]
    else:
        records_to_process = candidate_records

    if debug_skip:
        print_skip_debug(skipped_records)

    if dry_run:
        print("DRY RUN - records sẽ tạo Planner task:")
        print(json.dumps([summarize_record(row) for row in records_to_process], ensure_ascii=False, indent=2))
        summary = {
            "ok": True,
            "dry_run": True,
            "action": action,
            "total_records": len(records),
            "skipped_records": len(skipped_records),
            "candidate_records": len(candidate_records),
            "records_to_process": len(records_to_process),
            "created_tasks": 0,
            "failed_records": 0,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    for record in records_to_process:
        row_number = record.get("_rowNumber")
        task_result: dict = {}
        try:
            print(f"Tạo Planner task cho row={row_number} | {record.get('Số hiệu', '')}")
            task_result = create_planner_task_from_record(record)
            if not task_result.get("ok"):
                failed_records.append(
                    {
                        "row_number": row_number,
                        "so_hieu": record.get("Số hiệu", ""),
                        "task_id": task_result.get("task_id", ""),
                        "message": task_result.get("message", "create_planner_task_from_record failed"),
                        "rollback_result": task_result.get("rollback_result"),
                    }
                )
                continue

            update_result = update_record_with_planner_info(record, task_result)
            created_tasks.append(
                {
                    "row_number": row_number,
                    "task_id": task_result.get("task_id", ""),
                    "title": task_result.get("title", ""),
                    "update_result": update_result,
                }
            )
        except Exception as exc:
            rollback_result = None
            if task_result.get("ok") and task_result.get("task_id"):
                rollback_result = delete_planner_task(task_result["task_id"])
            failed_records.append(
                {
                    "row_number": row_number,
                    "so_hieu": record.get("Số hiệu", ""),
                    "task_id": task_result.get("task_id", ""),
                    "message": str(exc),
                    "rollback_result": rollback_result,
                }
            )

    summary = {
        "ok": len(failed_records) == 0,
        "dry_run": False,
        "action": action,
        "total_records": len(records),
        "skipped_records": len(skipped_records),
        "candidate_records": len(candidate_records),
        "records_to_process": len(records_to_process),
        "created_tasks": len(created_tasks),
        "failed_records": len(failed_records),
        "created_items": created_tasks,
        "failed_items": failed_records,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Đồng bộ record WebApp/Google Sheet sang Microsoft Planner.")
    parser.add_argument("--limit", type=int, default=1, help="Giới hạn số record tạo task. Dùng 0 để không giới hạn.")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in record sẽ xử lý, không tạo task thật.")
    parser.add_argument(
        "--debug-skip",
        action="store_true",
        help="In mọi record bị skip kèm skip_reason để kiểm tra vì sao không tạo Planner task.",
    )
    parser.add_argument(
        "--action",
        default=DEFAULT_RECORD_ACTION,
        choices=["get_pending_records", "get_all_records"],
        help="WebApp action để lấy dữ liệu. Mặc định lấy sheet VBQPPL; get_pending_records chỉ dùng với --dry-run.",
    )
    args = parser.parse_args()

    sync_webapp_to_planner(limit=args.limit, dry_run=args.dry_run, action=args.action, debug_skip=args.debug_skip)


if __name__ == "__main__":
    main()

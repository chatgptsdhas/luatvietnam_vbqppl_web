import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv


WEBAPP_TIMEOUT_SECONDS = 60
DEFAULT_RECORD_ACTION = "get_all_records"
OUTPUT_DIR = Path("output/reports")
DELETED_SYNC_STATUS = "Đã xóa task Planner"
COMPLETED_STATUSES = {"Đã hoàn thành checkpoint", "Đã hoàn thành task"}
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
CSV_FIELDNAMES = {
    "overdue_tasks": [
        "Số hiệu",
        "Tên văn bản",
        "Planner Task ID",
        "Planner Task URL",
        "Planner Sync Status",
        "Planner Last Sync",
        "Current PIC",
        "Current Checkpoint",
        "Next Response Due",
        "Bộ phận",
        "Ngày hạn",
        "Số ngày quá hạn",
    ],
    "slow_departments": ["Bộ phận", "Tổng việc", "Việc quá hạn", "Tỷ lệ quá hạn (%)"],
    "slow_people": ["Current PIC", "Tổng việc", "Việc quá hạn", "Tỷ lệ quá hạn (%)"],
    "checklist_completion": ["Tổng task", "Đã hoàn thành", "Tỷ lệ hoàn thành (%)"],
}


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


def clean_text(value: Any) -> str:
    return str(value or "").strip()


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


def get_all_records() -> list[dict]:
    return extract_records(webapp_post(DEFAULT_RECORD_ACTION, {}))


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
        current = value
        if current.tzinfo is not None:
            current = current.astimezone(LOCAL_TIMEZONE)
        return current.date()

    if isinstance(value, date):
        return value

    text = clean_text(value)
    if not text:
        return None

    parsed = parse_ddmmyyyy(text)
    if parsed:
        return parsed

    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed_datetime = datetime.fromisoformat(iso_text)
    except ValueError:
        return None

    if parsed_datetime.tzinfo is not None:
        parsed_datetime = parsed_datetime.astimezone(LOCAL_TIMEZONE)

    return parsed_datetime.date()


def format_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def parse_checklist_title(value: Any) -> dict | None:
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


def infer_department_from_current_pic(current_pic: str) -> str:
    parts = [part.strip() for part in clean_text(current_pic).split("|")]
    if len(parts) >= 2:
        return parts[0]
    return ""


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
        department = infer_department_from_current_pic(current_pic)
        pic = current_pic
        checkpoint = current_checkpoint
        due_date = parse_date_value(next_response_due)

    sync_status = clean_text(record.get("Planner Sync Status"))
    is_completed = sync_status in COMPLETED_STATUSES
    today = datetime.now(LOCAL_TIMEZONE).date()
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
        "Ngày hạn": format_date(due_date),
        "Số ngày quá hạn": days_overdue,
        "_due_date": due_date,
        "_is_overdue": is_overdue,
        "_is_completed": is_completed,
    }


def should_include_record(record: dict) -> bool:
    if not clean_text(record.get("Planner Task ID")):
        return False
    if clean_text(record.get("Planner Sync Status")) == DELETED_SYNC_STATUS:
        return False
    return True


def build_group_report(records: list[dict], group_key: str, label: str) -> list[dict]:
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "overdue": 0})

    for record in records:
        key = clean_text(record.get(group_key))
        grouped[key]["total"] += 1
        if record["_is_overdue"]:
            grouped[key]["overdue"] += 1

    rows = []
    for key, stats in grouped.items():
        total = stats["total"]
        overdue = stats["overdue"]
        rows.append({
            label: key,
            "Tổng việc": total,
            "Việc quá hạn": overdue,
            "Tỷ lệ quá hạn (%)": round((overdue / total * 100) if total else 0, 2),
        })

    rows.sort(key=lambda row: (-int(row["Việc quá hạn"]), -float(row["Tỷ lệ quá hạn (%)"]), clean_text(row.get(label))))
    return rows


def build_reports(records: list[dict]) -> dict:
    filtered_records = [record for record in records if should_include_record(record)]
    enriched_records = [enrich_record(record) for record in filtered_records]
    overdue_records = [record for record in enriched_records if record["_is_overdue"]]
    completed_records = [record for record in enriched_records if record["_is_completed"]]

    overdue_rows = [
        {
            "Số hiệu": record["Số hiệu"],
            "Tên văn bản": record["Tên văn bản"],
            "Planner Task ID": record["Planner Task ID"],
            "Planner Task URL": record["Planner Task URL"],
            "Planner Sync Status": record["Planner Sync Status"],
            "Planner Last Sync": record["Planner Last Sync"],
            "Current PIC": record["Current PIC"],
            "Current Checkpoint": record["Current Checkpoint"],
            "Next Response Due": record["Next Response Due"],
            "Bộ phận": record["Bộ phận"],
            "Ngày hạn": record["Ngày hạn"],
            "Số ngày quá hạn": record["Số ngày quá hạn"],
        }
        for record in overdue_records
    ]
    overdue_rows.sort(key=lambda row: (-int(row["Số ngày quá hạn"]), clean_text(row["Số hiệu"])))

    total = len(enriched_records)
    completed = len(completed_records)
    completion_rate = round((completed / total * 100) if total else 0, 2)
    status_counts = Counter(record["Planner Sync Status"] or "(trống)" for record in enriched_records)

    checklist_completion_rows = [{
        "Tổng task": total,
        "Đã hoàn thành": completed,
        "Tỷ lệ hoàn thành (%)": completion_rate,
    }]

    summary = {
        "generated_at": datetime.now(LOCAL_TIMEZONE).strftime("%d/%m/%Y %H:%M:%S"),
        "total_webapp_records": len(records),
        "records_with_planner_task": total,
        "overdue_tasks": len(overdue_rows),
        "completed_tasks": completed,
        "completion_rate_percent": completion_rate,
        "slow_departments": len({record["Bộ phận"] for record in enriched_records}),
        "slow_people": len({record["Current PIC"] for record in enriched_records}),
        "status_counts": dict(status_counts),
        "outputs": {
            "overdue_tasks_csv": str(OUTPUT_DIR / "overdue_tasks.csv"),
            "slow_departments_csv": str(OUTPUT_DIR / "slow_departments.csv"),
            "slow_people_csv": str(OUTPUT_DIR / "slow_people.csv"),
            "checklist_completion_csv": str(OUTPUT_DIR / "checklist_completion.csv"),
            "summary_json": str(OUTPUT_DIR / "planner_report_summary.json"),
        },
    }

    return {
        "overdue_tasks": overdue_rows,
        "slow_departments": build_group_report(enriched_records, "Bộ phận", "Bộ phận"),
        "slow_people": build_group_report(enriched_records, "Current PIC", "Current PIC"),
        "checklist_completion": checklist_completion_rows,
        "summary": summary,
    }


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_reports(reports: dict, output_format: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if output_format in ("csv", "all"):
        write_csv(OUTPUT_DIR / "overdue_tasks.csv", reports["overdue_tasks"], CSV_FIELDNAMES["overdue_tasks"])
        write_csv(OUTPUT_DIR / "slow_departments.csv", reports["slow_departments"], CSV_FIELDNAMES["slow_departments"])
        write_csv(OUTPUT_DIR / "slow_people.csv", reports["slow_people"], CSV_FIELDNAMES["slow_people"])
        write_csv(
            OUTPUT_DIR / "checklist_completion.csv",
            reports["checklist_completion"],
            CSV_FIELDNAMES["checklist_completion"],
        )

    if output_format in ("json", "all"):
        with (OUTPUT_DIR / "planner_report_summary.json").open("w", encoding="utf-8") as file:
            json.dump(reports["summary"], file, ensure_ascii=False, indent=2)


def generate_planner_reports(dry_run: bool = False, output_format: str = "all") -> dict:
    records = get_all_records()
    reports = build_reports(records)

    if not dry_run:
        write_reports(reports, output_format)

    terminal_summary = {
        "ok": True,
        "dry_run": dry_run,
        "format": output_format,
        **reports["summary"],
    }
    print(json.dumps(terminal_summary, ensure_ascii=False, indent=2))
    return terminal_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Tạo báo cáo Planner từ dữ liệu VBQPPL.")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in summary, không ghi file.")
    parser.add_argument(
        "--format",
        choices=["csv", "json", "all"],
        default="all",
        help="Định dạng output cần ghi. Mặc định all.",
    )
    args = parser.parse_args()

    generate_planner_reports(dry_run=args.dry_run, output_format=args.format)


if __name__ == "__main__":
    main()

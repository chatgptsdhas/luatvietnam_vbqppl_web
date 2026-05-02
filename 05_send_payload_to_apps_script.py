from pathlib import Path
import json
import os
from datetime import datetime

import requests
from dotenv import load_dotenv


load_dotenv()


PAYLOAD_FILE = Path("output/vbqppl_nhap_payload.json")
LUOC_DO_FILE = Path("output/extracted_luocdo_live.json")
RESPONSE_FILE = Path("output/apps_script_response.json")
RESPONSE_TEXT_FILE = Path("output/apps_script_response_readable.txt")


APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
APPS_SCRIPT_TOKEN = os.getenv("APPS_SCRIPT_TOKEN", "").strip()


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict):
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_text(path: Path, text: str):
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_readable_response(response_data: dict) -> str:
    lines = []

    lines.append("=" * 80)
    lines.append("BÁO CÁO GỬI PAYLOAD SANG APPS SCRIPT WEB APP")
    lines.append("=" * 80)
    lines.append("")

    lines.append(f"Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    lines.append(f"Trạng thái: {'THÀNH CÔNG' if response_data.get('ok') else 'THẤT BẠI'}")
    lines.append(f"Thông báo: {response_data.get('message', '')}")
    lines.append("")

    result = response_data.get("result", {})

    write_result = result.get("write_result", {})
    matched_payload = result.get("matched_payload", {})
    match_report = result.get("match_report", {})

    if write_result:
        lines.append("1. KẾT QUẢ GHI VBQPPL_NHAP")
        lines.append("-" * 80)
        lines.append(f"Hành động: {write_result.get('action', '')}")
        lines.append(f"Dòng: {write_result.get('row_number', '')}")
        lines.append(f"Số hiệu: {write_result.get('so_hieu', '')}")
        lines.append("")

    if matched_payload:
        lines.append("2. 4 CỘT QUAN HỆ PHÁP LÝ CHÍNH THỨC")
        lines.append("-" * 80)

        for col in [
            "Căn cứ pháp lý",
            "Hướng dẫn thực hiện",
            "Sửa đổi, bổ sung cho",
            "Sửa đổi, bổ sung bởi",
        ]:
            lines.append(f"{col}:")
            lines.append(matched_payload.get(col, "") or "(trống)")
            lines.append("")

        lines.append("Trạng thái quan hệ pháp lý:")
        lines.append(matched_payload.get("Trạng thái quan hệ pháp lý", ""))
        lines.append("")

    if match_report:
        lines.append("3. CHI TIẾT ĐỐI CHIẾU")
        lines.append("-" * 80)

        for heading, report in match_report.items():
            lines.append(f"[{heading}] → {report.get('official_column', '')}")

            matched_details = report.get("matched_details", [])
            missing_items = report.get("missing_items", [])

            lines.append("Đã đối chiếu được ID:")
            if matched_details:
                for item in matched_details:
                    lines.append(
                        f"- {item.get('so_hieu_tu_luoc_do', '')} "
                        f"→ {item.get('id_van_ban', '')}"
                    )
            else:
                lines.append("- Không có")

            lines.append("Chưa có trong danh mục:")
            if missing_items:
                for item in missing_items:
                    lines.append(f"- {item.get('so_hieu_tu_luoc_do', '')}")
            else:
                lines.append("- Không có")

            lines.append("")

    if not response_data.get("ok"):
        lines.append("4. LỖI")
        lines.append("-" * 80)
        lines.append(str(response_data.get("error", "")))
        lines.append(str(response_data.get("message", "")))
        lines.append(str(response_data.get("stack", "")))

    return "\n".join(lines)


def main():
    if not APPS_SCRIPT_WEBAPP_URL:
        raise ValueError(
            "Thiếu APPS_SCRIPT_WEBAPP_URL trong file .env."
        )

    if not APPS_SCRIPT_TOKEN:
        raise ValueError(
            "Thiếu APPS_SCRIPT_TOKEN trong file .env."
        )

    payload = load_json(PAYLOAD_FILE)
    luoc_do_data = load_json(LUOC_DO_FILE)

    request_body = {
        "token": APPS_SCRIPT_TOKEN,
        "action": "import_vbqppl_nhap",
        "payload": payload,
        "luoc_do_data": luoc_do_data,
    }

    print("Đang gửi payload sang Apps Script Web App...")
    print(f"URL: {APPS_SCRIPT_WEBAPP_URL}")
    print(f"Số hiệu: {payload.get('Số hiệu', '')}")

    response = requests.post(
        APPS_SCRIPT_WEBAPP_URL,
        json=request_body,
        timeout=120,
    )

    try:
        response_data = response.json()
    except Exception:
        response_data = {
            "ok": False,
            "error": "INVALID_JSON_RESPONSE",
            "message": response.text,
            "status_code": response.status_code,
        }

    save_json(RESPONSE_FILE, response_data)
    save_text(RESPONSE_TEXT_FILE, build_readable_response(response_data))

    if response.status_code >= 400:
        raise RuntimeError(
            f"Apps Script trả HTTP {response.status_code}: {response.text}"
        )

    if not response_data.get("ok"):
        raise RuntimeError(
            "Apps Script xử lý thất bại: "
            + str(response_data.get("message", ""))
        )

    result = response_data.get("result", {})
    write_result = result.get("write_result", {})

    print()
    print("Đã gửi thành công.")
    print(f"Hành động: {write_result.get('action', '')}")
    print(f"Dòng: {write_result.get('row_number', '')}")
    print(f"Số hiệu: {write_result.get('so_hieu', '')}")

    print()
    print(f"Đã lưu phản hồi JSON vào: {RESPONSE_FILE}")
    print(f"Đã lưu báo cáo dễ đọc vào: {RESPONSE_TEXT_FILE}")


if __name__ == "__main__":
    main()
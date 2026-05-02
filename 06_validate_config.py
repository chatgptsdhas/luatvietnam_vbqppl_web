from pathlib import Path
import json
import os

from dotenv import load_dotenv


load_dotenv()


ENV_REQUIRED_KEYS = [
    "LUATVN_LOGIN_URL",
    "LUATVN_TEST_DOCUMENT_URL",
    "APPS_SCRIPT_WEBAPP_URL",
    "APPS_SCRIPT_TOKEN",
]


CONFIG_FILE = Path("config/scan_config.json")
PAYLOAD_FILE = Path("output/vbqppl_nhap_payload.json")
LUOC_DO_FILE = Path("output/extracted_luocdo_live.json")


REQUIRED_PAYLOAD_COLUMNS = [
    "ID VĂN BẢN",
    "Lĩnh vực",
    "Chủ đề",
    "Mục",
    "Loại văn bản",
    "Tên văn bản",
    "Số hiệu",
    "Ngày hiệu lực",
    "Mức độ tác động",
    "Bộ phận chủ trì",
    "Link Văn bản",
    "Căn cứ pháp lý",
    "Hướng dẫn thực hiện",
    "Sửa đổi, bổ sung cho",
    "Sửa đổi, bổ sung bởi",
    "Trạng thái duyệt",
    "Trạng thái xử lý",
    "Nội dung căn cứ",
    "Gợi ý căn cứ pháp lý",
    "Văn bản căn cứ chưa có trong danh mục",
    "Trạng thái quan hệ pháp lý",
    "Ghi chú quan hệ pháp lý",
    "Nguồn dữ liệu",
    "Ngày Python quét",
    "Ghi chú Python",
]


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def check_env() -> list[str]:
    errors = []

    for key in ENV_REQUIRED_KEYS:
        value = os.getenv(key, "").strip()

        if not value:
            errors.append(f"Thiếu biến .env: {key}")

    return errors


def check_scan_config() -> list[str]:
    errors = []

    config = load_json(CONFIG_FILE)

    if "run_mode" not in config:
        errors.append("config/scan_config.json thiếu run_mode.")

    if "luatvietnam_fields" not in config:
        errors.append("config/scan_config.json thiếu luatvietnam_fields.")
        return errors

    fields = config.get("luatvietnam_fields", [])

    if not isinstance(fields, list):
        errors.append("luatvietnam_fields phải là list.")
        return errors

    enabled_fields = [
        item for item in fields
        if item.get("enabled") is True
    ]

    if not enabled_fields:
        errors.append("Chưa có lĩnh vực nào enabled=true.")

    for index, field in enumerate(fields, start=1):
        if "ma_linh_vuc" not in field:
            errors.append(f"Lĩnh vực thứ {index} thiếu ma_linh_vuc.")

        if "ten_linh_vuc_luatvietnam" not in field:
            errors.append(f"Lĩnh vực thứ {index} thiếu ten_linh_vuc_luatvietnam.")

        if "list_url" not in field:
            errors.append(f"Lĩnh vực thứ {index} thiếu list_url.")

    return errors


def check_payload() -> list[str]:
    errors = []

    payload = load_json(PAYLOAD_FILE)

    for column in REQUIRED_PAYLOAD_COLUMNS:
        if column not in payload:
            errors.append(f"Payload thiếu cột: {column}")

    so_hieu = str(payload.get("Số hiệu", "")).strip()
    ten_van_ban = str(payload.get("Tên văn bản", "")).strip()

    if not so_hieu:
        errors.append("Payload thiếu Số hiệu.")

    if not ten_van_ban:
        errors.append("Payload thiếu Tên văn bản.")

    return errors


def check_luoc_do() -> list[str]:
    errors = []

    luoc_do = load_json(LUOC_DO_FILE)

    relationships = luoc_do.get("quan_he_phap_ly_theo_luoc_do", {})

    if not isinstance(relationships, dict):
        errors.append("extracted_luocdo_live.json thiếu quan_he_phap_ly_theo_luoc_do.")
        return errors

    if not relationships:
        errors.append("Không có dữ liệu quan hệ pháp lý từ Lược đồ.")

    return errors


def main():
    print("Đang kiểm tra cấu hình Bước 06...")
    print()

    checks = {
        ".env": check_env,
        "config/scan_config.json": check_scan_config,
        "output/vbqppl_nhap_payload.json": check_payload,
        "output/extracted_luocdo_live.json": check_luoc_do,
    }

    all_errors = []

    for name, check_func in checks.items():
        print(f"Kiểm tra: {name}")

        try:
            errors = check_func()

            if errors:
                print("  Có lỗi:")
                for error in errors:
                    print(f"  - {error}")

                all_errors.extend(errors)
            else:
                print("  OK")

        except Exception as exc:
            message = f"{name}: {exc}"
            print(f"  Lỗi: {message}")
            all_errors.append(message)

        print()

    if all_errors:
        print("=" * 80)
        print("KẾT QUẢ: CẤU HÌNH CHƯA ĐẠT")
        print("=" * 80)

        for error in all_errors:
            print(f"- {error}")

        raise SystemExit(1)

    print("=" * 80) 
    print("KẾT QUẢ: CẤU HÌNH ĐẠT")
    print("=" * 80)
    print("Có thể chuyển sang bước tiếp theo: xây crawler danh sách văn bản theo lĩnh vực.")


if __name__ == "__main__":
    main()
from pathlib import Path
import json
from datetime import datetime


INPUT_FILE = Path("output/extracted_luocdo_live.json")
OUTPUT_FILE = Path("output/vbqppl_nhap_payload.json")


SHEET_COLUMNS = [
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


PRIMARY_RELATIONSHIP_MAPPING = {
    "Văn bản căn cứ": "Gợi ý căn cứ pháp lý",
}


OFFICIAL_RELATIONSHIP_COLUMNS = [
    "Căn cứ pháp lý",
    "Hướng dẫn thực hiện",
    "Sửa đổi, bổ sung cho",
    "Sửa đổi, bổ sung bởi",
]


def unique_list(values: list[str]) -> list[str]:
    result = []

    for value in values:
        value = str(value).strip()

        if value and value not in result:
            result.append(value)

    return result


def get_relationship(relationships: dict, heading: str) -> dict:
    data = relationships.get(heading, {})

    if not isinstance(data, dict):
        return {}

    return data


def get_primary_numbers_from_heading(relationships: dict, heading: str) -> list[str]:
    """
    Lấy số hiệu chính của từng card trong một headline Lược đồ.

    Nguyên tắc:
    - Ưu tiên item["so_hieu_chinh"].
    - Không lấy toàn bộ item["so_hieu_tim_duoc"], vì có thể chứa số hiệu được nhắc trong tên văn bản.
    - Fallback chỉ dùng khi dữ liệu bước 03 chưa có so_hieu_chinh.
    """
    data = get_relationship(relationships, heading)

    result = []

    items = data.get("items", [])

    for item in items:
        if not isinstance(item, dict):
            continue

        primary_number = str(item.get("so_hieu_chinh", "")).strip()

        if primary_number:
            result.append(primary_number)
            continue

        # Fallback cho trường hợp file bước 03 cũ chưa có so_hieu_chinh.
        item_numbers = item.get("so_hieu_tim_duoc", [])

        if isinstance(item_numbers, list) and item_numbers:
            result.append(str(item_numbers[0]).strip())

    # Fallback cuối cùng: nếu không có items, lấy số hiệu cấp cha.
    # Trường hợp này chỉ dùng để tránh payload rỗng khi dữ liệu bước 03 thiếu cấu trúc.
    if not result:
        parent_numbers = data.get("so_hieu_tim_duoc", [])

        if isinstance(parent_numbers, list):
            result.extend(parent_numbers)

    return unique_list(result)


def join_primary_numbers(relationships: dict, heading: str) -> str:
    numbers = get_primary_numbers_from_heading(relationships, heading)
    return "\n".join(numbers)


def get_items_from_heading(relationships: dict, heading: str) -> list[dict]:
    data = get_relationship(relationships, heading)
    items = data.get("items", [])

    if not isinstance(items, list):
        return []

    result = []

    for item in items:
        if not isinstance(item, dict):
            continue

        text = str(item.get("noi_dung", "")).strip()
        primary_number = str(item.get("so_hieu_chinh", "")).strip()

        if not text and not primary_number:
            continue

        result.append({
            "noi_dung": text,
            "so_hieu_chinh": primary_number,
        })

    return result


def join_item_contents(relationships: dict, heading: str) -> str:
    items = get_items_from_heading(relationships, heading)

    lines = []

    for item in items:
        text = item.get("noi_dung", "")

        if text:
            lines.append(text)

    return "\n".join(lines)


def build_relationship_note(relationships: dict) -> str:
    """
    Ghi chú quan hệ pháp lý dùng để lưu toàn bộ các quan hệ đọc được từ Lược đồ.

    Lưu ý:
    - Ghi chú dùng so_hieu_chinh của từng card.
    - Không dùng toàn bộ số hiệu xuất hiện trong nội dung.
    """
    headings_to_note = [
        "Văn bản được hướng dẫn",
        "Văn bản bị sửa đổi, bổ sung",
        "Văn bản căn cứ",
        "Văn bản dẫn chiếu",
        "Văn bản hướng dẫn",
        "Văn bản sửa đổi, bổ sung",
        "Văn bản thay thế",
        "Văn bản hợp nhất",
        "Văn bản đính chính",
        "Văn bản đình chỉ",
        "Văn bản đình chỉ một phần",
        "Văn bản hết hiệu lực",
        "Văn bản hết hiệu lực một phần",
        "Văn bản quy định hết hiệu lực",
        "Văn bản quy định hết hiệu lực một phần",
    ]

    note_blocks = []

    for heading in headings_to_note:
        data = get_relationship(relationships, heading)

        if not data:
            continue

        items = get_items_from_heading(relationships, heading)
        primary_numbers = get_primary_numbers_from_heading(relationships, heading)

        if not items and not primary_numbers:
            continue

        block_lines = [f"[{heading}]"]

        count = data.get("so_luong_theo_luatvietnam")

        if count is not None:
            block_lines.append(f"Số lượng theo LuatVietnam: {count}")

        if items:
            for item in items:
                primary_number = item.get("so_hieu_chinh", "")
                text = item.get("noi_dung", "")

                if primary_number and text:
                    block_lines.append(f"- {primary_number}: {text}")
                elif primary_number:
                    block_lines.append(f"- {primary_number}")
                elif text:
                    block_lines.append(f"- {text}")
        else:
            for number in primary_numbers:
                block_lines.append(f"- {number}")

        note_blocks.append("\n".join(block_lines))

    return "\n\n".join(note_blocks)


def build_python_note(relationships: dict) -> str:
    can_cu_numbers = get_primary_numbers_from_heading(
        relationships,
        "Văn bản căn cứ",
    )

    return (
        "Dữ liệu được trích xuất từ Lược đồ LuatVietnam. "
        "Bước 04 chỉ chuẩn hóa dữ liệu nháp. "
        "Các cột quan hệ pháp lý chính thức chưa được ghi vì chưa đối chiếu ID VĂN BẢN. "
        f"Số văn bản căn cứ gợi ý: {len(can_cu_numbers)}."
    )


def validate_payload_against_luocdo(relationships: dict) -> list[str]:
    """
    Kiểm tra sơ bộ số lượng card đọc được so với số lượng LuatVietnam công bố.
    Chỉ cảnh báo, không dừng chương trình.
    """
    warnings = []

    for heading, data in relationships.items():
        if not isinstance(data, dict):
            continue

        count = data.get("so_luong_theo_luatvietnam")
        items = data.get("items", [])

        if count is None:
            continue

        if not isinstance(items, list):
            items = []

        if count != len(items):
            warnings.append(
                f"[{heading}] LuatVietnam ghi {count}, Python đọc được {len(items)} card."
            )

    return warnings


def build_payload(raw: dict) -> dict:
    current_doc = raw.get("van_ban_dang_xem", {}) or {}
    relationships = raw.get("quan_he_phap_ly_theo_luoc_do", {}) or {}

    payload = {
        # Nhóm ID và phân loại nội bộ.
        # Bước 04 chưa sinh ID chính thức và chưa tự phân loại nội bộ.
        "ID VĂN BẢN": "",
        "Lĩnh vực": "",
        "Chủ đề": "",
        "Mục": "",
        "Mức độ tác động": "",
        "Bộ phận chủ trì": "",

        # Nhóm thông tin văn bản đang xem.
        "Loại văn bản": current_doc.get("loai_van_ban", ""),
        "Tên văn bản": current_doc.get("ten_van_ban", ""),
        "Số hiệu": current_doc.get("so_hieu", ""),
        "Ngày hiệu lực": current_doc.get("ngay_hieu_luc", ""),
        "Link Văn bản": raw.get("url", ""),

        # 4 cột quan hệ chính thức.
        # Bước 04 để trống. Bước 05 mới ghi ID VĂN BẢN sau khi đối chiếu.
        "Căn cứ pháp lý": "",
        "Hướng dẫn thực hiện": "",
        "Sửa đổi, bổ sung cho": "",
        "Sửa đổi, bổ sung bởi": "",

        # Dữ liệu căn cứ từ Lược đồ.
        "Nội dung căn cứ": join_item_contents(
            relationships,
            "Văn bản căn cứ",
        ),
        "Gợi ý căn cứ pháp lý": join_primary_numbers(
            relationships,
            "Văn bản căn cứ",
        ),

        # Bước 04 chưa đối chiếu với VBQPPL nên chưa xác định văn bản chưa có trong danh mục.
        "Văn bản căn cứ chưa có trong danh mục": "",

        # Trạng thái.
        "Trạng thái quan hệ pháp lý": "Đã trích xuất Lược đồ - Chưa đối chiếu ID",
        "Trạng thái duyệt": "Chờ kiểm tra",
        "Trạng thái xử lý": "Chờ kiểm tra tự động",

        # Log.
        "Nguồn dữ liệu": "LuatVietnam",
        "Ngày Python quét": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "Ghi chú Python": build_python_note(relationships),

        # Ghi chú tổng hợp toàn bộ quan hệ pháp lý đọc được từ Lược đồ.
        "Ghi chú quan hệ pháp lý": build_relationship_note(relationships),
    }

    ordered_payload = {}

    for column in SHEET_COLUMNS:
        ordered_payload[column] = payload.get(column, "")

    return ordered_payload


def print_payload_summary(payload: dict, warnings: list[str]):
    print("Đã chuẩn hóa dữ liệu cho VBQPPL_Nhap.")
    print()
    print("THÔNG TIN VĂN BẢN")
    print(f"Số hiệu: {payload.get('Số hiệu', '')}")
    print(f"Tên văn bản: {payload.get('Tên văn bản', '')}")
    print(f"Loại văn bản: {payload.get('Loại văn bản', '')}")
    print(f"Ngày hiệu lực: {payload.get('Ngày hiệu lực', '')}")
    print(f"Link Văn bản: {payload.get('Link Văn bản', '')}")

    print()
    print("DỮ LIỆU CĂN CỨ")
    print("Nội dung căn cứ:")
    print(payload.get("Nội dung căn cứ", ""))

    print()
    print("Gợi ý căn cứ pháp lý:")
    print(payload.get("Gợi ý căn cứ pháp lý", ""))

    print()
    print("TRẠNG THÁI")
    print(f"Trạng thái quan hệ pháp lý: {payload.get('Trạng thái quan hệ pháp lý', '')}")
    print(f"Trạng thái duyệt: {payload.get('Trạng thái duyệt', '')}")
    print(f"Trạng thái xử lý: {payload.get('Trạng thái xử lý', '')}")

    print()
    print("Lưu ý:")
    for column in OFFICIAL_RELATIONSHIP_COLUMNS:
        print(f"- {column}: chưa ghi ở bước 04")

    print("- Các cột trên sẽ được ghi ở bước 05 sau khi đối chiếu ID VĂN BẢN.")

    if warnings:
        print()
        print("CẢNH BÁO KIỂM TRA DỮ LIỆU")
        for warning in warnings:
            print(f"- {warning}")


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            "Chưa có file output/extracted_luocdo_live.json. "
            "Hãy chạy 03_extract_luocdo_live.py trước."
        )

    raw = json.loads(INPUT_FILE.read_text(encoding="utf-8"))

    relationships = raw.get("quan_he_phap_ly_theo_luoc_do", {}) or {}
    warnings = validate_payload_against_luocdo(relationships)

    payload = build_payload(raw)

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print_payload_summary(payload, warnings)

    print()
    print(f"Đã lưu payload vào: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
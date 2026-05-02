from pathlib import Path
import os
import re
import json

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


load_dotenv()

AUTH_FILE = Path("auth/luatvietnam_state.json")
OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "extracted_luocdo_live.json"

TEST_DOCUMENT_URL = os.getenv("LUATVN_TEST_DOCUMENT_URL")


LUOC_DO_HEADINGS = [
    "Văn bản được hướng dẫn",
    "Văn bản bị sửa đổi, bổ sung",
    "Văn bản hết hiệu lực",
    "Văn bản bị quy định hết hiệu lực",
    "Văn bản hết hiệu lực một phần",
    "Văn bản đang xem",
    "Văn bản tiếng Anh",
    "Văn bản căn cứ",
    "Văn bản dẫn chiếu",
    "Văn bản hướng dẫn",
    "Văn bản sửa đổi, bổ sung",
    "Văn bản thay thế",
    "Văn bản quy định hết hiệu lực",
    "Văn bản quy định hết hiệu lực một phần",
    "Văn bản hợp nhất",
    "Văn bản đính chính",
    "Văn bản đình chỉ",
    "Văn bản đình chỉ một phần",
]


STATUS_VALUES = [
    "Chưa áp dụng",
    "Còn Hiệu lực",
    "Còn hiệu lực",
    "Hết hiệu lực",
    "Hết hiệu lực một phần",
    "Hết hiệu lực 1 phần",
    "Đã sửa đổi",
    "Đã đính chính",
    "Không còn phù hợp",
]


DOC_NUMBER_PATTERN = re.compile(
    r"\b\d{1,4}/\d{4}/[A-ZÀ-ỸĐ][A-ZÀ-ỸĐ0-9.-]*\b",
    re.IGNORECASE,
)


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = text.replace("\u2010", "-")
    text = text.replace("\u2011", "-")
    text = text.replace("\u2012", "-")
    text = text.replace("\u2013", "-")
    text = text.replace("\u2014", "-")
    text = text.replace("−", "-")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def normalize_doc_number_text(text: str) -> str:
    text = normalize_text(text)

    text = re.sub(r"(\d{1,4})\s*/\s*(\d{4})\s*/\s*", r"\1/\2/", text)

    text = re.sub(r"NĐ\s*-\s*CP", "NĐ-CP", text, flags=re.IGNORECASE)
    text = re.sub(r"ND\s*-\s*CP", "ND-CP", text, flags=re.IGNORECASE)
    text = re.sub(r"TT\s*-\s*", "TT-", text, flags=re.IGNORECASE)
    text = re.sub(r"TTLT\s*-\s*", "TTLT-", text, flags=re.IGNORECASE)
    text = re.sub(r"QĐ\s*-\s*", "QĐ-", text, flags=re.IGNORECASE)
    text = re.sub(r"NQ\s*-\s*", "NQ-", text, flags=re.IGNORECASE)
    text = re.sub(r"VBHN\s*-\s*", "VBHN-", text, flags=re.IGNORECASE)

    return text


def extract_doc_numbers(text: str) -> list[str]:
    text = normalize_doc_number_text(text)
    found = DOC_NUMBER_PATTERN.findall(text)

    result = []
    for item in found:
        item = item.strip()
        if item not in result:
            result.append(item)

    return result

def extract_primary_doc_number(text: str) -> str:
    """
    Xác định số hiệu chính của 01 card trong Lược đồ LuatVietnam.

    Nguyên tắc:
    - Card dạng "Nghị định 261/2025/NĐ-CP ..." thì lấy 261/2025/NĐ-CP.
    - Card dạng "... của Quốc hội, số 43/2024/QH15" thì lấy 43/2024/QH15.
    - Không lấy các số hiệu được nhắc trong tên văn bản.
    """
    text = normalize_doc_number_text(text)
    numbers = extract_doc_numbers(text)

    if not numbers:
        return ""

    doc_number_regex = r"\d{1,4}/\d{4}/[A-ZÀ-ỸĐ][A-ZÀ-ỸĐ0-9.\-]*"

    # 1. Nếu card bắt đầu bằng loại văn bản + số hiệu
    # Ví dụ: "Nghị định 261/2025/NĐ-CP ..."
    start_match = re.search(
        rf"^(Bộ luật|Luật|Nghị định|Thông tư|Thông tư liên tịch|Quyết định|Nghị quyết|Chỉ thị)\s+({doc_number_regex})",
        text,
        flags=re.IGNORECASE,
    )

    if start_match:
        return start_match.group(2).strip()

    # 2. Ưu tiên số hiệu nằm sau cụm cơ quan ban hành
    # Ví dụ: "... của Quốc hội, số 43/2024/QH15"
    authority_patterns = [
        rf"của\s+Quốc\s+hội,?\s+số\s+({doc_number_regex})",
        rf"của\s+Chính\s+phủ,?\s+số\s+({doc_number_regex})",
        rf"của\s+Thủ\s+tướng\s+Chính\s+phủ,?\s+số\s+({doc_number_regex})",
        rf"của\s+Bộ\s+[^,;\n]+,?\s+số\s+({doc_number_regex})",
        rf"của\s+[^,;\n]+,?\s+số\s+({doc_number_regex})",
    ]

    for pattern in authority_patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)

        if matches:
            return matches[-1].strip()

    # 3. Nếu có nhiều cụm ", số XXX", lấy cụm cuối
    # Trường hợp: "... của Quốc hội, số 43/2024/QH15"
    so_matches = re.findall(
        rf"(?:,\s*)số\s+({doc_number_regex})",
        text,
        flags=re.IGNORECASE,
    )

    if so_matches:
        return so_matches[-1].strip()

    # 4. Fallback cuối cùng: lấy số hiệu cuối cùng
    # Vì với các Luật sửa đổi phức tạp, số hiệu chính thường ở cuối card.
    return numbers[-1].strip()
    """
    Xác định số hiệu chính của một ô/card trong Lược đồ LuatVietnam.

    Nguyên tắc ưu tiên:

    1. Nếu card có dạng:
       "... của Quốc hội, số 43/2024/QH15"
       "... của Chính phủ, số 136/2026/NĐ-CP"
       "... của Bộ Giáo dục và Đào tạo, số 33/2026/TT-BGDĐT"
       thì lấy số hiệu sau cụm "của [cơ quan], số ...".

    2. Nếu card bắt đầu bằng:
       "Nghị định 261/2025/NĐ-CP ..."
       "Thông tư 33/2026/TT-BGDĐT ..."
       "Nghị quyết 16/2026/NQ-CP ..."
       thì lấy số hiệu đầu tiên sau loại văn bản.

    3. Nếu không nhận diện được theo 2 cách trên,
       lấy số hiệu cuối cùng có trong card.
    """
    text = normalize_doc_number_text(text)
    numbers = extract_doc_numbers(text)

    if not numbers:
        return ""

    doc_number_regex = r"\d{1,4}/\d{4}/[A-ZÀ-ỸĐ][A-ZÀ-ỸĐ0-9.\-]*"

    # Ưu tiên cao nhất:
    # "... của Quốc hội, số 43/2024/QH15"
    # "... của Chính phủ, số 136/2026/NĐ-CP"
    authority_number_matches = re.findall(
        rf"của\s+[^,;\n]{{2,120}},?\s+số\s+({doc_number_regex})",
        text,
        flags=re.IGNORECASE,
    )

    if authority_number_matches:
        return authority_number_matches[-1].strip()

    # Ưu tiên thứ hai:
    # "Nghị định 261/2025/NĐ-CP ..."
    # "Thông tư 33/2026/TT-BGDĐT ..."
    # "Luật 31/2024/QH15 ..."
    start_match = re.search(
        rf"^(Bộ luật|Luật|Nghị định|Thông tư|Thông tư liên tịch|Quyết định|Nghị quyết|Chỉ thị)\s+({doc_number_regex})",
        text,
        flags=re.IGNORECASE,
    )

    if start_match:
        return start_match.group(2).strip()

    # Fallback:
    # Với văn bản dạng Luật sửa đổi phức tạp, số hiệu chính thường nằm cuối card.
    return numbers[-1].strip()
    """
    Xác định số hiệu chính của một ô/card trong Lược đồ LuatVietnam.

    Nguyên tắc:
    1. Nếu có cụm ', số <số hiệu>' hoặc 'của Quốc hội, số <số hiệu>',
       ưu tiên lấy số hiệu cuối cùng sau chữ 'số'.
       Ví dụ:
       '... của Quốc hội, số 43/2024/QH15'
       → 43/2024/QH15

    2. Nếu văn bản bắt đầu bằng loại văn bản + số hiệu,
       lấy số hiệu đầu tiên.
       Ví dụ:
       'Nghị định 261/2025/NĐ-CP của Chính phủ...'
       → 261/2025/NĐ-CP

    3. Nếu không xác định được theo 2 cách trên,
       lấy số hiệu đầu tiên tìm được.
    """
    text = normalize_doc_number_text(text)
    numbers = extract_doc_numbers(text)

    if not numbers:
        return ""

    # Ưu tiên các trường hợp có dạng: ", số 43/2024/QH15"
    matches_after_so = re.findall(
        r"(?:,\s*)?số\s+(\d{1,4}/\d{4}/[A-ZÀ-ỸĐ][A-ZÀ-ỸĐ0-9.\-]*)",
        text,
        flags=re.IGNORECASE,
    )

    if matches_after_so:
        # Lấy số hiệu cuối cùng sau chữ "số"
        # để tránh lấy nhầm các số hiệu được nhắc trong tên văn bản.
        return matches_after_so[-1].strip()

    # Trường hợp văn bản bắt đầu bằng loại văn bản + số hiệu
    start_match = re.search(
        r"^(Nghị định|Thông tư|Quyết định|Nghị quyết|Luật|Bộ luật)\s+"
        r"(\d{1,4}/\d{4}/[A-ZÀ-ỸĐ][A-ZÀ-ỸĐ0-9.\-]*)",
        text,
        flags=re.IGNORECASE,
    )

    if start_match:
        return start_match.group(2).strip()

    return numbers[0]

def safe_goto(page, url: str):
    try:
        page.goto(url, wait_until="networkidle", timeout=60000)
    except PlaywrightTimeoutError:
        print("Trang tải quá lâu. Vẫn tiếp tục xử lý nội dung hiện có...")


def click_luoc_do_tab(page) -> bool:
    print("\nĐang chuyển sang tab Lược đồ...")

    try:
        page.get_by_text("Lược đồ", exact=True).click(timeout=10000)
        page.wait_for_timeout(3000)
        return True
    except Exception:
        pass

    try:
        page.locator("text=Lược đồ").first.click(timeout=10000)
        page.wait_for_timeout(3000)
        return True
    except Exception as e:
        print("Không bấm được tab Lược đồ.")
        print(f"Lỗi: {e}")
        return False


def expand_luoc_do_sections(page):
    """
    Mở các nhóm Lược đồ có số lượng > 0.
    """
    print("\nĐang mở các nhóm Lược đồ có dữ liệu...")

    for heading in LUOC_DO_HEADINGS:
        try:
            pattern = re.compile(rf"^{re.escape(heading)}\s*\([1-9][0-9]*\)$")
            locator = page.get_by_text(pattern).first

            if locator.count() == 0:
                continue

            locator.scroll_into_view_if_needed(timeout=3000)
            locator.click(timeout=3000)
            page.wait_for_timeout(1000)

            print(f"Đã thử mở nhóm: {heading}")

        except Exception:
            pass

    page.wait_for_timeout(3000)


def get_body_lines(page) -> list[str]:
    body_text = page.locator("body").inner_text(timeout=10000)
    body_text = normalize_text(body_text)

    lines = []
    for line in body_text.splitlines():
        line = normalize_text(line)
        if line:
            lines.append(line)

    return lines


def find_value_after_label(lines: list[str], label: str) -> str:
    """
    Hỗ trợ 2 dạng:

    Số hiệu: 136/2026/NĐ-CP

    hoặc:

    Số hiệu:
    136/2026/NĐ-CP
    """
    label_lower = label.lower()

    for index, line in enumerate(lines):
        lower = line.lower()

        if lower.startswith(label_lower + ":"):
            value = line.split(":", 1)[1].strip()

            if value:
                return value

            if index + 1 < len(lines):
                return lines[index + 1].strip()

    return ""


def extract_status(lines: list[str]) -> str:
    """
    Chỉ lấy trạng thái thật.
    Không lấy dòng tooltip giải thích của LuatVietnam.
    """
    joined_text = "\n".join(lines)

    for line in lines:
        if not line.startswith("Tình trạng hiệu lực:"):
            continue

        if "Cho biết trạng thái hiệu lực" in line:
            continue

        value = line.split(":", 1)[1].strip()

        for status in STATUS_VALUES:
            if status.lower() in value.lower():
                return status

        if value:
            return value

    for status in STATUS_VALUES:
        if status.lower() in joined_text.lower():
            return status

    return ""


def extract_current_document_info(lines: list[str]) -> dict:
    so_hieu = find_value_after_label(lines, "Số hiệu")
    loai_van_ban = find_value_after_label(lines, "Loại văn bản")
    co_quan_ban_hanh = find_value_after_label(lines, "Cơ quan ban hành")
    ngay_ban_hanh = find_value_after_label(lines, "Ngày ban hành")
    ngay_hieu_luc = find_value_after_label(lines, "Hiệu lực")
    linh_vuc = find_value_after_label(lines, "Lĩnh vực")
    tinh_trang = extract_status(lines)

    ten_van_ban = ""

    for line in lines:
        if so_hieu and so_hieu in line and len(line) > len(so_hieu) + 15:
            ten_van_ban = line
            break

    if not ten_van_ban:
        for line in lines:
            if (
                "Nghị định" in line
                or "Thông tư" in line
                or "Luật " in line
                or "Quyết định" in line
            ) and len(line) > 30:
                ten_van_ban = line
                break

    return {
        "so_hieu": so_hieu,
        "ten_van_ban": ten_van_ban,
        "loai_van_ban": loai_van_ban,
        "co_quan_ban_hanh": co_quan_ban_hanh,
        "ngay_ban_hanh": ngay_ban_hanh,
        "ngay_hieu_luc": ngay_hieu_luc,
        "linh_vuc_luatvietnam": linh_vuc,
        "tinh_trang_hieu_luc": tinh_trang,
    }


def extract_dom_positions(page) -> dict:
    """
    Đọc trực tiếp DOM đang hiển thị.

    Trả về:
    - headings: vị trí các headline trong Lược đồ.
    - items: các phần tử có chứa số hiệu văn bản.
    """
    raw = page.evaluate(
        """
        (headings) => {
            function norm(s) {
                return (s || '')
                    .replace(/\\u00a0/g, ' ')
                    .replace(/[ \\t]+/g, ' ')
                    .replace(/\\n{3,}/g, '\\n\\n')
                    .trim();
            }

            function escapeRegExp(s) {
                return s.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
            }

            function hasDocNo(s) {
                return /\\b\\d{1,4}\\s*\\/\\s*\\d{4}\\s*\\/\\s*[A-ZÀ-ỸĐ][A-ZÀ-ỸĐ0-9.\\-]*/i.test(s);
            }

            function isVisible(el) {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);

                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    style.opacity !== '0'
                );
            }

            const elements = Array.from(document.querySelectorAll('body *'));

            const headingResults = [];

            for (const el of elements) {
                if (!isVisible(el)) continue;

                const text = norm(el.innerText || el.textContent || '');
                if (!text) continue;

                const flatText = text.replace(/\\n/g, ' ');

                for (const heading of headings) {
                    const re = new RegExp(
                        '^' + escapeRegExp(heading) + '\\\\s*\\\\(([0-9]+)\\\\)$',
                        'i'
                    );

                    const match = flatText.match(re);

                    if (!match) continue;

                    const rect = el.getBoundingClientRect();

                    headingResults.push({
                        heading: heading,
                        count: Number(match[1]),
                        text: flatText,
                        top: rect.top + window.scrollY,
                        left: rect.left + window.scrollX,
                        width: rect.width,
                        height: rect.height
                    });
                }
            }

            const itemResults = [];

            const itemElements = Array.from(
                document.querySelectorAll('a, li, p, span, div')
            );

            for (const el of itemElements) {
                if (!isVisible(el)) continue;

                const text = norm(el.innerText || el.textContent || '');
                if (!text) continue;
                if (!hasDocNo(text)) continue;

                if (text.includes('LuatVietnam')) continue;
                if (text.includes('Tổng đài')) continue;
                if (text.includes('Tìm kiếm')) continue;
                if (text.length > 2000) continue;

                let childHasDocNo = false;

                for (const child of Array.from(el.children || [])) {
                    const childText = norm(child.innerText || child.textContent || '');
                    if (hasDocNo(childText)) {
                        childHasDocNo = true;
                        break;
                    }
                }

                if (childHasDocNo && el.tagName.toLowerCase() !== 'a') {
                    continue;
                }

                const rect = el.getBoundingClientRect();

                itemResults.push({
                    text: text,
                    tag: el.tagName,
                    top: rect.top + window.scrollY,
                    left: rect.left + window.scrollX,
                    width: rect.width,
                    height: rect.height
                });
            }

            return {
                headings: headingResults,
                items: itemResults
            };
        }
        """,
        LUOC_DO_HEADINGS,
    )

    return raw


def deduplicate_headings(raw_headings: list[dict]) -> list[dict]:
    result = []
    seen = set()

    for item in raw_headings:
        key = (
            item.get("heading"),
            round(float(item.get("top", 0))),
            round(float(item.get("left", 0))),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

    result.sort(key=lambda x: (x.get("top", 0), x.get("left", 0)))

    return result


def deduplicate_items(raw_items: list[dict]) -> list[dict]:
    """
    Khử trùng item theo cả nội dung và vị trí.

    Không được khử trùng chỉ theo text, vì cùng một văn bản có thể xuất hiện
    ở nhiều headline khác nhau trong Lược đồ.

    Ví dụ:
    'Luật Nhà ở của Quốc hội, số 27/2023/QH15'
    có thể xuất hiện ở:
    - Văn bản được hướng dẫn
    - Văn bản căn cứ

    Hai lần xuất hiện này phải được giữ lại vì thuộc 2 quan hệ pháp lý khác nhau.
    """
    result = []
    seen = set()

    for item in raw_items:
        text = normalize_text(item.get("text", ""))

        if not text:
            continue

        numbers = extract_doc_numbers(text)

        if not numbers:
            continue

        top = round(float(item.get("top", 0)))
        left = round(float(item.get("left", 0)))

        # Khử trùng theo text + vị trí, không khử trùng chỉ theo text
        key = (
            text,
            top,
            left,
        )

        if key in seen:
            continue

        seen.add(key)

        result.append({
            "noi_dung": text,
            "so_hieu_tim_duoc": numbers,
            "tag": item.get("tag"),
            "top": item.get("top"),
            "left": item.get("left"),
            "width": item.get("width"),
            "height": item.get("height"),
        })

    result.sort(key=lambda x: (x.get("top", 0), x.get("left", 0)))

    return result
def get_primary_doc_number(text: str) -> str:
    """
    Lấy số hiệu chính của item.
    Tạm thời lấy số hiệu đầu tiên xuất hiện trong dòng văn bản.
    Ví dụ:
    - Nghị định 261/2025/NĐ-CP ... -> 261/2025/NĐ-CP
    - Nghị định 100/2024/NĐ-CP ... -> 100/2024/NĐ-CP
    """
    numbers = extract_doc_numbers(text)
    if numbers:
        return numbers[0]
    return ""


def should_skip_relationship_item(item: dict, current_doc_so_hieu: str) -> bool:
    """
    Loại bỏ các item không phải văn bản quan hệ pháp lý thực sự.
    """
    text = normalize_text(item.get("noi_dung", ""))
    numbers = item.get("so_hieu_tim_duoc", [])

    if not text:
        return True

    # Bỏ dòng metadata của văn bản đang xem
    metadata_prefixes = [
        "Số hiệu:",
        "Tên văn bản:",
        "Loại văn bản:",
        "Cơ quan ban hành:",
        "Ngày ban hành:",
        "Hiệu lực:",
        "Ngày hiệu lực:",
        "Lĩnh vực:",
        "Tình trạng hiệu lực:",
    ]

    if any(text.startswith(prefix) for prefix in metadata_prefixes):
        return True

    # Bỏ chính văn bản đang xem
    if current_doc_so_hieu and current_doc_so_hieu in numbers:
        return True

    # Bỏ các đoạn quá dài có khả năng là block tổng hợp/trang
    if len(text) > 1200:
        return True

    # Bỏ mô tả/tooltip của LuatVietnam
    skip_phrases = [
        "là văn bản ban hành trước",
        "là các văn bản ban hành trước",
        "được nêu trong nội dung của",
        "bị sửa đổi, bổ sung là văn bản",
    ]

    if any(phrase in text for phrase in skip_phrases):
        return True

    return False

def assign_items_to_headings(
    headings: list[dict],
    items: list[dict],
    current_doc_so_hieu: str = "",
) -> dict:
    """
    Gán mỗi item văn bản về headline gần nhất phía trên cùng cột.

    Nguyên tắc:
    - Không lấy văn bản đang xem.
    - Không lấy dòng metadata.
    - Không lấy tooltip/mô tả headline.
    - Mỗi nhóm chỉ lấy tối đa đúng số lượng theo LuatVietnam.
    """
    relationships = {}

    useful_headings = [
        h for h in headings
        if h.get("count", 0) > 0
    ]

    for item in items:
        if should_skip_relationship_item(item, current_doc_so_hieu):
            continue

        item_top = float(item.get("top", 0))
        item_left = float(item.get("left", 0))

        candidate_headings = []

        for heading in useful_headings:
            heading_top = float(heading.get("top", 0))
            heading_left = float(heading.get("left", 0))

            if item_top <= heading_top:
                continue

            vertical_distance = item_top - heading_top
            horizontal_distance = abs(item_left - heading_left)

            if vertical_distance > 1200:
                continue

            if horizontal_distance > 500:
                continue

            candidate_headings.append({
                **heading,
                "vertical_distance": vertical_distance,
                "horizontal_distance": horizontal_distance,
            })

        if not candidate_headings:
            continue

        candidate_headings.sort(
            key=lambda h: (
                h["vertical_distance"],
                h["horizontal_distance"],
            )
        )

        selected_heading = candidate_headings[0]
        heading_name = selected_heading.get("heading")
        heading_count = selected_heading.get("count")

        if heading_name == "Văn bản đang xem":
            continue

        if heading_name not in relationships:
            relationships[heading_name] = {
                "so_luong_theo_luatvietnam": heading_count,
                "items": [],
                "so_hieu_tim_duoc": [],
            }

        # Nếu đã đủ số lượng theo LuatVietnam thì không thêm nữa
        existing_items = relationships[heading_name]["items"]

        if heading_count and len(existing_items) >= heading_count:
            continue

        text = item["noi_dung"]
        primary_number = extract_primary_doc_number(text)

        if not primary_number:
            continue

        existing_primary_numbers = [
            x.get("so_hieu_chinh", "")
            for x in existing_items
        ]

        if primary_number in existing_primary_numbers:
            continue

        relationships[heading_name]["items"].append({
            "noi_dung": text,
            "so_hieu_chinh": primary_number,
            "so_hieu_tim_duoc": item["so_hieu_tim_duoc"],
        })

        if primary_number not in relationships[heading_name]["so_hieu_tim_duoc"]:
            relationships[heading_name]["so_hieu_tim_duoc"].append(primary_number)

    return relationships
    """
    Gán mỗi item văn bản về headline gần nhất phía trên cùng cột.

    Nguyên tắc:
    - Item phải nằm dưới headline.
    - Khoảng cách ngang không quá xa.
    - Chọn headline gần nhất phía trên.
    """
    relationships = {}

    useful_headings = [
        h for h in headings
        if h.get("count", 0) > 0
    ]

    for item in items:
        item_top = float(item.get("top", 0))
        item_left = float(item.get("left", 0))

        candidate_headings = []

        for heading in useful_headings:
            heading_top = float(heading.get("top", 0))
            heading_left = float(heading.get("left", 0))

            if item_top <= heading_top:
                continue

            vertical_distance = item_top - heading_top
            horizontal_distance = abs(item_left - heading_left)

            if vertical_distance > 1200:
                continue

            if horizontal_distance > 500:
                continue

            candidate_headings.append({
                **heading,
                "vertical_distance": vertical_distance,
                "horizontal_distance": horizontal_distance,
            })

        if not candidate_headings:
            continue

        candidate_headings.sort(
            key=lambda h: (
                h["vertical_distance"],
                h["horizontal_distance"],
            )
        )

        selected_heading = candidate_headings[0]
        heading_name = selected_heading.get("heading")

        if heading_name == "Văn bản đang xem":
            continue

        if heading_name not in relationships:
            relationships[heading_name] = {
                "so_luong_theo_luatvietnam": selected_heading.get("count"),
                "items": [],
                "so_hieu_tim_duoc": [],
            }

        existing_texts = [
            x.get("noi_dung", "")
            for x in relationships[heading_name]["items"]
        ]

        if item["noi_dung"] in existing_texts:
            continue

        relationships[heading_name]["items"].append({
            "noi_dung": item["noi_dung"],
            "so_hieu_tim_duoc": item["so_hieu_tim_duoc"],
        })

        if primary_number not in relationships[heading_name]["so_hieu_tim_duoc"]:
            relationships[heading_name]["so_hieu_tim_duoc"].append(primary_number)

    return relationships


def main():
    test_extract_primary_doc_number()
    if not AUTH_FILE.exists():
        raise FileNotFoundError(
            "Chưa tìm thấy file auth/luatvietnam_state.json. "
            "Hãy chạy 01_save_session.py trước."
        )

    if not TEST_DOCUMENT_URL:
        raise ValueError(
            "Thiếu LUATVN_TEST_DOCUMENT_URL trong file .env. "
            "Hãy mở file .env và điền link văn bản mẫu."
        )

    OUTPUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=100,
        )

        context = browser.new_context(
            storage_state=str(AUTH_FILE)
        )

        page = context.new_page()

        print("Đang mở văn bản LuatVietnam bằng session đã lưu...")
        print(f"URL: {TEST_DOCUMENT_URL}")

        safe_goto(page, TEST_DOCUMENT_URL)

        opened = click_luoc_do_tab(page)

        if not opened:
            browser.close()
            return

        expand_luoc_do_sections(page)

        lines = get_body_lines(page)
        current_doc = extract_current_document_info(lines)

        dom_data = extract_dom_positions(page)
        headings = deduplicate_headings(dom_data.get("headings", []))
        items = deduplicate_items(dom_data.get("items", []))

        relationships = assign_items_to_headings(
            headings,
            items,
            current_doc.get("so_hieu", ""),
)

        result = {
            "nguon_du_lieu": "LuatVietnam - Lược đồ - DOM live",
            "url": page.url,
            "van_ban_dang_xem": current_doc,
            "quan_he_phap_ly_theo_luoc_do": relationships,
            "debug": {
                "so_headline_tim_duoc": len(headings),
                "so_item_co_so_hieu_tim_duoc": len(items),
                "headings": headings,
                "items": items,
            },
        }

        OUTPUT_FILE.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print("\nĐã tách dữ liệu từ Lược đồ LuatVietnam.")

        print("\nTHÔNG TIN VĂN BẢN ĐANG XEM")
        print(f"Số hiệu: {current_doc.get('so_hieu', '')}")
        print(f"Tên văn bản: {current_doc.get('ten_van_ban', '')}")
        print(f"Loại văn bản: {current_doc.get('loai_van_ban', '')}")
        print(f"Cơ quan ban hành: {current_doc.get('co_quan_ban_hanh', '')}")
        print(f"Ngày ban hành: {current_doc.get('ngay_ban_hanh', '')}")
        print(f"Ngày hiệu lực: {current_doc.get('ngay_hieu_luc', '')}")
        print(f"Lĩnh vực LuatVietnam: {current_doc.get('linh_vuc_luatvietnam', '')}")
        print(f"Tình trạng hiệu lực: {current_doc.get('tinh_trang_hieu_luc', '')}")

        print("\nDEBUG")
        print(f"Số headline tìm được: {len(headings)}")
        print(f"Số item có số hiệu tìm được: {len(items)}")

        print("\nQUAN HỆ PHÁP LÝ THEO LƯỢC ĐỒ LUATVIETNAM")

        if not relationships:
            print("Chưa gán được văn bản cụ thể vào từng headline.")
            print("Hãy mở file output/extracted_luocdo_live.json để xem phần debug.")
        else:
            for heading, data in relationships.items():
                count = data.get("so_luong_theo_luatvietnam")

                print(f"\n[{heading}] - Số lượng theo LuatVietnam: {count}")

                for item in data.get("items", []):
                    print("- Nội dung:", item.get("noi_dung", ""))
                    print("  Số hiệu chính:", item.get("so_hieu_chinh", ""))

        print()
        print(f"Đã lưu kết quả vào: {OUTPUT_FILE}")

        input("\nNhấn Enter để đóng trình duyệt... ")

        browser.close()

def test_extract_primary_doc_number():
    sample = (
        "Luật sửa đổi, bổ sung một số điều của Luật Đất đai số 31/2024/QH15, "
        "Luật Nhà ở số 27/2023/QH15, "
        "Luật Kinh doanh bất động sản số 29/2023/QH15 "
        "và Luật Các tổ chức tín dụng số 32/2024/QH15 "
        "của Quốc hội, số 43/2024/QH15"
    )

    print("TEST SỐ HIỆU CHÍNH:", extract_primary_doc_number(sample))

if __name__ == "__main__":
    main()
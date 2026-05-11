from pathlib import Path
import json
import os
import re
import hashlib
import sys
import socket
import ssl
import time
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def setup_utf8_stdio():
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

INPUT_FILE = Path("output/field_document_urls.json")
CONFIG_FILE = Path("config/scan_config.json")
AUTH_FILE = Path("auth/luatvietnam_state.json")
OUTPUT_FILE = Path("output/vbqppl_nhap_batch_payload.json")
OUTPUT_REQUEST_DEBUG_FILE = Path("output/apps_script_request_debug.json")
SHEET_SCHEMA_FILE = Path("config/sheet_schema.json")
ENV_FILE = Path(".env")

LUOC_DO_HEADINGS = [
    "Văn bản căn cứ",
    "Văn bản được căn cứ",
    "Văn bản hướng dẫn",
    "Văn bản được hướng dẫn",
    "Văn bản sửa đổi, bổ sung",
    "Văn bản bị sửa đổi, bổ sung",
    "Văn bản thay thế",
    "Văn bản bị thay thế",
    "Văn bản hết hiệu lực",
    "Văn bản liên quan",
]

DEFAULT_SHEET_COLUMNS = [
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
    "Văn bản chưa có trong danh mục",
    "Trạng thái quan hệ pháp lý",
    "Ghi chú quan hệ pháp lý",
    "Nguồn dữ liệu",
    "Ngày Python quét",
    "Ghi chú Python",
]
REQUIRED_COLUMNS = ["ID VĂN BẢN", "Loại văn bản", "Tên văn bản", "Số hiệu", "Ngày hiệu lực", "Link Văn bản", "Trạng thái duyệt", "Trạng thái xử lý"]
OFFICIAL_RELATIONSHIP_COLUMNS = ["Căn cứ pháp lý", "Hướng dẫn thực hiện", "Sửa đổi, bổ sung cho", "Sửa đổi, bổ sung bởi"]
HEADING_TO_COLUMN = {"Văn bản căn cứ": "Căn cứ pháp lý", "Văn bản hướng dẫn": "Hướng dẫn thực hiện", "Văn bản sửa đổi, bổ sung": "Sửa đổi, bổ sung cho", "Văn bản bị sửa đổi, bổ sung": "Sửa đổi, bổ sung bởi"}

DATE_PATTERN = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")
SO_HIEU_PATTERN = re.compile(r"\b\d{1,4}/\d{4}/[A-ZÀ-ỸĐ][A-ZÀ-ỸĐ0-9.\-]*\b", re.IGNORECASE)
SKIP_RELATION_PHRASES = [
    "là văn bản ban hành trước",
    "là các văn bản ban hành trước",
    "được nêu trong nội dung của",
    "bị sửa đổi, bổ sung là văn bản",
]



def normalize_text(value: str) -> str:
    value = str(value or "").replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{2,}", "\n", value)
    return value.strip()


import re

import re

def normalize_so_hieu(value: str) -> str:
    """
    Chuẩn hóa số hiệu văn bản để phục vụ chống trùng.
    Nguyên tắc:
    - Chỉ nắn các mẫu chắc chắn/khá chắc chắn.
    - Mẫu lạ thì giữ nguyên để người dùng kiểm tra tay.
    """
    text = normalize_text(value).upper()

    # Chuẩn hóa khoảng trắng quanh / và -
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\s*-\s*", "-", text)

    # 1. Chỉ nắn các biến thể gần chắc chắn của Thông tư Bộ GDĐT
    bgddt_variants = {
        "TT-BGDĐT",
        "TT-BGĐT",
        "TT-BGDDT",
        "TT-BGDT",
        "TT-GDĐT",
        "TT-GDDT",
        "TT-BGD",
    }

    parts = text.split("/")
    if len(parts) >= 3:
        suffix = parts[-1]
        if suffix in bgddt_variants:
            parts[-1] = "TT-BGDĐT"
            text = "/".join(parts)

    # 2. Chuẩn hóa Nghị định
    text = re.sub(r"/N[DĐ][- ]*CP$", "/NĐ-CP", text)

    # 3. Chuẩn hóa Luật / Bộ luật
    text = re.sub(r"/QH\s*(\d+)$", r"/QH\1", text)

    return text


def format_vb_id(number: int) -> str:
    return f"VB{int(number):03d}"



def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_env_file(path: Path = ENV_FILE):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_apps_script_token(config: dict) -> str:
    """
    Ưu tiên lấy token theo thứ tự:
    1) config.APPS_SCRIPT_TOKEN
    2) ENV APPS_SCRIPT_TOKEN
    3) file đường dẫn trong config.APPS_SCRIPT_TOKEN_FILE / ENV APPS_SCRIPT_TOKEN_FILE
    """
    token = normalize_text(config.get("APPS_SCRIPT_TOKEN", "") or os.getenv("APPS_SCRIPT_TOKEN", ""))
    if token:
        return token

    token_file = normalize_text(config.get("APPS_SCRIPT_TOKEN_FILE", "") or os.getenv("APPS_SCRIPT_TOKEN_FILE", ""))
    if token_file and Path(token_file).exists():
        try:
            return normalize_text(Path(token_file).read_text(encoding="utf-8"))
        except Exception:
            return ""
    return ""



def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")



def load_sheet_schema() -> list[str]:
    """
    Đọc schema cột đích từ config/sheet_schema.json (nếu có).
    Format hỗ trợ:
    {
      "sheet_columns": ["ID VĂN BẢN", ...]
    }
    hoặc
    ["ID VĂN BẢN", ...]
    """
    if not SHEET_SCHEMA_FILE.exists():
        return list(DEFAULT_SHEET_COLUMNS)

    try:
        schema = json.loads(SHEET_SCHEMA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return list(DEFAULT_SHEET_COLUMNS)

    if isinstance(schema, dict):
        columns = schema.get("sheet_columns", []) or []
    elif isinstance(schema, list):
        columns = schema
    else:
        columns = []

    normalized_columns = [normalize_text(c) for c in columns if normalize_text(c)]
    return normalized_columns or list(DEFAULT_SHEET_COLUMNS)


def map_external_field_to_internal(field_name: str, config: dict) -> str:
    """
    Map tên lĩnh vực LuatVietnam sang tên lĩnh vực nội bộ trên Google Sheet.
    Nếu không có mapping rõ ràng, trả về rỗng để người dùng chọn trên sidebar.
    """
    normalized = normalize_text(field_name)
    if not normalized:
        return ""

    mapping = config.get("linh_vuc_mapping", {}) or {}
    if not isinstance(mapping, dict):
        return ""

    for k, v in mapping.items():
        if normalize_text(k).lower() == normalized.lower():
            return normalize_text(v)
    return ""



def safe_goto(page, url: str):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
    except PlaywrightTimeoutError:
        print(f"Timeout khi mở URL: {url}")



def click_luoc_do_tab(page):
    selectors = [
        "text=Lược đồ",
        "a:has-text('Lược đồ')",
        "button:has-text('Lược đồ')",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.click(timeout=3000)
                page.wait_for_timeout(600)
                return
        except Exception:
            continue


def expand_luoc_do_sections(page):
    try:
        page.evaluate(
            """
            () => {
              const root = document.body;
              const toggles = Array.from(root.querySelectorAll('button, a, div[role="button"], .accordion-button, .collapse-title'));
              const isTarget = (el) => {
                const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                if (!txt) return false;
                return txt.includes('văn bản') || txt.includes('lược đồ') || txt.includes('luoc do') || /\\(\\d+\\)/.test(txt);
              };
              toggles.forEach((el) => {
                const expanded = (el.getAttribute('aria-expanded') || '').toLowerCase();
                if (expanded === 'false' && isTarget(el)) el.click();
              });
            }
            """
        )
        page.wait_for_timeout(500)
    except Exception:
        pass



def get_body_lines(page) -> list[str]:
    try:
        text = page.locator("body").inner_text(timeout=8000)
    except Exception:
        return []
    return [normalize_text(x) for x in text.splitlines() if normalize_text(x)]



def extract_current_document_info(lines: list[str]) -> dict:
    text = "\n".join(lines)

    so_hieu = ""
    m = SO_HIEU_PATTERN.search(text)
    if m:
        so_hieu = normalize_text(m.group(0))

    title = ""
    for ln in lines:
        if len(ln) < 20:
            continue
        if so_hieu and so_hieu in ln:
            title = ln
            break
        if any(ln.lower().startswith(x) for x in ["luật", "nghị định", "thông tư", "bộ luật"]):
            title = ln
            break
    if not title and lines:
        title = lines[0]

    loai = ""
    for t in ["Bộ luật", "Luật", "Nghị định", "Thông tư", "Nghị quyết", "Quyết định", "Chỉ thị", "Công văn"]:
        if title.lower().startswith(t.lower()):
            loai = t
            break

    def find_after(prefix: str) -> str:
        p = prefix.lower()
        for idx, ln in enumerate(lines):
            if p in ln.lower():
                parts = ln.split(":", 1)
                if len(parts) == 2:
                    return normalize_text(parts[1])
                # Hỗ trợ dạng:
                # Số hiệu:
                # 136/2026/NĐ-CP
                if idx + 1 < len(lines):
                    return normalize_text(lines[idx + 1])
        return ""

    ngay_ban_hanh = ""
    ngay_hieu_luc = ""
    for ln in lines:
        if "ban hành" in ln.lower() and not ngay_ban_hanh:
            m = DATE_PATTERN.search(ln)
            if m:
                ngay_ban_hanh = m.group(0)
        if ("hiệu lực" in ln.lower() or "áp dụng" in ln.lower()) and not ngay_hieu_luc:
            m = DATE_PATTERN.search(ln)
            if m:
                ngay_hieu_luc = m.group(0)

    return {
        "so_hieu": find_after("Số hiệu") or so_hieu,
        "ten_van_ban": title,
        "loai_van_ban": loai,
        "co_quan_ban_hanh": find_after("Cơ quan ban hành"),
        "ngay_ban_hanh": ngay_ban_hanh,
        "ngay_hieu_luc": ngay_hieu_luc,
        "linh_vuc": find_after("Lĩnh vực"),
        "tinh_trang_hieu_luc": find_after("Hiệu lực"),
    }



def extract_dom_positions(page) -> dict:
    return page.evaluate(
        """
        () => {
          const norm = (s) => (s || '').replace(/\u00a0/g, ' ').replace(/[ \t]+/g, ' ').trim();
          const texts = Array.from(document.querySelectorAll('a,div,span,li,h1,h2,h3,h4'));
          const items = [];
          for (const el of texts) {
            const t = norm(el.innerText || el.textContent || '');
            if (!t || t.length < 2) continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            items.push({
              text: t,
              top: r.top + window.scrollY,
              left: r.left + window.scrollX,
              tag: (el.tagName || '').toLowerCase(),
            });
          }
          return {items};
        }
        """
    )


def extract_luoc_do_relationships_from_dom_blocks(page) -> list[dict]:
    rows = page.evaluate(
        """
        () => {
          const norm = (s) => (s || '').replace(/\\u00a0/g, ' ').replace(/[ \\t]+/g, ' ').trim();
          const blocks = Array.from(document.querySelectorAll('.block-list.list-luocdo'));
          const out = [];
          for (const block of blocks) {
            const titleEl = block.querySelector('.block-list-title');
            let heading = norm(titleEl ? (titleEl.innerText || titleEl.textContent || '') : '');
            if (!heading) continue;
            heading = heading.replace(/\\(\\d+\\)/g, '').trim();
            if (!heading.toLowerCase().startsWith('văn bản')) continue;
            const links = Array.from(block.querySelectorAll('.block-list-content a.doc-properties, .luocdo-item a.doc-properties'));
            for (const a of links) {
              const text = norm(a.innerText || a.textContent || '');
              if (!text) continue;
              out.push({ heading, item: text });
            }
          }
          return out;
        }
        """
    )
    cleaned, seen = [], set()
    for row in rows or []:
        heading = normalize_text(row.get("heading", ""))
        item = normalize_text(row.get("item", ""))
        if not heading or not item:
            continue
        key = (heading, item)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"heading": heading, "item": item})
    return cleaned



def deduplicate_headings(dom_data: dict) -> list[dict]:
    result, seen = [], set()
    for it in dom_data.get("items", []):
        txt = normalize_text(it.get("text", ""))
        if txt in LUOC_DO_HEADINGS and txt not in seen:
            seen.add(txt)
            result.append(it)
    result.sort(key=lambda x: (x.get("top", 0), x.get("left", 0)))
    return result



def deduplicate_items(dom_data: dict) -> list[dict]:
    out, seen = [], set()
    for it in dom_data.get("items", []):
        txt = normalize_text(it.get("text", ""))
        if not txt or txt in LUOC_DO_HEADINGS:
            continue
        if len(txt) < 8 or not SO_HIEU_PATTERN.search(txt):
            continue
        if any(p in txt.lower() for p in SKIP_RELATION_PHRASES):
            continue
        key = (txt, int(float(it.get("top", 0) or 0)))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    out.sort(key=lambda x: (x.get("top", 0), x.get("left", 0)))
    return out



def assign_items_to_headings(headings: list[dict], items: list[dict]) -> list[dict]:
    if not headings:
        return []
    h_sorted = sorted(headings, key=lambda x: x.get("top", 0))
    rel = []
    for item in items:
        top = float(item.get("top", 0) or 0)
        current = None
        left = float(item.get("left", 0) or 0)
        for h in h_sorted:
            h_left = float(h.get("left", 0) or 0)
            if abs(h_left - left) > 240:
                continue
            if float(h.get("top", 0) or 0) <= top:
                current = h
            else:
                break
        if current:
            rel.append({
                "heading": normalize_text(current.get("text", "")),
                "item": normalize_text(item.get("text", "")),
                "item_top": top,
                "item_left": left,
            })
    return rel


def extract_primary_so_hieu_from_relationship_item(text: str) -> str:
    txt = normalize_text(text)
    if not txt:
        return ""
    marker_match = re.search(r"\bsố\s+(" + SO_HIEU_PATTERN.pattern[2:-2] + r")\b", txt, flags=re.IGNORECASE)
    if marker_match:
        return normalize_so_hieu(marker_match.group(1))
    all_matches = SO_HIEU_PATTERN.findall(txt)
    return normalize_so_hieu(all_matches[0]) if all_matches else ""


def build_relationship_outputs(relationships: list[dict]) -> dict:
    grouped: dict[str, list[tuple[str, str]]] = {}
    for row in relationships or []:
        heading = normalize_text(row.get("heading", ""))
        item = normalize_text(row.get("item", ""))
        if heading and item and not any(p in item.lower() for p in SKIP_RELATION_PHRASES):
            grouped.setdefault(heading, []).append((extract_primary_so_hieu_from_relationship_item(item), item))

    official_map = {c: "" for c in OFFICIAL_RELATIONSHIP_COLUMNS}
    can_cu_so_hieu: list[str] = []
    note_sections: list[str] = []
    for heading, entries in grouped.items():
        mapped_col = HEADING_TO_COLUMN.get(heading, "")
        # Cột quan hệ chính thức dùng dropdown theo "Số hiệu", không dùng full title.
        values = [so for so, _ in entries if so]
        if mapped_col:
            official_map[mapped_col] = "\n".join(values)
        if heading == "Văn bản căn cứ":
            can_cu_so_hieu = [so for so, _ in entries if so]

        section = [
            f"[{heading}]",
            "Trạng thái đối chiếu: Chưa đối chiếu ID nội bộ (chỉ gợi ý theo số hiệu/nội dung).",
            f"Số lượng theo LuatVietnam: {len(entries)}",
        ]
        for so, title in entries:
            section.append(f"- {so}: {title}" if so else f"- {title}")
        note_sections.append("\n".join(section))

    return {
        "official_map": official_map,
        "noi_dung_can_cu": "\n".join([title for _, title in grouped.get("Văn bản căn cứ", [])]),
        "goi_y_can_cu_phap_ly": "\n".join(can_cu_so_hieu),
        "ghi_chu_quan_he_phap_ly": "\n\n".join(note_sections),
        "has_relationship_data": bool(grouped),
    }


def build_luoc_do_payload_for_apps_script(relationships: list[dict]) -> dict:
    official_headings = {
        "Văn bản căn cứ",
        "Văn bản hướng dẫn",
        "Văn bản sửa đổi, bổ sung",
        "Văn bản bị sửa đổi, bổ sung",
    }

    canonical_heading_aliases = {
        "Văn bản căn cứ": [
            "văn bản căn cứ",
            "van ban can cu",
        ],
        "Văn bản hướng dẫn": [
            "văn bản hướng dẫn",
            "văn bản được hướng dẫn",
            "văn bản dẫn chiếu",
            "van ban huong dan",
            "van ban duoc huong dan",
            "van ban dan chieu",
        ],
        "Văn bản sửa đổi, bổ sung": [
            "văn bản sửa đổi, bổ sung",
            "văn bản sửa đổi bổ sung",
            "van ban sua doi bo sung",
        ],
        "Văn bản bị sửa đổi, bổ sung": [
            "văn bản bị sửa đổi, bổ sung",
            "văn bản bị sửa đổi bổ sung",
            "van ban bi sua doi bo sung",
        ],
    }

    def canonicalize_heading(raw: str) -> str:
        text = normalize_text(raw)
        text = re.sub(r"\(\d+\)", "", text).strip()
        text = re.sub(r"\s+", " ", text)
        text_lower = text.lower()
        for canon, aliases in canonical_heading_aliases.items():
            for alias in aliases:
                if text_lower == alias or text_lower.startswith(alias):
                    return canon
            if text_lower == canon.lower() or text_lower.startswith(canon.lower()):
                return canon
        return text

    grouped: dict[str, list[dict]] = {}
    for row in relationships or []:
        heading = canonicalize_heading(row.get("heading", ""))
        item_text = normalize_text(row.get("item", ""))
        if not heading or not item_text or heading not in official_headings:
            continue
        so_hieu_chinh = extract_primary_so_hieu_from_relationship_item(item_text)
        grouped.setdefault(heading, []).append(
            {
                "so_hieu_chinh": so_hieu_chinh,
                "so_hieu_tim_duoc": [so_hieu_chinh] if so_hieu_chinh else [],
                "noi_dung": item_text,
            }
        )
    return {"quan_he_phap_ly_theo_luoc_do": {k: {"items": v} for k, v in grouped.items()}}


def infer_relationship_status(relation_data: dict) -> str:
    # Chuẩn hoá đơn giản để luôn hợp lệ với dropdown và không tạo trạng thái gây hiểu nhầm.
    has_data = bool(relation_data.get("has_relationship_data", False))
    has_suggestions = bool(normalize_text(relation_data.get("goi_y_can_cu_phap_ly", "")))
    return "Đã gợi ý" if (has_data or has_suggestions) else "Chưa quét"


def normalize_relationship_status_dropdown(value: str) -> str:
    allowed = ["Chưa quét", "Đã gợi ý", "Cần kiểm tra thủ công", "Cần xác nhận", "Lỗi quét"]
    text = normalize_text(value)
    return text if text in allowed else "Chưa quét"



def build_payload(result: dict, config: dict, sheet_columns: list[str] | None = None, id_van_ban: str = "") -> dict:
    info = result.get("current_doc", {})
    source_doc_type = normalize_text(result.get("source_doc_type", ""))
    source_doc_number = normalize_text(result.get("source_doc_number", ""))
    source_title = normalize_text(result.get("source_title", ""))

    id_seed = source_doc_number or normalize_text(info.get("so_hieu", "")) or normalize_text(result.get("url", ""))
    stable_id = id_van_ban or (hashlib.md5(id_seed.encode("utf-8")).hexdigest()[:16] if id_seed else "")
    relation_data = build_relationship_outputs(result.get("luoc_do_data", []))
    relationship_status = normalize_relationship_status_dropdown(infer_relationship_status(relation_data))
    include_relationship_note = bool(config.get("include_relationship_note", False))
    payload = {
        "ID VĂN BẢN": stable_id,
        "Lĩnh vực": map_external_field_to_internal(
            normalize_text(info.get("linh_vuc", "")) or normalize_text(result.get("field_name", ""),
            ),
            config,
        ),
        "Chủ đề": "",
        "Mục": "",
        # Ưu tiên dữ liệu từ step 7 để đồng nhất với danh sách đầu vào đã được lọc.
        "Loại văn bản": source_doc_type or normalize_text(info.get("loai_van_ban", "")),
        "Tên văn bản": source_title or normalize_text(info.get("ten_van_ban", "")),
        "Số hiệu": normalize_so_hieu(source_doc_number or normalize_text(info.get("so_hieu", ""))),
        "Ngày hiệu lực": normalize_text(info.get("ngay_hieu_luc", "")),
        "Mức độ tác động": "",
        "Bộ phận chủ trì": "",
        "Link Văn bản": normalize_text(result.get("url", "")),
        "Căn cứ pháp lý": relation_data["official_map"].get("Căn cứ pháp lý", ""),
        "Hướng dẫn thực hiện": relation_data["official_map"].get("Hướng dẫn thực hiện", ""),
        "Sửa đổi, bổ sung cho": relation_data["official_map"].get("Sửa đổi, bổ sung cho", ""),
        "Sửa đổi, bổ sung bởi": relation_data["official_map"].get("Sửa đổi, bổ sung bởi", ""),
        "Trạng thái duyệt": "Chờ kiểm tra",
        "Trạng thái xử lý": "Chờ kiểm tra tự động",
        "Nội dung căn cứ": relation_data["noi_dung_can_cu"],
        "Gợi ý căn cứ pháp lý": relation_data["goi_y_can_cu_phap_ly"],
        "Văn bản chưa có trong danh mục": "",
        "Trạng thái quan hệ pháp lý": relationship_status,
        "Ghi chú quan hệ pháp lý": relation_data["ghi_chu_quan_he_phap_ly"] if include_relationship_note else "",
        "Nguồn dữ liệu": "LuatVietnam",
        "Ngày Python quét": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "Ghi chú Python": (
            "Dữ liệu được trích xuất tự động từ Lược đồ LuatVietnam trong chế độ batch. "
            f"Lĩnh vực nguồn LuatVietnam: {normalize_text(result.get('field_name', ''))}. "
            f"Mã lĩnh vực nguồn: {normalize_text(result.get('field_code', ''))}. "
            f"URL danh sách nguồn: {normalize_text(result.get('source_list_url', ''))}. "
            f"Số văn bản căn cứ gợi ý: {len([x for x in relation_data['goi_y_can_cu_phap_ly'].splitlines() if x.strip()])}."
        ),
    }

    # Bổ sung cột theo schema đích (có thể tuỳ biến theo Google Sheet thực tế).
    active_columns = sheet_columns or list(DEFAULT_SHEET_COLUMNS)
    for c in active_columns:
        payload.setdefault(c, "")
    return payload



def validate_payload(payload: dict) -> tuple[bool, str]:
    required = REQUIRED_COLUMNS
    for f in required:
        if not normalize_text(payload.get(f, "")):
            return False, f"Thiếu trường bắt buộc: {f}"
    return True, ""



def should_skip_payload(payload: dict, config: dict) -> tuple[bool, str]:
    filters = (config.get("filters", {}) or {})
    skip_doc_types = filters.get("skip_doc_types", []) or []
    accepted_doc_types = filters.get("accepted_doc_types", []) or ["Bộ luật", "Luật", "Nghị định", "Thông tư"]
    exclude_title_keywords = filters.get("exclude_title_keywords", []) or []
    exclude_url_keywords = filters.get("exclude_url_keywords", []) or []
    exclude_so_hieu_keywords = filters.get("exclude_so_hieu_keywords", []) or []

    loai = normalize_text(payload.get("Loại văn bản", ""))
    title = normalize_text(payload.get("Tên văn bản", "")).lower()
    url = normalize_text(payload.get("Link Văn bản", "")).lower()
    so_hieu = normalize_text(payload.get("Số hiệu", ""))

    if not loai:
        return True, "missing_doc_type"
    if accepted_doc_types and loai not in accepted_doc_types:
        return True, f"not_in_accepted_doc_types:{loai}"
    if loai in skip_doc_types:
        return True, f"skip_doc_types:{loai}"

    for kw in exclude_title_keywords:
        kw = normalize_text(kw).lower()
        if kw and kw in title:
            return True, f"exclude_title_keywords:{kw}"

    # Bảo hiểm cứng để không gửi các loại ngoài phạm vi dù parser nhận diện lệch.
    hard_block_url_keywords = ["chi-thi", "quyet-dinh", "van-ban-hop-nhat", "cong-van"]
    for kw in hard_block_url_keywords + [normalize_text(k).lower() for k in exclude_url_keywords]:
        if kw and kw in url:
            return True, f"exclude_url_keywords:{kw}"

    for kw in exclude_so_hieu_keywords:
        kw = normalize_text(kw)
        if kw and kw.lower() in so_hieu.lower():
            return True, f"exclude_so_hieu_keywords:{kw}"

    return False, ""



def get_positive_int(config: dict, key: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(config.get(key, default) or default)
    except Exception:
        value = default
    return max(minimum, value)


def get_positive_float(config: dict, key: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(config.get(key, default) or default)
    except Exception:
        value = default
    return max(minimum, value)


def is_retryable_apps_script_error(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in {408, 409, 425, 429, 500, 502, 503, 504}

    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", exc)
        return is_retryable_apps_script_error(reason) if isinstance(reason, Exception) else is_retryable_error_text(reason)

    if isinstance(exc, (TimeoutError, socket.timeout, ConnectionResetError, ConnectionAbortedError, BrokenPipeError, ssl.SSLError)):
        return True

    if isinstance(exc, OSError) and getattr(exc, "winerror", None) in {10053, 10054, 10060}:
        return True

    return is_retryable_error_text(exc)


def is_retryable_error_text(value) -> bool:
    text = str(value or "").lower()
    retryable_markers = [
        "timed out",
        "timeout",
        "connection reset",
        "connection aborted",
        "connection refused",
        "forcibly closed",
        "remote end closed",
        "temporarily unavailable",
        "too many requests",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
    ]
    return any(marker in text for marker in retryable_markers)


def sleep_before_apps_script_retry(attempt: int, base_delay_seconds: float, max_delay_seconds: float) -> None:
    delay = min(max_delay_seconds, base_delay_seconds * (2 ** max(0, attempt - 1)))
    if delay > 0:
        time.sleep(delay)


def send_to_apps_script(payload: dict, luoc_do_data: dict, config: dict, debug_save_request_body: bool = False) -> dict:
    url = normalize_text(config.get("APPS_SCRIPT_WEBAPP_URL", "") or os.getenv("APPS_SCRIPT_WEBAPP_URL", ""))
    token = resolve_apps_script_token(config)
    if not url:
        return {"ok": False, "error": "Thiếu APPS_SCRIPT_WEBAPP_URL"}
    if not token:
        return {"ok": False, "error": "Thiếu APPS_SCRIPT_TOKEN"}
    max_attempts = get_positive_int(config, "apps_script_send_max_attempts", 3, minimum=1)
    timeout_seconds = get_positive_int(config, "apps_script_timeout_seconds", 60, minimum=10)
    base_delay_seconds = get_positive_float(config, "apps_script_retry_base_delay_seconds", 2.0, minimum=0.0)
    max_delay_seconds = get_positive_float(config, "apps_script_retry_max_delay_seconds", 12.0, minimum=0.0)

    options = {
        # Cho phép người dùng vẫn sửa tay trên Google Sheet mà không bị ghi đè.
        "mode": config.get("apps_script_mode", "upsert_preserve_existing"),
        "match_keys": config.get("apps_script_match_keys", ["Số hiệu"]),
        "update_only_blank_fields": bool(config.get("update_only_blank_fields", True)),
        "preserve_manual_edits": bool(config.get("preserve_manual_edits", True)),
        "allow_manual_override": bool(config.get("allow_manual_override", True)),
        # Quy ước giá trị cho 4 cột quan hệ chính thức: so_hieu | id_van_ban
        "relationship_value_mode": (
            normalize_text(config.get("relationship_value_mode", "so_hieu")).lower()
            if normalize_text(config.get("relationship_value_mode", "so_hieu")).lower() in ["so_hieu", "id_van_ban"]
            else "so_hieu"
        ),
        # first_only: 1 giá trị; multi_line: nhiều dòng; multi_select: chuỗi phân tách bằng ", " cho ô dropdown nhiều lựa chọn.
        "relationship_cell_strategy": (
            normalize_text(config.get("relationship_cell_strategy", "multi_select")).lower()
            if normalize_text(config.get("relationship_cell_strategy", "multi_select")).lower() in ["first_only", "multi_line", "multi_select"]
            else "multi_select"
        ),
    }

    body = {
        "token": token,
        "action": "import_vbqppl_nhap",
        "payload": payload,
        "luoc_do_data": luoc_do_data,
        "options": options,
    }

    request_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    failed_attempts = []

    for attempt in range(1, max_attempts + 1):
        try:
            req = Request(
                url,
                data=request_bytes,
                headers={"Content-Type": "application/json", "Connection": "close"},
                method="POST",
            )
            with urlopen(req, timeout=timeout_seconds) as res:
                content = res.read().decode("utf-8", errors="replace")
            parsed = {}
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = {"raw": content}
            out = {"ok": True, "result": parsed, "attempt": attempt}
            if failed_attempts:
                out["retry_errors"] = failed_attempts
            if debug_save_request_body:
                out["request_body"] = body
            return out
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            detail = f"HTTPError {exc.code}: {exc.reason}. Body: {response_body[:500]}"
            retryable = is_retryable_apps_script_error(exc)
        except URLError as exc:
            detail = f"URLError: {exc.reason}"
            retryable = is_retryable_apps_script_error(exc)
        except Exception as exc:
            msg = str(exc) if str(exc) else repr(exc)
            detail = f"{exc.__class__.__name__}: {msg}"
            retryable = is_retryable_apps_script_error(exc)

        failed_attempts.append({"attempt": attempt, "error": detail, "retryable": retryable})
        if (not retryable) or attempt >= max_attempts:
            prefix = f"Apps Script send failed after {attempt}/{max_attempts} attempt(s)"
            out = {"ok": False, "error": f"{prefix}: {detail}", "attempt": attempt, "retry_errors": failed_attempts}
            if debug_save_request_body:
                out["request_body"] = body
            return out

        sleep_before_apps_script_retry(attempt, base_delay_seconds, max_delay_seconds)

    out = {"ok": False, "error": "Apps Script send failed without a captured exception", "retry_errors": failed_attempts}
    if debug_save_request_body:
        out["request_body"] = body
    return out



def process_document(page, doc: dict, config: dict) -> dict:
    url = normalize_text(doc.get("url", ""))
    safe_goto(page, url)
    click_luoc_do_tab(page)
    expand_luoc_do_sections(page)

    lines = get_body_lines(page)
    current_doc = extract_current_document_info(lines)

    # Ưu tiên parser theo block DOM của tab "Lược đồ" để bám sát cấu trúc HTML thật.
    relationships_from_blocks = extract_luoc_do_relationships_from_dom_blocks(page)

    # Fallback bằng heuristic vị trí nếu parser theo block không lấy được dữ liệu.
    dom_data = extract_dom_positions(page)
    headings = deduplicate_headings(dom_data)
    items = deduplicate_items(dom_data)
    relationships_from_positions = assign_items_to_headings(headings, items)

    # Gộp 2 nguồn để hạn chế mất dữ liệu khi mỗi nguồn bắt được một phần khác nhau.
    merged_relationships: list[dict] = []
    seen_keys = set()
    for row in (relationships_from_blocks or []) + (relationships_from_positions or []):
        heading = normalize_text(row.get("heading", ""))
        item = normalize_text(row.get("item", ""))
        if not heading or not item:
            continue
        key = (heading, item)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        merged_relationships.append({"heading": heading, "item": item})
    relationships = merged_relationships

    extraction_meta = {
        "from_blocks_count": len(relationships_from_blocks or []),
        "from_positions_count": len(relationships_from_positions or []),
        "merged_count": len(relationships),
        "used_fallback_only": bool((not relationships_from_blocks) and relationships_from_positions),
    }

    luoc_do_payload = build_luoc_do_payload_for_apps_script(relationships)

    return {
        "url": url,
        "field_name": doc.get("ten_linh_vuc_luatvietnam", ""),
        "source_doc_type": doc.get("doc_type_from_list", ""),
        "source_doc_number": doc.get("doc_number_from_list", ""),
        "source_title": doc.get("title_from_list", ""),
        "field_code": doc.get("ma_linh_vuc", ""),
        "source_list_url": doc.get("source_list_url", ""),
        "current_doc": current_doc,
        "luoc_do_data": relationships,
        "luoc_do_payload": luoc_do_payload,
        "luoc_do_extraction_meta": extraction_meta,
    }



def main():
    setup_utf8_stdio()
    load_env_file()
    config = load_json(CONFIG_FILE)
    batch_input = load_json(INPUT_FILE)
    sheet_columns = load_sheet_schema()

    dry_run = bool(config.get("dry_run", False))
    apps_script_enabled = bool(config.get("apps_script_enabled", True))
    webapp_url = normalize_text(config.get("APPS_SCRIPT_WEBAPP_URL", "") or os.getenv("APPS_SCRIPT_WEBAPP_URL", ""))
    webapp_token = resolve_apps_script_token(config)
    print(f"Apps Script enabled: {apps_script_enabled} | dry_run: {dry_run}")
    print(f"APPS_SCRIPT_WEBAPP_URL: {'OK' if webapp_url else 'MISSING'}")
    print(f"APPS_SCRIPT_TOKEN: {'OK' if webapp_token else 'MISSING'}")

    docs = batch_input.get("documents", []) or []
    debug_save_request_body = bool(config.get("debug_save_request_body", False))
    id_start_from = int(config.get("id_van_ban_start_from", 174) or 174)
    next_vb_number = id_start_from

    results = []
    payloads = []
    request_debug_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=30)
        context = browser.new_context(storage_state=str(AUTH_FILE) if AUTH_FILE.exists() else None)
        page = context.new_page()

        for idx, doc in enumerate(docs, start=1):
            url = normalize_text(doc.get("url", ""))
            if not url:
                continue

            print(f"[{idx}/{len(docs)}] Xử lý: {url}")
            processed = process_document(page, doc, config)
            payload = build_payload(
                processed,
                config=config,
                sheet_columns=sheet_columns,
                id_van_ban=format_vb_id(next_vb_number),
            )

            valid, message = validate_payload(payload)
            if not valid:
                results.append({"url": url, "status": "invalid", "message": message})
                continue

            skip, skip_reason = should_skip_payload(payload, config)
            if skip:
                results.append({"url": url, "status": "skipped", "message": skip_reason})
                continue

            payloads.append(payload)
            next_vb_number += 1

            if dry_run or not apps_script_enabled:
                results.append({"url": url, "status": "dry_run", "message": "Không gửi Apps Script"})
                continue

            luoc_do_payload = processed.get("luoc_do_payload", {"quan_he_phap_ly_theo_luoc_do": {}})
            sent = send_to_apps_script(payload, luoc_do_payload, config, debug_save_request_body=debug_save_request_body)
            if debug_save_request_body:
                debug_row = {
                    "url": url,
                    "request_body": sent.get("request_body", {}),
                    "attempt": sent.get("attempt", 1),
                    "response": sent.get("result", {}) if sent.get("ok") else {"ok": False, "error": sent.get("error", "")},
                }
                if sent.get("retry_errors"):
                    debug_row["retry_errors"] = sent.get("retry_errors")
                request_debug_rows.append(debug_row)
            if sent.get("ok"):
                result_row = {"url": url, "status": "sent", "result": sent.get("result", {})}
                if sent.get("attempt", 1) > 1:
                    result_row["send_attempt"] = sent.get("attempt", 1)
                    result_row["send_retry_errors"] = sent.get("retry_errors", [])
                    print(f"Gửi Apps Script thành công sau {sent.get('attempt', 1)} lần thử.")
                results.append(result_row)
            else:
                results.append(
                    {
                        "url": url,
                        "status": "error",
                        "message": sent.get("error", ""),
                        "send_attempt": sent.get("attempt", 1),
                        "send_retry_errors": sent.get("retry_errors", []),
                    }
                )
                print(f"Lỗi gửi Apps Script: {sent.get('error', '')}")

        browser.close()

    output = {
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "run_mode": config.get("run_mode", ""),
        "dry_run": dry_run,
        "apps_script_enabled": apps_script_enabled,
        "sheet_columns": sheet_columns,
        "id_van_ban_start_from": id_start_from,
        "total_input": len(docs),
        "total_payloads": len(payloads),
        "payloads": payloads,
        "results": results,
    }

    save_json(OUTPUT_FILE, output)
    if debug_save_request_body:
        save_json(
            OUTPUT_REQUEST_DEBUG_FILE,
            {
                "created_at": output["created_at"],
                "run_mode": config.get("run_mode", ""),
                "rows": request_debug_rows,
            },
        )
        print(f"Đã lưu request debug: {OUTPUT_REQUEST_DEBUG_FILE}")
    print(f"Đã lưu batch payload: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

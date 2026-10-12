# GD2 - Cong cu phat hien va de xuat ra soat hieu luc (ban dau)

Trang thai: **Da co code va test; chua kiem thu website that / chua deploy pipeline theo lich / khong ghi production**.

## File

- `legal_effect_analysis.py`: bo phan tich theo ngu canh van ban moi, doc dieu khoan va Luoc do do Step08 thu thap. Luon tra `CHUA_XAC_MINH` va `CHO_XAC_MINH`; KHONG tu ket luan da het hieu luc.
- `08_process_field_documents_batch.py`: giu nguyen API import; them `legal_effect_candidates` vao file JSON dau ra Step08. Khong truyen candidate vao Apps Script.
- `15_check_legal_effect.py`: doc workbook offline gom 2 sheet `VBQPPL` / `VBQPPL_Nhap`, doi chieu so hieu chuan hoa, tao report CSV/JSON phu hop 28 cot staging GD1. Ho tro `baseline` va `events`.
- `tests/test_legal_effect_analysis.py`: unit test; chay qua GitHub Actions.
- `requirements-legal-effect.txt`: openpyxl cho cong doan doc snapshot.

## Lenh chay tren may Windows

Dau vao la mot **ban sao .xlsx** cua Google Sheets, KHONG chinh sua file nguon.

```powershell
python -m pip install -r requirements-legal-effect.txt
python -m unittest discover -s tests -p "test_legal_effect_analysis.py" -v

# Khoi tao danh sach ra soat tat ca so hieu (khong tu ket luan)
python 15_check_legal_effect.py --mode baseline --workbook "backup.xlsx" --output-dir "output/gd2-baseline"

# Khi Step08 da chay phien ban moi va xuat legal_effect_candidates
python 15_check_legal_effect.py --mode events --workbook "backup.xlsx" --step08-json "output/vbqppl_nhap_batch_payload.json" --output-dir "output/gd2-events"
```

Dau ra: `legal_effect_review.csv`, `legal_effect_review.json` co cot theo dac ta GD1. Du lieu theo nguon tu dong la **ung vien can xac minh**, khong phai ho so duoc xac nhan het hieu luc.

## Gioi han an toan

- Chi doc file local va tao report local, khong su dung token, khong goi API ghi Sheets, khong goi Planner.
- Luoc do cho biet quan he goi y; can kiem tra chieu quan he, pham vi bi tac dong va quy dinh chuyen tiep. Tu khoa khong du ket luan het hieu luc.
- Nhan dien `event_key` co tinh lap lai; so hieu co the trung/khac nguon, can review va xac minh dinh danh khi migration.
- Trang thai `SAP_HET_HIEU_LUC` chua duoc ket luan tu dong vi thieu ngay ket thuc duoc chung minh.
- Ma so va ngay theo nguon co the sai; khoi tao baseline khong dong nghia rang van ban da duoc xac minh phap ly.
- Chua co bo doi chieu trang thai voi CSDL VBPL chinh thuc, OCR/PDF, trinh duyet tren may Windows, hay test E2E cua crawl 07->08->09. Can thuc hien tiep va danh gia do phu truoc khi tu dong chay theo lich.
- Chua co action service tiep nhan ket qua vao `VBQPPL_RaSoatHieuLuc`; phan nay thuoc GD3. Khong su dung public token de ghi.
- Hoan toan khong dong cham toi Google Sheets production, WebApp, Dashboard, MS Planner hoac Task Scheduler.

## Nghiem thu GD2 - hạng muc

1. Parser xu ly duoc luoc do thay the / het hieu luc / sua doi, dieu khoan va ngay du kien, khong auto-classify.
2. Baseline 531 ban ghi, 339 so hieu (tai snapshot 12/10/2026) -> 339 phieu cho ra soat, khong nhan doi.
3. Unit tests va CI qua; thu nghem E2E tren 30 van ban da duoc nguoi duyet danh gia, xac dinh precision/recall va cot loi.
4. Thong nhat nguon chinh thuc va phuong an quet dinh ky an toan.
5. Chi sau khi GD2 duoc nghiem thu moi chuyen GD3 (Apps Script service API + Dashboard admin).

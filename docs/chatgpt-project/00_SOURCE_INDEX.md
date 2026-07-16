# ChatGPT Project Source Index

## 1. Mục đích

Thư mục này chứa bộ tài liệu nguồn tối thiểu để nghiên cứu, phát triển và vận hành repository `chatgptsdhas/luatvietnam_vbqppl_web` trong một ChatGPT Project.

Các file này cung cấp bối cảnh ổn định mà mã nguồn không thể hiện đầy đủ. Chúng không thay thế GitHub. Khi câu hỏi liên quan đến code, commit, branch, pull request hoặc hành vi kỹ thuật hiện tại, phải đọc trực tiếp repository qua GitHub.

## 2. Các file nên đưa vào mục Nguồn của ChatGPT Project

1. `01_PROJECT_CONTEXT.md` — mục tiêu, người dùng, phạm vi và nguyên tắc nghiệp vụ.
2. `02_ARCHITECTURE_AND_BOUNDARIES.md` — kiến trúc, luồng dữ liệu và ranh giới không được phá vỡ.
3. `03_BUSINESS_RULES_AND_DATA_CONTRACT.md` — sheet, trường dữ liệu, trạng thái và quy tắc đồng bộ.
4. `04_REPO_MAP_AND_CHANGE_GUIDE.md` — bản đồ repository và cách xác định phạm vi ảnh hưởng.
5. `05_OPERATIONS_AND_PRODUCTION_STATE.md` — runbook vận hành và mẫu ghi nhận trạng thái production.
6. `06_DECISIONS_AND_OPEN_ISSUES.md` — quyết định kiến trúc, vấn đề mở và mẫu ADR.

## 3. File dùng cho Project instructions

`PROJECT_INSTRUCTIONS.md` được thiết kế để sao chép vào **Project settings → Project instructions**. Không bắt buộc tải file này vào mục Nguồn nếu nội dung đã được dán vào phần hướng dẫn của Project.

## 4. Nguồn sự thật

| Loại thông tin | Nguồn ưu tiên |
|---|---|
| Code, file, hàm, branch, commit, PR | GitHub repository tại ref đang được yêu cầu |
| Kiến trúc và ranh giới bảo mật hiện hành | Code + `SECURITY.md` + tài liệu trong thư mục này |
| Trạng thái production | `05_OPERATIONS_AND_PRODUCTION_STATE.md` sau khi người quản trị cập nhật |
| Quy tắc nghiệp vụ và dữ liệu | `03_BUSINESS_RULES_AND_DATA_CONTRACT.md` + code hiện hành |
| Quyết định đã thống nhất | `06_DECISIONS_AND_OPEN_ISSUES.md` |
| Lịch sử trao đổi | Các chat trong cùng ChatGPT Project |

Khi các nguồn mâu thuẫn, không tự suy đoán. Phải nêu rõ mâu thuẫn và xác định nguồn cần được cập nhật.

## 5. Cách sử dụng

- Tải 6 file nguồn vào ChatGPT Project.
- Dán nội dung `PROJECT_INSTRUCTIONS.md` vào Project instructions.
- Kết nối và dùng `@GitHub` khi nghiên cứu code.
- Không tải bản sao các file `.py`, `.js`, `.html`, workflow, log hoặc toàn bộ ZIP repo vào Project.
- Cập nhật các file này trong cùng pull request khi thay đổi kiến trúc, data contract hoặc quy trình vận hành.

## 6. Metadata

- Repository: `chatgptsdhas/luatvietnam_vbqppl_web`
- Nhánh chuẩn: `main`
- Ngày tạo bộ nguồn: `2026-07-16`
- Trạng thái: tài liệu nền; production state cần người quản trị xác nhận trước khi sử dụng làm sự thật vận hành.
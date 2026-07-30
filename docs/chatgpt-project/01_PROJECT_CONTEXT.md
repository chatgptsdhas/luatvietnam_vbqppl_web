# Project Context — Legal AI Operating System / VBQPPL H.A.S

## 1. Mục tiêu

Hệ thống hỗ trợ H.A.S thu thập, chuẩn hóa, kiểm tra, phê duyệt và theo dõi việc triển khai văn bản quy phạm pháp luật có ảnh hưởng đến tổ chức.

Hệ thống không tự đưa ra kết luận pháp lý cuối cùng. Dữ liệu do crawler hoặc pipeline thu thập là đầu vào để người phụ trách pháp chế kiểm tra và quyết định.

## 2. Người sử dụng

- Người phụ trách pháp chế và quản trị nội bộ.
- Người quản trị kỹ thuật.
- Ban Điều hành và quản lý được phân quyền.
- Bộ phận được giao chủ trì hoặc phối hợp triển khai nghĩa vụ pháp lý.
- Người theo dõi nhiệm vụ qua Microsoft Planner.

## 3. Phạm vi chức năng

- Thu thập dữ liệu văn bản từ LuatVietnam và nguồn được cấu hình.
- Chuẩn hóa thông tin và quan hệ hiệu lực.
- Ghi dữ liệu chờ kiểm tra vào `VBQPPL_Nhap`.
- Cho phép người có quyền đọc, sửa, bỏ qua hoặc chuyển văn bản.
- Chuyển dữ liệu đã kiểm tra sang `VBQPPL`.
- Tạo và đồng bộ nhiệm vụ Microsoft Planner.
- Ghi log, báo cáo và cảnh báo phục vụ truy vết.

## 4. Nguồn sự thật nghiệp vụ

- `VBQPPL_Nhap`: vùng dữ liệu trung gian/chờ kiểm tra; không mặc nhiên là kết luận đã được xác nhận.
- `VBQPPL`: danh mục văn bản đã được chuyển sang quản lý chính thức trong hệ thống.
- Microsoft Planner: công cụ theo dõi nhiệm vụ; không thay thế dữ liệu pháp lý trong Google Sheets.
- Văn bản gốc từ nguồn chính thức: căn cứ cuối cùng khi xác định nội dung và hiệu lực pháp luật.

## 5. Nguyên tắc nghiệp vụ

1. Không coi kết quả quét tự động là kết luận pháp lý cuối cùng.
2. Không chuyển văn bản khi thiếu trường bắt buộc.
3. Không tạo trùng Planner Task cho cùng bản ghi.
4. Mọi thay đổi dữ liệu phải có khả năng truy vết.
5. Không dùng trạng thái giao diện để chứng minh quyền thực hiện thao tác.
6. Không tự thay đổi tên sheet, tên cột hoặc trạng thái khi chưa đánh giá migration.
7. Việc xóa hoặc cập nhật Planner Task phải được kiểm soát quyền và đồng bộ ngược.
8. Khi dữ liệu giữa Sheet và Planner mâu thuẫn, phải xác định rõ nguồn được ưu tiên theo từng trường dữ liệu.

## 6. Ngoài phạm vi

- Thay thế người phụ trách pháp chế trong việc kết luận hiệu lực hoặc nghĩa vụ pháp lý.
- Lưu secret, token, password hoặc session trong GitHub/ChatGPT Project.
- Coi branch `main` là trạng thái production nếu chưa xác nhận deployment.
- Tự động thay đổi cấu trúc dữ liệu production mà không có kế hoạch migration và rollback.

## 7. Thuật ngữ chính

- **Văn bản chờ kiểm tra**: bản ghi tại `VBQPPL_Nhap` chưa hoàn tất phê duyệt/chuyển giao.
- **Văn bản đã chuyển**: bản ghi đã được đưa sang `VBQPPL` theo luồng nghiệp vụ.
- **Service action**: API máy–máy do pipeline Python gọi.
- **Admin/write action**: thao tác làm thay đổi dữ liệu từ Dashboard, cần admin session hợp lệ.
- **Signed envelope**: payload được Apps Script lọc và ký HMAC để Planner Sync Server xác minh.
- **Production state**: commit, deployment, Script Properties và tiến trình thực tế đang phục vụ người dùng.
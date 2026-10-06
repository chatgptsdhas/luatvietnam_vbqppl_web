# Backend Vercel cho luồng chuyển văn bản và Planner

Từ phiên bản này, Dashboard gọi API cùng origin thay vì gọi trực tiếp Google Apps Script hoặc `127.0.0.1:8765`.

```text
Browser -> /api/transfer-and-create-planner -> Apps Script -> Google Sheet
                                            -> Microsoft Graph -> Planner
```

`api/webapp` cũng là proxy cùng origin cho các request Dashboard thông thường. Điều này loại bỏ lỗi CORS do Apps Script redirect sang `script.googleusercontent.com`.

## 1. Chuẩn bị Microsoft Entra ID

Tạo (hoặc dùng) một App Registration dành riêng cho backend. Tạo một client secret và cấp **Application permission** `Tasks.ReadWrite.All` của Microsoft Graph, sau đó thực hiện **Grant admin consent**. API tạo Planner task hiện hỗ trợ application permission này theo [tài liệu Microsoft Graph](https://learn.microsoft.com/en-us/graph/api/planner-post-tasks).

Không dùng session Graph Explorer, `browser_session.json`, hay access token hết hạn cho Vercel.

## 2. Cấu hình Vercel

Vercel Project phải dùng **Root Directory là thư mục gốc repository**, không phải riêng `Dashboard/`, để Vercel nhận thư mục `api/`.

Khai báo các Environment Variables cho cả Production và Preview (giá trị thật không commit vào Git):

```text
APPS_SCRIPT_WEBAPP_URL
APPS_SCRIPT_TOKEN
APPS_SCRIPT_SERVICE_TOKEN

MS_GRAPH_TENANT_ID
MS_GRAPH_CLIENT_ID
MS_GRAPH_CLIENT_SECRET

PLANNER_PLAN_ID
PLANNER_BUCKET_ID_PHAP_CHE
PLANNER_INITIAL_ASSIGNEE_USER_IDS
PLANNER_INITIAL_ASSIGNEE_EMAILS
PLANNER_INITIAL_ASSIGNEE_DEPARTMENTS
LEGAL_PIC_USER_ID
LEGAL_DEFAULT_DUE_DAYS
TENANT_ID
PLANNER_TASK_URL_TEMPLATE
BACKEND_ALLOWED_ORIGINS
```

`vercel.json` phục vụ giao diện từ `Dashboard/` và deploy các Python Functions trong `api/`.

## 3. Deploy Apps Script một lần

Đẩy/deploy mã `apps_script/` cùng phiên bản này. Thay đổi chỉ gồm:

- `transfer_record` trả thêm `vbqppl_row_number`, để backend xác định chính xác dòng vừa chuyển;
- action `validate_admin_session`, dùng để kiểm tra session khi thực hiện thao tác Planner nhạy cảm như xóa task.

Các Sheet, action cũ và Script Properties hiện có không cần đổi. `PLANNER_SYNC_SHARED_SECRET` chỉ còn cần thiết nếu vẫn vận hành Planner Sync Server cục bộ cũ; Dashboard mới không dùng nó.

## 4. Xác nhận sau deploy

1. Mở Dashboard, đăng nhập quản trị viên, rồi chuyển một văn bản thử.
2. Nhận lần lượt thông báo chuyển thành công và tạo task Planner.
3. Mở `VBQPPL`: dòng mới phải có `Planner Task ID`, `Planner Task URL` và `Planner Sync Status = Đã tạo task Planner`.
4. Trình duyệt không còn request đến `script.google.com`, `script.googleusercontent.com`, hay `127.0.0.1:8765`; các request Dashboard đi tới `/api/webapp` và `/api/transfer-and-create-planner`.

Nếu Microsoft Graph trả lỗi, văn bản vẫn được chuyển và API trả `planner_ok: false` thay vì báo chuyển thất bại. Lần retry không tạo trùng: backend tìm task cùng tiêu đề trong Plan trước khi tạo task mới.

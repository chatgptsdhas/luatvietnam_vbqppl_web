# Vercel backend: Dashboard proxy cho Apps Script

Vercel chỉ phục vụ Dashboard và `/api/webapp`, một proxy cùng origin đến Google
Apps Script. Vercel không gọi Microsoft Graph, không cần App Registration, client
secret hoặc application permission.

```text
Browser -> /api/webapp -> Apps Script -> Google Sheet

Browser -> /api/webapp (request_planner_sync_envelope) -> Apps Script
        -> signed HMAC envelope -> 127.0.0.1:8765 -> delegated Graph session -> Planner
```

Dashboard không gọi trực tiếp `script.google.com` cho các request thường. Riêng
request Planner tới `127.0.0.1:8765` là chuyển tiếp envelope ngắn hạn đã được
Apps Script ký; frontend không biết shared secret và không tự ký request.

## Cấu hình Vercel

Vercel Project phải đặt Root Directory là thư mục gốc repository để nhận `api/`
và `Dashboard/`. Khai báo các Environment Variables cho Production và Preview:

```text
APPS_SCRIPT_WEBAPP_URL
APPS_SCRIPT_TOKEN
BACKEND_ALLOWED_ORIGINS
```

`APPS_SCRIPT_SERVICE_TOKEN`, `PLANNER_SYNC_SHARED_SECRET`, Microsoft session và
mọi Microsoft credential không được cấu hình trên Vercel. Service token chỉ ở máy
chạy Python/Planner Sync Server; shared secret có cả trong Script Properties của
Apps Script và `.env` cục bộ.

## Cấu hình Apps Script và máy Windows

Deploy Apps Script có `request_planner_sync_envelope` (nhóm admin/write), schema
whitelist cho `/sync-webapp-to-planner` và `/delete-planner-task`, và đảm bảo
`transfer_record` trả `vbqppl_row_number`.

Trên máy Windows, cấu hình `.env` cục bộ theo `.env.example`, giữ Graph Explorer
delegated session ở `BROWSER_SESSION_PATH`, rồi cài task bằng
`./install_planner_sync_task.ps1`. Server chỉ bind `127.0.0.1:8765`; kiểm tra:

```powershell
./check_planner_sync_health.ps1
```

## Kiểm tra sau deploy

1. Đăng nhập Dashboard và chuyển một văn bản.
2. Xác nhận `transfer_record` tạo đúng dòng VBQPPL và trả `vbqppl_row_number`.
3. Dashboard xin envelope qua `/api/webapp`, sau đó gọi localhost với ba header
   `X-P0-*` từ envelope.
4. Xác nhận dòng VBQPPL được ghi `Planner Task ID`, URL và trạng thái đồng bộ.
5. Gọi lại cùng record: không được tạo task Planner thứ hai.

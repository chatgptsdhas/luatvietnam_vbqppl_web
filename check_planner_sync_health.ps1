# ============================================================
# KIEM TRA HEALTH: Planner Sync Server (127.0.0.1:8765)
# ============================================================

$ErrorActionPreference = "Stop"
$HealthUrl = "http://127.0.0.1:8765/health"

try {
    $result = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 5
    if ($result.ok) {
        Write-Host "OK - Planner Sync Server dang chay." -ForegroundColor Green
        Write-Host ("  service: {0}" -f $result.service)
        Write-Host ("  sync_endpoint: {0}" -f $result.sync_endpoint)
        Write-Host ("  delete_endpoint: {0}" -f $result.delete_endpoint)
        exit 0
    } else {
        Write-Host "CANH BAO - Server phan hoi nhung ok=false." -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host "LOI - Khong ket noi duoc Planner Sync Server tai $HealthUrl" -ForegroundColor Red
    Write-Host ("  Chi tiet: {0}" -f $_.Exception.Message)
    Write-Host ""
    Write-Host "Goi y khac phuc:"
    Write-Host "  1. Kiem tra Scheduled Task 'HAS_Planner_Sync_Server' co dang chay khong:"
    Write-Host "     Get-ScheduledTask -TaskName HAS_Planner_Sync_Server | Get-ScheduledTaskInfo"
    Write-Host "  2. Neu chua cai, chay: .\install_planner_sync_task.ps1"
    Write-Host "  3. Hoac chay thu cong: .\run_planner_sync_server.ps1"
    exit 1
}

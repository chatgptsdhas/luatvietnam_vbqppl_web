# ============================================================
# CAI DAT SCHEDULED TASK: HAS_Planner_Sync_Server
# Tu dong chay Planner Sync Server (127.0.0.1:8765) khi dang nhap
# Windows, tu khoi dong lai khi loi, khong tu dung sau vai gio,
# va KHONG HIEN bat ky cua so PowerShell/console nao tren desktop.
#
# Co che an cua so:
#   Scheduled Task -> wscript.exe //B run_planner_sync_server_hidden.vbs
#                  -> (shell.Run windowStyle=0, wait=True)
#                  -> run_planner_sync_server_hidden.bat (cd + set env + redirect log)
#                  -> pythonw.exe planner_sync_server.py (khong co console)
#
# Chay 1 lan de cai dat (khong can quyen Admin — server chi bind
# localhost va chay duoi quyen user hien tai).
# ============================================================

$ErrorActionPreference = "Stop"

$TaskName   = "HAS_Planner_Sync_Server"
$ProjectDir = $PSScriptRoot
$VbsPath    = Join-Path $ProjectDir "run_planner_sync_server_hidden.vbs"
$BatPath    = Join-Path $ProjectDir "run_planner_sync_server_hidden.bat"
$LogPath    = Join-Path $ProjectDir "logs\planner_sync_server.log"
$HealthUrl  = "http://127.0.0.1:8765/health"

if (-not (Test-Path -LiteralPath $VbsPath)) {
    throw "Khong tim thay script: $VbsPath"
}
if (-not (Test-Path -LiteralPath $BatPath)) {
    throw "Khong tim thay script: $BatPath"
}

$CurrentUser = "$env:USERDOMAIN\$env:USERNAME"

Write-Host "Dang cai dat Scheduled Task '$TaskName' cho user '$CurrentUser'..."

# Action: goi wscript.exe chay wrapper .vbs (an hoan toan, khong minimized, khong flash).
# //B = batch mode, chan moi popup loi/canh bao tu wscript.
$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "//B `"$VbsPath`"" `
    -WorkingDirectory $ProjectDir

# Trigger: chay khi user dang nhap Windows
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser

# Settings:
# - ExecutionTimeLimit = 0 (TimeSpan.Zero) => KHONG GIOI HAN thoi gian chay (server song lien tuc)
# - RestartCount / RestartInterval => tu dong restart 5 lan, moi lan cach 1 phut neu task bi loi
#   (hoat dong dung vi wscript.exe cho (wait=True) toi khi pythonw.exe thoat, nen Task Scheduler
#   thay task "that bai/ket thuc" dung luc server crash, khong phai ngay sau khi khoi chay)
# - MultipleInstances IgnoreNew => tranh chay trung nhieu instance server tren cung 1 cong
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# Principal: chay duoi quyen user hien tai, logon type Interactive (khong can Highest vi
# server chi bind localhost). Interactive can thiet de wscript/pythonw co the chay trong
# session cua user (du khong hien cua so nao).
$principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType Interactive `
    -RunLevel Limited

# Neu task da ton tai tu truoc thi go bo de cai lai cho sach
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Task '$TaskName' da ton tai, dang go bo de cai dat lai..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Tu dong chay Planner Sync Server (localhost:8765) an nen khi dang nhap Windows, phuc vu WebApp VBQPPL tao task Planner sau khi chuyen van ban." `
    | Out-Null

Write-Host "Da cai dat Scheduled Task '$TaskName' thanh cong."
Write-Host "  - Trigger: At logon (user $CurrentUser)"
Write-Host "  - Che do chay: AN HOAN TOAN (wscript.exe + pythonw.exe, khong co cua so)"
Write-Host "  - ExecutionTimeLimit: khong gioi han"
Write-Host "  - Restart on failure: 5 lan, cach nhau 1 phut"
Write-Host "  - Log: $LogPath"
Write-Host ""

Write-Host "Dang khoi dong task ngay bay gio..."
Start-ScheduledTask -TaskName $TaskName

# Cho server khoi dong (import module + bind port) roi kiem tra health, thu lai toi da 10 lan.
$isHealthy = $false
$lastError = $null
for ($i = 1; $i -le 10; $i++) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 3
        if ($health.ok) {
            $isHealthy = $true
            break
        }
    } catch {
        $lastError = $_.Exception.Message
    }
}

$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host ""
Write-Host "Trang thai task: LastTaskResult=$($taskInfo.LastTaskResult), LastRunTime=$($taskInfo.LastRunTime)"

if ($isHealthy) {
    Write-Host ""
    Write-Host "OK - Planner Sync Server dang chay NEN (khong hien cua so nao)." -ForegroundColor Green
    Write-Host "Kiem tra lai bat cu luc nao bang: Invoke-RestMethod $HealthUrl"
} else {
    Write-Host ""
    Write-Host "CANH BAO - Chua xac nhan duoc server dang chay sau 10 giay." -ForegroundColor Yellow
    if ($lastError) { Write-Host "  Loi gan nhat: $lastError" }
    Write-Host "  Kiem tra log tai: $LogPath"
    Write-Host "  Kiem tra lai thu cong bang: .\check_planner_sync_health.ps1"
}

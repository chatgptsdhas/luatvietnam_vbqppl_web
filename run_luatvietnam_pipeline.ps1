# ============================================================
# RUN LUATVIETNAM PIPELINE
# Step07 -> Step08 -> Step09
# ============================================================

$ProjectDir = "C:\Users\Admin\Desktop\luatvietnam_vbqppl"
$PythonExe = "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"

Set-Location $ProjectDir

# UTF-8 console/log
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$null = chcp 65001
$env:PLAYWRIGHT_BROWSERS_PATH = "C:\playwright-browsers"

New-Item -ItemType Directory -Path ".\output" -Force | Out-Null
New-Item -ItemType Directory -Path ".\logs" -Force | Out-Null

$TimeStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = ".\logs\pipeline_$TimeStamp.log"
$LockFile = ".\logs\pipeline.lock"

# Xóa log cũ, chỉ giữ 5 pipeline gần nhất (log hiện tại chưa tồn tại → luôn an toàn)
Get-ChildItem -Path ".\logs" -Filter "pipeline_*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 5 |
    Remove-Item -Force -ErrorAction SilentlyContinue

function Write-Log {
    param (
        [string]$Message
    )

    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $Message"
    $line | Tee-Object -FilePath $LogFile -Append
}

function Stop-With-Error {
    param (
        [string]$Message,
        [int]$ExitCode = 1
    )

    Write-Log "ERROR: $Message"

    if (Test-Path $LockFile) {
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    }

    Write-Log "PIPELINE FAILED"
    exit $ExitCode
}

function Invoke-Step {
    param (
        [string]$StepName,
        [string]$ScriptPath
    )

    if (!(Test-Path $ScriptPath)) {
        Stop-With-Error "Không tìm thấy script: $ScriptPath"
    }

    Write-Log "============================================================"
    Write-Log "$StepName START"
    Write-Log "Script: $ScriptPath"
    Write-Log "============================================================"

    & $PythonExe -X utf8 $ScriptPath 2>&1 | Tee-Object -FilePath $LogFile -Append

    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        Stop-With-Error "$StepName FAILED. ExitCode=$exitCode" $exitCode
    }

    Write-Log "$StepName DONE"
    Write-Log ""
}

# ------------------------------------------------------------
# Chặn chạy chồng pipeline
# ------------------------------------------------------------
if (Test-Path $LockFile) {
    Stop-With-Error "Pipeline đang có lock file. Có thể lần chạy trước chưa kết thúc: $LockFile"
}

New-Item -ItemType File -Path $LockFile -Force | Out-Null

try {
    Write-Log "============================================================"
    Write-Log "PIPELINE START"
    Write-Log "ProjectDir: $ProjectDir"
    Write-Log "PythonExe: $PythonExe"
    Write-Log "LogFile: $LogFile"
    Write-Log "============================================================"

    if (!(Test-Path $PythonExe)) {
        Stop-With-Error "Không tìm thấy PythonExe: $PythonExe"
    }

    if (!(Test-Path ".\config\scan_config.json")) {
        Stop-With-Error "Không tìm thấy config\scan_config.json"
    }

    if (!(Test-Path ".\auth\luatvietnam_state.json")) {
        Stop-With-Error "Không tìm thấy auth\luatvietnam_state.json. Cần chạy 01_save_session.py trước."
    }

    # ------------------------------------------------------------
    # STEP 07 - Crawl danh sách URL văn bản
    # ------------------------------------------------------------
    Invoke-Step `
        -StepName "STEP 07 - Crawl document URLs" `
        -ScriptPath ".\07_crawl_luatvietnam_list_by_field.py"

    if (!(Test-Path ".\output\field_document_urls.json")) {
        Stop-With-Error "Không tìm thấy output\field_document_urls.json sau Step07."
    }

    if (!(Test-Path ".\output\field_document_urls_readable.txt")) {
        Stop-With-Error "Không tìm thấy output\field_document_urls_readable.txt sau Step07."
    }

    # ------------------------------------------------------------
    # STEP 08 - Xử lý chi tiết và gửi Apps Script
    # ------------------------------------------------------------
    Invoke-Step `
        -StepName "STEP 08 - Process documents and send Apps Script" `
        -ScriptPath ".\08_process_field_documents_batch.py"

    if (!(Test-Path ".\output\vbqppl_nhap_batch_payload.json")) {
        Stop-With-Error "Không tìm thấy output\vbqppl_nhap_batch_payload.json sau Step08."
    }

    # ------------------------------------------------------------
    # STEP 09 - Kiểm định kết quả
    # ------------------------------------------------------------
    Invoke-Step `
        -StepName "STEP 09 - Validate pipeline result" `
        -ScriptPath ".\09_validate_pipeline_result.py"

    if (!(Test-Path ".\output\step09_validation_report.txt")) {
        Stop-With-Error "Không tìm thấy output\step09_validation_report.txt sau Step09."
    }

    if (!(Test-Path ".\output\step09_validation_report.json")) {
        Stop-With-Error "Không tìm thấy output\step09_validation_report.json sau Step09."
    }

    Write-Log "============================================================"
    Write-Log "PIPELINE DONE SUCCESSFULLY"
    Write-Log "============================================================"

    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    exit 0
}
catch {
    # Ghi log lỗi vào hệ thống (Xóa số 1 thừa ở đây)
    Stop-With-Error $_.Exception.Message 

    # Hiện thông báo Popup ra màn hình
    $wshell = New-Object -ComObject WScript.Shell
    $wshell.Popup("Cảnh báo: Hệ thống cập nhật Luật Việt Nam gặp lỗi!`n`nChi tiết: $($_.Exception.Message)", 0, "Lỗi hệ thống", 0x10)
}
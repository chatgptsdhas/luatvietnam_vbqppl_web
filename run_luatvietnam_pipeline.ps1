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
$RunId = [guid]::NewGuid().ToString("N")
$OwnsLock = $false
$LegacyLockStaleHours = 6

function Write-Log {
    param (
        [string]$Message
    )

    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $Message"
    $line | Tee-Object -FilePath $LogFile -Append
}

function Remove-OldPipelineLogs {
    # Xóa log cũ, chỉ giữ 5 pipeline gần nhất.
    Get-ChildItem -Path ".\logs" -Filter "pipeline_*.log" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip 5 |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

function Read-PipelineLock {
    param (
        [string]$Path
    )

    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    $lock = [ordered]@{
        Pid = $null
        StartedAtUtc = $null
        RunId = $null
        LogFile = $null
        LastWriteTime = $item.LastWriteTime
        Age = ((Get-Date) - $item.LastWriteTime)
        ParseError = $null
    }

    try {
        $raw = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop

        if (![string]::IsNullOrWhiteSpace($raw)) {
            $json = $raw | ConvertFrom-Json -ErrorAction Stop

            if ($json.pid) {
                $lock.Pid = [int]$json.pid
            }

            if ($json.started_at_utc) {
                try {
                    $lock.StartedAtUtc = ([datetime]$json.started_at_utc).ToUniversalTime()
                }
                catch {
                    $lock.StartedAtUtc = $null
                }
            }

            if ($json.run_id) {
                $lock.RunId = [string]$json.run_id
            }

            if ($json.log_file) {
                $lock.LogFile = [string]$json.log_file
            }
        }
    }
    catch {
        $lock.ParseError = $_.Exception.Message
    }

    return [pscustomobject]$lock
}

function Test-ProcessIsRunning {
    param (
        [int]$ProcessId,
        $StartedAtUtc = $null
    )

    try {
        $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue

        if ($null -eq $process) {
            return $false
        }

        if ($null -ne $StartedAtUtc) {
            try {
                $processStartUtc = $process.StartTime.ToUniversalTime()
                $lockStartUtc = ([datetime]$StartedAtUtc).ToUniversalTime()

                # Nếu PID đã được hệ điều hành tái sử dụng sau thời điểm tạo lock,
                # đây không còn là pipeline cũ nữa.
                if ($processStartUtc -gt $lockStartUtc.AddSeconds(5)) {
                    return $false
                }
            }
            catch {
                # Không đọc được StartTime thì chỉ dựa vào PID đang chạy.
            }
        }

        return $true
    }
    catch {
        return $false
    }
}

function Get-ActivePipelineProcess {
    $patterns = @(
        "run_luatvietnam_pipeline.ps1",
        "07_crawl_luatvietnam_list_by_field.py",
        "08_process_field_documents_batch.py",
        "09_validate_pipeline_result.py"
    )

    try {
        $processes = Get-CimInstance Win32_Process -ErrorAction Stop
        $match = $processes | Where-Object {
            if ([int]$_.ProcessId -eq [int]$PID) {
                return $false
            }

            $commandLine = [string]$_.CommandLine

            if ([string]::IsNullOrWhiteSpace($commandLine)) {
                return $false
            }

            foreach ($pattern in $patterns) {
                if ($commandLine -like "*$pattern*") {
                    return $true
                }
            }

            return $false
        } | Select-Object -First 1

        return [pscustomobject]@{
            QueryOk = $true
            Process = $match
            Error = $null
        }
    }
    catch {
        return [pscustomobject]@{
            QueryOk = $false
            Process = $null
            Error = $_.Exception.Message
        }
    }
}

function Remove-Owned-Lock {
    if (!$script:OwnsLock -or !(Test-Path -LiteralPath $script:LockFile)) {
        return
    }

    try {
        $lock = Read-PipelineLock -Path $script:LockFile

        if ($lock.RunId -eq $script:RunId) {
            Remove-Item -LiteralPath $script:LockFile -Force -ErrorAction SilentlyContinue
            $script:OwnsLock = $false
        }
        else {
            Write-Log "WARNING: Không xóa lock vì lock không thuộc phiên chạy hiện tại: $script:LockFile"
        }
    }
    catch {
        Write-Log "WARNING: Không thể kiểm tra/xóa lock: $($_.Exception.Message)"
    }
}

function Stop-With-Error {
    param (
        [string]$Message,
        [int]$ExitCode = 1
    )

    Write-Log "ERROR: $Message"
    Remove-Owned-Lock
    Write-Log "PIPELINE FAILED"
    exit $ExitCode
}

function Stop-Due-To-ActiveLock {
    param (
        [string]$Message,
        [int]$ExitCode = 1
    )

    Write-Log "ERROR: $Message"
    Write-Log "PIPELINE FAILED"
    exit $ExitCode
}

function Resolve-ExistingLock {
    if (!(Test-Path -LiteralPath $script:LockFile)) {
        return
    }

    $lock = Read-PipelineLock -Path $script:LockFile

    if ($null -ne $lock.Pid -and (Test-ProcessIsRunning -ProcessId $lock.Pid -StartedAtUtc $lock.StartedAtUtc)) {
        $details = "pid=$($lock.Pid)"

        if ($lock.LogFile) {
            $details = "$details, log=$($lock.LogFile)"
        }

        Stop-Due-To-ActiveLock "Pipeline đang chạy ($details). Lock file: $script:LockFile"
    }

    if ($null -ne $lock.Pid) {
        Write-Log "WARNING: Xóa lock cũ vì pid=$($lock.Pid) không còn chạy: $script:LockFile"
        Remove-Item -LiteralPath $script:LockFile -Force -ErrorAction Stop
        return
    }

    $activePipelineProcess = Get-ActivePipelineProcess

    if ($null -ne $activePipelineProcess.Process) {
        $process = $activePipelineProcess.Process
        Stop-Due-To-ActiveLock "Pipeline có vẻ đang chạy (pid=$($process.ProcessId), name=$($process.Name)). Lock file: $script:LockFile"
    }

    if ($activePipelineProcess.QueryOk) {
        Write-Log "WARNING: Xóa lock cũ/không có metadata vì không tìm thấy process pipeline đang chạy: $script:LockFile"
        Remove-Item -LiteralPath $script:LockFile -Force -ErrorAction Stop
        return
    }

    if ($lock.Age.TotalHours -ge $script:LegacyLockStaleHours) {
        $ageHours = [Math]::Round($lock.Age.TotalHours, 2)
        Write-Log "WARNING: Xóa lock cũ/không có metadata. Không kiểm tra được process pipeline ($($activePipelineProcess.Error)). AgeHours=$ageHours; file=$script:LockFile"
        Remove-Item -LiteralPath $script:LockFile -Force -ErrorAction Stop
        return
    }

    Stop-Due-To-ActiveLock "Pipeline đang có lock cũ/không có metadata; không kiểm tra được process pipeline và chưa đủ $script:LegacyLockStaleHours giờ để coi là stale: $script:LockFile"
}

function New-LockFile {
    param (
        [string]$Path,
        [string]$Content
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $bytes = $encoding.GetBytes($Content)
    $stream = $null

    try {
        $stream = [System.IO.File]::Open(
            $fullPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        $stream.Write($bytes, 0, $bytes.Length)
        return $true
    }
    catch [System.IO.IOException] {
        return $false
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function New-PipelineLock {
    $metadata = [ordered]@{
        run_id = $script:RunId
        pid = $PID
        started_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        log_file = $script:LogFile
        host = $env:COMPUTERNAME
        project_dir = $script:ProjectDir
    }

    $content = $metadata | ConvertTo-Json -Depth 3

    if (New-LockFile -Path $script:LockFile -Content $content) {
        $script:OwnsLock = $true
        return
    }

    # Trường hợp hai lịch chạy khởi động sát nhau: kiểm tra lại lock vừa xuất hiện.
    Resolve-ExistingLock

    if (New-LockFile -Path $script:LockFile -Content $content) {
        $script:OwnsLock = $true
        return
    }

    Stop-With-Error "Không thể tạo lock file: $script:LockFile"
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

try {
    # Chặn chạy chồng pipeline nhưng vẫn tự phục hồi nếu lock của lần chạy cũ bị sót.
    Resolve-ExistingLock
    New-PipelineLock
    Remove-OldPipelineLogs

    Write-Log "============================================================"
    Write-Log "PIPELINE START"
    Write-Log "ProjectDir: $ProjectDir"
    Write-Log "PythonExe: $PythonExe"
    Write-Log "LogFile: $LogFile"
    Write-Log "LockFile: $LockFile"
    Write-Log "RunId: $RunId"
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

    Remove-Owned-Lock
    exit 0
}
catch {
    Stop-With-Error $_.Exception.Message
}

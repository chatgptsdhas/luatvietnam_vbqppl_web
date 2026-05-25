$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = $env:PYTHON_EXE
$PythonArgs = @()

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $DefaultPythonExe = "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"
    if (Test-Path -LiteralPath $DefaultPythonExe) {
        $PythonExe = $DefaultPythonExe
    } else {
        $PythonExe = "py.exe"
        $PythonArgs = @("-3")
    }
}

Set-Location $ProjectDir

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

& $PythonExe @PythonArgs ".\planner_sync_server.py"

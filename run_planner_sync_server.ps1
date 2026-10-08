$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = $env:PYTHON_EXE
$PythonArgs = @()

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        $PythonExe = $PythonCommand.Source
    } else {
        $PyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
        if (-not $PyLauncher) {
            throw "Khong tim thay Python. Dat bien moi truong PYTHON_EXE hoac cai python.exe/py.exe vao PATH."
        }
        $PythonExe = $PyLauncher.Source
        $PythonArgs = @("-3")
    }
}

Set-Location $ProjectDir

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

& $PythonExe @PythonArgs ".\planner_sync_server.py"

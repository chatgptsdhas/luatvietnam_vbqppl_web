@echo off
REM ============================================================
REM Chay Planner Sync Server bang pythonw.exe (khong co console).
REM Duoc goi qua run_planner_sync_server_hidden.vbs (an cua so hoan
REM toan). Khong tu chay file .bat nay truc tiep neu muon xem log
REM truc tiep tren man hinh — dung run_planner_sync_server.ps1 de debug.
REM ============================================================
setlocal

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

set "LOG_FILE=logs\planner_sync_server.log"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1

set "PYTHONW_EXE=C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe"
if not exist "%PYTHONW_EXE%" set "PYTHONW_EXE=pythonw.exe"

echo ==== %date% %time% Planner Sync Server starting (%PYTHONW_EXE%) ==== >> "%LOG_FILE%"
"%PYTHONW_EXE%" "planner_sync_server.py" >> "%LOG_FILE%" 2>&1
echo ==== %date% %time% Planner Sync Server stopped (exit code %errorlevel%) ==== >> "%LOG_FILE%"

endlocal

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

REM Uu tien bien moi truong de phu hop voi may co nhieu Python. Neu khong co,
REM resolve pythonw.exe tren PATH; cuoi cung dung py.exe (VBS da an cua so).
if not defined PYTHONW_EXE if defined PYTHON_EXE set "PYTHONW_EXE=%PYTHON_EXE%"
if not defined PYTHONW_EXE (
    for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do if not defined PYTHONW_EXE set "PYTHONW_EXE=%%I"
)
if not defined PYTHONW_EXE (
    for /f "delims=" %%I in ('where py.exe 2^>nul') do if not defined PYTHONW_EXE set "PYTHONW_EXE=%%I"
)
if not defined PYTHONW_EXE (
    echo ==== %date% %time% Python/pythonw not found on PATH ==== >> "%LOG_FILE%"
    exit /b 9009
)

echo ==== %date% %time% Planner Sync Server starting (%PYTHONW_EXE%) ==== >> "%LOG_FILE%"
"%PYTHONW_EXE%" "planner_sync_server.py" >> "%LOG_FILE%" 2>&1
echo ==== %date% %time% Planner Sync Server stopped (exit code %errorlevel%) ==== >> "%LOG_FILE%"

endlocal

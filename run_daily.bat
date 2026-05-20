@echo off
REM Windows Task Scheduler entrypoint for daily cinema promotion sync.
REM Scheduled at 07:00 daily by schtasks /Create.
REM Logs: assets\data\daily_log\latest.log (console) + {YYYY-MM-DD}.json (structured)

cd /d "%~dp0"
chcp 65001 >nul

if not exist "assets\data\daily_log" mkdir "assets\data\daily_log"

REM Use absolute Python path (Task Scheduler has no user PATH)
set PYTHON="C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe"

%PYTHON% scripts\run_daily.py >> "assets\data\daily_log\latest.log" 2>&1
exit /b %ERRORLEVEL%

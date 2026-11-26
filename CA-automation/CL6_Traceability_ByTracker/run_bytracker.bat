@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
rem 예: run_bytracker.bat --ci SYS5_05  (생략하면 목록에서 고름)
python traceability_bytracker.py %*
pause

@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
rem 옵션을 직접 준 경우(예: run_traceability.bat --quick)는 묻지 않고 그대로 실행
if not "%~1"=="" goto run
echo.
echo  검사 방식을 고르세요 (10초 동안 입력이 없으면 1번 전체 검사)
echo    1. 전체 검사 - 최상위 Tracker와 하위 Tracker 전부 (CA 근거용)
echo    2. 빠른 검사 - CI list에 적힌 Tracker 하나만 (참고용)
choice /c 12 /t 10 /d 1 /n /m " 번호: "
if errorlevel 2 (
  python traceability.py --quick
  goto end
)
python traceability.py
goto end
:run
python traceability.py %*
:end
pause

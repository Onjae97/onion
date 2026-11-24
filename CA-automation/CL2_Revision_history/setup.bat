@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [CL2] Installing packages: openpyxl, playwright, pywin32, keyring
python -m pip install --upgrade openpyxl playwright pywin32 keyring
if errorlevel 1 (
  echo.
  echo [ERROR] pip install failed. Check Python install or company proxy.
) else (
  echo.
  echo [OK] Setup done. Next: run doctor.bat
)
pause

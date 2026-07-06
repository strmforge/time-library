@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%SCRIPT_DIR%tools\windows_double_click_install.ps1"
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" (
  echo [time-library] Installer exited with code %EXITCODE%.
) else (
  echo [time-library] Install finished.
)
echo Press any key to close this window.
pause >nul
exit /b %EXITCODE%

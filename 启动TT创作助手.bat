@echo off
setlocal
cd /d "%~dp0"
title TT Creation Assistant
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\run_dev.ps1" %*
set "TT_EXIT_CODE=%ERRORLEVEL%"
if not "%TT_EXIT_CODE%"=="0" (
    echo.
    pause
)
exit /b %TT_EXIT_CODE%

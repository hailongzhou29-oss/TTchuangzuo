@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
title TT Creation Assistant
set "TT_PYTHON="
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%~dp0local.runtime.json") do if "%%A"=="python" set "TT_PYTHON=%%B"
set "TT_PYTHON=%TT_PYTHON:\\=\%"
for %%P in ("%TT_PYTHON%") do set "TT_PYTHONW=%%~dpPpythonw.exe"
if not exist "%TT_PYTHONW%" (
    echo Launch failed: configure an existing Python path in local.runtime.json.
    pause
    exit /b 1
)
start "" "%TT_PYTHONW%" "%~dp0tools\gui_bootstrap.pyw" %*
exit /b %ERRORLEVEL%

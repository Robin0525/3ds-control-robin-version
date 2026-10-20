@echo off
rem ============================================================
rem  3DS Controller - PC receiver launcher
rem  Keep this window open while playing.
rem ============================================================
setlocal
title 3DS Controller Receiver

set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "%~dp0..\pc\pc.py" (
    echo [ERROR] pc\pc.py not found
    pause
    exit /b 1
)

echo ============================================
echo  3DS Controller - PC Receiver
echo  Keep this window open while playing.
echo  Now launch "3DS Controller" on the 3DS.
echo ============================================
echo.
echo python: %PY%
echo.

"%PY%" -u "%~dp0..\pc\pc.py" %*

echo.
echo Receiver stopped. Press any key to close.
pause

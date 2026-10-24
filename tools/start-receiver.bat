@echo off
rem ============================================================
rem  3DS Control - PC receiver (gamepad + pointer in one window)
rem  Keep this window open while playing.
rem ============================================================
setlocal
title 3DS Control Receiver

set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "%~dp0..\pc\receiver_all.py" (
    echo [ERROR] pc\receiver_all.py not found
    pause
    exit /b 1
)

echo ============================================
echo  3DS Control - PC Receiver
echo  Keep this window open while playing.
echo  Now launch "3DS Control" on the 3DS.
echo ============================================
echo.
echo python: %PY%
echo.

"%PY%" -u "%~dp0..\pc\receiver_all.py" %*

echo.
echo Receiver stopped. Press any key to close.
pause

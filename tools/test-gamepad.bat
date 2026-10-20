@echo off
rem Read the virtual XInput gamepad and print its live state.
rem Use it to confirm that 3DS button presses actually reach the PC.
setlocal
title Gamepad Input Test

set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================
echo  Keep the receiver + 3DS running, then press
echo  buttons (A / B / D-pad) while this watches.
echo  Note: most games read XInput slot 0 only.
echo ============================================
echo.

"%PY%" -u "%~dp0test-gamepad.py" %*

echo.
pause

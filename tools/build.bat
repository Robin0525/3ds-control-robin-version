@echo off
rem ============================================================
rem  Build 3ds_controller.3dsx (needs devkitPro + devkitARM + 3ds-dev)
rem  Output: src\3ds_controller.3dsx  -> copy to prebuilt\
rem ============================================================
setlocal

if "%DEVKITPRO%"=="" set "DEVKITPRO=C:\devkitPro"
if "%DEVKITARM%"=="" set "DEVKITARM=%DEVKITPRO%\devkitARM"
set "PATH=%DEVKITPRO%\tools\bin;%DEVKITARM%\bin;%DEVKITPRO%\msys2\usr\bin;%PATH%"

if not exist "%DEVKITARM%\bin\arm-none-eabi-gcc.exe" (
    echo [ERROR] devkitARM not found at %DEVKITARM%
    echo Install devkitPro with 3DS support: https://devkitpro.org/wiki/Getting_Started
    pause
    exit /b 1
)

cd /d "%~dp0..\src"
if exist build rmdir /s /q build
if exist 3ds_controller.elf del /q 3ds_controller.elf

make -j4
if errorlevel 1 (
    echo.
    echo [FAILED] build error
    pause
    exit /b 1
)

echo.
if exist 3ds_controller.3dsx (
    copy /y 3ds_controller.3dsx "%~dp0..\prebuilt\3ds_controller.3dsx" >nul
    echo [OK] 3ds_controller.3dsx built and copied to prebuilt\
) else (
    echo [WARN] build finished but no 3dsx found
)
echo.
pause

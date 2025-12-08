@echo off
echo ===================================================
echo Building CiderBridge Release v1.0
echo ===================================================

echo.
echo 1. Cleaning previous builds...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

echo.
echo 2. Running PyInstaller...
echo    - Icon: src/assets/app_icon.ico
echo    - Mode: OneFile, Windowed (No Console)
echo.

python -m PyInstaller --noconfirm --onefile --windowed --name "CiderBridge_v1.0" --icon "src/assets/app_icon.ico" --add-data "src/assets/app_icon.ico;src/assets" --hidden-import "PIL._tkinter_finder" --collect-all customtkinter --version-file "version_info.txt" main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: PyInstaller failed!
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo 3. Copying README.txt...
copy "README.txt" "dist\"

echo.
echo ===================================================
echo BUILD SUCCESSFUL!
echo Location: dist/CiderBridge_v1.0.exe
echo ===================================================
pause

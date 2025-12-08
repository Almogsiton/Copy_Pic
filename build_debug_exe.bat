@echo off
echo Building iPhone Media Backup Tool (DEBUG MODE - Console Visible)...
python -m PyInstaller --noconfirm --onefile --console --collect-all customtkinter main.py
echo Build Complete! Executable is in the 'dist' folder.
pause

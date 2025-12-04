@echo off
echo Building iPhone Media Backup Tool...
python -m PyInstaller --noconfirm --onefile --windowed --collect-all customtkinter main.py
echo Build Complete! Executable is in the 'dist' folder.
pause

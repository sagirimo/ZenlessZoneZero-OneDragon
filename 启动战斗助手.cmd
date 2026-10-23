@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Python environment is missing. Run the install CMD first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0tools\battle_assistant.py"

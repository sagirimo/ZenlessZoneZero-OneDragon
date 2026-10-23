@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -File "%~dp0tools\setup_battle_assistant.ps1"
pause

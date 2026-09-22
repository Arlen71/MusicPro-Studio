@echo off
setlocal
cd /d "%~dp0"
"%~dp0runtime\python.exe" -X utf8 -B "%~dp0app\bootstrap.py" --check
if errorlevel 1 pause

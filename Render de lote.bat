@echo off
cd /d "%~dp0automacao"
python app.py
if errorlevel 1 pause

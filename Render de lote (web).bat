@echo off
title Render de lote (web)
cd /d "%~dp0automacao"
python servidor.py
if errorlevel 1 pause

@echo off
cd /d %~dp0
powershell -ExecutionPolicy Bypass -File scripts\start_sylphie.ps1
if errorlevel 1 pause

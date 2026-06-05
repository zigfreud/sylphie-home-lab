@echo off
cd /d %~dp0
python src\server\sylphie_server.py --host 127.0.0.1 --port 8765 --exe bin\sylphie_rgb.exe

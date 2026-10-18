@echo off
title TOPSHELFMI — Server & Admin
cd /d "%~dp0"

echo ========================================================
echo       TOPSHELFMI — GALLERY & ADMIN SERVER
echo ========================================================
echo.
echo Avvio del server in corso...
echo.

start "" "http://localhost:5000"
start "" "http://localhost:5000/admin"

python app.py

pause

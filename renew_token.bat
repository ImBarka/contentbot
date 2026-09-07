@echo off
title ContentBot - OAuth Token Renewal
cd /d "%~dp0"
"C:\Users\kawa crtve\AppData\Local\Programs\Python\Python312\python.exe" refresh_token.py
echo.
pause

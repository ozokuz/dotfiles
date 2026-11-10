@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0env.ps1" %*
exit /b %errorlevel%

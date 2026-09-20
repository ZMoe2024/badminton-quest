@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 start_web.py %*
) else (
  python start_web.py %*
)
pause

@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if defined BADMINTON_PYTHON (
  "%BADMINTON_PYTHON%" "%~dp0launcher.py" %*
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0launcher.py" %*
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0launcher.py" %*
  goto finished
)
echo Python 3.10+ is required. Install it from https://www.python.org/downloads/
echo Enable "Add Python to PATH" during installation, then start again.
:finished
pause

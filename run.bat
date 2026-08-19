@echo off
cd /d "%~dp0"

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

REM Cheap when already satisfied, and picks up requirement changes.
pip install -q -r requirements.txt || goto :error

REM No browser download needed: core/browser.py drives your installed Chrome
REM via channel="chrome", so the session and login persist in a real profile.

start "" http://127.0.0.1:8000
python -m uvicorn server:app --host 127.0.0.1 --port 8000
goto :eof

:error
echo.
echo Dependency install failed. Check that Python 3.11+ is on PATH.
pause

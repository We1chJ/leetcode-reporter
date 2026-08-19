@echo off
cd /d "%~dp0"

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
  python -m playwright install chromium
) else (
  call .venv\Scripts\activate.bat
)

start "" http://127.0.0.1:8000
python -m uvicorn server:app --host 127.0.0.1 --port 8000

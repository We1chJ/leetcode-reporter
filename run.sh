#!/usr/bin/env bash
# macOS / Linux equivalent of run.bat.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate

# Cheap when already satisfied, and picks up requirement changes.
pip install -q -r requirements.txt

# No browser download needed: core/browser.py drives your installed Chrome
# via channel="chrome", so the session and login persist in a real profile.

(sleep 2 && (open http://127.0.0.1:8000 2>/dev/null || xdg-open http://127.0.0.1:8000 2>/dev/null)) &
python -m uvicorn server:app --host 127.0.0.1 --port 8000

#!/usr/bin/env bash
# macOS / Linux equivalent of start_chrome.bat.
#
# This is a normal browser: Playwright does not launch it, so it carries no
# automation flags and sign-in behaves like any other browsing session.
# Sign in to LeetCode in the window that opens, then leave it open and run
# the scan. The profile is kept in data/chrome-profile, separate from your
# everyday Chrome, so this never touches your normal tabs or history.
set -e
cd "$(dirname "$0")"

PROFILE="$PWD/data/chrome-profile"

for c in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  /usr/bin/google-chrome /usr/bin/google-chrome-stable \
  /usr/bin/chromium /usr/bin/chromium-browser /snap/bin/chromium
do
  [ -x "$c" ] && CHROME="$c" && break
done

if [ -z "${CHROME:-}" ]; then
  echo "Could not find Chrome. Edit this file and set CHROME to its path."
  exit 1
fi

mkdir -p "$PROFILE"

echo "Starting Chrome with remote debugging on port 9222..."
echo "Sign in to LeetCode, then leave that window open."
"$CHROME" --remote-debugging-port=9222 --user-data-dir="$PROFILE" \
  https://leetcode.com/accounts/login/ >/dev/null 2>&1 &

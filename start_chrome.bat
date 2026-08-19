@echo off
REM Starts an ordinary Chrome with a debugging port so the reporter can attach.
REM
REM This is a normal browser: Playwright does not launch it, so it carries no
REM automation flags and sign-in behaves like any other browsing session.
REM Sign in to LeetCode in the window that opens, then leave it open and run
REM the scan. The profile is kept in data\chrome-profile, separate from your
REM everyday Chrome, so this never touches your normal tabs or history.

setlocal
set "PROFILE=%~dp0data\chrome-profile"
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if not exist "%CHROME%" (
  echo Could not find chrome.exe. Edit this file and set CHROME to its path.
  pause
  exit /b 1
)

if not exist "%PROFILE%" mkdir "%PROFILE%"

echo Starting Chrome with remote debugging on port 9222...
echo Sign in to LeetCode, then leave this window open.
start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%PROFILE%" https://leetcode.com/accounts/login/
endlocal

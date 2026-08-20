"""Start and inspect the debugging Chrome that the tool attaches to.

The scan attaches to a Chrome you started yourself rather than launching its
own, because a Playwright-launched browser advertises itself as automated and
LeetCode's sign-in verification refuses it. That means the browser can simply
not be there -- closed, or never started -- so the dashboard needs to be able
to see that and offer to start it.
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from core import config

LOGIN_URL = "https://leetcode.com/accounts/login/"

# Where Chrome installs itself, per platform. macOS puts the executable inside
# the .app bundle; the bundle path itself is not runnable.
CANDIDATES = {
    "win32": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
    ],
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ],
    "linux": [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
    ],
}


def _port():
    return config.load()["browser"].get("cdp_url", "http://127.0.0.1:9222")


def _profile():
    return config.ROOT / config.load()["browser"]["user_data_dir"]


def chrome_path():
    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    for c in CANDIDATES.get(platform, []):
        if Path(c).exists():
            return c
    return None


def is_up(timeout=1.5):
    """Is a debuggable Chrome listening?"""
    try:
        with urllib.request.urlopen(f"{_port()}/json/version", timeout=timeout) as r:
            return json.loads(r.read().decode()).get("Browser")
    except Exception:
        return None


def status():
    browser = is_up()
    return {
        "connected": bool(browser),
        "browser": browser,
        "chrome_found": bool(chrome_path()),
        "profile": str(_profile()),
    }


def start(wait_seconds=15):
    """Launch Chrome with the debugging port, on the tool's own profile.

    Returns the same shape as status(). Safe to call when already running: the
    port check short-circuits.
    """
    if is_up():
        return status()

    exe = chrome_path()
    if not exe:
        return {"connected": False, "chrome_found": False,
                "error": "Chrome not found in the usual locations"}

    profile = _profile()
    profile.mkdir(parents=True, exist_ok=True)
    port = _port().rsplit(":", 1)[-1]

    # Detach so Chrome outlives the server process. The mechanism differs by
    # platform: creationflags exists only on Windows, start_new_session only on
    # POSIX, and passing the wrong one raises.
    detach = ({"creationflags": subprocess.DETACHED_PROCESS}
              if sys.platform == "win32" else {"start_new_session": True})
    subprocess.Popen(
        [exe, f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", LOGIN_URL],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **detach,
    )

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if is_up():
            break
        time.sleep(0.5)
    return status()

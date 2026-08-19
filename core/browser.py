"""Playwright session against LeetCode.

LeetCode sits behind Cloudflare and rejects unauthenticated HTTP, so every
request has to originate from a real logged-in browser. We keep a persistent
Chrome profile: the user logs in by hand once and the session is reused.
"""

import contextlib

from playwright.sync_api import sync_playwright

from core import config

BASE = "https://leetcode.com"


class Session:
    def __init__(self):
        cfg = config.load()["browser"]
        self._profile = config.ROOT / cfg["user_data_dir"]
        self._headless = cfg["headless"]
        self._pw = None
        self.context = None
        self.page = None

    def __enter__(self):
        self._profile.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self._profile),
            headless=self._headless,
            channel="chrome",
            viewport={"width": 1440, "height": 900},
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def __exit__(self, *exc):
        with contextlib.suppress(Exception):
            self.context.close()
        with contextlib.suppress(Exception):
            self._pw.stop()

    def whoami(self):
        """Signed-in username, or None.

        LEETCODE_SESSION is HttpOnly, so it is invisible to page JavaScript --
        ask the API instead of sniffing document.cookie.
        """
        if self.page.url == "about:blank":
            self.page.goto(f"{BASE}/contest/", wait_until="domcontentloaded")
        res = self.page.evaluate(
            """async () => {
                const r = await fetch('/graphql/', {method: 'POST',
                    credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(
                        {query: '{ userStatus { isSignedIn username } }'})});
                const j = await r.json();
                return j.data && j.data.userStatus;
            }"""
        )
        return res["username"] if res and res.get("isSignedIn") else None

    def require_login(self, timeout_ms=300_000):
        """Open the login page and block until the user has signed in."""
        if self.whoami():
            return
        if self._headless:
            raise RuntimeError(
                "Not logged in and running headless. Set browser.headless = false "
                "in config.toml and sign in once to seed the profile."
            )
        self.page.goto(f"{BASE}/accounts/login/")
        self.page.wait_for_url(lambda u: "/accounts/login" not in u, timeout=timeout_ms)
        if not self.whoami():
            raise RuntimeError("login did not complete")

    def get_json(self, url):
        """Fetch JSON from inside the page so cookies and CF clearance apply."""
        return self.page.evaluate(
            """async (u) => {
                const r = await fetch(u, {credentials: 'include',
                                          headers: {'Accept': 'application/json'}});
                if (!r.ok) return {__error: r.status};
                return await r.json();
            }""",
            url,
        )

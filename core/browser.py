"""Playwright session against LeetCode.

LeetCode sits behind Cloudflare and rejects unauthenticated HTTP, so every
request has to originate from a real logged-in browser.

Two modes, set by `browser.mode` in config.toml:

  attach  (recommended)
      Connect over CDP to a Chrome you started yourself with
      --remote-debugging-port. Playwright never launches the browser, so it is
      an ordinary Chrome: no automation flags, no navigator.webdriver. You sign
      in by hand in that window like any other browsing session, and the tool
      simply reuses it. Start it with start_chrome.bat.

  launch
      Let Playwright start its own Chrome against a private profile. Simpler,
      but a Playwright-launched browser advertises itself as automated, and
      LeetCode's sign-in verification tends to refuse it.
"""

import contextlib

from playwright.sync_api import sync_playwright

from core import config

BASE = "https://leetcode.com"


class NoBrowserError(RuntimeError):
    pass


class Session:
    def __init__(self):
        cfg = config.load()["browser"]
        self.mode = cfg.get("mode", "attach")
        self.cdp_url = cfg.get("cdp_url", "http://127.0.0.1:9222")
        self._profile = config.ROOT / cfg["user_data_dir"]
        self._headless = cfg["headless"]
        self._pw = None
        self._browser = None
        self.context = None
        self.page = None

    def __enter__(self):
        self._pw = sync_playwright().start()
        if self.mode == "attach":
            self._attach()
        else:
            self._launch()
        return self

    def _attach(self):
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
        except Exception as exc:
            raise NoBrowserError(
                f"Could not attach to Chrome at {self.cdp_url}. Start it with "
                f"start_chrome.bat (or run Chrome with "
                f"--remote-debugging-port=9222), sign in to LeetCode there, "
                f"and leave the window open. Original error: {exc}"
            ) from exc
        self.context = (self._browser.contexts[0] if self._browser.contexts
                        else self._browser.new_context())
        # Prefer a tab already on LeetCode so we do not disturb other tabs.
        for p in self.context.pages:
            if "leetcode.com" in p.url:
                self.page = p
                break
        else:
            self.page = (self.context.pages[0] if self.context.pages
                         else self.context.new_page())

    def _launch(self):
        self._profile.mkdir(parents=True, exist_ok=True)
        self.context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self._profile),
            headless=self._headless,
            channel="chrome",
            viewport={"width": 1440, "height": 900},
        )
        self.page = (self.context.pages[0] if self.context.pages
                     else self.context.new_page())

    def __exit__(self, *exc):
        # In attach mode the browser belongs to the user; never close it.
        if self.mode != "attach":
            with contextlib.suppress(Exception):
                self.context.close()
        else:
            with contextlib.suppress(Exception):
                self._browser.close()      # detaches CDP, leaves Chrome running
        with contextlib.suppress(Exception):
            self._pw.stop()

    def whoami(self):
        """Signed-in username, or None.

        LEETCODE_SESSION is HttpOnly, so it is invisible to page JavaScript --
        ask the API instead of sniffing document.cookie.
        """
        # Relative fetches only resolve correctly from a leetcode.com page.
        if "leetcode.com" not in self.page.url:
            self.page.goto(f"{BASE}/contest/", wait_until="domcontentloaded")
        res = self.page.evaluate(
            """async () => {
                try {
                    const r = await fetch('/graphql/', {method: 'POST',
                        credentials: 'include',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(
                            {query: '{ userStatus { isSignedIn username } }'})});
                    if (!r.ok) return null;
                    const j = await r.json();
                    return j.data && j.data.userStatus;
                } catch (e) { return null; }   // signed out serves HTML, not JSON
            }"""
        )
        return res["username"] if res and res.get("isSignedIn") else None

    def require_login(self, timeout_ms=300_000):
        """Ensure the session is signed in.

        In attach mode we never drive the sign-in form: you log in yourself in
        your own browser window, and this just waits for that to happen.
        """
        if self.whoami():
            return
        if self.mode == "attach":
            raise NoBrowserError(
                "Attached to Chrome, but not signed in to LeetCode. Sign in in "
                "that Chrome window, then run this again."
            )
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

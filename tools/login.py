"""One-time login to seed the browser profile.

Opens Chrome on the LeetCode login page and waits for you to sign in by hand.
The session is saved in the profile directory, so every later scan runs
unattended. Run this once, or again if the session ever expires.

    python -m tools.login
"""

import sys

from core.browser import Session


def main():
    with Session() as s:
        who = s.whoami()
        if who:
            print(f"Already signed in as {who}. Nothing to do.")
            return 0

        print("Opening the LeetCode login page. Sign in in the Chrome window "
              "that just opened; this will wait up to 5 minutes.", flush=True)
        try:
            s.require_login()
        except Exception as exc:
            print(f"Login did not complete: {exc}")
            return 1

        who = s.whoami()
        if not who:
            print("Login did not complete.")
            return 1
        print(f"Signed in as {who}. The session is saved; scans can now run "
              f"unattended.")
        return 0


if __name__ == "__main__":
    sys.exit(main())

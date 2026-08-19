"""STEP 0 spike: discover LeetCode's replay endpoint by watching real traffic.

The Code Replay endpoint is not publicly documented, so we capture it. Run this,
then in the browser window that opens: click a submission icon on the ranking
board and play the code replay. Every XHR/fetch LeetCode makes is written to
tools/captures/ along with its response body.

    python -m tools.discover weekly-contest-450

Afterwards, inspect tools/captures/index.json to find the replay request, and
wire its URL template and JSON shape into core/replay.py.
"""

import json
import re
import sys
from pathlib import Path

from core.browser import BASE, Session

OUT = Path(__file__).resolve().parent / "captures"

# Noise we never care about.
SKIP = re.compile(
    r"(google|gstatic|doubleclick|sentry|segment|hotjar|cloudflareinsights"
    r"|\.css|\.js$|\.png|\.jpg|\.svg|\.woff)", re.I
)


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "weekly-contest-450"
    OUT.mkdir(parents=True, exist_ok=True)
    index = []

    with Session() as s:
        s.require_login()

        def on_response(resp):
            url = resp.url
            if "leetcode.com" not in url or SKIP.search(url):
                return
            ctype = resp.headers.get("content-type", "")
            if "json" not in ctype:
                return
            try:
                body = resp.json()
            except Exception:
                return
            n = len(index)
            entry = {
                "n": n,
                "method": resp.request.method,
                "url": url,
                "post_data": resp.request.post_data,
                "status": resp.status,
            }
            # GraphQL: record the operation name so the replay query is findable.
            if resp.request.post_data and "graphql" in url:
                try:
                    entry["operation"] = json.loads(resp.request.post_data).get(
                        "operationName"
                    )
                except Exception:
                    pass
            index.append(entry)
            (OUT / f"{n:03d}.json").write_text(
                json.dumps({"request": entry, "response": body}, indent=2)[:2_000_000],
                encoding="utf-8",
            )
            print(f"[{n:03d}] {entry.get('operation') or entry['method']} {url[:110]}")

        s.page.on("response", on_response)
        s.page.goto(f"{BASE}/contest/{slug}/ranking/", wait_until="domcontentloaded")

        print("\n" + "=" * 72)
        print("Browser is open. Now, by hand:")
        print("  1. click the icon next to a contestant's submission time")
        print("  2. in the code popup, open / play the Code Replay")
        print("  3. also open the 'Report Cheating' dialog (do NOT submit it)")
        print("Then press Enter here to save the capture index.")
        print("=" * 72)
        input()

        (OUT / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
        print(f"\nWrote {len(index)} captures to {OUT}")


if __name__ == "__main__":
    main()

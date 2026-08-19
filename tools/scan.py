"""Run a scan from the command line, printing progress to stdout.

Same pipeline the web UI drives; useful for a first run or for debugging the
replay scraper, where a terminal log is easier to read than the browser.

    python -m tools.scan weekly-contest-515
"""

import sys

from core.pipeline import Pipeline


def emit(ev):
    t = ev.get("type")
    if t == "progress":
        print(f"  .. rank {ev['rank']}: {ev['user']}", flush=True)
    elif t == "log":
        print(f"  [{ev.get('level', 'info')}] {ev['msg']}", flush=True)
    elif t == "report":
        print(f"  >> REPORT {ev['user']} / {ev['question']} :: {ev['reason']} "
              f"({ev['score']}) -> {ev['outcome']}", flush=True)
    elif t == "scan_start":
        print(f"== scan {ev['contest']}  dry_run={ev['dry_run']}", flush=True)
    elif t == "scan_end":
        print(f"== {ev['status']}: scanned={ev['scanned']} "
              f"flagged={ev['flagged']} reported={ev['reported']}", flush=True)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    Pipeline(emit).scan(sys.argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())

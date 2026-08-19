"""Clear the lifetime counters and the local report log.

The counters accumulated across several detector revisions, including two that
were wrong, so the totals do not describe the current rules. This resets them
so "reports sent" counts only what was actually filed from here on.

Does not touch anything on LeetCode. Reports already filed there stay filed,
and the duplicate check still consults LeetCode directly, so clearing the local
log cannot cause the same submission to be reported twice.

    python -m tools.reset_counters --yes
"""

import sys

from db import store


def main():
    if "--yes" not in sys.argv:
        print(__doc__)
        print("Refusing to clear without --yes.")
        return 2

    conn = store.connect()
    try:
        before = store.stats(conn)
        n_reports = len(store.reports(conn, 100_000))
        conn.execute("DELETE FROM stats")
        conn.execute("DELETE FROM reports")
        conn.execute("DELETE FROM scans")
        conn.commit()
        print(f"cleared {n_reports} local report rows and the scan history")
        print(f"  before: {before}")
        print(f"  after:  {store.stats(conn)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

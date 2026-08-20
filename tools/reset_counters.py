"""Clear the local findings log and scan history.

The totals on the dashboard are counted from these rows, so emptying them puts
every number back to zero. Use it to start a contest fresh, or after a detector
change makes older verdicts no longer describe the current rules.

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
        n_reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        conn.execute("DELETE FROM reports")
        conn.execute("DELETE FROM scans")
        conn.commit()
        print(f"cleared {n_reports} finding row(s) and the scan history")
        print(f"  before: {before}")
        print(f"  after:  {store.stats(conn)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""SQLite persistence: findings, scans, and the totals derived from them."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core import config

SCHEMA = Path(__file__).resolve().parent / "schema.sql"

# Created after the migration, not in schema.sql: an older database has not
# grown the verdict column yet at the point the tables are declared.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_reports_contest ON reports (contest_slug);
CREATE INDEX IF NOT EXISTS idx_reports_verdict ON reports (verdict);
CREATE INDEX IF NOT EXISTS idx_rank_contest ON rank_history (contest_slug, username);
"""

CHEAT = "cheat"
GREY = "grey"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _migrate(conn):
    """Bring a database written by an older version up to the current shape.

    Columns are added rather than recreated so existing rows survive. The old
    `stats` table held running counters that double-counted rescans and counted
    scans that never got started; the totals are computed from the rows now, so
    it is dropped.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(reports)")}
    if "verdict" not in cols:
        conn.execute("ALTER TABLE reports ADD COLUMN verdict TEXT NOT NULL "
                     "DEFAULT 'cheat'")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(scans)")}
    if "submissions_seen" not in cols:
        conn.execute("ALTER TABLE scans ADD COLUMN submissions_seen INTEGER "
                     "NOT NULL DEFAULT 0")
    conn.execute("DROP TABLE IF EXISTS stats")
    conn.commit()


def connect():
    db_path = config.path("database")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    _migrate(conn)
    conn.executescript(INDEXES)
    return conn


# --- findings ------------------------------------------------------------

def record_report(conn, *, username, contest_slug, question_slug, submission_id,
                  reason_code, score, evidence, narrative, dry_run,
                  verdict=CHEAT):
    """Persist a finding before any submission attempt.

    Returns the row id, or None if this submission+reason is already on file.
    That None is what keeps a rescan from counting the same submission twice.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO reports "
        "(username, contest_slug, question_slug, submission_id, verdict,"
        " reason_code, score, evidence_json, narrative, created_at, dry_run) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (username, contest_slug, question_slug, submission_id, verdict,
         reason_code, score, json.dumps(evidence), narrative, _now(),
         int(dry_run)),
    )
    conn.commit()
    if cur.rowcount:
        return cur.lastrowid

    # Already on file. Hand back the existing row so a report that never landed
    # can be attempted again -- an attempt that failed partway (a closed page, a
    # disabled Submit button) must not exempt the submission for good.
    row = conn.execute(
        "SELECT id, outcome FROM reports WHERE submission_id=? AND reason_code=?",
        (submission_id, reason_code),
    ).fetchone()
    if row and row["outcome"] != "submitted":
        return row["id"]
    return None


def mark_report(conn, report_id, outcome, error=None):
    conn.execute(
        "UPDATE reports SET outcome=?, error=?, submitted_at=? WHERE id=?",
        (outcome, error, _now() if outcome == "submitted" else None, report_id),
    )
    conn.commit()


def already_reported(conn, submission_id):
    """Has this submission already been filed successfully?

    Only a report that actually landed counts. A row whose attempt failed is
    unfinished business, not a record of a filing, and skipping it would leave
    the submission unreportable for good.

    Grey rows do not count either: a submission recorded for review must still
    be re-examined on a later scan.
    """
    return conn.execute(
        "SELECT 1 FROM reports WHERE submission_id=? AND verdict=? "
        "AND outcome='submitted'",
        (submission_id, CHEAT),
    ).fetchone() is not None


def reports(conn, limit=200):
    rows = conn.execute(
        "SELECT * FROM reports WHERE verdict=? ORDER BY id DESC LIMIT ?",
        (CHEAT, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def by_user(conn):
    """Reports grouped by contestant, for display only.

    This is a view over what was filed, not a profile used in judging: no
    verdict ever consults a contestant's past.
    """
    rows = conn.execute(
        "SELECT username,"
        "       COUNT(*) AS submissions,"
        "       COUNT(DISTINCT contest_slug) AS contests,"
        "       GROUP_CONCAT(DISTINCT reason_code) AS reasons,"
        "       MAX(score) AS top_score,"
        "       SUM(CASE WHEN outcome='submitted' THEN 1 ELSE 0 END) AS sent,"
        "       MAX(created_at) AS last_seen "
        "FROM reports WHERE verdict=? GROUP BY username "
        "ORDER BY submissions DESC, last_seen DESC",
        (CHEAT,),
    ).fetchall()
    return [dict(r) for r in rows]


# --- totals --------------------------------------------------------------

def stats(conn):
    """Lifetime totals, counted from the rows rather than incremented.

    Nothing here can be inflated by pressing Scan: a scan that crashed or was
    stopped before it read a contestant leaves a row with ranks_scanned = 0 and
    is excluded, and scanning the same contest twice still counts one contest
    and one finding per submission.
    """
    caught, suspicious, users_caught, users_suspicious = conn.execute(
        "SELECT COUNT(DISTINCT CASE WHEN verdict=? THEN submission_id END),"
        "       COUNT(DISTINCT CASE WHEN verdict=? THEN submission_id END),"
        "       COUNT(DISTINCT CASE WHEN verdict=? THEN username END),"
        "       COUNT(DISTINCT CASE WHEN verdict=? THEN username END) "
        "FROM reports", (CHEAT, GREY, CHEAT, GREY),
    ).fetchone()
    # Two ways to count what was filed: one row per report, and one per person.
    # A contestant who pasted all four problems is four reports but one
    # offender, and the headline is about people.
    sent, users_reported = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT username) "
        "FROM reports WHERE outcome='submitted'"
    ).fetchone()
    # Per contest, not per scan: the deepest scan of a contest is what was
    # covered, so rescanning the top 100 five times is still 100 contestants.
    # Summing the scan rows counted the same people once per rescan.
    contestants, submissions, contests_seen = conn.execute(
        "SELECT COALESCE(SUM(deepest), 0), COALESCE(SUM(seen), 0), COUNT(*) "
        "FROM (SELECT MAX(ranks_scanned) AS deepest,"
        "             MAX(submissions_seen) AS seen"
        "        FROM scans GROUP BY contest_slug"
        "       HAVING MAX(ranks_scanned) > 0)"
    ).fetchone()
    return {
        "cheating_submissions_caught": caught,
        "reports_submitted": sent,
        "suspicious_recorded": suspicious,
        "users_caught": users_caught,
        "users_reported": users_reported,
        "users_suspicious": users_suspicious,
        "contestants_scanned": contestants,
        "submissions_scanned": submissions,
        "contests_scanned": contests_seen,
    }


# --- scans ---------------------------------------------------------------

def start_scan(conn, contest_slug):
    cur = conn.execute(
        "INSERT INTO scans (contest_slug, started_at) VALUES (?,?)",
        (contest_slug, _now()),
    )
    conn.commit()
    return cur.lastrowid


def finish_scan(conn, scan_id, ranks_scanned, submissions_seen, flagged,
                reported, status="done"):
    conn.execute(
        "UPDATE scans SET finished_at=?, ranks_scanned=?, submissions_seen=?,"
        " flagged=?, reported=?, status=? WHERE id=?",
        (_now(), ranks_scanned, submissions_seen, flagged, reported, status,
         scan_id),
    )
    conn.commit()


def contests(conn, limit=50):
    """One row per contest, however many times it has been scanned.

    Depth is the deepest single scan, not the sum: scanning the top 100 twice
    covers 100 contestants, not 200. Reports do sum, because a rescan only ever
    files submissions the earlier scan did not.
    """
    rows = conn.execute(
        "SELECT contest_slug,"
        "       COUNT(*) AS scans,"
        "       MAX(ranks_scanned) AS contestants,"
        "       MAX(submissions_seen) AS inspected,"
        "       SUM(reported) AS reported,"
        "       MIN(started_at) AS first_at,"
        "       MAX(started_at) AS last_at,"
        "       (SELECT status FROM scans WHERE contest_slug = s.contest_slug"
        "          ORDER BY id DESC LIMIT 1) AS status"
        " FROM scans s GROUP BY contest_slug ORDER BY last_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# --- my own rank ---------------------------------------------------------

def record_rank(conn, contest_slug, username, rank):
    """Append one reading of my rank in a contest.

    Consecutive identical readings are skipped: a scan that moved nobody says
    nothing new, and the first and latest values are what the total is built
    from either way.
    """
    last = conn.execute(
        "SELECT rank FROM rank_history WHERE contest_slug=? AND username=? "
        "ORDER BY id DESC LIMIT 1", (contest_slug, username)).fetchone()
    if last and last["rank"] == rank:
        return None
    cur = conn.execute(
        "INSERT INTO rank_history (contest_slug, username, rank, seen_at) "
        "VALUES (?,?,?,?)", (contest_slug, username, rank, _now()))
    conn.commit()
    return cur.lastrowid


def scanned_contests(conn):
    """Contest slugs this app has actually scanned.

    Rank tracking follows scanning: a contest enters the list the first time it
    is scanned, and its rank at that moment is the baseline everything later is
    measured against. Contests entered before the app existed are deliberately
    not tracked -- there is no baseline for them and nothing to attribute.
    """
    rows = conn.execute("SELECT DISTINCT contest_slug FROM scans").fetchall()
    return sorted(r["contest_slug"] for r in rows)


def rank_progress(conn, username=None):
    """Per contest: the first rank recorded, the latest, and the gain.

    `moved_up` is first minus latest, so a smaller rank number -- which is a
    better placing -- reads as a positive gain.
    """
    # MIN(rank) is the best placing ever seen and MAX(rank) the worst: a
    # smaller rank number is a better result, so the names are the other way
    # round from the arithmetic.
    sql = ("SELECT h.contest_slug, h.username, COUNT(*) AS readings,"
           " MIN(h.seen_at) AS first_at, MAX(h.seen_at) AS last_at,"
           " MIN(h.rank) AS best_rank, MAX(h.rank) AS worst_rank,"
           " (SELECT rank FROM rank_history WHERE contest_slug=h.contest_slug"
           "    AND username=h.username ORDER BY id ASC  LIMIT 1) AS first_rank,"
           " (SELECT rank FROM rank_history WHERE contest_slug=h.contest_slug"
           "    AND username=h.username ORDER BY id DESC LIMIT 1) AS latest_rank"
           " FROM rank_history h")
    args = ()
    if username:
        sql += " WHERE h.username=?"
        args = (username,)
    # Only contests the app scanned. A reading can outlive the reason it was
    # taken, and the tab is about what this tool has been working on.
    sql += (" AND" if username else " WHERE")
    sql += " h.contest_slug IN (SELECT contest_slug FROM scans)"
    sql += " GROUP BY h.contest_slug, h.username ORDER BY last_at DESC"
    out = []
    for r in conn.execute(sql, args):
        d = dict(r)
        d["moved_up"] = d["first_rank"] - d["latest_rank"]
        # Sitting on the best number ever recorded, with something to compare
        # against -- what the UI marks as a record.
        d["at_best"] = (d["latest_rank"] == d["best_rank"]
                        and d["best_rank"] != d["worst_rank"])
        out.append(d)
    return out

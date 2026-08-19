"""SQLite persistence: reports, scans, and lifetime counters."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core import config

SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    db_path = config.path("database")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    return conn


# --- reports -------------------------------------------------------------

def record_report(conn, *, username, contest_slug, question_slug, submission_id,
                  reason_code, score, evidence, narrative, dry_run):
    """Persist the composed report before any submission attempt.

    Returns the report id, or None if this submission+reason was already filed.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO reports "
        "(username, contest_slug, question_slug, submission_id, reason_code,"
        " score, evidence_json, narrative, created_at, dry_run) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (username, contest_slug, question_slug, submission_id, reason_code,
         score, json.dumps(evidence), narrative, _now(), int(dry_run)),
    )
    conn.commit()
    return cur.lastrowid if cur.rowcount else None


def mark_report(conn, report_id, outcome, error=None):
    conn.execute(
        "UPDATE reports SET outcome=?, error=?, submitted_at=? WHERE id=?",
        (outcome, error, _now() if outcome == "submitted" else None, report_id),
    )
    conn.commit()


def already_reported(conn, submission_id):
    return conn.execute(
        "SELECT 1 FROM reports WHERE submission_id=?", (submission_id,)
    ).fetchone() is not None


def reports(conn, limit=200):
    rows = conn.execute(
        "SELECT * FROM reports ORDER BY id DESC LIMIT ?", (limit,)
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
        "FROM reports GROUP BY username "
        "ORDER BY submissions DESC, last_seen DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# --- lifetime counters ------------------------------------------------

# Totals across every scan ever run, not per user and not per contest.
CAUGHT = "cheating_submissions_caught"   # judged CHEAT
REPORTED = "reports_submitted"           # actually sent to LeetCode
SUSPICIOUS = "suspicious_recorded"       # grey zone, never auto-reported
SCANNED = "submissions_scanned"
CONTESTS = "contests_scanned"


def bump(conn, key, n=1):
    """Add to a lifetime counter, creating it on first use."""
    if not n:
        return
    conn.execute(
        "INSERT INTO stats (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = value + excluded.value",
        (key, n),
    )
    conn.commit()


def stats(conn):
    rows = conn.execute("SELECT key, value FROM stats").fetchall()
    out = {r["key"]: r["value"] for r in rows}
    for k in (CAUGHT, REPORTED, SUSPICIOUS, SCANNED, CONTESTS):
        out.setdefault(k, 0)
    return out


# --- scans ---------------------------------------------------------------

def start_scan(conn, contest_slug):
    cur = conn.execute(
        "INSERT INTO scans (contest_slug, started_at) VALUES (?,?)",
        (contest_slug, _now()),
    )
    conn.commit()
    return cur.lastrowid


def finish_scan(conn, scan_id, ranks_scanned, flagged, reported, status="done"):
    conn.execute(
        "UPDATE scans SET finished_at=?, ranks_scanned=?, flagged=?, reported=?,"
        " status=? WHERE id=?",
        (_now(), ranks_scanned, flagged, reported, status, scan_id),
    )
    conn.commit()


def scans(conn, limit=50):
    rows = conn.execute(
        "SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]

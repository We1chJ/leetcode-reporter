"""SQLite persistence: offenders, reports, scans."""

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


# --- offenders -----------------------------------------------------------

def touch_offender(conn, username, contest_slug, counted_report):
    """Upsert the offender row. contest_count counts distinct contests."""
    row = conn.execute(
        "SELECT username FROM offenders WHERE username=?", (username,)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO offenders (username, first_seen, last_seen) VALUES (?,?,?)",
            (username, _now(), _now()),
        )
    conn.execute("UPDATE offenders SET last_seen=? WHERE username=?", (_now(), username))
    if counted_report:
        contests = conn.execute(
            "SELECT COUNT(DISTINCT contest_slug) c FROM reports WHERE username=?",
            (username,),
        ).fetchone()["c"]
        total = conn.execute(
            "SELECT COUNT(*) c FROM reports WHERE username=?", (username,)
        ).fetchone()["c"]
        conn.execute(
            "UPDATE offenders SET report_count=?, contest_count=? WHERE username=?",
            (total, contests, username),
        )
    conn.commit()


def offenders(conn):
    rows = conn.execute(
        "SELECT * FROM offenders ORDER BY report_count DESC, last_seen DESC"
    ).fetchall()
    return [dict(r) for r in rows]


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

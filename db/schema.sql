CREATE TABLE IF NOT EXISTS reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL,
    contest_slug  TEXT NOT NULL,
    question_slug TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    reason_code   TEXT NOT NULL,
    score         REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    narrative     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    submitted_at  TEXT,
    dry_run       INTEGER NOT NULL,
    outcome       TEXT NOT NULL DEFAULT 'pending',
    error         TEXT,
    UNIQUE (submission_id, reason_code)
);

CREATE TABLE IF NOT EXISTS scans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    contest_slug  TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    ranks_scanned INTEGER NOT NULL DEFAULT 0,
    flagged       INTEGER NOT NULL DEFAULT 0,
    reported      INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'running'
);

-- Lifetime counters, never reset. Survives scans, restarts and reinstalls of
-- the app as long as the database file is kept.
CREATE TABLE IF NOT EXISTS stats (
    key   TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_reports_contest ON reports (contest_slug);

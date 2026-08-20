CREATE TABLE IF NOT EXISTS reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL,
    contest_slug  TEXT NOT NULL,
    question_slug TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    -- 'cheat' rows are filed to LeetCode; 'grey' rows are recorded for review
    -- and never submitted. Both live here so the totals can be counted from
    -- one place.
    verdict       TEXT NOT NULL DEFAULT 'cheat',
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
    -- Contestants taken off the leaderboard, and replays actually opened.
    -- A scan that reached neither is not counted as having scanned a contest.
    ranks_scanned INTEGER NOT NULL DEFAULT 0,
    submissions_seen INTEGER NOT NULL DEFAULT 0,
    flagged       INTEGER NOT NULL DEFAULT 0,
    reported      INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'running'
);

<img src="web/logo.svg" width="72" alt="">

# LeetCode Contest Reporter

A local desktop tool that scans the top of a LeetCode contest leaderboard after
the contest ends, identifies submissions that were pasted in rather than written
in the editor, writes the violation report, and files it — with a local SQLite
record of every offender and every report sent.

Single-user, runs on your machine, no hosting. Python core + a local web UI at
`127.0.0.1:8000`.

> **Read this before turning it loose.** "Pasted the whole solution" is not
> identical to "cheated" — some people legitimately write in a local IDE and
> paste in. This tool files reports against real people automatically, so it
> ships with `dry_run = true`, a report cap, a rate limit, and a stop button.
> Run it in dry run across a few past contests and read the reports it *would*
> have sent before you switch it live.

## How detection works

The original plan was to reconstruct keystrokes from LeetCode's Code Replay.
A live spike found that replay events are not retrievable over the API — opening
a replay fires no request carrying them (see [`tools/FINDINGS.md`](tools/FINDINGS.md)).

What it uses instead is better: **LeetCode's own `not_enough_activities` flag**,
exposed on the `region=global_v2` ranking payload. That is LeetCode's editor-
activity check — their paste detector — already computed and handed to us. On
`weekly-contest-515` it was set on 51 of the 400 top-100 submissions.

Signals, in order of weight:

| Reason code | Meaning | Score |
|---|---|---|
| `FLAGGED_AND_IMPLAUSIBLE_SPEED` | LeetCode flagged it **and** it beat the plausible-solve floor for its credit value | 0.97 |
| `CLEAN_SWEEP_IMPLAUSIBLE` | LeetCode flagged it **and** every problem landed within a tight span | 0.96 |
| `LC_INSUFFICIENT_ACTIVITY` | LeetCode flagged it | 0.90 |
| `IMPLAUSIBLE_SOLVE_SPEED` | Accepted dramatically faster than the floor, no LeetCode flag | ≤ 0.90 |

At or above `cheat_threshold` (0.95) a report is filed. Between `grey_low` and
that, Claude adjudicates and can promote it. `require_leetcode_flag = true`
means speed alone never files a report — it can only corroborate LeetCode's flag
or send a case to the model.

A tight clean sweep is deliberately **not** a standalone signal. Calibration
against the real top-11 of weekly-contest-515 had it firing on 39 of 44
submissions: at the top of any leaderboard everybody finishes fast.

## What the AI does

- **Writes the report narrative** — `claude-opus-5` turns the hard-coded reason
  code plus measured evidence into the specific prose LeetCode's form requires.
  Reason codes are constants; the model never invents one, and is instructed to
  ground every sentence in the evidence.
- **Adjudicates the grey zone** — returns a structured `{verdict, confidence,
  rationale}`, defaulting to `not_violation` when ambiguous.

Set `ai.enabled = false` to skip the API entirely and use deterministic
templates.

## Setup

```
run.bat
```

First launch creates a venv, installs dependencies and Chromium, then opens
`http://127.0.0.1:8000`. A Chrome window opens the first time you scan — **log
in to LeetCode by hand once**. The session persists in `data/chrome-profile/`
and is reused. (LeetCode sits behind Cloudflare and rejects unauthenticated
HTTP, which is why this drives a real browser rather than using `requests`.)

For narrative generation, either export `ANTHROPIC_API_KEY` or run
`ant auth login`.

## Use

Enter a contest slug (`weekly-contest-515`) and press **Scan contest**. Tabs
show the live log, the offender table with per-user report counts, full report
history including the exact text sent, and past scans.

Tune thresholds offline against a captured contest, no LeetCode access needed:

```
python -m tools.calibrate tools/fixtures/wc515_top11.json
```

## Configuration

`config.toml`:

- `safety.dry_run` — compose and store reports without sending. **Default true.**
- `safety.max_reports_per_contest`, `safety.min_seconds_between_reports`
- `scope.rank_start` / `rank_end` / `questions` / `request_delay`
- `detect.*` — thresholds above
- `ai.model` / `ai.effort` / `ai.enabled`

## Layout

```
core/      browser, contest scraping, detection, reporting, pipeline
ai/        narrative generation, grey-zone adjudication
db/        SQLite schema and store
web/       dashboard
tools/     discovery spike, API findings, offline calibration
```

## Status

Detection, scoring, storage, the dashboard and dry-run reporting are working and
calibrated against live data. The one piece **not** verified end-to-end is the
actual report submission: the POST shape was deliberately not probed, because
probing it means filing a real report against a real person. Confirm the
selectors in `core/reporter.py` against the live dialog once before going live.

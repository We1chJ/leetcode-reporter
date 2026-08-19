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

It reads **LeetCode's own Code Replay event history** for each submission and
judges it itself.

There is no API for those events — opening a replay fires no request carrying
them (see [`tools/FINDINGS.md`](tools/FINDINGS.md)). But the player has an
"Event History" panel that lists every recorded editor event, and that panel is
scrapable. LeetCode's event vocabulary:

```
start · switchQuestion · switchLang · pageVisible (Page Switch) · interpretCode
submitCode · end · input · undo · redo · paste (External Paste) · changeCursor · debug
```

`Input` is typing in the editor. `External Paste` is LeetCode's own label for
content arriving from outside it. A submission with pastes and no Input events
was not written in the editor. Real example, rank 3's Q4 on weekly-contest-515:

```
Switch Language | 0:01 | Java
External Paste  | 0:06 | size > 500 chars | 🔴
Run Code        | 0:07 | Accepted
Submit Code     | 0:08 | Accepted
```

A commented Java bitmask DP, in four events and eight seconds.

| Reason code | Meaning | Score |
|---|---|---|
| `PASTE_NO_TYPING` | External pastes present, zero Input events | 0.99 |
| `PASTE_DOMINANT` | Solution arrived almost entirely by paste | 0.95 |
| `LARGE_EXTERNAL_PASTE` | A single paste big enough to be the whole solution | 0.93 |
| `PASTE_THEN_IMMEDIATE_SUBMIT` | Submitted seconds after the last paste | 0.90 |
| `IMPLAUSIBLE_SOLVE_SPEED` | Fallback when no replay exists; never auto-reports | ≤ 0.90 |

At or above `cheat_threshold` (0.95) a report is filed. Between `grey_low` and
that, Claude adjudicates and can promote it.

### It does not trust LeetCode's own flag

The ranking payload carries `not_enough_activities`, LeetCode's editor-activity
check. **This tool ignores it for scoring** and records it as context only.

It under-fires badly. On the real example above, the replay is a single external
paste with no typing whatsoever — and `not_enough_activities` was **not** set.
Gating on it would inherit every miss in LeetCode's detector, which is the whole
reason for building this.

Solve speed is likewise only a fallback for submissions with no replay, and
otherwise mild corroboration. A tight clean sweep is not a signal at all: at the
top of any leaderboard everyone finishes fast.

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

Check the detector offline against captured event histories — real cheats plus
controls that must stay clean. No LeetCode access needed:

```
python -m tools.calibrate
```

It exits non-zero if any control case would be reported. Run it before ever
turning `dry_run` off.

## Configuration

`config.toml`:

- `safety.dry_run` — compose and store reports without sending. **Default true.**
- `safety.max_reports_per_contest`, `safety.min_seconds_between_reports`
- `scope.rank_start` / `rank_end` / `questions` / `request_delay`
- `detect.*` — thresholds above, plus `large_paste_chars` and `paste_ratio`
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

Detection, scoring, storage, the dashboard and dry-run reporting work, and the
detector is checked against a real captured event history plus controls.

The Event History **scraper** (`core/replay.py`) is written against the DOM
structure confirmed live, but has not yet run under Playwright end-to-end — the
parser is tested on real scraped rows, the browser driving around it is not. The one piece **not** verified end-to-end is the
actual report submission: the POST shape was deliberately not probed, because
probing it means filing a real report against a real person. Confirm the
selectors in `core/reporter.py` against the live dialog once before going live.

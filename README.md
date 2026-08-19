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

It scrubs the Code Replay timeline and measures **how much code exists at each
point**. Work done in the editor grows the code steadily; a solution brought in
from outside appears in one step. Measured on weekly-contest-515:

```
rank 3   Q4, cheat     100 100 100 100  1  1  1  1  1  1 1474   biggest jump 100%
rank 501, 42 min       110 110 110 110 110 184 256 296 382 484   biggest jump  21%
rank 502, 42 min        89  89  89 110 145 177 242 292 357 418   biggest jump  16%
```

The gap between 21% and 100% is the whole signal, and it is what a person does
when they check a replay by hand.

| Reason code | Meaning | Score |
|---|---|---|
| `CODE_APPEARS_IN_ONE_STEP` | Most of the finished solution appears in a single timeline step | 0.98 |
| `LARGE_PASTE_THEN_SUBMIT` | Large external paste, submitted seconds later | 0.96 |
| `BURST_AFTER_IDLE` | Long silence, then one large external paste | 0.95 |
| `NO_INCREMENTAL_PROGRESS` | Code never grows across the recording | 0.94 |
| `REPEATED_LARGE_PASTES` | More than one large external paste | 0.93 |
| `LARGE_EXTERNAL_PASTE` | A paste big enough to be the whole solution | 0.90 |
| `IMPLAUSIBLE_SOLVE_SPEED` | Fallback when no replay exists; never auto-reports | ≤ 0.90 |

At or above `cheat_threshold` (0.95) a report is filed. Between `grey_low` and
that, the submission is recorded and shown in the UI but never auto-reported.

### Growth overrides everything else

If the code keeps growing across the timeline, the submission is **not reported
at all**, whatever the event list says. Pasting your own template or library and
then writing the solution around it is legitimate and must not be punished. This
suppression caught a false positive in the test suite that the paste rules alone
had reported.

### Why not the event list

The replay also has an Event History panel, and it is read for corroboration,
but it **does not record typing** - honest contestants' entire history is
`Switch Language -> Run Code -> Submit Code`. An earlier version treated "zero
typing events" as decisive, which is true of everybody, and judged 73% of the
top 100 as cheating. The event list can see that a paste happened; only the
growth curve can tell whether the code was then actually written.

### It does not trust LeetCode's own flag

`not_enough_activities` under-fires badly - it was unset on the rank 3 case
above, whose code appears 100% in one step. Recorded as context only.

## Fully deterministic

There is no model anywhere in this tool. No API key, no network calls beyond
LeetCode itself, no `anthropic` dependency. The same event history always
produces the same verdict and the same report text, and every rule is readable
in `core/detector.py`.

Report bodies are hard-coded templates in `core/report_text.py`, one per reason
code, filled with numbers taken straight from the event history. Every sentence
is either fixed text or a measured value, so any claim in a report can be traced
back to what was actually observed.

## Setup

**1. Start the browser and sign in — once.**

```
start_chrome.bat
```

This opens an ordinary Chrome with a debugging port, using a profile in
`data/chrome-profile/` that is separate from your everyday Chrome. Sign in to
LeetCode in that window and leave it open.

Signing in has to happen in a browser that Playwright did not launch. A
Playwright-launched Chrome sets `navigator.webdriver` and carries automation
flags, and LeetCode's sign-in verification refuses it. Attaching to a browser
you started avoids the problem entirely: a real person signs in, in a real
browser, and the tool just reuses that session.

**2. Start the app.**

```
run.bat
```

Creates a venv, installs dependencies, opens `http://127.0.0.1:8000`.

(LeetCode sits behind Cloudflare and rejects unauthenticated HTTP, which is why
this drives a browser at all rather than using `requests`.)

## Use

Enter a contest slug (`weekly-contest-515`) and press **Scan contest**. Tabs show
the live log, the full report history including the exact text sent, and past
scans. Or from a terminal:

```
python -m tools.scan weekly-contest-515
```

### Lifetime counters

The header shows running totals across every scan the app has ever done, kept in
the `stats` table and never reset:

- **cheating submissions caught** — judged as violations
- reports submitted — actually sent to LeetCode (dry runs excluded)
- suspicious, not reported — grey zone
- submissions scanned, contests scanned

### No per-user history

The tool does **not** build a profile of who has cheated before, and does not use
past behaviour to judge a new submission. Every submission is judged only on its
own event history. The `reports` table keeps what was sent, as an audit trail and
to avoid filing the same report twice, but nothing aggregates it per user.

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
- `browser.mode` — `attach` (default) or `launch`; see Setup
- `detect.*` — thresholds above, plus `large_paste_chars`, `paste_ratio` and
  `idle_burst_seconds`

## Layout

```
core/      browser, contest scraping, detection, report text, reporting, pipeline
db/        SQLite schema and store (reports, scans, lifetime counters)
web/       dashboard
tools/     scan runner, discovery spike, API findings, offline calibration
```

## Status

Detection, scoring, storage, the dashboard and dry-run reporting work, and the
detector is checked against a real captured event history plus controls.

Two pieces are **not** verified end-to-end:

1. **The Event History scraper** (`core/replay.py`) is written against the DOM
   structure confirmed live, but has not yet run under Playwright. The parser is
   tested on real scraped rows; the browser driving around it is not.
2. **Report submission.** The POST shape was deliberately not probed, because
   probing it means filing a real report against a real person. Confirm the
   selectors in `core/reporter.py` against the live dialog once before going live.

Both are exercised safely by a dry-run scan, which does everything except send.

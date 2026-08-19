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

**External Paste events are the primary signal, and they are ground truth.**
LeetCode records them itself: they say where code came from rather than
inferring it. Honest contestants in the control sample (ranks 501-505, ~42
minute finishers) had none at all. Any paste is reportable.

| Reason code | Meaning | Score |
|---|---|---|
| `PASTED_IN_PIECES` | Three or more pastes in sequence | 0.98 |
| `CODE_APPEARS_IN_ONE_STEP` | No paste recorded, but the code appears in one timeline step | 0.98 |
| `LARGE_PASTE_THEN_SUBMIT` | Large paste, submitted seconds later | 0.97 |
| `BURST_AFTER_IDLE` / `REPEATED_LARGE_PASTES` / `LARGE_EXTERNAL_PASTE` / `EXTERNAL_PASTE_PRESENT` | Any external paste | 0.96 |
| `NO_INCREMENTAL_PROGRESS` | No paste, and the code never grows | 0.94 |
| `IMPLAUSIBLE_SOLVE_SPEED` | No replay at all; never auto-reports | ≤ 0.90 |

### Why the growth curve is only a fallback

Scrubbing the timeline and measuring how much code exists at each point was
tried as the primary signal. It is not sufficient. Rank 15 produced a textbook
authoring curve:

```
132 132 132 132 132 132 132 132 182 361 370 543     jump 33%, 4 growth steps
```

and their event history is:

```
Switch Language -> Paste -> Paste -> Paste -> Run -> Submit
```

Every "growth step" was a paste. **Pasting in pieces is indistinguishable from
typing by curve shape alone**, which is why `PASTED_IN_PIECES` exists and why
the curve is now consulted only when the history records no paste - where it
still catches code appearing in one step with no paste event. Skipping the
scrub when a paste is already recorded also makes scans substantially faster.

### Known cost

`report_any_paste = true` means pasting your own template or library is
reported too. Deliberate: the control sample had zero pastes, so the trade
looks cheap in practice, but it is a trade. One switch in `config.toml`.

### It does not trust LeetCode's own flag

`not_enough_activities` under-fires - unset on cases whose code appears 100% in
one step. Recorded as context only.

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

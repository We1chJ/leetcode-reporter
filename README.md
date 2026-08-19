<p align="center">
  <img src="web/logo.svg" width="88" alt="">
</p>

<h1 align="center">LeetCode Contest Reporter</h1>

<p align="center">
  Finds contest submissions that were pasted in rather than written,<br>
  writes the violation report, and files it.
</p>

<p align="center">
  <em>Runs locally. Fully deterministic — no model, no API key.</em>
</p>

---

## Quick start

```
start_chrome.bat     # sign in to LeetCode once, leave the window open
run.bat              # opens http://127.0.0.1:8000
```

Enter a contest slug (`weekly-contest-515`), press **Scan contest**.

Ships with `dry_run = true`: reports are composed and stored, nothing is sent.

| command | what it does |
|---|---|
| `python -m tools.audit <slug> 1 25` | judge a rank range, print verdicts, file nothing |
| `python -m tools.scan <slug>` | full pipeline from the terminal |
| `python -m tools.calibrate` | offline suite; non-zero exit on any false positive |

## How it decides

**External Paste events are the signal.** LeetCode records them itself — they
say where code came from rather than inferring it. Honest contestants in the
control sample had none at all. Any paste is reportable.

| reason | score |
|---|---|
| `PASTED_IN_PIECES` — three or more pastes in sequence | 0.98 |
| `CODE_APPEARS_IN_ONE_STEP` — no paste, but code appears in one timeline step | 0.98 |
| `LARGE_PASTE_THEN_SUBMIT` — large paste, submitted seconds later | 0.97 |
| any external paste | 0.96 |
| `NO_INCREMENTAL_PROGRESS` — no paste, code never grows | 0.94 |
| `IMPLAUSIBLE_SOLVE_SPEED` — no replay at all; never auto-reports | ≤ 0.90 |

At or above 0.95 → reported. 0.55–0.95 → recorded and shown, never reported.

<details>
<summary><b>Why the growth curve is only a fallback</b></summary>

Scrubbing the timeline to measure how much code exists at each point was tried
as the primary signal. It fails. Rank 15 produced a textbook authoring curve —

```
132 132 132 132 132 132 132 132 182 361 370 543    jump 33%, 4 growth steps
```

— while their event history reads `Switch Language → Paste → Paste → Paste →
Run → Submit`. Every "growth step" was a paste. Pasting in pieces is
indistinguishable from typing by curve shape alone.

The curve is now consulted only when no paste is recorded, where it still
catches code appearing in one step. Skipping it otherwise also makes scans
much faster.
</details>

<details>
<summary><b>Why not LeetCode's own flag</b></summary>

The ranking payload carries `not_enough_activities`. It under-fires badly — it
was unset on a submission whose entire solution appears in one step. Gating on
it would inherit every miss in LeetCode's detector. Recorded as context only.
</details>

<details>
<summary><b>Measured behaviour</b></summary>

| sample | contestants flagged | submissions flagged |
|---|---|---|
| ranks 1–25 | 23/25 | 89/89 |
| ranks 201–215 | 5/15 | 9/51 |

Mid-table offenders are mostly one problem of four — someone solving three
honestly and pasting the hardest.
</details>

## Setup notes

Sign-in must happen in a browser Playwright did **not** launch: a launched
Chrome sets `navigator.webdriver` and LeetCode's verification refuses it.
`start_chrome.bat` opens an ordinary Chrome with a debugging port, using a
profile in `data/chrome-profile/` kept separate from your everyday browser.

LeetCode sits behind Cloudflare and rejects unauthenticated HTTP, which is why
this drives a browser rather than using `requests`.

Replays belonging to LeetCode China accounts offer to redirect to leetcode.cn.
The offer is declined and the submission skipped, rather than followed.

## Configuration

`config.toml`:

- `safety.dry_run` — compose and store without sending. **Default true.**
- `safety.max_reports_per_contest`, `min_seconds_between_reports`
- `scope.rank_start` / `rank_end` / `questions`
- `detect.report_any_paste` — **on**; this also reports pasting your own template
- `detect.burst_fraction`, `authored_fraction`, `pieces_paste_count`
- `browser.mode` — `attach` (default) or `launch`

## Counters

The header shows lifetime totals, never reset: cheating submissions caught,
reports submitted, suspicious recorded, submissions and contests scanned.

No per-user history is kept or used. Every submission is judged only on its own
replay; past behaviour never influences a verdict. The `reports` table is an
audit trail of what was sent and a guard against filing twice.

## Layout

```
core/    browser, contest scraping, detection, report text, pipeline
db/      SQLite schema and store
web/     dashboard
tools/   audit, scan, login, calibrate, discovery spike, API findings
```

## Status

Working and verified: leaderboard and replay scraping, detection, hard-coded
reports, storage, dashboard, dry-run.

**Not verified: actual report submission.** The POST shape was deliberately not
probed, because probing it files a real report against a real person. Confirm
the selectors in `core/reporter.py` against the live dialog once before going
live.

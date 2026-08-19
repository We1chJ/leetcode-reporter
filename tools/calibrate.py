"""Run the detector over captured Code Replay event histories and check verdicts.

Offline: no LeetCode access needed. Run this after touching thresholds or
scoring rules, and before ever turning dry_run off.

    python -m tools.calibrate

A false positive here means the tool would file a report against someone who did
nothing wrong, so any control case landing on `cheat` is a hard failure.
"""

import json
import sys
from pathlib import Path

from core import config, detector
from core.replay import parse_rows

DEFAULT = "tools/fixtures/events_wc515.json"


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
    fx = json.loads(path.read_text(encoding="utf-8"))
    d = config.load()["detect"]
    print(f"cheat>={d['cheat_threshold']}  grey>={d['grey_low']}  "
          f"large_paste>={d['large_paste_chars']} chars\n")

    failures = []
    for c in fx["cases"]:
        events = parse_rows(c["rows"])
        sub = {"date": c["seconds_after_start"], "lang": None,
               "fail_count": 0, "not_enough_activities": c["leetcode_flag"]}
        ctx = {"start_time": 0, "credit": c["credit"],
               "question_slug": c["question"]}
        verdict, score, reason, ev = detector.analyse(events, sub, ctx)

        expect = c["expect"]
        # grey never auto-reports, so treating a clean control as grey is a
        # softer miss than reporting it -- but a reported control is fatal.
        ok = verdict == expect or (expect == "clean" and verdict == "grey")
        fatal = expect == "clean" and verdict == "cheat"
        mark = "ok  " if ok else ("FAIL" if fatal else "warn")
        if not ok:
            failures.append((c["label"], verdict, expect, fatal))

        print(f"  [{mark}] {verdict:<5} {score:<5} {reason or '-'}")
        print(f"         {c['label']}")
        print(f"         pastes={ev.get('paste_events')} "
              f"largest={ev.get('largest_paste_chars')}ch "
              f"idle_before={ev.get('idle_before_largest_paste')}s "
              f"paste->submit={ev.get('paste_to_submit_seconds')}s "
              f"runs_after={ev.get('runs_after_last_paste')}")

    fatal = [f for f in failures if f[3]]
    print()
    if fatal:
        print(f"  {len(fatal)} FALSE POSITIVE(S) - do not disable dry_run")
        return 1
    if failures:
        print(f"  {len(failures)} soft mismatch(es), no false positives")
    else:
        print("  all cases as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())

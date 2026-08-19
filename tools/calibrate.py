"""Run the detector over a captured contest fixture and print the verdicts.

Offline: no LeetCode access needed. Use this to sanity-check thresholds before
turning dry_run off.

    python -m tools.calibrate tools/fixtures/wc515_top11.json
"""

import json
import sys
from collections import Counter
from pathlib import Path

from core import config, detector

START = None


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1
                else "tools/fixtures/wc515_top11.json")
    fx = json.loads(path.read_text())
    slug_of = {q["question_id"]: q["title_slug"] for q in fx["questions"]}
    start = fx["start_time"]
    d = config.load()["detect"]

    print(f"{fx['slug']}  cheat>={d['cheat_threshold']}  grey>={d['grey_low']}  "
          f"require_leetcode_flag={d['require_leetcode_flag']}\n")

    tally = Counter()
    for rank, user, subs in fx["rows"]:
        offsets = [s[1] for s in subs]
        sweep = max(offsets) - min(offsets) if len(subs) > 1 else None
        lines = []
        for qid, offset, credit, flag, fails in subs:
            sub = {"date": start + offset, "not_enough_activities": bool(flag),
                   "fail_count": fails, "lang": "python3", "has_replay": True}
            ctx = {"start_time": start, "credit": credit,
                   "question_slug": slug_of[qid], "sweep_span": sweep}
            verdict, score, reason, _ = detector.analyse(sub, ctx)

            # Mirror the pipeline's guard: speed alone never auto-reports.
            if d["require_leetcode_flag"] and not flag and verdict == detector.CHEAT:
                verdict = detector.GREY

            tally[verdict] += 1
            if verdict != detector.CLEAN:
                lines.append(f"      Q{credit}p {offset:>4}s "
                             f"{'LC-FLAG' if flag else '       '} "
                             f"{verdict:<5} {score:<5} {reason}")
        if lines:
            print(f"  #{rank:<3} {user}  (sweep {sweep}s)")
            print("\n".join(lines))

    print(f"\n  {dict(tally)}")
    print("  cheat -> auto-reported; grey -> sent to Claude to adjudicate")


if __name__ == "__main__":
    main()

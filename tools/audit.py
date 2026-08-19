"""Read-only audit: judge a rank range and print the verdicts.

Files nothing, writes nothing to the database, and ignores the report cap. Use
it to see what the current rules say about a leaderboard before letting the
pipeline act on it.

    python -m tools.audit weekly-contest-515 1 25
"""

import sys

from core import config, contest, detector, replay
from core.browser import Session

MARK = {detector.CHEAT: "X", detector.GREY: "?", detector.CLEAN: "."}


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "weekly-contest-515"
    lo = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    hi = int(sys.argv[3]) if len(sys.argv) > 3 else 25
    cfg = config.load(reload=True)
    samples = cfg["detect"]["progression_samples"]

    with Session() as s:
        s.require_login()
        meta = contest.info(s, slug)
        qs = contest.questions(s, slug)
        print(f"{meta['title'] or slug}: ranks {lo}-{hi}, {len(qs)} problems")
        print(f"X = would report   ? = suspicious, not reported   . = clean   "
              f"- = no replay/unreadable\n")
        print(f"{'#':>4}  {'user':<24} {'Q1 Q2 Q3 Q4':<12}  detail")

        flagged = []
        for row in contest.leaderboard(s, slug, lo, hi,
                                       delay=cfg["scope"]["request_delay"]):
            marks, notes = [], []
            for i, q in enumerate(qs):
                sub = row["submissions"].get(str(q["question_id"]))
                if not sub or not sub.get("has_replay"):
                    marks.append("-")
                    continue
                try:
                    got = replay.inspect(
                        s, slug, row["username"], i, problem_count=len(qs),
                        ui_page=(row["rank"] - 1) // 25 + 1, samples=samples,
                        rank=row["rank"],
                        finish_offset=(row["finish_time"] - meta["start_time"])
                        if row.get("finish_time") else None)
                except Exception:
                    got = None
                if not got:
                    marks.append("-")
                    continue
                v, sc, reason, ev = detector.analyse(
                    got["events"], sub,
                    {"start_time": meta["start_time"], "credit": q["credit"],
                     "question_slug": q["title_slug"],
                     "progression": got["progression"]})
                marks.append(MARK[v])
                if v == detector.CHEAT:
                    notes.append(f"Q{i + 1} {reason} {sc} "
                                 f"jump={ev.get('biggest_jump_fraction')} "
                                 f"steps={ev.get('growth_steps')}")
            line = " ".join(f"{m} " for m in marks)
            print(f"{row['rank']:>4}  {row['username'][:24]:<24} {line:<12}  "
                  f"{'; '.join(notes)}", flush=True)
            if "X" in marks:
                flagged.append((row["rank"], row["username"], marks.count("X")))

        print(f"\n{len(flagged)} contestant(s) with at least one reportable "
              f"submission:")
        for rank, user, n in flagged:
            print(f"   #{rank:<4} {user}  ({n} submission(s))")


if __name__ == "__main__":
    main()

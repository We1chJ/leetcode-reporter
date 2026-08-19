"""Deterministic scoring of a contest submission.

Reason codes are hard-coded constants. The model never invents a reason; it only
writes prose around whatever this module decides, and adjudicates the grey zone.

The primary signal is LeetCode's own `not_enough_activities` flag, exposed on the
region=global_v2 ranking payload -- their editor-activity detector, already
computed. Per-keystroke replay events are not retrievable over the API (see
tools/FINDINGS.md), so speed corroborates the flag rather than replacing it.
"""

from core import config

# --- reason codes ---------------------------------------------------------
LC_INSUFFICIENT_ACTIVITY = "LC_INSUFFICIENT_ACTIVITY"
FLAGGED_AND_IMPLAUSIBLE_SPEED = "FLAGGED_AND_IMPLAUSIBLE_SPEED"
IMPLAUSIBLE_SOLVE_SPEED = "IMPLAUSIBLE_SOLVE_SPEED"
CLEAN_SWEEP_IMPLAUSIBLE = "CLEAN_SWEEP_IMPLAUSIBLE"

REASON_TEXT = {
    LC_INSUFFICIENT_ACTIVITY:
        "LeetCode's own editor-activity check flagged this submission as having "
        "insufficient editor activity, meaning the code was not typed out in the "
        "contest editor",
    FLAGGED_AND_IMPLAUSIBLE_SPEED:
        "LeetCode's editor-activity check flagged this submission as having "
        "insufficient editor activity, and it was accepted far sooner after the "
        "contest opened than the problem's difficulty allows",
    IMPLAUSIBLE_SOLVE_SPEED:
        "the submission was accepted far sooner after the contest opened than "
        "reading, implementing and testing the problem plausibly permits",
    CLEAN_SWEEP_IMPLAUSIBLE:
        "LeetCode's editor-activity check flagged this submission as having "
        "insufficient editor activity, and every problem in the contest, including "
        "the hardest, was accepted within a span far shorter than the problems can "
        "plausibly be read and implemented in",
}

CLEAN, GREY, CHEAT = "clean", "grey", "cheat"

# Fastest plausible accepted solve, in seconds from contest start, by credit.
# Deliberately generous -- these are floors that strong contestants stay above.
SPEED_FLOOR = {3: 45, 4: 90, 5: 180, 6: 300}


def _speed_evidence(sub, ctx):
    start = ctx.get("start_time")
    if not start or not sub.get("date"):
        return None, None
    offset = sub["date"] - start
    floor = SPEED_FLOOR.get(ctx.get("credit"), 180)
    return offset, floor


def analyse(sub, ctx):
    """Score one submission.

    `sub` is a merged record from core.contest (needs not_enough_activities,
    date, lang, fail_count). `ctx` carries start_time, credit, question_slug and
    optionally sweep_span (seconds between the contestant's first and last
    accepted submission in this contest).

    Returns (verdict, score, reason_code, evidence).
    """
    d = config.load()["detect"]
    flagged = bool(sub.get("not_enough_activities"))
    offset, floor = _speed_evidence(sub, ctx)

    evidence = {
        "leetcode_insufficient_activity": flagged,
        "language": sub.get("lang"),
        "fail_count": sub.get("fail_count"),
        "problem_credit": ctx.get("credit"),
        "has_replay": sub.get("has_replay"),
    }
    if offset is not None:
        evidence["seconds_after_contest_start"] = offset
        evidence["plausible_floor_seconds"] = floor
    if ctx.get("sweep_span") is not None:
        evidence["all_problems_solved_within_seconds"] = ctx["sweep_span"]

    too_fast = offset is not None and offset < floor
    sweep = ctx.get("sweep_span")
    tight_sweep = sweep is not None and sweep < d["sweep_span_seconds"]
    evidence["tight_sweep"] = tight_sweep

    # A tight sweep is NOT evidence on its own: at the top of any leaderboard
    # everyone finishes every problem within a few minutes. Calibration against
    # weekly-contest-515 had it firing on 39 of 44 top-11 submissions. It only
    # ever corroborates a submission that LeetCode itself flagged, and it never
    # produces a reason code of its own -- otherwise one per-contestant finding
    # would be duplicated into a report against each of their four submissions.
    reasons = []

    if flagged and too_fast:
        reasons.append((FLAGGED_AND_IMPLAUSIBLE_SPEED, 0.97))
    elif flagged and tight_sweep:
        reasons.append((CLEAN_SWEEP_IMPLAUSIBLE, 0.96))
    elif flagged:
        reasons.append((LC_INSUFFICIENT_ACTIVITY, 0.90))

    if too_fast and not flagged:
        # Speed alone: only worth a look when it is dramatically below the floor.
        margin = 1.0 - (offset / floor)
        if margin >= 0.4:
            reasons.append((IMPLAUSIBLE_SOLVE_SPEED, min(0.55 + margin * 0.4, 0.90)))

    if not reasons:
        return CLEAN, 0.0, None, evidence

    reason_code, score = max(reasons, key=lambda r: r[1])
    evidence["all_reasons"] = sorted({r[0] for r in reasons})

    if score >= d["cheat_threshold"]:
        verdict = CHEAT
    elif score >= d["grey_low"]:
        verdict = GREY
    else:
        verdict = CLEAN
    return verdict, round(score, 3), reason_code, evidence

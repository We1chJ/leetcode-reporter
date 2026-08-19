"""Deterministic judgment on a contest submission, from its Code Replay.

No model is involved anywhere in this module. Same input, same verdict.

**External Paste events are the primary signal, and they are ground truth.**
LeetCode records them itself; they say where the code came from rather than
inferring it. Honest contestants in the control sample (ranks 501-505, ~42
minute finishers) had none at all.

The growth curve -- how much code exists at each point of the timeline -- was
tried as the primary signal and is not sufficient on its own. vinaypinagadi,
rank 15, produced a textbook authoring curve (132 -> 182 -> 361 -> 370 -> 543,
biggest jump 33%) while their event history is:

    Switch Language -> Paste -> Paste -> Paste -> Run -> Submit

Every one of those "growth steps" was a paste. Pasting in pieces is
indistinguishable from typing by curve shape alone, so the curve is now only
consulted when the history records no paste at all -- where it still catches
code that appears in one step without a recorded paste.

Typing itself is never recorded, so nothing here may claim its absence.

LeetCode's own `not_enough_activities` flag under-fires and is context only.
"""

from core import config
from core.replay import PAGE_SWITCH, PASTE, RUN, SUBMIT

# --- reason codes ---------------------------------------------------------
EXTERNAL_PASTE_PRESENT = "EXTERNAL_PASTE_PRESENT"
PASTED_IN_PIECES = "PASTED_IN_PIECES"
CODE_APPEARS_IN_ONE_STEP = "CODE_APPEARS_IN_ONE_STEP"
NO_INCREMENTAL_PROGRESS = "NO_INCREMENTAL_PROGRESS"
LARGE_PASTE_THEN_SUBMIT = "LARGE_PASTE_THEN_SUBMIT"
BURST_AFTER_IDLE = "BURST_AFTER_IDLE"
LARGE_EXTERNAL_PASTE = "LARGE_EXTERNAL_PASTE"
REPEATED_LARGE_PASTES = "REPEATED_LARGE_PASTES"
IMPLAUSIBLE_SOLVE_SPEED = "IMPLAUSIBLE_SOLVE_SPEED"

# Phrased strictly in terms of what the event history records. None of these may
# assert anything about typing, which the history does not capture.
REASON_TEXT = {
    EXTERNAL_PASTE_PRESENT:
        "the Code Replay records an external paste - code brought into the "
        "editor from outside it rather than written in place",
    PASTED_IN_PIECES:
        "the Code Replay records the solution arriving as a series of external "
        "pastes, one after another, with no code written in the editor between "
        "them",
    CODE_APPEARS_IN_ONE_STEP:
        "stepping through the Code Replay shows the editor essentially empty "
        "and then, in a single step of the timeline, holding the complete "
        "solution -- the code never grew, it arrived all at once",
    NO_INCREMENTAL_PROGRESS:
        "stepping through the Code Replay shows no gradual growth of the "
        "solution across the recording; the code is static and then complete",
    LARGE_PASTE_THEN_SUBMIT:
        "a large block of code arrived in a single external paste and was "
        "submitted within seconds, leaving no time to read, adapt or test it",
    BURST_AFTER_IDLE:
        "a long stretch with no recorded editor activity was followed "
        "immediately by one large external paste",
    REPEATED_LARGE_PASTES:
        "the solution arrived through more than one large external paste",
    LARGE_EXTERNAL_PASTE:
        "a single external paste large enough to account for the whole "
        "solution was recorded",
    IMPLAUSIBLE_SOLVE_SPEED:
        "the submission was accepted far sooner after the contest opened than "
        "reading, implementing and testing the problem plausibly permits",
}

CLEAN, GREY, CHEAT = "clean", "grey", "cheat"

# Fastest plausible accepted solve, in seconds from contest start, by credit.
# Deliberately generous -- floors that strong contestants stay above.
SPEED_FLOOR = {3: 45, 4: 90, 5: 180, 6: 300}


def summarise_progression(prog):
    """Describe how the code grew across the timeline.

    `prog` is the character count of the code at evenly spaced points through
    the replay. Work done in the editor climbs steadily; a solution brought in
    from outside jumps from nothing to complete in one step.
    """
    peak = max(prog) if prog else 0
    final = prog[-1] if prog else 0
    steps = [prog[i + 1] - prog[i] for i in range(len(prog) - 1)]
    growth = [d for d in steps if d > 0]
    biggest = max(steps) if steps else 0
    # Growth apart from the single largest jump. Counting bare increments was
    # not enough: goel0277's Q4 grew at five points totalling 43 characters and
    # then gained 939 in one step, which the step count alone called authoring.
    other_growth = sum(growth) - biggest if growth else 0
    return {
        "samples": len(prog),
        # Peak and end differ when code is pasted and then trimmed back down,
        # so report both rather than calling the peak "the final solution".
        "peak_chars": peak,
        "final_chars": final,
        "trimmed_chars": max(peak - final, 0),
        "biggest_single_jump_chars": biggest,
        # The headline number: how much of the finished solution appeared in
        # one step of the timeline. Near 1.0 means it was never written here.
        "biggest_jump_fraction": round(biggest / peak, 3) if peak else 0.0,
        "growth_steps": len(growth),
        "growth_excluding_jump_chars": max(other_growth, 0),
        "growth_excluding_jump_fraction":
            round(max(other_growth, 0) / peak, 3) if peak else 0.0,
        "curve": prog,
    }


def summarise(events):
    """Reduce an event history to the numbers the rules need."""
    pastes = [e for e in events if e["type"] == PASTE]
    submits = [e for e in events if e["type"] == SUBMIT]

    # Idle gap immediately before each paste. For the first event, the gap is
    # measured from the start of the recording.
    gaps = {}
    for i, e in enumerate(events):
        prev_t = events[i - 1]["t"] if i else 0
        gaps[i] = max(e["t"] - prev_t, 0)

    largest = max(pastes, key=lambda e: e["chars"] or 0, default=None)
    idle_before_largest = None
    if largest is not None:
        idle_before_largest = gaps[events.index(largest)]

    all_gaps = [gaps[i] for i in range(len(events))]
    return {
        "event_count": len(events),
        "paste_events": len(pastes),
        "pasted_chars": sum(e["chars"] or 0 for e in pastes),
        "largest_paste_chars": (largest["chars"] or 0) if largest else 0,
        "paste_size_is_lower_bound": any(e["chars_is_lower_bound"] for e in pastes),
        "idle_before_largest_paste": idle_before_largest,
        "longest_idle_seconds": max(all_gaps, default=0),
        "runs_after_last_paste": sum(
            1 for e in events
            if e["type"] == RUN and largest is not None and e["t"] > largest["t"]),
        "page_switches": sum(1 for e in events if e["type"] == PAGE_SWITCH),
        "last_paste_t": max((e["t"] for e in pastes), default=None),
        "submit_t": max((e["t"] for e in submits), default=None),
        "session_seconds": max((e["t"] for e in events), default=0),
        "event_sequence": [e["type"] for e in events][:40],
        # Stated explicitly so nothing downstream can imply typing was observed.
        "typing_is_not_recorded": True,
    }


def analyse(events, sub, ctx):
    """Score one submission. Returns (verdict, score, reason_code, evidence).

    `events` is the parsed Code Replay history, or None when unavailable.
    """
    d = config.load()["detect"]

    evidence = {
        "problem_credit": ctx.get("credit"),
        "language": sub.get("lang"),
        "fail_count": sub.get("fail_count"),
        # Recorded for context only -- never gates a decision.
        "leetcode_insufficient_activity": bool(sub.get("not_enough_activities")),
    }

    start = ctx.get("start_time")
    offset = (sub["date"] - start) if start and sub.get("date") else None
    floor = SPEED_FLOOR.get(ctx.get("credit"), 180)
    if offset is not None:
        evidence["seconds_after_contest_start"] = offset
        evidence["plausible_floor_seconds"] = floor

    reasons = []

    # The growth curve decides whether the code was written here, and that
    # governs the burst rules below. It does NOT excuse an external paste:
    # under report_any_paste, a paste is reportable even when the code
    # otherwise grew normally.
    authored = False
    prog = ctx.get("progression")
    if prog:
        g = summarise_progression(prog)
        evidence.update(g)
        # Authoring means the code grew substantially by means other than the
        # one big jump -- not merely that it changed at several points.
        authored = (g["growth_steps"] > d["min_growth_steps"] and
                    g["growth_excluding_jump_fraction"] >= d["authored_fraction"])
        evidence["shows_ongoing_authoring"] = authored

    if events is not None:
        s = summarise(events)
        evidence.update(s)

        if s["paste_events"]:
            # Ground truth: this code came from outside the editor. Which rule
            # names it only changes the wording of the report, not the verdict.
            if s["paste_events"] >= d["pieces_paste_count"]:
                # Arriving in many pieces mimics typing on the growth curve,
                # which is exactly how rank 15 read as authored.
                reasons.append((PASTED_IN_PIECES, 0.98))
            big = s["largest_paste_chars"] >= d["large_paste_chars"]
            gap = None
            if s["last_paste_t"] is not None and s["submit_t"] is not None:
                gap = s["submit_t"] - s["last_paste_t"]
                evidence["paste_to_submit_seconds"] = gap
            if big and gap is not None and 0 <= gap <= d["instant_submit_seconds"]:
                reasons.append((LARGE_PASTE_THEN_SUBMIT, 0.97))
            if big and (s["idle_before_largest_paste"] or 0) >= d["idle_burst_seconds"]:
                reasons.append((BURST_AFTER_IDLE, 0.96))
            if s["paste_events"] >= 2:
                reasons.append((REPEATED_LARGE_PASTES, 0.96))
            if big:
                reasons.append((LARGE_EXTERNAL_PASTE, 0.96))
            if d["report_any_paste"]:
                reasons.append((EXTERNAL_PASTE_PRESENT, 0.96))
        elif prog:
            # No paste recorded. The curve is the remaining check: code that
            # appears all at once was not written here either.
            g = summarise_progression(prog)
            if g["peak_chars"] >= d["min_solution_chars"] and not authored:
                if g["biggest_jump_fraction"] >= d["burst_fraction"]:
                    reasons.append((CODE_APPEARS_IN_ONE_STEP, 0.98))
                else:
                    reasons.append((NO_INCREMENTAL_PROGRESS, 0.94))
    else:
        evidence["replay_available"] = False

    # Speed is a fallback for submissions with no replay, and otherwise only
    # mild corroboration. It is never the sole basis for an automatic report.
    if offset is not None and offset < floor:
        margin = 1.0 - (offset / floor)
        if not events:
            reasons.append((IMPLAUSIBLE_SOLVE_SPEED, min(0.55 + margin * 0.4, 0.90)))
        elif reasons:
            reasons = [(r, min(sc + 0.02, 1.0)) for r, sc in reasons]

    if not reasons:
        return CLEAN, 0.0, None, evidence

    reason_code, score = max(reasons, key=lambda r: r[1])
    evidence["all_reasons"] = sorted({r[0] for r in reasons})

    if score >= d["cheat_threshold"]:
        verdict = CHEAT
    elif score >= d["grey_low"]:
        # Recorded and shown in the UI, never auto-reported.
        verdict = GREY
    else:
        verdict = CLEAN
    return verdict, round(score, 3), reason_code, evidence

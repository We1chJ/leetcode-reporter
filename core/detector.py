"""Deterministic judgment on a contest submission, from its Code Replay events.

No model is involved anywhere in this module. Same events in, same verdict out.

This deliberately does NOT defer to LeetCode's `not_enough_activities` flag.
That flag under-fires: on weekly-contest-515 it was unset on rank 3's Q4, whose
own event history is `Switch Language -> External Paste (>500 chars) -> Run Code
-> Submit Code` with zero Input events. It is recorded as context, nothing more.

The judgment is made on the event history itself:
  - Input events are characters typed in the editor.
  - External Paste is LeetCode's own label for content arriving from outside it.
  - Event timestamps give the idle gaps between activity.

Writing a solution in the editor produces continuous incremental typing. The
cheating pattern is the opposite shape: long inactivity, then a sudden burst of
pasted text, then submit.
"""

from core import config
from core.replay import INPUT, PAGE_SWITCH, PASTE, SUBMIT

# --- reason codes ---------------------------------------------------------
PASTE_NO_TYPING = "PASTE_NO_TYPING"
PASTE_DOMINANT = "PASTE_DOMINANT"
BURST_AFTER_IDLE = "BURST_AFTER_IDLE"
LARGE_EXTERNAL_PASTE = "LARGE_EXTERNAL_PASTE"
PASTE_THEN_IMMEDIATE_SUBMIT = "PASTE_THEN_IMMEDIATE_SUBMIT"
IMPLAUSIBLE_SOLVE_SPEED = "IMPLAUSIBLE_SOLVE_SPEED"

CLEAN, GREY, CHEAT = "clean", "grey", "cheat"

# Fastest plausible accepted solve, in seconds from contest start, by credit.
# Deliberately generous -- floors that strong contestants stay above.
SPEED_FLOOR = {3: 45, 4: 90, 5: 180, 6: 300}


def summarise(events):
    """Reduce an event history to the numbers the rules need."""
    inputs = [e for e in events if e["type"] == INPUT]
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
        "input_events": len(inputs),
        "paste_events": len(pastes),
        "typed_chars": sum(e["chars"] or 0 for e in inputs),
        "pasted_chars": sum(e["chars"] or 0 for e in pastes),
        "largest_paste_chars": (largest["chars"] or 0) if largest else 0,
        "paste_size_is_lower_bound": any(e["chars_is_lower_bound"] for e in pastes),
        "idle_before_largest_paste": idle_before_largest,
        "longest_idle_seconds": max(all_gaps, default=0),
        "page_switches": sum(1 for e in events if e["type"] == PAGE_SWITCH),
        "last_paste_t": max((e["t"] for e in pastes), default=None),
        "submit_t": max((e["t"] for e in submits), default=None),
        "session_seconds": max((e["t"] for e in events), default=0),
        "event_sequence": [e["type"] for e in events][:40],
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

    if events:
        s = summarise(events)
        evidence.update(s)
        big = s["largest_paste_chars"] >= d["large_paste_chars"]

        if s["paste_events"]:
            # Pasted in, nothing typed. The decisive pattern.
            if s["input_events"] == 0:
                reasons.append((PASTE_NO_TYPING, 1.0))
            elif s["pasted_chars"] and s["typed_chars"] <= s["pasted_chars"] * (
                    1 - d["paste_ratio"]):
                reasons.append((PASTE_DOMINANT, 0.97))

            # Inactivity, then a sudden burst of pasted code.
            if big and (s["idle_before_largest_paste"] or 0) >= d["idle_burst_seconds"]:
                reasons.append((BURST_AFTER_IDLE, 0.96))

            if big:
                reasons.append((LARGE_EXTERNAL_PASTE, 0.93))

            if s["last_paste_t"] is not None and s["submit_t"] is not None:
                gap = s["submit_t"] - s["last_paste_t"]
                evidence["paste_to_submit_seconds"] = gap
                if 0 <= gap <= d["instant_submit_seconds"]:
                    reasons.append((PASTE_THEN_IMMEDIATE_SUBMIT, 0.90))
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

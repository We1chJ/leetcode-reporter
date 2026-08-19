"""Our own judgment on a contest submission, from its Code Replay events.

Reason codes are hard-coded constants. The model never invents one; it only
writes prose around what this module decides, and adjudicates the grey zone.

This deliberately does NOT defer to LeetCode's `not_enough_activities` flag.
That flag under-fires badly: on weekly-contest-515 it was unset on rank 3's Q4,
whose own event history is `Switch Language -> External Paste (>500 chars) ->
Run Code -> Submit Code` with zero Input events. Gating on it would inherit
every miss in LeetCode's detector. It is recorded as context and nothing more.

The judgment is made on the event history itself:
  - Input events are characters typed in the editor.
  - External Paste is LeetCode's own label for content arriving from outside it.
A submission with pastes and no typing was not written in the editor.
"""

from core import config
from core.replay import INPUT, PAGE_SWITCH, PASTE, SUBMIT

# --- reason codes ---------------------------------------------------------
PASTE_NO_TYPING = "PASTE_NO_TYPING"
PASTE_DOMINANT = "PASTE_DOMINANT"
LARGE_EXTERNAL_PASTE = "LARGE_EXTERNAL_PASTE"
PASTE_THEN_IMMEDIATE_SUBMIT = "PASTE_THEN_IMMEDIATE_SUBMIT"
IMPLAUSIBLE_SOLVE_SPEED = "IMPLAUSIBLE_SOLVE_SPEED"

REASON_TEXT = {
    PASTE_NO_TYPING:
        "the Code Replay event history for this submission contains external "
        "paste events and no typing events at all, so the accepted solution was "
        "never written in the contest editor",
    PASTE_DOMINANT:
        "the Code Replay event history shows the accepted solution arrived almost "
        "entirely through external paste events, with only incidental typing",
    LARGE_EXTERNAL_PASTE:
        "the Code Replay event history contains a single external paste large "
        "enough to account for the whole solution",
    PASTE_THEN_IMMEDIATE_SUBMIT:
        "the Code Replay event history shows the submission followed an external "
        "paste almost immediately, leaving no time to read, adapt or test the code",
    IMPLAUSIBLE_SOLVE_SPEED:
        "the submission was accepted far sooner after the contest opened than "
        "reading, implementing and testing the problem plausibly permits",
}

CLEAN, GREY, CHEAT = "clean", "grey", "cheat"

# Fastest plausible accepted solve, in seconds from contest start, by credit.
# Deliberately generous -- floors that strong contestants stay above.
SPEED_FLOOR = {3: 45, 4: 90, 5: 180, 6: 300}


def summarise(events):
    """Reduce an event history to the numbers the scoring rules need."""
    inputs = [e for e in events if e["type"] == INPUT]
    pastes = [e for e in events if e["type"] == PASTE]
    submits = [e for e in events if e["type"] == SUBMIT]

    typed = sum(e["chars"] or 0 for e in inputs)
    pasted = sum(e["chars"] or 0 for e in pastes)
    return {
        "event_count": len(events),
        "input_events": len(inputs),
        "paste_events": len(pastes),
        "typed_chars": typed,
        "pasted_chars": pasted,
        "largest_paste_chars": max((e["chars"] or 0 for e in pastes), default=0),
        "paste_size_is_lower_bound": any(e["chars_is_lower_bound"] for e in pastes),
        "page_switches": sum(1 for e in events if e["type"] == PAGE_SWITCH),
        "last_paste_t": max((e["t"] for e in pastes), default=None),
        "submit_t": max((e["t"] for e in submits), default=None),
        "session_seconds": max((e["t"] for e in events), default=0),
        "event_sequence": [e["type"] for e in events][:40],
    }


def analyse(events, sub, ctx):
    """Score one submission.

    `events` is the parsed Code Replay history, or None when unavailable.
    `sub` is the merged ranking record; `ctx` carries start_time, credit and
    question_slug.

    Returns (verdict, score, reason_code, evidence).
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

        if s["paste_events"]:
            # The decisive pattern: pasted in, nothing typed.
            if s["input_events"] == 0:
                reasons.append((PASTE_NO_TYPING, 0.99))
            elif s["pasted_chars"] and s["typed_chars"] <= s["pasted_chars"] * (
                    1 - d["paste_ratio"]):
                reasons.append((PASTE_DOMINANT, 0.95))

            if s["largest_paste_chars"] >= d["large_paste_chars"]:
                reasons.append((LARGE_EXTERNAL_PASTE, 0.93))

            if s["last_paste_t"] is not None and s["submit_t"] is not None:
                gap = s["submit_t"] - s["last_paste_t"]
                evidence["paste_to_submit_seconds"] = gap
                if 0 <= gap <= d["instant_submit_seconds"]:
                    reasons.append((PASTE_THEN_IMMEDIATE_SUBMIT, 0.90))
    else:
        evidence["replay_available"] = False

    # Speed is a fallback for submissions with no replay, and otherwise just
    # corroboration -- it is never the sole basis for a report.
    if offset is not None and offset < floor:
        margin = 1.0 - (offset / floor)
        score = min(0.55 + margin * 0.4, 0.90)
        if not events:
            reasons.append((IMPLAUSIBLE_SOLVE_SPEED, score))
        elif reasons:
            reasons = [(r, min(s + 0.02, 0.99)) for r, s in reasons]

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

"""Hard-coded report bodies. No model involved.

One template per reason code, filled from the measured evidence. Every sentence
is either fixed text or a number taken straight from the Code Replay event
history, so a report can always be traced back to what was actually observed.

Nothing here may claim the contestant did not type. LeetCode's Event History
records only notable events -- language switches, runs, submissions, external
pastes -- and never individual keystrokes, so the absence of typing events is
true of every submission and says nothing. Reports assert only the presence and
timing of what the history does record.
"""

from core import config
from core import detector as D

_OPEN = ("Reporting user {user} for their submission to \"{question}\" in "
         "{contest}.")
_CLOSE = ("The full event history is visible in the Code Replay for this "
          "submission. Please review it.")


def _size(e):
    n = e.get("largest_paste_chars", 0)
    return f"at least {n} characters" if e.get("paste_size_is_lower_bound") \
        else f"{n} characters"


def _idle(e):
    """Only claim an idle gap when it is long enough to actually mean something."""
    n = e.get("idle_before_largest_paste")
    if not n or n < config.load()["detect"]["idle_burst_seconds"]:
        return ""
    return (f" The paste was preceded by {n} seconds with no recorded editor "
            f"activity.")


def _timeline(e):
    seq = e.get("event_sequence") or []
    return (" The recorded event sequence is: " + " -> ".join(seq[:12]) + ".") \
        if seq else ""


def _no_run(e):
    if e.get("runs_after_last_paste"):
        return ""
    return " The code was never run between the paste and the submission."


def _curve(e):
    c = e.get("curve") or []
    if not c:
        return ""
    return (" Sampling the replay timeline at " + str(len(c)) +
            " evenly spaced points, the amount of code present was: " +
            ", ".join(str(n) for n in c) + " characters.")


BODIES = {
    D.CODE_APPEARS_IN_ONE_STEP: lambda e: (
        f" Stepping through LeetCode's Code Replay for this submission shows "
        f"the solution appearing all at once rather than being written. "
        f"{e.get('biggest_single_jump_chars', 0)} characters - "
        f"{round(100 * e.get('biggest_jump_fraction', 0))}% of the finished "
        f"{e.get('final_chars', 0)}-character solution - appear in a single "
        f"step of the timeline, and the code grows at only "
        f"{e.get('growth_steps', 0)} point(s) in the whole recording."
        + _curve(e) +
        " Code written in the editor grows steadily across the replay. This "
        "did not; it was complete the moment it appeared."),

    D.NO_INCREMENTAL_PROGRESS: lambda e: (
        f" Stepping through LeetCode's Code Replay for this submission shows no "
        f"gradual progress: across {e.get('samples', 0)} evenly spaced points "
        f"in the recording the code grows at only {e.get('growth_steps', 0)} "
        f"of them, ending at {e.get('final_chars', 0)} characters."
        + _curve(e) +
        " Writing a solution in the editor produces continuous growth across "
        "the recording."),

    D.LARGE_PASTE_THEN_SUBMIT: lambda e: (
        f" LeetCode's Code Replay records an external paste of {_size(e)} at "
        f"{e.get('last_paste_t', 0)} seconds into the editing session, and the "
        f"submission {e.get('paste_to_submit_seconds', 0)} seconds later. The "
        f"whole session lasted {e.get('session_seconds', 0)} seconds."
        + _idle(e) + _no_run(e) + _timeline(e) +
        " A block of that size arriving from outside the editor and being "
        "submitted within seconds leaves no time to read, adapt or test it."),

    D.BURST_AFTER_IDLE: lambda e: (
        f" LeetCode's Code Replay records "
        f"{e.get('idle_before_largest_paste', 0)} seconds with no editor "
        f"activity, followed immediately by a single external paste of "
        f"{_size(e)}. The whole session lasted "
        f"{e.get('session_seconds', 0)} seconds."
        + _no_run(e) + _timeline(e) +
        " Work done in the editor leaves a trail of recorded activity. A silent "
        "gap ending in one large paste indicates the code was produced "
        "elsewhere and transferred in."),

    D.REPEATED_LARGE_PASTES: lambda e: (
        f" LeetCode's Code Replay records {e.get('paste_events', 0)} external "
        f"paste events for this submission, the largest {_size(e)}, totalling "
        f"{e.get('pasted_chars', 0)} characters, across a session of "
        f"{e.get('session_seconds', 0)} seconds."
        + _idle(e) + _timeline(e) +
        " Repeatedly bringing large blocks in from outside the editor is not "
        "consistent with writing the solution in place."),

    D.LARGE_EXTERNAL_PASTE: lambda e: (
        f" LeetCode's Code Replay records an external paste of {_size(e)} for "
        f"this submission - large enough to account for the whole solution - "
        f"in a session lasting {e.get('session_seconds', 0)} seconds."
        + _idle(e) + _no_run(e) + _timeline(e) +
        " A paste of that size is not an incidental edit."),

    D.IMPLAUSIBLE_SOLVE_SPEED: lambda e: (
        f" This submission was accepted {e.get('seconds_after_contest_start', 0)} "
        f"seconds after the contest opened, on a {e.get('problem_credit')}-point "
        f"problem, with {e.get('fail_count', 0)} failed attempt(s). Reading, "
        f"implementing and testing a problem of this difficulty in that time is "
        f"not plausible."),
}


def generate(username, contest_slug, question_slug, reason_code, evidence):
    """Build the report body. Pure string formatting - deterministic."""
    body = BODIES.get(reason_code)
    middle = body(evidence) if body else (
        " LeetCode's Code Replay for this submission shows editor activity "
        "inconsistent with the solution having been written in the editor.")
    return (_OPEN.format(user=username, question=question_slug,
                         contest=contest_slug)
            + middle + " " + _CLOSE)

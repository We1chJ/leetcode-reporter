"""Hard-coded report bodies. No model involved.

One template per reason code, filled from the measured evidence. Every sentence
is either fixed text or a number taken straight from the Code Replay event
history, so a report can always be traced back to what was actually observed.
"""

from core import config
from core import detector as D

# Fixed opening and closing wrapped around a per-reason middle.
_OPEN = ("Reporting user {user} for their submission to \"{question}\" in "
         "{contest}.")
_CLOSE = ("The full event history is visible in the Code Replay for this "
          "submission. Please review it.")


def _idle(e):
    """Only claim an idle gap when it is long enough to actually mean something.

    A four-second pause before a paste is not evidence, and including it as if
    it were weakens the rest of the report.
    """
    n = e.get("idle_before_largest_paste")
    if not n or n < config.load()["detect"]["idle_burst_seconds"]:
        return ""
    return (f" That paste was preceded by {n} seconds with no editor activity "
            f"at all, so nothing was being written in the editor beforehand.")


def _timeline(e):
    seq = e.get("event_sequence") or []
    if not seq:
        return ""
    return " The recorded event sequence is: " + " -> ".join(seq[:12]) + "."


BODIES = {
    D.PASTE_NO_TYPING: lambda e: (
        f" LeetCode's Code Replay records {e.get('paste_events', 0)} external "
        f"paste event(s) for this submission and no typing events whatsoever "
        f"({e.get('input_events', 0)} input events). At least "
        f"{e.get('pasted_chars', 0)} characters arrived by paste while 0 were "
        f"typed. The entire editing session lasted only "
        f"{e.get('session_seconds', 0)} seconds."
        + _idle(e) + _timeline(e) +
        " The accepted solution was therefore never written in the contest "
        "editor; it was pasted in from an external source."),

    D.PASTE_DOMINANT: lambda e: (
        f" LeetCode's Code Replay shows the solution arrived almost entirely by "
        f"external paste: at least {e.get('pasted_chars', 0)} characters were "
        f"pasted across {e.get('paste_events', 0)} event(s), against only "
        f"{e.get('typed_chars', 0)} characters typed over "
        f"{e.get('input_events', 0)} input event(s). The editing session lasted "
        f"{e.get('session_seconds', 0)} seconds."
        + _idle(e) + _timeline(e) +
        " The small amount of typing is not consistent with authoring this "
        "solution; it is consistent with minor edits made around pasted code."),

    D.BURST_AFTER_IDLE: lambda e: (
        f" LeetCode's Code Replay shows a period of "
        f"{e.get('idle_before_largest_paste', 0)} seconds with no editor "
        f"activity, followed immediately by a single external paste of at least "
        f"{e.get('largest_paste_chars', 0)} characters. Across the whole session "
        f"only {e.get('typed_chars', 0)} characters were typed over "
        f"{e.get('input_events', 0)} input event(s)."
        + _timeline(e) +
        " Solving a problem in the editor produces continuous incremental "
        "typing. An idle gap ending in one large paste indicates the solution "
        "was produced elsewhere and transferred in."),

    D.LARGE_EXTERNAL_PASTE: lambda e: (
        f" LeetCode's Code Replay records an external paste of at least "
        f"{e.get('largest_paste_chars', 0)} characters for this submission - "
        f"large enough to account for the entire solution - against "
        f"{e.get('typed_chars', 0)} characters typed."
        + _idle(e) + _timeline(e) +
        " A paste of this size is not an incidental edit."),

    D.PASTE_THEN_IMMEDIATE_SUBMIT: lambda e: (
        f" LeetCode's Code Replay shows this submission was made "
        f"{e.get('paste_to_submit_seconds', 0)} seconds after an external paste "
        f"of at least {e.get('largest_paste_chars', 0)} characters, with "
        f"{e.get('typed_chars', 0)} characters typed in total."
        + _timeline(e) +
        " That leaves no time to read, adapt or test the pasted code, which is "
        "consistent with submitting a solution obtained externally."),

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

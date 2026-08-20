"""Drives LeetCode's "Report Cheating" dialog.

There is no documented report API, so this is UI automation. Selectors are
text/role based rather than class based, since LeetCode's generated class names
churn. Confirm them against a live dialog with `python -m tools.discover`.

In dry-run mode the browser never navigates and nothing is sent; the composed
narrative is still persisted by the caller.
"""

import time

from core import replay

# The dialog will not submit until one of its five reason boxes is ticked.
# Confirmed against a live dialog: with text but no box the Submit button is
# disabled, with a box and no text it is enabled. The box is the only gate.
#
# This is the closest of the five to what the detector actually establishes --
# that the code entered the editor by external paste rather than being written
# there. It does not distinguish an AI from a leaked solution, and the
# narrative says so; "unauthorized assistance" covers both.
REASON_LABEL = "Used external AI / unauthorized assistance"

# The open dialog, ignoring the empty overlay elements that share the role.
_DIALOG = """
  const dlg = [...document.querySelectorAll('[role="dialog"]')]
      .filter(d => d.innerText && d.innerText.length > 40).pop();
  if (!dlg) return null;
"""

# Radix renders each reason as a button[role=checkbox] beside its label rather
# than a real <input>, so .check() does not apply and the modal overlay eats an
# ordinary click. Match on the row's text and dispatch the click. Whether it
# took has to be read back afterwards: data-state is updated by a re-render, so
# it still says "unchecked" in the same tick as the click.
_TICK = "(want) => {" + _DIALOG + """
  for (const b of dlg.querySelectorAll('[role="checkbox"]')) {
    const row = b.parentElement;
    if (row && row.innerText.trim().startsWith(want)) {
      if (b.getAttribute('data-state') !== 'checked') b.click();
      return true;
    }
  }
  return false;
}"""

_STATE = "() => {" + _DIALOG + """
  const sub = [...dlg.querySelectorAll('button')]
      .find(b => b.innerText.trim() === 'Submit');
  return {
    submitDisabled: sub ? sub.disabled : null,
    ticked: [...dlg.querySelectorAll('[role="checkbox"]')]
        .filter(b => b.getAttribute('data-state') === 'checked').length,
    reasons: [...dlg.querySelectorAll('[role="checkbox"]')]
        .map(b => (b.parentElement.innerText || '').trim()),
  };
}"""


class ReportError(RuntimeError):
    pass


# el.click() is an HTMLElement method. The replay control is an <svg>, and
# SVGElement does not inherit it, so the fallback used to die with
# "el.click is not a function" on exactly the element it was written for.
# Dispatching a bubbling MouseEvent works on any element and still reaches
# React's delegated handler.
_DISPATCH = """el => {
  if (typeof el.click === 'function') { el.click(); return; }
  el.dispatchEvent(new MouseEvent('click',
      {bubbles: true, cancelable: true, view: window}));
}"""


def _click(locator, timeout_ms=5_000):
    """Click through the modal overlay.

    The replay modal lays a full-screen overlay over the page, which swallows
    ordinary clicks, so fall back to dispatching the click on the element.
    """
    try:
        locator.click(timeout=timeout_ms)
    except Exception:
        locator.evaluate(_DISPATCH)


def open_submission(session, contest_slug, username, question_index,
                    problem_count=4, ui_page=1, rank=None, finish_offset=None):
    """Open the ranking page for a contestant and click into their submission.

    question_index is 0-based across the contest's problems. rank and
    finish_offset are the positional fallback for the contestants who render no
    profile link; without them find_row has nothing to fall back on.
    """
    page = session.page
    replay.ensure_ranking_page(session, contest_slug, ui_page)
    # The detection pass leaves its replay modal open, and its overlay swallows
    # the click below. The replay path already closes it before clicking; this
    # one did not, which is what pushed every report into the _click fallback.
    replay._close(page)
    row = replay.find_row(page, username, rank=rank, finish_offset=finish_offset)
    cell = replay.problem_cell(row, question_index, problem_count)
    if cell is None:
        raise ReportError(
            f"{username}: no submission cell at index {question_index}")
    _click(cell.locator("svg").last)

    # A China-hosted replay offers to send you to leetcode.cn instead of
    # rendering, and there is no Report Cheating control behind that offer.
    # Decline it and skip, rather than waiting out the timeout. The check reads
    # the open dialog, so it has to wait for one to exist first -- calling it
    # too early finds nothing and passes a China offer straight through.
    try:
        page.wait_for_selector("div[role='dialog']", timeout=8_000)
    except Exception:
        pass
    replay._decline_china_redirect(page)
    page.get_by_text("Report Cheating", exact=False).first.wait_for(timeout=20_000)


def open_report_form(page, timeout_ms=15_000):
    """Click "Report Cheating" and wait for its textarea."""
    ctl = page.get_by_text("Report Cheating", exact=False).first
    ctl.wait_for(timeout=timeout_ms)
    _click(ctl)
    box = page.locator("textarea").last
    box.wait_for(timeout=timeout_ms)
    return box


def tick_reason(page, label=REASON_LABEL, timeout_ms=5_000):
    """Tick the reason box that enables Submit. Raises if it does not take."""
    state = page.evaluate(_STATE) or {}
    if not page.evaluate(_TICK, label):
        raise ReportError(
            f"no reason box matching {label!r}; dialog offers "
            f"{state.get('reasons')}")

    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        state = page.evaluate(_STATE) or {}
        if state.get("ticked"):
            return
        time.sleep(0.15)
    raise ReportError(f"clicked {label!r} but no box reads as ticked")


def submit_report(session, narrative, dry_run=True):
    """Fill and submit the open Report Cheating dialog."""
    page = session.page
    box = open_report_form(page)
    box.fill(narrative)

    written = box.input_value()
    if written.strip() != narrative.strip():
        raise ReportError(
            f"report text did not land in the form "
            f"({len(written)} of {len(narrative)} characters)")

    if dry_run:
        page.keyboard.press("Escape")
        return "dry_run"

    tick_reason(page)

    # Confirm the button actually came alive. Clicking a disabled button is
    # silent, and every earlier report failed exactly there.
    state = page.evaluate(_STATE) or {}
    if state.get("submitDisabled"):
        raise ReportError(
            f"Submit still disabled after ticking a reason "
            f"({state.get('ticked')} box(es) ticked)")

    submit = page.get_by_role("button", name="Submit", exact=False).last
    if not submit.count():
        raise ReportError("no Submit button in the report dialog")
    _click(submit)
    time.sleep(2)
    return "submitted"


def confirm_registered(session, contest_submission_id, tries=6):
    """Ask LeetCode whether the report actually landed.

    A click that silently failed would otherwise be counted as a report sent,
    so the count would overstate what was really filed.

    LeetCode does not always answer yes immediately after the dialog closes.
    Three tries at 1.5s gave up after 4.5s and marked landed reports failed, so
    back off over roughly 20s, returning the moment it shows up.
    """
    for attempt in range(tries):
        if replay.existing_report(session, contest_submission_id):
            return True
        if attempt < tries - 1:
            time.sleep(min(1.5 * (attempt + 1), 6))
    return False


def file_report(session, *, contest_slug, username, question_index, narrative,
                problem_count=4, ui_page=1, dry_run=True,
                contest_submission_id=None, rank=None, finish_offset=None):
    """Full report flow for one submission. Returns the outcome string."""
    if dry_run:
        # Never touch the network in dry-run; the narrative is already persisted.
        return "dry_run"
    open_submission(session, contest_slug, username, question_index,
                    problem_count, ui_page, rank=rank,
                    finish_offset=finish_offset)
    outcome = submit_report(session, narrative, dry_run=False)
    if contest_submission_id and not confirm_registered(session,
                                                        contest_submission_id):
        raise ReportError("submitted, but LeetCode does not show the report")
    return outcome

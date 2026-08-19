"""Drives LeetCode's "Report Cheating" dialog.

There is no documented report API, so this is UI automation. Selectors are
text/role based rather than class based, since LeetCode's generated class names
churn. Confirm them against a live dialog with `python -m tools.discover`.

In dry-run mode the browser never navigates and nothing is sent; the composed
narrative is still persisted by the caller.
"""

import time

from core import replay


class ReportError(RuntimeError):
    pass


def open_submission(session, contest_slug, username, question_index,
                    problem_count=4, ui_page=1):
    """Open the ranking page for a contestant and click into their submission.

    question_index is 0-based across the contest's problems.
    """
    page = session.page
    replay.ensure_ranking_page(session, contest_slug, ui_page)
    row = replay.find_row(page, username)
    cell = replay.problem_cell(row, question_index, problem_count)
    if cell is None:
        raise ReportError(
            f"{username}: no submission cell at index {question_index}")
    cell.locator("svg").last.click()
    page.get_by_text("Report Cheating", exact=False).first.wait_for(timeout=20_000)


def open_report_form(page, timeout_ms=15_000):
    """Click "Report Cheating" and wait for its textarea.

    The replay modal lays a full-screen overlay over the page, which swallows a
    normal click, so fall back to dispatching the click directly on the element.
    """
    ctl = page.get_by_text("Report Cheating", exact=False).first
    ctl.wait_for(timeout=timeout_ms)
    try:
        ctl.click(timeout=5_000)
    except Exception:
        ctl.evaluate("el => el.click()")
    box = page.locator("textarea").last
    box.wait_for(timeout=timeout_ms)
    return box


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

    submit = page.get_by_role("button", name="Submit", exact=False).last
    if not submit.count():
        raise ReportError("no Submit button in the report dialog")
    submit.click()
    time.sleep(2)
    return "submitted"


def confirm_registered(session, contest_submission_id, tries=3):
    """Ask LeetCode whether the report actually landed.

    A click that silently failed would otherwise be counted as a report sent,
    so the count would overstate what was really filed.
    """
    for _ in range(tries):
        if replay.existing_report(session, contest_submission_id):
            return True
        time.sleep(1.5)
    return False


def file_report(session, *, contest_slug, username, question_index, narrative,
                problem_count=4, ui_page=1, dry_run=True,
                contest_submission_id=None):
    """Full report flow for one submission. Returns the outcome string."""
    if dry_run:
        # Never touch the network in dry-run; the narrative is already persisted.
        return "dry_run"
    open_submission(session, contest_slug, username, question_index,
                    problem_count, ui_page)
    outcome = submit_report(session, narrative, dry_run=False)
    if contest_submission_id and not confirm_registered(session,
                                                        contest_submission_id):
        raise ReportError("submitted, but LeetCode does not show the report")
    return outcome

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


def submit_report(session, narrative, dry_run=True):
    """Fill and submit the open Report Cheating dialog."""
    page = session.page
    page.get_by_text("Report Cheating", exact=False).first.click()
    box = page.locator("textarea").last
    box.wait_for(timeout=15_000)
    box.fill(narrative)

    if dry_run:
        page.keyboard.press("Escape")
        return "dry_run"

    page.get_by_role("button", name="Submit", exact=False).last.click()
    time.sleep(2)
    return "submitted"


def file_report(session, *, contest_slug, username, question_index, narrative,
                problem_count=4, ui_page=1, dry_run=True):
    """Full report flow for one submission. Returns the outcome string."""
    if dry_run:
        # Never touch the network in dry-run; the narrative is already persisted.
        return "dry_run"
    open_submission(session, contest_slug, username, question_index,
                    problem_count, ui_page)
    return submit_report(session, narrative, dry_run=False)

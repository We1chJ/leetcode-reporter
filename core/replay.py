"""Code Replay event extraction, plus submission code and report status.

There is no API for replay events: opening a replay fires no request carrying
them, and nothing in the page state exposes them (see tools/FINDINGS.md). But
the player itself has an "Event History" panel that lists every recorded editor
event, and that panel is scrapable. That is what this module reads.

LeetCode's own event vocabulary (from its i18n bundle, `recordEventType`):

    start, switchQuestion, switchLang, pageVisible ("Page Switch"),
    interpretCode ("Run Code"), submitCode, end, input, undo, redo,
    paste ("External Paste"), changeCursor, debug, debugEnd

`External Paste` is LeetCode's own label for content arriving from outside the
editor. A submission whose history is a single External Paste with no Input
events was not written in the editor -- which is the judgment this tool makes
for itself, rather than deferring to LeetCode's `not_enough_activities` flag.
"""

import re

SUBMISSION = "/api/submissions/{submission_id}/"
REPORT = "/contest/api/reports/submissions/{contest_submission_id}/"

# The Event History list container inside the replay modal.
EVENT_LIST = "div.flex.flex-1.flex-col.overflow-y-auto"

INPUT = "Input"
PASTE = "External Paste"
SUBMIT = "Submit Code"
RUN = "Run Code"
PAGE_SWITCH = "Page Switch"

_TIME = re.compile(r"^(\d+):(\d{2})$")
_SIZE = re.compile(r"size\s*(>|≥)?\s*([\d,]+)\s*chars", re.I)


def parse_rows(rows):
    """Parse scraped 'Type | m:ss | detail | ...' strings into event dicts.

    Returns [{"type", "t", "chars", "chars_is_lower_bound", "detail"}].
    `chars` is None when the row carries no size. LeetCode buckets large pastes
    as "size > 500 chars", so a size may be a lower bound rather than exact.
    """
    out = []
    for raw in rows:
        parts = [p.strip() for p in str(raw).split("|") if p.strip()]
        if not parts:
            continue
        etype = parts[0]
        t = None
        chars = None
        lower_bound = False
        for p in parts[1:]:
            m = _TIME.match(p)
            if m and t is None:
                t = int(m.group(1)) * 60 + int(m.group(2))
                continue
            m = _SIZE.search(p)
            if m:
                chars = int(m.group(2).replace(",", ""))
                lower_bound = bool(m.group(1))
        out.append({"type": etype, "t": t if t is not None else 0,
                    "chars": chars, "chars_is_lower_bound": lower_bound,
                    "detail": " | ".join(parts[1:])})
    return out


def _open_event_list(page):
    """Toggle the Event History panel open, if it is not already."""
    for sel in ('button[aria-label="Toggle Event List"]',
                'button[title="Toggle Event List"]',
                '[aria-label="Toggle Event List"]'):
        btn = page.locator(sel)
        if btn.count():
            btn.first.click()
            return True
    # Fall back to the last icon button in the player footer.
    btns = page.locator("div[role='dialog'] button, .fixed button")
    if btns.count():
        btns.last.click()
        return True
    return False


RANKING_URL = "https://leetcode.com/contest/{slug}/ranking/{page}?region=global_v2"


def ensure_ranking_page(session, contest_slug, ui_page=1):
    """Open the ranking page holding a given block of 25 contestants.

    The replay modal can only be opened from the ranking table, so the right
    page has to be on screen before scraping. Cheap no-op when already there.
    """
    want = RANKING_URL.format(slug=contest_slug,
                              page="" if ui_page <= 1 else f"{ui_page}/")
    if session.page.url.split("#")[0] != want:
        session.page.goto(want, wait_until="domcontentloaded")
        session.page.wait_for_selector("tr", timeout=20_000)


def events(session, contest_slug, username, question_index, ui_page=1,
           timeout_ms=15_000):
    """Scrape one submission's Code Replay event history.

    Returns the parsed event list, or None when the submission has no replay.
    """
    ensure_ranking_page(session, contest_slug, ui_page)
    page = session.page
    row = page.locator("tr", has=page.get_by_role("link", name=username)).first
    row.wait_for(timeout=timeout_ms)

    cells = row.locator("td")
    # The first columns are rank / name / score / finish time; problems follow.
    offset = cells.count() - _problem_count(page)
    cell = cells.nth(offset + question_index)
    icon = cell.locator("button, svg, a").last
    if not icon.count():
        return None
    icon.click()

    page.wait_for_selector("text=Code Replay", timeout=timeout_ms)
    _open_event_list(page)

    container = page.locator(EVENT_LIST).filter(
        has_text=re.compile("Submit Code|Input|External Paste"))
    if not container.count():
        _close(page)
        return None
    rows = container.first.locator("> *").all_inner_texts()
    _close(page)
    return parse_rows(r.replace("\n", " | ") for r in rows)


def _problem_count(page):
    """Number of problem columns, read from the ranking table header."""
    heads = page.locator("thead th, tr:first-child th").all_inner_texts()
    return sum(1 for h in heads if re.match(r"^Q\d", h.strip())) or 4


def _close(page):
    page.keyboard.press("Escape")


# --- plain REST helpers ---------------------------------------------------

def code(session, submission_id):
    """Submitted source. Returns {'lang', 'code', 'contest_submission'} or None."""
    data = session.get_json(SUBMISSION.format(submission_id=submission_id))
    if not isinstance(data, dict) or "__error" in data:
        return None
    return {"lang": data.get("lang"), "code": data.get("code") or "",
            "contest_submission": data.get("contest_submission")}


def existing_report(session, contest_submission_id):
    """The report already filed against this submission, or None.

    LeetCode answers {"id": -1} when the signed-in user has not reported it, so
    this is an authoritative duplicate check that survives a database reset.
    """
    data = session.get_json(
        REPORT.format(contest_submission_id=contest_submission_id))
    if not isinstance(data, dict) or "__error" in data:
        return None
    return None if data.get("id", -1) == -1 else data

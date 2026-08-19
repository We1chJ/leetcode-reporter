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

# The ranking "table" is not a table: there is no <table>, <tr> or <td> on the
# page at all, only nested divs. A contestant's row is the nearest ancestor of
# their profile link that spans the full width, and its last N children are the
# per-problem cells (the rank number lives outside the row, in a sticky column).
ROW_FROM_LINK = ('xpath=ancestor::div[contains(@class,"h-[50px]")'
                 ' and contains(@class,"w-full")][1]')

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


def _event_toggle(page):
    """The Event History toggle button in the player footer.

    It carries no aria-label, but it is a real toggle: aria-pressed / data-state
    report whether the panel is open, so its state can be read rather than
    guessed. Never select the last footer button -- that one is "Close".
    """
    # Not scoped to the dialog: the footer controls sit outside the element
    # that carries role="dialog".
    btns = page.locator("button[aria-pressed]")
    return btns.last if btns.count() else None


def _open_event_list(page):
    """Ensure the Event History panel is open. Safe to call when already open."""
    btn = _event_toggle(page)
    if btn is None:
        return False
    if (btn.get_attribute("aria-pressed") or "").lower() == "true":
        return True                      # already open; toggling would close it
    btn.click()
    return True


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
    # Wait for the grid itself, not for a <tr> that never exists.
    session.page.wait_for_selector('a[href^="/u/"]', timeout=20_000)


def find_row(page, username, timeout_ms=15_000):
    """The row container for one contestant, located via their profile link."""
    link = page.locator(f'a[href="/u/{username}/"]').first
    link.wait_for(timeout=timeout_ms)
    return link.locator(ROW_FROM_LINK)


def problem_cell(row, question_index, problem_count):
    """The cell for one problem. Problem cells are the row's last N children."""
    cells = row.locator("> div")
    offset = cells.count() - problem_count
    if offset < 0 or question_index >= problem_count:
        return None
    return cells.nth(offset + question_index)


def events(session, contest_slug, username, question_index, problem_count=4,
           ui_page=1, timeout_ms=15_000, attempts=3):
    """Scrape one submission's Code Replay event history.

    Returns the parsed event list, or None when the submission has no replay.

    Opening the modal and rendering the panel is timing-sensitive, and an
    occasional attempt comes back empty even though the data is there. Since an
    empty result silently looks like "nothing suspicious", retry before
    accepting it.
    """
    for attempt in range(attempts):
        got = _events_once(session, contest_slug, username, question_index,
                           problem_count, ui_page, timeout_ms)
        if got:
            return got
        session.page.wait_for_timeout(700)
    return None


def _events_once(session, contest_slug, username, question_index, problem_count,
                 ui_page, timeout_ms):
    ensure_ranking_page(session, contest_slug, ui_page)
    page = session.page
    # A modal left open by the previous submission would swallow the next
    # click, so make sure the board is actually reachable first.
    _close(page)
    row = find_row(page, username, timeout_ms)
    cell = problem_cell(row, question_index, problem_count)
    if cell is None:
        return None
    # The replay control is the rightmost icon in the cell.
    icon = cell.locator("svg").last
    if not icon.count():
        return None

    # A click can be swallowed while the previous modal is still animating out,
    # leaving no dialog at all. Retry once before giving up on the submission.
    for attempt in range(2):
        icon.click()
        try:
            page.wait_for_selector("div[role='dialog']", timeout=6_000)
            break
        except Exception:
            if attempt:
                return None
            page.wait_for_timeout(1_000)

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


def _close(page):
    """Close the replay modal and wait until it is really gone."""
    if not page.locator("div[role='dialog']").count():
        return
    page.keyboard.press("Escape")
    try:
        page.wait_for_function(
            "() => !document.querySelector('div[role=\'dialog\']')",
            timeout=5_000)
    except Exception:
        pass


def _wait_container(page, timeout_ms):
    """Wait for the Event History rows to render, then return the container."""
    try:
        page.wait_for_function(
            """(sel) => {
                for (const e of document.querySelectorAll(sel)) {
                    if (/Submit Code|Input|External Paste|Run Code/.test(e.innerText || ''))
                        return true;
                }
                return false;
            }""",
            arg=EVENT_LIST, timeout=timeout_ms)
    except Exception:
        return None
    return _event_container(page)


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

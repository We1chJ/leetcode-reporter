"""Per-submission detail: the submitted code, and existing-report status.

Named for Code Replay because that is the feature this tool reasons about, but
note what the discovery spike established (tools/FINDINGS.md): opening a Code
Replay fires no request carrying keystroke events, and no replay GraphQL
operation exists in the loaded bundles. Per-event replay data is therefore NOT
retrievable over the API.

What *is* retrievable, and what this module provides:
  - the submitted source code
  - whether the signed-in user has already reported this submission

The paste signal itself comes from LeetCode's own `not_enough_activities` flag
on the ranking payload; see core/contest.py.
"""

SUBMISSION = "/api/submissions/{submission_id}/"
REPORT = "/contest/api/reports/submissions/{contest_submission_id}/"


def code(session, submission_id):
    """Submitted source. Returns {'lang', 'code', 'contest_submission'} or None."""
    data = session.get_json(SUBMISSION.format(submission_id=submission_id))
    if not isinstance(data, dict) or "__error" in data:
        return None
    return {"lang": data.get("lang"), "code": data.get("code") or "",
            "contest_submission": data.get("contest_submission")}


def existing_report(session, contest_submission_id):
    """The report already filed against this submission, or None.

    LeetCode answers {"id": -1} when the signed-in user has not reported it.
    This survives a reinstall of the local database, so it is the authoritative
    duplicate check.
    """
    data = session.get_json(
        REPORT.format(contest_submission_id=contest_submission_id))
    if not isinstance(data, dict) or "__error" in data:
        return None
    if data.get("id", -1) == -1:
        return None
    return data

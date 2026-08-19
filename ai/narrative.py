"""Turn a hard-coded reason code plus replay evidence into report prose.

LeetCode rejects reports that lack detail, so the narrative has to be specific.
Every sentence must be grounded in the evidence dict -- a report sent to a human
reviewer must not contain invented facts.
"""

import json

from ai import client
from core.detector import REASON_TEXT

SYSTEM = """You write contest-violation reports for LeetCode's moderation team.

You are given a hard-coded reason code, the finding it corresponds to, and the \
measured evidence from LeetCode's own Code Replay recording of the submission.

Rules:
- Use ONLY the numbers and facts in the evidence object. Never invent a detail, \
never estimate a number that is not given, never speculate about the source of \
the code or the contestant's intent.
- Write 4-7 sentences of plain prose. No markdown, no bullet points, no headings.
- State what the replay shows, cite the specific figures (character counts, event \
counts, timestamps in seconds from the contest start), and say why that pattern \
is inconsistent with writing the solution in the editor.
- Acknowledge nothing you cannot support. Do not claim to know where the code \
came from.
- End by asking the moderation team to review the Code Replay for this submission.
"""


def _template(username, contest_slug, question_slug, reason_code, evidence):
    """Deterministic fallback used when ai.enabled is false or the API fails."""
    e = evidence
    parts = [
        f"Reporting user {username} for the submission to {question_slug} in "
        f"{contest_slug}. "
        f"{REASON_TEXT.get(reason_code, 'The submission shows signs of a contest violation').capitalize()}."
    ]
    if e.get("leetcode_insufficient_activity"):
        parts.append(
            "LeetCode's own editor-activity check marked this submission as having "
            "insufficient editor activity.")
    if e.get("seconds_after_contest_start") is not None:
        parts.append(
            f"The submission was accepted {e['seconds_after_contest_start']} seconds "
            f"after the contest opened, on a {e.get('problem_credit')}-point problem, "
            f"with {e.get('fail_count', 0)} failed attempt(s).")
    if e.get("all_problems_solved_within_seconds") is not None:
        parts.append(
            f"All problems in this contest were solved within "
            f"{e['all_problems_solved_within_seconds']} seconds of one another.")
    parts.append("Please review the Code Replay for this submission.")
    return " ".join(parts)


def generate(username, contest_slug, question_slug, reason_code, evidence):
    if not client.enabled():
        return _template(username, contest_slug, question_slug, reason_code, evidence)

    cfg = client.settings()
    prompt = (
        f"Contestant: {username}\n"
        f"Contest: {contest_slug}\n"
        f"Problem: {question_slug}\n"
        f"Reason code: {reason_code}\n"
        f"Finding: {REASON_TEXT.get(reason_code, '')}\n"
        f"Evidence from the Code Replay:\n{json.dumps(evidence, indent=2)}\n\n"
        "Write the report body."
    )
    try:
        resp = client.get().messages.create(
            model=cfg["model"],
            max_tokens=1600,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": cfg["effort"]},
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or _template(username, contest_slug, question_slug,
                                 reason_code, evidence)
    except Exception:
        return _template(username, contest_slug, question_slug, reason_code, evidence)

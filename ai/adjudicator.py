"""Grey-zone adjudication: is this submission actually a violation?

Only called for submissions the deterministic detector scored between
detect.grey_low and detect.cheat_threshold, or that tripped a speed rule without
LeetCode's own activity flag. A grey case defaults to "not a violation" -- the
model has to affirmatively promote it.
"""

import json

from ai import client

SYSTEM = """You review LeetCode contest submissions to judge whether one should be reported for a contest violation.

You are given measured evidence, not opinions. The strongest single signal is `leetcode_insufficient_activity`: LeetCode's own editor-activity check, which is true when their system determined the code was not typed in the contest editor. The other signals are timing: how many seconds after the contest opened the submission was accepted, against a generous floor for that problem's credit value, and whether every problem was solved within an implausibly short span.

Things that are NOT by themselves violations:
- a fast solve by a strong contestant on a low-credit problem
- pasting in one's own pre-written template or library code
- a fast solve where LeetCode's activity check did not fire

Be conservative: this drives an automated report against a real person. Report "violation" only when the evidence is genuinely hard to explain innocently. If it is ambiguous, answer "not_violation".
"""

SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["violation", "not_violation"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string"},
        },
        "required": ["verdict", "confidence", "rationale"],
        "additionalProperties": False,
    },
}


def adjudicate(evidence, ctx=None):
    """Returns {verdict, confidence, rationale}. Defaults to not_violation."""
    if not client.enabled():
        return {"verdict": "not_violation", "confidence": 0.0,
                "rationale": "AI adjudication disabled."}

    cfg = client.settings()
    prompt = (
        f"Problem: {(ctx or {}).get('question_slug', 'unknown')} "
        f"(credit {(ctx or {}).get('credit')})\n"
        f"Measured evidence:\n{json.dumps(evidence, indent=2)}"
    )
    try:
        resp = client.get().messages.create(
            model=cfg["model"],
            max_tokens=2000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": cfg["effort"], "format": SCHEMA},
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return json.loads(text)
    except Exception as exc:
        return {"verdict": "not_violation", "confidence": 0.0,
                "rationale": f"adjudication failed: {exc}"}

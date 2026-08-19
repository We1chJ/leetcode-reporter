"""Contest metadata and leaderboard scraping.

Endpoint shapes below were confirmed against a live signed-in session on
weekly-contest-515 (see tools/FINDINGS.md), not guessed.

Two ranking regions return different payloads and we need both:

  region=global      -> {time, is_past, submissions[], questions[], total_rank[],
                         user_num}. submissions[i] is a dict keyed by question_id
                         whose records carry `id` (the contest-submission id used
                         by the report endpoint) as well as `submission_id`.
  region=global_v2   -> {user_num, ak_info, total_rank[]}. Each row nests its own
                        `submissions` and `replays`, and each submission record
                        carries `not_enough_activities` -- LeetCode's own
                        editor-activity flag, which is our primary signal.
"""

import time

RANKING = "/contest/api/ranking/{slug}/?pagination={page}&region={region}"
INFO = "/contest/api/info/{slug}/"
PAGE_SIZE = 25


def _get(session, url):
    data = session.get_json(url)
    if isinstance(data, dict) and "__error" in data:
        raise RuntimeError(f"{url}: HTTP {data['__error']}")
    return data


def info(session, slug):
    """Contest metadata. `start_time` is epoch seconds; `duration` is seconds."""
    data = _get(session, INFO.format(slug=slug))
    c = data.get("contest") or {}
    return {"start_time": c.get("start_time"), "duration": c.get("duration"),
            "title": c.get("title")}


def questions(session, slug):
    """Ordered problems. Returns [{question_id, title_slug, credit}]."""
    data = _get(session, RANKING.format(slug=slug, page=1, region="global"))
    if not data:
        raise RuntimeError(f"{slug}: no ranking data (contest may not have run yet)")
    return [{"question_id": q["question_id"], "title_slug": q["title_slug"],
             "credit": q.get("credit")} for q in data.get("questions", [])]


def _page(session, slug, page):
    """Merge the two region payloads for one page of 25 contestants."""
    v1 = _get(session, RANKING.format(slug=slug, page=page, region="global"))
    v2 = _get(session, RANKING.format(slug=slug, page=page, region="global_v2"))
    rows_v1 = (v1 or {}).get("total_rank") or []
    subs_v1 = (v1 or {}).get("submissions") or []
    rows_v2 = (v2 or {}).get("total_rank") or []

    # v2 rows carry not_enough_activities; v1 rows carry the report-side `id`.
    v2_by_user = {r.get("user_slug"): r for r in rows_v2}

    out = []
    for i, row in enumerate(rows_v1):
        user = row.get("user_slug") or row.get("username")
        v2row = v2_by_user.get(user, {})
        merged = {}
        for qid, rec in (subs_v1[i] if i < len(subs_v1) else {}).items():
            v2rec = (v2row.get("submissions") or {}).get(str(qid), {})
            merged[str(qid)] = {
                "submission_id": rec.get("submission_id"),
                # `id` is the contest-submission id the report endpoint keys on.
                "contest_submission_id": rec.get("id"),
                "date": rec.get("date"),
                "lang": rec.get("lang"),
                "fail_count": rec.get("fail_count"),
                "not_enough_activities": bool(v2rec.get("not_enough_activities")),
                "has_replay": bool((v2row.get("replays") or {}).get(str(qid))),
            }
        out.append({
            "rank": row.get("rank"),
            "username": user,
            "score": row.get("score"),
            "finish_time": row.get("finish_time"),
            "submissions": merged,
        })
    return out


def leaderboard(session, slug, rank_start, rank_end, delay=1.0, on_progress=None):
    """Yield contestant dicts for ranks in [rank_start, rank_end]."""
    first = max(1, (rank_start - 1) // PAGE_SIZE + 1)
    last = max(1, (rank_end - 1) // PAGE_SIZE + 1)

    for page in range(first, last + 1):
        for row in _page(session, slug, page):
            if row["rank"] is not None and rank_start <= row["rank"] <= rank_end:
                yield row
        if on_progress:
            on_progress(page, last)
        time.sleep(delay)

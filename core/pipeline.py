"""Scan orchestration: leaderboard -> replay -> detect -> report.

Fully deterministic; no model is called anywhere in this path.
"""

import threading
import time

from core import config, contest, detector, replay, report_text, reporter
from core.browser import Session
from db import store


class Pipeline:
    """One scan at a time. `stop()` is the kill switch."""

    def __init__(self, emit):
        self.emit = emit                 # emit(dict) -> pushed to the UI over SSE
        self._stop = threading.Event()
        self.running = False

    def stop(self):
        self._stop.set()
        self.emit({"type": "log", "level": "warn", "msg": "Stop requested."})

    def scan(self, contest_slug, contestants=None):
        """Scan one contest.

        `contestants` overrides how far down the leaderboard to go, counting
        from the configured starting rank. None means use the configured range.
        """
        cfg = config.load(reload=True)
        safety, scope = cfg["safety"], dict(cfg["scope"])
        if contestants:
            scope["rank_end"] = scope["rank_start"] + int(contestants) - 1
        dry_run = safety["dry_run"]

        self.running = True
        self._stop.clear()
        conn = store.connect()
        scan_id = store.start_scan(conn, contest_slug)
        scanned = inspected = flagged = reported = 0
        last_report_at = 0.0
        status = "done"

        # The range goes out with the event so the UI counts against what is
        # actually being scanned, not what the config file happens to say.
        self.emit({"type": "scan_start", "contest": contest_slug,
                   "dry_run": dry_run, "rank_start": scope["rank_start"],
                   "rank_end": scope["rank_end"]})
        if dry_run:
            self.emit({"type": "log", "level": "warn",
                       "msg": "DRY RUN - reports are composed and stored, nothing "
                              "is submitted to LeetCode."})

        try:
            with Session() as session:
                session.require_login()
                who = session.whoami()
                self.emit({"type": "log", "msg": f"Signed in as {who}."})

                meta = contest.info(session, contest_slug)
                qs = contest.questions(session, contest_slug)
                credit = {str(q["question_id"]): q["credit"] for q in qs}
                slug_of = {str(q["question_id"]): q["title_slug"] for q in qs}
                index_of = {str(q["question_id"]): i for i, q in enumerate(qs)}
                wanted = set(scope["questions"] or range(len(qs)))
                self.emit({"type": "log",
                           "msg": f"{meta['title'] or contest_slug}: {len(qs)} problems, "
                                  f"scanning ranks {scope['rank_start']}-{scope['rank_end']}."})

                for row in contest.leaderboard(
                    session, contest_slug, scope["rank_start"], scope["rank_end"],
                    delay=scope["request_delay"],
                ):
                    if self._stop.is_set():
                        status = "stopped"
                        break
                    scanned += 1
                    username = row["username"]
                    self.emit({"type": "progress", "rank": row["rank"], "user": username})

                    dates = [s["date"] for s in row["submissions"].values() if s.get("date")]
                    sweep = (max(dates) - min(dates)
                             if len(dates) == len(qs) and len(qs) > 1 else None)
                    # Context for the report only; a tight sweep is normal at the
                    # top of a leaderboard and never scores on its own.

                    for qid, sub in row["submissions"].items():
                        if self._stop.is_set():
                            break
                        if index_of.get(qid) not in wanted:
                            continue
                        sub_id = str(sub.get("submission_id") or "")
                        if not sub_id or store.already_reported(conn, sub_id):
                            continue

                        qslug = slug_of.get(qid, qid)

                        # Read the Code Replay: both the event history and the
                        # growth curve. This is the whole basis of the judgment,
                        # so a failure must not be silently treated as
                        # "nothing to see".
                        evs = None
                        ctx_progression = None
                        if sub.get("has_replay"):
                            try:
                                got = replay.inspect(
                                    session, contest_slug, username,
                                    index_of[qid], problem_count=len(qs),
                                    ui_page=(row["rank"] - 1) // 25 + 1,
                                    samples=cfg["detect"]["progression_samples"],
                                    rank=row["rank"],
                                    finish_offset=(row["finish_time"] -
                                                   meta["start_time"])
                                    if row.get("finish_time") else None)
                                if got:
                                    evs = got["events"]
                                    ctx_progression = got["progression"]
                            except replay.ChinaAccountRedirect:
                                self.emit({"type": "log",
                                           "msg": f"{username} {qslug}: LeetCode "
                                                  f"China account, skipped"})
                            except Exception as exc:
                                self.emit({"type": "log", "level": "warn",
                                           "msg": f"{username} {qslug}: "
                                                  f"replay unreadable ({exc})"})

                        ctx = {"start_time": meta["start_time"],
                               "credit": credit.get(qid),
                               "question_slug": qslug,
                               "sweep_span": sweep,
                               "progression": ctx_progression}
                        inspected += 1
                        verdict, score, reason, evidence = detector.analyse(evs, sub, ctx)

                        if verdict == detector.CLEAN:
                            continue

                        if verdict == detector.GREY:
                            # Recorded for review, never auto-reported. Stored
                            # as a row so the total counts it once however many
                            # times the contest is rescanned.
                            flagged += 1
                            store.record_report(
                                conn, username=username, contest_slug=contest_slug,
                                question_slug=ctx["question_slug"], submission_id=sub_id,
                                reason_code=reason, score=score, evidence=evidence,
                                narrative=report_text.generate(
                                    username, contest_slug, ctx["question_slug"],
                                    reason, evidence),
                                dry_run=dry_run, verdict=store.GREY)
                            self.emit({"type": "log",
                                       "msg": f"{username} {ctx['question_slug']}: "
                                              f"grey ({score}) {reason} - not reported"})
                            continue

                        if reported >= safety["max_reports_per_contest"]:
                            self.emit({"type": "log", "level": "warn",
                                       "msg": "Report cap reached for this contest."})
                            continue

                        # Authoritative duplicate check against LeetCode itself.
                        csid = sub.get("contest_submission_id")
                        if csid and replay.existing_report(session, csid):
                            self.emit({"type": "log",
                                       "msg": f"{username} {ctx['question_slug']}: "
                                              "already reported on LeetCode, skipping."})
                            continue

                        text = report_text.generate(username, contest_slug,
                                                    ctx["question_slug"], reason, evidence)
                        report_id = store.record_report(
                            conn, username=username, contest_slug=contest_slug,
                            question_slug=ctx["question_slug"], submission_id=sub_id,
                            reason_code=reason, score=score, evidence=evidence,
                            narrative=text, dry_run=dry_run)
                        if report_id is None:
                            continue

                        gap = safety["min_seconds_between_reports"] - (
                            time.time() - last_report_at)
                        if gap > 0 and not dry_run:
                            time.sleep(gap)

                        try:
                            outcome = reporter.file_report(
                                session, contest_slug=contest_slug, username=username,
                                question_index=index_of[qid], narrative=text,
                                problem_count=len(qs),
                                ui_page=(row["rank"] - 1) // 25 + 1,
                                dry_run=dry_run, contest_submission_id=csid,
                                rank=row["rank"],
                                finish_offset=(row["finish_time"] -
                                               meta["start_time"])
                                if row.get("finish_time") else None)
                            store.mark_report(conn, report_id, outcome)
                        except Exception as exc:
                            store.mark_report(conn, report_id, "failed", str(exc))
                            self.emit({"type": "log", "level": "error",
                                       "msg": f"report {username}: {exc}"})
                            continue

                        last_report_at = time.time()
                        reported += 1
                        self.emit({"type": "report", "user": username,
                                   "question": ctx["question_slug"], "reason": reason,
                                   "score": score, "outcome": outcome})
        except Exception as exc:
            status = "error"
            self.emit({"type": "log", "level": "error", "msg": f"scan failed: {exc}"})
        finally:
            store.finish_scan(conn, scan_id, scanned, inspected, flagged,
                              reported, status)
            conn.close()
            self.running = False
            self.emit({"type": "scan_end", "status": status, "scanned": scanned,
                       "inspected": inspected, "flagged": flagged,
                       "reported": reported})

"""Scan orchestration: leaderboard -> detect -> adjudicate -> report."""

import threading
import time

from ai import adjudicator, narrative
from core import config, contest, detector, replay, reporter
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

    def scan(self, contest_slug):
        cfg = config.load(reload=True)
        safety, scope, det = cfg["safety"], cfg["scope"], cfg["detect"]
        dry_run = safety["dry_run"]

        self.running = True
        self._stop.clear()
        conn = store.connect()
        scan_id = store.start_scan(conn, contest_slug)
        scanned = flagged = reported = 0
        last_report_at = 0.0
        status = "done"

        self.emit({"type": "scan_start", "contest": contest_slug, "dry_run": dry_run})
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

                    for qid, sub in row["submissions"].items():
                        if self._stop.is_set():
                            break
                        if index_of.get(qid) not in wanted:
                            continue
                        sub_id = str(sub.get("submission_id") or "")
                        if not sub_id or store.already_reported(conn, sub_id):
                            continue

                        ctx = {"start_time": meta["start_time"],
                               "credit": credit.get(qid),
                               "question_slug": slug_of.get(qid, qid),
                               "sweep_span": sweep}
                        verdict, score, reason, evidence = detector.analyse(sub, ctx)

                        if verdict == detector.CLEAN:
                            continue

                        # Never report on speed alone unless explicitly allowed.
                        if det["require_leetcode_flag"] and not sub.get("not_enough_activities"):
                            if verdict == detector.CHEAT:
                                verdict = detector.GREY

                        if verdict == detector.GREY:
                            ruling = adjudicator.adjudicate(evidence, ctx)
                            evidence["adjudication"] = ruling
                            self.emit({"type": "log",
                                       "msg": f"{username} {ctx['question_slug']}: grey "
                                              f"({score}) -> {ruling['verdict']}"})
                            if ruling["verdict"] != "violation":
                                continue
                            verdict = detector.CHEAT

                        flagged += 1
                        store.touch_offender(conn, username, contest_slug, False)

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

                        text = narrative.generate(username, contest_slug,
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
                                dry_run=dry_run)
                            store.mark_report(conn, report_id, outcome)
                        except Exception as exc:
                            store.mark_report(conn, report_id, "failed", str(exc))
                            self.emit({"type": "log", "level": "error",
                                       "msg": f"report {username}: {exc}"})
                            continue

                        last_report_at = time.time()
                        reported += 1
                        store.touch_offender(conn, username, contest_slug, True)
                        self.emit({"type": "report", "user": username,
                                   "question": ctx["question_slug"], "reason": reason,
                                   "score": score, "outcome": outcome})
        except Exception as exc:
            status = "error"
            self.emit({"type": "log", "level": "error", "msg": f"scan failed: {exc}"})
        finally:
            store.finish_scan(conn, scan_id, scanned, flagged, reported, status)
            conn.close()
            self.running = False
            self.emit({"type": "scan_end", "status": status, "scanned": scanned,
                       "flagged": flagged, "reported": reported})

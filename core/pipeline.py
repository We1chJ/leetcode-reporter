"""Scan orchestration: leaderboard -> replay -> detect -> report.

Fully deterministic; no model is called anywhere in this path.
"""

import threading
import time

from core import config, contest, detector, replay, report_text, reporter
from core.browser import Session
from db import store


class Pipeline:
    """One scan at a time. `stop()` is the kill switch, `pause()` the hold.

    Both are cooperative: the scan spends most of its time inside Playwright
    calls that cannot be interrupted from another thread, so it checks between
    steps instead. The checks sit either side of every slow step, and every
    sleep is a wait on the stop event rather than time.sleep, so a stop lands
    within the current step rather than after the next 45-second throttle.
    """

    def __init__(self, emit):
        self.emit = emit                 # emit(dict) -> pushed to the UI over SSE
        self._stop = threading.Event()
        self._pause = threading.Event()
        self.running = False

    @property
    def paused(self):
        return self._pause.is_set()

    def stop(self):
        self._stop.set()
        # Releases the scan if it is sitting in a pause.
        self._pause.clear()
        self.emit({"type": "log", "level": "warn", "msg": "Stop requested."})

    def pause(self):
        if self.running and not self._pause.is_set():
            self._pause.set()
            self.emit({"type": "log", "level": "warn",
                       "msg": "Paused - finishing the current step first."})
            self.emit({"type": "state", "paused": True})

    def resume(self):
        if self._pause.is_set():
            self._pause.clear()
            self.emit({"type": "log", "msg": "Resumed."})
            self.emit({"type": "state", "paused": False})

    def _go(self):
        """Hold here while paused. False means the scan should stop."""
        while self._pause.is_set() and not self._stop.is_set():
            self._stop.wait(0.2)
        return not self._stop.is_set()

    def _wait(self, seconds):
        """Sleep, waking at once on stop and holding while paused.

        The deadline is wall-clock, so time spent paused counts towards the
        report throttle -- pausing can only ever make the pacing gentler.
        """
        deadline = time.time() + seconds
        while True:
            if not self._go():
                return False
            left = deadline - time.time()
            if left <= 0:
                return True
            if self._stop.wait(min(left, 0.5)):
                return False

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
        self._pause.clear()
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

                # My own placing in this contest, recorded before the scan
                # changes anything. Only meaningful for a contest I entered;
                # for any other there is simply no rank, which is not an error.
                try:
                    mine = contest.my_rank(session, contest_slug, who)
                except Exception as exc:
                    mine = None
                    self.emit({"type": "log", "level": "warn",
                               "msg": f"Could not read my rank ({exc})."})
                if mine is None:
                    self.emit({"type": "log",
                               "msg": f"{who} did not enter this contest - "
                                      "no rank to track."})
                else:
                    prev = store.rank_progress(conn, who)
                    was = next((r["first_rank"] for r in prev
                                if r["contest_slug"] == contest_slug), None)
                    store.record_rank(conn, contest_slug, who, mine)
                    moved = "" if was is None else f", {was - mine:+d} since first seen"
                    self.emit({"type": "log",
                               "msg": f"My rank in this contest: {mine}{moved}."})

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
                    if not self._go():
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
                        if not self._go():
                            break
                        if index_of.get(qid) not in wanted:
                            continue
                        sub_id = str(sub.get("submission_id") or "")
                        if not sub_id or store.already_reported(conn, sub_id):
                            continue

                        qslug = slug_of.get(qid, qid)

                        # Gate before the replay read, the slowest step here.
                        # It has to break rather than skip the read: judging a
                        # submission whose replay was never fetched would score
                        # it on missing evidence.
                        if not self._go():
                            break

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
                        if gap > 0 and not dry_run and not self._wait(gap):
                            break

                        # Last check before the one step that changes anything
                        # outside this machine. Stopping here leaves the finding
                        # stored and unsent, which a later scan will pick up.
                        if not self._go():
                            break

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

"""Local FastAPI app. Not exposed beyond localhost."""

import json
import queue
import re
import threading

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core import chrome, config, contest
from core.pipeline import Pipeline
from db import store

app = FastAPI(title="LeetCode Contest Reporter")

_events = queue.Queue()
_pipeline = Pipeline(lambda ev: _events.put(ev))


# The dashboard is read straight off disk on every request, so a stale copy in
# the browser is always wrong. It is also actively harmful: an old index.html
# served next to a new app.js leaves the script querying buttons that are not
# in the page, and the resulting null throws out of setRunning and takes the
# Stop button down with it. Nothing here is worth caching -- it is localhost.
NO_STORE = {"Cache-Control": "no-store, must-revalidate"}


@app.get("/")
def index():
    return FileResponse(config.ROOT / "web" / "index.html", headers=NO_STORE)


class _NoStoreStatic(StaticFiles):
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers.update(NO_STORE)
        return resp


app.mount("/static", _NoStoreStatic(directory=config.ROOT / "web"), name="static")


@app.get("/api/config")
def get_config():
    cfg = config.load(reload=True)
    return {"safety": cfg["safety"], "scope": cfg["scope"],
            "detect": cfg["detect"], "running": _pipeline.running,
            "paused": _pipeline.paused}


@app.post("/api/scan/{contest_slug}")
def start_scan(contest_slug: str, contestants: int | None = None):
    """Start a scan. `contestants` overrides the configured rank range."""
    if _pipeline.running:
        return {"ok": False, "error": "a scan is already running"}
    slug = contest.normalise_slug(contest_slug)
    if contestants is not None and contestants < 1:
        return {"ok": False, "error": "contestants must be at least 1"}
    threading.Thread(target=_pipeline.scan, args=(slug,),
                     kwargs={"contestants": contestants}, daemon=True).start()
    return {"ok": True, "slug": slug, "contestants": contestants}


# Anchored to the whole line so it cannot match dry_run inside a comment.
_DRY_RUN_LINE = re.compile(r"^(dry_run\s*=\s*)(?:true|false)[ 	]*$", re.M)


@app.post("/api/mode")
def set_mode(dry_run: bool):
    """Flip the dry-run switch and persist it to config.toml.

    Rewrites the one line rather than re-serialising the file: the comments in
    config.toml are its documentation, and a TOML dump would drop every one.

    A scan already under way keeps the mode it started with. It read its own
    copy of the config at the start, and reload() builds a fresh dict rather
    than mutating that one, so a report can never change category mid-flight.
    """
    path = config.ROOT / "config.toml"
    text = path.read_text(encoding="utf-8")
    new_text, n = _DRY_RUN_LINE.subn(
        lambda m: m.group(1) + ("true" if dry_run else "false"), text)
    if n != 1:
        return {"ok": False, "error": f"expected one dry_run line, found {n}"}
    path.write_text(new_text, encoding="utf-8")
    # Report what actually parsed back, not what we meant to write.
    return {"ok": True, "dry_run": config.load(reload=True)["safety"]["dry_run"],
            "running": _pipeline.running}


@app.post("/api/stop")
def stop():
    _pipeline.stop()
    return {"ok": True}


@app.post("/api/pause")
def pause():
    """Hold the scan at the next step boundary. Nothing is lost."""
    if not _pipeline.running:
        return {"ok": False, "error": "no scan is running"}
    _pipeline.pause()
    return {"ok": True, "paused": True}


@app.post("/api/resume")
def resume():
    _pipeline.resume()
    return {"ok": True, "paused": False}


@app.get("/api/stats")
def stats():
    """Lifetime totals across every scan ever run."""
    conn = store.connect()
    try:
        return store.stats(conn)
    finally:
        conn.close()


@app.get("/api/setup")
def setup():
    """Everything that must be true before a scan can run."""
    st = chrome.status()
    cfg = config.load(reload=True)
    return {
        "chrome_found": st["chrome_found"],
        "browser_running": st["connected"],
        "signed_in_as": _signed_in_as() if st["connected"] else None,
        "dry_run": cfg["safety"]["dry_run"],
        "profile": st.get("profile"),
    }


def _signed_in_as():
    """Ask the running browser who is signed in. None if nobody."""
    try:
        from core.browser import Session
        with Session() as s:
            return s.whoami()
    except Exception:
        return None


@app.post("/api/browser/start")
def browser_start():
    return chrome.start()


@app.get("/api/by-user")
def by_user():
    conn = store.connect()
    try:
        return store.by_user(conn)
    finally:
        conn.close()


@app.get("/api/reports")
def reports():
    conn = store.connect()
    try:
        return store.reports(conn)
    finally:
        conn.close()


@app.get("/api/scans")
def scans():
    conn = store.connect()
    try:
        return store.scans(conn)
    finally:
        conn.close()


@app.get("/api/stream")
def stream():
    def gen():
        while True:
            try:
                ev = _events.get(timeout=15)
                yield f"data: {json.dumps(ev)}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

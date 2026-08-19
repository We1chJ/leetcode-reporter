"""Local FastAPI app. Not exposed beyond localhost."""

import json
import queue
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


@app.get("/")
def index():
    return FileResponse(config.ROOT / "web" / "index.html")


app.mount("/static", StaticFiles(directory=config.ROOT / "web"), name="static")


@app.get("/api/config")
def get_config():
    cfg = config.load(reload=True)
    return {"safety": cfg["safety"], "scope": cfg["scope"],
            "detect": cfg["detect"], "running": _pipeline.running}


@app.post("/api/scan/{contest_slug}")
def start_scan(contest_slug: str):
    if _pipeline.running:
        return {"ok": False, "error": "a scan is already running"}
    slug = contest.normalise_slug(contest_slug)
    threading.Thread(target=_pipeline.scan, args=(slug,), daemon=True).start()
    return {"ok": True, "slug": slug}


@app.post("/api/stop")
def stop():
    _pipeline.stop()
    return {"ok": True}


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

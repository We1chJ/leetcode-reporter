"""Local FastAPI app. Not exposed beyond localhost."""

import json
import queue
import threading

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core import config
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
    threading.Thread(target=_pipeline.scan, args=(contest_slug,),
                     daemon=True).start()
    return {"ok": True}


@app.post("/api/stop")
def stop():
    _pipeline.stop()
    return {"ok": True}


@app.get("/api/offenders")
def offenders():
    conn = store.connect()
    try:
        return store.offenders(conn)
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

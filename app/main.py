"""
ICC AI Agent — FastAPI application.

Endpoints:
  GET  /                    Dashboard UI
  GET  /run/{id}            View a specific briefing run
  POST /api/run             Trigger a new ICC analysis run
  POST /api/signal          Submit a qualitative signal
  GET  /api/signals         List qualitative signals
  GET  /api/history         List all past runs
  GET  /api/run/{id}        Get a specific run (JSON)
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

_executor = ThreadPoolExecutor(max_workers=4)

from app.services.signal_collector import (
    add_qualitative_signal,
    collect_all_signals,
    get_qualitative_signals,
)
from app.services.ai_synthesizer import synthesize_icc_briefing
from app.services.briefing_store import get_all_runs, get_run, save_run

app = FastAPI(title="ICC AI Agent", version="1.0.0")

_dir = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(_dir, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(_dir, "static")), name="static")


# ---------------------------------------------------------------------------
# HTML Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    runs = get_all_runs()
    signals = get_qualitative_signals()
    latest = runs[0] if runs else None
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "runs": runs,
        "signals": signals,
        "latest": latest,
    })


@app.get("/run/{run_id}", response_class=HTMLResponse)
async def view_run(request: Request, run_id: int):
    run = get_run(run_id)
    if not run:
        return HTMLResponse("<h2>Run not found</h2>", status_code=404)
    return templates.TemplateResponse("briefing.html", {
        "request": request,
        "run": run,
    })


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.post("/api/run")
async def api_run(request: Request):
    """Trigger a full ICC analysis run."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    extra_context = body.get("extra_context", "").strip()
    trigger = body.get("trigger", "manual")
    trade_lanes = body.get("trade_lanes") or ["TPEB"]
    # Validate lanes
    from app.config import TRADE_LANES as _TL
    trade_lanes = [l for l in trade_lanes if l in _TL] or ["TPEB"]

    loop = asyncio.get_event_loop()

    # 1. Collect signals (runs in thread to avoid blocking event loop)
    signals = await loop.run_in_executor(
        _executor,
        lambda: collect_all_signals(extra_context=extra_context, trade_lanes=trade_lanes)
    )

    # 2. Synthesize with Claude (boto3 is sync — run in thread)
    briefing = await loop.run_in_executor(
        _executor,
        lambda: synthesize_icc_briefing(signals["signals"], extra_context=extra_context, trade_lanes=trade_lanes)
    )
    briefing["trigger"] = trigger

    # 3. Store
    record = save_run(briefing, signals["summary"])

    return {
        "status": "ok",
        "run_id": record["id"],
        "generated_at": record["generated_at"],
        "used_claude": record["used_claude"],
        "error": record.get("error"),
        "signal_summary": signals["summary"],
        "view_url": f"/run/{record['id']}",
    }


@app.post("/api/signal")
async def api_signal(request: Request):
    """Submit a new qualitative signal."""
    body = await request.json()
    author = body.get("author", "Anonymous").strip() or "Anonymous"
    text = body.get("text", "").strip()
    tags_raw = body.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)

    entry = add_qualitative_signal(author=author, text=text, tags=tags)
    return {"status": "ok", "signal": entry}


@app.get("/api/signals")
async def api_signals():
    return get_qualitative_signals()


@app.get("/api/history")
async def api_history():
    runs = get_all_runs()
    # Return without full content to keep response small
    return [
        {
            "id": r["id"],
            "generated_at": r["generated_at"],
            "trade_lane": r["trade_lane"],
            "used_claude": r["used_claude"],
            "trigger": r["trigger"],
            "signal_summary": r["signal_summary"],
        }
        for r in runs
    ]


@app.get("/api/run/{run_id}")
async def api_get_run(run_id: int):
    run = get_run(run_id)
    if not run:
        return JSONResponse({"error": "not found"}, status_code=404)
    return run

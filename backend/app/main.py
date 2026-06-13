"""Agentic AutoML — FastAPI backend.

Run:  uvicorn app.main:app --reload --port 8000   (from backend/)
"""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from .config import get_settings
from .orchestrator import execute_run, make_backend
from .schemas import (
    GenieSpace,
    PHASE_LABELS,
    PHASE_ORDER,
    PipelineRun,
    RunConfig,
    RunStatus,
    RunSummary,
)
from .store import store

settings = get_settings()
app = FastAPI(title="Agentic AutoML — Genie Orchestrator", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "workspace": settings.databricks_host or None,
        "phases": [{"key": p.value, "label": PHASE_LABELS[p]} for p in PHASE_ORDER],
    }


# ----------------------------------------------------------------- pipeline
@app.post("/api/runs", response_model=RunSummary, status_code=201)
async def create_run(config: RunConfig):
    if not config.tables:
        raise HTTPException(400, "At least one table is required.")
    if not config.models:
        raise HTTPException(400, "Select at least one model class.")
    run = PipelineRun(config=config)
    store.add(run)
    task = asyncio.create_task(execute_run(run, settings))
    store.set_task(run.id, task)
    return RunSummary.from_run(run)


@app.get("/api/runs", response_model=list[RunSummary])
async def list_runs():
    return [RunSummary.from_run(r) for r in store.all()]


@app.get("/api/runs/{run_id}", response_model=PipelineRun)
async def get_run(run_id: str):
    run = store.get(run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    return run


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    run = store.get(run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    if run.status != RunStatus.running:
        raise HTTPException(409, f"Run is {run.status.value}, not running.")
    store.cancel(run_id)
    return {"ok": True}


@app.get("/api/runs/{run_id}/events/stream")
async def stream_events(run_id: str, after: int = 0):
    """SSE stream of agent events. `after` replays history from that index
    first, so reconnects/late joins never miss events."""
    run = store.get(run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")

    async def generator():
        queue = store.subscribe(run_id)
        try:
            for event in run.events[after:]:
                yield {"event": "agent", "data": event.model_dump_json()}
            if run.status not in (RunStatus.pending, RunStatus.running):
                yield {"event": "done",
                       "data": json.dumps({"status": run.status.value})}
                return
            while True:
                event = await queue.get()
                if event is None:  # run finished
                    yield {"event": "done",
                           "data": json.dumps({"status": run.status.value})}
                    return
                yield {"event": "agent", "data": event.model_dump_json()}
        finally:
            store.unsubscribe(run_id, queue)

    return EventSourceResponse(generator())


# ------------------------------------------------------------ catalog/genie
@app.get("/api/catalog/tables")
async def list_tables():
    backend = make_backend(settings)
    return await backend.list_tables()


@app.get("/api/genie/spaces", response_model=list[GenieSpace])
async def list_spaces():
    backend = make_backend(settings)
    return await backend.list_spaces()


@app.get("/api/leaderboard")
async def leaderboard():
    """All trained models across runs, best-first — the MLflow-style board."""
    rows = []
    for run in store.all():
        for m in run.models:
            if m.mape is None:
                continue
            rows.append({
                "run_id": run.id,
                "run_name": run.config.name,
                "model": m.model,
                "mape": m.mape,
                "rmse": m.rmse,
                "mlflow_run_id": m.mlflow_run_id,
                "is_champion": bool(run.champion and run.champion.model == m.model),
                "registered_name": run.champion.registered_name
                if run.champion and run.champion.model == m.model else None,
            })
    return sorted(rows, key=lambda r: r["mape"])

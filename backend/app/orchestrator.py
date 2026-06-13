"""The agentic AutoML loop: drives the four phases against an AgentBackend
and broadcasts every AgentEvent to SSE subscribers."""
from __future__ import annotations

import asyncio
import traceback

from .agents.base import AgentBackend
from .config import Settings
from .schemas import (
    AgentEvent,
    EventType,
    PHASE_LABELS,
    PHASE_ORDER,
    Phase,
    PipelineRun,
    RunStatus,
)
from .store import store


def make_backend(settings: Settings) -> AgentBackend:
    if settings.demo_mode:
        from .agents.demo import DemoAgent
        return DemoAgent()
    from .agents.genie import GenieAgent
    return GenieAgent(settings)


async def execute_run(run: PipelineRun, settings: Settings) -> None:
    backend = make_backend(settings)
    run.status = RunStatus.running

    phase_fns = {
        Phase.curation: backend.curate,
        Phase.eda: backend.explore,
        Phase.automl: backend.train,
        Phase.champion: backend.select_champion,
    }

    try:
        for phase in PHASE_ORDER:
            run.phase = phase
            await store.publish(run.id, AgentEvent(
                phase=phase, type=EventType.phase_start,
                title=PHASE_LABELS[phase]))

            async for event in phase_fns[phase](run):
                await store.publish(run.id, event)

            run.phases_done.append(phase)
            await store.publish(run.id, AgentEvent(
                phase=phase, type=EventType.phase_end,
                title=f"{PHASE_LABELS[phase]} complete"))

        run.status = RunStatus.succeeded
        run.phase = None
    except asyncio.CancelledError:
        run.status = RunStatus.cancelled
        run.error = "Cancelled by user."
        await store.publish(run.id, AgentEvent(
            phase=run.phase or Phase.curation, type=EventType.log,
            title="Run cancelled", content="Pipeline stopped by user."))
    except Exception as exc:  # surface failures into the event stream
        run.status = RunStatus.failed
        run.error = str(exc)
        await store.publish(run.id, AgentEvent(
            phase=run.phase or Phase.curation, type=EventType.error,
            title="Pipeline failed",
            content=f"{exc}\n\n{traceback.format_exc(limit=4)}"))
    finally:
        await store.close_stream(run.id)

"""In-memory run store + per-run pub/sub event bus for SSE streaming."""
from __future__ import annotations

import asyncio
from typing import Optional

from .schemas import AgentEvent, GenieSpace, PipelineRun


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, PipelineRun] = {}
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self.spaces: dict[str, GenieSpace] = {}

    # -- runs ---------------------------------------------------------------
    def add(self, run: PipelineRun) -> None:
        self._runs[run.id] = run

    def get(self, run_id: str) -> Optional[PipelineRun]:
        return self._runs.get(run_id)

    def all(self) -> list[PipelineRun]:
        return sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)

    # -- background task tracking -------------------------------------------
    def set_task(self, run_id: str, task: asyncio.Task) -> None:
        self._tasks[run_id] = task

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    # -- event bus ------------------------------------------------------------
    async def publish(self, run_id: str, event: AgentEvent) -> None:
        run = self._runs.get(run_id)
        if run is not None:
            run.events.append(event)
        for queue in self._subscribers.get(run_id, set()):
            await queue.put(event)

    def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        self._subscribers.get(run_id, set()).discard(queue)

    async def close_stream(self, run_id: str) -> None:
        """Signal subscribers that the run finished (None sentinel)."""
        for queue in self._subscribers.get(run_id, set()):
            await queue.put(None)


store = RunStore()

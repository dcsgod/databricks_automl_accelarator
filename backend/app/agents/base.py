"""Agent backend interface.

The orchestrator is backend-agnostic: it narrates the four phases and asks
an AgentBackend to do the actual work. Two implementations ship:

- DemoAgent  : high-fidelity simulator (default) so the product runs anywhere.
- GenieAgent : drives a real Databricks workspace via the Genie Conversation
               API + Command Execution API.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from ..schemas import (
    AgentEvent,
    CatalogTable,
    Champion,
    EdaSummary,
    GenieSpace,
    ModelResult,
    PipelineRun,
)


class AgentBackend(ABC):
    """One pipeline run gets one backend instance (it may keep state, e.g. a
    Genie conversation id)."""

    @abstractmethod
    async def curate(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        """Phase 1: enrich metadata + provision a scoped Genie Space."""
        ...

    @abstractmethod
    async def explore(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        """Phase 2: automated time-series EDA. Must set run.eda before
        finishing."""
        ...

    @abstractmethod
    async def train(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        """Phase 3: feature engineering + multi-model Optuna training. Must
        populate run.models."""
        ...

    @abstractmethod
    async def select_champion(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        """Phase 4: pick + register the champion. Must set run.champion."""
        ...

    # -- catalog / spaces (used by the UI outside of pipeline runs) ----------
    @abstractmethod
    async def list_tables(self) -> list[CatalogTable]:
        ...

    @abstractmethod
    async def list_spaces(self) -> list[GenieSpace]:
        ...

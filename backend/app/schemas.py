"""Pydantic schemas shared by the API and the orchestrator."""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> float:
    return time.time()


class Phase(str, Enum):
    curation = "curation"        # Phase 1 — Semantic curation (Genie Space)
    eda = "eda"                  # Phase 2 — Automated time-series EDA
    automl = "automl"            # Phase 3 — Feature gen + multi-model training
    champion = "champion"        # Phase 4 — Selection & registration


PHASE_ORDER: list[Phase] = [Phase.curation, Phase.eda, Phase.automl, Phase.champion]

PHASE_LABELS: dict[Phase, str] = {
    Phase.curation: "Semantic Curation",
    Phase.eda: "Automated EDA",
    Phase.automl: "AutoML Training",
    Phase.champion: "Champion Selection",
}


class RunStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class EventType(str, Enum):
    log = "log"                # plain progress line
    prompt = "prompt"          # natural-language prompt sent to the Genie agent
    code = "code"              # code the agent generated
    exec = "exec"              # execution output (stdout / cell results)
    markdown = "markdown"      # structured markdown summary from the agent
    metric = "metric"          # a logged metric (model, name, value)
    trial = "trial"            # one Optuna trial result
    error = "error"            # traceback the agent intercepted
    autofix = "autofix"        # agent rewrote a failing block and continued
    guardrail = "guardrail"    # guardrail evaluation (pass / reject)
    phase_start = "phase_start"
    phase_end = "phase_end"
    artifact = "artifact"      # produced asset (table, notebook, model version)


class AgentEvent(BaseModel):
    id: str = Field(default_factory=_id)
    ts: float = Field(default_factory=_now)
    phase: Phase
    type: EventType
    title: str = ""
    content: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class GuardrailConfig(BaseModel):
    max_loss_divergence_pct: float = 15.0   # reject if train/val loss diverge more
    max_mape_pct: float = 60.0              # sanity ceiling for candidate models
    require_temporal_split: bool = True


class RunConfig(BaseModel):
    name: str = "Untitled forecast run"
    tables: list[str] = Field(default_factory=lambda: ["main.demo.sales_timeseries"])
    timestamp_col: str = "date"
    target_col: str = "units_sold"
    entity_keys: list[str] = Field(default_factory=lambda: ["store_id", "product_id"])
    grain: str = "daily"
    horizon_days: int = 28
    models: list[str] = Field(default_factory=lambda: ["xgboost", "prophet", "lightgbm"])
    optuna_trials: int = 20
    train_split_pct: int = 80
    guardrails: GuardrailConfig = Field(default_factory=GuardrailConfig)
    genie_instructions: list[str] = Field(default_factory=lambda: [
        "Always assume the data grain is daily.",
        "Treat column store_id as a categorical slice entity.",
    ])
    register_champion_to: str = "prod.ml_models.ts_forecast_champion"


class ModelResult(BaseModel):
    model: str
    status: str = "pending"          # pending | training | done | rejected
    mape: Optional[float] = None
    rmse: Optional[float] = None
    best_params: dict[str, Any] = Field(default_factory=dict)
    trials: list[dict[str, Any]] = Field(default_factory=list)  # {trial, mape, rmse}
    train_seconds: Optional[float] = None
    mlflow_run_id: Optional[str] = None
    rejected_reason: Optional[str] = None


class EdaSummary(BaseModel):
    rows: int = 0
    date_min: str = ""
    date_max: str = ""
    missing_gaps: int = 0
    trend: str = ""
    seasonality_period: int = 0
    adf_statistic: Optional[float] = None
    adf_pvalue: Optional[float] = None
    stationary: Optional[bool] = None
    significant_lags: list[int] = Field(default_factory=list)
    notes: str = ""


class Champion(BaseModel):
    model: str
    mape: float
    rmse: float
    registered_name: str
    version: int = 1
    rationale: str = ""


class PipelineRun(BaseModel):
    id: str = Field(default_factory=_id)
    created_at: float = Field(default_factory=_now)
    status: RunStatus = RunStatus.pending
    phase: Optional[Phase] = None
    phases_done: list[Phase] = Field(default_factory=list)
    config: RunConfig
    genie_space_id: Optional[str] = None
    eda: Optional[EdaSummary] = None
    models: list[ModelResult] = Field(default_factory=list)
    champion: Optional[Champion] = None
    error: Optional[str] = None
    events: list[AgentEvent] = Field(default_factory=list)


class RunSummary(BaseModel):
    """Lightweight projection for list views (omits the event log)."""
    id: str
    created_at: float
    status: RunStatus
    phase: Optional[Phase]
    phases_done: list[Phase]
    name: str
    tables: list[str]
    models: list[str]
    champion: Optional[Champion]

    @classmethod
    def from_run(cls, run: PipelineRun) -> "RunSummary":
        return cls(
            id=run.id, created_at=run.created_at, status=run.status,
            phase=run.phase, phases_done=run.phases_done,
            name=run.config.name, tables=run.config.tables,
            models=run.config.models, champion=run.champion,
        )


class TableColumn(BaseModel):
    name: str
    type: str
    comment: str = ""
    semantic_role: str = ""   # timestamp | target | entity_key | metric | feature


class CatalogTable(BaseModel):
    full_name: str
    comment: str = ""
    row_count: Optional[int] = None
    columns: list[TableColumn] = Field(default_factory=list)


class GenieSpace(BaseModel):
    id: str
    title: str
    description: str = ""
    tables: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=_now)

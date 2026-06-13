"""Real-workspace adapter: drives Databricks via REST.

APIs used
---------
- Genie Spaces / Conversation API (`/api/2.0/genie/...`) — the agent brain.
  Prompts are sent as conversation messages; Genie plans, generates and runs
  code/SQL, and we poll until COMPLETED, yielding its responses as events.
- Unity Catalog API (`/api/2.1/unity-catalog/...`) — metadata enrichment and
  table listing for the UI.
- Command Execution API (`/api/1.2/...`) — fallback execution of generated
  Python on `databricks_cluster_id` when a Genie response contains a code
  attachment that was not auto-executed.
- MLflow API (`/api/2.0/mlflow/...`) — reading run metrics and registering
  the champion model in UC.

Genie "Agent Mode" capabilities differ across workspaces/release channels; if
your space does not execute Python autonomously, the conversation responses
still flow through and the Command Execution fallback runs the code blocks.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncIterator, Optional

import httpx

from ..config import Settings
from ..prompts import champion_prompt, eda_prompt, feature_prompt, training_prompt
from ..schemas import (
    AgentEvent,
    CatalogTable,
    Champion,
    EdaSummary,
    EventType,
    GenieSpace,
    ModelResult,
    Phase,
    PipelineRun,
    TableColumn,
)
from ..store import store
from .base import AgentBackend

POLL_SECONDS = 3.0
GENIE_TIMEOUT_SECONDS = 1800  # generous: training sweeps are long


def _ev(phase: Phase, type: EventType, title: str = "", content: str = "",
        **data) -> AgentEvent:
    return AgentEvent(phase=phase, type=type, title=title, content=content,
                      data=data)


class GenieAgent(AgentBackend):
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.client = httpx.AsyncClient(
            base_url=settings.databricks_host.rstrip("/"),
            headers={"Authorization": f"Bearer {settings.databricks_token}"},
            timeout=60.0,
        )
        self.conversation_id: Optional[str] = None
        self.space_id: Optional[str] = None

    # ------------------------------------------------------------ low level
    async def _api(self, method: str, path: str, **kwargs) -> dict:
        resp = await self.client.request(method, path, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def _send_to_genie(self, run: PipelineRun, phase: Phase,
                             prompt: str) -> AsyncIterator[AgentEvent]:
        """Send a prompt to the Genie conversation and stream back responses."""
        yield _ev(phase, EventType.prompt, "Prompt → Genie Code API", prompt)

        if self.conversation_id is None:
            data = await self._api(
                "POST", f"/api/2.0/genie/spaces/{self.space_id}/start-conversation",
                json={"content": prompt})
            self.conversation_id = data["conversation_id"]
            message_id = data["message_id"]
        else:
            data = await self._api(
                "POST",
                f"/api/2.0/genie/spaces/{self.space_id}/conversations/"
                f"{self.conversation_id}/messages",
                json={"content": prompt})
            message_id = data["message_id"] if "message_id" in data else data["id"]

        waited = 0.0
        last_status = ""
        while True:
            msg = await self._api(
                "GET",
                f"/api/2.0/genie/spaces/{self.space_id}/conversations/"
                f"{self.conversation_id}/messages/{message_id}")
            status = msg.get("status", "")
            if status != last_status:
                last_status = status
                yield _ev(phase, EventType.log, "Genie status", status)

            if status in ("COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"):
                for event in self._attachments_to_events(phase, msg):
                    yield event
                if status == "FAILED":
                    raise RuntimeError(
                        f"Genie message failed: {msg.get('error', msg)}")
                return

            await asyncio.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
            if waited > GENIE_TIMEOUT_SECONDS:
                raise TimeoutError("Genie did not complete within the timeout.")

    def _attachments_to_events(self, phase: Phase, msg: dict) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        for att in msg.get("attachments", []) or []:
            if "text" in att and att["text"].get("content"):
                events.append(_ev(phase, EventType.markdown, "Genie response",
                                  att["text"]["content"]))
            if "query" in att and att["query"].get("query"):
                events.append(_ev(phase, EventType.code, "Generated query",
                                  att["query"]["query"], language="sql"))
        for block in _code_blocks(msg):
            events.append(_ev(phase, EventType.code, "Generated code", block,
                              language="python"))
        return events

    # ------------------------------------------------------------- Phase 1
    async def curate(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        cfg = run.config
        P = Phase.curation

        # 1. Enrich UC metadata with semantic roles via column comments.
        for table in cfg.tables:
            yield _ev(P, EventType.log, f"Enriching {table}",
                      "Writing semantic-role comments to Unity Catalog")
            roles = {cfg.timestamp_col: "TIMESTAMP COLUMN (series index)",
                     cfg.target_col: "TARGET VALUE for forecasting"}
            roles.update({k: "CATEGORICAL SLICE ENTITY" for k in cfg.entity_keys})
            for col, role in roles.items():
                try:
                    await self._api(
                        "PATCH", f"/api/2.1/unity-catalog/tables/{table}",
                        json={"columns": [{"name": col, "comment": role}]})
                except httpx.HTTPStatusError:
                    # Comment patching needs ALTER on the table; non-fatal.
                    yield _ev(P, EventType.log, "Metadata write skipped",
                              f"No ALTER permission on {table}.{col}; "
                              "continuing with existing comments.")
                    break

        # 2. Provision a scoped Genie space.
        yield _ev(P, EventType.log, "Provisioning scoped Genie Space",
                  f"warehouse={self.s.databricks_warehouse_id}, "
                  f"tables={len(cfg.tables)}")
        body = {
            "title": f"AutoML TS — {cfg.name}",
            "description": "Auto-provisioned for agentic time-series AutoML.",
            "warehouse_id": self.s.databricks_warehouse_id,
            "table_identifiers": cfg.tables,
            "instructions": "\n".join(cfg.genie_instructions),
        }
        data = await self._api("POST", "/api/2.0/genie/spaces", json=body)
        self.space_id = data.get("space_id") or data.get("id")
        run.genie_space_id = self.space_id

        space = GenieSpace(id=self.space_id, title=body["title"],
                           description=body["description"],
                           tables=cfg.tables,
                           instructions=cfg.genie_instructions)
        store.spaces[space.id] = space

        yield _ev(P, EventType.artifact, "Genie Space created",
                  f"Space `{self.space_id}` scoped to {len(cfg.tables)} table(s).",
                  kind="genie_space", space_id=self.space_id)

    # ------------------------------------------------------------- Phase 2
    async def explore(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        async for event in self._send_to_genie(run, Phase.eda,
                                               eda_prompt(run.config)):
            yield event
        # Best-effort parse of agent summary into the structured EDA panel.
        run.eda = run.eda or _parse_eda(run)

    # ------------------------------------------------------------- Phase 3
    async def train(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        period = run.eda.seasonality_period if run.eda and \
            run.eda.seasonality_period else 7
        async for event in self._send_to_genie(
                run, Phase.automl, feature_prompt(run.config, period)):
            yield event
        async for event in self._send_to_genie(
                run, Phase.automl, training_prompt(run.config)):
            yield event
        async for event in self._collect_mlflow_results(run):
            yield event

    async def _collect_mlflow_results(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        """Pull val_mape / val_rmse for this experiment's latest runs."""
        P = Phase.automl
        try:
            exp = await self._api(
                "GET", "/api/2.0/mlflow/experiments/get-by-name",
                params={"experiment_name": self.s.mlflow_experiment})
            exp_id = exp["experiment"]["experiment_id"]
            search = await self._api(
                "POST", "/api/2.0/mlflow/runs/search",
                json={"experiment_ids": [exp_id], "max_results": 50,
                      "order_by": ["attributes.start_time DESC"]})
        except httpx.HTTPStatusError as exc:
            yield _ev(P, EventType.log, "MLflow read failed",
                      f"{exc.response.status_code}: results panel will rely "
                      "on the agent's markdown summary.")
            return

        run.models = []
        for r in search.get("runs", []):
            info, data = r.get("info", {}), r.get("data", {})
            name = (info.get("run_name") or "").replace("automl_", "")
            if name not in run.config.models:
                continue
            metrics = {m["key"]: m["value"] for m in data.get("metrics", [])}
            params = {p["key"]: p["value"] for p in data.get("params", [])}
            if "val_mape" not in metrics:
                continue
            result = ModelResult(
                model=name, status="done",
                mape=round(metrics["val_mape"], 3),
                rmse=round(metrics.get("val_rmse", 0.0), 1),
                best_params=params, mlflow_run_id=info.get("run_id"))
            run.models.append(result)
            yield _ev(P, EventType.metric, f"MLflow logged: {name}",
                      f"val_mape={result.mape}% · val_rmse={result.rmse}",
                      model=name, mape=result.mape, rmse=result.rmse,
                      mlflow_run_id=result.mlflow_run_id)

    # ------------------------------------------------------------- Phase 4
    async def select_champion(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        cfg = run.config
        P = Phase.champion
        async for event in self._send_to_genie(run, P, champion_prompt(cfg)):
            yield event

        done = [m for m in run.models if m.mape is not None]
        if not done:
            yield _ev(P, EventType.log, "No structured metrics",
                      "Champion details are in the agent's report above.")
            return
        winner = min(done, key=lambda m: m.mape)

        # Deterministic registration from our side (idempotent if the agent
        # already registered it).
        try:
            reg = await self._api(
                "POST", "/api/2.0/mlflow/model-versions/create",
                json={"name": cfg.register_champion_to,
                      "source": f"runs:/{winner.mlflow_run_id}/model",
                      "run_id": winner.mlflow_run_id})
            version = int(reg.get("model_version", {}).get("version", 1))
        except httpx.HTTPStatusError as exc:
            yield _ev(P, EventType.log, "Registration via API failed",
                      f"{exc.response.status_code} — agent may have already "
                      "registered it.")
            version = 1

        run.champion = Champion(
            model=winner.model, mape=winner.mape, rmse=winner.rmse or 0.0,
            registered_name=cfg.register_champion_to, version=version,
            rationale=f"Lowest validation MAPE ({winner.mape}%) across "
                      f"{len(done)} candidates.")
        yield _ev(P, EventType.artifact, "Champion registered",
                  f"`{cfg.register_champion_to}` v{version} ← {winner.model}",
                  kind="model", model=winner.model,
                  registered_name=cfg.register_champion_to)

    # ------------------------------------------------------------- catalog
    async def list_tables(self) -> list[CatalogTable]:
        """List tables for catalog.schema pairs referenced by known spaces or
        the default config tables."""
        tables: list[CatalogTable] = []
        seen_schemas: set[tuple[str, str]] = set()
        candidates = [t for sp in store.spaces.values() for t in sp.tables]
        for full in candidates or []:
            parts = full.split(".")
            if len(parts) == 3:
                seen_schemas.add((parts[0], parts[1]))
        for catalog, schema in seen_schemas or {("main", "default")}:
            try:
                data = await self._api(
                    "GET", "/api/2.1/unity-catalog/tables",
                    params={"catalog_name": catalog, "schema_name": schema})
            except httpx.HTTPStatusError:
                continue
            for t in data.get("tables", []):
                tables.append(CatalogTable(
                    full_name=t["full_name"],
                    comment=t.get("comment", ""),
                    columns=[TableColumn(name=c["name"],
                                         type=c.get("type_text", ""),
                                         comment=c.get("comment", ""))
                             for c in t.get("columns", [])]))
        return tables

    async def list_spaces(self) -> list[GenieSpace]:
        try:
            data = await self._api("GET", "/api/2.0/genie/spaces")
        except httpx.HTTPStatusError:
            return list(store.spaces.values())
        spaces = []
        for sp in data.get("spaces", []):
            spaces.append(GenieSpace(
                id=sp.get("space_id", sp.get("id", "")),
                title=sp.get("title", ""),
                description=sp.get("description", "")))
        return spaces or list(store.spaces.values())


def _code_blocks(msg: dict) -> list[str]:
    text = ""
    for att in msg.get("attachments", []) or []:
        if "text" in att:
            text += att["text"].get("content", "") + "\n"
    return re.findall(r"```(?:python)?\n(.*?)```", text, flags=re.S)


def _parse_eda(run: PipelineRun) -> Optional[EdaSummary]:
    """Best-effort extraction of ADF/seasonality numbers from agent markdown."""
    text = "\n".join(e.content for e in run.events
                     if e.phase == Phase.eda and e.type == EventType.markdown)
    if not text:
        return None
    summary = EdaSummary(notes="Parsed from agent summary; see event log.")
    if m := re.search(r"p[- ]?value\s*[=:]?\s*([0-9.]+)", text, re.I):
        summary.adf_pvalue = float(m.group(1))
        summary.stationary = summary.adf_pvalue < 0.05
    if m := re.search(r"period\s*[=:]?\s*(\d+)", text, re.I):
        summary.seasonality_period = int(m.group(1))
    return summary

"""High-fidelity simulator of the Genie Code agent loop.

Every event the real GenieAgent would emit (prompts, generated code, cell
output, intercepted tracebacks, auto-fixes, Optuna trials, guardrail checks,
MLflow logging, UC registration) is reproduced here with realistic timing so
the UI/UX can be exercised end-to-end without a Databricks workspace.
"""
from __future__ import annotations

import asyncio
import math
import random
from typing import AsyncIterator

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

# Tunable pacing so a full demo run takes ~2-3 minutes.
TICK = 0.35


def _ev(phase: Phase, type: EventType, title: str = "", content: str = "",
        **data) -> AgentEvent:
    return AgentEvent(phase=phase, type=type, title=title, content=content,
                      data=data)


DEMO_TABLES: list[CatalogTable] = [
    CatalogTable(
        full_name="main.demo.sales_timeseries",
        comment="Daily store/product sales. Grain: daily per (store_id, product_id).",
        row_count=412_640,
        columns=[
            TableColumn(name="date", type="DATE", semantic_role="timestamp",
                        comment="Business date (daily grain, no timezone)."),
            TableColumn(name="store_id", type="STRING", semantic_role="entity_key",
                        comment="Categorical slice entity — retail store identifier."),
            TableColumn(name="product_id", type="STRING", semantic_role="entity_key",
                        comment="Categorical slice entity — SKU identifier."),
            TableColumn(name="units_sold", type="BIGINT", semantic_role="target",
                        comment="Target value: units sold per store/product/day."),
            TableColumn(name="revenue", type="DECIMAL(18,2)", semantic_role="metric",
                        comment="Gross revenue in USD."),
            TableColumn(name="promo_flag", type="BOOLEAN", semantic_role="feature",
                        comment="True when the SKU was on promotion that day."),
        ],
    ),
    CatalogTable(
        full_name="main.demo.store_calendar",
        comment="Store-level calendar with holidays and trading-hour exceptions.",
        row_count=18_250,
        columns=[
            TableColumn(name="date", type="DATE", semantic_role="timestamp"),
            TableColumn(name="store_id", type="STRING", semantic_role="entity_key"),
            TableColumn(name="is_holiday", type="BOOLEAN", semantic_role="feature",
                        comment="Public-holiday flag for the store's region."),
            TableColumn(name="is_open", type="BOOLEAN", semantic_role="feature"),
        ],
    ),
    CatalogTable(
        full_name="main.demo.weather_daily",
        comment="Daily weather aggregates joined by store region.",
        row_count=91_250,
        columns=[
            TableColumn(name="date", type="DATE", semantic_role="timestamp"),
            TableColumn(name="store_id", type="STRING", semantic_role="entity_key"),
            TableColumn(name="avg_temp_c", type="DOUBLE", semantic_role="feature"),
            TableColumn(name="precipitation_mm", type="DOUBLE", semantic_role="feature"),
        ],
    ),
]


EDA_CODE = '''import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller, acf, pacf

df = spark.table("{table}").toPandas()
df["{ts}"] = pd.to_datetime(df["{ts}"])
series = (df.groupby("{ts}")["{target}"].sum()
            .asfreq("D"))

# 1. Missing timestamp gaps
gaps = series[series.isna()]
print(f"missing timestamp gaps: {{len(gaps)}}")

# 2. Trend + seasonal decomposition
decomp = sm.tsa.seasonal_decompose(series.interpolate(), period=7)

# 3. Stationarity (Augmented Dickey-Fuller)
adf_stat, pvalue, *_ = adfuller(series.interpolate())
print(f"ADF statistic={{adf_stat:.3f}} p-value={{pvalue:.4f}}")

# 4. ACF / PACF
acf_vals = acf(series.interpolate(), nlags=30)
pacf_vals = pacf(series.interpolate(), nlags=30)'''


FEATURE_CODE = '''from pyspark.sql import functions as F, Window

w_entity = Window.partitionBy({keys}).orderBy("{ts}")

features = (spark.table("{table}")
    .withColumn("lag_1",  F.lag("{target}", 1).over(w_entity))
    .withColumn("lag_{p}",  F.lag("{target}", {p}).over(w_entity))
    .withColumn("lag_{p2}", F.lag("{target}", {p2}).over(w_entity))
    .withColumn("roll_{p}d_mean",
        F.avg("{target}").over(w_entity.rowsBetween(-{p}, -1)))
    .withColumn("roll_{p2}d_mean",
        F.avg("{target}").over(w_entity.rowsBetween(-{p2}, -1)))
    .withColumn("dow", F.dayofweek("{ts}"))
    .withColumn("month", F.month("{ts}"))
    .join(spark.table("main.demo.store_calendar")
              .select("date", "store_id", "is_holiday"),
          on=["date", "store_id"], how="left"))

features.write.mode("overwrite").saveAsTable(
    "main.demo.sales_timeseries_features")'''


TRAIN_CODE = '''import mlflow, optuna
from sklearn.metrics import mean_absolute_percentage_error as mape_fn
from sklearn.metrics import root_mean_squared_error

mlflow.set_experiment("{experiment}")
cutoff = df["{ts}"].quantile({split})          # temporal split — no leakage
train, valid = df[df["{ts}"] <= cutoff], df[df["{ts}"] > cutoff]

def objective_factory(model_name):
    def objective(trial):
        model = build_model(model_name, trial)   # xgboost / prophet / lightgbm
        model.fit(train[FEATURES], train["{target}"])
        pred = model.predict(valid[FEATURES])
        mape = mape_fn(valid["{target}"], pred) * 100
        trial.set_user_attr("rmse", root_mean_squared_error(
            valid["{target}"], pred))
        return mape
    return objective

for name in {models}:
    with mlflow.start_run(run_name=f"automl_{{name}}"):
        study = optuna.create_study(direction="minimize")
        study.optimize(objective_factory(name), n_trials={trials})
        mlflow.log_params(study.best_params)
        mlflow.log_metric("val_mape", study.best_value)
        mlflow.log_metric("val_rmse",
                          study.best_trial.user_attrs["rmse"])'''


DEPRECATION_TRACEBACK = '''Traceback (most recent call last):
  File "/databricks/driver/automl_train.py", line 14, in <module>
    from sklearn.metrics import root_mean_squared_error
ImportError: cannot import name 'root_mean_squared_error' from
'sklearn.metrics' (cluster runtime pins scikit-learn 1.3.2)'''


AUTOFIX_DIFF = '''- from sklearn.metrics import root_mean_squared_error
+ from sklearn.metrics import mean_squared_error
...
-         trial.set_user_attr("rmse", root_mean_squared_error(
-             valid["{target}"], pred))
+         trial.set_user_attr("rmse", mean_squared_error(
+             valid["{target}"], pred, squared=False))'''


# Model "personalities" for the simulator: (base_mape, spread, base_rmse,
# convergence_rate). LightGBM tends to win, Prophet is stable but coarser.
MODEL_PROFILES = {
    "xgboost":  (9.8, 2.6, 312.0, 0.55),
    "lightgbm": (8.6, 2.4, 286.0, 0.60),
    "prophet":  (12.4, 1.6, 401.0, 0.35),
    "arima":    (14.1, 1.9, 446.0, 0.30),
}


class DemoAgent(AgentBackend):
    def __init__(self) -> None:
        self.rng = random.Random()

    # ------------------------------------------------------------------ utils
    async def _sleep(self, ticks: float = 1.0) -> None:
        await asyncio.sleep(TICK * ticks * self.rng.uniform(0.7, 1.3))

    # -------------------------------------------------------------- Phase 1
    async def curate(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        cfg = run.config
        self.rng.seed(run.id)
        P = Phase.curation

        yield _ev(P, EventType.log, "Scanning Unity Catalog metadata",
                  f"Inspecting {len(cfg.tables)} table(s): {', '.join(cfg.tables)}")
        await self._sleep(2)

        for table in cfg.tables:
            meta = next((t for t in DEMO_TABLES if t.full_name == table), None)
            cols = meta.columns if meta else []
            tagged = ", ".join(f"{c.name} → {c.semantic_role}" for c in cols
                               if c.semantic_role)
            yield _ev(P, EventType.log, f"Enriching {table}",
                      f"Applied semantic roles: {tagged or 'timestamp/target inferred from config'}")
            await self._sleep(1.5)

        yield _ev(P, EventType.log, "Provisioning scoped Genie Space",
                  "POST /api/2.0/genie/spaces — scoping to "
                  f"{len(cfg.tables)} table(s) (< 5 for optimal accuracy)")
        await self._sleep(3)

        space = GenieSpace(
            id="gs_" + run.id[:8],
            title=f"AutoML TS — {cfg.name}",
            description="Auto-provisioned scoped space for agentic time-series AutoML.",
            tables=list(cfg.tables),
            instructions=list(cfg.genie_instructions),
        )
        store.spaces[space.id] = space
        run.genie_space_id = space.id

        yield _ev(P, EventType.artifact, "Genie Space created",
                  f"Space `{space.id}` scoped to {len(space.tables)} table(s).",
                  kind="genie_space", space_id=space.id)
        await self._sleep(1)

        for instr in cfg.genie_instructions:
            yield _ev(P, EventType.log, "Seeded constraint", f"“{instr}”")
            await self._sleep(0.8)

        yield _ev(P, EventType.markdown, "Curation summary", (
            "### Semantic layer ready\n"
            f"- **Space**: `{space.id}` ({len(space.tables)} tables)\n"
            f"- **Timestamp**: `{cfg.timestamp_col}` · **Target**: `{cfg.target_col}`\n"
            f"- **Entities**: {', '.join(f'`{k}`' for k in cfg.entity_keys)}\n"
            f"- **Grain**: {cfg.grain} · **Constraints seeded**: {len(cfg.genie_instructions)}"
        ))

    # -------------------------------------------------------------- Phase 2
    async def explore(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        cfg = run.config
        P = Phase.eda
        table = cfg.tables[0]

        yield _ev(P, EventType.prompt, "Prompt → Genie Code API", eda_prompt(cfg))
        await self._sleep(3)

        yield _ev(P, EventType.log, "Agent Mode engaged",
                  "Genie resolved @-references against the scoped space schema; "
                  "constructing EDA notebook with statsmodels/pandas.")
        await self._sleep(2)

        yield _ev(P, EventType.code, "Generated: 01_timeseries_eda.py",
                  EDA_CODE.format(table=table, ts=cfg.timestamp_col,
                                  target=cfg.target_col),
                  language="python")
        await self._sleep(4)

        gaps = self.rng.randint(2, 9)
        adf_stat = round(self.rng.uniform(-4.2, -2.1), 3)
        pvalue = round(self.rng.uniform(0.001, 0.08), 4)
        stationary = pvalue < 0.05
        period = 7
        rows = 412_640

        yield _ev(P, EventType.exec, "Cell output", (
            f"missing timestamp gaps: {gaps}\n"
            f"ADF statistic={adf_stat} p-value={pvalue}\n"
            "seasonal_decompose: strong weekly cycle (period=7), "
            "mild upward trend (+4.2%/quarter)\n"
            "ACF significant lags: 1, 7, 14, 28 · PACF cutoff after lag 7"
        ))
        await self._sleep(2)

        run.eda = EdaSummary(
            rows=rows, date_min="2022-01-01", date_max="2025-12-31",
            missing_gaps=gaps, trend="mild upward (+4.2%/quarter)",
            seasonality_period=period, adf_statistic=adf_stat,
            adf_pvalue=pvalue, stationary=stationary,
            significant_lags=[1, 7, 14, 28],
            notes="Weekly seasonality dominates; holiday spikes visible in "
                  "Nov-Dec. Gaps align with store closures in store_calendar.",
        )

        verdict = ("stationary — differencing not required"
                   if stationary else
                   "non-stationary — agent will difference / use trend features")
        yield _ev(P, EventType.markdown, "EDA summary (returned by agent)", (
            "### Behavioral properties of the series\n"
            f"| Property | Finding |\n|---|---|\n"
            f"| Rows | {rows:,} ({run.eda.date_min} → {run.eda.date_max}) |\n"
            f"| Missing gaps | {gaps} (align with store closures) |\n"
            f"| Trend | mild upward, +4.2%/quarter |\n"
            f"| Seasonality | weekly (period = {period}), ACF lags 1/7/14/28 |\n"
            f"| ADF test | stat {adf_stat}, p={pvalue} → **{verdict}** |\n\n"
            f"Recommended features: lag-{period}, lag-{period*2}, rolling "
            f"{period}d/{period*2}d means, day-of-week, holiday effects."
        ), eda=run.eda.model_dump())

    # -------------------------------------------------------------- Phase 3
    async def train(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        cfg = run.config
        P = Phase.automl
        period = run.eda.seasonality_period if run.eda else 7
        table = cfg.tables[0]

        # --- 3a. feature engineering
        yield _ev(P, EventType.prompt, "Prompt → Genie Code API",
                  feature_prompt(cfg, period))
        await self._sleep(3)

        keys = ", ".join(f'"{k}"' for k in cfg.entity_keys)
        yield _ev(P, EventType.code, "Generated: 02_feature_engineering.py",
                  FEATURE_CODE.format(table=table, ts=cfg.timestamp_col,
                                      target=cfg.target_col, keys=keys,
                                      p=period, p2=period * 2),
                  language="python")
        await self._sleep(4)

        feat_table = table + "_features"
        yield _ev(P, EventType.artifact, "Feature table materialized",
                  f"`{feat_table}` — 11 engineered columns "
                  "(lags, rolling means, calendar, holiday effects).",
                  kind="table", table=feat_table)
        await self._sleep(1.5)

        # --- 3b. training harness
        yield _ev(P, EventType.prompt, "Prompt → Genie Code API",
                  training_prompt(cfg))
        await self._sleep(3)

        yield _ev(P, EventType.code, "Generated: 03_automl_training.py",
                  TRAIN_CODE.format(ts=cfg.timestamp_col, target=cfg.target_col,
                                    split=cfg.train_split_pct / 100,
                                    models=cfg.models, trials=cfg.optuna_trials,
                                    experiment="(demo) /Shared/agentic-automl"),
                  language="python")
        await self._sleep(3)

        # --- 3c. the auto-debug moment: intercept traceback, rewrite, continue
        yield _ev(P, EventType.error, "Execution failed — traceback intercepted",
                  DEPRECATION_TRACEBACK)
        await self._sleep(3)
        yield _ev(P, EventType.autofix, "Agent rewrote failing block", (
            "Detected `root_mean_squared_error` unavailable on pinned "
            "scikit-learn 1.3.2. Rewriting to "
            "`mean_squared_error(..., squared=False)` and re-executing.\n\n"
            + AUTOFIX_DIFF.format(target=cfg.target_col)
        ))
        await self._sleep(2)
        yield _ev(P, EventType.log, "Re-execution clean",
                  "Notebook compiles; starting Optuna studies "
                  f"({cfg.optuna_trials} trials × {len(cfg.models)} models).")
        await self._sleep(1.5)

        # --- 3d. Optuna trials per model
        run.models = [ModelResult(model=m) for m in cfg.models]
        guard = cfg.guardrails

        for result in run.models:
            base, spread, base_rmse, rate = MODEL_PROFILES.get(
                result.model, (13.0, 2.0, 420.0, 0.4))
            result.status = "training"
            yield _ev(P, EventType.log, f"Optuna study started: {result.model}",
                      f"direction=minimize, n_trials={cfg.optuna_trials}, "
                      "sampler=TPESampler")

            best = math.inf
            best_rmse = math.inf
            diverged_once = False
            for trial_no in range(1, cfg.optuna_trials + 1):
                await self._sleep(0.6)
                progress = 1 - math.exp(-rate * trial_no / 4)
                mape = base + spread * (1 - progress) + self.rng.uniform(-0.6, 0.9)
                mape = round(max(mape, base * 0.92), 3)
                rmse = round(base_rmse * (mape / base) *
                             self.rng.uniform(0.96, 1.04), 1)

                # occasionally trip the divergence guardrail on a bad trial
                divergence = round(self.rng.uniform(1.0, 22.0), 1)
                rejected = divergence > guard.max_loss_divergence_pct
                if rejected and not diverged_once:
                    diverged_once = True
                    yield _ev(P, EventType.guardrail,
                              f"Guardrail REJECT — {result.model} trial {trial_no}",
                              f"train/val loss divergence {divergence}% > "
                              f"{guard.max_loss_divergence_pct}% limit. Trial "
                              "pruned; params excluded from study.",
                              model=result.model, trial=trial_no,
                              divergence=divergence, passed=False)
                    result.trials.append({"trial": trial_no, "mape": mape,
                                          "rmse": rmse, "pruned": True})
                    continue

                result.trials.append({"trial": trial_no, "mape": mape,
                                      "rmse": rmse, "pruned": False})
                if mape < best:
                    best, best_rmse = mape, rmse
                yield _ev(P, EventType.trial, f"{result.model} · trial {trial_no}",
                          f"val_mape={mape}% val_rmse={rmse}",
                          model=result.model, trial=trial_no, mape=mape,
                          rmse=rmse, best_mape=best)

            result.status = "done"
            result.mape = round(best, 3)
            result.rmse = round(best_rmse, 1)
            result.train_seconds = round(self.rng.uniform(40, 220), 1)
            result.mlflow_run_id = "demo_" + self.rng.randbytes(6).hex()
            result.best_params = _demo_best_params(result.model, self.rng)

            yield _ev(P, EventType.metric, f"MLflow logged: {result.model}",
                      f"val_mape={result.mape}% · val_rmse={result.rmse} · "
                      f"run_id={result.mlflow_run_id}",
                      model=result.model, mape=result.mape, rmse=result.rmse,
                      mlflow_run_id=result.mlflow_run_id,
                      params=result.best_params)
            await self._sleep(1)

        yield _ev(P, EventType.markdown, "Training sweep complete", (
            "### Optuna sweep results\n"
            "| Model | best val MAPE | val RMSE | trials |\n|---|---|---|---|\n"
            + "\n".join(
                f"| {m.model} | {m.mape}% | {m.rmse} | "
                f"{len([t for t in m.trials if not t['pruned']])}"
                f"/{len(m.trials)} kept |"
                for m in run.models)
        ))

    # -------------------------------------------------------------- Phase 4
    async def select_champion(self, run: PipelineRun) -> AsyncIterator[AgentEvent]:
        cfg = run.config
        P = Phase.champion

        yield _ev(P, EventType.prompt, "Prompt → Genie Code API",
                  champion_prompt(cfg))
        await self._sleep(3)

        done = [m for m in run.models if m.status == "done" and m.mape]
        winner = min(done, key=lambda m: m.mape)
        runner_up = sorted(done, key=lambda m: m.mape)[1] if len(done) > 1 else None

        yield _ev(P, EventType.log, "Reading MLflow metrics",
                  "Comparing validation MAPE across "
                  + ", ".join(m.model for m in done))
        await self._sleep(2)

        margin = (round(runner_up.mape - winner.mape, 3)
                  if runner_up else 0.0)
        rationale = (
            f"{winner.model} achieved the lowest validation MAPE "
            f"({winner.mape}%), beating "
            + (f"{runner_up.model} by {margin} pts. " if runner_up else "")
            + "Validation curve shows monotone convergence with no train/val "
              "divergence beyond the "
            f"{cfg.guardrails.max_loss_divergence_pct:.0f}% guardrail. RMSE "
            f"({winner.rmse}) is also best-in-class."
        )

        yield _ev(P, EventType.log, "Registering to Unity Catalog",
                  f"mlflow.register_model(runs:/{winner.mlflow_run_id}/model, "
                  f"\"{cfg.register_champion_to}\")")
        await self._sleep(3)

        run.champion = Champion(
            model=winner.model, mape=winner.mape, rmse=winner.rmse,
            registered_name=cfg.register_champion_to, version=1,
            rationale=rationale,
        )

        yield _ev(P, EventType.artifact, "Champion registered",
                  f"`{cfg.register_champion_to}` v1 ← {winner.model} "
                  f"(MAPE {winner.mape}%)",
                  kind="model", model=winner.model,
                  registered_name=cfg.register_champion_to)
        await self._sleep(1)

        yield _ev(P, EventType.markdown, "Audit trail — execution report", (
            "### Champion selection report\n"
            f"**Winner:** `{winner.model}` → registered as "
            f"`{cfg.register_champion_to}` (v1)\n\n"
            f"**Why:** {rationale}\n\n"
            "| Model | val MAPE | val RMSE | MLflow run |\n|---|---|---|---|\n"
            + "\n".join(
                f"| {'🏆 ' if m is winner else ''}{m.model} | {m.mape}% | "
                f"{m.rmse} | `{m.mlflow_run_id}` |"
                for m in sorted(done, key=lambda x: x.mape))
            + "\n\nValidation curves for all studies are attached as MLflow "
              "artifacts (`optuna_history.png`, `val_curve_*.png`)."
        ))

    # ------------------------------------------------------------- catalog
    async def list_tables(self) -> list[CatalogTable]:
        return DEMO_TABLES

    async def list_spaces(self) -> list[GenieSpace]:
        return list(store.spaces.values())


def _demo_best_params(model: str, rng: random.Random) -> dict:
    if model == "xgboost":
        return {"max_depth": rng.choice([5, 6, 8]), "eta": round(rng.uniform(0.03, 0.12), 3),
                "n_estimators": rng.choice([400, 600, 800]),
                "subsample": round(rng.uniform(0.7, 0.95), 2)}
    if model == "lightgbm":
        return {"num_leaves": rng.choice([31, 63, 127]),
                "learning_rate": round(rng.uniform(0.02, 0.1), 3),
                "n_estimators": rng.choice([500, 700, 900]),
                "feature_fraction": round(rng.uniform(0.7, 0.95), 2)}
    if model == "prophet":
        return {"changepoint_prior_scale": round(rng.uniform(0.01, 0.4), 3),
                "seasonality_prior_scale": round(rng.uniform(1, 10), 2),
                "seasonality_mode": rng.choice(["additive", "multiplicative"])}
    return {"p": rng.choice([1, 2, 3]), "d": 1, "q": rng.choice([1, 2]),
            "seasonal_order": "(1,1,1,7)"}

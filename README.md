# Agentic AutoML — Genie Orchestrator

A custom "AutoML" ecosystem built on Databricks **Genie Spaces** (context layer)
and the **Genie Code API in Agent Mode** (autonomous ML engineer). Instead of a
rigid black-box AutoML library, an agentic loop plans, writes code, runs
notebooks, tests multiple time-series models, and logs everything to MLflow.

```
[Unity Catalog Data] ➡ [Genie Space (Context Layer)] ➡ [Genie Code API (Agent)] ➡ [Auto-EDA / Optuna / MLflow]
```

## The 4-phase agentic loop

| Phase | What happens |
|---|---|
| 1 · **Semantic Curation** | Enriches UC column metadata with semantic roles (timestamp / target / entity key), provisions a *scoped* Genie Space (≤ 5 tables), seeds custom constraints ("data grain is daily", …) |
| 2 · **Automated EDA** | Natural-language prompt → agent generates & runs a statsmodels notebook: gap detection, trend/seasonality decomposition, ADF stationarity test, ACF/PACF |
| 3 · **AutoML Training** | Agent engineers lag/rolling/holiday features from EDA findings, builds a multi-model harness (XGBoost / LightGBM / Prophet / ARIMA), optimizes with Optuna, enforces guardrails (train/val divergence limit), intercepts its own tracebacks and auto-fixes failing code, logs to MLflow |
| 4 · **Champion Selection** | Compares validation MAPE across candidates, registers the winner to Unity Catalog (`prod.ml_models.ts_forecast_champion`), returns an audit-trail report |

## Project layout

```
backend/                  FastAPI orchestrator
  app/main.py             REST + SSE API
  app/orchestrator.py     phase state machine
  app/prompts.py          the @-operator prompt templates per phase
  app/agents/demo.py      high-fidelity simulator (default)
  app/agents/genie.py     real-workspace adapter (Genie + UC + MLflow REST)
frontend/                 React + Vite + TypeScript UI
  src/components/         run wizard, live agent console, phase stepper,
                          EDA panel, leaderboard + sparklines, champion report
```

## Quick start (demo mode — no workspace needed)

```powershell
# backend (terminal 1)
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# frontend (terminal 2)
cd frontend
npm install
npm run dev          # → http://localhost:5173
```

Click **＋ New AutoML Run** → configure tables/models/guardrails → **Launch**.
Watch the agent console stream prompts, generated code, an intercepted
deprecation traceback + auto-fix, Optuna trials, guardrail rejections, and the
final champion registration in real time (a full demo run takes ~2 minutes).

## Connecting a real Databricks workspace

```powershell
cd backend
copy .env.example .env
```

Edit `.env`:

```ini
DEMO_MODE=false
DATABRICKS_HOST=https://adb-xxxx.azuredatabricks.net
DATABRICKS_TOKEN=dapi...
DATABRICKS_WAREHOUSE_ID=<sql warehouse backing the Genie space>
DATABRICKS_CLUSTER_ID=<cluster for agent code execution>
MLFLOW_EXPERIMENT=/Shared/agentic-automl
CHAMPION_MODEL_NAME=prod.ml_models.ts_forecast_champion
```

The `GenieAgent` adapter (`backend/app/agents/genie.py`) then drives:

- `POST /api/2.0/genie/spaces` — provision the scoped space with seeded instructions
- `POST /api/2.0/genie/spaces/{id}/start-conversation` + message polling — the agent loop
- `PATCH /api/2.1/unity-catalog/tables/{name}` — semantic-role metadata enrichment
- `GET/POST /api/2.0/mlflow/...` — metric collection + champion registration

> Genie Agent-Mode capabilities vary by workspace release channel. If your
> space doesn't execute Python autonomously, responses still stream through and
> code attachments can be executed via the Command Execution API fallback.

## API surface

| Endpoint | Purpose |
|---|---|
| `POST /api/runs` | launch a pipeline run (body = `RunConfig`) |
| `GET /api/runs`, `GET /api/runs/{id}` | list / inspect runs |
| `GET /api/runs/{id}/events/stream?after=N` | **SSE** live agent events (replays history from N) |
| `POST /api/runs/{id}/cancel` | stop a running pipeline |
| `GET /api/catalog/tables` | UC tables + semantic roles |
| `GET /api/genie/spaces` | provisioned Genie spaces |
| `GET /api/leaderboard` | all candidates across runs, ranked by val MAPE |

## Pro-tips baked into the implementation

- **`@` operator** — every prompt template references tables as `@table_name`
  so Genie binds to exact schemas (see `app/prompts.py`).
- **Strict guardrails** — the training prompt embeds the divergence limit; the
  orchestrator surfaces every guardrail rejection as a first-class event.
- **Scoped spaces** — the run wizard warns when you scope more than 5 tables.
- **MCP extension point** — wrap proprietary outlier/metric UDFs as UC
  functions and expose them to Genie via MCP; add them to the space
  instructions in the wizard.

## Notes & limitations

- Run state is in-memory (restarting the backend clears history). Add a
  database or persist `store` to disk for production.
- No auth on the backend API — front it with your gateway/SSO before exposing.

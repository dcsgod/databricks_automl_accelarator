import { useEffect, useState } from "react";
import { api } from "../api";
import type { CatalogTable, RunConfig } from "../types";

const MODEL_OPTIONS = [
  { key: "xgboost", label: "XGBoost", desc: "Gradient-boosted trees" },
  { key: "lightgbm", label: "LightGBM", desc: "Fast GBDT" },
  { key: "prophet", label: "Prophet", desc: "Additive seasonality" },
  { key: "arima", label: "ARIMA", desc: "Statistical baseline" },
];

const DEFAULTS: RunConfig = {
  name: "Sales forecast — weekly seasonality",
  tables: ["main.demo.sales_timeseries"],
  timestamp_col: "date",
  target_col: "units_sold",
  entity_keys: ["store_id", "product_id"],
  grain: "daily",
  horizon_days: 28,
  models: ["xgboost", "prophet", "lightgbm"],
  optuna_trials: 12,
  train_split_pct: 80,
  guardrails: {
    max_loss_divergence_pct: 15,
    max_mape_pct: 60,
    require_temporal_split: true,
  },
  genie_instructions: [
    "Always assume the data grain is daily.",
    "Treat column store_id as a categorical slice entity.",
  ],
  register_champion_to: "prod.ml_models.ts_forecast_champion",
};

export default function NewRunWizard({
  onCreated, onCancel,
}: { onCreated: (id: string) => void; onCancel: () => void }) {
  const [cfg, setCfg] = useState<RunConfig>(DEFAULTS);
  const [tables, setTables] = useState<CatalogTable[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listTables().then(setTables).catch(() => {});
  }, []);

  const set = <K extends keyof RunConfig>(key: K, value: RunConfig[K]) =>
    setCfg((c) => ({ ...c, [key]: value }));

  const toggleTable = (name: string) =>
    set("tables", cfg.tables.includes(name)
      ? cfg.tables.filter((t) => t !== name)
      : [...cfg.tables, name]);

  const toggleModel = (key: string) =>
    set("models", cfg.models.includes(key)
      ? cfg.models.filter((m) => m !== key)
      : [...cfg.models, key]);

  const launch = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const run = await api.createRun(cfg);
      onCreated(run.id);
    } catch (e: any) {
      setError(e.message);
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h2>New AutoML Run</h2>
          <p>Configure the agentic loop. The Genie agent handles everything else.</p>
        </div>
        <button className="btn ghost" onClick={onCancel}>← Back</button>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>1 · Data context</h3>
          <div className="field">
            <label>Run name</label>
            <input value={cfg.name} onChange={(e) => set("name", e.target.value)} />
          </div>
          <div className="field">
            <label>Unity Catalog tables (scoped Genie Space, keep ≤ 5)</label>
            <div className="chip-row">
              {(tables.length ? tables.map((t) => t.full_name)
                : DEFAULTS.tables).map((name) => (
                <button key={name}
                        className={`chip ${cfg.tables.includes(name) ? "on" : ""}`}
                        onClick={() => toggleTable(name)}>
                  {name}
                </button>
              ))}
            </div>
            {cfg.tables.length > 5 && (
              <span className="hint" style={{ color: "var(--amber)" }}>
                ⚠ More than 5 tables degrades Genie accuracy.
              </span>
            )}
          </div>
          <div className="grid cols-2">
            <div className="field">
              <label>Timestamp column</label>
              <input value={cfg.timestamp_col}
                     onChange={(e) => set("timestamp_col", e.target.value)} />
            </div>
            <div className="field">
              <label>Target column</label>
              <input value={cfg.target_col}
                     onChange={(e) => set("target_col", e.target.value)} />
            </div>
          </div>
          <div className="grid cols-2">
            <div className="field">
              <label>Entity keys (comma-separated)</label>
              <input value={cfg.entity_keys.join(", ")}
                     onChange={(e) => set("entity_keys",
                       e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
            </div>
            <div className="field">
              <label>Grain</label>
              <select value={cfg.grain} onChange={(e) => set("grain", e.target.value)}>
                <option value="hourly">hourly</option>
                <option value="daily">daily</option>
                <option value="weekly">weekly</option>
                <option value="monthly">monthly</option>
              </select>
            </div>
          </div>
        </div>

        <div className="card">
          <h3>2 · Model search space</h3>
          <div className="field">
            <label>Model classes to compete</label>
            <div className="chip-row">
              {MODEL_OPTIONS.map((m) => (
                <button key={m.key}
                        className={`chip ${cfg.models.includes(m.key) ? "on" : ""}`}
                        onClick={() => toggleModel(m.key)}
                        title={m.desc}>
                  {m.label}
                </button>
              ))}
            </div>
          </div>
          <div className="grid cols-2">
            <div className="field">
              <label>Optuna trials per model</label>
              <input type="number" min={3} max={100} value={cfg.optuna_trials}
                     onChange={(e) => set("optuna_trials", +e.target.value || 12)} />
            </div>
            <div className="field">
              <label>Forecast horizon (days)</label>
              <input type="number" min={1} value={cfg.horizon_days}
                     onChange={(e) => set("horizon_days", +e.target.value || 28)} />
            </div>
          </div>
          <div className="field">
            <label>Temporal train split — {cfg.train_split_pct}% historical / {100 - cfg.train_split_pct}% future</label>
            <input type="range" min={60} max={95} value={cfg.train_split_pct}
                   onChange={(e) => set("train_split_pct", +e.target.value)} />
            <span className="hint">Temporal split prevents data leakage into validation.</span>
          </div>
        </div>

        <div className="card">
          <h3>3 · Guardrails</h3>
          <div className="field">
            <label>Max train/val loss divergence — reject beyond {cfg.guardrails.max_loss_divergence_pct}%</label>
            <input type="range" min={5} max={40} value={cfg.guardrails.max_loss_divergence_pct}
                   onChange={(e) => set("guardrails",
                     { ...cfg.guardrails, max_loss_divergence_pct: +e.target.value })} />
            <span className="hint">
              The agent prunes any Optuna trial whose train/val losses diverge past this limit.
            </span>
          </div>
          <div className="field">
            <label>Register champion to (Unity Catalog)</label>
            <input className="mono" value={cfg.register_champion_to}
                   onChange={(e) => set("register_champion_to", e.target.value)} />
          </div>
        </div>

        <div className="card">
          <h3>4 · Genie Space instructions</h3>
          <div className="field">
            <label>Seeded constraints (one per line)</label>
            <textarea rows={5}
                      value={cfg.genie_instructions.join("\n")}
                      onChange={(e) => set("genie_instructions",
                        e.target.value.split("\n").filter((s) => s.trim()))} />
            <span className="hint">
              Embedded into the scoped Genie Space so the agent inherits them implicitly.
            </span>
          </div>
        </div>
      </div>

      {error && <div className="toast">⚠️ {error}</div>}

      <div style={{ marginTop: 18, display: "flex", gap: 10 }}>
        <button className="btn" disabled={submitting || !cfg.tables.length || !cfg.models.length}
                onClick={launch}>
          {submitting ? "Launching…" : "🚀 Launch Agentic AutoML Run"}
        </button>
        <button className="btn ghost" onClick={onCancel}>Cancel</button>
      </div>
    </>
  );
}

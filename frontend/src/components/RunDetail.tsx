import { useEffect, useRef, useState } from "react";
import { api, streamRunEvents } from "../api";
import type { AgentEvent, Phase, PipelineRun } from "../types";
import { PHASE_ICONS, PHASE_LABELS, PHASE_ORDER } from "../types";
import { Markdown, StatusPill, TrialSparkline, fmtTime } from "./shared";

type Tab = "console" | "eda" | "models" | "champion";

export default function RunDetail({
  id, onBack,
}: { id: string; onBack: () => void }) {
  const [run, setRun] = useState<PipelineRun | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [tab, setTab] = useState<Tab>("console");
  const [autoScroll, setAutoScroll] = useState(true);
  const consoleRef = useRef<HTMLDivElement>(null);

  // Initial fetch + SSE subscription (replays history via `after=`).
  useEffect(() => {
    let cleanup: (() => void) | undefined;
    let cancelled = false;

    api.getRun(id).then((r) => {
      if (cancelled) return;
      setRun(r);
      setEvents(r.events);
      if (r.status === "running" || r.status === "pending") {
        cleanup = streamRunEvents(
          id,
          r.events.length,
          (e) => setEvents((prev) => [...prev, e]),
          () => api.getRun(id).then((final) => !cancelled && setRun(final)),
        );
      }
    });
    return () => { cancelled = true; cleanup?.(); };
  }, [id]);

  // Refresh structured state (eda/models/champion) when phases complete.
  useEffect(() => {
    const last = events[events.length - 1];
    if (last && (last.type === "phase_end" || last.type === "metric" || last.type === "artifact")) {
      api.getRun(id).then(setRun).catch(() => {});
    }
  }, [events.length]);

  useEffect(() => {
    if (autoScroll && consoleRef.current && tab === "console") {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [events.length, tab, autoScroll]);

  if (!run) return <div className="empty">Loading run…</div>;

  const currentPhase = lastPhase(events) ?? run.phase;
  const phasesDone = phasesCompleted(events, run);

  return (
    <>
      <div className="page-head">
        <div>
          <h2>
            {run.config.name} <StatusPill status={run.status} />
          </h2>
          <p>
            {run.config.tables.join(", ")} · target <code>{run.config.target_col}</code> ·{" "}
            {run.config.models.join(" / ")} · {run.config.optuna_trials} trials/model
            {run.genie_space_id && <> · space <code>{run.genie_space_id}</code></>}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {run.status === "running" && (
            <button className="btn danger" onClick={() => api.cancelRun(id)}>
              ■ Stop
            </button>
          )}
          <button className="btn ghost" onClick={onBack}>← Runs</button>
        </div>
      </div>

      <div className="stepper">
        {PHASE_ORDER.map((p, i) => {
          const state = phasesDone.includes(p)
            ? "done"
            : p === currentPhase && run.status === "running"
              ? "active"
              : "pending";
          return (
            <div key={p} className={`step ${state}`}>
              <div className="step-dot">
                {state === "done" ? "✓" : PHASE_ICONS[p]}
              </div>
              <div className="step-label">
                <b>Phase {i + 1} · {PHASE_LABELS[p]}</b>
                {state === "active" && <span style={{ color: "var(--blue)" }}>running…</span>}
                {state === "done" && <span style={{ color: "var(--green)" }}>complete</span>}
              </div>
            </div>
          );
        })}
      </div>

      {run.champion && <ChampionBanner run={run} />}

      <div className="tabs">
        {(["console", "eda", "models", "champion"] as Tab[]).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`}
                  onClick={() => setTab(t)}>
            {{ console: "🖥️ Agent Console", eda: "🔬 EDA", models: "⚙️ Models", champion: "🏆 Champion" }[t]}
          </button>
        ))}
        {tab === "console" && (
          <label style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-dim)", alignSelf: "center" }}>
            <input type="checkbox" checked={autoScroll}
                   onChange={(e) => setAutoScroll(e.target.checked)} /> auto-scroll
          </label>
        )}
      </div>

      {tab === "console" && (
        <div className="console" ref={consoleRef}>
          {events.length === 0 && <div className="empty">Waiting for agent…</div>}
          {events.map((e) => <EventRow key={e.id} e={e} />)}
        </div>
      )}
      {tab === "eda" && <EdaPanel run={run} />}
      {tab === "models" && <ModelsPanel run={run} events={events} />}
      {tab === "champion" && <ChampionPanel run={run} events={events} />}
    </>
  );
}

/* ------------------------------------------------------------- helpers */

function lastPhase(events: AgentEvent[]): Phase | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].type === "phase_start") return events[i].phase;
  }
  return null;
}

function phasesCompleted(events: AgentEvent[], run: PipelineRun): Phase[] {
  const done = new Set<Phase>(run.phases_done);
  for (const e of events) if (e.type === "phase_end") done.add(e.phase);
  return [...done];
}

function EventRow({ e }: { e: AgentEvent }) {
  if (e.type === "phase_start" || e.type === "phase_end") {
    return (
      <div className={`evt evt-${e.type}`}>
        <span className="evt-title">
          {e.type === "phase_start" ? `━━ ${e.title} ━━` : `✓ ${e.title}`}
        </span>
      </div>
    );
  }
  return (
    <div className={`evt evt-${e.type}`}>
      <div className="evt-head">
        <span className="evt-type">{e.type}</span>
        <span className="evt-title">{e.title}</span>
        <span className="evt-time">{fmtTime(e.ts)}</span>
      </div>
      {e.content && (
        e.type === "code" ? (
          <pre className="code-block">{e.content}</pre>
        ) : e.type === "markdown" ? (
          <div className="evt-body"><Markdown text={e.content} /></div>
        ) : e.type === "error" || e.type === "autofix" || e.type === "exec" ? (
          <pre className="code-block">{e.content}</pre>
        ) : (
          <div className="evt-body">{e.content}</div>
        )
      )}
    </div>
  );
}

function EdaPanel({ run }: { run: PipelineRun }) {
  const eda = run.eda;
  if (!eda) {
    return <div className="empty">EDA has not completed yet — watch the Agent Console.</div>;
  }
  const stats: [string, string][] = [
    ["Rows", eda.rows ? eda.rows.toLocaleString() : "—"],
    ["Date range", eda.date_min ? `${eda.date_min} → ${eda.date_max}` : "—"],
    ["Missing gaps", String(eda.missing_gaps)],
    ["Trend", eda.trend || "—"],
    ["Seasonality period", eda.seasonality_period ? `${eda.seasonality_period} (weekly)` : "—"],
    ["ADF statistic", eda.adf_statistic != null ? String(eda.adf_statistic) : "—"],
    ["ADF p-value", eda.adf_pvalue != null ? String(eda.adf_pvalue) : "—"],
    ["Stationary", eda.stationary == null ? "—" : eda.stationary ? "✓ yes" : "✗ no"],
  ];
  return (
    <div className="card">
      <h3>Time-series behavioral profile</h3>
      <div className="eda-grid">
        {stats.map(([k, v]) => (
          <div key={k} className="eda-stat">
            <div className="k">{k}</div>
            <div className="v">{v}</div>
          </div>
        ))}
      </div>
      {eda.significant_lags.length > 0 && (
        <p className="dim" style={{ marginTop: 14 }}>
          Significant ACF lags: {eda.significant_lags.join(", ")} — these drive the
          engineered lag/rolling-window features in Phase 3.
        </p>
      )}
      {eda.notes && <p className="dim">{eda.notes}</p>}
    </div>
  );
}

function ModelsPanel({ run, events }: { run: PipelineRun; events: AgentEvent[] }) {
  if (!run.models.length) {
    return <div className="empty">Training has not started yet.</div>;
  }
  const guardrails = events.filter((e) => e.type === "guardrail");
  const sorted = [...run.models].sort(
    (a, b) => (a.mape ?? Infinity) - (b.mape ?? Infinity));
  return (
    <>
      <div className="card" style={{ marginBottom: 14 }}>
        <h3>Model leaderboard (validation)</h3>
        <table className="data">
          <thead>
            <tr>
              <th></th><th>Model</th><th>Status</th><th>val MAPE</th><th>val RMSE</th>
              <th>Convergence</th><th>Best params</th><th>MLflow run</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((m, i) => {
              const champ = run.champion?.model === m.model;
              return (
                <tr key={m.model} className={champ ? "champ-row" : ""}>
                  <td>{champ ? "🏆" : `#${i + 1}`}</td>
                  <td><b>{m.model}</b></td>
                  <td><span className={`status-pill status-${m.status === "done" ? "succeeded" : "running"}`}>{m.status}</span></td>
                  <td className="mono">{m.mape != null ? `${m.mape}%` : "—"}</td>
                  <td className="mono">{m.rmse ?? "—"}</td>
                  <td><TrialSparkline trials={m.trials} /></td>
                  <td className="mono dim" style={{ maxWidth: 260 }}>
                    {Object.entries(m.best_params).map(([k, v]) => `${k}=${v}`).join(" ")}
                  </td>
                  <td className="mono dim">{m.mlflow_run_id ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {guardrails.length > 0 && (
        <div className="card">
          <h3>Guardrail interventions ({guardrails.length})</h3>
          {guardrails.map((g) => (
            <div key={g.id} className="evt evt-guardrail" style={{ marginBottom: 8 }}>
              <div className="evt-head">
                <span className="evt-type">guardrail</span>
                <span className="evt-title">{g.title}</span>
              </div>
              <div className="evt-body">{g.content}</div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function ChampionBanner({ run }: { run: PipelineRun }) {
  const c = run.champion!;
  return (
    <div className="champion-banner">
      <div className="trophy">🏆</div>
      <div>
        <h3>{c.model} is the champion</h3>
        <div className="reg">{c.registered_name} · v{c.version}</div>
        <p>{c.rationale}</p>
      </div>
      <div className="kpis">
        <div className="kpi"><div className="v">{c.mape}%</div><div className="k">val MAPE</div></div>
        <div className="kpi"><div className="v">{c.rmse}</div><div className="k">val RMSE</div></div>
      </div>
    </div>
  );
}

function ChampionPanel({ run, events }: { run: PipelineRun; events: AgentEvent[] }) {
  if (!run.champion) {
    return <div className="empty">Champion selection has not completed yet.</div>;
  }
  const report = [...events].reverse().find(
    (e) => e.phase === "champion" && e.type === "markdown");
  return (
    <div className="card">
      <h3>Audit trail — execution report</h3>
      {report ? <Markdown text={report.content} /> : <p className="dim">No report.</p>}
    </div>
  );
}

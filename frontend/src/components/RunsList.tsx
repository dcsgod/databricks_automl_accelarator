import { useEffect, useState } from "react";
import { api } from "../api";
import type { RunSummary } from "../types";
import { PHASE_LABELS, PHASE_ORDER } from "../types";
import { StatusPill, fmtDateTime } from "./shared";

export default function RunsList({
  onOpen, onNew,
}: { onOpen: (id: string) => void; onNew: () => void }) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.listRuns().then((r) => alive && setRuns(r)).catch(() => {});
    load();
    const t = setInterval(load, 4000); // keep statuses fresh while runs execute
    return () => { alive = false; clearInterval(t); };
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Pipeline Runs</h2>
          <p>Each run executes the 4-phase agentic AutoML loop: Curation → EDA → Training → Champion.</p>
        </div>
        <button className="btn" onClick={onNew}>＋ New AutoML Run</button>
      </div>

      {runs === null ? (
        <div className="empty">Loading…</div>
      ) : runs.length === 0 ? (
        <div className="empty">
          <div className="big">🧞</div>
          <p>No runs yet. Launch your first agentic AutoML run.</p>
          <button className="btn" onClick={onNew}>＋ New AutoML Run</button>
        </div>
      ) : (
        <div className="grid">
          {runs.map((r) => (
            <button key={r.id} className="run-card" onClick={() => onOpen(r.id)}>
              <div className="row1">
                <span className="name">{r.name}</span>
                <StatusPill status={r.status} />
              </div>
              <div className="meta">
                {fmtDateTime(r.created_at)} · {r.tables.join(", ")} ·{" "}
                {r.models.join(" / ")}
                {r.status === "running" && r.phase && (
                  <> · <b style={{ color: "var(--blue)" }}>
                    {PHASE_LABELS[r.phase]} ({PHASE_ORDER.indexOf(r.phase) + 1}/4)
                  </b></>
                )}
                {r.champion && (
                  <> · 🏆 {r.champion.model} (MAPE {r.champion.mape}%)</>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </>
  );
}

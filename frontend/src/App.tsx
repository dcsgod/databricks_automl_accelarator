import { useEffect, useState } from "react";
import { api } from "./api";
import RunsList from "./components/RunsList";
import NewRunWizard from "./components/NewRunWizard";
import RunDetail from "./components/RunDetail";
import CatalogView from "./components/CatalogView";
import SpacesView from "./components/SpacesView";
import LeaderboardView from "./components/LeaderboardView";

export type View =
  | { kind: "runs" }
  | { kind: "new-run" }
  | { kind: "run"; id: string }
  | { kind: "catalog" }
  | { kind: "spaces" }
  | { kind: "leaderboard" };

const NAV: { key: string; label: string; icon: string; view: View }[] = [
  { key: "runs", label: "Pipeline Runs", icon: "🔁", view: { kind: "runs" } },
  { key: "catalog", label: "Data Catalog", icon: "🗂️", view: { kind: "catalog" } },
  { key: "spaces", label: "Genie Spaces", icon: "🧞", view: { kind: "spaces" } },
  { key: "leaderboard", label: "Leaderboard", icon: "📊", view: { kind: "leaderboard" } },
];

export default function App() {
  const [view, setView] = useState<View>({ kind: "runs" });
  const [demoMode, setDemoMode] = useState<boolean | null>(null);
  const [workspace, setWorkspace] = useState<string | null>(null);
  const [backendDown, setBackendDown] = useState(false);

  useEffect(() => {
    api.health()
      .then((h) => { setDemoMode(h.demo_mode); setWorkspace(h.workspace); setBackendDown(false); })
      .catch(() => setBackendDown(true));
  }, []);

  const activeKey =
    view.kind === "run" || view.kind === "new-run" ? "runs" : view.kind;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">🧞</div>
          <div>
            <h1>Agentic AutoML</h1>
            <span>Genie Orchestrator</span>
          </div>
        </div>

        {NAV.map((n) => (
          <button
            key={n.key}
            className={`nav-item ${activeKey === n.key ? "active" : ""}`}
            onClick={() => setView(n.view)}
          >
            <span>{n.icon}</span> {n.label}
          </button>
        ))}

        <div className="sidebar-footer">
          {demoMode === null ? null : demoMode ? (
            <span className="mode-pill">● DEMO MODE</span>
          ) : (
            <span className="mode-pill live">● {workspace?.replace(/^https?:\/\//, "") ?? "LIVE"}</span>
          )}
          <div style={{ marginTop: 8 }}>
            UC ▸ Genie Space ▸ Genie Code ▸ MLflow
          </div>
        </div>
      </aside>

      <main className="main">
        {backendDown && (
          <div className="toast">
            ⚠️ Backend unreachable — start it with{" "}
            <code>uvicorn app.main:app --port 8000</code> (from <code>backend/</code>).
          </div>
        )}
        {view.kind === "runs" && (
          <RunsList
            onOpen={(id) => setView({ kind: "run", id })}
            onNew={() => setView({ kind: "new-run" })}
          />
        )}
        {view.kind === "new-run" && (
          <NewRunWizard
            onCreated={(id) => setView({ kind: "run", id })}
            onCancel={() => setView({ kind: "runs" })}
          />
        )}
        {view.kind === "run" && (
          <RunDetail id={view.id} onBack={() => setView({ kind: "runs" })} />
        )}
        {view.kind === "catalog" && <CatalogView />}
        {view.kind === "spaces" && <SpacesView />}
        {view.kind === "leaderboard" && (
          <LeaderboardView onOpenRun={(id) => setView({ kind: "run", id })} />
        )}
      </main>
    </div>
  );
}

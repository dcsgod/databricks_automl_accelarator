import { useEffect, useState } from "react";
import { api } from "../api";
import type { GenieSpace } from "../types";

export default function SpacesView() {
  const [spaces, setSpaces] = useState<GenieSpace[] | null>(null);

  useEffect(() => {
    api.listSpaces().then(setSpaces).catch(() => setSpaces([]));
  }, []);

  if (spaces === null) return <div className="empty">Loading spaces…</div>;

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Genie Spaces</h2>
          <p>
            Scoped context layers provisioned by Phase 1 — each holds ≤ 5 tables plus
            seeded constraints, so the agent inherits domain knowledge implicitly.
          </p>
        </div>
      </div>

      {spaces.length === 0 ? (
        <div className="empty">
          <div className="big">🧞</div>
          <p>No spaces yet. Launch an AutoML run — Phase 1 provisions one automatically.</p>
        </div>
      ) : (
        <div className="grid cols-2">
          {spaces.map((s) => (
            <div key={s.id} className="card">
              <h3>{s.title}</h3>
              <div className="mono dim" style={{ fontSize: 12, marginBottom: 10 }}>{s.id}</div>
              <p className="dim" style={{ fontSize: 12.5 }}>{s.description}</p>
              {s.tables.length > 0 && (
                <>
                  <div className="dim" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".5px", margin: "10px 0 6px" }}>
                    Scoped tables
                  </div>
                  <div className="chip-row">
                    {s.tables.map((t) => <span key={t} className="chip on">{t}</span>)}
                  </div>
                </>
              )}
              {s.instructions.length > 0 && (
                <>
                  <div className="dim" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".5px", margin: "12px 0 6px" }}>
                    Seeded constraints
                  </div>
                  {s.instructions.map((i, idx) => (
                    <div key={idx} style={{ fontSize: 12.5, color: "var(--text-dim)", padding: "3px 0" }}>
                      💬 “{i}”
                    </div>
                  ))}
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

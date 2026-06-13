import { useEffect, useState } from "react";
import { api } from "../api";
import type { CatalogTable } from "../types";

const ROLE_COLORS: Record<string, string> = {
  timestamp: "var(--blue)",
  target: "var(--accent-soft)",
  entity_key: "var(--purple)",
  metric: "var(--green)",
  feature: "var(--amber)",
};

export default function CatalogView() {
  const [tables, setTables] = useState<CatalogTable[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api.listTables().then((t) => {
      setTables(t);
      if (t.length) setOpen(t[0].full_name);
    }).catch(() => setTables([]));
  }, []);

  if (tables === null) return <div className="empty">Loading catalog…</div>;

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Data Catalog</h2>
          <p>
            Phase 1 reads these semantic roles. Time-series models live and die by
            data structure — label timestamps, targets, and entity keys explicitly.
          </p>
        </div>
      </div>

      <div className="grid">
        {tables.map((t) => (
          <div key={t.full_name} className="card">
            <div style={{ display: "flex", justifyContent: "space-between", cursor: "pointer" }}
                 onClick={() => setOpen(open === t.full_name ? null : t.full_name)}>
              <div>
                <h3 style={{ marginBottom: 4 }} className="mono">{t.full_name}</h3>
                <span className="dim" style={{ fontSize: 12.5 }}>{t.comment}</span>
              </div>
              <div className="dim" style={{ fontSize: 12 }}>
                {t.row_count != null && <>{t.row_count.toLocaleString()} rows · </>}
                {t.columns.length} cols {open === t.full_name ? "▾" : "▸"}
              </div>
            </div>
            {open === t.full_name && (
              <table className="data" style={{ marginTop: 12 }}>
                <thead>
                  <tr><th>Column</th><th>Type</th><th>Semantic role</th><th>Comment</th></tr>
                </thead>
                <tbody>
                  {t.columns.map((c) => (
                    <tr key={c.name}>
                      <td className="mono">{c.name}</td>
                      <td className="mono dim">{c.type}</td>
                      <td>
                        {c.semantic_role && (
                          <span className="status-pill"
                                style={{ background: "rgba(255,255,255,.05)",
                                         color: ROLE_COLORS[c.semantic_role] ?? "var(--text-dim)" }}>
                            {c.semantic_role}
                          </span>
                        )}
                      </td>
                      <td className="dim">{c.comment}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ))}
      </div>
    </>
  );
}

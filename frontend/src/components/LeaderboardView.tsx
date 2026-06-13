import { useEffect, useState } from "react";
import { api } from "../api";
import type { LeaderboardRow } from "../types";

export default function LeaderboardView({
  onOpenRun,
}: { onOpenRun: (id: string) => void }) {
  const [rows, setRows] = useState<LeaderboardRow[] | null>(null);

  useEffect(() => {
    api.leaderboard().then(setRows).catch(() => setRows([]));
  }, []);

  if (rows === null) return <div className="empty">Loading leaderboard…</div>;

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Model Leaderboard</h2>
          <p>Every candidate trained across all runs, ranked by validation MAPE (MLflow).</p>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="empty">
          <div className="big">📊</div>
          <p>No trained models yet — launch an AutoML run.</p>
        </div>
      ) : (
        <div className="card">
          <table className="data">
            <thead>
              <tr>
                <th>#</th><th>Model</th><th>Run</th><th>val MAPE</th><th>val RMSE</th>
                <th>MLflow run</th><th>Registered</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.run_id}-${r.model}`} className={r.is_champion ? "champ-row" : ""}>
                  <td>{r.is_champion ? "🏆" : i + 1}</td>
                  <td><b>{r.model}</b></td>
                  <td>
                    <a style={{ color: "var(--blue)", cursor: "pointer" }}
                       onClick={() => onOpenRun(r.run_id)}>
                      {r.run_name}
                    </a>
                  </td>
                  <td className="mono">{r.mape}%</td>
                  <td className="mono">{r.rmse ?? "—"}</td>
                  <td className="mono dim">{r.mlflow_run_id ?? "—"}</td>
                  <td className="mono" style={{ color: "var(--green)" }}>
                    {r.registered_name ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

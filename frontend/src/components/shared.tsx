import type { RunStatus } from "../types";

export function StatusPill({ status }: { status: RunStatus }) {
  return <span className={`status-pill status-${status}`}>{status}</span>;
}

export function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export function fmtDateTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString([], {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

/** Minimal, safe markdown renderer (headings, tables, bold, code). */
export function Markdown({ text }: { text: string }) {
  const esc = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  const inline = (s: string) =>
    esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");

  const lines = text.split("\n");
  const out: string[] = [];
  let tableRows: string[][] = [];

  const flushTable = () => {
    if (!tableRows.length) return;
    const [head, ...body] = tableRows;
    out.push(
      "<table><thead><tr>" +
        head.map((c) => `<th>${inline(c)}</th>`).join("") +
        "</tr></thead><tbody>" +
        body.map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") +
        "</tbody></table>",
    );
    tableRows = [];
  };

  for (const line of lines) {
    if (/^\|/.test(line.trim())) {
      const cells = line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      if (cells.every((c) => /^-{2,}$/.test(c.replace(/:/g, "")))) continue; // separator
      tableRows.push(cells);
      continue;
    }
    flushTable();
    if (line.startsWith("### ")) out.push(`<h3>${inline(line.slice(4))}</h3>`);
    else if (line.startsWith("- ")) out.push(`<div>• ${inline(line.slice(2))}</div>`);
    else if (line.trim()) out.push(`<div>${inline(line)}</div>`);
    else out.push("<div style='height:6px'></div>");
  }
  flushTable();

  return <div className="md" dangerouslySetInnerHTML={{ __html: out.join("") }} />;
}

/** SVG sparkline of Optuna trial MAPE history. */
export function TrialSparkline({
  trials, width = 180, height = 44,
}: {
  trials: { trial: number; mape: number; pruned: boolean }[];
  width?: number; height?: number;
}) {
  const kept = trials.filter((t) => !t.pruned);
  if (kept.length < 2) return null;
  const mapes = kept.map((t) => t.mape);
  const min = Math.min(...mapes), max = Math.max(...mapes);
  const span = max - min || 1;
  const px = (i: number) => 4 + (i / (kept.length - 1)) * (width - 8);
  const py = (m: number) => 4 + ((m - min) / span) * (height - 8);

  // running best (lower envelope)
  let best = Infinity;
  const bestPts = kept.map((t, i) => {
    best = Math.min(best, t.mape);
    return `${px(i)},${py(best)}`;
  });
  const rawPts = kept.map((t, i) => `${px(i)},${py(t.mape)}`);

  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polyline points={rawPts.join(" ")} fill="none" stroke="#334155" strokeWidth="1.2" />
      <polyline points={bestPts.join(" ")} fill="none" stroke="#34d399" strokeWidth="1.8" />
      <circle cx={px(kept.length - 1)} cy={py(best)} r="2.6" fill="#34d399" />
    </svg>
  );
}

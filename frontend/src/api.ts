import type {
  AgentEvent, CatalogTable, GenieSpace, LeaderboardRow, PipelineRun,
  RunConfig, RunSummary,
} from "./types";

const BASE = "/api";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json();
}

export const api = {
  health: () => http<{ status: string; demo_mode: boolean; workspace: string | null }>("/health"),
  createRun: (config: RunConfig) =>
    http<RunSummary>("/runs", { method: "POST", body: JSON.stringify(config) }),
  listRuns: () => http<RunSummary[]>("/runs"),
  getRun: (id: string) => http<PipelineRun>(`/runs/${id}`),
  cancelRun: (id: string) => http<{ ok: boolean }>(`/runs/${id}/cancel`, { method: "POST" }),
  listTables: () => http<CatalogTable[]>("/catalog/tables"),
  listSpaces: () => http<GenieSpace[]>("/genie/spaces"),
  leaderboard: () => http<LeaderboardRow[]>("/leaderboard"),
};

/** Subscribe to a run's live agent events over SSE. Returns a cleanup fn. */
export function streamRunEvents(
  runId: string,
  after: number,
  onEvent: (e: AgentEvent) => void,
  onDone: (status: string) => void,
): () => void {
  const source = new EventSource(`${BASE}/runs/${runId}/events/stream?after=${after}`);
  source.addEventListener("agent", (msg) => {
    onEvent(JSON.parse((msg as MessageEvent).data));
  });
  source.addEventListener("done", (msg) => {
    const { status } = JSON.parse((msg as MessageEvent).data);
    source.close();
    onDone(status);
  });
  source.onerror = () => {
    /* EventSource auto-reconnects; the `after` replay on the server keeps
       history intact for late joins. */
  };
  return () => source.close();
}

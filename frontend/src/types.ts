// Mirrors backend/app/schemas.py

export type Phase = "curation" | "eda" | "automl" | "champion";
export type RunStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";

export type EventType =
  | "log" | "prompt" | "code" | "exec" | "markdown" | "metric" | "trial"
  | "error" | "autofix" | "guardrail" | "phase_start" | "phase_end" | "artifact";

export const PHASE_ORDER: Phase[] = ["curation", "eda", "automl", "champion"];

export const PHASE_LABELS: Record<Phase, string> = {
  curation: "Semantic Curation",
  eda: "Automated EDA",
  automl: "AutoML Training",
  champion: "Champion Selection",
};

export const PHASE_ICONS: Record<Phase, string> = {
  curation: "🏛️",
  eda: "🔬",
  automl: "⚙️",
  champion: "🏆",
};

export interface AgentEvent {
  id: string;
  ts: number;
  phase: Phase;
  type: EventType;
  title: string;
  content: string;
  data: Record<string, any>;
}

export interface GuardrailConfig {
  max_loss_divergence_pct: number;
  max_mape_pct: number;
  require_temporal_split: boolean;
}

export interface RunConfig {
  name: string;
  tables: string[];
  timestamp_col: string;
  target_col: string;
  entity_keys: string[];
  grain: string;
  horizon_days: number;
  models: string[];
  optuna_trials: number;
  train_split_pct: number;
  guardrails: GuardrailConfig;
  genie_instructions: string[];
  register_champion_to: string;
}

export interface ModelResult {
  model: string;
  status: string;
  mape: number | null;
  rmse: number | null;
  best_params: Record<string, any>;
  trials: { trial: number; mape: number; rmse: number; pruned: boolean }[];
  train_seconds: number | null;
  mlflow_run_id: string | null;
  rejected_reason: string | null;
}

export interface EdaSummary {
  rows: number;
  date_min: string;
  date_max: string;
  missing_gaps: number;
  trend: string;
  seasonality_period: number;
  adf_statistic: number | null;
  adf_pvalue: number | null;
  stationary: boolean | null;
  significant_lags: number[];
  notes: string;
}

export interface Champion {
  model: string;
  mape: number;
  rmse: number;
  registered_name: string;
  version: number;
  rationale: string;
}

export interface PipelineRun {
  id: string;
  created_at: number;
  status: RunStatus;
  phase: Phase | null;
  phases_done: Phase[];
  config: RunConfig;
  genie_space_id: string | null;
  eda: EdaSummary | null;
  models: ModelResult[];
  champion: Champion | null;
  error: string | null;
  events: AgentEvent[];
}

export interface RunSummary {
  id: string;
  created_at: number;
  status: RunStatus;
  phase: Phase | null;
  phases_done: Phase[];
  name: string;
  tables: string[];
  models: string[];
  champion: Champion | null;
}

export interface TableColumn {
  name: string;
  type: string;
  comment: string;
  semantic_role: string;
}

export interface CatalogTable {
  full_name: string;
  comment: string;
  row_count: number | null;
  columns: TableColumn[];
}

export interface GenieSpace {
  id: string;
  title: string;
  description: string;
  tables: string[];
  instructions: string[];
  created_at: number;
}

export interface LeaderboardRow {
  run_id: string;
  run_name: string;
  model: string;
  mape: number;
  rmse: number | null;
  mlflow_run_id: string | null;
  is_champion: boolean;
  registered_name: string | null;
}

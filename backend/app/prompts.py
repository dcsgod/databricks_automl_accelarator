"""Natural-language prompt templates sent to the Genie Code API (Agent Mode).

These mirror the strategic plan: every phase is driven by an explicit,
auditable prompt. Tables are always referenced with the @ operator so Genie
binds to the exact Unity Catalog schema instead of hallucinating columns.
"""
from .schemas import RunConfig


def _at(table: str) -> str:
    return "@" + table.split(".")[-1]


def eda_prompt(cfg: RunConfig) -> str:
    tables = ", ".join(_at(t) for t in cfg.tables)
    return (
        f"Access {tables}. Perform comprehensive time-series EDA on target "
        f"`{cfg.target_col}` over timestamp `{cfg.timestamp_col}` "
        f"(grain: {cfg.grain}, entities: {', '.join(cfg.entity_keys)}): "
        "check for missing timestamp gaps, evaluate overall trend and seasonal "
        "cycles, run an Augmented Dickey-Fuller (ADF) test for stationarity, "
        "and generate ACF/PACF plots. Return a structured markdown summary."
    )


def feature_prompt(cfg: RunConfig, seasonality_period: int) -> str:
    return (
        f"Based on the seasonal lag of {seasonality_period} identified in EDA, "
        f"write a notebook to engineer {seasonality_period}-day and "
        f"{seasonality_period * 2}-day rolling windows, lag variables, and "
        "holiday effects. Save this into a new materialized feature table."
    )


def training_prompt(cfg: RunConfig) -> str:
    models = ", ".join(m.capitalize() for m in cfg.models)
    return (
        "Act as an expert ML Engineer. Write an end-to-end training framework "
        "on our engineered features.\n"
        f"1. Use a temporal train/test split ({cfg.train_split_pct}% historical / "
        f"{100 - cfg.train_split_pct}% future) to prevent data leakage.\n"
        f"2. Programmatically train and compare {len(cfg.models)} distinct "
        f"approaches: {models}.\n"
        f"3. Use Optuna ({cfg.optuna_trials} trials each) to optimize "
        "hyperparameters for each model.\n"
        "4. Calculate MAPE and RMSE for evaluation.\n"
        "5. Log all parameters, artifacts, and evaluation metrics natively to "
        "MLflow.\n"
        f"GUARDRAIL: Reject any model iteration where training loss and "
        f"validation loss diverge by more than "
        f"{cfg.guardrails.max_loss_divergence_pct:.0f}%."
    )


def champion_prompt(cfg: RunConfig) -> str:
    models = ", ".join(m.capitalize() for m in cfg.models)
    return (
        "Read the MLflow metrics from the current run. Compare the validation "
        f"MAPE score across {models}. Automatically register the "
        f"best-performing model into Unity Catalog at "
        f"`{cfg.register_champion_to}` and return a detailed execution report "
        "outlining why you picked the winner, including a breakdown of "
        "validation curves."
    )

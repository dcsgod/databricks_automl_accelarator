"""Application settings.

All Databricks connectivity is optional: when DEMO_MODE is true (the default)
the app runs against a high-fidelity simulator so the full UI/UX works
without a workspace. Flip DEMO_MODE=false and provide host + token to drive
a real workspace.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    demo_mode: bool = True

    # Databricks workspace connectivity (real mode)
    databricks_host: str = ""          # e.g. https://adb-1234567890123456.7.azuredatabricks.net
    databricks_token: str = ""         # PAT or OAuth token
    databricks_warehouse_id: str = ""  # SQL warehouse backing Genie spaces
    databricks_cluster_id: str = ""    # cluster used for agent code execution

    # MLflow / Unity Catalog defaults
    mlflow_experiment: str = "/Shared/agentic-automl"
    champion_model_name: str = "prod.ml_models.ts_forecast_champion"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()

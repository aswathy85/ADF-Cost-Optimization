"""config.py — Loads `config.yaml` and environment variables.

This module defines lightweight typed dataclasses that represent the
configuration used throughout the tool and provides `load_config()` to
produce a single `AppConfig` instance.
"""
from __future__ import annotations
import os, yaml
from dataclasses import dataclass, field
from typing import Dict, List
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

@dataclass
class EnvironmentConfig:
    # Patterns help map factory names to environment labels (dev/qa/prod)
    patterns: List[str]
    color: str = "4472C4"

@dataclass
class AzureConfig:
    # Azure-specific connectivity and scope settings
    subscription_ids: List[str]
    tenant_id: str
    resource_groups: List[str] = field(default_factory=list)

@dataclass
class AnalysisConfig:
    # Analysis-related options: how many days to include, environment mapping
    date_range_days: int
    environments: Dict[str, EnvironmentConfig]
    top_pipelines_for_ai: int = 15

@dataclass
class CostThresholds:
    # Thresholds used to classify pipelines/factories into cost tiers
    high: float = 200.0
    medium: float = 50.0
    low: float = 10.0

@dataclass
class GenAIConfig:
    # GenAI-related settings (model name + token limits)
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096

@dataclass
class OutputConfig:
    # Paths for final outputs: Excel workbook and Power BI CSV export
    excel_path: str = "./reports/ADF_Cost_Optimization_Report.xlsx"
    powerbi_csv_path: str = "./reports/PowerBI_DataModel.csv"

@dataclass
class AppConfig:
    # Aggregated application configuration (single source of truth)
    azure: AzureConfig
    analysis: AnalysisConfig
    cost_thresholds: CostThresholds
    genai: GenAIConfig
    output: OutputConfig
    use_mock_data: bool = False
    mock_data_seed: int = 42
    anthropic_api_key: str = ""

def load_config(config_path: str = "config.yaml") -> AppConfig:
    # Read YAML file, support overrides from environment variables
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(path) as fh:
        raw = yaml.safe_load(fh)

    # Azure settings: prefer comma-separated env var if set for automation
    azure_raw = raw["azure"]
    sub_ids = os.environ.get("AZURE_SUBSCRIPTION_IDS", "")
    subscription_ids = (
        [s.strip() for s in sub_ids.split(",") if s.strip()]
        if sub_ids else azure_raw["subscription_ids"]
    )
    azure = AzureConfig(
        subscription_ids=subscription_ids,
        tenant_id=os.environ.get("AZURE_TENANT_ID", azure_raw.get("tenant_id", "")),
        resource_groups=azure_raw.get("resource_groups", []),
    )

    # Analysis block: environments mapping -> EnvironmentConfig objects
    analysis_raw = raw["analysis"]
    envs: Dict[str, EnvironmentConfig] = {}
    for env_name, env_data in analysis_raw["environments"].items():
        envs[env_name] = EnvironmentConfig(patterns=env_data["patterns"], color=env_data.get("color", "4472C4"))
    analysis = AnalysisConfig(
        date_range_days=analysis_raw["date_range_days"],
        environments=envs,
        top_pipelines_for_ai=analysis_raw.get("top_pipelines_for_ai", 15),
    )

    # Misc thresholds and output settings
    ct_raw = raw.get("cost_thresholds", {})
    cost_thresholds = CostThresholds(high=float(ct_raw.get("high", 200.0)), medium=float(ct_raw.get("medium", 50.0)), low=float(ct_raw.get("low", 10.0)))
    genai_raw = raw.get("genai", {})
    genai = GenAIConfig(model=genai_raw.get("model", "claude-sonnet-4-20250514"), max_tokens=int(genai_raw.get("max_tokens", 4096)))
    out_raw = raw.get("output", {})
    output = OutputConfig(
        excel_path=out_raw.get("excel_path", "./reports/ADF_Cost_Optimization_Report.xlsx"),
        powerbi_csv_path=out_raw.get("powerbi_csv_path", "./reports/PowerBI_DataModel.csv"),
    )

    # Ensure output folders exist
    for p in [output.excel_path, output.powerbi_csv_path]:
        Path(p).parent.mkdir(parents=True, exist_ok=True)

    # Return a fully-populated AppConfig object
    return AppConfig(
        azure=azure, analysis=analysis, cost_thresholds=cost_thresholds,
        genai=genai, output=output,
        use_mock_data=raw.get("use_mock_data", False),
        mock_data_seed=int(raw.get("mock_data_seed", 42)),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
    )

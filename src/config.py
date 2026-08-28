"""Validated configuration loading with project-relative paths."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PathsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    universe: Path
    raw_data: Path
    processed_data: Path
    cache: Path
    sec_cache: Path | None = None
    valuation: Path | None = None
    macro: Path | None = None
    macro_exposures: Path | None = None
    shock_taxonomy: Path | None = None
    macro_cache: Path | None = None
    news_cache: Path | None = None
    reports: Path


class PriceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "yahoo"
    history_period: str = "max"
    cache_ttl_hours: int = Field(default=18, ge=0)
    max_workers: int = Field(default=4, ge=1, le=32)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)

    @field_validator("provider")
    @classmethod
    def provider_is_supported(cls, value: str) -> str:
        if value.lower() != "yahoo":
            raise ValueError("V1 currently supports only the 'yahoo' price provider")
        return value.lower()


class ScreeningSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawdown_52w_threshold: float = Field(default=-0.20, ge=-1.0, le=0.0)
    drawdown_3m_threshold: float = Field(default=-0.15, ge=-1.0, le=0.0)
    drawdown_6m_threshold: float = Field(default=-0.20, ge=-1.0, le=0.0)
    relative_sector_threshold: float = Field(default=-0.10, ge=-2.0, le=0.0)
    minimum_observations: int = Field(default=60, ge=2)
    rsi_period: int = Field(default=14, ge=2)
    annualization_days: int = Field(default=252, ge=1)


class FundamentalsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    provider: str = "sec_edgar"
    user_agent_env: str = "SEC_USER_AGENT"
    cache_ttl_hours: int = Field(default=24, ge=0)
    requests_per_second: float = Field(default=5.0, gt=0.0, le=10.0)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_retries: int = Field(default=3, ge=0, le=8)
    history_years: int = Field(default=5, ge=2, le=20)
    as_of: date | datetime | None = None
    minimum_score_coverage: float = Field(default=0.50, ge=0.0, le=1.0)

    @field_validator("provider")
    @classmethod
    def fundamental_provider_is_supported(cls, value: str) -> str:
        if value.lower() != "sec_edgar":
            raise ValueError("this phase currently supports only 'sec_edgar'")
        return value.lower()


class ValuationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    historical_minimum_points: int = Field(default=3, ge=1)
    sector_minimum_peers: int = Field(default=3, ge=1)
    minimum_score_coverage: float = Field(default=0.50, ge=0.0, le=1.0)
    reverse_growth_lower_bound: float = Field(default=-0.50, gt=-1.0, le=0.0)
    reverse_growth_upper_bound: float = Field(default=0.50, ge=0.0, le=2.0)

    @model_validator(mode="after")
    def reverse_bounds_are_ordered(self) -> "ValuationSettings":
        if self.reverse_growth_lower_bound >= self.reverse_growth_upper_bound:
            raise ValueError("reverse DCF lower bound must be below upper bound")
        return self


class MacroSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: str = "fred"
    api_key_env: str = "FRED_API_KEY"
    cache_ttl_hours: int = Field(default=24, ge=0)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_retries: int = Field(default=3, ge=0, le=8)
    history_years: int = Field(default=2, ge=1, le=20)

    @field_validator("provider")
    @classmethod
    def macro_provider_is_supported(cls, value: str) -> str:
        if value.lower() != "fred":
            raise ValueError("this phase currently supports only the 'fred' macro provider")
        return value.lower()


class NewsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: str = "gdelt"
    cache_ttl_hours: int = Field(default=6, ge=0)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_retries: int = Field(default=3, ge=0, le=8)
    lookback_days: int = Field(default=30, ge=1, le=90)
    max_articles: int = Field(default=75, ge=1, le=250)

    @field_validator("provider")
    @classmethod
    def news_provider_is_supported(cls, value: str) -> str:
        if value.lower() != "gdelt":
            raise ValueError("this phase currently supports only the 'gdelt' news provider")
        return value.lower()


class ShockSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    minimum_independent_sources: int = Field(default=2, ge=1, le=10)
    minimum_score_coverage: float = Field(default=0.50, ge=0.0, le=1.0)


class HistoricalSettings(BaseModel):
    """Detection rules for point-in-time, same-security drawdown analogues."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    minimum_drawdown: float = Field(default=-0.15, ge=-1.0, lt=0.0)
    recovery_tolerance: float = Field(default=0.0, ge=0.0, le=0.10)
    maximum_analogues: int = Field(default=5, ge=1, le=25)
    fundamental_minimum_score_coverage: float = Field(
        default=0.0, ge=0.0, le=1.0
    )


class ExportSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csv: bool = True
    excel: bool = True
    filename_prefix: str = "stock_opportunity_scan"

    @model_validator(mode="after")
    def at_least_one_format(self) -> "ExportSettings":
        if not self.csv and not self.excel:
            raise ValueError("at least one export format must be enabled")
        return self


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_root: Path
    paths: PathsSettings
    price: PriceSettings = Field(default_factory=PriceSettings)
    fundamentals: FundamentalsSettings = Field(default_factory=FundamentalsSettings)
    valuation: ValuationSettings = Field(default_factory=ValuationSettings)
    macro: MacroSettings = Field(default_factory=MacroSettings)
    news: NewsSettings = Field(default_factory=NewsSettings)
    shock: ShockSettings = Field(default_factory=ShockSettings)
    historical: HistoricalSettings = Field(default_factory=HistoricalSettings)
    screening: ScreeningSettings = Field(default_factory=ScreeningSettings)
    export: ExportSettings = Field(default_factory=ExportSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


def load_settings(path: str | Path = "config/settings.yaml") -> AppSettings:
    """Load settings and resolve every configured path from the project root."""

    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    configured_root = Path(raw.get("project_root", ".."))
    project_root = (
        configured_root
        if configured_root.is_absolute()
        else (config_path.parent / configured_root).resolve()
    )
    load_dotenv(project_root / ".env", override=False)
    raw["project_root"] = project_root

    path_values = raw.get("paths", {})
    raw["paths"] = {
        key: (
            None
            if value is None
            else value if Path(value).is_absolute() else project_root / value
        )
        for key, value in path_values.items()
    }
    return AppSettings.model_validate(raw)

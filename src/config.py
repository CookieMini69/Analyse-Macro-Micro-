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
    backtest_archive: Path | None = None
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
        normalized = value.lower()
        if normalized not in {"fred", "mixed_official"}:
            raise ValueError("macro provider must be 'fred' or 'mixed_official'")
        return normalized


class FxSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: str = "frankfurter_ecb"
    target_currencies: list[str] = Field(default_factory=lambda: ["USD", "EUR"])
    cache_ttl_hours: int = Field(default=24, ge=0)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_retries: int = Field(default=3, ge=0, le=8)

    @field_validator("provider")
    @classmethod
    def provider_is_supported(cls, value: str) -> str:
        if value.lower() != "frankfurter_ecb":
            raise ValueError("FX provider must be frankfurter_ecb")
        return value.lower()

    @field_validator("target_currencies")
    @classmethod
    def validate_currencies(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values]
        if not normalized or any(len(value) != 3 for value in normalized):
            raise ValueError("FX target currencies must be three-letter codes")
        return list(dict.fromkeys(normalized))


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


class ScenarioSettings(BaseModel):
    """Rules for evidence-derived temporal scenario projections."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    horizons_months: list[int] = Field(
        default_factory=lambda: [3, 6, 12, 18, 24], min_length=1
    )
    target_horizon_months: int = Field(default=12, ge=1, le=120)
    minimum_history_points: int = Field(default=2, ge=1, le=20)
    minimum_target_models: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def validate_horizons(self) -> "ScenarioSettings":
        if any(month < 1 or month > 120 for month in self.horizons_months):
            raise ValueError("scenario horizons must fall within 1..120 months")
        if len(set(self.horizons_months)) != len(self.horizons_months):
            raise ValueError("scenario horizons must be unique")
        if self.target_horizon_months not in self.horizons_months:
            raise ValueError("target_horizon_months must be one configured horizon")
        self.horizons_months.sort()
        return self


class ScoringSettings(BaseModel):
    """Coverage-aware Phase 8 weights; scores are never probabilities."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    fundamental_quality_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    valuation_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    temporary_shock_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    normalization_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    catalyst_weight: float = Field(default=0.10, ge=0.0, le=1.0)
    future_growth_weight: float = Field(default=0.10, ge=0.0, le=1.0)
    risk_weight: float = Field(default=0.10, ge=0.0, le=1.0)
    minimum_subscore_coverage: float = Field(default=0.25, ge=0.0, le=1.0)
    minimum_opportunity_coverage: float = Field(default=0.50, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_weights(self) -> "ScoringSettings":
        total = sum(
            (
                self.fundamental_quality_weight,
                self.valuation_weight,
                self.temporary_shock_weight,
                self.normalization_weight,
                self.catalyst_weight,
                self.future_growth_weight,
                self.risk_weight,
            )
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError("Phase 8 opportunity-score weights must sum to 1.0")
        return self


class BacktestSettings(BaseModel):
    """Strict archived-snapshot backtest configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    archive_live_runs: bool = True
    strict: bool = True
    start_year: int = Field(default=2018, ge=1900, le=2100)
    end_year: int = Field(default=2025, ge=1900, le=2100)
    holding_months: int = Field(default=12, ge=1, le=60)
    minimum_score: float = Field(default=50.0, ge=0.0, le=100.0)
    transaction_cost_bps_per_side: float = Field(default=10.0, ge=0.0, le=500.0)
    annual_risk_free_rate: float = Field(default=0.0, ge=-0.20, le=0.50)
    minimum_trades: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def validate_years(self) -> "BacktestSettings":
        if self.start_year > self.end_year:
            raise ValueError("backtest start_year cannot exceed end_year")
        return self


class HistoricalDataSettings(BaseModel):
    """Licensed point-in-time dataset used to reconstruct historical signals."""

    model_config = ConfigDict(extra="forbid")

    provider: str = "sharadar"
    api_key_env: str = "SHARADAR_API_KEY"
    base_url: str = "https://api.sharadar.com/v1.0/data"
    start_year: int = Field(default=2018, ge=1998, le=2100)
    end_year: int = Field(default=2025, ge=1998, le=2100)
    universe: str = "sp500"
    required_tables: list[str] = Field(
        default_factory=lambda: [
            "tickers", "sp500", "stocks", "fundamentals", "daily", "actions",
            "events",
        ]
    )
    timeout_seconds: int = Field(default=60, ge=1, le=600)

    @field_validator("provider")
    @classmethod
    def provider_is_supported(cls, value: str) -> str:
        if value.lower() != "sharadar":
            raise ValueError("historical_data currently supports only 'sharadar'")
        return value.lower()

    @field_validator("required_tables")
    @classmethod
    def validate_tables(cls, values: list[str]) -> list[str]:
        supported = {
            "tickers", "sp500", "stocks", "fundamentals", "daily", "actions",
            "events",
        }
        normalized = list(dict.fromkeys(value.strip().lower() for value in values))
        if not normalized or any(value not in supported for value in normalized):
            raise ValueError(
                "historical_data.required_tables contains an unsupported table"
            )
        return normalized

    @model_validator(mode="after")
    def validate_years(self) -> "HistoricalDataSettings":
        if self.start_year > self.end_year:
            raise ValueError("historical_data start_year cannot exceed end_year")
        return self


class AiAnalystSettings(BaseModel):
    """Provider boundary for the later evidence-constrained critical analyst."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: str = "openai"
    model: str = "gpt-5.6-terra"
    api_key_env: str = "OPENAI_API_KEY"
    api: str = "responses"
    store: bool = False

    @field_validator("provider")
    @classmethod
    def provider_is_supported(cls, value: str) -> str:
        if value.lower() != "openai":
            raise ValueError("ai_analyst currently supports only 'openai'")
        return value.lower()

    @field_validator("api")
    @classmethod
    def api_is_supported(cls, value: str) -> str:
        if value.lower() != "responses":
            raise ValueError("ai_analyst must use the OpenAI Responses API")
        return value.lower()


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
    fx: FxSettings = Field(default_factory=FxSettings)
    news: NewsSettings = Field(default_factory=NewsSettings)
    shock: ShockSettings = Field(default_factory=ShockSettings)
    historical: HistoricalSettings = Field(default_factory=HistoricalSettings)
    scenario: ScenarioSettings = Field(default_factory=ScenarioSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    backtest: BacktestSettings = Field(default_factory=BacktestSettings)
    historical_data: HistoricalDataSettings = Field(
        default_factory=HistoricalDataSettings
    )
    ai_analyst: AiAnalystSettings = Field(default_factory=AiAnalystSettings)
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

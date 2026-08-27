"""Shared, provenance-aware data models.

Missing external data is represented by ``value=None`` together with
``status=data_unavailable``. The application never substitutes a fabricated
financial value.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DataStatus(StrEnum):
    """Availability state for an external datum or calculated metric."""

    AVAILABLE = "available"
    DATA_UNAVAILABLE = "data_unavailable"
    INVALID = "invalid"
    NOT_APPLICABLE = "not_applicable"


class DataQuality(StrEnum):
    """Coarse quality indicator used in user-facing results."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNAVAILABLE = "UNAVAILABLE"


class ObservationMetadata(BaseModel):
    """Provenance attached to every external financial observation."""

    model_config = ConfigDict(extra="forbid")

    source: str
    source_url: str | None = None
    retrieved_at: datetime
    observation_date: date | datetime | None = None
    period: str | None = None
    currency: str | None = None
    unit: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    status: DataStatus = DataStatus.AVAILABLE

    @model_validator(mode="after")
    def available_observation_has_source_url(self) -> "ObservationMetadata":
        if self.status == DataStatus.AVAILABLE and not self.source_url:
            raise ValueError("an available external observation requires source_url")
        return self


class FinancialMetric(BaseModel):
    """A single numeric metric with complete provenance."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: float | None
    metadata: ObservationMetadata

    @model_validator(mode="after")
    def validate_missing_value_status(self) -> "FinancialMetric":
        if self.value is None and self.metadata.status == DataStatus.AVAILABLE:
            raise ValueError("a null value cannot have status=available")
        if self.value is not None and self.metadata.status == DataStatus.DATA_UNAVAILABLE:
            raise ValueError("a populated value cannot have status=data_unavailable")
        return self


class Security(BaseModel):
    """A listed security configured in the scan universe."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str = Field(min_length=1)
    cik: str | None = Field(default=None, pattern=r"^\d{1,10}$")
    company: str | None = None
    country: str | None = None
    sector: str | None = None
    exchange: str | None = None
    currency: str | None = None
    benchmark: str | None = None
    sector_benchmark: str | None = None
    market_cap: float | None = Field(default=None, ge=0)
    market_cap_currency: str | None = None
    market_cap_source: str | None = None
    market_cap_source_url: str | None = None
    market_cap_observation_date: date | None = None
    market_cap_retrieved_at: datetime | None = None
    market_cap_confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("cik", mode="before")
    @classmethod
    def normalize_cik_input(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError("CIK must contain digits only")
            value = int(value)
        return str(value).strip()

    @model_validator(mode="after")
    def market_cap_has_provenance(self) -> "Security":
        if self.market_cap is None:
            return self
        required = {
            "market_cap_currency": self.market_cap_currency,
            "market_cap_source": self.market_cap_source,
            "market_cap_source_url": self.market_cap_source_url,
            "market_cap_observation_date": self.market_cap_observation_date,
            "market_cap_retrieved_at": self.market_cap_retrieved_at,
            "market_cap_confidence": self.market_cap_confidence,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(
                "market_cap requires provenance fields: " + ", ".join(missing)
            )
        return self


class MetricValue(BaseModel):
    """A calculated metric and its availability state."""

    model_config = ConfigDict(extra="forbid")

    value: float | None
    status: DataStatus
    reason: str | None = None

    @classmethod
    def available(cls, value: float) -> "MetricValue":
        return cls(value=float(value), status=DataStatus.AVAILABLE)

    @classmethod
    def unavailable(cls, reason: str) -> "MetricValue":
        return cls(value=None, status=DataStatus.DATA_UNAVAILABLE, reason=reason)


class AvailabilityPrecision(StrEnum):
    """Precision of the first-public-availability timestamp."""

    ACCEPTANCE_TIMESTAMP = "acceptance_timestamp"
    FILED_DATE = "filed_date"


class FundamentalObservation(BaseModel):
    """One as-filed SEC XBRL fact with point-in-time availability metadata."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: float | None
    taxonomy: str
    concept: str
    unit: str | None = None
    currency: str | None = None
    start_date: date | None = None
    end_date: date
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str
    accession: str
    filed_date: date
    accepted_at: datetime | None = None
    available_at: datetime
    availability_precision: AvailabilityPrecision
    source: str = "SEC EDGAR"
    source_url: str
    retrieved_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    status: DataStatus = DataStatus.AVAILABLE

    @model_validator(mode="after")
    def validate_observation(self) -> "FundamentalObservation":
        if self.value is None and self.status == DataStatus.AVAILABLE:
            raise ValueError("an available fundamental observation requires a value")
        if self.start_date and self.start_date > self.end_date:
            raise ValueError("start_date cannot be after end_date")
        return self


class CalculatedFundamentalMetric(BaseModel):
    """A derived metric with formula, period, inputs, and source accessions."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: float | None
    unit: str | None = None
    status: DataStatus
    reason: str | None = None
    formula: str | None = None
    inputs: list[str] = Field(default_factory=list)
    period_start: date | None = None
    period_end: date | None = None
    source_accessions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_value_status(self) -> "CalculatedFundamentalMetric":
        if self.value is None and self.status == DataStatus.AVAILABLE:
            raise ValueError("an available calculated metric requires a value")
        if self.value is not None and self.status != DataStatus.AVAILABLE:
            raise ValueError("a populated calculated metric must have status=available")
        return self


class FundamentalScoreComponent(BaseModel):
    """One quality-score pillar with explicit metric coverage."""

    model_config = ConfigDict(extra="forbid")

    name: str
    observed_score: float | None = Field(default=None, ge=0.0, le=100.0)
    adjusted_score: float | None = Field(default=None, ge=0.0, le=100.0)
    coverage: float = Field(ge=0.0, le=1.0)
    metric_scores: dict[str, float | None] = Field(default_factory=dict)


class FundamentalQualityScore(BaseModel):
    """Coverage-adjusted quality score; never a probability of profit."""

    model_config = ConfigDict(extra="forbid")

    score: float | None = Field(default=None, ge=0.0, le=100.0)
    observed_score: float | None = Field(default=None, ge=0.0, le=100.0)
    coverage: float = Field(ge=0.0, le=1.0)
    status: DataStatus
    methodology_version: str = "fundamental-quality-v1"
    components: dict[str, FundamentalScoreComponent] = Field(default_factory=dict)
    reason: str | None = None


class FundamentalAnalysisResult(BaseModel):
    """Point-in-time SEC history, calculated metrics, and quality score."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    cik: str | None = None
    company: str | None = None
    as_of: datetime
    status: DataStatus
    data_quality: DataQuality
    annual_observations: dict[str, list[FundamentalObservation]] = Field(
        default_factory=dict
    )
    metrics: dict[str, CalculatedFundamentalMetric] = Field(default_factory=dict)
    quality_score: FundamentalQualityScore
    latest_period_end: date | None = None
    retrieved_at: datetime
    sources: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class HistoricalMultiplePoint(BaseModel):
    """One annual multiple using the first close after public filing availability."""

    model_config = ConfigDict(extra="forbid")

    value: float
    fiscal_period_end: date
    available_at: datetime
    price: float
    price_date: date
    source_accessions: list[str] = Field(default_factory=list)
    market_cap_basis: str | None = None


class ValuationMultiple(BaseModel):
    """Current, historical, and peer references for one valuation multiple."""

    model_config = ConfigDict(extra="forbid")

    name: str
    formula: str
    current: MetricValue
    historical_median: MetricValue
    sector_median: MetricValue
    history: list[HistoricalMultiplePoint] = Field(default_factory=list)
    market_cap_basis: str | None = None
    sector_peer_count: int = Field(default=0, ge=0)


class DcfProjectionYear(BaseModel):
    """Auditable annual unlevered cash-flow projection."""

    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=1)
    revenue: float
    ebit: float
    nopat: float
    depreciation_amortization: float
    capex: float
    working_capital_investment: float
    unlevered_free_cash_flow: float
    discount_factor: float
    present_value: float


class DcfScenarioResult(BaseModel):
    """DCF output tied to dated, sourced scenario assumptions."""

    model_config = ConfigDict(extra="forbid")

    scenario: str
    status: DataStatus
    enterprise_value: float | None = None
    equity_value: float | None = None
    value_per_share: float | None = None
    terminal_value: float | None = None
    terminal_value_present_value: float | None = None
    projected_cash_flow_present_value: float | None = None
    assumption_date: date | None = None
    assumption_source: str | None = None
    assumptions: dict[str, Any] = Field(default_factory=dict)
    projections: list[DcfProjectionYear] = Field(default_factory=list)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_dcf_status(self) -> "DcfScenarioResult":
        populated = self.value_per_share is not None
        if populated and self.status != DataStatus.AVAILABLE:
            raise ValueError("a populated DCF result must have status=available")
        if not populated and self.status == DataStatus.AVAILABLE:
            raise ValueError("an available DCF result requires value_per_share")
        return self


class ReverseDcfResult(BaseModel):
    """Constant revenue growth implied by the point-in-time market price."""

    model_config = ConfigDict(extra="forbid")

    implied_revenue_growth: float | None = None
    target_enterprise_value: float | None = None
    solved_enterprise_value: float | None = None
    status: DataStatus
    lower_bound: float
    upper_bound: float
    iterations: int = Field(default=0, ge=0)
    reason: str | None = None


class ValuationScoreComponent(BaseModel):
    """One valuation signal; missing references are not imputed."""

    model_config = ConfigDict(extra="forbid")

    name: str
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    weight: float = Field(ge=0.0, le=1.0)
    signals: dict[str, float | None] = Field(default_factory=dict)
    reason: str | None = None


class ValuationScore(BaseModel):
    """Coverage-adjusted valuation score; it is not a return probability."""

    model_config = ConfigDict(extra="forbid")

    score: float | None = Field(default=None, ge=0.0, le=100.0)
    observed_score: float | None = Field(default=None, ge=0.0, le=100.0)
    coverage: float = Field(ge=0.0, le=1.0)
    status: DataStatus
    methodology_version: str = "valuation-v1"
    components: dict[str, ValuationScoreComponent] = Field(default_factory=dict)
    reason: str | None = None


class ValuationAnalysisResult(BaseModel):
    """Point-in-time multiples, DCF scenarios, reverse DCF, and score."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    company: str | None = None
    sector: str | None = None
    as_of: datetime
    valuation_price: float | None = None
    valuation_price_date: date | None = None
    valuation_currency: str | None = None
    market_cap: float | None = None
    market_cap_basis: str | None = None
    status: DataStatus
    data_quality: DataQuality
    multiples: dict[str, ValuationMultiple] = Field(default_factory=dict)
    dcf_scenarios: dict[str, DcfScenarioResult] = Field(default_factory=dict)
    reverse_dcf: ReverseDcfResult | None = None
    score: ValuationScore
    retrieved_at: datetime
    sources: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class MacroObservation(BaseModel):
    """One FRED/ALFRED observation valid at an explicit real-time cutoff."""

    model_config = ConfigDict(extra="forbid")

    series_key: str
    series_id: str
    series_title: str
    value: float
    observation_date: date
    realtime_start: date
    realtime_end: date
    as_of: datetime
    frequency: str | None = None
    unit: str | None = None
    seasonal_adjustment: str | None = None
    source: str = "Federal Reserve Bank of St. Louis FRED/ALFRED"
    source_url: str
    retrieved_at: datetime
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: DataStatus = DataStatus.AVAILABLE

    @model_validator(mode="after")
    def observation_respects_cutoff(self) -> "MacroObservation":
        if self.observation_date > self.as_of.date():
            raise ValueError("macro observation cannot postdate its point-in-time cutoff")
        return self


class MacroSeriesResult(BaseModel):
    """Point-in-time history for one configured macro series."""

    model_config = ConfigDict(extra="forbid")

    series_key: str
    series_id: str
    configured_name: str
    as_of: datetime
    status: DataStatus
    data_quality: DataQuality
    observations: list[MacroObservation] = Field(default_factory=list)
    retrieved_at: datetime
    source_url: str
    from_cache: bool = False
    error: str | None = None


class MacroSeriesAnalysis(BaseModel):
    """Latest level and raw changes; no causal interpretation is embedded."""

    model_config = ConfigDict(extra="forbid")

    series_key: str
    series_id: str
    title: str
    as_of: datetime
    latest_value: float | None = None
    latest_observation_date: date | None = None
    unit: str | None = None
    frequency: str | None = None
    changes: dict[str, MetricValue] = Field(default_factory=dict)
    status: DataStatus
    data_quality: DataQuality
    source_url: str
    error: str | None = None


class NewsArticle(BaseModel):
    """Public article metadata indexed by GDELT; no copyrighted body is stored."""

    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    source_domain: str | None = None
    seen_at: datetime
    language: str | None = None
    source_country: str | None = None
    query: str
    index_source: str = "GDELT DOC 2.0 API"
    index_source_url: str
    retrieved_at: datetime
    confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    status: DataStatus = DataStatus.AVAILABLE


class NewsSearchResult(BaseModel):
    """Cutoff-filtered news metadata for one security."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    company: str | None = None
    query: str
    window_start: datetime
    as_of: datetime
    status: DataStatus
    data_quality: DataQuality
    articles: list[NewsArticle] = Field(default_factory=list)
    retrieved_at: datetime
    source_url: str
    from_cache: bool = False
    error: str | None = None


class ShockCategory(StrEnum):
    GEOPOLITICAL = "GEOPOLITICAL"
    MACRO = "MACRO"
    INTEREST_RATES = "INTEREST_RATES"
    INFLATION = "INFLATION"
    COMMODITIES = "COMMODITIES"
    REGULATION = "REGULATION"
    LEGAL = "LEGAL"
    EARNINGS = "EARNINGS"
    GUIDANCE = "GUIDANCE"
    COMPETITION = "COMPETITION"
    PRODUCT = "PRODUCT"
    MANAGEMENT = "MANAGEMENT"
    OPERATIONAL = "OPERATIONAL"
    SUPPLY_CHAIN = "SUPPLY_CHAIN"
    CYCLICAL = "CYCLICAL"
    UNKNOWN = "UNKNOWN"


class ShockNature(StrEnum):
    TEMPORARY = "TEMPORARY"
    PROBABLY_TEMPORARY = "PROBABLY_TEMPORARY"
    UNCERTAIN = "UNCERTAIN"
    STRUCTURAL = "STRUCTURAL"
    SEVERE_STRUCTURAL = "SEVERE_STRUCTURAL"


class ShockEvidence(BaseModel):
    """A matched headline with the exact terms used by the classifier."""

    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    source_domain: str | None = None
    seen_at: datetime
    category: ShockCategory | None = None
    matched_terms: list[str] = Field(default_factory=list)
    temporary_terms: list[str] = Field(default_factory=list)
    resolution_terms: list[str] = Field(default_factory=list)
    damage_terms: list[str] = Field(default_factory=list)
    structural_terms: list[str] = Field(default_factory=list)
    severe_structural_terms: list[str] = Field(default_factory=list)


class MacroAssociation(BaseModel):
    """Arithmetic alignment with a configured exposure; explicitly not causality."""

    model_config = ConfigDict(extra="forbid")

    series_key: str
    series_id: str
    coefficient: float
    latest_value: float | None = None
    change_horizon: str | None = None
    observed_change: float | None = None
    aligned_with_headwind: bool | None = None
    rationale: str
    assumption_date: date
    assumption_source: str
    interpretation: str = "configured sensitivity association; not proof of causality"
    status: DataStatus
    reason: str | None = None


class TemporaryShockScoreComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    weight: float = Field(ge=0.0, le=1.0)
    observed: bool
    evidence: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class TemporaryShockScore(BaseModel):
    """Coverage-adjusted evidence score; never a normalization probability."""

    model_config = ConfigDict(extra="forbid")

    score: float | None = Field(default=None, ge=0.0, le=100.0)
    observed_score: float | None = Field(default=None, ge=0.0, le=100.0)
    coverage: float = Field(ge=0.0, le=1.0)
    status: DataStatus
    methodology_version: str = "temporary-shock-v1"
    components: dict[str, TemporaryShockScoreComponent] = Field(default_factory=dict)
    reason: str | None = None


class ShockAnalysisResult(BaseModel):
    """Evidence-backed headline classification with conservative shock nature."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    company: str | None = None
    as_of: datetime
    category: ShockCategory
    nature: ShockNature
    status: DataStatus
    data_quality: DataQuality
    temporary_score: TemporaryShockScore
    evidence: list[ShockEvidence] = Field(default_factory=list)
    macro_associations: list[MacroAssociation] = Field(default_factory=list)
    independent_source_count: int = Field(default=0, ge=0)
    conclusion: str
    retrieved_at: datetime
    sources: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class OpportunityCandidate(BaseModel):
    """Price candidate enriched with point-in-time fundamentals, value, and shock."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    company: str | None = None
    country: str | None = None
    sector: str | None = None
    exchange: str | None = None
    currency: str | None = None
    market_cap: float | None = None
    market_cap_currency: str | None = None
    current_price: float | None = None
    price_basis: str | None = None
    observation_date: date | None = None
    drawdown_ath: float | None = None
    drawdown_52w: float | None = None
    drawdown_1m: float | None = None
    drawdown_3m: float | None = None
    drawdown_6m: float | None = None
    drawdown_ytd: float | None = None
    drawdown_1y: float | None = None
    distance_ma50: float | None = None
    distance_ma200: float | None = None
    rsi: float | None = None
    volatility: float | None = None
    beta: float | None = None
    relative_benchmark_performance: float | None = None
    relative_sector_performance: float | None = None
    fundamental_quality_score: float | None = None
    fundamental_quality_observed_score: float | None = None
    fundamental_quality_coverage: float | None = None
    fundamental_growth_score: float | None = None
    fundamental_profitability_score: float | None = None
    fundamental_balance_sheet_score: float | None = None
    fundamental_cash_flow_score: float | None = None
    fundamental_data_quality: DataQuality | None = None
    fundamental_status: DataStatus | None = None
    fundamental_as_of: datetime | None = None
    fundamental_latest_period_end: date | None = None
    fundamental_metrics: dict[str, float | None] = Field(default_factory=dict)
    valuation_score: float | None = None
    valuation_observed_score: float | None = None
    valuation_coverage: float | None = None
    valuation_status: DataStatus | None = None
    valuation_data_quality: DataQuality | None = None
    valuation_as_of: datetime | None = None
    valuation_price: float | None = None
    valuation_price_date: date | None = None
    pe_current: float | None = None
    pe_historical_median: float | None = None
    pe_sector_median: float | None = None
    ev_ebitda_current: float | None = None
    ev_ebitda_historical_median: float | None = None
    ev_ebitda_sector_median: float | None = None
    price_fcf_current: float | None = None
    price_fcf_historical_median: float | None = None
    price_fcf_sector_median: float | None = None
    dcf_bear_value_per_share: float | None = None
    dcf_base_value_per_share: float | None = None
    dcf_bull_value_per_share: float | None = None
    normalized_value_per_share: float | None = None
    reverse_dcf_implied_revenue_growth: float | None = None
    valuation_metrics: dict[str, Any] = Field(default_factory=dict)
    shock_category: ShockCategory | None = None
    shock_nature: ShockNature | None = None
    temporary_shock_score: float | None = None
    temporary_shock_observed_score: float | None = None
    temporary_shock_coverage: float | None = None
    shock_status: DataStatus | None = None
    shock_data_quality: DataQuality | None = None
    shock_as_of: datetime | None = None
    shock_evidence_count: int | None = None
    shock_independent_source_count: int | None = None
    shock_conclusion: str | None = None
    shock_metrics: dict[str, Any] = Field(default_factory=dict)
    decline_severity_score: float = Field(ge=0.0, le=100.0)
    is_candidate: bool
    candidate_reasons: list[str] = Field(default_factory=list)
    rank: int | None = Field(default=None, ge=1)
    data_quality: DataQuality
    metric_statuses: dict[str, DataStatus] = Field(default_factory=dict)
    missing_metrics: list[str] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_at: datetime

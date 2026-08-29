"""Coverage-aware Phase 8 opportunity scoring from point-in-time evidence."""

from __future__ import annotations

from datetime import UTC, datetime

from src.config import ScoringSettings
from src.models import (
    DataQuality,
    DataStatus,
    EvidenceScore,
    FundamentalAnalysisResult,
    HistoricalAnalogueResult,
    ScenarioAnalysisResult,
    ScoreComponent,
    ScoringAnalysisResult,
    Security,
    ShockAnalysisResult,
    ValuationAnalysisResult,
)
from src.scoring.confidence import (
    build_evidence_score,
    piecewise_score,
    preserve_source_score,
    scoring_data_quality,
)
from src.scoring.risk import score_risk_resilience


def analyze_opportunity_score(
    security: Security,
    fundamental: FundamentalAnalysisResult | None,
    valuation: ValuationAnalysisResult | None,
    shock: ShockAnalysisResult | None,
    historical: HistoricalAnalogueResult | None,
    scenario: ScenarioAnalysisResult | None,
    settings: ScoringSettings,
    *,
    as_of: datetime,
    volatility: float | None,
    beta: float | None,
) -> ScoringAnalysisResult:
    """Calculate analytical scores without converting them to probabilities."""

    fundamental = _eligible(fundamental, as_of)
    valuation = _eligible(valuation, as_of)
    shock = _eligible(shock, as_of)
    historical = _eligible(historical, as_of)
    scenario = _eligible(scenario, as_of)
    fundamental_score = _fundamental_score(fundamental)
    valuation_score = _valuation_score(valuation)
    temporary_score = _temporary_score(shock)
    normalization_score = _normalization_score(
        scenario, historical, temporary_score,
        minimum_coverage=settings.minimum_subscore_coverage,
    )
    catalyst_score = _catalyst_score(
        shock, minimum_coverage=settings.minimum_subscore_coverage
    )
    growth_score = _future_growth_score(
        fundamental, minimum_coverage=settings.minimum_subscore_coverage
    )
    risk_score = score_risk_resilience(
        fundamental,
        scenario,
        shock,
        volatility=volatility,
        beta=beta,
        minimum_coverage=settings.minimum_subscore_coverage,
    )
    inputs = {
        "fundamental_quality": (fundamental_score, settings.fundamental_quality_weight),
        "valuation": (valuation_score, settings.valuation_weight),
        "temporary_shock": (temporary_score, settings.temporary_shock_weight),
        "normalization": (normalization_score, settings.normalization_weight),
        "catalyst": (catalyst_score, settings.catalyst_weight),
        "future_growth": (growth_score, settings.future_growth_weight),
        "risk_resilience": (risk_score, settings.risk_weight),
    }
    opportunity = build_evidence_score(
        "temporary_mispricing_opportunity",
        {
            name: ScoreComponent(
                name=name,
                score=score.score if score.status == DataStatus.AVAILABLE else None,
                weight=weight,
                observed=score.status == DataStatus.AVAILABLE and score.score is not None,
                source=score.methodology_version,
                evidence={
                    "subscore_coverage": score.coverage,
                    "subscore_observed_score": score.observed_score,
                },
                reason=score.reason,
            )
            for name, (score, weight) in inputs.items()
        },
        minimum_coverage=settings.minimum_opportunity_coverage,
        methodology_version="temporary-mispricing-opportunity-v1",
    )
    evidence_coverage = sum(
        weight * score.coverage for score, weight in inputs.values()
    )
    statuses = [
        item.status
        for item in (fundamental, valuation, shock, historical, scenario)
        if item is not None
    ]
    qualities = [
        item.data_quality
        for item in (fundamental, valuation, shock, historical, scenario)
        if item is not None
    ]
    quality = scoring_data_quality(
        coverage=evidence_coverage, statuses=statuses, qualities=qualities
    )
    retrieved_at = max(
        [datetime.now(UTC)]
        + [
            item.retrieved_at
            for item in (fundamental, valuation, shock, historical, scenario)
            if item is not None
        ]
    )
    return ScoringAnalysisResult(
        ticker=security.ticker,
        company=security.company,
        as_of=as_of,
        status=opportunity.status,
        data_quality=quality,
        fundamental_quality=fundamental_score,
        valuation=valuation_score,
        temporary_shock=temporary_score,
        normalization=normalization_score,
        catalyst=catalyst_score,
        future_growth=growth_score,
        risk=risk_score,
        opportunity=opportunity,
        confidence_score=round(evidence_coverage * 100, 2),
        score_band=_score_band(opportunity),
        retrieved_at=retrieved_at,
        sources=_sources(fundamental, valuation, shock, historical, scenario),
        error=opportunity.reason,
    )


def _fundamental_score(
    result: FundamentalAnalysisResult | None,
) -> EvidenceScore:
    source = result.quality_score if result is not None else None
    return preserve_source_score(
        "fundamental_quality",
        score=source.score if source is not None else None,
        observed_score=source.observed_score if source is not None else None,
        coverage=source.coverage if source is not None else 0.0,
        status=source.status if source is not None else DataStatus.DATA_UNAVAILABLE,
        methodology_version=(
            source.methodology_version if source is not None else "fundamental-quality-v1"
        ),
        source="Phase 3 SEC point-in-time fundamental engine",
    )


def _valuation_score(result: ValuationAnalysisResult | None) -> EvidenceScore:
    source = result.score if result is not None else None
    return preserve_source_score(
        "valuation",
        score=source.score if source is not None else None,
        observed_score=source.observed_score if source is not None else None,
        coverage=source.coverage if source is not None else 0.0,
        status=source.status if source is not None else DataStatus.DATA_UNAVAILABLE,
        methodology_version=source.methodology_version if source is not None else "valuation-v1",
        source="Phase 4 point-in-time valuation engine",
    )


def _temporary_score(result: ShockAnalysisResult | None) -> EvidenceScore:
    source = result.temporary_score if result is not None else None
    return preserve_source_score(
        "temporary_shock",
        score=source.score if source is not None else None,
        observed_score=source.observed_score if source is not None else None,
        coverage=source.coverage if source is not None else 0.0,
        status=source.status if source is not None else DataStatus.DATA_UNAVAILABLE,
        methodology_version=(
            source.methodology_version if source is not None else "temporary-shock-v1"
        ),
        source="Phase 5 conservative shock engine",
    )


def _future_growth_score(
    fundamental: FundamentalAnalysisResult | None, *, minimum_coverage: float
) -> EvidenceScore:
    component = (
        fundamental.quality_score.components.get("growth")
        if fundamental is not None else None
    )
    coverage = component.coverage if component is not None else 0.0
    observed = component.observed_score if component is not None else None
    components = {
        "observed_growth_metrics": ScoreComponent(
            name="observed_growth_metrics",
            score=observed,
            weight=coverage,
            observed=observed is not None,
            source="SEC annual growth metrics",
            evidence={
                "metric_scores": component.metric_scores if component is not None else {},
                "metric_coverage": coverage,
            },
            reason=None if observed is not None else "growth metrics are unavailable",
        ),
        "missing_growth_metrics": ScoreComponent(
            name="missing_growth_metrics",
            score=None,
            weight=1.0 - coverage,
            observed=False,
            source="SEC annual growth metrics",
            reason="uncovered growth metrics",
        ),
    }
    return build_evidence_score(
        "future_growth",
        components,
        minimum_coverage=minimum_coverage,
        methodology_version="future-growth-v1",
    )


def _normalization_score(
    scenario: ScenarioAnalysisResult | None,
    historical: HistoricalAnalogueResult | None,
    temporary: EvidenceScore,
    *,
    minimum_coverage: float,
) -> EvidenceScore:
    base_upside = scenario.risk_reward.upside_base.value if scenario is not None else None
    analogue_return = _analogue_return(historical)
    analogue_count = len(historical.analogues) if historical is not None else 0
    best_similarity = historical.best_similarity_score if historical is not None else None
    precedent = (
        min(100.0, best_similarity * min(1.0, analogue_count / 3.0))
        if best_similarity is not None and analogue_count else None
    )
    values = {
        "base_case_revaluation": (
            piecewise_score(
                base_upside, ((-0.50, 0), (-0.20, 20), (0.0, 50), (0.25, 75), (0.50, 100))
            ) if base_upside is not None else None,
            0.35,
            {"base_upside": base_upside},
        ),
        "historical_12m_outcome": (
            piecewise_score(
                analogue_return,
                ((-0.50, 0), (-0.20, 20), (0.0, 50), (0.25, 75), (0.50, 100)),
            ) if analogue_return is not None else None,
            0.30,
            {"similarity_weighted_12m_return": analogue_return},
        ),
        "historical_recovery_precedent": (
            precedent,
            0.20,
            {"analogue_count": analogue_count, "best_similarity": best_similarity},
        ),
        "shock_resolution_evidence": (
            temporary.score if temporary.status == DataStatus.AVAILABLE else None,
            0.15,
            {"temporary_shock_score": temporary.score},
        ),
    }
    return build_evidence_score(
        "normalization",
        {
            name: _component(name, score, weight, "audited normalization evidence", evidence)
            for name, (score, weight, evidence) in values.items()
        },
        minimum_coverage=minimum_coverage,
        methodology_version="normalization-score-v1",
    )


def _catalyst_score(
    shock: ShockAnalysisResult | None, *, minimum_coverage: float
) -> EvidenceScore:
    resolution = None
    if shock is not None and shock.evidence:
        component = shock.temporary_score.components.get("resolution_evidence")
        resolution = component.score if component is not None and component.observed else 0.0
    available_associations = [
        item for item in (shock.macro_associations if shock is not None else [])
        if item.status == DataStatus.AVAILABLE and item.aligned_with_headwind is not None
    ]
    macro_relief = (
        100.0 * sum(not item.aligned_with_headwind for item in available_associations)
        / len(available_associations)
        if available_associations else None
    )
    return build_evidence_score(
        "catalyst",
        {
            "explicit_resolution_language": _component(
                "explicit_resolution_language", resolution, 0.75,
                "dated headline resolution terms",
                {"classified_evidence_count": len(shock.evidence) if shock else 0},
            ),
            "configured_macro_relief": _component(
                "configured_macro_relief", macro_relief, 0.25,
                "dated configured macro associations; not causality",
                {"association_count": len(available_associations)},
            ),
        },
        minimum_coverage=minimum_coverage,
        methodology_version="catalyst-score-v1",
    )


def _analogue_return(historical: HistoricalAnalogueResult | None) -> float | None:
    if historical is None:
        return None
    weighted: list[tuple[float, float]] = []
    for analogue in historical.analogues:
        metric = analogue.episode.subsequent_returns.get("return_12m")
        if metric is not None and metric.value is not None:
            weighted.append((metric.value, max(analogue.similarity_score / 100.0, 0.01)))
    total = sum(weight for _, weight in weighted)
    return sum(value * weight for value, weight in weighted) / total if total else None


def _component(
    name: str,
    score: float | None,
    weight: float,
    source: str,
    evidence: dict[str, object],
) -> ScoreComponent:
    return ScoreComponent(
        name=name,
        score=round(score, 4) if score is not None else None,
        weight=weight,
        observed=score is not None,
        source=source,
        evidence=evidence,
        reason=None if score is not None else f"{name} evidence is unavailable",
    )


def _score_band(score: EvidenceScore) -> str:
    if score.score is None:
        return "INSUFFICIENT_DATA"
    if score.score < 50:
        return "LOW_SCORE"
    if score.score < 60:
        return "LIMITED_SCORE"
    if score.score < 70:
        return "WATCHLIST_SCORE"
    if score.score < 80:
        return "ELEVATED_SCORE"
    return "HIGH_SCORE"


def _eligible(result, as_of: datetime):
    return result if result is not None and result.as_of <= as_of else None


def _sources(*results) -> list[dict[str, object]]:
    sources: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for result in results:
        if result is None:
            continue
        result_sources = getattr(result, "sources", None)
        if result_sources is None:
            result_sources = [
                {
                    "source": getattr(result, "source", ""),
                    "source_url": getattr(result, "source_url", None),
                }
            ]
        for source in result_sources:
            key = (
                str(source.get("source") or ""),
                str(source.get("source_url") or source.get("url") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            sources.append(source)
    return sources


__all__ = ["analyze_opportunity_score"]

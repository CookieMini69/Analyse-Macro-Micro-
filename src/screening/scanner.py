"""Build auditable V1 scan rows from validated price histories."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from src.config import ScreeningSettings
from src.data.sources import PriceHistoryResult
from src.models import DataQuality, DataStatus, OpportunityCandidate
from src.screening.anomaly import candidate_reasons, decline_severity_score
from src.screening.drawdown import calculate_price_metrics


def _last_non_null(frame: pd.DataFrame, column: str) -> object | None:
    if frame.empty or column not in frame:
        return None
    values = frame[column].dropna()
    return values.iloc[-1] if not values.empty else None


def _combine_quality(source_quality: DataQuality, missing_count: int, total: int) -> DataQuality:
    if source_quality == DataQuality.UNAVAILABLE:
        return DataQuality.UNAVAILABLE
    completeness = 1 - (missing_count / total if total else 1)
    if source_quality == DataQuality.MEDIUM and completeness >= 0.70:
        return DataQuality.MEDIUM
    return DataQuality.LOW


def build_scan_result(
    price_result: PriceHistoryResult,
    settings: ScreeningSettings,
    *,
    benchmark_result: PriceHistoryResult | None = None,
    sector_result: PriceHistoryResult | None = None,
) -> OpportunityCandidate:
    security = price_result.security
    calculated = calculate_price_metrics(
        price_result.frame,
        benchmark_frame=benchmark_result.frame if benchmark_result else None,
        sector_frame=sector_result.frame if sector_result else None,
        rsi_period=settings.rsi_period,
        annualization_days=settings.annualization_days,
    )
    values = calculated.values
    statuses = {name: metric.status for name, metric in values.items()}
    missing = [name for name, metric in values.items() if metric.value is None]
    reasons = candidate_reasons(values, settings)
    enough_observations = len(price_result.frame) >= settings.minimum_observations
    is_candidate = (
        bool(reasons)
        and enough_observations
        and calculated.current_price is not None
        and price_result.status == DataStatus.AVAILABLE
    )

    sources = [
        {
            "name": price_result.source,
            "url": price_result.source_url,
            "status": price_result.status.value,
            "from_cache": price_result.from_cache,
        }
    ]
    if security.market_cap is not None:
        sources.append(
            {
                "name": security.market_cap_source,
                "url": security.market_cap_source_url,
                "status": DataStatus.AVAILABLE.value,
                "role": "market_cap",
                "observation_date": (
                    security.market_cap_observation_date.isoformat()
                    if security.market_cap_observation_date
                    else None
                ),
                "retrieved_at": (
                    security.market_cap_retrieved_at.isoformat()
                    if security.market_cap_retrieved_at
                    else None
                ),
                "currency": security.market_cap_currency,
                "unit": security.market_cap_currency,
                "confidence": security.market_cap_confidence,
            }
        )
    for label, result in (("benchmark", benchmark_result), ("sector_benchmark", sector_result)):
        if result is not None:
            sources.append(
                {
                    "name": result.source,
                    "url": result.source_url,
                    "status": result.status.value,
                    "role": label,
                    "ticker": result.security.ticker,
                    "from_cache": result.from_cache,
                }
            )

    retrieved_at = datetime.now(UTC)
    if not price_result.frame.empty and "retrieved_at" in price_result.frame:
        parsed = price_result.frame["retrieved_at"].dropna()
        if not parsed.empty:
            candidate_timestamp = parsed.iloc[-1]
            if not isinstance(candidate_timestamp, datetime):
                candidate_timestamp = datetime.fromisoformat(str(candidate_timestamp))
            if candidate_timestamp.tzinfo is None:
                candidate_timestamp = candidate_timestamp.replace(tzinfo=UTC)
            retrieved_at = candidate_timestamp

    metric_values = {name: metric.value for name, metric in values.items()}
    return OpportunityCandidate(
        ticker=security.ticker,
        company=security.company,
        country=security.country,
        listing_country=security.listing_country,
        country_basis=security.country_basis,
        region=security.region,
        sector=security.sector,
        exchange=security.exchange or _last_non_null(price_result.frame, "exchange"),
        currency=security.currency or _last_non_null(price_result.frame, "currency"),
        index_memberships=security.index_memberships,
        market_cap=security.market_cap,
        market_cap_currency=security.market_cap_currency,
        current_price=calculated.current_price,
        price_basis=calculated.price_basis,
        observation_date=calculated.observation_date,
        decline_severity_score=decline_severity_score(values),
        is_candidate=is_candidate,
        candidate_reasons=reasons,
        data_quality=_combine_quality(price_result.data_quality, len(missing), len(values)),
        metric_statuses=statuses,
        missing_metrics=missing,
        sources=sources,
        retrieved_at=retrieved_at,
        **metric_values,
    )


def rank_results(results: list[OpportunityCandidate]) -> list[OpportunityCandidate]:
    """Sort candidates first by decline severity and assign candidate-only ranks."""

    ordered = sorted(
        results,
        key=lambda item: (item.is_candidate, item.decline_severity_score),
        reverse=True,
    )
    rank = 0
    ranked: list[OpportunityCandidate] = []
    for result in ordered:
        if result.is_candidate:
            rank += 1
            result = result.model_copy(update={"rank": rank})
        ranked.append(result)
    return ranked

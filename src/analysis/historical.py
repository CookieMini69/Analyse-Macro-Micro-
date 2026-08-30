"""Point-in-time detection and comparison of same-security drawdown episodes."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Iterable

import pandas as pd

from src.analysis.fundamentals import analyze_fundamentals
from src.config import HistoricalSettings
from src.data.fundamentals import FundamentalDataResult, normalize_as_of
from src.data.sources import PriceHistoryResult
from src.models import (
    DataQuality,
    DataStatus,
    FundamentalAnalysisResult,
    HistoricalAnalogue,
    HistoricalAnalogueResult,
    HistoricalContextSnapshot,
    HistoricalEpisode,
    MetricValue,
    Security,
    ValuationAnalysisResult,
)

SIMILARITY_WEIGHTS = {
    "maximum_drawdown": 0.35,
    "decline_duration": 0.20,
    "fundamentals": 0.25,
    "valuation": 0.20,
}
RETURN_HORIZONS_MONTHS = {"return_3m": 3, "return_6m": 6, "return_12m": 12, "return_24m": 24}
FUNDAMENTAL_SNAPSHOT_METRICS = (
    "revenue", "revenue_cagr", "gross_margin", "operating_margin", "net_margin",
    "roic", "debt_to_equity", "cash_to_debt", "current_ratio",
    "free_cash_flow", "fcf_margin",
)
FUNDAMENTAL_SIMILARITY_METRICS = (
    "revenue_cagr", "gross_margin", "operating_margin", "net_margin", "roic",
    "debt_to_equity", "cash_to_debt", "current_ratio", "fcf_margin",
)


def analyze_historical_analogues(
    security: Security,
    prices: PriceHistoryResult,
    settings: HistoricalSettings,
    *,
    as_of: datetime,
    fundamental: FundamentalAnalysisResult | None = None,
    valuation: ValuationAnalysisResult | None = None,
) -> HistoricalAnalogueResult:
    """Compare the active drawdown with completed prior episodes.

    The pipeline supplies cutoff-filtered prices and this public function filters
    again defensively. Fundamental and valuation snapshots are reconstructed at
    each episode peak, so later data cannot leak into an older comparison.
    """

    frame = _normalized_price_path(prices.frame)
    eligible_date = as_of.date()
    if as_of.time() < time(23, 59, 59):
        eligible_date -= timedelta(days=1)
    frame = frame.loc[frame["date"] <= eligible_date].reset_index(drop=True)
    retrieved_at = _retrieved_at(prices.frame)
    if frame.empty:
        return _empty_result(
            security, prices, as_of, retrieved_at, DataStatus.DATA_UNAVAILABLE,
            prices.error or "no usable price observations",
        )

    completed, current = detect_drawdown_episodes(
        frame,
        minimum_drawdown=settings.minimum_drawdown,
        recovery_tolerance=settings.recovery_tolerance,
    )
    if current is None:
        return _empty_result(
            security, prices, as_of, retrieved_at, DataStatus.NOT_APPLICABLE,
            "no active drawdown reaches the configured threshold "
            f"{settings.minimum_drawdown:.2%}",
            completed_count=len(completed),
        )

    current = _attach_context(current, security, fundamental, valuation, settings)
    enriched_completed = [
        _attach_context(
            episode.model_copy(
                update={"subsequent_returns": _subsequent_returns(frame, episode.trough_date)}
            ),
            security, fundamental, valuation, settings,
        )
        for episode in completed
    ]
    analogues = [_compare_episodes(current, episode) for episode in enriched_completed]
    analogues.sort(
        key=lambda item: (item.similarity_score, item.episode.peak_date), reverse=True
    )
    analogues = analogues[: settings.maximum_analogues]
    if not analogues:
        return HistoricalAnalogueResult(
            ticker=security.ticker,
            company=security.company,
            as_of=as_of,
            status=DataStatus.DATA_UNAVAILABLE,
            data_quality=DataQuality.UNAVAILABLE,
            current_episode=current,
            analogues=[],
            detected_completed_episode_count=0,
            best_similarity_score=None,
            similarity_weights=SIMILARITY_WEIGHTS,
            source=prices.source,
            source_url=prices.source_url,
            retrieved_at=retrieved_at,
            error="no completed prior drawdown episode reaches the configured threshold",
        )

    context_coverage = max(item.similarity_coverage for item in analogues)
    quality = prices.data_quality
    if context_coverage < 0.75 and quality in {DataQuality.HIGH, DataQuality.MEDIUM}:
        quality = DataQuality.LOW
    return HistoricalAnalogueResult(
        ticker=security.ticker,
        company=security.company,
        as_of=as_of,
        status=DataStatus.AVAILABLE,
        data_quality=quality,
        current_episode=current,
        analogues=analogues,
        detected_completed_episode_count=len(completed),
        best_similarity_score=analogues[0].similarity_score,
        similarity_weights=SIMILARITY_WEIGHTS,
        source=prices.source,
        source_url=prices.source_url,
        retrieved_at=retrieved_at,
    )


def detect_drawdown_episodes(
    frame: pd.DataFrame,
    *,
    minimum_drawdown: float = -0.15,
    recovery_tolerance: float = 0.0,
) -> tuple[list[HistoricalEpisode], HistoricalEpisode | None]:
    """Return completed episodes and the active threshold-crossing episode."""

    path = (
        frame.copy()
        if {"date", "price"}.issubset(frame.columns)
        else _normalized_price_path(frame)
    )
    if path.empty:
        return [], None
    price_values = pd.to_numeric(path["price"], errors="coerce").to_numpy(dtype=float)
    peak_index = 0
    active = False
    trough_index = 0
    completed: list[HistoricalEpisode] = []

    for index in range(1, len(path)):
        price = float(price_values[index])
        peak_price = float(price_values[peak_index])
        if not active:
            if price >= peak_price:
                peak_index = index
                continue
            if price / peak_price - 1 <= minimum_drawdown:
                active = True
                trough_index = index
            continue
        if price < float(price_values[trough_index]):
            trough_index = index
        if price >= peak_price * (1 - recovery_tolerance):
            completed.append(_episode(path, peak_index, trough_index, index))
            peak_index = index
            trough_index = index
            active = False

    current = _episode(path, peak_index, trough_index, None) if active else None
    return completed, current


def _episode(
    path: pd.DataFrame, peak_index: int, trough_index: int, recovery_index: int | None
) -> HistoricalEpisode:
    peak_date = path.iloc[peak_index]["date"]
    trough_date = path.iloc[trough_index]["date"]
    peak_price = float(path.iloc[peak_index]["price"])
    trough_price = float(path.iloc[trough_index]["price"])
    recovery_date = path.iloc[recovery_index]["date"] if recovery_index is not None else None
    return HistoricalEpisode(
        peak_date=peak_date,
        peak_price=peak_price,
        trough_date=trough_date,
        trough_price=trough_price,
        recovery_date=recovery_date,
        maximum_drawdown=trough_price / peak_price - 1,
        decline_duration_days=(trough_date - peak_date).days,
        recovery_duration_days=(
            (recovery_date - trough_date).days if recovery_date is not None else None
        ),
        total_recovery_days=(
            (recovery_date - peak_date).days if recovery_date is not None else None
        ),
    )


def _attach_context(
    episode: HistoricalEpisode,
    security: Security,
    fundamental: FundamentalAnalysisResult | None,
    valuation: ValuationAnalysisResult | None,
    settings: HistoricalSettings,
) -> HistoricalEpisode:
    cutoff = normalize_as_of(episode.peak_date)
    return episode.model_copy(
        update={
            "fundamentals": _fundamental_snapshot(
                security, fundamental, cutoff,
                settings.fundamental_minimum_score_coverage,
            ),
            "valuation": _valuation_snapshot(valuation, cutoff),
        }
    )


def _fundamental_snapshot(
    security: Security,
    result: FundamentalAnalysisResult | None,
    cutoff: datetime,
    minimum_score_coverage: float,
) -> HistoricalContextSnapshot:
    if result is None:
        return _unavailable_snapshot(cutoff, "fundamental history is unavailable")
    observations = {
        name: [item for item in items if item.available_at <= cutoff]
        for name, items in result.annual_observations.items()
    }
    observations = {name: items for name, items in observations.items() if items}
    if not observations:
        return _unavailable_snapshot(
            cutoff, "no SEC annual fact was public by the episode peak"
        )
    historical_data = FundamentalDataResult(
        security=security,
        cik=result.cik,
        company=result.company,
        as_of=cutoff,
        status=DataStatus.AVAILABLE,
        data_quality=result.data_quality,
        observations=observations,
        retrieved_at=result.retrieved_at,
        sources=result.sources,
    )
    analysis = analyze_fundamentals(
        historical_data, minimum_score_coverage=minimum_score_coverage
    )
    selected = {
        name: (analysis.metrics[name].value if name in analysis.metrics else None)
        for name in FUNDAMENTAL_SNAPSHOT_METRICS
    }
    metadata = {
        name: {
            "formula": metric.formula,
            "period_start": metric.period_start,
            "period_end": metric.period_end,
            "source_accessions": metric.source_accessions,
        }
        for name, metric in analysis.metrics.items()
        if name in FUNDAMENTAL_SNAPSHOT_METRICS
    }
    eligible_facts = [item for items in observations.values() for item in items]
    return HistoricalContextSnapshot(
        as_of=cutoff,
        period_end=analysis.latest_period_end,
        status=DataStatus.AVAILABLE,
        metrics=selected,
        metric_metadata=metadata,
        source_accessions=list(dict.fromkeys(item.accession for item in eligible_facts)),
        source_urls=list(dict.fromkeys(item.source_url for item in eligible_facts)),
    )


def _valuation_snapshot(
    result: ValuationAnalysisResult | None, cutoff: datetime
) -> HistoricalContextSnapshot:
    if result is None:
        return _unavailable_snapshot(cutoff, "valuation history is unavailable")
    metrics: dict[str, float | None] = {}
    metadata: dict[str, dict[str, object]] = {}
    accessions: list[str] = []
    for name, multiple in result.multiples.items():
        eligible = [
            point for point in multiple.history
            if point.available_at <= cutoff and point.price_date <= cutoff.date()
        ]
        if not eligible:
            metrics[name] = None
            continue
        point = max(eligible, key=lambda item: (item.price_date, item.available_at))
        metrics[name] = point.value
        metadata[name] = {
            "formula": multiple.formula,
            "fiscal_period_end": point.fiscal_period_end,
            "available_at": point.available_at,
            "price": point.price,
            "price_date": point.price_date,
            "source_accessions": point.source_accessions,
            "market_cap_basis": point.market_cap_basis,
        }
        accessions.extend(point.source_accessions)
    if not any(value is not None for value in metrics.values()):
        return _unavailable_snapshot(
            cutoff, "no historical multiple was public by the episode peak"
        )
    return HistoricalContextSnapshot(
        as_of=cutoff,
        period_end=max(
            (item["fiscal_period_end"] for item in metadata.values()), default=None
        ),
        status=DataStatus.AVAILABLE,
        metrics=metrics,
        metric_metadata=metadata,
        source_accessions=list(dict.fromkeys(accessions)),
        source_urls=[
            str(source.get("source_url") or source.get("url"))
            for source in result.sources
            if source.get("source_url") or source.get("url")
        ],
    )


def _compare_episodes(
    current: HistoricalEpisode, historical: HistoricalEpisode
) -> HistoricalAnalogue:
    components = {
        "maximum_drawdown": MetricValue.available(
            _relative_similarity(
                abs(current.maximum_drawdown), abs(historical.maximum_drawdown)
            )
        ),
        "decline_duration": MetricValue.available(
            _relative_similarity(
                float(current.decline_duration_days),
                float(historical.decline_duration_days),
            )
        ),
        "fundamentals": _snapshot_similarity(
            current.fundamentals, historical.fundamentals,
            FUNDAMENTAL_SIMILARITY_METRICS,
        ),
        "valuation": _snapshot_similarity(
            current.valuation, historical.valuation,
            ("pe", "ev_ebitda", "price_fcf"), positive_only=True,
        ),
    }
    available = {
        name: metric for name, metric in components.items()
        if metric.status == DataStatus.AVAILABLE and metric.value is not None
    }
    coverage = sum(SIMILARITY_WEIGHTS[name] for name in available)
    score = sum(
        SIMILARITY_WEIGHTS[name] * metric.value
        for name, metric in available.items() if metric.value is not None
    ) / coverage
    return HistoricalAnalogue(
        episode=historical,
        similarity_score=round(score, 2),
        similarity_coverage=round(coverage, 4),
        similarity_components=components,
    )


def _snapshot_similarity(
    left: HistoricalContextSnapshot | None,
    right: HistoricalContextSnapshot | None,
    names: Iterable[str],
    *,
    positive_only: bool = False,
) -> MetricValue:
    if (
        left is None or right is None
        or left.status != DataStatus.AVAILABLE
        or right.status != DataStatus.AVAILABLE
    ):
        return MetricValue.unavailable(
            "one or both point-in-time snapshots are unavailable"
        )
    pairs = []
    for name in names:
        first, second = left.metrics.get(name), right.metrics.get(name)
        if first is None or second is None:
            continue
        if positive_only and (first <= 0 or second <= 0):
            continue
        pairs.append(_relative_similarity(float(first), float(second)))
    if not pairs:
        return MetricValue.unavailable("no comparable metrics in both snapshots")
    return MetricValue.available(sum(pairs) / len(pairs))


def _relative_similarity(first: float, second: float) -> float:
    scale = max(abs(first), abs(second), 0.10)
    return round(max(0.0, 100.0 * (1 - abs(first - second) / scale)), 4)


def _subsequent_returns(path: pd.DataFrame, trough_date: date) -> dict[str, MetricValue]:
    base_rows = path[path["date"] == trough_date]
    if base_rows.empty:
        return {
            name: MetricValue.unavailable("trough price unavailable")
            for name in RETURN_HORIZONS_MONTHS
        }
    base = float(base_rows.iloc[-1]["price"])
    results: dict[str, MetricValue] = {}
    for name, months in RETURN_HORIZONS_MONTHS.items():
        target = (pd.Timestamp(trough_date) + pd.DateOffset(months=months)).date()
        eligible = path[path["date"] >= target]
        if eligible.empty:
            results[name] = MetricValue.unavailable(
                f"price horizon {months} months after trough is beyond the cutoff"
            )
        else:
            results[name] = MetricValue.available(
                float(eligible.iloc[0]["price"]) / base - 1
            )
    return results


def _normalized_price_path(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "observation_date" not in frame:
        return pd.DataFrame(columns=["date", "price"])
    adjusted = pd.to_numeric(frame.get("adjusted_close"), errors="coerce")
    close = pd.to_numeric(frame.get("close"), errors="coerce")
    price = adjusted.combine_first(close)
    dates = pd.to_datetime(frame["observation_date"], errors="coerce")
    path = pd.DataFrame({"date": dates.dt.date, "price": price})
    path = path.dropna().loc[lambda value: value["price"] > 0]
    return (
        path.sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )


def _retrieved_at(frame: pd.DataFrame) -> datetime:
    if not frame.empty and "retrieved_at" in frame:
        parsed = pd.to_datetime(frame["retrieved_at"], errors="coerce", utc=True).dropna()
        if not parsed.empty:
            return parsed.max().to_pydatetime()
    return datetime.now(UTC)


def _unavailable_snapshot(cutoff: datetime, reason: str) -> HistoricalContextSnapshot:
    return HistoricalContextSnapshot(
        as_of=cutoff, status=DataStatus.DATA_UNAVAILABLE, reason=reason
    )


def _empty_result(
    security: Security,
    prices: PriceHistoryResult,
    as_of: datetime,
    retrieved_at: datetime,
    status: DataStatus,
    error: str,
    *,
    completed_count: int = 0,
) -> HistoricalAnalogueResult:
    return HistoricalAnalogueResult(
        ticker=security.ticker,
        company=security.company,
        as_of=as_of,
        status=status,
        data_quality=(
            DataQuality.UNAVAILABLE
            if status == DataStatus.DATA_UNAVAILABLE else prices.data_quality
        ),
        detected_completed_episode_count=completed_count,
        similarity_weights=SIMILARITY_WEIGHTS,
        source=prices.source,
        source_url=prices.source_url,
        retrieved_at=retrieved_at,
        error=error,
    )


__all__ = ["analyze_historical_analogues", "detect_drawdown_episodes"]


"""Non-causal transformations of point-in-time macro histories."""

from __future__ import annotations

from datetime import date, timedelta

from src.models import (
    DataStatus,
    MacroObservation,
    MacroSeriesAnalysis,
    MacroSeriesResult,
    MetricValue,
)

CHANGE_HORIZONS = {"30d": 30, "90d": 90, "365d": 365}
MAX_TARGET_GAP_DAYS = 31


def analyze_macro_series(result: MacroSeriesResult) -> MacroSeriesAnalysis:
    if result.status != DataStatus.AVAILABLE or not result.observations:
        return MacroSeriesAnalysis(
            series_key=result.series_key,
            series_id=result.series_id,
            title=result.configured_name,
            as_of=result.as_of,
            changes=_unavailable_changes(result.error or "macro history unavailable"),
            status=result.status,
            data_quality=result.data_quality,
            source_url=result.source_url,
            error=result.error,
        )
    points = sorted(result.observations, key=lambda item: item.observation_date)
    latest = points[-1]
    changes: dict[str, MetricValue] = {}
    for label, days in CHANGE_HORIZONS.items():
        target = latest.observation_date - timedelta(days=days)
        prior = _point_on_or_before(points, target)
        if prior is None or (target - prior.observation_date).days > MAX_TARGET_GAP_DAYS:
            changes[f"absolute_{label}"] = MetricValue.unavailable(
                f"no aligned observation near {days}-day target"
            )
            changes[f"percent_{label}"] = MetricValue.unavailable(
                f"no aligned observation near {days}-day target"
            )
            continue
        absolute = latest.value - prior.value
        changes[f"absolute_{label}"] = MetricValue.available(absolute)
        changes[f"percent_{label}"] = (
            MetricValue.available(absolute / abs(prior.value))
            if prior.value != 0
            else MetricValue.unavailable("percentage change denominator is zero")
        )
    return MacroSeriesAnalysis(
        series_key=result.series_key,
        series_id=result.series_id,
        title=latest.series_title,
        as_of=result.as_of,
        latest_value=latest.value,
        latest_observation_date=latest.observation_date,
        unit=latest.unit,
        frequency=latest.frequency,
        changes=changes,
        status=DataStatus.AVAILABLE,
        data_quality=result.data_quality,
        source_url=result.source_url,
    )


def _point_on_or_before(
    points: list[MacroObservation], target: date
) -> MacroObservation | None:
    eligible = [point for point in points if point.observation_date <= target]
    return eligible[-1] if eligible else None


def _unavailable_changes(reason: str) -> dict[str, MetricValue]:
    return {
        f"{kind}_{label}": MetricValue.unavailable(reason)
        for label in CHANGE_HORIZONS
        for kind in ("absolute", "percent")
    }

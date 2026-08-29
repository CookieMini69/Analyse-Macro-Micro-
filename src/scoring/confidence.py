"""Shared coverage, interpolation, and data-quality helpers for Phase 8."""

from __future__ import annotations

from src.models import DataQuality, DataStatus, EvidenceScore, ScoreComponent


def build_evidence_score(
    name: str,
    components: dict[str, ScoreComponent],
    *,
    minimum_coverage: float,
    methodology_version: str,
) -> EvidenceScore:
    """Aggregate observed evidence while treating missing weight as zero."""

    total_weight = sum(item.weight for item in components.values())
    if abs(total_weight - 1.0) > 1e-9:
        raise ValueError(f"{name} component weights must sum to 1.0")
    observed = [item for item in components.values() if item.observed]
    coverage = sum(item.weight for item in observed)
    observed_score = (
        sum(item.weight * float(item.score) for item in observed) / coverage
        if coverage
        else None
    )
    adjusted = sum(
        item.weight * (float(item.score) if item.score is not None else 0.0)
        for item in components.values()
    )
    status = (
        DataStatus.AVAILABLE
        if observed_score is not None and coverage >= minimum_coverage
        else DataStatus.DATA_UNAVAILABLE
    )
    return EvidenceScore(
        name=name,
        score=round(adjusted, 2) if status == DataStatus.AVAILABLE else None,
        observed_score=(
            round(observed_score, 2) if observed_score is not None else None
        ),
        coverage=round(coverage, 4),
        status=status,
        methodology_version=methodology_version,
        components=components,
        reason=(
            None
            if status == DataStatus.AVAILABLE
            else f"score coverage {coverage:.2%} is below required {minimum_coverage:.2%}"
        ),
    )


def preserve_source_score(
    name: str,
    *,
    score: float | None,
    observed_score: float | None,
    coverage: float,
    status: DataStatus,
    methodology_version: str,
    source: str,
) -> EvidenceScore:
    """Expose an earlier-stage score without silently changing its method."""

    observed_weight = min(max(coverage, 0.0), 1.0)
    components = {
        "observed_evidence": ScoreComponent(
            name="observed_evidence",
            score=observed_score,
            weight=observed_weight,
            observed=observed_score is not None,
            source=source,
            evidence={"source_score": score, "source_coverage": coverage},
            reason=None if observed_score is not None else f"{name} is unavailable",
        ),
        "missing_evidence": ScoreComponent(
            name="missing_evidence",
            score=None,
            weight=1.0 - observed_weight,
            observed=False,
            source=source,
            evidence={},
            reason="evidence not covered by the source methodology",
        ),
    }
    return EvidenceScore(
        name=name,
        score=score if status == DataStatus.AVAILABLE else None,
        observed_score=observed_score,
        coverage=round(observed_weight, 4),
        status=status,
        methodology_version=methodology_version,
        components=components,
        reason=None if status == DataStatus.AVAILABLE else f"{name} is unavailable",
    )


def piecewise_score(value: float, bands: tuple[tuple[float, float], ...]) -> float:
    ordered = sorted(bands)
    if value <= ordered[0][0]:
        return ordered[0][1]
    if value >= ordered[-1][0]:
        return ordered[-1][1]
    for (left_x, left_y), (right_x, right_y) in zip(ordered, ordered[1:]):
        if left_x <= value <= right_x:
            position = (value - left_x) / (right_x - left_x)
            return left_y + position * (right_y - left_y)
    raise RuntimeError("piecewise scoring bands are invalid")


def scoring_data_quality(
    *, coverage: float, statuses: list[DataStatus], qualities: list[DataQuality]
) -> DataQuality:
    available_stages = sum(status == DataStatus.AVAILABLE for status in statuses)
    reliable_stages = sum(
        quality in {DataQuality.HIGH, DataQuality.MEDIUM} for quality in qualities
    )
    if coverage >= 0.90 and available_stages >= 5 and reliable_stages >= 4:
        return DataQuality.HIGH
    if coverage >= 0.75 and available_stages >= 3 and reliable_stages >= 2:
        return DataQuality.MEDIUM
    if available_stages:
        return DataQuality.LOW
    return DataQuality.UNAVAILABLE


__all__ = [
    "build_evidence_score",
    "piecewise_score",
    "preserve_source_score",
    "scoring_data_quality",
]

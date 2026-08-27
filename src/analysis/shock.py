"""Conservative, evidence-backed shock classification from public headlines."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from src.macro_config import (
    MacroExposureDefinition,
    ShockTaxonomyConfig,
)
from src.models import (
    DataQuality,
    DataStatus,
    FundamentalAnalysisResult,
    MacroAssociation,
    MacroSeriesAnalysis,
    NewsArticle,
    NewsSearchResult,
    Security,
    ShockAnalysisResult,
    ShockCategory,
    ShockEvidence,
    ShockNature,
    TemporaryShockScore,
    TemporaryShockScoreComponent,
)

TEMPORARY_SCORE_WEIGHTS = {
    "resolution_evidence": 0.35,
    "structural_damage": 0.35,
    "source_corroboration": 0.15,
    "fundamental_resilience": 0.15,
}


def analyze_shock(
    security: Security,
    news: NewsSearchResult,
    macro: dict[str, MacroSeriesAnalysis],
    exposures: list[MacroExposureDefinition],
    taxonomy: ShockTaxonomyConfig,
    *,
    fundamental: FundamentalAnalysisResult | None = None,
    minimum_independent_sources: int = 2,
    minimum_score_coverage: float = 0.50,
) -> ShockAnalysisResult:
    """Classify titles only; absence of evidence never becomes temporary proof."""

    evidence = [
        item
        for article in news.articles
        if (item := _article_evidence(article, taxonomy)) is not None
    ]
    independent_sources = {
        item.source_domain for item in evidence if item.source_domain
    }
    category = _select_category(evidence)
    nature = _classify_nature(
        evidence,
        minimum_independent_sources=minimum_independent_sources,
    )
    associations = _macro_associations(
        exposures, macro, as_of=news.as_of
    )
    score = score_temporary_shock(
        evidence,
        fundamental=fundamental,
        minimum_independent_sources=minimum_independent_sources,
        minimum_coverage=minimum_score_coverage,
        news_available=news.status == DataStatus.AVAILABLE,
    )
    status = (
        DataStatus.AVAILABLE
        if news.status == DataStatus.AVAILABLE
        else DataStatus.DATA_UNAVAILABLE
    )
    quality = news.data_quality
    if not evidence and quality == DataQuality.MEDIUM:
        quality = DataQuality.LOW
    return ShockAnalysisResult(
        ticker=security.ticker,
        company=security.company,
        as_of=news.as_of,
        category=category,
        nature=nature,
        status=status,
        data_quality=quality,
        temporary_score=score,
        evidence=evidence,
        macro_associations=associations,
        independent_source_count=len(independent_sources),
        conclusion=_conclusion(category, nature, evidence, news),
        retrieved_at=max(news.retrieved_at, datetime.now(UTC)),
        sources=_shock_sources(news, evidence, associations),
        error=news.error,
    )


def score_temporary_shock(
    evidence: list[ShockEvidence],
    *,
    fundamental: FundamentalAnalysisResult | None,
    minimum_independent_sources: int,
    minimum_coverage: float,
    news_available: bool,
) -> TemporaryShockScore:
    """Score explicit evidence coverage; this is not a probability."""

    has_evidence = bool(evidence) and news_available
    resolution_domains = _domains_with_terms(
        evidence, "temporary_terms", "resolution_terms"
    )
    structural_domains = _domains_with_terms(
        evidence, "structural_terms", "severe_structural_terms"
    )
    damage_domains = _domains_with_terms(evidence, "damage_terms")
    all_domains = {item.source_domain for item in evidence if item.source_domain}

    resolution_score = (
        min(100.0, 100.0 * len(resolution_domains) / minimum_independent_sources)
        if has_evidence
        else None
    )
    if has_evidence:
        if _has_terms(evidence, "severe_structural_terms"):
            structural_score = 0.0
        elif structural_domains:
            structural_score = 10.0
        elif damage_domains:
            structural_score = 30.0
        else:
            structural_score = 50.0
        corroboration_score = min(
            100.0, 100.0 * len(all_domains) / minimum_independent_sources
        )
    else:
        structural_score = None
        corroboration_score = None

    fundamental_score = (
        fundamental.quality_score.score
        if fundamental is not None
        and fundamental.quality_score.status == DataStatus.AVAILABLE
        else None
    )
    components = {
        "resolution_evidence": _score_component(
            "resolution_evidence",
            resolution_score,
            evidence={"independent_sources": len(resolution_domains)},
            reason="no classified headline evidence" if not has_evidence else None,
        ),
        "structural_damage": _score_component(
            "structural_damage",
            structural_score,
            evidence={
                "structural_sources": len(structural_domains),
                "damage_sources": len(damage_domains),
            },
            reason="no classified headline evidence" if not has_evidence else None,
        ),
        "source_corroboration": _score_component(
            "source_corroboration",
            corroboration_score,
            evidence={"independent_sources": len(all_domains)},
            reason="no classified headline evidence" if not has_evidence else None,
        ),
        "fundamental_resilience": _score_component(
            "fundamental_resilience",
            fundamental_score,
            evidence={
                "fundamental_quality_score": fundamental_score,
                "fundamental_quality_coverage": (
                    fundamental.quality_score.coverage if fundamental else None
                ),
            },
            reason=(
                None
                if fundamental_score is not None
                else "Fundamental Quality Score unavailable"
            ),
        ),
    }
    available = [item for item in components.values() if item.observed]
    coverage = sum(item.weight for item in available)
    observed_score = (
        sum(item.weight * item.score for item in available) / coverage
        if coverage
        else None
    )
    adjusted_score = sum(
        item.weight * (item.score or 0.0) for item in components.values()
    )
    status = (
        DataStatus.AVAILABLE
        if observed_score is not None and coverage >= minimum_coverage
        else DataStatus.DATA_UNAVAILABLE
    )
    return TemporaryShockScore(
        score=round(adjusted_score, 2) if status == DataStatus.AVAILABLE else None,
        observed_score=(
            round(observed_score, 2) if observed_score is not None else None
        ),
        coverage=round(coverage, 4),
        status=status,
        components=components,
        reason=(
            None
            if status == DataStatus.AVAILABLE
            else f"score coverage {coverage:.2%} is below required {minimum_coverage:.2%}"
        ),
    )


def _article_evidence(
    article: NewsArticle, taxonomy: ShockTaxonomyConfig
) -> ShockEvidence | None:
    category_matches: dict[ShockCategory, list[str]] = {}
    for raw_category, terms in taxonomy.categories.items():
        try:
            category = ShockCategory(raw_category)
        except ValueError:
            continue
        matched = _matched_terms(article.title, terms)
        if matched:
            category_matches[category] = matched
    selected = (
        max(category_matches, key=lambda item: len(category_matches[item]))
        if category_matches
        else None
    )
    temporary = _matched_terms(article.title, taxonomy.temporary_terms)
    resolution = _matched_terms(article.title, taxonomy.resolution_terms)
    damage = _matched_terms(article.title, taxonomy.damage_terms)
    structural = _matched_terms(article.title, taxonomy.structural_terms)
    severe = _matched_terms(article.title, taxonomy.severe_structural_terms)
    if selected is None and not any(
        (temporary, resolution, damage, structural, severe)
    ):
        return None
    return ShockEvidence(
        title=article.title,
        url=article.url,
        source_domain=article.source_domain,
        seen_at=article.seen_at,
        category=selected,
        matched_terms=category_matches.get(selected, []) if selected else [],
        temporary_terms=temporary,
        resolution_terms=resolution,
        damage_terms=damage,
        structural_terms=structural,
        severe_structural_terms=severe,
    )


def _select_category(evidence: list[ShockEvidence]) -> ShockCategory:
    scores: dict[ShockCategory, int] = {}
    for item in evidence:
        if item.category is not None:
            scores[item.category] = scores.get(item.category, 0) + len(
                item.matched_terms
            )
    return max(scores, key=scores.get) if scores else ShockCategory.UNKNOWN


def _classify_nature(
    evidence: list[ShockEvidence], *, minimum_independent_sources: int
) -> ShockNature:
    if _has_terms(evidence, "severe_structural_terms"):
        return ShockNature.SEVERE_STRUCTURAL
    structural_domains = _domains_with_terms(evidence, "structural_terms")
    if len(structural_domains) >= minimum_independent_sources:
        return ShockNature.STRUCTURAL
    if structural_domains or _has_terms(evidence, "damage_terms"):
        return ShockNature.UNCERTAIN
    resolution_domains = _domains_with_terms(
        evidence, "temporary_terms", "resolution_terms"
    )
    if len(resolution_domains) >= minimum_independent_sources:
        return ShockNature.PROBABLY_TEMPORARY
    return ShockNature.UNCERTAIN


def _macro_associations(
    exposures: list[MacroExposureDefinition],
    macro: dict[str, MacroSeriesAnalysis],
    *,
    as_of: datetime,
) -> list[MacroAssociation]:
    associations: list[MacroAssociation] = []
    for exposure in exposures:
        analysis = macro.get(exposure.series_key)
        if exposure.assumption_date > as_of.date():
            associations.append(
                _unavailable_association(
                    exposure,
                    analysis,
                    "exposure assumption was not available at the cutoff",
                )
            )
            continue
        if analysis is None or analysis.status != DataStatus.AVAILABLE:
            associations.append(
                _unavailable_association(
                    exposure, analysis, "point-in-time macro series unavailable"
                )
            )
            continue
        selected_horizon = None
        selected_change = None
        for horizon in ("30d", "90d", "365d"):
            metric = analysis.changes.get(f"absolute_{horizon}")
            if metric is not None and metric.value is not None:
                selected_horizon = horizon
                selected_change = metric.value
                break
        if selected_change is None:
            associations.append(
                _unavailable_association(
                    exposure, analysis, "no aligned macro change is available"
                )
            )
            continue
        associations.append(
            MacroAssociation(
                series_key=exposure.series_key,
                series_id=analysis.series_id,
                coefficient=exposure.coefficient,
                latest_value=analysis.latest_value,
                change_horizon=selected_horizon,
                observed_change=selected_change,
                aligned_with_headwind=(selected_change * exposure.coefficient < 0),
                rationale=exposure.rationale,
                assumption_date=exposure.assumption_date,
                assumption_source=exposure.source,
                status=DataStatus.AVAILABLE,
            )
        )
    return associations


def _unavailable_association(
    exposure: MacroExposureDefinition,
    analysis: MacroSeriesAnalysis | None,
    reason: str,
) -> MacroAssociation:
    return MacroAssociation(
        series_key=exposure.series_key,
        series_id=analysis.series_id if analysis else exposure.series_key,
        coefficient=exposure.coefficient,
        latest_value=analysis.latest_value if analysis else None,
        rationale=exposure.rationale,
        assumption_date=exposure.assumption_date,
        assumption_source=exposure.source,
        status=DataStatus.DATA_UNAVAILABLE,
        reason=reason,
    )


def _score_component(
    name: str,
    score: float | None,
    *,
    evidence: dict,
    reason: str | None,
) -> TemporaryShockScoreComponent:
    return TemporaryShockScoreComponent(
        name=name,
        score=round(score, 2) if score is not None else None,
        weight=TEMPORARY_SCORE_WEIGHTS[name],
        observed=score is not None,
        evidence=evidence,
        reason=reason,
    )


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    matched = []
    for term in terms:
        pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
        if re.search(pattern, text, flags=re.IGNORECASE):
            matched.append(term)
    return matched


def _has_terms(evidence: list[ShockEvidence], field: str) -> bool:
    return any(bool(getattr(item, field)) for item in evidence)


def _domains_with_terms(
    evidence: list[ShockEvidence], *fields: str
) -> set[str]:
    return {
        item.source_domain
        for item in evidence
        if item.source_domain and any(getattr(item, field) for field in fields)
    }


def _conclusion(
    category: ShockCategory,
    nature: ShockNature,
    evidence: list[ShockEvidence],
    news: NewsSearchResult,
) -> str:
    if news.status != DataStatus.AVAILABLE:
        return "News metadata unavailable; no shock conclusion can be supported."
    if not evidence:
        return "No configured taxonomy term matched the available headlines; cause remains unknown."
    if nature == ShockNature.SEVERE_STRUCTURAL:
        return "Severe structural terms appear in the available headlines; independent verification is required."
    if nature == ShockNature.STRUCTURAL:
        return "Structural terms are corroborated by multiple headline sources."
    if nature == ShockNature.PROBABLY_TEMPORARY:
        return "Temporary or resolution language is corroborated, but this score is not a normalization probability."
    return f"Evidence suggests category {category.value}, but duration and structural impact remain uncertain."


def _shock_sources(
    news: NewsSearchResult,
    evidence: list[ShockEvidence],
    associations: list[MacroAssociation],
) -> list[dict]:
    sources: list[dict] = [
        {
            "source": "GDELT DOC 2.0 API",
            "source_url": news.source_url,
            "retrieved_at": news.retrieved_at.isoformat(),
            "role": "news_index",
        }
    ]
    sources.extend(
        {
            "source": item.source_domain or "article source",
            "source_url": item.url,
            "observation_date": item.seen_at.isoformat(),
            "role": "headline_evidence",
        }
        for item in evidence
    )
    sources.extend(
        {
            "source": item.assumption_source,
            "observation_date": item.assumption_date.isoformat(),
            "role": "macro_exposure_assumption",
        }
        for item in associations
    )
    return sources

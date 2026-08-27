"""Point-in-time orchestration for prices, fundamentals, valuation, and shocks."""

from __future__ import annotations

import argparse
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from src.analysis.fundamentals import analyze_fundamentals
from src.analysis.macro import analyze_macro_series
from src.analysis.shock import analyze_shock
from src.analysis.valuation import analyze_valuations
from src.config import AppSettings, load_settings
from src.data.fundamentals import (
    SecEdgarFundamentalSource,
    is_sec_eligible,
    normalize_as_of,
    unavailable_fundamental_data,
)
from src.data.macro import FredMacroSource, unavailable_macro_series
from src.data.news import (
    GDELT_DOC_URL,
    GdeltNewsSource,
    build_news_query,
    unavailable_news_result,
)
from src.data.prices import YahooFinancePriceSource, empty_price_frame
from src.data.sec_edgar import SecEdgarClient
from src.data.sources import (
    FundamentalSource,
    MacroSource,
    NewsSource,
    PriceHistoryResult,
    PriceSource,
)
from src.macro_config import (
    MacroConfig,
    MacroExposureConfig,
    ShockTaxonomyConfig,
    load_macro_config,
    load_macro_exposure_config,
    load_shock_taxonomy,
)
from src.models import (
    DataQuality,
    DataStatus,
    FundamentalAnalysisResult,
    MacroSeriesAnalysis,
    MacroSeriesResult,
    NewsSearchResult,
    OpportunityCandidate,
    Security,
    ShockAnalysisResult,
    ValuationAnalysisResult,
)
from src.reporting.export import export_scan_results
from src.reporting.fundamentals import persist_fundamental_results
from src.reporting.macro_shock import persist_macro_results, persist_shock_results
from src.reporting.valuation import persist_valuation_results
from src.screening.scanner import build_scan_result, rank_results
from src.screening.universe import auxiliary_benchmarks, load_universe
from src.valuation_config import ValuationConfig, load_valuation_config

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    results: list[OpportunityCandidate]
    exported_files: list[Path]
    download_errors: dict[str, str]
    fundamental_results: dict[str, FundamentalAnalysisResult]
    fundamental_exported_files: list[Path]
    fundamental_errors: dict[str, str]
    valuation_results: dict[str, ValuationAnalysisResult]
    valuation_exported_files: list[Path]
    valuation_errors: dict[str, str]
    macro_results: dict[str, MacroSeriesResult]
    macro_analysis: dict[str, MacroSeriesAnalysis]
    macro_exported_files: list[Path]
    macro_errors: dict[str, str]
    news_results: dict[str, NewsSearchResult]
    shock_results: dict[str, ShockAnalysisResult]
    shock_exported_files: list[Path]
    shock_errors: dict[str, str]


def _configure_logging(level: str) -> None:
    configured_level = os.getenv("STOCK_SCANNER_LOG_LEVEL", level).upper()
    logging.basicConfig(
        level=getattr(logging, configured_level, logging.INFO),
        format="[%(levelname)s] %(message)s",
        force=True,
    )


def _download_prices(
    securities: list[Security],
    source: PriceSource,
    *,
    period: str,
    max_workers: int,
) -> dict[str, PriceHistoryResult]:
    downloaded: dict[str, PriceHistoryResult] = {}
    if not securities:
        return downloaded
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(source.fetch, security, period=period): security
            for security in securities
        }
        for future in as_completed(futures):
            security = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # custom provider errors cannot abort the whole universe
                LOGGER.exception("Unhandled provider error for %s", security.ticker)
                result = PriceHistoryResult(
                    security=security,
                    frame=empty_price_frame(),
                    status=DataStatus.DATA_UNAVAILABLE,
                    data_quality=DataQuality.UNAVAILABLE,
                    source=type(source).__name__,
                    source_url=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            downloaded[security.ticker.upper()] = result
            if result.error:
                LOGGER.warning("%s: %s", security.ticker, result.error)
    return downloaded


def _persist_normalized_prices(
    results: dict[str, PriceHistoryResult], output_dir: Path
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for result in results.values():
        if result.frame.empty:
            continue
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", result.security.ticker)
        result.frame.to_csv(output_dir / f"{safe_name}.csv", index=False)


def _run_fundamentals(
    securities: list[Security],
    settings: AppSettings,
    *,
    source: FundamentalSource | None,
    as_of: date | datetime | str | None,
) -> list[FundamentalAnalysisResult]:
    if not settings.fundamentals.enabled:
        return []

    eligible = [security for security in securities if is_sec_eligible(security)]
    configured_source = source
    configuration_error: str | None = None
    if configured_source is None and eligible:
        user_agent = os.getenv(settings.fundamentals.user_agent_env, "").strip()
        if not user_agent:
            configuration_error = (
                f"{settings.fundamentals.user_agent_env} is required for SEC EDGAR access"
            )
        else:
            sec_cache = settings.paths.sec_cache or (
                settings.project_root / "data" / "cache" / "sec"
            )
            try:
                client = SecEdgarClient(
                    sec_cache,
                    user_agent=user_agent,
                    cache_ttl_hours=settings.fundamentals.cache_ttl_hours,
                    requests_per_second=settings.fundamentals.requests_per_second,
                    timeout_seconds=settings.fundamentals.timeout_seconds,
                    max_retries=settings.fundamentals.max_retries,
                )
                configured_source = SecEdgarFundamentalSource(
                    client, history_years=settings.fundamentals.history_years
                )
            except Exception as exc:
                configuration_error = f"{type(exc).__name__}: {exc}"
                LOGGER.error("SEC fundamental source is unavailable: %s", exc)

    cutoff = normalize_as_of(
        as_of if as_of is not None else settings.fundamentals.as_of
    )
    results: list[FundamentalAnalysisResult] = []
    for security in securities:
        if not is_sec_eligible(security):
            data = unavailable_fundamental_data(
                security,
                cutoff,
                DataStatus.NOT_APPLICABLE,
                "SEC EDGAR provider currently covers US reporting issuers only",
            )
        elif configured_source is None:
            data = unavailable_fundamental_data(
                security,
                cutoff,
                DataStatus.DATA_UNAVAILABLE,
                configuration_error or "fundamental source unavailable",
            )
        else:
            try:
                data = configured_source.fetch(security, as_of=cutoff)
            except Exception as exc:
                LOGGER.exception("Unhandled fundamental provider error for %s", security.ticker)
                data = unavailable_fundamental_data(
                    security,
                    cutoff,
                    DataStatus.DATA_UNAVAILABLE,
                    f"{type(exc).__name__}: {exc}",
                )
        results.append(
            analyze_fundamentals(
                data,
                minimum_score_coverage=settings.fundamentals.minimum_score_coverage,
            )
        )
    return results


def _run_macro(
    settings: AppSettings,
    *,
    source: MacroSource | None,
    as_of: date | datetime | str | None,
) -> tuple[dict[str, MacroSeriesResult], dict[str, MacroSeriesAnalysis]]:
    if not settings.macro.enabled:
        return {}, {}
    config = (
        load_macro_config(settings.paths.macro)
        if settings.paths.macro is not None
        else MacroConfig()
    )
    cutoff = normalize_as_of(as_of)
    configured_source = source
    configuration_error: str | None = None
    if configured_source is None and config.series:
        api_key = os.getenv(settings.macro.api_key_env, "").strip()
        if not api_key:
            configuration_error = (
                f"{settings.macro.api_key_env} is required for FRED/ALFRED access"
            )
        else:
            try:
                configured_source = FredMacroSource(
                    settings.paths.macro_cache
                    or settings.project_root / "data" / "cache" / "macro",
                    api_key=api_key,
                    cache_ttl_hours=settings.macro.cache_ttl_hours,
                    timeout_seconds=settings.macro.timeout_seconds,
                    max_retries=settings.macro.max_retries,
                )
            except Exception as exc:
                configuration_error = f"{type(exc).__name__}: {exc}"
    raw: dict[str, MacroSeriesResult] = {}
    for key, definition in config.series.items():
        if not definition.enabled:
            continue
        if configured_source is None:
            result = unavailable_macro_series(
                key,
                definition,
                cutoff,
                f"https://fred.stlouisfed.org/series/{definition.series_id}",
                configuration_error or "macro source unavailable",
            )
        else:
            try:
                result = configured_source.fetch(
                    key,
                    definition,
                    as_of=cutoff,
                    history_years=settings.macro.history_years,
                )
            except Exception as exc:
                result = unavailable_macro_series(
                    key,
                    definition,
                    cutoff,
                    f"https://fred.stlouisfed.org/series/{definition.series_id}",
                    f"{type(exc).__name__}: {exc}",
                )
        raw[key] = result
    analyses = {key: analyze_macro_series(result) for key, result in raw.items()}
    return raw, analyses


def _run_news(
    securities: list[Security],
    settings: AppSettings,
    *,
    source: NewsSource | None,
    as_of: date | datetime | str | None,
) -> dict[str, NewsSearchResult]:
    if not settings.news.enabled or not securities:
        return {}
    provider = source or GdeltNewsSource(
        settings.paths.news_cache
        or settings.project_root / "data" / "cache" / "news",
        cache_ttl_hours=settings.news.cache_ttl_hours,
        timeout_seconds=settings.news.timeout_seconds,
        max_retries=settings.news.max_retries,
    )
    cutoff = normalize_as_of(as_of)
    results: dict[str, NewsSearchResult] = {}
    for security in securities:
        try:
            result = provider.fetch(
                security,
                as_of=cutoff,
                lookback_days=settings.news.lookback_days,
                max_articles=settings.news.max_articles,
            )
        except Exception as exc:
            query = build_news_query(security)
            result = unavailable_news_result(
                security,
                query,
                cutoff - timedelta(days=settings.news.lookback_days),
                cutoff,
                GDELT_DOC_URL,
                f"{type(exc).__name__}: {exc}",
            )
        results[security.ticker.upper()] = result
    return results


def _enrich_with_fundamentals(
    result: OpportunityCandidate,
    fundamental: FundamentalAnalysisResult | None,
) -> OpportunityCandidate:
    if fundamental is None:
        return result
    components = fundamental.quality_score.components
    updates = {
        "fundamental_quality_score": fundamental.quality_score.score,
        "fundamental_quality_observed_score": fundamental.quality_score.observed_score,
        "fundamental_quality_coverage": fundamental.quality_score.coverage,
        "fundamental_growth_score": (
            components["growth"].adjusted_score if "growth" in components else None
        ),
        "fundamental_profitability_score": (
            components["profitability"].adjusted_score
            if "profitability" in components
            else None
        ),
        "fundamental_balance_sheet_score": (
            components["balance_sheet"].adjusted_score
            if "balance_sheet" in components
            else None
        ),
        "fundamental_cash_flow_score": (
            components["cash_flow"].adjusted_score if "cash_flow" in components else None
        ),
        "fundamental_data_quality": fundamental.data_quality,
        "fundamental_status": fundamental.status,
        "fundamental_as_of": fundamental.as_of,
        "fundamental_latest_period_end": fundamental.latest_period_end,
        "fundamental_metrics": {
            name: metric.value for name, metric in fundamental.metrics.items()
        },
        "sources": result.sources
        + [
            {**source, "role": "fundamentals"}
            for source in fundamental.sources
        ],
    }
    return OpportunityCandidate.model_validate(
        {**result.model_dump(), **updates}
    )


def _enrich_with_valuation(
    result: OpportunityCandidate,
    valuation: ValuationAnalysisResult | None,
) -> OpportunityCandidate:
    if valuation is None:
        return result

    def multiple_value(name: str, reference: str) -> float | None:
        multiple = valuation.multiples.get(name)
        metric = getattr(multiple, reference) if multiple is not None else None
        return metric.value if metric is not None else None

    def scenario_value(name: str) -> float | None:
        scenario = valuation.dcf_scenarios.get(name)
        return scenario.value_per_share if scenario is not None else None

    valuation_detail = {
        "market_cap": valuation.market_cap,
        "market_cap_basis": valuation.market_cap_basis,
        "valuation_currency": valuation.valuation_currency,
        "multiples": {
            name: multiple.model_dump(mode="json")
            for name, multiple in valuation.multiples.items()
        },
        "dcf_scenarios": {
            name: scenario.model_dump(mode="json", exclude={"projections"})
            for name, scenario in valuation.dcf_scenarios.items()
        },
        "reverse_dcf": (
            valuation.reverse_dcf.model_dump(mode="json")
            if valuation.reverse_dcf is not None
            else None
        ),
        "score_components": {
            name: component.model_dump(mode="json")
            for name, component in valuation.score.components.items()
        },
    }
    updates = {
        "valuation_score": valuation.score.score,
        "valuation_observed_score": valuation.score.observed_score,
        "valuation_coverage": valuation.score.coverage,
        "valuation_status": valuation.status,
        "valuation_data_quality": valuation.data_quality,
        "valuation_as_of": valuation.as_of,
        "valuation_price": valuation.valuation_price,
        "valuation_price_date": valuation.valuation_price_date,
        "pe_current": multiple_value("pe", "current"),
        "pe_historical_median": multiple_value("pe", "historical_median"),
        "pe_sector_median": multiple_value("pe", "sector_median"),
        "ev_ebitda_current": multiple_value("ev_ebitda", "current"),
        "ev_ebitda_historical_median": multiple_value(
            "ev_ebitda", "historical_median"
        ),
        "ev_ebitda_sector_median": multiple_value("ev_ebitda", "sector_median"),
        "price_fcf_current": multiple_value("price_fcf", "current"),
        "price_fcf_historical_median": multiple_value(
            "price_fcf", "historical_median"
        ),
        "price_fcf_sector_median": multiple_value("price_fcf", "sector_median"),
        "dcf_bear_value_per_share": scenario_value("bear"),
        "dcf_base_value_per_share": scenario_value("base"),
        "dcf_bull_value_per_share": scenario_value("bull"),
        "normalized_value_per_share": scenario_value("normalized"),
        "reverse_dcf_implied_revenue_growth": (
            valuation.reverse_dcf.implied_revenue_growth
            if valuation.reverse_dcf is not None
            else None
        ),
        "valuation_metrics": valuation_detail,
        "sources": result.sources
        + [{**source, "role": source.get("role", "valuation")} for source in valuation.sources],
    }
    return OpportunityCandidate.model_validate({**result.model_dump(), **updates})


def _enrich_with_shock(
    result: OpportunityCandidate,
    shock: ShockAnalysisResult | None,
) -> OpportunityCandidate:
    if shock is None:
        return result
    updates = {
        "shock_category": shock.category,
        "shock_nature": shock.nature,
        "temporary_shock_score": shock.temporary_score.score,
        "temporary_shock_observed_score": shock.temporary_score.observed_score,
        "temporary_shock_coverage": shock.temporary_score.coverage,
        "shock_status": shock.status,
        "shock_data_quality": shock.data_quality,
        "shock_as_of": shock.as_of,
        "shock_evidence_count": len(shock.evidence),
        "shock_independent_source_count": shock.independent_source_count,
        "shock_conclusion": shock.conclusion,
        "shock_metrics": {
            "evidence": [item.model_dump(mode="json") for item in shock.evidence],
            "macro_associations": [
                item.model_dump(mode="json") for item in shock.macro_associations
            ],
            "score_components": {
                name: component.model_dump(mode="json")
                for name, component in shock.temporary_score.components.items()
            },
        },
        "sources": result.sources
        + [{**source, "role": source.get("role", "shock")} for source in shock.sources],
    }
    return OpportunityCandidate.model_validate({**result.model_dump(), **updates})


def run_pipeline(
    settings: AppSettings | str | Path = "config/settings.yaml",
    *,
    universe_path: str | Path | None = None,
    price_source: PriceSource | None = None,
    fundamental_source: FundamentalSource | None = None,
    macro_source: MacroSource | None = None,
    news_source: NewsSource | None = None,
    fundamentals_as_of: date | datetime | str | None = None,
) -> PipelineResult:
    """Run the integrated scanner without fabricating missing external data."""

    app_settings = load_settings(settings) if not isinstance(settings, AppSettings) else settings
    _configure_logging(app_settings.logging.level)

    configured_universe = Path(universe_path).resolve() if universe_path else app_settings.paths.universe
    LOGGER.info("Loading universe from %s...", configured_universe)
    securities = load_universe(configured_universe)
    LOGGER.info("%d securities loaded", len(securities))
    if not securities:
        LOGGER.warning(
            "Universe is empty. Add securities to config/universe.yaml or configure csv_path."
        )

    LOGGER.info("Updating point-in-time fundamentals...")
    fundamental_list = _run_fundamentals(
        securities,
        app_settings,
        source=fundamental_source,
        as_of=fundamentals_as_of,
    )
    fundamental_results = {
        result.ticker.upper(): result for result in fundamental_list
    }
    fundamental_available = sum(
        result.status == DataStatus.AVAILABLE for result in fundamental_list
    )
    LOGGER.info(
        "%d/%d fundamental histories available",
        fundamental_available,
        len(fundamental_list),
    )
    fundamental_exported = (
        persist_fundamental_results(
            fundamental_list,
            app_settings.paths.processed_data,
            app_settings.paths.reports,
        )
        if fundamental_list
        else []
    )

    LOGGER.info("Updating point-in-time macro vintages...")
    macro_results, macro_analysis = _run_macro(
        app_settings,
        source=macro_source,
        as_of=fundamentals_as_of,
    )
    macro_available = sum(
        result.status == DataStatus.AVAILABLE for result in macro_results.values()
    )
    LOGGER.info(
        "%d/%d macro series available", macro_available, len(macro_results)
    )
    macro_exported = (
        persist_macro_results(
            macro_results,
            macro_analysis,
            app_settings.paths.processed_data,
            app_settings.paths.reports,
        )
        if macro_results
        else []
    )

    auxiliary = auxiliary_benchmarks(securities)
    all_downloads = securities + auxiliary
    provider = price_source or YahooFinancePriceSource(
        app_settings.paths.cache,
        cache_ttl_hours=app_settings.price.cache_ttl_hours,
        confidence=app_settings.price.confidence,
    )

    LOGGER.info("Downloading prices for %d primary and %d benchmark tickers...", len(securities), len(auxiliary))
    price_results = _download_prices(
        all_downloads,
        provider,
        period=app_settings.price.history_period,
        max_workers=app_settings.price.max_workers,
    )
    updated = sum(1 for result in price_results.values() if not result.frame.empty)
    LOGGER.info("%d/%d price histories available", updated, len(all_downloads))
    _persist_normalized_prices(price_results, app_settings.paths.processed_data / "prices")

    LOGGER.info("Calculating drawdowns and technical metrics...")
    scan_results: list[OpportunityCandidate] = []
    for security in securities:
        price_result = price_results.get(security.ticker.upper())
        if price_result is None:
            LOGGER.error("No provider result exists for %s", security.ticker)
            continue
        benchmark_result = (
            price_results.get(security.benchmark.upper()) if security.benchmark else None
        )
        sector_result = (
            price_results.get(security.sector_benchmark.upper())
            if security.sector_benchmark
            else None
        )
        scan_results.append(
            build_scan_result(
                price_result,
                app_settings.screening,
                benchmark_result=benchmark_result,
                sector_result=sector_result,
            )
        )
    ranked = rank_results(scan_results)
    ranked = [
        _enrich_with_fundamentals(
            result, fundamental_results.get(result.ticker.upper())
        )
        for result in ranked
    ]

    valuation_results: dict[str, ValuationAnalysisResult] = {}
    valuation_exported: list[Path] = []
    if app_settings.valuation.enabled:
        LOGGER.info("Calculating point-in-time valuation...")
        valuation_config = (
            load_valuation_config(app_settings.paths.valuation)
            if app_settings.paths.valuation is not None
            else ValuationConfig()
        )
        valuation_results = analyze_valuations(
            securities,
            fundamental_results,
            price_results,
            valuation_config,
            app_settings.valuation,
        )
        if valuation_results:
            valuation_exported = persist_valuation_results(
                list(valuation_results.values()),
                app_settings.paths.processed_data,
                app_settings.paths.reports,
            )
        ranked = [
            _enrich_with_valuation(
                result, valuation_results.get(result.ticker.upper())
            )
            for result in ranked
        ]
        valuation_available = sum(
            result.status == DataStatus.AVAILABLE
            for result in valuation_results.values()
        )
        LOGGER.info(
            "%d/%d valuations have at least one available method",
            valuation_available,
            len(valuation_results),
        )
    else:
        valuation_available = 0
    candidate_count = sum(result.is_candidate for result in ranked)
    LOGGER.info("%d large-decline candidates detected", candidate_count)

    news_results: dict[str, NewsSearchResult] = {}
    shock_results: dict[str, ShockAnalysisResult] = {}
    shock_exported: list[Path] = []
    if app_settings.shock.enabled:
        candidate_tickers = {
            result.ticker.upper() for result in ranked if result.is_candidate
        }
        candidate_securities = [
            security
            for security in securities
            if security.ticker.upper() in candidate_tickers
        ]
        LOGGER.info("Retrieving public news metadata for %d candidates...", len(candidate_securities))
        news_results = _run_news(
            candidate_securities,
            app_settings,
            source=news_source,
            as_of=fundamentals_as_of,
        )
        exposure_config = (
            load_macro_exposure_config(app_settings.paths.macro_exposures)
            if app_settings.paths.macro_exposures is not None
            else MacroExposureConfig()
        )
        taxonomy = (
            load_shock_taxonomy(app_settings.paths.shock_taxonomy)
            if app_settings.paths.shock_taxonomy is not None
            else ShockTaxonomyConfig()
        )
        for security in candidate_securities:
            ticker = security.ticker.upper()
            news = news_results.get(ticker)
            if news is None:
                continue
            shock_results[ticker] = analyze_shock(
                security,
                news,
                macro_analysis,
                exposure_config.for_security(security.ticker, security.sector),
                taxonomy,
                fundamental=fundamental_results.get(ticker),
                minimum_independent_sources=(
                    app_settings.shock.minimum_independent_sources
                ),
                minimum_score_coverage=app_settings.shock.minimum_score_coverage,
            )
        if news_results or shock_results:
            shock_exported = persist_shock_results(
                news_results,
                shock_results,
                app_settings.paths.processed_data,
                app_settings.paths.reports,
            )
        ranked = [
            _enrich_with_shock(result, shock_results.get(result.ticker.upper()))
            for result in ranked
        ]
        LOGGER.info("%d candidate shocks analyzed", len(shock_results))

    LOGGER.info("Exporting scan results...")
    exported = export_scan_results(
        ranked,
        app_settings.paths.reports,
        filename_prefix=app_settings.export.filename_prefix,
        write_csv=app_settings.export.csv,
        write_excel=app_settings.export.excel,
        run_metadata={
            "universe_path": str(configured_universe),
            "price_provider": app_settings.price.provider,
            "history_period": app_settings.price.history_period,
            "download_error_count": sum(bool(result.error) for result in price_results.values()),
            "fundamental_result_count": len(fundamental_results),
            "fundamental_available_count": fundamental_available,
            "valuation_result_count": len(valuation_results),
            "valuation_available_count": valuation_available,
            "macro_series_count": len(macro_results),
            "macro_available_count": macro_available,
            "news_result_count": len(news_results),
            "shock_result_count": len(shock_results),
            "fundamental_as_of": (
                (
                    fundamental_list[0].as_of
                    if fundamental_list
                    else normalize_as_of(
                        fundamentals_as_of
                        if fundamentals_as_of is not None
                        else app_settings.fundamentals.as_of
                    )
                ).isoformat()
                if app_settings.fundamentals.enabled
                else None
            ),
        },
    )
    for path in exported:
        LOGGER.info("Created %s", path)

    errors = {
        result.security.ticker: result.error
        for result in price_results.values()
        if result.error is not None
    }
    fundamental_errors = {
        result.ticker: result.error
        for result in fundamental_list
        if result.error is not None
    }
    valuation_errors = {
        result.ticker: result.error
        for result in valuation_results.values()
        if result.error is not None
    }
    macro_errors = {
        key: result.error
        for key, result in macro_results.items()
        if result.error is not None
    }
    shock_errors = {
        ticker: result.error
        for ticker, result in shock_results.items()
        if result.error is not None
    }
    return PipelineResult(
        results=ranked,
        exported_files=exported,
        download_errors=errors,
        fundamental_results=fundamental_results,
        fundamental_exported_files=fundamental_exported,
        fundamental_errors=fundamental_errors,
        valuation_results=valuation_results,
        valuation_exported_files=valuation_exported,
        valuation_errors=valuation_errors,
        macro_results=macro_results,
        macro_analysis=macro_analysis,
        macro_exported_files=macro_exported,
        macro_errors=macro_errors,
        news_results=news_results,
        shock_results=shock_results,
        shock_exported_files=shock_exported,
        shock_errors=shock_errors,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scan an explicit equity universe for price declines and "
            "point-in-time fundamentals, valuation, macro vintages, and shocks."
        )
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="Path to settings YAML (default: config/settings.yaml)",
    )
    parser.add_argument(
        "--universe",
        default=None,
        help="Optional universe YAML override",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="Shared point-in-time cutoff for every data stage (ISO date or timestamp)",
    )
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    run_pipeline(
        args.config,
        universe_path=args.universe,
        fundamentals_as_of=args.as_of,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

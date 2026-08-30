"""Point-in-time orchestration for prices, fundamentals, valuation, and shocks."""

from __future__ import annotations

import argparse
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from src.analysis.fundamentals import analyze_fundamentals
from src.analysis.historical import analyze_historical_analogues
from src.analysis.macro import analyze_macro_series
from src.analysis.shock import analyze_shock, augment_shock_with_historical
from src.analysis.valuation import analyze_valuations
from src.alerts.engine import build_alerts, persist_local_alerts
from src.backtest.archive import archive_live_run
from src.config import AppSettings, load_settings
from src.data.fundamentals import (
    SecEdgarFundamentalSource,
    is_sec_eligible,
    normalize_as_of,
    unavailable_fundamental_data,
)
from src.data.fx import FrankfurterFxSource, convert_currency
from src.data.macro import FredMacroSource, unavailable_macro_series
from src.data.public_macro import CboePutCallSource, CftcCotSource, EcbMacroSource
from src.data.news import (
    GDELT_DOC_URL,
    GdeltNewsSource,
    build_news_query,
    unavailable_news_result,
)
from src.data.prices import (
    YahooFinancePriceSource,
    assess_price_quality,
    empty_price_frame,
)
from src.data.sec_edgar import SecEdgarClient
from src.data.sources import (
    FundamentalSource,
    FxSource,
    MacroSource,
    NewsSource,
    PriceHistoryResult,
    PriceSource,
)
from src.forecasting.scenarios import analyze_scenarios
from src.macro_config import (
    MacroConfig,
    MacroExposureConfig,
    MacroSeriesDefinition,
    ShockTaxonomyConfig,
    load_macro_config,
    load_macro_exposure_config,
    load_shock_taxonomy,
)
from src.models import (
    DataQuality,
    DataStatus,
    FundamentalAnalysisResult,
    FxRateResult,
    HistoricalAnalogueResult,
    MacroSeriesAnalysis,
    MacroSeriesResult,
    NewsSearchResult,
    OpportunityCandidate,
    OpportunityAlert,
    ScenarioAnalysisResult,
    ScoringAnalysisResult,
    Security,
    ShockAnalysisResult,
    ValuationAnalysisResult,
)
from src.reporting.export import export_scan_results
from src.reporting.fundamentals import persist_fundamental_results
from src.reporting.fx import persist_fx_results
from src.reporting.historical import persist_historical_results
from src.reporting.macro_shock import persist_macro_results, persist_shock_results
from src.reporting.scenarios import persist_scenario_results
from src.reporting.scoring import persist_scoring_results
from src.reporting.valuation import persist_valuation_results
from src.scoring.opportunity import analyze_opportunity_score
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
    fx_results: dict[str, FxRateResult]
    fx_exported_files: list[Path]
    fx_errors: dict[str, str]
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
    historical_results: dict[str, HistoricalAnalogueResult]
    historical_exported_files: list[Path]
    historical_errors: dict[str, str]
    scenario_results: dict[str, ScenarioAnalysisResult]
    scenario_exported_files: list[Path]
    scenario_errors: dict[str, str]
    scoring_results: dict[str, ScoringAnalysisResult]
    scoring_exported_files: list[Path]
    scoring_errors: dict[str, str]
    backtest_archive_files: list[Path]
    backtest_archive_error: str | None
    alerts: list[OpportunityAlert]
    alert_exported_files: list[Path]
    alert_error: str | None


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
    cutoff: datetime | None = None,
    normalized_output_dir: Path | None = None,
) -> dict[str, PriceHistoryResult]:
    """Download prices in bounded batches and stop cleanly on provider quotas.

    Submitting the whole universe at once makes a transient Yahoo quota consume
    thousands of requests that are guaranteed to fail.  Small batches let a
    later run resume from the valid cache without turning the rest of the
    alphabet into a misleading provider-absence result.
    """

    downloaded: dict[str, PriceHistoryResult] = {}
    if not securities:
        return downloaded

    def unavailable(security: Security, error: str) -> PriceHistoryResult:
        return PriceHistoryResult(
            security=security,
            frame=empty_price_frame(),
            status=DataStatus.DATA_UNAVAILABLE,
            data_quality=DataQuality.UNAVAILABLE,
            source=type(source).__name__,
            source_url=None,
            error=error,
        )

    batch_size = max(1, max_workers * 2)
    for start in range(0, len(securities), batch_size):
        batch = securities[start : start + batch_size]
        rate_limited = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(source.fetch, security, period=period): security
                for security in batch
            }
            for future in as_completed(futures):
                security = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # custom provider errors cannot abort the whole universe
                    LOGGER.exception("Unhandled provider error for %s", security.ticker)
                    result = unavailable(security, f"{type(exc).__name__}: {exc}")
                ticker = security.ticker.upper()
                if cutoff is not None:
                    result = _filter_prices_as_of({ticker: result}, cutoff)[ticker]
                if normalized_output_dir is not None:
                    cutoff_for_age = (
                        cutoff
                        if cutoff is not None and cutoff.tzinfo is not None
                        else cutoff.replace(tzinfo=UTC) if cutoff is not None else None
                    )
                    is_live_cutoff = (
                        cutoff_for_age is not None
                        and abs((datetime.now(UTC) - cutoff_for_age).total_seconds())
                        < 6 * 60 * 60
                    )
                    _persist_normalized_prices(
                        {ticker: result},
                        normalized_output_dir,
                        skip_existing_cache=is_live_cutoff,
                    )
                    _compact_price_frames({ticker: result})
                downloaded[ticker] = result
                if result.error:
                    LOGGER.warning("%s: %s", security.ticker, result.error)
                    normalized_error = result.error.lower()
                    if "ratelimit" in normalized_error or "too many requests" in normalized_error:
                        rate_limited += 1

        quota_threshold = min(len(batch), max(2, max_workers))
        if rate_limited >= quota_threshold:
            remaining = securities[start + len(batch) :]
            LOGGER.error(
                "Price-provider quota circuit opened after %d rate-limited "
                "responses; deferring %d instruments to the next cached run",
                rate_limited,
                len(remaining),
            )
            for security in remaining:
                downloaded[security.ticker.upper()] = unavailable(
                    security,
                    "rate_limit_circuit_open: deferred to the next cached run",
                )
            break
    return downloaded


def _persist_normalized_prices(
    results: dict[str, PriceHistoryResult],
    output_dir: Path,
    *,
    skip_existing_cache: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for result in results.values():
        if result.frame.empty:
            continue
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", result.security.ticker)
        output_path = output_dir / f"{safe_name}.csv"
        if skip_existing_cache and result.from_cache and output_path.exists():
            continue
        result.frame.to_csv(output_path, index=False)


def _compact_price_frames(results: dict[str, PriceHistoryResult]) -> None:
    """Release columns not used by in-memory analysis after normalized persistence.

    Provenance and OHLCV remain in the normalized CSV files.  Keeping repeated
    source/status strings for decades of daily rows across a 6k-title universe
    otherwise consumes several gigabytes while the scanner only needs dates,
    close prices, retrieval metadata, and listing labels.
    """

    analysis_columns = (
        "observation_date",
        "close",
        "adjusted_close",
        "exchange",
        "currency",
        "retrieved_at",
    )
    for result in results.values():
        if result.frame.empty:
            continue
        retained = [column for column in analysis_columns if column in result.frame.columns]
        result.frame = result.frame.loc[:, retained].copy()


def _select_deep_analysis_securities(
    ranked: list[OpportunityCandidate],
    securities: list[Security],
    limit: int,
) -> list[Security]:
    """Select a reproducible external-data shortlist from all price candidates.

    Four fifths are selected by a disclosed preliminary composite using only
    already-computed fields.  One fifth is reserved for the most severe price
    declines so regions without SEC coverage are not automatically eliminated.
    This is a cost/rate-limit gate, not the final opportunity ranking.
    """

    candidates = [result for result in ranked if result.is_candidate]
    if len(candidates) <= limit:
        selected_tickers = {result.ticker.upper() for result in candidates}
    else:
        severity_reserve = max(1, limit // 5)
        by_severity = sorted(
            candidates,
            key=lambda item: item.decline_severity_score,
            reverse=True,
        )
        reserved = by_severity[:severity_reserve]
        reserved_tickers = {item.ticker.upper() for item in reserved}

        def covered_score(value: float | None, coverage: float | None) -> float:
            if value is None or coverage is None:
                return 0.0
            return value * coverage

        def preliminary_score(item: OpportunityCandidate) -> float:
            return (
                0.45
                * covered_score(
                    item.fundamental_quality_score,
                    item.fundamental_quality_coverage,
                )
                + 0.25
                * covered_score(item.valuation_score, item.valuation_coverage)
                + 0.30 * item.decline_severity_score
            )

        by_composite = sorted(
            (item for item in candidates if item.ticker.upper() not in reserved_tickers),
            key=lambda item: (preliminary_score(item), item.decline_severity_score),
            reverse=True,
        )
        selected = reserved + by_composite[: limit - len(reserved)]
        selected_tickers = {item.ticker.upper() for item in selected}

    return [
        security
        for security in securities
        if security.ticker.upper() in selected_tickers
    ]


def _filter_prices_as_of(
    results: dict[str, PriceHistoryResult], cutoff: datetime
) -> dict[str, PriceHistoryResult]:
    """Remove observations after the shared cutoff before any calculation.

    Providers may return their full current history even for a historical run.
    Filtering centrally ensures the drawdown scanner, benchmarks, valuation, and
    persisted normalized frames all see the same point-in-time price history.
    """

    eligible_date = cutoff.date()
    if cutoff.time() < time(23, 59, 59):
        eligible_date -= timedelta(days=1)
    filtered: dict[str, PriceHistoryResult] = {}
    for ticker, result in results.items():
        if result.frame.empty:
            filtered[ticker] = result
            continue
        dates = pd.to_datetime(result.frame["observation_date"], errors="coerce")
        eligible = dates.notna() & (dates.dt.date <= eligible_date)
        frame = result.frame.loc[eligible].copy().reset_index(drop=True)
        if frame.empty:
            reason = (
                "data_unavailable: no price observation exists on or before "
                f"the point-in-time cutoff {cutoff.isoformat()}"
            )
            filtered[ticker] = PriceHistoryResult(
                security=result.security,
                frame=empty_price_frame(),
                status=DataStatus.DATA_UNAVAILABLE,
                data_quality=DataQuality.UNAVAILABLE,
                source=result.source,
                source_url=result.source_url,
                error=reason if result.error is None else f"{result.error}; {reason}",
                from_cache=result.from_cache,
                warnings=[*result.warnings, reason],
            )
            continue
        filtered[ticker] = PriceHistoryResult(
            security=result.security,
            frame=frame,
            status=result.status,
            data_quality=(
                assess_price_quality(frame)
                if result.status == DataStatus.AVAILABLE
                else result.data_quality
            ),
            source=result.source,
            source_url=result.source_url,
            error=result.error,
            from_cache=result.from_cache,
            warnings=list(result.warnings),
        )
    return filtered


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
    def process_security(security: Security) -> FundamentalAnalysisResult:
        if not is_sec_eligible(security):
            data = unavailable_fundamental_data(
                security,
                cutoff,
                DataStatus.NOT_APPLICABLE,
                "SEC EDGAR provider requires a US reporting issuer or explicit CIK",
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
        return analyze_fundamentals(
            data,
            minimum_score_coverage=settings.fundamentals.minimum_score_coverage,
        )

    results: list[FundamentalAnalysisResult] = []
    total = len(securities)
    if not securities:
        return results
    # HTTP calls remain serialized and rate-limited inside SecEdgarClient. The
    # pool overlaps only local JSON/XBRL decoding and per-company calculations.
    with ThreadPoolExecutor(max_workers=settings.fundamentals.max_workers) as executor:
        for position, result in enumerate(executor.map(process_security, securities), start=1):
            results.append(result)
            if position % 250 == 0 or position == total:
                LOGGER.info("Fundamentals progress: %d/%d", position, total)
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
    cache_dir = settings.paths.macro_cache or (
        settings.project_root / "data" / "cache" / "macro"
    )
    providers: dict[str, MacroSource] = {}
    provider_errors: dict[str, str] = {}

    def configured_provider(name: str) -> MacroSource | None:
        if source is not None:
            return source
        if name in providers:
            return providers[name]
        try:
            if name == "fred":
                api_key = os.getenv(settings.macro.api_key_env, "").strip()
                if not api_key:
                    raise RuntimeError(
                        f"{settings.macro.api_key_env} is required for FRED/ALFRED access"
                    )
                result: MacroSource = FredMacroSource(
                    cache_dir / "fred",
                    api_key=api_key,
                    cache_ttl_hours=settings.macro.cache_ttl_hours,
                    timeout_seconds=settings.macro.timeout_seconds,
                    max_retries=settings.macro.max_retries,
                )
            elif name == "ecb":
                result = EcbMacroSource(
                    cache_dir / "ecb",
                    cache_ttl_hours=settings.macro.cache_ttl_hours,
                    timeout_seconds=settings.macro.timeout_seconds,
                    max_retries=settings.macro.max_retries,
                )
            elif name == "cboe_put_call":
                result = CboePutCallSource(
                    cache_dir / "cboe",
                    cache_ttl_hours=settings.macro.cache_ttl_hours,
                    timeout_seconds=settings.macro.timeout_seconds,
                    max_retries=settings.macro.max_retries,
                )
            elif name == "cftc_cot":
                result = CftcCotSource(
                    cache_dir / "cftc",
                    cache_ttl_hours=settings.macro.cache_ttl_hours,
                    timeout_seconds=settings.macro.timeout_seconds,
                    max_retries=settings.macro.max_retries,
                )
            else:  # guarded by MacroSeriesDefinition validation
                raise RuntimeError(f"unsupported macro provider {name!r}")
            providers[name] = result
            return result
        except Exception as exc:
            provider_errors[name] = f"{type(exc).__name__}: {exc}"
            return None
    raw: dict[str, MacroSeriesResult] = {}
    for key, definition in config.series.items():
        if not definition.enabled:
            continue
        configured_source = configured_provider(definition.provider)
        if configured_source is None:
            result = unavailable_macro_series(
                key,
                definition,
                cutoff,
                _macro_source_url(definition),
                provider_errors.get(definition.provider, "macro source unavailable"),
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
                    _macro_source_url(definition),
                    f"{type(exc).__name__}: {exc}",
                )
        raw[key] = result
    analyses = {key: analyze_macro_series(result) for key, result in raw.items()}
    return raw, analyses


def _macro_source_url(definition: MacroSeriesDefinition) -> str:
    if definition.provider == "ecb":
        api_path = definition.series_id.replace(".", "/", 1)
        return f"https://data-api.ecb.europa.eu/service/data/{api_path}"
    if definition.provider == "cboe_put_call":
        return "https://www.cboe.com/markets/us/options/market-statistics/daily/"
    if definition.provider == "cftc_cot":
        return f"https://publicreporting.cftc.gov/resource/{definition.series_id}"
    return f"https://fred.stlouisfed.org/series/{definition.series_id}"


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

    def fetch_one(security: Security) -> tuple[str, NewsSearchResult]:
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
        return security.ticker.upper(), result

    with ThreadPoolExecutor(max_workers=settings.news.max_workers) as executor:
        futures = [executor.submit(fetch_one, security) for security in securities]
        for future in as_completed(futures):
            ticker, result = future.result()
            results[ticker] = result
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


def _enrich_with_fx(
    result: OpportunityCandidate,
    fx_results: dict[str, FxRateResult],
) -> OpportunityCandidate:
    """Add explicit USD/EUR equivalents without replacing source currencies."""

    values: dict[str, float | datetime | dict | None] = {
        "current_price_usd": None,
        "current_price_eur": None,
        "market_cap_usd": None,
        "market_cap_eur": None,
        "fx_as_of": None,
    }
    metrics: dict[str, dict] = {}
    sources = list(result.sources)
    pairs = (
        ("current_price", result.current_price, result.currency),
        ("market_cap", result.market_cap, result.market_cap_currency),
    )
    for field, amount, currency in pairs:
        if amount is None or not currency:
            continue
        for target in ("USD", "EUR"):
            pair = f"{currency.upper()}/{target}"
            rate_result = fx_results.get(pair)
            if rate_result is None:
                continue
            converted = convert_currency(amount, rate_result)
            values[f"{field}_{target.lower()}"] = converted
            observation = rate_result.observation
            metrics[pair] = {
                "status": rate_result.status.value,
                "rate": observation.rate if observation else None,
                "observation_date": (
                    observation.observation_date.isoformat() if observation else None
                ),
                "source_url": rate_result.source_url,
                "error": rate_result.error,
            }
            if observation is not None:
                values["fx_as_of"] = rate_result.as_of
                source = {
                    "name": observation.source,
                    "url": observation.source_url,
                    "role": "fx_conversion",
                    "observation_date": observation.observation_date.isoformat(),
                    "retrieved_at": observation.retrieved_at.isoformat(),
                    "currency": target,
                    "unit": observation.unit,
                    "confidence": observation.confidence,
                }
                if source not in sources:
                    sources.append(source)
    values["fx_metrics"] = metrics
    return OpportunityCandidate.model_validate(
        {**result.model_dump(), **values, "sources": sources}
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
        "shock_specification_criteria_coverage": (
            shock.specification_criteria_coverage
        ),
        "shock_missing_criteria": shock.missing_criteria,
        "shock_conclusion": shock.conclusion,
        "shock_metrics": {
            "evidence": [item.model_dump(mode="json") for item in shock.evidence],
            "macro_associations": [
                item.model_dump(mode="json") for item in shock.macro_associations
            ],
            "criterion_statuses": {
                name: status.value
                for name, status in shock.criterion_statuses.items()
            },
            "score_components": {
                name: component.model_dump(mode="json")
                for name, component in shock.temporary_score.components.items()
            },
        },
        "sources": result.sources
        + [{**source, "role": source.get("role", "shock")} for source in shock.sources],
    }
    return OpportunityCandidate.model_validate({**result.model_dump(), **updates})


def _enrich_with_historical(
    result: OpportunityCandidate,
    historical: HistoricalAnalogueResult | None,
) -> OpportunityCandidate:
    if historical is None:
        return result
    updates = {
        "historical_status": historical.status,
        "historical_data_quality": historical.data_quality,
        "historical_as_of": historical.as_of,
        "historical_analogue_count": len(historical.analogues),
        "best_historical_similarity": historical.best_similarity_score,
        "historical_metrics": {
            "methodology_version": historical.methodology_version,
            "similarity_weights": historical.similarity_weights,
            "detected_completed_episode_count": (
                historical.detected_completed_episode_count
            ),
            "current_episode": (
                historical.current_episode.model_dump(mode="json")
                if historical.current_episode is not None
                else None
            ),
            "analogues": [
                item.model_dump(mode="json") for item in historical.analogues
            ],
            "error": historical.error,
        },
        "sources": result.sources
        + [
            {
                "name": historical.source,
                "url": historical.source_url,
                "status": historical.status.value,
                "role": "historical_analogue_prices",
            }
        ],
    }
    return OpportunityCandidate.model_validate({**result.model_dump(), **updates})


def _enrich_with_scenario(
    result: OpportunityCandidate,
    scenario: ScenarioAnalysisResult | None,
) -> OpportunityCandidate:
    if scenario is None:
        return result

    def metric_value(metric) -> float | None:
        return metric.value if metric is not None else None

    updates = {
        "scenario_status": scenario.status,
        "scenario_data_quality": scenario.data_quality,
        "scenario_as_of": scenario.as_of,
        "fair_value": metric_value(scenario.targets.fair_value),
        "normalized_fair_value_scenario": metric_value(
            scenario.targets.normalized_fair_value
        ),
        "bear_target": metric_value(scenario.targets.bear_target),
        "base_target": metric_value(scenario.targets.base_target),
        "bull_target": metric_value(scenario.targets.bull_target),
        "tp1": metric_value(scenario.targets.tp1),
        "tp2": metric_value(scenario.targets.tp2),
        "tp3": metric_value(scenario.targets.tp3),
        "upside_base": metric_value(scenario.risk_reward.upside_base),
        "upside_bull": metric_value(scenario.risk_reward.upside_bull),
        "downside_bear": metric_value(scenario.risk_reward.downside_bear),
        "risk_reward": metric_value(scenario.risk_reward.risk_reward),
        "fundamental_invalidation": [
            item.model_dump(mode="json") for item in scenario.invalidation_levels
        ],
        "scenario_metrics": {
            "methodology_version": scenario.methodology_version,
            "cases": {
                name: case.model_dump(mode="json")
                for name, case in scenario.cases.items()
            },
            "targets": scenario.targets.model_dump(mode="json"),
            "risk_reward": scenario.risk_reward.model_dump(mode="json"),
            "missing_invalidation_dimensions": (
                scenario.missing_invalidation_dimensions
            ),
            "error": scenario.error,
        },
        "sources": result.sources
        + [
            {**source, "role": source.get("role", "scenario")}
            for source in scenario.sources
        ],
    }
    return OpportunityCandidate.model_validate({**result.model_dump(), **updates})


def _enrich_with_scoring(
    result: OpportunityCandidate,
    scoring: ScoringAnalysisResult | None,
) -> OpportunityCandidate:
    if scoring is None:
        return result
    updates = {
        "normalization_score": scoring.normalization.score,
        "normalization_score_coverage": scoring.normalization.coverage,
        "catalyst_score": scoring.catalyst.score,
        "catalyst_score_coverage": scoring.catalyst.coverage,
        "future_growth_score": scoring.future_growth.score,
        "risk_score": scoring.risk.score,
        "risk_score_coverage": scoring.risk.coverage,
        "opportunity_score": scoring.opportunity.score,
        "opportunity_observed_score": scoring.opportunity.observed_score,
        "opportunity_score_coverage": scoring.opportunity.coverage,
        "opportunity_score_status": scoring.opportunity.status,
        "opportunity_data_quality": scoring.data_quality,
        "confidence_score": scoring.confidence_score,
        "score_band": scoring.score_band,
        "scoring_metrics": scoring.model_dump(mode="json"),
        "sources": result.sources
        + [{**source, "role": "opportunity_scoring"} for source in scoring.sources],
        "retrieved_at": max(result.retrieved_at, scoring.retrieved_at),
    }
    return OpportunityCandidate.model_validate({**result.model_dump(), **updates})


def _rank_with_opportunity_scores(
    results: list[OpportunityCandidate],
) -> list[OpportunityCandidate]:
    candidates = [item for item in results if item.is_candidate]
    others = [item.model_copy(update={"rank": None}) for item in results if not item.is_candidate]
    candidates.sort(
        key=lambda item: (
            item.opportunity_score is not None,
            item.opportunity_score if item.opportunity_score is not None else -1.0,
            item.decline_severity_score,
        ),
        reverse=True,
    )
    ranked = [item.model_copy(update={"rank": index}) for index, item in enumerate(candidates, 1)]
    return ranked + others


def run_pipeline(
    settings: AppSettings | str | Path = "config/settings.yaml",
    *,
    universe_path: str | Path | None = None,
    price_source: PriceSource | None = None,
    fundamental_source: FundamentalSource | None = None,
    macro_source: MacroSource | None = None,
    fx_source: FxSource | None = None,
    news_source: NewsSource | None = None,
    fundamentals_as_of: date | datetime | str | None = None,
) -> PipelineResult:
    """Run the integrated scanner without fabricating missing external data."""

    app_settings = load_settings(settings) if not isinstance(settings, AppSettings) else settings
    _configure_logging(app_settings.logging.level)
    cutoff = normalize_as_of(
        fundamentals_as_of
        if fundamentals_as_of is not None
        else app_settings.fundamentals.as_of
    )

    configured_universe = Path(universe_path).resolve() if universe_path else app_settings.paths.universe
    LOGGER.info("Loading universe from %s...", configured_universe)
    securities = load_universe(configured_universe)
    LOGGER.info("%d securities loaded", len(securities))
    if not securities:
        LOGGER.warning(
            "Universe is empty. Add securities to config/universe.yaml or configure csv_path."
        )

    # Fundamentals are deliberately deferred until after the inexpensive price
    # screen. Every security is screened, while SEC/XBRL analysis is focused on
    # the large-decline candidates for which the strategy can act.
    fundamental_list: list[FundamentalAnalysisResult] = []
    fundamental_results: dict[str, FundamentalAnalysisResult] = {}
    fundamental_available = 0
    fundamental_exported: list[Path] = []

    fx_results: dict[str, FxRateResult] = {}
    fx_exported: list[Path] = []
    if app_settings.fx.enabled:
        LOGGER.info("Updating dated ECB reference FX rates...")
        provider_fx = fx_source or FrankfurterFxSource(
            app_settings.paths.cache,
            cache_ttl_hours=app_settings.fx.cache_ttl_hours,
            timeout_seconds=app_settings.fx.timeout_seconds,
            max_retries=app_settings.fx.max_retries,
        )
        original_currencies = sorted(
            {
                currency.upper()
                for security in securities
                for currency in (security.currency, security.market_cap_currency)
                if currency
            }
        )
        for base in original_currencies:
            for quote in app_settings.fx.target_currencies:
                pair = f"{base}/{quote}"
                fx_results[pair] = provider_fx.fetch(base, quote, as_of=cutoff)
        if fx_results:
            fx_exported = persist_fx_results(
                fx_results, app_settings.paths.processed_data, app_settings.paths.reports
            )
        LOGGER.info(
            "%d/%d FX pairs available",
            sum(item.status == DataStatus.AVAILABLE for item in fx_results.values()),
            len(fx_results),
        )

    LOGGER.info("Updating point-in-time macro vintages...")
    macro_results, macro_analysis = _run_macro(
        app_settings,
        source=macro_source,
        as_of=cutoff,
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
    downloaded_price_results = _download_prices(
        all_downloads,
        provider,
        period=app_settings.price.history_period,
        max_workers=app_settings.price.max_workers,
        cutoff=cutoff,
        normalized_output_dir=app_settings.paths.processed_data / "prices",
    )
    price_results = downloaded_price_results
    updated = sum(
        1
        for result in price_results.values()
        if result.status == DataStatus.AVAILABLE and not result.frame.empty
    )
    LOGGER.info("%d/%d price histories available", updated, len(all_downloads))

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
    ranked = [_enrich_with_fx(result, fx_results) for result in ranked]
    candidate_tickers = {
        result.ticker.upper() for result in ranked if result.is_candidate
    }
    candidate_securities = [
        security for security in securities
        if security.ticker.upper() in candidate_tickers
    ]
    LOGGER.info(
        "Updating point-in-time fundamentals for %d/%d price-screen candidates...",
        len(candidate_securities),
        len(securities),
    )
    fundamental_list = _run_fundamentals(
        candidate_securities,
        app_settings,
        source=fundamental_source,
        as_of=cutoff,
    )
    fundamental_results = {
        result.ticker.upper(): result for result in fundamental_list
    }
    fundamental_available = sum(
        result.status == DataStatus.AVAILABLE for result in fundamental_list
    )
    LOGGER.info(
        "%d/%d candidate fundamental histories available",
        fundamental_available,
        len(fundamental_list),
    )
    if fundamental_list:
        fundamental_exported = persist_fundamental_results(
            fundamental_list,
            app_settings.paths.processed_data,
            app_settings.paths.reports,
        )
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
        candidate_securities = _select_deep_analysis_securities(
            ranked,
            securities,
            app_settings.news.deep_analysis_limit,
        )
        LOGGER.info(
            "Retrieving public news metadata for %d/%d preliminary deep-analysis candidates...",
            len(candidate_securities),
            candidate_count,
        )
        news_results = _run_news(
            candidate_securities,
            app_settings,
            source=news_source,
            as_of=cutoff,
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
        LOGGER.info("%d candidate shocks analyzed", len(shock_results))

    historical_results: dict[str, HistoricalAnalogueResult] = {}
    historical_exported: list[Path] = []
    if app_settings.historical.enabled:
        candidate_tickers = {
            result.ticker.upper() for result in ranked if result.is_candidate
        }
        historical_completed = 0
        for security in securities:
            ticker = security.ticker.upper()
            if ticker not in candidate_tickers or ticker not in price_results:
                continue
            historical_results[ticker] = analyze_historical_analogues(
                security,
                price_results[ticker],
                app_settings.historical,
                as_of=cutoff,
                fundamental=fundamental_results.get(ticker),
                valuation=valuation_results.get(ticker),
            )
            historical_completed += 1
            if historical_completed % 250 == 0:
                LOGGER.info(
                    "Historical analogue progress: %d/%d",
                    historical_completed,
                    len(candidate_tickers),
                )
        if historical_results:
            historical_exported = persist_historical_results(
                list(historical_results.values()),
                app_settings.paths.processed_data,
                app_settings.paths.reports,
            )
        ranked = [
            _enrich_with_historical(
                result, historical_results.get(result.ticker.upper())
            )
            for result in ranked
        ]
        historical_available = sum(
            result.status == DataStatus.AVAILABLE
            for result in historical_results.values()
        )
        LOGGER.info(
            "%d/%d candidates have completed historical analogues",
            historical_available,
            len(historical_results),
        )
    else:
        historical_available = 0

    if shock_results:
        shock_results = {
            ticker: augment_shock_with_historical(
                shock,
                historical_results.get(ticker),
                minimum_coverage=app_settings.shock.minimum_score_coverage,
            )
            for ticker, shock in shock_results.items()
        }
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

    scenario_results: dict[str, ScenarioAnalysisResult] = {}
    scenario_exported: list[Path] = []
    if app_settings.scenario.enabled:
        candidate_rows = {
            result.ticker.upper(): result for result in ranked if result.is_candidate
        }
        for security in securities:
            ticker = security.ticker.upper()
            row = candidate_rows.get(ticker)
            if row is None:
                continue
            scenario_results[ticker] = analyze_scenarios(
                security,
                fundamental_results.get(ticker),
                valuation_results.get(ticker),
                row.current_price,
                app_settings.scenario,
                as_of=cutoff,
            )
        if scenario_results:
            scenario_exported = persist_scenario_results(
                list(scenario_results.values()),
                app_settings.paths.processed_data,
                app_settings.paths.reports,
            )
        ranked = [
            _enrich_with_scenario(
                result, scenario_results.get(result.ticker.upper())
            )
            for result in ranked
        ]
        scenario_available = sum(
            result.status == DataStatus.AVAILABLE
            for result in scenario_results.values()
        )
        LOGGER.info(
            "%d/%d candidates have model-derived scenarios",
            scenario_available,
            len(scenario_results),
        )
    else:
        scenario_available = 0

    scoring_results: dict[str, ScoringAnalysisResult] = {}
    scoring_exported: list[Path] = []
    if app_settings.scoring.enabled:
        candidate_rows = {
            result.ticker.upper(): result for result in ranked if result.is_candidate
        }
        for security in securities:
            ticker = security.ticker.upper()
            row = candidate_rows.get(ticker)
            if row is None:
                continue
            scoring_results[ticker] = analyze_opportunity_score(
                security,
                fundamental_results.get(ticker),
                valuation_results.get(ticker),
                shock_results.get(ticker),
                historical_results.get(ticker),
                scenario_results.get(ticker),
                app_settings.scoring,
                as_of=cutoff,
                volatility=row.volatility,
                beta=row.beta,
            )
        if scoring_results:
            scoring_exported = persist_scoring_results(
                list(scoring_results.values()),
                app_settings.paths.processed_data,
                app_settings.paths.reports,
            )
        ranked = [
            _enrich_with_scoring(result, scoring_results.get(result.ticker.upper()))
            for result in ranked
        ]
        ranked = _rank_with_opportunity_scores(ranked)
        scoring_available = sum(
            result.status == DataStatus.AVAILABLE
            for result in scoring_results.values()
        )
        LOGGER.info(
            "%d/%d candidates have coverage-qualified opportunity scores",
            scoring_available,
            len(scoring_results),
        )
    else:
        scoring_available = 0

    backtest_archive_files: list[Path] = []
    backtest_archive_error: str | None = None
    if app_settings.backtest.archive_live_runs:
        try:
            backtest_archive_files = archive_live_run(
                ranked,
                securities,
                as_of=cutoff,
                archive_root=(
                    app_settings.paths.backtest_archive
                    or app_settings.project_root / "data" / "raw" / "backtest"
                ),
            )
            if backtest_archive_files:
                LOGGER.info(
                    "Archived live point-in-time signal bundle in %s",
                    backtest_archive_files[0].parent.parent,
                )
        except Exception as exc:
            backtest_archive_error = f"{type(exc).__name__}: {exc}"
            LOGGER.error("Backtest live archive unavailable: %s", backtest_archive_error)

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
            "fx_pair_count": len(fx_results),
            "fx_available_count": sum(
                item.status == DataStatus.AVAILABLE for item in fx_results.values()
            ),
            "valuation_result_count": len(valuation_results),
            "valuation_available_count": valuation_available,
            "macro_series_count": len(macro_results),
            "macro_available_count": macro_available,
            "news_result_count": len(news_results),
            "shock_result_count": len(shock_results),
            "historical_result_count": len(historical_results),
            "historical_available_count": historical_available,
            "scenario_result_count": len(scenario_results),
            "scenario_available_count": scenario_available,
            "scoring_result_count": len(scoring_results),
            "scoring_available_count": scoring_available,
            "backtest_archive_file_count": len(backtest_archive_files),
            "backtest_archive_error": backtest_archive_error,
            "pipeline_as_of": cutoff.isoformat(),
            "fundamental_as_of": (
                cutoff.isoformat() if app_settings.fundamentals.enabled else None
            ),
        },
    )
    for path in exported:
        LOGGER.info("Created %s", path)

    alerts = build_alerts(ranked, app_settings.alerts)
    delivered_alerts: list[OpportunityAlert] = []
    alert_exported: list[Path] = []
    alert_error: str | None = None
    if app_settings.alerts.enabled:
        alert_dir = app_settings.paths.alerts or (
            app_settings.paths.processed_data / "alerts"
        )
        alert_state = app_settings.paths.alert_state or (
            app_settings.paths.cache.parent / "alerts" / "state.json"
        )
        try:
            delivered_alerts, alert_exported = persist_local_alerts(
                alerts,
                alert_dir,
                alert_state,
                send_only_new=app_settings.alerts.send_only_new,
            )
        except (OSError, ValueError) as exc:
            alert_error = str(exc)
            LOGGER.error("Local alert delivery failed: %s", exc)
        LOGGER.info(
            "%d threshold-qualified alerts; %d new local alerts emitted",
            len(alerts),
            len(delivered_alerts),
        )

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
    fx_errors = {
        pair: result.error for pair, result in fx_results.items() if result.error is not None
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
    historical_errors = {
        ticker: result.error
        for ticker, result in historical_results.items()
        if result.error is not None
    }
    scenario_errors = {
        ticker: result.error
        for ticker, result in scenario_results.items()
        if result.error is not None
    }
    scoring_errors = {
        ticker: result.error
        for ticker, result in scoring_results.items()
        if result.error is not None
    }
    return PipelineResult(
        results=ranked,
        exported_files=exported,
        download_errors=errors,
        fundamental_results=fundamental_results,
        fundamental_exported_files=fundamental_exported,
        fundamental_errors=fundamental_errors,
        fx_results=fx_results,
        fx_exported_files=fx_exported,
        fx_errors=fx_errors,
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
        historical_results=historical_results,
        historical_exported_files=historical_exported,
        historical_errors=historical_errors,
        scenario_results=scenario_results,
        scenario_exported_files=scenario_exported,
        scenario_errors=scenario_errors,
        scoring_results=scoring_results,
        scoring_exported_files=scoring_exported,
        scoring_errors=scoring_errors,
        backtest_archive_files=backtest_archive_files,
        backtest_archive_error=backtest_archive_error,
        alerts=delivered_alerts,
        alert_exported_files=alert_exported,
        alert_error=alert_error,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scan an explicit equity universe for price declines and "
            "point-in-time fundamentals, valuation, analogues, scenarios, and scores."
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


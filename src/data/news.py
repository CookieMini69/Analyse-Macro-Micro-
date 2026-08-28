"""Public article metadata from GDELT DOC 2.0 without article-body scraping."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests

from src.data.fundamentals import normalize_as_of
from src.data.http_json import CachedJsonClient
from src.models import (
    DataQuality,
    DataStatus,
    NewsArticle,
    NewsSearchResult,
    Security,
)

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_MAX_HISTORY_DAYS = 90


class GdeltNewsSource:
    """Search GDELT's rolling article index and retain metadata only."""

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        cache_ttl_hours: int = 6,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self.client = CachedJsonClient(
            cache_dir,
            user_agent="AI Stock Opportunity Scanner/0.8",
            cache_ttl_hours=cache_ttl_hours,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            session=session,
        )

    def fetch(
        self,
        security: Security,
        *,
        as_of: date | datetime | str | None = None,
        lookback_days: int = 30,
        max_articles: int = 75,
    ) -> NewsSearchResult:
        cutoff = normalize_as_of(as_of)
        query = build_news_query(security)
        window_start = cutoff - timedelta(days=lookback_days)
        params = {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": max_articles,
            "startdatetime": window_start.strftime("%Y%m%d%H%M%S"),
            "enddatetime": cutoff.strftime("%Y%m%d%H%M%S"),
            "sort": "DateDesc",
        }
        public_url = f"{GDELT_DOC_URL}?{urlencode(params)}"
        now = datetime.now(UTC)
        if cutoff < now - timedelta(days=GDELT_MAX_HISTORY_DAYS):
            return unavailable_news_result(
                security,
                query,
                window_start,
                cutoff,
                public_url,
                "GDELT DOC only supports a rolling three-month search window",
            )
        try:
            response = self.client.get_json(
                GDELT_DOC_URL,
                params=params,
                public_source_url=public_url,
                cache_namespace=f"news_{security.ticker}",
            )
            articles = _normalize_articles(
                response.payload,
                query=query,
                index_source_url=public_url,
                retrieved_at=response.retrieved_at,
                window_start=window_start,
                cutoff=cutoff,
            )
            independent_domains = {
                item.source_domain for item in articles if item.source_domain
            }
            quality = (
                DataQuality.MEDIUM
                if len(independent_domains) >= 2
                else DataQuality.LOW
            )
            return NewsSearchResult(
                ticker=security.ticker,
                company=security.company,
                query=query,
                window_start=window_start,
                as_of=cutoff,
                status=DataStatus.AVAILABLE,
                data_quality=quality,
                articles=articles,
                retrieved_at=response.retrieved_at,
                source_url=public_url,
                from_cache=response.from_cache,
            )
        except Exception as exc:
            return unavailable_news_result(
                security,
                query,
                window_start,
                cutoff,
                public_url,
                f"{type(exc).__name__}: {exc}",
            )


def build_news_query(security: Security) -> str:
    if security.company:
        company = security.company.replace('"', " ").strip()
        return f'"{company}"'
    ticker = security.ticker.replace('"', " ").strip()
    return f'"{ticker}" (stock OR shares OR earnings)'


def _normalize_articles(
    payload: dict,
    *,
    query: str,
    index_source_url: str,
    retrieved_at: datetime,
    window_start: datetime,
    cutoff: datetime,
) -> list[NewsArticle]:
    rows = payload.get("articles", [])
    by_url: dict[str, NewsArticle] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        seen_at = _parse_gdelt_datetime(row.get("seendate"))
        if (
            not title
            or not _is_public_http_url(url)
            or seen_at is None
            or seen_at < window_start
            or seen_at > cutoff
        ):
            continue
        domain = str(row.get("domain") or "").strip() or urlparse(url).hostname
        by_url[url] = NewsArticle(
            title=title,
            url=url,
            source_domain=domain.lower() if domain else None,
            seen_at=seen_at,
            language=_optional_text(row.get("language")),
            source_country=_optional_text(row.get("sourcecountry")),
            query=query,
            index_source_url=index_source_url,
            retrieved_at=retrieved_at,
        )
    return sorted(by_url.values(), key=lambda item: item.seen_at, reverse=True)


def _parse_gdelt_datetime(value) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(raw, pattern).replace(tzinfo=UTC)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


def _is_public_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _optional_text(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def unavailable_news_result(
    security: Security,
    query: str,
    window_start: datetime,
    as_of: datetime,
    source_url: str,
    error: str,
) -> NewsSearchResult:
    return NewsSearchResult(
        ticker=security.ticker,
        company=security.company,
        query=query,
        window_start=window_start,
        as_of=as_of,
        status=DataStatus.DATA_UNAVAILABLE,
        data_quality=DataQuality.UNAVAILABLE,
        articles=[],
        retrieved_at=datetime.now(UTC),
        source_url=source_url,
        error=error,
    )

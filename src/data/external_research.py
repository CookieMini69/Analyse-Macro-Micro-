"""Point-in-time bridge for Bigdata.com and Aiera research exports.

Codex apps cannot be called from a standalone Python process. This module
defines the auditable hand-off: app results are exported as JSONL, validated,
hashed, and then merged with the public-news stream without losing the true
availability timestamp.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.data.fundamentals import normalize_as_of
from src.data.news import build_news_query
from src.models import DataQuality, DataStatus, NewsArticle, NewsSearchResult, Security

PROVIDER_DOCS = {
    "bigdata.com": "https://docs.bigdata.com/mcp-reference/introduction",
    "aiera": "https://rest.aiera.com/",
}


class ExternalResearchRecord(BaseModel):
    """One provider item with publication and actual availability separated."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    ticker: str
    title: str
    url: str
    published_at: datetime
    available_at: datetime
    retrieved_at: datetime
    document_type: str
    source_domain: str | None = None
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)

    @field_validator("provider")
    @classmethod
    def supported_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in PROVIDER_DOCS:
            raise ValueError("provider must be 'bigdata.com' or 'aiera'")
        return normalized

    @field_validator("ticker", "title", "document_type")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be empty")
        return normalized

    @field_validator("url")
    @classmethod
    def public_http_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be a public HTTP(S) URL")
        return value.strip()

    @model_validator(mode="after")
    def timestamps_are_causal(self) -> "ExternalResearchRecord":
        for field_name in ("published_at", "available_at", "retrieved_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None:
                raise ValueError(f"{field_name} must include a timezone")
        if self.available_at < self.published_at:
            raise ValueError("available_at cannot predate published_at")
        if self.retrieved_at < self.available_at:
            raise ValueError("retrieved_at cannot predate available_at")
        if not self.source_domain:
            self.source_domain = (urlparse(self.url).hostname or "").lower() or None
        return self


class LocalExternalResearchSource:
    """Read immutable validated JSONL records produced by either Codex app."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def fetch(
        self,
        security: Security,
        *,
        as_of: date | datetime | str | None = None,
        lookback_days: int = 30,
        max_articles: int = 75,
    ) -> NewsSearchResult:
        cutoff = normalize_as_of(as_of)
        window_start = cutoff - timedelta(days=lookback_days)
        query = build_news_query(security)
        records = [
            item for item in self._records()
            if item.ticker.upper() == security.ticker.upper()
            and window_start <= item.available_at.astimezone(UTC) <= cutoff
        ]
        records.sort(key=lambda item: item.available_at, reverse=True)
        articles = [
            NewsArticle(
                title=item.title,
                url=item.url,
                source_domain=item.source_domain,
                seen_at=item.available_at,
                query=query,
                index_source=f"{item.provider} point-in-time export",
                index_source_url=PROVIDER_DOCS[item.provider],
                retrieved_at=item.retrieved_at,
                confidence=item.confidence,
            )
            for item in records[:max_articles]
        ]
        domains = {item.source_domain for item in articles if item.source_domain}
        quality = DataQuality.MEDIUM if len(domains) >= 2 else DataQuality.LOW
        return NewsSearchResult(
            ticker=security.ticker,
            company=security.company,
            query=query,
            window_start=window_start,
            as_of=cutoff,
            status=DataStatus.AVAILABLE if articles else DataStatus.DATA_UNAVAILABLE,
            data_quality=quality if articles else DataQuality.UNAVAILABLE,
            articles=articles,
            retrieved_at=max(
                (item.retrieved_at for item in records), default=datetime.now(UTC)
            ),
            source_url=";".join(PROVIDER_DOCS.values()),
            error=None if articles else "no validated Bigdata.com/Aiera record for cutoff",
        )

    def _records(self) -> list[ExternalResearchRecord]:
        records: list[ExternalResearchRecord] = []
        if not self.directory.is_dir():
            return records
        for path in sorted(self.directory.glob("*.jsonl")):
            try:
                staged: list[ExternalResearchRecord] = []
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        staged.append(ExternalResearchRecord.model_validate_json(line))
                records.extend(staged)
            except (OSError, ValueError):
                # A malformed or partially copied archive is never used as evidence.
                continue
        return records


def merge_news_results(
    primary: NewsSearchResult, external: NewsSearchResult
) -> NewsSearchResult:
    """Merge sources by URL while retaining the earliest known availability."""

    by_url = {article.url: article for article in primary.articles}
    for article in external.articles:
        existing = by_url.get(article.url)
        if existing is None or article.seen_at < existing.seen_at:
            by_url[article.url] = article
    articles = sorted(by_url.values(), key=lambda item: item.seen_at, reverse=True)
    domains = {item.source_domain for item in articles if item.source_domain}
    status = DataStatus.AVAILABLE if articles else DataStatus.DATA_UNAVAILABLE
    quality = (
        DataQuality.MEDIUM if len(domains) >= 2 else
        DataQuality.LOW if articles else DataQuality.UNAVAILABLE
    )
    errors = [value for value in (primary.error, external.error) if value]
    return NewsSearchResult(
        ticker=primary.ticker,
        company=primary.company,
        query=primary.query,
        window_start=min(primary.window_start, external.window_start),
        as_of=min(primary.as_of, external.as_of),
        status=status,
        data_quality=quality,
        articles=articles,
        retrieved_at=max(primary.retrieved_at, external.retrieved_at),
        source_url=primary.source_url,
        from_cache=primary.from_cache,
        error="; ".join(errors) if status != DataStatus.AVAILABLE and errors else None,
    )


def validate_and_archive(input_path: str | Path, output_dir: str | Path) -> tuple[Path, Path]:
    """Validate an export, normalize it, and write a SHA-256 lineage manifest."""

    source = Path(input_path).resolve()
    records = [
        ExternalResearchRecord.model_validate_json(line)
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        raise ValueError("external research export is empty")
    normalized = "\n".join(
        item.model_dump_json() for item in sorted(
            records, key=lambda row: (row.available_at, row.provider, row.ticker, row.url)
        )
    ) + "\n"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"external_research_{digest[:16]}.jsonl"
    archive.write_text(normalized, encoding="utf-8")
    manifest = archive.with_suffix(".manifest.json")
    manifest.write_text(json.dumps({
        "schema": "external-research-point-in-time-v1",
        "providers": sorted({item.provider for item in records}),
        "record_count": len(records),
        "minimum_available_at": min(item.available_at for item in records).isoformat(),
        "maximum_available_at": max(item.available_at for item in records).isoformat(),
        "archived_at": datetime.now(UTC).isoformat(),
        "file": archive.name,
        "sha256": digest,
        "source_file_name": source.name,
        "secrets_stored": False,
    }, indent=2, sort_keys=True), encoding="utf-8")
    return archive, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Bigdata.com/Aiera JSONL export")
    parser.add_argument("input")
    parser.add_argument("--output", default="data/raw/external_research")
    args = parser.parse_args()
    for path in validate_and_archive(args.input, args.output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ExternalResearchRecord", "LocalExternalResearchSource", "merge_news_results",
    "validate_and_archive",
]

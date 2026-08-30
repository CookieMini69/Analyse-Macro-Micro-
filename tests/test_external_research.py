import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.data.external_research import (
    ExternalResearchRecord,
    LocalExternalResearchSource,
    merge_news_results,
    validate_and_archive,
)
from src.data.news import unavailable_news_result
from src.models import Security


def _record(**updates):
    payload = {
        "provider": "aiera", "ticker": "SAP.DE", "title": "SAP earnings call",
        "url": "https://example.com/sap-call", "published_at": "2025-01-10T17:00:00Z",
        "available_at": "2025-01-10T17:02:00Z", "retrieved_at": "2025-01-10T18:00:00Z",
        "document_type": "transcript", "source_domain": "example.com", "confidence": .8,
    }
    payload.update(updates)
    return payload


def test_record_rejects_future_leakage_order() -> None:
    with pytest.raises(ValueError, match="available_at cannot predate"):
        ExternalResearchRecord.model_validate(_record(available_at="2025-01-09T00:00:00Z"))


def test_validate_archive_and_cutoff_filter(tmp_path: Path) -> None:
    source = tmp_path / "export.jsonl"
    source.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
    archive, manifest = validate_and_archive(source, tmp_path / "archive")
    assert archive.exists() and manifest.exists()
    assert json.loads(manifest.read_text())["record_count"] == 1
    security = Security(ticker="SAP.DE", company="SAP", country="Germany")
    before = LocalExternalResearchSource(archive.parent).fetch(
        security, as_of="2025-01-10T17:01:00Z", lookback_days=30
    )
    after = LocalExternalResearchSource(archive.parent).fetch(
        security, as_of="2025-01-10T17:03:00Z", lookback_days=30
    )
    assert before.articles == []
    assert [item.title for item in after.articles] == ["SAP earnings call"]


def test_merge_promotes_available_external_evidence() -> None:
    security = Security(ticker="SAP.DE", company="SAP", country="Germany")
    cutoff = datetime(2025, 1, 11, tzinfo=UTC)
    primary = unavailable_news_result(
        security, '"SAP"', cutoff, cutoff, "https://gdelt.example", "unavailable"
    )
    record = ExternalResearchRecord.model_validate(_record())
    # Build through the local source to exercise the exact NewsArticle mapping.
    external_article = {
        "ticker": security.ticker, "company": security.company, "query": '"SAP"',
        "window_start": datetime(2025, 1, 1, tzinfo=UTC), "as_of": cutoff,
        "status": "available", "data_quality": "LOW",
        "articles": [{
            "title": record.title, "url": record.url, "source_domain": record.source_domain,
            "seen_at": record.available_at, "query": '"SAP"', "index_source_url": "https://rest.aiera.com/",
            "retrieved_at": record.retrieved_at,
        }],
        "retrieved_at": record.retrieved_at, "source_url": "https://rest.aiera.com/",
    }
    from src.models import NewsSearchResult
    merged = merge_news_results(primary, NewsSearchResult.model_validate(external_article))
    assert merged.status.value == "available"
    assert len(merged.articles) == 1

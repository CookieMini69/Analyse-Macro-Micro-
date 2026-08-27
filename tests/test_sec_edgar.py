from pathlib import Path

import pytest

from src.data.sec_edgar import SecEdgarClient, SecEdgarError, normalize_cik


class FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.headers = {}
        self.calls = 0

    def get(self, url: str, timeout: int):
        self.calls += 1
        return FakeResponse(self.payload)


def test_cik_is_zero_padded_and_validated() -> None:
    assert normalize_cik(320193) == "0000320193"
    with pytest.raises(ValueError):
        normalize_cik("ABC")


def test_sec_user_agent_must_contain_real_contact(tmp_path: Path) -> None:
    with pytest.raises(SecEdgarError, match="SEC_USER_AGENT"):
        SecEdgarClient(tmp_path, user_agent="anonymous bot")
    with pytest.raises(SecEdgarError, match="SEC_USER_AGENT"):
        SecEdgarClient(
            tmp_path, user_agent="Your Organization your.email@example.com"
        )


def test_json_response_is_cached_with_retrieval_metadata(tmp_path: Path) -> None:
    session = FakeSession({"answer": 42})
    client = SecEdgarClient(
        tmp_path,
        user_agent="Research Unit contact@example.invalid",
        session=session,
        requests_per_second=10,
    )
    first = client.get_json("https://data.sec.gov/test.json", cache_key="test")
    second = client.get_json("https://data.sec.gov/test.json", cache_key="test")
    assert first.payload == {"answer": 42}
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.retrieved_at == first.retrieved_at
    assert session.calls == 1


def test_filing_index_preserves_acceptance_timestamp(tmp_path: Path) -> None:
    client = SecEdgarClient(
        tmp_path,
        user_agent="Research Unit contact@example.invalid",
        session=FakeSession({}),
    )
    from src.data.sec_edgar import SecJsonResponse
    from datetime import UTC, datetime

    submissions = SecJsonResponse(
        payload={
            "filings": {
                "recent": {
                    "accessionNumber": ["0000000000-24-000001"],
                    "form": ["10-K"],
                    "filingDate": ["2024-02-01"],
                    "reportDate": ["2023-12-31"],
                    "acceptanceDateTime": ["2024-02-01T21:05:00.000Z"],
                    "primaryDocument": ["report.htm"],
                },
                "files": [],
            }
        },
        source_url="https://data.sec.gov/submissions/test.json",
        retrieved_at=datetime.now(UTC),
        from_cache=False,
    )
    indexed = client.build_filing_index(submissions)
    filing = indexed["0000000000-24-000001"]
    assert filing.acceptance_datetime == "2024-02-01T21:05:00.000Z"
    assert filing.primary_document == "report.htm"


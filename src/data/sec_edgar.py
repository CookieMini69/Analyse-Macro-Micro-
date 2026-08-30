"""Responsible, cache-aware access to the official SEC EDGAR JSON APIs."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)

SEC_DATA_BASE = "https://data.sec.gov"
SEC_WWW_BASE = "https://www.sec.gov"
COMPANY_TICKERS_URL = f"{SEC_WWW_BASE}/files/company_tickers.json"


class SecEdgarError(RuntimeError):
    """Raised for a configuration, transport, or SEC response failure."""


@dataclass(frozen=True, slots=True)
class SecJsonResponse:
    payload: dict[str, Any]
    source_url: str
    retrieved_at: datetime
    from_cache: bool


@dataclass(frozen=True, slots=True)
class FilingMetadata:
    accession: str
    form: str | None
    filed_date: str | None
    report_date: str | None
    acceptance_datetime: str | None
    primary_document: str | None


def normalize_cik(cik: str | int) -> str:
    digits = str(cik).strip()
    if not digits.isdigit() or len(digits) > 10:
        raise ValueError(f"invalid SEC CIK: {cik!r}")
    return digits.zfill(10)


def _validate_user_agent(user_agent: str) -> str:
    value = user_agent.strip()
    if not value or "@" not in value or "your.email@" in value.lower():
        raise SecEdgarError(
            "SEC_USER_AGENT must identify an organization/person and a real contact email"
        )
    return value


class SecEdgarClient:
    """Small SEC client enforcing identification, caching, and fair-access pacing."""

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        user_agent: str,
        cache_ttl_hours: int = 24,
        requests_per_second: float = 5.0,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.minimum_interval = 1.0 / requests_per_second
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": _validate_user_agent(user_agent),
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0

    def resolve_cik(self, ticker: str) -> tuple[str, str | None] | None:
        response = self.get_json(COMPANY_TICKERS_URL, cache_key="company_tickers")
        wanted = ticker.strip().upper()
        for item in response.payload.values():
            if str(item.get("ticker", "")).upper() == wanted:
                return normalize_cik(item["cik_str"]), item.get("title")
        return None

    def fetch_companyfacts(self, cik: str | int) -> SecJsonResponse:
        padded = normalize_cik(cik)
        return self.get_json(
            f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{padded}.json",
            cache_key=f"companyfacts_{padded}",
        )

    def fetch_submissions(self, cik: str | int) -> SecJsonResponse:
        padded = normalize_cik(cik)
        return self.get_json(
            f"{SEC_DATA_BASE}/submissions/CIK{padded}.json",
            cache_key=f"submissions_{padded}",
        )

    def build_filing_index(
        self,
        submissions: SecJsonResponse,
        *,
        required_accessions: set[str] | None = None,
    ) -> dict[str, FilingMetadata]:
        """Index recent filings and fetch only continuation files still needed."""

        payload = submissions.payload
        filings = payload.get("filings", {})
        index = _columnar_filing_index(filings.get("recent", {}))
        missing = set(required_accessions or ()) - set(index)
        for continuation in filings.get("files", []):
            if required_accessions is not None and not missing:
                break
            name = continuation.get("name")
            if not name:
                continue
            response = self.get_json(
                f"{SEC_DATA_BASE}/submissions/{name}",
                cache_key=f"submissions_continuation_{name}",
            )
            table = response.payload.get("filings", {}).get("recent", response.payload)
            index.update(_columnar_filing_index(table))
            missing = set(required_accessions or ()) - set(index)
        return index

    def get_json(self, url: str, *, cache_key: str | None = None) -> SecJsonResponse:
        key = cache_key or hashlib.sha256(url.encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"{_safe_name(key)}.json"
        cached = self._read_cache(cache_path, url)
        if cached is not None:
            return cached

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._request(url)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise SecEdgarError(f"SEC returned non-object JSON for {url}")
                retrieved_at = datetime.now(UTC)
                self._write_cache(cache_path, url, payload, retrieved_at)
                return SecJsonResponse(payload, url, retrieved_at, False)
            except (requests.RequestException, ValueError, SecEdgarError) as exc:
                last_error = exc
                retryable = True
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    status = exc.response.status_code
                    retryable = status in {408, 425, 429} or status >= 500
                if attempt >= self.max_retries or not retryable:
                    break
                delay = min(2**attempt, 8)
                LOGGER.warning(
                    "SEC request failed (%s); retrying in %ss", type(exc).__name__, delay
                )
                time.sleep(delay)
        raise SecEdgarError(f"SEC request failed for {url}: {last_error}") from last_error

    def _request(self, url: str) -> requests.Response:
        with self._request_lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.minimum_interval:
                time.sleep(self.minimum_interval - elapsed)
            response = self.session.get(url, timeout=self.timeout_seconds)
            self._last_request_at = time.monotonic()
            return response

    def _read_cache(self, path: Path, expected_url: str) -> SecJsonResponse | None:
        if not path.exists():
            return None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            retrieved_at = datetime.fromisoformat(wrapper["retrieved_at"])
            if retrieved_at.tzinfo is None:
                retrieved_at = retrieved_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - retrieved_at > self.cache_ttl:
                return None
            if wrapper.get("source_url") != expected_url:
                return None
            payload = wrapper["payload"]
            if not isinstance(payload, dict):
                return None
            return SecJsonResponse(payload, expected_url, retrieved_at, True)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            LOGGER.warning("Ignoring unreadable SEC cache %s", path)
            return None

    @staticmethod
    def _write_cache(
        path: Path, url: str, payload: dict[str, Any], retrieved_at: datetime
    ) -> None:
        wrapper = {
            "source_url": url,
            "retrieved_at": retrieved_at.isoformat(),
            "payload": payload,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(wrapper, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def _columnar_filing_index(table: dict[str, Any]) -> dict[str, FilingMetadata]:
    accessions = table.get("accessionNumber", [])
    fields = {
        "form": table.get("form", []),
        "filed_date": table.get("filingDate", []),
        "report_date": table.get("reportDate", []),
        "acceptance_datetime": table.get("acceptanceDateTime", []),
        "primary_document": table.get("primaryDocument", []),
    }

    def at(values: list[Any], index: int) -> Any:
        return values[index] if index < len(values) else None

    result: dict[str, FilingMetadata] = {}
    for position, accession in enumerate(accessions):
        if not accession:
            continue
        result[str(accession)] = FilingMetadata(
            accession=str(accession),
            form=at(fields["form"], position),
            filed_date=at(fields["filed_date"], position),
            report_date=at(fields["report_date"], position),
            acceptance_datetime=at(fields["acceptance_datetime"], position),
            primary_document=at(fields["primary_document"], position),
        )
    return result


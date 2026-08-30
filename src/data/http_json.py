"""Small cache-aware JSON client for responsible public API access."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class ExternalDataError(RuntimeError):
    """Raised when a public external API cannot return valid JSON."""


@dataclass(frozen=True, slots=True)
class CachedJsonResponse:
    payload: dict[str, Any]
    source_url: str
    retrieved_at: datetime
    from_cache: bool


class CachedJsonClient:
    """GET JSON with bounded retries, TTL caching, and redacted provenance URLs."""

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        user_agent: str,
        cache_ttl_hours: int,
        timeout_seconds: int,
        max_retries: int,
        session: requests.Session | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept": "application/json"}
        )

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, object],
        public_source_url: str,
        cache_namespace: str,
    ) -> CachedJsonResponse:
        cache_material = json.dumps(
            {"url": url, "params": params}, sort_keys=True, default=str
        )
        digest = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()
        path = self.cache_dir / f"{cache_namespace}_{digest}.json"
        cached = self._read_cache(path, public_source_url)
        if cached is not None:
            return cached

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url, params=params, timeout=self.timeout_seconds
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ExternalDataError("external API returned non-object JSON")
                retrieved_at = datetime.now(UTC)
                self._write_cache(path, public_source_url, payload, retrieved_at)
                return CachedJsonResponse(
                    payload=payload,
                    source_url=public_source_url,
                    retrieved_at=retrieved_at,
                    from_cache=False,
                )
            except (requests.RequestException, ValueError, ExternalDataError) as exc:
                last_error = exc
                retryable = True
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    status = exc.response.status_code
                    retryable = status in {408, 425, 429} or status >= 500
                if attempt >= self.max_retries or not retryable:
                    break
                delay = min(2**attempt, 8)
                LOGGER.warning(
                    "External JSON request failed (%s); retrying in %ss",
                    type(exc).__name__,
                    delay,
                )
                time.sleep(delay)
        if isinstance(last_error, requests.RequestException):
            status = (
                last_error.response.status_code
                if last_error.response is not None
                else None
            )
            safe_detail = f"HTTP {status}" if status is not None else type(last_error).__name__
        else:
            safe_detail = f"{type(last_error).__name__}: {last_error}"
        raise ExternalDataError(
            f"external JSON request failed for {public_source_url}: {safe_detail}"
        ) from last_error

    def _read_cache(
        self, path: Path, source_url: str
    ) -> CachedJsonResponse | None:
        if not path.exists():
            return None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            retrieved_at = datetime.fromisoformat(wrapper["retrieved_at"])
            if retrieved_at.tzinfo is None:
                retrieved_at = retrieved_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - retrieved_at > self.cache_ttl:
                return None
            if wrapper.get("source_url") != source_url:
                return None
            payload = wrapper["payload"]
            if not isinstance(payload, dict):
                return None
            return CachedJsonResponse(payload, source_url, retrieved_at, True)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            LOGGER.warning("Ignoring unreadable external JSON cache %s", path)
            return None

    @staticmethod
    def _write_cache(
        path: Path,
        source_url: str,
        payload: dict[str, Any],
        retrieved_at: datetime,
    ) -> None:
        wrapper = {
            "source_url": source_url,
            "retrieved_at": retrieved_at.isoformat(),
            "payload": payload,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(wrapper, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)


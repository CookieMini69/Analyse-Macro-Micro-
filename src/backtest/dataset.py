"""Secure acquisition and audit of licensed point-in-time history.

The module deliberately separates obtaining raw provider files from generating
signals. A downloaded table is not treated as a validated backtest input until
its archive header and SHA-256 manifest have been checked.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

import requests

from src.config import HistoricalDataSettings, load_settings

PROVIDER = "Sharadar Direct"
PROVIDER_URL = "https://sharadar.com/bundle"
DOCUMENTATION_URL = "https://sharadar.com/docs"

TABLE_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "tickers": {
        "table", "permaticker", "ticker", "isdelisted", "firstpricedate",
        "lastpricedate",
    },
    "sp500": {"date", "action", "ticker"},
    "stocks": {"ticker", "date", "closeadj", "closeunadj", "volume"},
    "fundamentals": {
        "ticker", "dimension", "calendardate", "date", "reportperiod",
        "revenue", "netinc", "assets", "liabilities", "ncfo", "capex",
    },
    "daily": {"ticker", "date", "marketcap", "ev", "pe", "pb", "ps"},
    "actions": {"date", "action", "ticker", "contraticker"},
    "events": {"ticker", "date", "eventcodes"},
}


class HistoricalDataAccessError(RuntimeError):
    """Raised without ever including a secret or signed redirect URL."""


@dataclass(slots=True)
class TableAudit:
    table: str
    available: bool
    provider_modified_at: str | None = None
    provider_size: int | None = None
    local_path: str | None = None
    sha256: str | None = None
    schema_valid: bool | None = None
    missing_columns: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class HistoricalAccessAudit:
    provider: str
    audited_at: str
    study_period: str
    universe: str
    api_key_env: str
    api_key_configured: bool
    remote_access_valid: bool
    local_dataset_valid: bool | None
    core_backtest_ready: bool
    full_spec_ready: bool
    tables: list[TableAudit]
    blockers: list[str]
    additional_access: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SharadarBulkClient:
    """Minimal authenticated client for documented Sharadar bulk endpoints."""

    def __init__(
        self,
        settings: HistoricalDataSettings,
        *,
        api_key: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.api_key = (api_key if api_key is not None else os.getenv(settings.api_key_env, "")).strip()
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": "AI-Stock-Opportunity-Scanner/1.0", "Accept": "application/json"}
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def audit_access(self) -> HistoricalAccessAudit:
        blockers: list[str] = []
        table_audits: list[TableAudit] = []
        if not self.configured:
            blockers.append(
                f"missing {self.settings.api_key_env}; a Sharadar subscription/API key is required"
            )
            table_audits = [
                TableAudit(table=table, available=False, error="API key not configured")
                for table in self.settings.required_tables
            ]
        else:
            for table in self.settings.required_tables:
                table_audits.append(self._audit_table_access(table))
            unavailable = [item.table for item in table_audits if not item.available]
            if unavailable:
                blockers.append(
                    "subscription does not expose required tables: " + ", ".join(unavailable)
                )
        remote_valid = bool(table_audits) and all(item.available for item in table_audits)
        if remote_valid:
            blockers.append(
                "raw tables are accessible but have not yet been downloaded, hashed, "
                "normalized, and used to rebuild dated signals"
            )
        return HistoricalAccessAudit(
            provider=PROVIDER,
            audited_at=datetime.now(UTC).isoformat(),
            study_period=f"{self.settings.start_year}-01-01/{self.settings.end_year}-12-31",
            universe=self.settings.universe,
            api_key_env=self.settings.api_key_env,
            api_key_configured=self.configured,
            remote_access_valid=remote_valid,
            local_dataset_valid=None,
            core_backtest_ready=False,
            full_spec_ready=False,
            tables=table_audits,
            blockers=blockers,
            additional_access=_additional_access(),
        )

    def _audit_table_access(self, table: str) -> TableAudit:
        try:
            response = self.session.get(
                f"{self.settings.base_url.rstrip('/')}/{table}",
                params={"api_key": self.api_key, "status": "True", "years": "full"},
                timeout=self.settings.timeout_seconds,
            )
        except requests.RequestException as exc:
            return TableAudit(
                table=table,
                available=False,
                error=f"network error ({type(exc).__name__}); no secret was logged",
            )
        if response.status_code != 200:
            return TableAudit(
                table=table,
                available=False,
                error=f"provider returned HTTP {response.status_code}",
            )
        try:
            payload = response.json()
        except ValueError:
            return TableAudit(table=table, available=False, error="provider returned invalid JSON")
        record = _full_history_record(payload)
        return TableAudit(
            table=table,
            available=bool(record and record.get("available", True)),
            provider_modified_at=str(record.get("modified")) if record and record.get("modified") else None,
            provider_size=_integer_or_none(record.get("size")) if record else None,
            error=None if record else "full-history bulk file is not available",
        )

    def download_table(self, table: str, destination: str | Path) -> tuple[Path, Path]:
        if table not in TABLE_REQUIRED_COLUMNS:
            raise ValueError(f"unsupported Sharadar table: {table}")
        if not self.configured:
            raise HistoricalDataAccessError(f"missing {self.settings.api_key_env}")
        root = Path(destination).resolve()
        root.mkdir(parents=True, exist_ok=True)
        archive_path = root / f"{table}.csv.zip"
        temporary_path = root / f".{table}.csv.zip.part"
        try:
            response = self.session.get(
                f"{self.settings.base_url.rstrip('/')}/{table}",
                params={"api_key": self.api_key, "years": "full"},
                timeout=self.settings.timeout_seconds,
                stream=True,
                allow_redirects=True,
            )
            if response.status_code != 200:
                raise HistoricalDataAccessError(
                    f"Sharadar returned HTTP {response.status_code} for table {table}"
                )
            with temporary_path.open("wb") as handle:
                _copy_response(response, handle)
            temporary_path.replace(archive_path)
            columns = _zip_csv_columns(archive_path)
            missing = sorted(TABLE_REQUIRED_COLUMNS[table] - columns)
            if missing:
                raise HistoricalDataAccessError(
                    f"table {table} is missing required columns: {', '.join(missing)}"
                )
            digest = _sha256(archive_path)
            manifest = {
                "provider": PROVIDER,
                "provider_public_url": PROVIDER_URL,
                "documentation_url": f"https://sharadar.com/docs/{table}",
                "table": table,
                "history": "full",
                "retrieved_at": datetime.now(UTC).isoformat(),
                "file": archive_path.name,
                "bytes": archive_path.stat().st_size,
                "sha256": digest,
                "required_columns": sorted(TABLE_REQUIRED_COLUMNS[table]),
                "api_key_stored": False,
            }
            manifest_path = root / f"{table}.manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
            return archive_path, manifest_path
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            raise


def audit_local_dataset(
    settings: HistoricalDataSettings, directory: str | Path
) -> HistoricalAccessAudit:
    root = Path(directory).resolve()
    blockers: list[str] = []
    table_audits: list[TableAudit] = []
    for table in settings.required_tables:
        archive = root / f"{table}.csv.zip"
        manifest_path = root / f"{table}.manifest.json"
        audit = TableAudit(table=table, available=False, local_path=str(archive))
        try:
            if not archive.is_file() or not manifest_path.is_file():
                raise HistoricalDataAccessError("archive or manifest missing")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            digest = _sha256(archive)
            if manifest.get("sha256") != digest:
                raise HistoricalDataAccessError("SHA-256 differs from manifest")
            columns = _zip_csv_columns(archive)
            missing = sorted(TABLE_REQUIRED_COLUMNS[table] - columns)
            audit.sha256 = digest
            audit.schema_valid = not missing
            audit.missing_columns = missing
            audit.available = not missing
            if missing:
                audit.error = "required columns missing"
        except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile,
                HistoricalDataAccessError) as exc:
            audit.error = str(exc)
            audit.schema_valid = False
        table_audits.append(audit)
    invalid = [item.table for item in table_audits if not item.available]
    if invalid:
        blockers.append("local archives are missing or invalid: " + ", ".join(invalid))
    local_valid = bool(table_audits) and not invalid
    if local_valid:
        blockers.append(
            "provider archives pass integrity/schema checks; dated signal reconstruction "
            "and strict Phase 9 execution are still required"
        )
    return HistoricalAccessAudit(
        provider=PROVIDER,
        audited_at=datetime.now(UTC).isoformat(),
        study_period=f"{settings.start_year}-01-01/{settings.end_year}-12-31",
        universe=settings.universe,
        api_key_env=settings.api_key_env,
        api_key_configured=bool(os.getenv(settings.api_key_env, "").strip()),
        remote_access_valid=False,
        local_dataset_valid=local_valid,
        core_backtest_ready=False,
        full_spec_ready=False,
        tables=table_audits,
        blockers=blockers,
        additional_access=_additional_access(),
    )


def persist_audit(audit: HistoricalAccessAudit, path: str | Path) -> Path:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(audit.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    return destination


def _additional_access() -> dict[str, str]:
    return {
        "international_ifrs": (
            "not configured; SEC covers US-listed foreign filers only. For broad global "
            "coverage, license LSEG Worldscope/Financials Point-in-Time or equivalent"
        ),
        "consensus_guidance": (
            "not configured; license LSEG I/B/E/S Point-in-Time plus Guidance history"
        ),
        "historical_causal_news": (
            "not configured; a licensed timestamped news/event archive is required for "
            "causal shock features"
        ),
        "critical_ai_analyst": (
            "configured design: OpenAI Responses API, model gpt-5.6-terra; "
            "OPENAI_API_KEY is required before activation"
        ),
    }


def _full_history_record(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    files = payload.get("files")
    if isinstance(files, list):
        for record in files:
            if isinstance(record, dict) and str(record.get("history", "")).lower() == "full":
                return record
        return None
    if payload.get("name"):
        return payload
    return None


def _integer_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _copy_response(response: requests.Response, handle: BinaryIO) -> None:
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if chunk:
            handle.write(chunk)


def _zip_csv_columns(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        members = [
            info for info in archive.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".csv")
        ]
        if len(members) != 1:
            raise HistoricalDataAccessError("bulk archive must contain exactly one CSV")
        member = members[0]
        member_path = Path(member.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise HistoricalDataAccessError("unsafe member path in bulk archive")
        with archive.open(member) as raw:
            header = raw.readline().decode("utf-8-sig").strip()
    if not header:
        raise HistoricalDataAccessError("bulk CSV has no header")
    return {value.strip().lower() for value in next(csv.reader([header]))}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acquire or audit Sharadar point-in-time history"
    )
    parser.add_argument("command", choices=("access", "download", "audit-local"))
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--directory", default="data/raw/historical/sharadar")
    parser.add_argument("--report", default="reports/historical_access_audit.json")
    parser.add_argument("--tables", nargs="*")
    args = parser.parse_args()
    settings = load_settings(args.config).historical_data
    client = SharadarBulkClient(settings)
    if args.command == "access":
        audit = client.audit_access()
    elif args.command == "audit-local":
        audit = audit_local_dataset(settings, args.directory)
    else:
        tables = args.tables or settings.required_tables
        unsupported = sorted(set(tables) - set(settings.required_tables))
        if unsupported:
            parser.error("tables are not configured: " + ", ".join(unsupported))
        access = client.audit_access()
        if not access.remote_access_valid:
            persist_audit(access, args.report)
            print(Path(args.report).resolve())
            return 2
        for table in tables:
            client.download_table(table, args.directory)
        audit = audit_local_dataset(settings, args.directory)
    report = persist_audit(audit, args.report)
    print(report)
    return 0 if audit.core_backtest_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "HistoricalAccessAudit", "HistoricalDataAccessError", "SharadarBulkClient",
    "TABLE_REQUIRED_COLUMNS", "TableAudit", "audit_local_dataset", "persist_audit",
]

import io
import json
import zipfile

from src.backtest.dataset import (
    SharadarBulkClient,
    TABLE_REQUIRED_COLUMNS,
    audit_local_dataset,
)
from src.config import HistoricalDataSettings


class FakeResponse:
    def __init__(self, *, status_code=200, payload=None, body=b"") -> None:
        self.status_code = status_code
        self._payload = payload
        self._body = body

    def json(self):
        return self._payload

    def iter_content(self, chunk_size):
        del chunk_size
        yield self._body


class FakeSession:
    def __init__(self, response) -> None:
        self.response = response
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def _zip_bytes(table: str) -> bytes:
    buffer = io.BytesIO()
    columns = sorted(TABLE_REQUIRED_COLUMNS[table])
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{table}.csv", ",".join(columns) + "\n")
    return buffer.getvalue()


def test_access_audit_refuses_missing_key_without_network(monkeypatch) -> None:
    monkeypatch.delenv("SHARADAR_API_KEY", raising=False)
    session = FakeSession(FakeResponse())
    settings = HistoricalDataSettings(required_tables=["actions"])
    audit = SharadarBulkClient(settings, session=session).audit_access()
    assert audit.api_key_configured is False
    assert audit.remote_access_valid is False
    assert audit.core_backtest_ready is False
    assert "missing SHARADAR_API_KEY" in audit.blockers[0]
    assert session.calls == []


def test_access_audit_detects_full_history_entitlement() -> None:
    session = FakeSession(
        FakeResponse(
            payload={
                "table": "actions",
                "files": [
                    {"history": "full", "available": True, "size": 123,
                     "modified": "2026-08-01T00:00:00Z"}
                ],
            }
        )
    )
    settings = HistoricalDataSettings(required_tables=["actions"])
    audit = SharadarBulkClient(settings, api_key="secret", session=session).audit_access()
    assert audit.remote_access_valid is True
    assert audit.tables[0].provider_size == 123
    assert audit.core_backtest_ready is False
    assert session.calls[0][1]["params"]["years"] == "full"


def test_bulk_download_writes_hashed_secret_free_manifest(tmp_path) -> None:
    secret = "do-not-persist-this"
    session = FakeSession(FakeResponse(body=_zip_bytes("actions")))
    settings = HistoricalDataSettings(required_tables=["actions"])
    archive, manifest_path = SharadarBulkClient(
        settings, api_key=secret, session=session
    ).download_table("actions", tmp_path)
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert archive.exists()
    assert secret not in manifest_text
    assert manifest["api_key_stored"] is False
    assert len(manifest["sha256"]) == 64

    audit = audit_local_dataset(settings, tmp_path)
    assert audit.local_dataset_valid is True
    assert audit.tables[0].schema_valid is True
    assert audit.core_backtest_ready is False


def test_local_audit_detects_tampered_provider_archive(tmp_path) -> None:
    session = FakeSession(FakeResponse(body=_zip_bytes("actions")))
    settings = HistoricalDataSettings(required_tables=["actions"])
    archive, _ = SharadarBulkClient(
        settings, api_key="secret", session=session
    ).download_table("actions", tmp_path)
    with archive.open("ab") as handle:
        handle.write(b"tampered")
    audit = audit_local_dataset(settings, tmp_path)
    assert audit.local_dataset_valid is False
    assert "SHA-256" in audit.tables[0].error


def test_provider_errors_do_not_echo_api_key() -> None:
    secret = "never-log-me"
    session = FakeSession(FakeResponse(status_code=403))
    settings = HistoricalDataSettings(required_tables=["actions"])
    audit = SharadarBulkClient(settings, api_key=secret, session=session).audit_access()
    serialized = json.dumps(audit.to_dict())
    assert secret not in serialized
    assert audit.tables[0].error == "provider returned HTTP 403"

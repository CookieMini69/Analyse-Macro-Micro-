"""Free official European universe-history acquisition through ESMA FIRDS.

Quarter-end FULINS_E files provide the active equity/ETF reference universe as
it was published at that date. They solve the survivorship-free *instrument
universe* layer, but deliberately do not claim index membership, ticker mapping,
prices, fundamentals, or reconstructed strategy signals.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import zipfile
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from lxml import etree

REGISTER_URL = (
    "https://registers.esma.europa.eu/publication/searchRegister/"
    "doRawSearch/esma_registers_firds_files/select"
)
PUBLIC_REGISTER_URL = (
    "https://registers.esma.europa.eu/publication/searchRegister?"
    "core=esma_registers_firds_files"
)
FILE_PATTERN = re.compile(r"^FULINS_E_(\d{8})_(\d{2})of(\d{2})\.zip$")


class FirdsHistoryError(RuntimeError):
    """A public-catalog or archive-integrity failure."""


def fetch_equity_catalog(
    start_year: int = 2018,
    end_year: int = 2025,
    *,
    session: requests.Session | None = None,
    timeout: int = 60,
) -> list[dict]:
    """Fetch every weekly equity full-file record from the ESMA register."""

    client = session or requests.Session()
    query = (
        "file_type:FULINS AND file_name:FULINS_E_* AND "
        f"publication_date:[{start_year}-01-01T00:00:00Z TO "
        f"{end_year}-12-31T23:59:59Z]"
    )
    response = client.get(
        REGISTER_URL,
        params={
            "q": query, "wt": "json", "rows": 20000, "start": 0,
            "sort": "publication_date asc",
            "fl": "file_name,file_type,publication_date,download_link",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    docs = payload.get("response", {}).get("docs", [])
    found = int(payload.get("response", {}).get("numFound", 0))
    if found > len(docs):
        raise FirdsHistoryError(f"catalog truncated: received {len(docs)} of {found}")
    records: list[dict] = []
    for row in docs:
        file_name = str(row.get("file_name") or "")
        link = str(row.get("download_link") or "")
        match = FILE_PATTERN.fullmatch(file_name)
        parsed = urlparse(link)
        if (
            not match or parsed.scheme != "https"
            or parsed.hostname != "firds.esma.europa.eu"
            or Path(parsed.path).name != file_name
        ):
            continue
        publication = datetime.fromisoformat(
            str(row["publication_date"]).replace("Z", "+00:00")
        ).date()
        records.append({
            "file_name": file_name,
            "file_type": "FULINS",
            "cfi_first_letter": "E",
            "publication_date": publication.isoformat(),
            "part": int(match.group(2)),
            "part_count": int(match.group(3)),
            "download_url": link,
        })
    if not records:
        raise FirdsHistoryError("ESMA returned no valid FULINS_E record")
    return records


def select_quarterly_snapshots(
    records: list[dict], start_year: int = 2018, end_year: int = 2025
) -> list[dict]:
    """Select all parts of the latest published full universe in each quarter."""

    grouped: dict[tuple[int, int], dict[date, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for record in records:
        observed = date.fromisoformat(record["publication_date"])
        if start_year <= observed.year <= end_year:
            grouped[(observed.year, (observed.month - 1) // 3 + 1)][observed].append(record)
    snapshots: list[dict] = []
    for year in range(start_year, end_year + 1):
        for quarter in range(1, 5):
            dates = grouped.get((year, quarter), {})
            if not dates:
                continue
            selected_date = max(dates)
            parts = sorted(dates[selected_date], key=lambda item: item["part"])
            expected = parts[0]["part_count"] if parts else 0
            complete = len(parts) == expected and [item["part"] for item in parts] == list(
                range(1, expected + 1)
            )
            snapshots.append({
                "snapshot_id": f"ESMA-FIRDS-E-{year}Q{quarter}",
                "year": year,
                "quarter": quarter,
                "publication_date": selected_date.isoformat(),
                "complete_parts": complete,
                "files": parts,
            })
    return snapshots


def build_access_audit(
    snapshots: list[dict], start_year: int = 2018, end_year: int = 2025
) -> dict:
    expected = (end_year - start_year + 1) * 4
    complete = sum(bool(item["complete_parts"]) for item in snapshots)
    return {
        "provider": "ESMA FIRDS",
        "provider_register_url": PUBLIC_REGISTER_URL,
        "methodology": "quarter-end-active-equity-reference-universe-v1",
        "study_period": f"{start_year}-01-01/{end_year}-12-31",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "expected_quarters": expected,
        "available_quarters": len(snapshots),
        "complete_quarters": complete,
        "instrument_universe_layer_ready": complete == expected,
        "strict_strategy_backtest_ready": False,
        "snapshots": snapshots,
        "resolved": [
            "survivorship-free active European instrument snapshots by ISIN/MIC",
            "dated official publication metadata and immutable download URLs",
        ],
        "remaining_blockers": [
            "FIRDS reference universes are not historical index compositions",
            "stable ISIN/MIC to vendor ticker mapping, including delisted instruments",
            "corporate-action-adjusted prices for disappeared instruments",
            "IFRS point-in-time fundamentals before and after ESEF adoption",
            "historical strategy signals reconstructed from data available at each cutoff",
        ],
    }


def persist_catalog(audit: dict, path: str | Path) -> Path:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    return destination


def download_snapshots(
    audit: dict,
    directory: str | Path,
    *,
    session: requests.Session | None = None,
    timeout: int = 120,
) -> Path:
    """Download selected archives and persist hashes; existing valid files are reused."""

    client = session or requests.Session()
    destination = Path(directory).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    files = [record for snapshot in audit["snapshots"] for record in snapshot["files"]]
    manifest_rows: list[dict] = []
    for record in files:
        archive = destination / record["file_name"]
        temporary = destination / f".{record['file_name']}.part"
        if not archive.is_file() or archive.stat().st_size == 0:
            response = client.get(record["download_url"], stream=True, timeout=timeout)
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            if not zip_signature_valid(temporary):
                temporary.unlink(missing_ok=True)
                raise FirdsHistoryError(f"invalid ZIP signature: {record['file_name']}")
            temporary.replace(archive)
        digest = sha256_file(archive)
        manifest_rows.append({
            **record, "local_path": archive.name, "bytes": archive.stat().st_size,
            "sha256": digest,
        })
    manifest = destination / "download_manifest.json"
    manifest.write_text(json.dumps({
        "provider": "ESMA FIRDS", "retrieved_at": datetime.now(UTC).isoformat(),
        "file_count": len(manifest_rows), "files": manifest_rows,
    }, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def build_instrument_snapshots(
    audit: dict, archive_directory: str | Path, output_directory: str | Path
) -> Path:
    """Normalize the downloaded full files into dated gzip CSV snapshots."""

    archives = Path(archive_directory).resolve()
    destination = Path(output_directory).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    outputs: list[dict] = []
    paris = ZoneInfo("Europe/Paris")
    columns = [
        "snapshot_id", "publication_date", "available_at", "isin", "mic",
        "issuer_lei", "full_name", "short_name", "cfi", "currency",
        "first_trade_at", "termination_at", "source_files",
    ]
    for snapshot in audit["snapshots"]:
        if not snapshot["complete_parts"]:
            raise FirdsHistoryError(f"incomplete snapshot {snapshot['snapshot_id']}")
        publication = date.fromisoformat(snapshot["publication_date"])
        # ESMA documents the files as published by 09:00 CET/CEST. Using that
        # deadline is conservative when the exact HTTP appearance is unknown.
        available_at = datetime(
            publication.year, publication.month, publication.day, 9, 0,
            tzinfo=paris,
        ).astimezone(UTC).isoformat()
        records: dict[tuple[str, str], dict[str, str]] = {}
        source_files: list[str] = []
        for record in snapshot["files"]:
            archive = archives / record["file_name"]
            if not archive.is_file():
                raise FirdsHistoryError(f"missing archive {record['file_name']}")
            source_files.append(archive.name)
            for item in iter_firds_reference_data(archive):
                key = (item["isin"], item["mic"])
                item["source_files"] = archive.name
                records[key] = item
        output = destination / f"{snapshot['snapshot_id']}.csv.gz"
        with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for key in sorted(records):
                writer.writerow({
                    "snapshot_id": snapshot["snapshot_id"],
                    "publication_date": snapshot["publication_date"],
                    "available_at": available_at,
                    **records[key],
                })
        outputs.append({
            "snapshot_id": snapshot["snapshot_id"],
            "publication_date": snapshot["publication_date"],
            "available_at": available_at,
            "row_count": len(records),
            "file": output.name,
            "bytes": output.stat().st_size,
            "sha256": sha256_file(output),
            "source_files": source_files,
        })
    manifest = destination / "instrument_snapshot_manifest.json"
    manifest.write_text(json.dumps({
        "schema": "esma-firds-quarterly-instrument-snapshot-v1",
        "provider": "ESMA FIRDS",
        "generated_at": datetime.now(UTC).isoformat(),
        "snapshot_count": len(outputs),
        "snapshots": outputs,
        "strict_strategy_backtest_ready": False,
        "reason": (
            "official ISIN/MIC universe is ready; historical ticker mapping, "
            "adjusted prices, fundamentals and dated signals are still absent"
        ),
    }, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def iter_firds_reference_data(archive_path: Path):
    """Yield selected fields without loading a potentially large XML into RAM."""

    with zipfile.ZipFile(archive_path) as archive:
        members = [
            info for info in archive.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".xml")
        ]
        if len(members) != 1:
            raise FirdsHistoryError(f"{archive_path.name} must contain one XML file")
        member = members[0]
        member_path = Path(member.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise FirdsHistoryError(f"unsafe ZIP member in {archive_path.name}")
        with archive.open(member) as raw:
            for _, element in etree.iterparse(
                raw, events=("end",), tag="{*}RefData", huge_tree=True
            ):
                item = parse_refdata(element)
                if item is not None:
                    yield item
                element.clear()
                parent = element.getparent()
                if parent is not None:
                    while element.getprevious() is not None:
                        del parent[0]


def parse_refdata(element) -> dict[str, str] | None:
    general = direct_child(element, "FinInstrmGnlAttrbts")
    venue = direct_child(element, "TradgVnRltdAttrbts")
    if general is None or venue is None:
        return None
    isin = child_text(general, "Id")
    mic = child_text(venue, "Id")
    cfi = child_text(general, "ClssfctnTp")
    if not isin or not mic or not cfi.startswith("E"):
        return None
    return {
        "isin": isin,
        "mic": mic,
        "issuer_lei": child_text(element, "Issr"),
        "full_name": child_text(general, "FullNm"),
        "short_name": child_text(general, "ShrtNm"),
        "cfi": cfi,
        "currency": child_text(general, "NtnlCcy"),
        "first_trade_at": child_text(venue, "FrstTradDt"),
        "termination_at": child_text(venue, "TermntnDt"),
        "source_files": "",
    }


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def direct_child(element, name: str):
    return next((child for child in element if local_name(child.tag) == name), None)


def child_text(element, name: str) -> str:
    child = direct_child(element, name)
    return (child.text or "").strip() if child is not None else ""


def zip_signature_valid(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire free ESMA FIRDS universe history")
    parser.add_argument("command", choices=("catalog", "download", "build"))
    parser.add_argument("--start-year", type=int, default=2018)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--catalog", default="reports/free_history_access_audit.json")
    parser.add_argument("--directory", default="data/raw/historical/esma_firds")
    parser.add_argument(
        "--output-directory", default="data/processed/historical/esma_firds"
    )
    args = parser.parse_args()
    records = fetch_equity_catalog(args.start_year, args.end_year)
    snapshots = select_quarterly_snapshots(records, args.start_year, args.end_year)
    audit = build_access_audit(snapshots, args.start_year, args.end_year)
    catalog = persist_catalog(audit, args.catalog)
    print(catalog)
    if args.command in {"download", "build"}:
        print(download_snapshots(audit, args.directory))
    if args.command == "build":
        print(build_instrument_snapshots(audit, args.directory, args.output_directory))
    return 0 if audit["instrument_universe_layer_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "FirdsHistoryError", "build_access_audit", "build_instrument_snapshots",
    "download_snapshots", "fetch_equity_catalog", "iter_firds_reference_data",
    "parse_refdata", "persist_catalog", "select_quarterly_snapshots",
]

from lxml import etree

from src.backtest.free_history import (
    build_access_audit, parse_refdata, select_quarterly_snapshots,
)


def _row(day: str, part: int = 1, count: int = 1) -> dict:
    compact = day.replace("-", "")
    return {
        "file_name": f"FULINS_E_{compact}_{part:02d}of{count:02d}.zip",
        "file_type": "FULINS", "cfi_first_letter": "E", "publication_date": day,
        "part": part, "part_count": count,
        "download_url": f"https://firds.esma.europa.eu/firds/file-{day}-{part}.zip",
    }


def test_quarterly_snapshot_selects_latest_date_and_all_parts() -> None:
    rows = [_row("2018-01-06"), _row("2018-03-31", 1, 2), _row("2018-03-31", 2, 2)]
    snapshots = select_quarterly_snapshots(rows, 2018, 2018)
    assert snapshots[0]["publication_date"] == "2018-03-31"
    assert snapshots[0]["complete_parts"] is True
    audit = build_access_audit(snapshots, 2018, 2018)
    assert audit["instrument_universe_layer_ready"] is False
    assert audit["strict_strategy_backtest_ready"] is False


def test_parse_refdata_ignores_namespaces_and_preserves_identifiers() -> None:
    element = etree.fromstring("""
    <RefData xmlns="urn:test">
      <FinInstrmGnlAttrbts><Id>FR0000000001</Id><FullNm>Example SA</FullNm>
      <ShrtNm>EXAMPLE/ORD</ShrtNm><ClssfctnTp>ESVUFR</ClssfctnTp><NtnlCcy>EUR</NtnlCcy></FinInstrmGnlAttrbts>
      <Issr>LEI123</Issr><TradgVnRltdAttrbts><Id>XPAR</Id><FrstTradDt>2010-01-01T00:00:00</FrstTradDt></TradgVnRltdAttrbts>
    </RefData>
    """)
    assert parse_refdata(element) == {
        "isin": "FR0000000001", "mic": "XPAR", "issuer_lei": "LEI123",
        "full_name": "Example SA", "short_name": "EXAMPLE/ORD", "cfi": "ESVUFR",
        "currency": "EUR", "first_trade_at": "2010-01-01T00:00:00",
        "termination_at": "", "source_files": "",
    }

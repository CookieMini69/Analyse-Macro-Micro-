from datetime import UTC, datetime

from src.data.fundamentals import extract_annual_observations, normalize_as_of
from src.data.sec_edgar import FilingMetadata
from src.models import AvailabilityPrecision


def filing(accession: str, accepted: str | None, filed: str) -> FilingMetadata:
    return FilingMetadata(
        accession=accession,
        form="10-K",
        filed_date=filed,
        report_date="2022-12-31",
        acceptance_datetime=accepted,
        primary_document="annual.htm",
    )


def revenue_fact(value: float, accession: str, filed: str, form: str = "10-K"):
    return {
        "start": "2022-01-01",
        "end": "2022-12-31",
        "val": value,
        "accn": accession,
        "fy": 2022,
        "fp": "FY",
        "form": form,
        "filed": filed,
    }


def companyfacts(entries):
    return {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": entries}
                }
            }
        }
    }


def test_cutoff_excludes_future_amendment_and_later_includes_it() -> None:
    original = "0000000000-23-000001"
    amended = "0000000000-23-000002"
    payload = companyfacts(
        [
            revenue_fact(100.0, original, "2023-02-01"),
            revenue_fact(110.0, amended, "2023-03-01"),
        ]
    )
    index = {
        original: filing(original, "2023-02-01T20:00:00Z", "2023-02-01"),
        amended: filing(amended, "2023-03-01T20:00:00Z", "2023-03-01"),
    }
    before_amendment = extract_annual_observations(
        payload,
        cik="0000000001",
        filing_index=index,
        as_of=datetime(2023, 2, 15, tzinfo=UTC),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        history_years=5,
    )
    after_amendment = extract_annual_observations(
        payload,
        cik="0000000001",
        filing_index=index,
        as_of=datetime(2023, 4, 1, tzinfo=UTC),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        history_years=5,
    )
    assert before_amendment["revenue"][0].value == 100.0
    assert after_amendment["revenue"][0].value == 110.0
    assert after_amendment["revenue"][0].accession == amended


def test_intraday_cutoff_uses_exact_acceptance_time() -> None:
    accession = "0000000000-23-000001"
    payload = companyfacts([revenue_fact(100.0, accession, "2023-02-01")])
    index = {
        accession: filing(accession, "2023-02-01T20:00:00Z", "2023-02-01")
    }
    before = extract_annual_observations(
        payload,
        cik="0000000001",
        filing_index=index,
        as_of=datetime(2023, 2, 1, 19, 59, tzinfo=UTC),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        history_years=5,
    )
    after = extract_annual_observations(
        payload,
        cik="0000000001",
        filing_index=index,
        as_of=datetime(2023, 2, 1, 20, 1, tzinfo=UTC),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        history_years=5,
    )
    assert "revenue" not in before
    assert after["revenue"][0].availability_precision == AvailabilityPrecision.ACCEPTANCE_TIMESTAMP


def test_missing_acceptance_uses_conservative_end_of_filed_date() -> None:
    accession = "0000000000-23-000001"
    payload = companyfacts([revenue_fact(100.0, accession, "2023-02-01")])
    index = {accession: filing(accession, None, "2023-02-01")}
    midday = extract_annual_observations(
        payload,
        cik="0000000001",
        filing_index=index,
        as_of=datetime(2023, 2, 1, 12, 0, tzinfo=UTC),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        history_years=5,
    )
    next_day = extract_annual_observations(
        payload,
        cik="0000000001",
        filing_index=index,
        as_of=datetime(2023, 2, 2, tzinfo=UTC),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        history_years=5,
    )
    assert "revenue" not in midday
    assert next_day["revenue"][0].availability_precision == AvailabilityPrecision.FILED_DATE


def test_quarterly_fact_is_not_misclassified_as_annual() -> None:
    accession = "0000000000-23-000001"
    payload = companyfacts([revenue_fact(25.0, accession, "2023-02-01", form="10-Q")])
    selected = extract_annual_observations(
        payload,
        cik="0000000001",
        filing_index={},
        as_of=datetime(2023, 3, 1, tzinfo=UTC),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        history_years=5,
    )
    assert selected == {}


def test_foreign_private_issuer_20f_is_accepted_as_annual() -> None:
    accession = "0000000000-23-000020"
    payload = companyfacts([revenue_fact(125.0, accession, "2023-03-10", form="20-F")])
    selected = extract_annual_observations(
        payload,
        cik="0000000001",
        filing_index={accession: filing(accession, "2023-03-10T18:00:00Z", "2023-03-10")},
        as_of=datetime(2023, 3, 11, tzinfo=UTC),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        history_years=5,
    )
    assert selected["revenue"][0].form == "20-F"
    assert selected["revenue"][0].value == 125.0


def test_ifrs_local_currency_fact_is_normalized_without_conversion() -> None:
    accession = "0000000000-23-000021"
    fact = revenue_fact(900.0, accession, "2023-03-10", form="20-F")
    payload = {
        "facts": {
            "ifrs-full": {"Revenue": {"units": {"DKK": [fact]}}}
        }
    }
    selected = extract_annual_observations(
        payload,
        cik="0000000001",
        filing_index={accession: filing(accession, "2023-03-10T18:00:00Z", "2023-03-10")},
        as_of=datetime(2023, 3, 11, tzinfo=UTC),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        history_years=5,
    )
    observation = selected["revenue"][0]
    assert observation.taxonomy == "ifrs-full"
    assert observation.currency == "DKK"
    assert observation.value == 900.0


def test_security_currency_is_preferred_when_sec_exposes_multiple_units() -> None:
    accession = "0000000000-23-000022"
    fact = revenue_fact(900.0, accession, "2023-03-10", form="20-F")
    payload = {
        "facts": {
            "ifrs-full": {
                "Revenue": {
                    "units": {
                        "USD": [{**fact, "val": 130.0}],
                        "DKK": [fact],
                    }
                }
            }
        }
    }
    selected = extract_annual_observations(
        payload,
        cik="0000000001",
        filing_index={
            accession: filing(
                accession, "2023-03-10T18:00:00Z", "2023-03-10"
            )
        },
        as_of=datetime(2023, 3, 11, tzinfo=UTC),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        history_years=5,
        preferred_currency="DKK",
    )
    assert selected["revenue"][0].currency == "DKK"
    assert selected["revenue"][0].value == 900.0


def test_date_only_cutoff_means_end_of_day() -> None:
    cutoff = normalize_as_of("2023-02-01")
    assert cutoff.hour == 23
    assert cutoff.minute == 59
    assert cutoff.tzinfo == UTC

"""Point-in-time extraction and normalization of annual SEC company facts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, Literal

from src.data.sec_edgar import FilingMetadata, SecEdgarClient, normalize_cik
from src.models import (
    AvailabilityPrecision,
    DataQuality,
    DataStatus,
    FundamentalObservation,
    Security,
)

FactKind = Literal["duration", "instant"]


@dataclass(frozen=True, slots=True)
class ConceptSpec:
    name: str
    kind: FactKind
    concepts: tuple[tuple[str, str], ...]
    preferred_units: tuple[str, ...]


CONCEPT_SPECS: tuple[ConceptSpec, ...] = (
    ConceptSpec(
        "revenue",
        "duration",
        (
            ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
            ("us-gaap", "SalesRevenueNet"),
            ("us-gaap", "Revenues"),
            ("ifrs-full", "Revenue"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "gross_profit",
        "duration",
        (("us-gaap", "GrossProfit"), ("ifrs-full", "GrossProfit")),
        ("USD",),
    ),
    ConceptSpec(
        "operating_income",
        "duration",
        (
            ("us-gaap", "OperatingIncomeLoss"),
            ("ifrs-full", "ProfitLossFromOperatingActivities"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "net_income",
        "duration",
        (
            ("us-gaap", "NetIncomeLoss"),
            ("us-gaap", "ProfitLoss"),
            ("ifrs-full", "ProfitLoss"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "eps_diluted",
        "duration",
        (
            ("us-gaap", "EarningsPerShareDiluted"),
            ("ifrs-full", "DilutedEarningsLossPerShare"),
        ),
        ("USD/shares",),
    ),
    ConceptSpec(
        "operating_cash_flow",
        "duration",
        (
            ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
            ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "capex",
        "duration",
        (
            ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
            ("us-gaap", "PaymentsForAdditionsToPropertyPlantAndEquipment"),
            ("ifrs-full", "PurchaseOfPropertyPlantAndEquipment"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "depreciation_amortization",
        "duration",
        (
            ("us-gaap", "DepreciationDepletionAndAmortization"),
            ("us-gaap", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment"),
            ("us-gaap", "Depreciation"),
            ("ifrs-full", "DepreciationAndAmortisationExpense"),
            ("ifrs-full", "DepreciationExpense"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "interest_expense",
        "duration",
        (
            ("us-gaap", "InterestExpenseNonOperating"),
            ("us-gaap", "InterestAndDebtExpense"),
            ("ifrs-full", "FinanceCosts"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "pretax_income",
        "duration",
        (
            (
                "us-gaap",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            ),
            (
                "us-gaap",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            ),
            ("ifrs-full", "ProfitLossBeforeTax"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "income_tax_expense",
        "duration",
        (
            ("us-gaap", "IncomeTaxExpenseBenefit"),
            ("ifrs-full", "IncomeTaxExpenseContinuingOperations"),
            ("ifrs-full", "IncomeTaxExpense"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "diluted_shares",
        "duration",
        (
            ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding"),
            ("ifrs-full", "DilutedWeightedAverageShares"),
            ("ifrs-full", "AdjustedWeightedAverageShares"),
        ),
        ("shares",),
    ),
    ConceptSpec(
        "dividends_paid",
        "duration",
        (
            ("us-gaap", "PaymentsOfDividends"),
            ("us-gaap", "PaymentsOfDividendsCommonStock"),
            ("ifrs-full", "DividendsPaid"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "cash",
        "instant",
        (
            ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
            (
                "us-gaap",
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            ),
            ("ifrs-full", "CashAndCashEquivalents"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "equity",
        "instant",
        (
            ("us-gaap", "StockholdersEquity"),
            (
                "us-gaap",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            ),
            ("ifrs-full", "Equity"),
            ("ifrs-full", "EquityAttributableToOwnersOfParent"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "current_assets",
        "instant",
        (("us-gaap", "AssetsCurrent"), ("ifrs-full", "CurrentAssets")),
        ("USD",),
    ),
    ConceptSpec(
        "current_liabilities",
        "instant",
        (
            ("us-gaap", "LiabilitiesCurrent"),
            ("ifrs-full", "CurrentLiabilities"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "long_term_debt_total",
        "instant",
        (
            ("us-gaap", "LongTermDebtAndFinanceLeaseObligations"),
            ("us-gaap", "LongTermDebt"),
            ("ifrs-full", "Borrowings"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "current_debt",
        "instant",
        (
            ("us-gaap", "LongTermDebtAndFinanceLeaseObligationsCurrent"),
            ("us-gaap", "LongTermDebtCurrent"),
            ("ifrs-full", "CurrentBorrowings"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "noncurrent_debt",
        "instant",
        (
            ("us-gaap", "LongTermDebtAndFinanceLeaseObligationsNoncurrent"),
            ("us-gaap", "LongTermDebtNoncurrent"),
            ("ifrs-full", "NoncurrentBorrowings"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "short_term_borrowings",
        "instant",
        (
            ("us-gaap", "ShortTermBorrowings"),
            ("ifrs-full", "ShorttermBorrowings"),
        ),
        ("USD",),
    ),
    ConceptSpec(
        "shares_outstanding",
        "instant",
        (("dei", "EntityCommonStockSharesOutstanding"),),
        ("shares",),
    ),
)

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
US_COUNTRIES = {"united states", "usa", "us", "u.s.", "u.s.a."}


@dataclass(slots=True)
class FundamentalDataResult:
    security: Security
    cik: str | None
    company: str | None
    as_of: datetime
    status: DataStatus
    data_quality: DataQuality
    observations: dict[str, list[FundamentalObservation]]
    retrieved_at: datetime
    sources: list[dict[str, Any]]
    error: str | None = None


def normalize_as_of(value: date | datetime | str | None) -> datetime:
    """Normalize a cutoff; a date means end-of-day UTC, never start-of-day."""

    if value is None:
        return datetime.now(UTC)
    if isinstance(value, str):
        normalized = value.strip()
        if "T" not in normalized and " " not in normalized:
            value = date.fromisoformat(normalized)
        else:
            value = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return datetime.combine(value, time.max, tzinfo=UTC)


def is_sec_eligible(security: Security) -> bool:
    if security.cik:
        return True
    if security.country is None:
        return True
    return security.country.casefold() in US_COUNTRIES


class SecEdgarFundamentalSource:
    """Retrieve annual SEC-reporting facts available at a chosen cutoff.

    This includes domestic 10-K filers and foreign private issuers filing 20-F
    or 40-F. The current concept map remains deliberately limited to standard
    taxonomies and preferred USD units; unsupported IFRS/local-currency facts
    are returned as unavailable instead of being silently converted.
    """

    def __init__(self, client: SecEdgarClient, *, history_years: int = 5) -> None:
        self.client = client
        self.history_years = history_years

    def fetch(
        self, security: Security, *, as_of: date | datetime | str | None = None
    ) -> FundamentalDataResult:
        cutoff = normalize_as_of(as_of)
        if not is_sec_eligible(security):
            return unavailable_fundamental_data(
                security,
                cutoff,
                DataStatus.NOT_APPLICABLE,
                "SEC EDGAR provider requires a US reporting issuer or explicit CIK",
            )

        resolved_name = security.company
        cik = normalize_cik(security.cik) if security.cik else None
        if cik is None:
            resolved = self.client.resolve_cik(security.ticker)
            if resolved is None:
                return unavailable_fundamental_data(
                    security,
                    cutoff,
                    DataStatus.DATA_UNAVAILABLE,
                    "ticker_not_found_in_sec_company_tickers; configure an explicit CIK",
                )
            cik, sec_name = resolved
            resolved_name = resolved_name or sec_name

        try:
            companyfacts = self.client.fetch_companyfacts(cik)
            required_accessions = _relevant_accessions(
                companyfacts.payload, cutoff, self.history_years
            )
            submissions = self.client.fetch_submissions(cik)
            filing_index = self.client.build_filing_index(
                submissions, required_accessions=required_accessions
            )
            observations = extract_annual_observations(
                companyfacts.payload,
                cik=cik,
                filing_index=filing_index,
                as_of=cutoff,
                retrieved_at=companyfacts.retrieved_at,
                history_years=self.history_years,
            )
        except Exception as exc:
            return unavailable_fundamental_data(
                security,
                cutoff,
                DataStatus.DATA_UNAVAILABLE,
                f"{type(exc).__name__}: {exc}",
                cik=cik,
                company=resolved_name,
            )

        count = sum(len(items) for items in observations.values())
        status = DataStatus.AVAILABLE if count else DataStatus.DATA_UNAVAILABLE
        quality = (
            DataQuality.MEDIUM
            if count >= 20
            else (DataQuality.LOW if count else DataQuality.UNAVAILABLE)
        )
        return FundamentalDataResult(
            security=security,
            cik=cik,
            company=resolved_name or companyfacts.payload.get("entityName"),
            as_of=cutoff,
            status=status,
            data_quality=quality,
            observations=observations,
            retrieved_at=max(companyfacts.retrieved_at, submissions.retrieved_at),
            sources=[
                {
                    "name": "SEC EDGAR Company Facts API",
                    "url": companyfacts.source_url,
                    "retrieved_at": companyfacts.retrieved_at.isoformat(),
                    "from_cache": companyfacts.from_cache,
                },
                {
                    "name": "SEC EDGAR Submissions API",
                    "url": submissions.source_url,
                    "retrieved_at": submissions.retrieved_at.isoformat(),
                    "from_cache": submissions.from_cache,
                },
            ],
            error=None if count else "no_eligible_annual_standard_taxonomy_facts",
        )


def extract_annual_observations(
    companyfacts: dict[str, Any],
    *,
    cik: str,
    filing_index: dict[str, FilingMetadata],
    as_of: datetime,
    retrieved_at: datetime,
    history_years: int,
) -> dict[str, list[FundamentalObservation]]:
    """Select the latest fact available by cutoff for each annual end date."""

    selected: dict[str, list[FundamentalObservation]] = {}
    facts = companyfacts.get("facts", {})
    for spec in CONCEPT_SPECS:
        by_end: dict[date, tuple[tuple[datetime, int], FundamentalObservation]] = {}
        for priority, (taxonomy, concept) in enumerate(spec.concepts):
            concept_payload = facts.get(taxonomy, {}).get(concept, {})
            units = concept_payload.get("units", {})
            unit = _select_unit(spec, units)
            if unit is None:
                continue
            for raw in units.get(unit, []):
                observation = _parse_fact(
                    raw,
                    spec=spec,
                    taxonomy=taxonomy,
                    concept=concept,
                    unit=unit,
                    cik=cik,
                    filing=filing_index.get(str(raw.get("accn", ""))),
                    cutoff=as_of,
                    retrieved_at=retrieved_at,
                )
                if observation is None:
                    continue
                key = (observation.available_at, -priority)
                previous = by_end.get(observation.end_date)
                if previous is None or key > previous[0]:
                    by_end[observation.end_date] = (key, observation)
        ordered = [
            pair[1]
            for pair in sorted(by_end.values(), key=lambda item: item[1].end_date)
        ]
        if ordered:
            selected[spec.name] = ordered[-(history_years + 1) :]
    return selected


def _parse_fact(
    raw: dict[str, Any],
    *,
    spec: ConceptSpec,
    taxonomy: str,
    concept: str,
    unit: str,
    cik: str,
    filing: FilingMetadata | None,
    cutoff: datetime,
    retrieved_at: datetime,
) -> FundamentalObservation | None:
    form = str(raw.get("form") or (filing.form if filing else ""))
    if form not in ANNUAL_FORMS or raw.get("fp") != "FY":
        return None
    try:
        end_date = date.fromisoformat(str(raw["end"]))
        filed_date = date.fromisoformat(str(raw.get("filed") or filing.filed_date))
        value = float(raw["val"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return None

    start_date: date | None = None
    if spec.kind == "duration":
        try:
            start_date = date.fromisoformat(str(raw["start"]))
        except (KeyError, TypeError, ValueError):
            return None
        if not 300 <= (end_date - start_date).days <= 430:
            return None
    elif raw.get("start"):
        return None

    accepted_at = _parse_acceptance(filing.acceptance_datetime if filing else None)
    if accepted_at is not None:
        available_at = accepted_at
        precision = AvailabilityPrecision.ACCEPTANCE_TIMESTAMP
        confidence = 1.0
    else:
        available_at = datetime.combine(filed_date, time.max, tzinfo=UTC)
        precision = AvailabilityPrecision.FILED_DATE
        confidence = 0.95
    if available_at > cutoff:
        return None

    accession = str(raw.get("accn") or (filing.accession if filing else ""))
    if not accession:
        return None
    currency = unit.split("/", 1)[0] if len(unit) >= 3 and unit[:3].isalpha() else None
    return FundamentalObservation(
        name=spec.name,
        value=value,
        taxonomy=taxonomy,
        concept=concept,
        unit=unit,
        currency=currency,
        start_date=start_date,
        end_date=end_date,
        fiscal_year=_optional_int(raw.get("fy")),
        fiscal_period=raw.get("fp"),
        form=form,
        accession=accession,
        filed_date=filed_date,
        accepted_at=accepted_at,
        available_at=available_at,
        availability_precision=precision,
        source_url=_filing_url(cik, accession, filing.primary_document if filing else None),
        retrieved_at=retrieved_at,
        confidence=confidence,
        status=DataStatus.AVAILABLE,
    )


def _relevant_accessions(
    payload: dict[str, Any], cutoff: datetime, history_years: int
) -> set[str]:
    result: set[str] = set()
    earliest_end_year = cutoff.year - history_years - 2
    for spec in CONCEPT_SPECS:
        for taxonomy, concept in spec.concepts:
            units = (
                payload.get("facts", {})
                .get(taxonomy, {})
                .get(concept, {})
                .get("units", {})
            )
            for entries in units.values():
                for raw in entries:
                    if raw.get("form") not in ANNUAL_FORMS or raw.get("fp") != "FY":
                        continue
                    try:
                        filed = date.fromisoformat(str(raw["filed"]))
                        end = date.fromisoformat(str(raw["end"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if (
                        filed <= cutoff.date()
                        and end.year >= earliest_end_year
                        and raw.get("accn")
                    ):
                        result.add(str(raw["accn"]))
    return result


def _parse_acceptance(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _filing_url(cik: str, accession: str, primary_document: str | None) -> str:
    base = (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/"
    )
    return base + primary_document if primary_document else base


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _select_unit(spec: ConceptSpec, units: dict[str, Any]) -> str | None:
    preferred = next(
        (candidate for candidate in spec.preferred_units if candidate in units), None
    )
    if preferred is not None:
        return preferred
    if "shares" in spec.preferred_units:
        return "shares" if "shares" in units else None
    if any("/shares" in item for item in spec.preferred_units):
        return next(
            (
                unit
                for unit in units
                if re.fullmatch(r"[A-Z]{3}/shares", str(unit))
            ),
            None,
        )
    return next(
        (unit for unit in units if re.fullmatch(r"[A-Z]{3}", str(unit))),
        None,
    )


def unavailable_fundamental_data(
    security: Security,
    cutoff: datetime,
    status: DataStatus,
    error: str,
    *,
    cik: str | None = None,
    company: str | None = None,
) -> FundamentalDataResult:
    return FundamentalDataResult(
        security=security,
        cik=cik,
        company=company or security.company,
        as_of=cutoff,
        status=status,
        data_quality=DataQuality.UNAVAILABLE,
        observations={},
        retrieved_at=datetime.now(UTC),
        sources=[],
        error=error,
    )

# AI Stock Opportunity Scanner

Version `0.8.0` implements the price/drawdown scanner, a **point-in-time
fundamental engine for SEC-reporting US issuers**, valuation, point-in-time
FRED/ALFRED macro vintages, public GDELT news metadata, and conservative shock
detection, same-security historical drawdown analogues, and evidence-derived
bear/base/bull temporal scenarios and targets. It preserves the
actual availability cutoff of SEC filings and macro
vintages, calculates current/historical/peer multiples, and can run sourced
bear/base/bull, normalized, and reverse DCFs. Fundamental Quality, Valuation,
and Temporary Shock scores are coverage-adjusted.

It still does **not** conclude that a decline is an investment opportunity or
that a shock is temporary. Final scoring, AI analysis, and backtesting are
reserved for later phases. DCF and macro-exposure
output remain null until the user adds real, dated, reviewable assumptions.

## Core data rule

No missing market datum is estimated or invented. External observations retain:

- source and source URL;
- retrieval timestamp and observation date/period;
- currency and unit when supplied by the universe or provider;
- confidence and availability status.

Unavailable values are exported as null and listed in `missing_metrics`; their
per-field state appears in `metric_statuses` as `data_unavailable`. The scanner
prefers adjusted close and explicitly records `price_basis=close` when adjusted
close is unavailable.

The same rule applies to forecasts. Temporal scenarios derive revenue growth,
margins, and multiples from point-in-time historical observations; they do not
apply discretionary `-10%` or `+20%` adjustments. The application ships with no
DCF growth, tax, capex, working-capital, WACC, or terminal-growth defaults.
Every DCF scenario must be explicitly configured with an assumption date and
source.

## Installation

Python 3.11 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The local `.env` is already populated with the project's identifying SEC
User-Agent. To enable macro data, add your personal FRED API key:

```dotenv
SEC_USER_AGENT=AI Stock Opportunity Scanner your.email@example.com
FRED_API_KEY=your_32_character_lowercase_key
```

The SEC requires automated clients to identify themselves. The application
refuses an anonymous or unchanged placeholder User-Agent. `.env` is loaded
without overriding variables already defined in the shell and is ignored by Git.
FRED requires a free API key; the scanner never writes it to cache, provenance,
or reports. GDELT and Yahoo require no key.

## Configure the universe

`config/universe.yaml` ships with a 15-security US pilot universe. Its CIKs,
issuer names, and exchanges were checked against the official SEC ticker mapping
on 2026-08-28. It is deliberately labeled as a pilot rather than a complete or
survivorship-free market universe. You can edit or replace its explicit entries:

```yaml
securities:
  - ticker: EXAMPLE
    cik: "1234567"
    company: Example Corp
    country: United States
    sector: Industrials
    exchange: Nasdaq
    currency: USD
    benchmark: ^GSPC
    sector_benchmark: EXAMPLE-SECTOR-ETF
```

The labels above only illustrate the schema; they are not shipped as market data
and should be replaced with verified identifiers.

For a large universe, set `csv_path` in `config/universe.yaml`. The CSV supports:

```text
ticker,cik,company,country,sector,exchange,currency,benchmark,sector_benchmark,
market_cap,market_cap_currency,market_cap_source,market_cap_source_url,
market_cap_observation_date,market_cap_retrieved_at,market_cap_confidence
```

`ticker` is required. `cik` is optional but strongly recommended for SEC issuers
because ticker mappings can change and the SEC states that their mapping is not
guaranteed to be complete. If `market_cap` is populated, all market-cap currency,
source, observation/retrieval date, and confidence fields are mandatory. The
universe is explicit and point-in-time: keep dated
snapshots externally if you later intend to backtest. `minimum_market_cap` filters
only rows that already contain a market cap; V1 does not fetch or infer one.

## Configure valuation assumptions

`config/valuation.yaml` is intentionally empty. Add a ticker only when every
assumption is documented and was genuinely available by the intended valuation
cutoff. Each security requires `assumption_date`, `source`, and complete
bear/base/bull scenarios. `normalized` is optional and must describe an explicit
shock-free operating case; the engine never manufactures one.

Schema example (illustrative values only, not market forecasts):

```yaml
version: 1
securities:
  EXAMPLE:
    assumption_date: 2025-01-15
    source: "Documented analyst assumptions; replace with a reviewable source"
    notes: "Illustrative schema only"
    bear:
      projection_years: 5
      revenue_growth: [0.01, 0.01, 0.02, 0.02, 0.02]
      operating_margin: 0.10
      tax_rate: 0.25
      depreciation_margin: 0.03
      capex_margin: 0.04
      working_capital_investment_margin: 0.01
      wacc: 0.10
      terminal_growth: 0.01
    base: # same required fields
      projection_years: 5
      revenue_growth: 0.04
      operating_margin: 0.12
      tax_rate: 0.25
      depreciation_margin: 0.03
      capex_margin: 0.04
      working_capital_investment_margin: 0.01
      wacc: 0.09
      terminal_growth: 0.02
    bull: # same required fields
      projection_years: 5
      revenue_growth: 0.07
      operating_margin: 0.14
      tax_rate: 0.25
      depreciation_margin: 0.03
      capex_margin: 0.04
      working_capital_investment_margin: 0.01
      wacc: 0.08
      terminal_growth: 0.025
```

Every scalar operating assumption may instead be a list with exactly one value
per projection year. Validation rejects invalid ranges and any terminal growth
greater than or equal to WACC. An assumption dated after `--as-of` is ignored and
exported as unavailable, preventing future forecast leakage.

## Run the scanner

```powershell
python -m src.pipeline
```

Alternative configuration/universe:

```powershell
python -m src.pipeline --config config/settings.yaml --universe path\to\universe.yaml
```

Historical point-in-time cutoff:

```powershell
python -m src.pipeline --as-of 2023-03-15
```

The cutoff is shared by prices, SEC facts, valuation, FRED/ALFRED vintages, and
news metadata. A date means end-of-day UTC. For an explicit intraday timestamp,
the daily price scanner conservatively stops at the preceding calendar date,
because Yahoo daily bars do not provide a reliable public-availability time.
This avoids using a same-day close that may not yet have existed.

After editable installation, the equivalent command is:

```powershell
stock-scanner
```

Missing `SEC_USER_AGENT` or `FRED_API_KEY` does not fabricate
data or abort unrelated stages: the corresponding results are exported as
`data_unavailable`.

## Current interface

Through Phase 7, the supported user interface is the generated Excel workbook,
not Streamlit. Open the newest workbook after a run with:

```powershell
$report = Get-ChildItem reports\*.xlsx | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Invoke-Item $report.FullName
```

The workbook contains `Candidates`, `All Results`, and `Run Metadata`. Detailed
audit trails are the JSON/CSV files described below. `dashboard/app.py` is an
explicit Phase 11 boundary and is not a runnable dashboard yet; launching it
would falsely imply that the later scoring, backtest, AI, and UI phases
already exist.

## Decision flow through Phase 7

The current strategy is a sequence of evidence filters, not a BUY/SELL model:

1. Load an explicit, dated universe and establish one shared `as_of` cutoff.
2. Retrieve SEC facts and FRED/ALFRED vintages that were available at that time.
3. Download price histories, remove every daily bar ineligible at the cutoff,
   and calculate drawdowns, returns, momentum, volatility, beta, and relative
   performance.
4. Mark a security as a decline candidate only when a configured drawdown or
   sector-relative threshold is crossed with enough observations.
5. Calculate point-in-time quality and valuation indicators. Missing inputs
   reduce coverage instead of being estimated.
6. Retrieve GDELT metadata only for decline candidates, match the configured
   shock taxonomy, require independent-source corroboration, and attach any
   dated macro-exposure assumptions.
7. Export every security and its audit trail. The pipeline ranks decline severity;
   it does not yet calculate the final Opportunity Score or an investment
   verdict.
8. For every decline candidate, detect prior completed peak–trough–recovery
   episodes on the same security, reconstruct SEC fundamentals and valuation
   multiples that were public at each episode peak, and rank comparable paths.
9. Derive lower-quartile/median/upper-quartile operating and valuation regimes,
   project them over 3/6/12/18/24 months, and calculate only model-supported
   targets, fundamental invalidations, and risk/reward.

Outputs are timestamped under `reports/`:

- CSV with every scanned security;
- Excel with `Candidates`, `All Results`, and `Run Metadata` sheets.
- `fundamental_analysis_*.csv` with score pillars and calculated metrics;
- full, cutoff-versioned per-company audit JSON under
  `data/processed/fundamentals/`.
- `valuation_analysis_*.csv` with multiples, scenario values, reverse DCF, and
  score coverage;
- full, cutoff-versioned valuation JSON under `data/processed/valuations/`,
  including formulas, filing accessions, assumptions, and annual DCF cash flows.
- `macro_analysis_*.csv` plus full, cutoff-versioned FRED series JSON under
  `data/processed/macro/`;
- `shock_analysis_*.csv`, candidate news-metadata JSON, and auditable shock JSON
  under `data/processed/shocks/`.
- `historical_analogues_*.csv` with current versus prior drawdown paths, recovery
  times, subsequent returns, similarity coverage, and point-in-time context;
  full audit JSON lives under `data/processed/historical/`.
- `scenario_analysis_*.csv` with 15 rows per analyzed candidate (three cases by
  five horizons), model-specific values, targets, coverage, invalidations, and
  risk/reward; full audit JSON lives under `data/processed/scenarios/`.

## Historical analogue methodology

Phase 6 scans adjusted daily closes (falling back to close when adjusted close
is unavailable) for threshold-crossing drawdown cycles. An episode begins at the
last running peak, records its lowest subsequent close, and is complete only when
the price regains the prior peak. The default threshold is -15%; both it and the
recovery tolerance are configurable under `historical`.

Only completed episodes preceding the active drawdown can become analogues. For
each one, the engine reports maximum drawdown, calendar-day decline duration,
trough-to-recovery time, total peak-to-recovery time, and 3/6/12/24-month returns
from the trough. A return is null when the requested horizon extends beyond the
shared `as_of` cutoff.

At every episode peak, SEC observations are re-filtered on their actual
`available_at` timestamp and the fundamental engine is rerun from that subset.
The historical snapshot therefore contains only annual metrics that an analyst
could have known then. Historical P/E, EV/EBITDA, and P/FCF points are likewise
eligible only when both filing availability and the associated price date are no
later than the episode peak. Accessions, formulas, period ends, availability
timestamps, and source URLs remain in the JSON audit trail.

Similarity is a 0–100 descriptive index, not a return probability. It combines
maximum drawdown (35%), decline duration (20%), comparable fundamental ratios
(25%), and positive valuation multiples (20%). Missing fundamental or valuation
context is not imputed: the score uses the available components and separately
exports `similarity_coverage`. With price-only evidence, coverage is 55%.
Analogues are same-security price/fundamental comparisons; the engine does not
claim that their causal shock matches COVID, 2008, inflation, energy, or a
geopolitical event. Causal event labeling requires dated primary evidence and is
not fabricated from a price path.

## Phase 7 scenario and target methodology

For each decline candidate, the engine reconstructs annual SEC revenue growth,
operating/net/EBITDA/FCF margins, leverage, and point-in-time historical P/E,
EV/EBITDA, and P/FCF observations available by the shared cutoff. Bear, base,
and bull use the observed lower quartile, median, and upper quartile. For
leverage, the adverse direction is reversed. A minimum of two observations is
required by default; missing inputs remain null.

At 3, 6, 12, 18, and 24 months, revenue is compounded with the selected annual
growth regime. EPS, FCF, and EBITDA follow from the corresponding observed margin
and the latest SEC share count. Target values are independently calculated by:

- projected positive EPS × historical P/E;
- projected positive FCF/share × historical P/FCF;
- projected positive EBITDA × historical EV/EBITDA, converted from enterprise
  to equity value with reported debt, cash, and shares.

The target is the median of the available model values and requires the
configurable minimum number of methods. No fixed price uplift is added. Bear,
base, and bull targets use the configured 12-month horizon by default. TP1,
TP2, and TP3 are the 6/12/24-month base targets. `Fair Value` uses a sourced base
DCF when available and otherwise the base temporal target. `Normalized Fair
Value` uses a sourced normalized DCF and otherwise the 24-month base target.

WACC and terminal growth are preserved only when a dated, sourced DCF
configuration exists by `as_of`; the temporal multiple models do not manufacture
them. Assumption coverage is exported across growth, margins, EPS, FCF,
multiples, WACC, and terminal growth.

Fundamental invalidation levels are derived from the bear operating regime for
revenue growth, operating margin, FCF margin, and leverage. Guidance, order-book,
and structural market-share invalidations remain explicitly unavailable without
a point-in-time source. These are thesis conditions, not technical stop-losses.

Risk/reward is `base upside / abs(bear downside)` and remains null unless base
upside is positive and bear downside is negative. Targets and risk/reward are
model outputs, not forecasts validated by backtesting and not investment advice.

Normalized daily observations are cached under `data/cache/prices/` and persisted
under `data/processed/prices/`. Raw SEC API responses are cached under
`data/cache/sec/`; FRED and GDELT responses use separate caches under
`data/cache/macro/` and `data/cache/news/`. Runtime data and reports are excluded
from Git.

## Point-in-time SEC methodology

The engine uses the official SEC `companyfacts` endpoint for standard-taxonomy
XBRL facts and the `submissions` endpoint for filing metadata. Ticker-to-CIK
resolution uses the official SEC mapping only when the universe does not supply a
CIK.

For every fact it stores:

- taxonomy and concept;
- reported value and unit;
- fiscal start/end dates;
- form, accession, filed date, and acceptance timestamp;
- direct filing URL, retrieval timestamp, and confidence;
- availability precision (`acceptance_timestamp` or conservative `filed_date`).

A fact is eligible only when its public availability is at or before `as_of`.
Later amendments/restatements replace an earlier value only after the amendment
was accepted. When an exact acceptance timestamp cannot be recovered, the filing
is conservatively considered available at the end of its filed date. Quarterly
facts are never mixed into annual metrics: this phase accepts annual 10-K/10-K/A
facts with durations between 300 and 430 days.

The client uses a required identifying User-Agent, defaults to five requests per
second (below the SEC limit of ten), caches responses, retries transient failures,
and fetches older submissions continuation files only when required accessions
are missing. See the official [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and [developer access guidance](https://www.sec.gov/about/developer-resources).

## Fundamental calculations

The engine currently calculates:

- growth: revenue, diluted EPS, calculated EBITDA, and FCF CAGR;
- profitability: gross, EBITDA, operating, and net margins; ROE and ROIC;
- balance sheet: disclosed debt, net debt, debt/equity, net debt/EBITDA,
  interest coverage, cash/debt, and current ratio;
- cash flow: operating cash flow, capex, FCF, FCF margin, FCF/share, cash
  conversion, and the share of positive-FCF years.

CAGR uses the earliest and latest positive endpoints available within the
configured history window (`history_years`, five by default) and the actual
elapsed calendar time between fiscal period ends.

`ebitda_calculated` is explicitly defined as operating income plus reported
depreciation/amortization. Debt uses a reported total long-term-debt fact when
available, otherwise current plus non-current long-term debt, and adds short-term
borrowings only when separately disclosed. Missing inputs remain null; the
engine never assumes zero debt, capex, tax, or depreciation.

ROIC uses reported effective tax expense/pretax income. No default statutory tax
rate is inserted. If inputs are missing or invalid, ROIC is null.

## Fundamental Quality Score

The score has four fixed-weight pillars:

- Growth: 25%
- Profitability: 30%
- Balance sheet: 25%
- Cash flow: 20%

Every input is mapped through documented piecewise bands in
`src/analysis/fundamentals.py`. Each pillar exposes its metric scores, observed
score, and coverage. The overall exported score is coverage-adjusted; missing
metrics contribute no points and are never imputed. If weighted coverage is below
the configurable minimum (50% by default), the overall score is null.

This is a **quality score out of 100**, not a probability of profit and not an
investment verdict. The first version is deliberately sector-agnostic, so banks,
insurers, REITs, and other structurally different sectors require later
sector-specific scorecards.

## Point-in-time valuation methodology

The valuation cutoff is the same timestamp used by the fundamental engine.
Current multiples use the last daily close dated no later than that cutoff. For
every historical fiscal year, the engine first finds the latest public
availability among all required SEC facts, then uses the first trading close
strictly after that date and no later than the cutoff. This conservative rule
prevents a filing from being paired with a price that predates its publication
or postdates the simulated analysis. The close must be within seven calendar
days of publication; otherwise the historical point is considered unavailable
rather than paired with a stale gap in the price series.

The implemented multiples are:

- P/E = close / positive diluted EPS;
- EV/EBITDA = (market capitalization + disclosed debt - cash) / positive
  calculated EBITDA;
- P/FCF = market capitalization / positive free cash flow.

For current EV and P/FCF, a universe market cap is eligible only when it has the
required provenance, is in USD, and its observation date exactly matches the
valuation close date. Otherwise market cap is calculated transparently from the
valuation close and SEC shares outstanding (or diluted weighted-average shares
when the instant share count is unavailable). Historical market caps always use
the post-publication close and the aligned reported share count. The basis is
stored in every audit result.

A historical median requires three positive annual observations by default.
Sector medians compare the exact configured sector label, exclude the target
security, require the same point-in-time cutoff, require three positive peers by
default, and never substitute a global median. These thresholds are configurable
under `valuation` in `config/settings.yaml`.

No FX conversion is currently implemented. A non-USD or unknown price currency
cannot be combined with SEC USD facts, so the affected valuation methods remain
null rather than silently mixing currencies.

## DCF, reverse DCF, and normalized value

Each configured scenario projects revenue and unlevered free cash flow as:

```text
EBIT  = revenue x operating margin
NOPAT = EBIT x (1 - tax rate)
UFCF  = NOPAT + D&A - capex - working-capital investment
```

Explicit annual UFCF is discounted at WACC. Terminal value uses the Gordon model
with validated `WACC > terminal growth`. Enterprise value is converted to equity
value using reported debt and cash, then divided by reported diluted shares (or
shares outstanding if diluted shares are unavailable). Every projected year,
discount factor, terminal value, and assumption is written to the audit JSON.

Bear, base, and bull scenarios are mandatory for a configured ticker. A
normalized scenario is optional and is calculated only from its own explicit
assumptions. The engine does not infer that a shock will disappear.

Reverse DCF holds the non-growth base assumptions fixed and solves, by bounded
dichotomy, for the constant revenue growth rate that makes DCF enterprise value
equal to the enterprise value implied by the point-in-time close. If the market
value is outside the configurable growth bounds (default -50% to +50%), the
implied rate is null with an explicit reason.

## Valuation Score

The score uses four fixed-weight components:

- P/E discount to available historical and sector references: 20%;
- EV/EBITDA discount to available historical and sector references: 20%;
- P/FCF discount to available historical and sector references: 20%;
- base-DCF margin of safety versus the valuation close: 40%.

Discounts pass through documented piecewise bands in
`src/analysis/valuation.py`. A missing reference or DCF is not imputed. The
result exposes the observed score, weighted coverage, every component signal,
and a coverage-adjusted score. It remains null below the configurable coverage
minimum (50% by default).

This is a **valuation indicator out of 100**, not a target-price guarantee, a
probability of profit, or a BUY/WATCH/PASS verdict.

## Point-in-time macro engine

`config/macro.yaml` declares stable FRED series identifiers; titles, frequency,
units, observations, and real-time periods come from the official API. For each
run, the engine sends the same cutoff date as both `realtime_start` and
`realtime_end`. This is the ALFRED vintage that was observable on that date, not
today's revised history retroactively attached to an old run. Each observation
retains its observation date, returned real-time start/end, retrieval timestamp,
source URL, status, and quality.

The default configuration retrieves the effective federal funds rate, US CPI,
WTI oil, 10-year Treasury yield, VIX, and US unemployment. It exports raw values
and mechanical absolute/percentage changes over approximately 30, 90, and 365
calendar days. These changes are context, not a claim that the variable caused a
stock move. Missing values and series errors remain explicit and never abort the
rest of the universe.

See the official [FRED observations API](https://fred.stlouisfed.org/docs/api/fred/series_observations.html),
[real-time-period documentation](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html),
and [FRED versus ALFRED explanation](https://fred.stlouisfed.org/docs/api/fred/fred_vs_alfred.html).

## Macro-exposure assumptions

`config/macro_exposures.yaml` is intentionally empty. A sector or security
exposure is applied only when it includes a non-zero coefficient, rationale,
assumption date, and reviewable source. Security-level entries override a sector
entry for the same series. Any assumption dated after `--as-of` is rejected.

The coefficient only determines the sign of a configured association. For
example, a negative coefficient combined with a rising macro series is reported
as a configured headwind. It is not an estimated beta, sensitivity, causal
effect, forecast, or proof that macro conditions explain the drawdown.

## News metadata and shock detection

Only securities that pass the decline screen trigger a GDELT query. The scanner
stores title, public URL, domain, language/country metadata, and GDELT `seendate`;
it does not scrape or persist article bodies, bypass paywalls, or fabricate a
publication timestamp. `seendate` is preserved specifically as the time GDELT
indexed/saw the item and must not be presented as a publisher-certified date.
The free DOC 2.0 API exposes a rolling recent window, so cutoffs older than 90
days are marked unavailable instead of silently querying current news. See the
official [GDELT DOC 2.0 API description](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/).

`config/shock_taxonomy.yaml` maps headline terms to the specification's public
categories:

```text
GEOPOLITICAL, MACRO, INTEREST_RATES, INFLATION, COMMODITIES,
REGULATION, LEGAL, EARNINGS, GUIDANCE, COMPETITION, PRODUCT,
MANAGEMENT, OPERATIONAL, SUPPLY_CHAIN, CYCLICAL, UNKNOWN
```

The nature is one of `TEMPORARY`, `PROBABLY_TEMPORARY`, `UNCERTAIN`,
`STRUCTURAL`, or `SEVERE_STRUCTURAL`, but this deterministic evidence layer
never emits `TEMPORARY`. Resolution or temporary language must be corroborated
by at least two independent domains before it can emit
`PROBABLY_TEMPORARY`. Structural evidence takes precedence; severe terms such
as bankruptcy or default yield `SEVERE_STRUCTURAL`. Otherwise the result stays
`UNCERTAIN`.

The Temporary Shock Score combines four audited components: resolution evidence
(35%), structural-damage evidence (35%), independent-source corroboration (15%),
and available fundamental resilience (15%). Missing components reduce coverage;
the score remains null below the configured coverage threshold. It is an
evidence-coverage-adjusted indicator, **not a probability of normalization**.
Headline keyword matches are triage signals and require human verification.

The shock result also exposes `specification_criteria_coverage`,
`criterion_statuses`, and `missing_criteria` for the ten Temporary Shock
criteria in the master specification. This coverage is deliberately separate
from the Phase 5 score coverage. Causal shock duration/precedents, quantified
revenue/margin/FCF/balance-sheet impacts, and analyst expectations remain
`data_unavailable` until later point-in-time engines supply real evidence.

## V1 methodology

For each security the scanner calculates:

- drawdown from the maximum in the downloaded history (`history_period: max` by
  default) and from the trailing 252-session high;
- drawdown from the highest price inside approximately 1, 3, 6, and 12 months
  (21/63/126/252 trading sessions) plus the current-year high;
- separately named endpoint total returns over 1, 3, 6, and 12 months plus YTD;
- distance from 50- and 200-session simple moving averages;
- Wilder RSI, annualized daily volatility, and 252-session beta;
- 12-month relative total return versus the configured broad and sector
  benchmarks.

`drawdown_*` always means current price divided by the relevant period high,
minus one. `return_*` always means endpoint total price return. The two are kept
separate so a recovery followed by a new decline cannot be mislabeled.

A row is a V1 candidate if it has at least `minimum_observations` and crosses any
configured threshold for 52-week, 3-month, 6-month, or sector-relative decline.
All thresholds are editable in `config/settings.yaml`.

`decline_severity_score` ranks the magnitude of observed price weakness from
0–100. It is **not** the future multi-factor Opportunity Score, is not a
probability of profit, and is not a BUY/WATCH/PASS verdict. Missing components
contribute zero and are never imputed.

## Price source and data quality

V1 uses Yahoo Finance through the open-source `yfinance` client. Yahoo is a useful
free source but not an official exchange feed. The provider:

- requests daily OHLCV and adjusted close without yfinance's price-repair option;
- stores the Yahoo quote URL and retrieval time on every row;
- catches ticker/network failures independently so one failure does not abort a
  universe scan;
- uses a configurable time-to-live cache to reduce load;
- assigns at most `MEDIUM` quality because V1 has only one price source.

Respect Yahoo's terms and avoid aggressive concurrency. `max_workers` defaults to
4. A later provider can implement the `PriceSource` protocol without changing the
screening logic.

## Tests

```powershell
python -m pytest
```

All test market series are synthetic and confined to `tests/`. They never appear
in user-facing scan output.

## Architecture

```text
config/                 validated YAML settings and universe
data/                   ignored raw/processed/cache/database runtime areas
src/models.py           provenance, analysis, shock, and historical models
src/data/               Yahoo, SEC EDGAR, FRED/ALFRED, and GDELT clients/caches
src/screening/          universe, returns/drawdowns, momentum, filter/ranking
src/reporting/          auditable price/fundamental/valuation/macro/shock/analogue exports
src/pipeline.py         integrated point-in-time scanner CLI
src/analysis/           fundamental, valuation, macro, shock, and analogue calculations
src/forecasting/        assumption-driven DCF and reverse DCF
src/scoring/            reserved opportunity/risk scoring boundary
src/backtest/           reserved point-in-time backtest boundary
src/ai/                 reserved critical analyst boundary
dashboard/              reserved Streamlit boundary
tests/                  offline unit and integration tests
```

Reserved modules contain no hidden placeholder calculations. This keeps the
specified architecture visible without pretending later phases are implemented.
The current checked/partial/deferred audit is maintained in
`docs/PHASE_7_COMPLIANCE.md`.

## Known V1 limitations

- There is no automatic, survivorship-bias-free global constituent discovery;
  users must provide a maintained YAML/CSV universe.
- Yahoo data can be delayed, adjusted, incomplete, unavailable, or subject to
  provider changes. V1 does not corroborate it with an exchange feed.
- Market cap is not fetched. Valuation may derive it from the point-in-time close
  and a reported SEC share count, with the formula recorded in the audit output.
- Relative performance and beta remain null unless benchmark tickers are set and
  have enough aligned observations.
- “ATH” means the maximum within the requested/downloaded history. With the
  default `max` period this attempts full provider history, but completeness still
  depends on the source.
- SEC normalization currently covers annual standard `us-gaap` facts in 10-K
  filings. Custom company extensions, IFRS/20-F/40-F, discrete quarters, and TTM
  calculations are not yet supported.
- Company Facts is a current aggregate API. Filtering by accession/acceptance
  prevents ordinary future-filing leakage, but a production historical backtest
  should additionally archive daily SEC snapshots or use dated bulk datasets to
  guard against later API-level corrections.
- Per-company APIs are appropriate for a filtered or cached universe. For several
  thousand issuers, the nightly SEC `companyfacts.zip` and `submissions.zip` bulk
  archives should be added rather than multiplying individual requests.
- Quality bands are sector-agnostic and must not be used as-is for financial
  institutions or other sectors with structurally different accounting.
- Multiples are annual rather than TTM, sector membership is user-configured, and
  free Yahoo prices plus SEC facts are not independently corroborated.
- DCF assumptions are manual and must be maintained by the user. A normalized
  value does not exist unless a sourced normalized scenario is supplied.
- FRED vintages require an API key and use the provider's documented real-time
  dates. Strict production backtests should additionally archive every raw
  response so later provider corrections remain reproducible.
- GDELT supplies discovery metadata and `seendate`, not a guaranteed original
  publication timestamp. Its rolling recent window cannot provide strict old
  point-in-time news history; those cutoffs are explicitly unavailable.
- Headline taxonomy is deterministic triage. It cannot establish causality,
  distinguish every linguistic nuance, assess full-text context, or substitute
  for a review of primary company disclosures and regulatory filings.
- Macro exposures are empty by default and user-supplied when enabled. Their
  signed arithmetic is not an empirically estimated causal model.
- The Temporary Shock Score currently covers only evidence that can be audited
  from Phase 3 fundamentals, macro inputs, and public headline metadata. The
  remaining specification criteria—historical shock duration/analogues,
  detailed guidance and analyst expectations—stay missing rather than imputed.
- No FX conversion, causal event catalogue, critical verdict,
  dashboard, alerts, or backtest exists yet.
- Phase 6 compares episodes only within the same security. It does not yet search
  other companies or attach a causal crisis label. Old episodes can have price
  comparisons while fundamental/valuation context stays null because the live
  SEC history window defaults to five years.
- Phase 7 regimes are historical quartiles, not analyst consensus and not
  statistically calibrated outcome probabilities. Annual SEC facts can miss
  recent quarterly inflections; model targets can be widely dispersed when the
  historical multiple distribution is wide.
- WACC and terminal growth stay null without a dated DCF configuration. The
  fallback normalized fair value is explicitly the 24-month base target, not a
  separately sourced shock-free DCF.
- A severe decline can be entirely rational. Ranking does not establish
  undervaluation or temporary mispricing.

## Next recommended phase

Phase 8 should combine the existing audited sub-scores into Normalization,
Catalyst, Risk, and final Opportunity Scores while keeping every score separate
from probability. Before broad production use, also add sector-specific
fundamental scorecards and daily archived SEC/GDELT snapshots for strict
historical backtesting.

## Backtesting status and required methodology

Backtesting is Phase 9 and is not implemented in version 0.8.0. No current score
should therefore be treated as statistically validated. The future engine must
use point-in-time universe membership, unrevised provider snapshots, actual
filing/news availability, delisted securities, region-appropriate benchmarks,
and transaction assumptions. It must measure the return/risk statistics and
score buckets specified in the master specification without look-ahead,
survivorship, or revision leakage.

## Financial disclaimer

This software is for research and education. It is not investment advice, does
not guarantee data accuracy or future returns, and does not replace independent
due diligence or a qualified financial adviser.

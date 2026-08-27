# AI Stock Opportunity Scanner

Version `0.5.0` implements the price/drawdown scanner, a **point-in-time
fundamental engine for SEC-reporting US issuers**, and the Phase 4 valuation
engine. It preserves SEC filing availability, calculates current/historical/peer
multiples, and can run sourced bear/base/bull, normalized, and reverse DCFs.
Fundamental Quality and Valuation scores are both coverage-adjusted.

It still does **not** conclude that a decline is an investment opportunity.
News/shock classification, temporal target scenarios, AI analysis, and
backtesting are reserved for later phases. DCF output remains null until the user
adds real, dated, reviewable assumptions for a ticker.

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

The same rule applies to forecasts. The application ships with no DCF growth,
margin, tax, capex, working-capital, WACC, or terminal-growth defaults. Every
scenario must be explicitly configured with an assumption date and source.

## Installation

Python 3.11 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

No API key is required. Before downloading SEC data, copy `.env.example` to
`.env` and replace the SEC placeholder with your real organization/name and
contact email:

```dotenv
SEC_USER_AGENT=Your Real Organization contact@your-domain.example
```

The SEC requires automated clients to identify themselves. The application
refuses an anonymous or unchanged placeholder User-Agent. `.env` is loaded
without overriding variables already defined in the shell and is ignored by Git.

## Configure the universe

`config/universe.yaml` intentionally starts with an empty security list. This
prevents a small, stale sample from being mistaken for a current global universe.
You can add explicit entries:

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
python -m src.pipeline --as-of 2023-03-15T21:00:00Z
```

After editable installation, the equivalent command is:

```powershell
stock-scanner
```

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

Normalized daily observations are cached under `data/cache/prices/` and persisted
under `data/processed/prices/`. Raw SEC API responses are cached under
`data/cache/sec/`. Runtime data and reports are excluded from Git.

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

## V1 methodology

For each security the scanner calculates:

- drawdown from the maximum in the downloaded history (`history_period: max` by
  default) and from the trailing 252-session high;
- total return over approximately 1, 3, 6, and 12 months (21/63/126/252 trading
  sessions) plus YTD return;
- distance from 50- and 200-session simple moving averages;
- Wilder RSI, annualized daily volatility, and 252-session beta;
- 12-month relative total return versus the configured broad and sector
  benchmarks.

The exported fields keep the requested `drawdown_1m` naming, but these horizon
fields are endpoint total returns, not path-dependent peak-to-trough drawdowns.
This distinction is documented to prevent misleading interpretation.

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
src/models.py           provenance, fundamentals, valuation, and candidate models
src/data/               Yahoo prices plus responsible SEC EDGAR client/cache
src/screening/          universe, returns/drawdowns, momentum, filter/ranking
src/reporting/          price/fundamental/valuation JSON, CSV, and Excel exports
src/pipeline.py         integrated prices + fundamentals + valuation CLI
src/analysis/           fundamental and valuation calculations/scoring
src/forecasting/        assumption-driven DCF and reverse DCF
src/scoring/            reserved opportunity/risk scoring boundary
src/backtest/           reserved point-in-time backtest boundary
src/ai/                 reserved critical analyst boundary
dashboard/              reserved Streamlit boundary
tests/                  offline unit and integration tests
```

Reserved modules contain no hidden placeholder calculations. This keeps the
specified architecture visible without pretending later phases are implemented.

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
- No FX conversion, shock causality, historical analogues, temporal targets,
  verdict, dashboard, alerts, or backtest exists yet.
- A severe decline can be entirely rational. Ranking does not establish
  undervaluation or temporary mispricing.

## Next recommended phase

Phase 5 should implement official/free macro sources, legally accessible news
ingestion, and evidence-backed shock detection/classification. It must not infer
that a shock is temporary merely from a price decline. Before broad production
use, also add sector-specific fundamental scorecards and archived SEC snapshots
for strict historical backtesting.

## Financial disclaimer

This software is for research and education. It is not investment advice, does
not guarantee data accuracy or future returns, and does not replace independent
due diligence or a qualified financial adviser.

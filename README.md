# AI Stock Opportunity Scanner

Version `1.4.0` implements the price/drawdown scanner, a **point-in-time
fundamental engine for domestic and foreign SEC-reporting issuers**, valuation,
point-in-time FRED/ALFRED and ECB macro vintages, official Cboe put/call and CFTC
positioning context, public GDELT news metadata, and conservative shock
detection, same-security historical drawdown analogues, and evidence-derived
bear/base/bull temporal scenarios and targets, plus coverage-aware Phase 8
sub-scores and a Temporary Mispricing Opportunity Score. It preserves the
actual availability cutoff of SEC filings and macro
vintages, calculates current/historical/peer multiples, and can run sourced
bear/base/bull, normalized, and reverse DCFs. Fundamental Quality, Valuation,
Temporary Shock, Normalization, Catalyst, Future Growth, Risk Resilience, and
Opportunity scores are coverage-adjusted. Phase 9 adds strict archived-snapshot
backtesting, dated ECB/Frankfurter FX conversion, and write-once live signal
archives with SHA-256 integrity checks. Phase 10 provides the final styled Excel
report, Phase 11 provides a working Streamlit dashboard, and Phase 12 adds
deduplicated local alerts plus a guarded Windows daily-runner architecture.

It still does **not** conclude that a decline is an investment opportunity or
that a shock is temporary. A high Opportunity Score is not a probability,
recommendation, probability, or validated return forecast. A real 2018–2025
study remains unavailable until a survivorship-free historical universe and
immutable historical signals are supplied. AI analysis remains reserved for a
later phase. DCF and macro-exposure
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
or reports. ECB, Cboe, CFTC, GDELT, Yahoo, and ECB/Frankfurter FX require no key.
The free-source coverage map and the exact optional keys the user can create are
documented in `docs/FREE_WORLDWIDE_ACCESS_PLAN.md`.

## Configure the universe

`config/universe.yaml` now loads 319 native listings from 11 flagship EEA
indices: CAC 40, DAX 40, AEX 25, BEL 20, IBEX 35, FTSE MIB 40, OMX Stockholm
30, OMX Copenhagen 25, OMX Helsinki 25, OBX 25 and PSI. The former US snapshot
is no longer versioned or loaded by default; `scripts/update_us_universe.py`
can regenerate one explicitly. This deliberately focuses the scanner on
potential PEA holdings instead of maximizing the number of assets.

Every retained security is marked `review_required`, not
`confirmed_eligible`. An EEA listing is only a geographic screen: before an
order, confirm the issuer's registered office, equivalent corporate-tax status,
security type (notably SIIC exclusions), and the title's eligibility with the
PEA broker. The rule source and check date are exported with each row. Every
universe row also retains its observation date and constituent source URL. This
is a current research snapshot, not a survivorship-free historical index. You
can edit or replace its entries:

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

For a large universe, set `csv_path` or `csv_paths` in `config/universe.yaml`.
The CSV supports:

```text
ticker,cik,company,country,listing_country,country_basis,region,sector,exchange,
currency,benchmark,sector_benchmark,index_memberships,universe_source_urls,
universe_observation_date,price_scale,price_scale_reason,
pea_eligibility_status,pea_eligibility_basis,pea_eligibility_source_url,
pea_eligibility_checked_at,
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

Refresh the public European snapshot deliberately, after reviewing constituent
changes, with:

```powershell
python scripts/update_europe_universe.py --snapshot-date 2026-08-29
```

The generator fails closed if a constituent-table count changes. It also retains
official corporate-action links for known symbol changes. London Yahoo quotes
are published in GBp; `price_scale=0.01` converts OHLC fields to configured GBP
without scaling volume, and the scaling rule is included in the cache key. The
OBX relative-performance benchmark uses the tradable `OBXD.OL` DNB OBX ETF proxy
because the public Yahoo feed does not reliably expose the official OBX index.

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

## Current interfaces

The Phase 10 workbook contains `Candidates`, `All Results`, and `Run Metadata`.
Open the newest workbook after a run with:

```powershell
$report = Get-ChildItem reports\*.xlsx | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Invoke-Item $report.FullName
```

Launch the Phase 11 dashboard from the repository root with:

```powershell
python -m streamlit run dashboard/app.py
```

Then open `http://localhost:8501`. The dashboard automatically reads the newest
`stock_opportunity_scan_*.csv`, exposes country, sector, index, score, drawdown,
market-cap, shock, risk and horizon filters, and provides price, fundamental,
valuation, evidence and scenario tabs. Run the scanner again and refresh the
page to display the new report. The table is paginated rather than silently
limited to 50 rows; global search and an explicit filter reset prevent a retained
country/index filter from masquerading as a small universe. The dashboard never generates a BUY verdict:
before a valid Phase 9 calibration it displays an analytical priority or
`Non classé`, and the inactive critical-AI panel is explicit.

## Phase 12 automation and local alerts

The normal pipeline applies the thresholds under `alerts` in
`config/settings.yaml`. A row can alert only when it is a technical candidate,
has a non-null Opportunity Score with sufficient coverage, and belongs to the
PEA focus when `require_pea_focus` is enabled. New alerts are written as JSON,
CSV and Markdown under `data/processed/alerts/`; a durable state file prevents
the same ticker/date/score signal from being emitted twice.

Run one guarded daily job manually:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_daily.ps1
```

Optionally install a Windows daily task at a time you choose:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  scripts/install_windows_daily_task.ps1 -At "07:00"
```

No scheduled task is installed automatically. The runner prevents overlapping
executions and writes logs under `logs/`. The delivery boundary is ready for
email, Telegram, and Discord adapters, but only the free local channel is
enabled until an external destination is explicitly configured.

## Decision flow through Phase 12

The current strategy is a sequence of evidence filters, not a BUY/SELL model:

1. Load an explicit, dated universe and establish one shared `as_of` cutoff.
2. Retrieve FRED/ALFRED vintages and dated ECB reference FX rates that were
   available at that time.
3. Download every price history, remove every daily bar ineligible at the cutoff,
   and calculate drawdowns, returns, momentum, volatility, beta, and relative
   performance.
4. Mark a security as a decline candidate only when a configured drawdown or
   sector-relative threshold is crossed with enough observations.
5. Retrieve SEC facts and calculate point-in-time quality and valuation only
   for the decline candidates. Missing inputs reduce coverage instead of being
   estimated; non-candidates remain in the report without triggering this
   expensive stage.
6. Retrieve GDELT metadata only for decline candidates, match the configured
   shock taxonomy, require independent-source corroboration, and attach any
   dated macro-exposure assumptions.
7. Retain every intermediate result and its audit trail; no unavailable input is
   converted to a neutral score.
8. For every decline candidate, detect prior completed peak–trough–recovery
   episodes on the same security, reconstruct SEC fundamentals and valuation
   multiples that were public at each episode peak, and rank comparable paths.
9. Derive lower-quartile/median/upper-quartile operating and valuation regimes,
   project them over 3/6/12/18/24 months, and calculate only model-supported
   targets, fundamental invalidations, and risk/reward.
10. Calculate the seven configured scoring inputs, penalize missing evidence,
    require minimum coverage, and rank candidates by Opportunity Score with
    decline severity only as a tie/fallback signal.
11. On a genuinely live run, freeze the complete result, signal rows, and dated
    universe for future point-in-time research. Historical reconstructions made
    today are never labeled as old live archives.
12. Export all required Phase 10 fields, using `NOT_CALIBRATED` and
    `data_unavailable` instead of invented verdicts, catalysts, or risks.
13. Let Phase 11 read the latest immutable output and expose the evidence and
    coverage interactively without recalculating or mutating the scan.
14. Select threshold-qualified PEA-focus signals, persist auditable local alert
    artifacts, and suppress duplicates through durable alert IDs.

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
- `opportunity_scoring_*.csv` with every sub-score, coverage, confidence,
  score band, and methodology; full per-company audit JSON lives under
  `data/processed/scoring/`.
- `fx_analysis_*.csv`, plus dated pair JSON under `data/processed/fx/`; scan rows
  retain original values and add USD/EUR equivalents when rates are available.
- write-once live archives under the configured PEA lineage
  `data/raw/backtest_pea_v1_4_0/{source_archives,signals,universes}`.
- Phase 9 backtests produce one full JSON, one metrics CSV, and one trades CSV.
- Phase 12 emits new-alert JSON, CSV and Markdown under
  `data/processed/alerts/`; deduplication state lives in
  `data/cache/alerts/state.json`.

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
Value` requires a sourced normalized DCF and otherwise remains null; a generic
temporal target is not mislabeled as demonstrated shock normalization.

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

## Phase 8 scoring methodology

The configured Opportunity Score follows the master-specification proposal:

- Fundamental Quality 20%;
- Valuation 20%;
- Temporary Shock 15%;
- Normalization 15%;
- Catalyst 10%;
- Future Growth 10%;
- Risk Resilience 10%.

Fundamental, Valuation, and Temporary Shock retain the Phase 3–5 methods.
Future Growth reuses the audited SEC growth pillar. Normalization combines the
base-case valuation gap, similarity-weighted 12-month analogue outcomes,
recovery precedent strength, and shock-resolution evidence. Catalyst uses only
explicit dated resolution language and eligible configured macro relief; it
stays null when neither is observed. Risk Resilience combines balance-sheet
quality, bear-case protection, volatility, beta, and structural-shock evidence.
For Risk Resilience, a higher score means lower measured risk.

Every sub-score stores its raw observed score, evidence coverage, adjusted
score, weights, sources, and missing-data reasons. Missing weight contributes
zero to the adjusted score and is never filled with a neutral 50. The final
score requires at least 50% of configured top-level weight. `Confidence Score`
is the weighted raw evidence coverage expressed out of 100; it is not confidence
in a positive return. Data Quality remains LOW when coverage or source support
is weak, even if the numerical score is high.

Score bands (`LOW_SCORE` through `HIGH_SCORE`) are descriptive ranking labels,
not BUY/SELL verdicts. The Phase 9 engine exists, but no real calibration result
is claimed without the required archives; the score must never be displayed as
a chance of profit.

## Phase 9 backtest methodology

### Obtaining a real 2018–2025 dataset

The selected US source is Sharadar Direct Bundle with at least 10 years of
history. The repository now includes a secret-safe access check, bulk downloader,
schema validation, and SHA-256 manifests for the active/delisted security master,
historical S&P 500 membership, prices, as-reported fundamentals, daily multiples,
corporate actions, and material 8-K events.

Add `SHARADAR_API_KEY` to the local `.env`, then run:

```powershell
python -m src.backtest.dataset access
python -m src.backtest.dataset download
python -m src.backtest.dataset audit-local
```

These commands intentionally keep `core_backtest_ready=false` until dated
signals have been rebuilt from the verified archives and the strict Phase 9
engine has completed. Full subscription guidance and the selected global,
consensus/guidance, historical-news, and AI sources are documented in
`docs/HISTORICAL_DATA_ACCESS.md`.

The backtest consumes archived signal CSV files, outcome-price CSV files, and
dated universe snapshots. It refuses output unless signal availability is no
later than the signal date, the source JSON's SHA-256 matches the declared hash,
the security belonged to that dated universe, and its regional benchmark has a
valid history. Price dates and values must be valid, positive, and unique.

Entry occurs at the first trading session strictly after the signal. Exit occurs
at the first session on or after the configured holding horizon (12 months by
default). Costs default to 10 basis points per side. The portfolio is equally
weighted across active positions and earns zero while in cash; benchmark paths
use matching windows without transaction costs.

Results include 2018–2025 year slices where data exists; score buckets 50–59,
60–69, 70–79, 80–89, and 90–100; CAGR, total return, hit rate, average and median
return, maximum drawdown, volatility, Sharpe, Sortino, recovery time, win/loss
ratio, and performance versus benchmark.

Run it after supplying the required archives:

```powershell
python -m src.backtest.engine `
  --signals data/raw/backtest/signals `
  --prices path/to/point_in_time_prices `
  --universes data/raw/backtest/universes `
  --config config/settings.yaml `
  --output reports/backtest_result.json
```

After editable installation, use `stock-backtest` with the same arguments. Both
`--signals` and `--prices` accept either one CSV or a directory of CSV files.
Each signal row requires:

```text
ticker,signal_date,opportunity_score,data_quality,signal_available_at,
universe_snapshot_date,source_archive_id,source_archive_sha256,
point_in_time_validated,benchmark_ticker
```

Universe snapshot filenames must be `YYYY-MM-DD.csv` and contain `ticker`.
Prices require `ticker,observation_date,adjusted_close`. Set a region-appropriate
benchmark in every signal (MSCI World, S&P 500, STOXX Europe 600, or CAC 40 as
appropriate to the tested mandate). The scanner automatically creates usable
live archives going forward, but it cannot recreate evidence that was never
archived in 2018–2025.

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

Dated FX conversion is implemented for scan prices and configured market caps,
with original, USD, and EUR values exported together. Valuation still requires
currency-consistent accounting inputs: it will not translate a historical SEC
fact with one current FX rate or silently mix currencies, so an incompatible or
unknown valuation currency leaves the affected method null.

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

`config/macro.yaml` declares the provider per series. FRED/ALFRED observations
use the same cutoff date for `realtime_start` and `realtime_end`. ECB SDMX rows
are filtered with `VALID_FROM`/`VALID_TO`. Cboe daily options statistics preserve
the selected trading date, and CFTC COT rows use a conservative seven-day delay
after the Tuesday position date because the public dataset does not expose a
reliable publication timestamp. Each observation retains its observation date,
availability period, retrieval timestamp, source URL, status, and quality.

The default configuration retrieves the effective federal funds rate, US CPI,
WTI oil, 10-year Treasury yield, VIX, US unemployment, the ECB deposit-facility
rate, Cboe total put/call ratio, and CFTC S&P 500 leveraged-money net positioning.
It exports raw values and mechanical changes. These series are risk/regime
context, not a claim that they caused a stock move. Missing values never abort
the rest of the universe.

See the official [FRED observations API](https://fred.stlouisfed.org/docs/api/fred/series_observations.html),
[real-time-period documentation](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html),
and [FRED versus ALFRED explanation](https://fred.stlouisfed.org/docs/api/fred/fred_vs_alfred.html).
Additional primary sources are the [ECB Data Portal API](https://data.ecb.europa.eu/help/api/data),
[Cboe daily market statistics](https://www.cboe.com/markets/us/options/market-statistics/daily/),
and [CFTC Commitments of Traders](https://publicreporting.cftc.gov/stories/s/r4w3-av2u).

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

`decline_severity_score` ranks only the magnitude of observed price weakness
from 0–100. It remains separate from the Phase 8 multi-factor Opportunity Score
and is not a probability of profit or a BUY/WATCH/PASS verdict.

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
src/data/               Yahoo, SEC EDGAR, FRED/ALFRED, GDELT, and ECB FX clients/caches
src/screening/          universe, returns/drawdowns, momentum, filter/ranking
src/reporting/          auditable price/fundamental/valuation/macro/shock/analogue exports
src/pipeline.py         integrated point-in-time scanner CLI
src/analysis/           fundamental, valuation, macro, shock, and analogue calculations
src/forecasting/        assumption-driven DCF and reverse DCF
src/scoring/            normalization/catalyst/risk/opportunity scoring
src/backtest/           strict validation, archives, engine, metrics, and loaders
src/ai/                 reserved critical analyst boundary
dashboard/              Phase 11 Streamlit application and testable data helpers
tests/                  offline unit and integration tests
```

Remaining reserved modules contain no hidden placeholder calculations. The
current checked/partial/deferred audits are maintained in
`docs/INTERNAL_AUDIT_PHASES_1_11.md` and the phase-specific compliance files.

## Known V1 limitations

- The shipped universe includes native European listings, but remains a current
  snapshot rather than a survivorship-free historical membership archive.
- Yahoo data can be delayed, adjusted, incomplete, unavailable, or subject to
  provider changes. V1 does not corroborate it with an exchange feed.
- Market cap is not fetched. Valuation may derive it from the point-in-time close
  and a reported SEC share count, with the formula recorded in the audit output.
- Relative performance and beta remain null unless benchmark tickers are set and
  have enough aligned observations.
- “ATH” means the maximum within the requested/downloaded history. With the
  default `max` period this attempts full provider history, but completeness still
  depends on the source.
- SEC normalization covers standard `us-gaap` and mapped `ifrs-full` annual facts
  in 10-K, 20-F, and 40-F filings. Unsupported company extensions, discrete
  quarters, and TTM calculations remain unavailable. Local-currency IFRS facts
  can feed dimensionless fundamental ratios, but valuation is rejected when the
  fact currency is not aligned with the USD-listed security price.
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
- The Temporary Shock Score uses auditable Phase 3 fundamentals, macro inputs,
  public headline metadata, and Phase 6 recovery duration/precedents when
  available. Quantified causal revenue/margin/FCF/balance-sheet impacts, detailed
  guidance, and analyst expectations stay missing rather than imputed.
- FX conversion is available through dated ECB reference rates via Frankfurter;
  it is a daily reference rate, not an executable intraday quote.
- No causal multi-company event catalogue or critical AI verdict exists yet.
  Bigdata.com and Aiera can complement filings, transcripts, events and
  consensus only when their connector tools are exposed to the active Codex
  task; missing connector evidence remains unavailable. Local alerts exist,
  while email, Telegram and Discord delivery stays deliberately disabled.
- Phase 6 compares episodes only within the same security. It does not yet search
  other companies or attach a causal crisis label. Old episodes can have price
  comparisons while fundamental/valuation context stays null because the live
  SEC history window defaults to five years.
- Phase 7 regimes are historical quartiles, not analyst consensus and not
  statistically calibrated outcome probabilities. Annual SEC facts can miss
  recent quarterly inflections; model targets can be widely dispersed when the
  historical multiple distribution is wide.
- WACC, terminal growth, and Normalized Fair Value stay null without a dated,
  sourced normalized DCF configuration.
- Phase 8 score bands and weights are deterministic research heuristics. They
  are not statistically calibrated probabilities; Catalyst can remain null when
  dated resolution evidence is absent, and missing evidence lowers both score
  and confidence.
- The Phase 9 engine is implemented, but a real 2018–2025 result is deliberately
  unavailable until dated universes including delisted names and integrity-
  checked historical signal archives are supplied. A current-survivor pilot is
  rejected as evidence, not silently backtested.
- A severe decline can be entirely rational. Ranking does not establish
  undervaluation or temporary mispricing.

## Next recommended work

Phase 12 is the final phase named in the master specification. The next work is
hardening rather than an invented Phase 13: confirm individual PEA eligibility,
expose the Bigdata.com/Aiera connector tools to the task, and supply the
survivorship-free historical inputs required to calibrate the score. See
`docs/INTERNAL_AUDIT_PHASES_1_12.md`.

## Backtesting status and required methodology

The strict Phase 9 engine is implemented in version 1.0.1. It validates
point-in-time universe membership, archive integrity, signal availability,
benchmark coverage, future outcome separation, and transaction assumptions.
No current score is statistically validated because the repository does not
contain the necessary survivorship-free 2018–2025 archives. The engine returns
`data_unavailable` instead of publishing a biased result.

## Financial disclaimer

This software is for research and education. It is not investment advice, does
not guarantee data accuracy or future returns, and does not replace independent
due diligence or a qualified financial adviser.


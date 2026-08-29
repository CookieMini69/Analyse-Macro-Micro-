# Phase 9 compliance — strict point-in-time backtesting

Version: 1.0.1
Audit date: 2026-08-29

## Implemented

- [x] Configurable 2018–2025 study window and holding period.
- [x] First-session-after-signal entry; no same-day close leakage.
- [x] Dated universe membership gate and explicit survivorship-bias rejection.
- [x] Signal availability cutoff, archive identifier, SHA-256 integrity check,
  and point-in-time validation gate.
- [x] Positive, dated, duplicate-free outcome price validation.
- [x] Per-signal regional benchmark and mandatory benchmark history.
- [x] Configurable costs on entry and exit.
- [x] CAGR, total return, hit rate, mean/median return, maximum drawdown,
  volatility, Sharpe, Sortino, recovery time, win/loss ratio, and benchmark
  comparison.
- [x] Independent 50–59, 60–69, 70–79, 80–89, and 90–100 score buckets.
- [x] Per-year results and overall equal-weight active-position portfolio.
- [x] JSON result, flat metrics CSV, and transaction-level CSV.
- [x] Write-once live universe/signal/source archives for future studies.
- [x] Historical reconstructions run today are never mislabeled as old archives.
- [x] Repeated intraday live scans select the earliest immutable daily signal;
  explicitly unavailable/incomplete provider bars are excluded before outcome
  validation, while malformed available bars still fail closed.
- [x] Synthetic unit/integration tests cover success and every critical refusal.

## Deliberately unavailable today

- [ ] A claimed 2018–2025 empirical result. The repository does not contain a
  survivorship-free historical universe, delisted names, or immutable historical
  signal/news archives. Producing a number from today's 15-name pilot would be
  misleading and is refused.
- [ ] Statistical calibration of Opportunity Score as a probability.
- [ ] Proof that a higher bucket outperforms until the required real dataset is
  supplied and the out-of-sample study is run.

## Historical-access remediation (2026-08-29)

- [x] A concrete source was selected: Sharadar Direct Bundle, 10-year history.
- [x] Required active/delisted master, historical S&P 500 membership, prices,
  as-reported fundamentals, daily multiples, corporate actions, and 8-K event
  tables are configured.
- [x] A secret-safe entitlement audit and full-history bulk downloader exist.
- [x] Every downloaded archive receives a provider/schema/SHA-256 manifest;
  tampering is rejected.
- [x] The audit cannot mark the core backtest ready merely because files exist.
- [ ] `SHARADAR_API_KEY` is not configured; no provider entitlement or real
  2018–2025 archive has therefore been validated yet.
- [ ] Dated signal reconstruction and the strict real backtest remain blocked
  until that access is supplied.

See `docs/HISTORICAL_DATA_ACCESS.md` for the exact subscription and commands.

## Verification

- Complete offline suite: 110 passed.
- Real cached-provider valuation re-audit after incomplete-bar fix: 14/15
  issuers available and 15/15 with a usable valuation close.
- Live-archive Phase 9 validation: all six integrity/anti-bias gates pass; the
  result remains explicitly unavailable because no historical holding period is
  present yet.
- Synthetic five-bucket run: all required metrics and benchmark comparison
  produced.
- Invalid future availability, missing membership, bad archive hash, absent
  benchmark, and unvalidated signal: explicit `data_unavailable` result.

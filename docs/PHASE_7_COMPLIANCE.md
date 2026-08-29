# Phase 7 compliance — scenario engine, targets, invalidation, risk/reward

Version: 0.8.0
Audit date: 2026-08-29 (post-implementation adversarial review)

## Implemented

- [x] Bear/base/bull cases for every decline candidate.
- [x] Evidence-derived lower-quartile/median/upper-quartile regimes; no arbitrary
  target-price uplift or discretionary scenario haircut.
- [x] Explicit revenue-growth, operating/net/EBITDA/FCF-margin, share-count,
  multiple, debt, cash, WACC, and terminal-growth assumption records.
- [x] Explicit latest point-in-time SEC EPS and FCF basis records, including a
  documented net-income/share derivation when reported diluted EPS is absent.
- [x] Real assumption counts, periods, SEC accessions, formulas, URLs, derivation,
  unit, availability status, and missing-data reason.
- [x] 3M, 6M, 12M, 18M, and 24M projections for revenue, margin, EPS, FCF, and
  model-derived target price.
- [x] P/E, EV/EBITDA, and P/FCF target methods calculated independently.
- [x] Median aggregation of available positive model values with a configurable
  minimum model count.
- [x] Fair Value, Bear/Base/Bull targets, and model-derived TP1/TP2/TP3.
- [x] Normalized Fair Value is emitted only from a dated sourced normalized DCF;
  no generic temporal target is mislabeled as shock normalization.
- [x] Sourced base DCF takes precedence for Fair Value; Normalized Fair Value
  requires its own configured DCF eligible at `as_of`; no implicit WACC or
  terminal growth.
- [x] Fundamental invalidations for revenue growth, operating margin, FCF margin,
  and net-debt/EBITDA.
- [x] Missing guidance, order-book, and market-share invalidation dimensions stay
  explicit instead of receiving fabricated thresholds.
- [x] Base upside, bull upside, bear downside, and risk/reward arithmetic.
- [x] Risk/reward remains unavailable unless base upside is positive and bear
  downside is negative.
- [x] Candidate-row enrichment plus full cutoff-versioned JSON and timestamped
  45-row CSV for the three-candidate real smoke run.
- [x] Same shared point-in-time cutoff as prices, SEC, valuation, macro, news,
  shock, and analogues.
- [x] Defensive rejection of standalone fundamental or valuation evidence whose
  analysis timestamp postdates the requested scenario cutoff.
- [x] FRED key remains local and was never added to Git or report provenance.

## Deliberately not claimed

- [ ] Bear/base/bull are probabilities or analyst-consensus estimates.
- [ ] A target is statistically validated before the Phase 9 backtest.
- [ ] A historical quartile captures every future regime or quarterly inflection.
- [ ] WACC or terminal growth can be inferred without a dated, sourced model.
- [ ] Guidance, order-book, or market-share invalidation can be measured without
  an eligible point-in-time source.
- [ ] Risk/reward is an investment recommendation.

## Verification result

- Offline regression, audit, Phase 7, and Phase 8 tests: 87 passed.
- Real providers: SEC 15/15, FRED 6/6, price histories 16/16, valuation 14/15.
- Real candidate outputs: historical analogues 3/3, scenarios 3/3, 45 scenario
  horizon rows.
- GDELT timeouts remained isolated and did not interrupt other stages.

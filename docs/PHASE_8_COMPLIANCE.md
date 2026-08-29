# Phase 8 compliance — coverage-aware scoring

Version: 1.0.0
Audit date: 2026-08-29

## Implemented

- [x] Fundamental Quality Score `/100`, preserved from the audited SEC engine.
- [x] Valuation Score `/100`, preserved from the audited valuation engine.
- [x] Temporary Shock Score `/100`, preserved from the conservative shock engine.
- [x] Normalization Score `/100` from model gap, analogue outcomes/recovery, and
  shock-resolution evidence; explicitly not a probability.
- [x] Catalyst Score `/100` only from dated resolution language and eligible
  configured macro relief; missing evidence remains null.
- [x] Future Growth Score `/100` from the SEC growth pillar required by the
  master-specification weighting proposal.
- [x] Risk Resilience Score `/100` from balance sheet, bear target, volatility,
  beta, and structural shock evidence; higher means lower measured risk.
- [x] Temporary Mispricing Opportunity Score `/100` with weights
  `20/20/15/15/10/10/10` exactly matching the initial specification proposal.
- [x] Config validation rejects weights that do not sum to 100%.
- [x] Missing inputs contribute zero weight, reduce evidence coverage/confidence,
  and are never imputed as a neutral score.
- [x] Minimum 50% top-level coverage before an Opportunity Score is available.
- [x] Confidence Score is weighted evidence coverage `/100`, not return confidence.
- [x] Data Quality is kept separate; weak coverage cannot be presented as high
  conviction merely because a numerical score is high.
- [x] Candidate ranking uses Opportunity Score, then decline severity as a
  tie/fallback signal.
- [x] Full per-company JSON plus timestamped CSV and main Excel/CSV columns.
- [x] Shared `as_of` cutoff and defensive exclusion of future-dated stage results.
- [x] Score bands are descriptive and never use BUY/SELL wording.

## Deliberately not claimed

- [ ] Opportunity Score is a probability of profit or normalization.
- [ ] Confidence Score is statistical forecast confidence.
- [ ] A HIGH_SCORE is a recommendation or investment verdict.
- [ ] Catalyst absence in indexed headlines proves that no catalyst exists.
- [ ] Historical similarity establishes causal equivalence.
- [x] A strict Phase 9 engine exists to test the score weights once valid
  historical archives are supplied.

## Verification result

- Offline unit/integration/audit tests: 103 passed.
- Project environment dependency check: no broken requirements.
- Real providers: SEC 15/15, FRED 6/6, price histories 16/16, valuation 14/15.
- Real candidate outputs: historical analogues 3/3, scenarios 3/3, coverage-
  qualified Opportunity Scores 3/3.
- Real score ranking: META 53.78 (confidence coverage 63.80, LOW quality), CAT
  38.49 (79.10, MEDIUM), WMT 32.62 (78.55, MEDIUM).
- GDELT timeout/partial evidence remained isolated; unavailable shock/catalyst
  inputs reduced score and confidence rather than being imputed.

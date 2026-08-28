# Phase 6 compliance — historical analogues

Version: 0.7.0
Audit date: 2026-08-28

## Implemented

- [x] Detect threshold-crossing peak–trough drawdowns from the cutoff-filtered
  daily price path.
- [x] Separate completed historical episodes from the active episode.
- [x] Require recovery to the prior peak by default; expose a validated optional
  tolerance in configuration.
- [x] Compare maximum drawdown and calendar-day decline duration.
- [x] Report trough-to-recovery and full peak-to-recovery durations.
- [x] Report 3, 6, 12, and 24-month returns from each historical trough.
- [x] Leave a subsequent return null when its horizon lies beyond `as_of`.
- [x] Re-filter SEC facts on their real `available_at` timestamp at every
  episode peak and rerun the fundamental calculations from that subset.
- [x] Retain filing accessions, URLs, formulas, periods, and availability dates.
- [x] Select historical valuation multiples only when their public availability
  and price date both precede the episode cutoff.
- [x] Rank analogues with an explicit component formula and separate coverage.
- [x] Analyze candidates only, avoiding unnecessary downstream work.
- [x] Export cutoff-versioned per-ticker JSON and a timestamped comparison CSV.
- [x] Enrich the main CSV/Excel rows with analogue status, count, best similarity,
  and the complete nested audit detail.
- [x] Keep the shared pipeline cutoff across price, SEC, valuation, macro, news,
  shock, and analogue stages.
- [x] Test completed/current episode separation, recovery, future-horizon
  unavailability, SEC publication cutoff, not-applicable behavior, pipeline
  integration, compilation, and the full regression suite.

## Deliberately not claimed

- [ ] A similar price path proves a similar causal shock.
- [ ] Same-security analogues are equivalent to cross-company or market-regime
  analogues.
- [ ] The similarity index is a probability of recovery or future return.
- [ ] A named event such as COVID, 2008, inflation, energy, or geopolitics can be
  attached without dated primary evidence.
- [ ] Current Company Facts alone creates a fully correction-proof historical
  archive; daily raw snapshots remain required for strict production backtests.

## Similarity formula

Available-component weighted mean:

- maximum drawdown similarity: 35%;
- decline-duration similarity: 20%;
- point-in-time fundamental-ratio similarity: 25%;
- point-in-time positive-multiple similarity: 20%.

Missing context is not imputed. `similarity_coverage` is the sum of the weights
actually observed; price-path-only comparisons therefore expose 55% coverage.
The result is an analytical index from 0 to 100, never a normalization
probability or investment recommendation.

## Verification result

`python -m pytest -q`: 73 tests passed on 2026-08-28.

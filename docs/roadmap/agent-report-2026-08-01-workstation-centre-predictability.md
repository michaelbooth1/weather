# Workstation centre-predictability estimate — 2026-08-01

## Verdict

**Centre correction is worth engineering as a measured, market-and-hour-
conditioned research candidate, but this experiment does not authorize a
production candidate.** A per-market × capture-hour offset recovered **49.06%**
of the accepted 74.97% severe-tail centre ceiling out of sample. It reduced
pooled aggregate positive excess Brier by **3.72%**, reduced fixed-tail positive
excess by **36.78%**, improved that tail on all four test dates, and reduced
severe rows from 3,893 to 2,980.

That result is materially conditional. The simpler per-market constant failed:
it increased aggregate positive excess by 63.31% and tail positive excess by
6.23%. The hour-conditioned rung also made total model Brier worse by a small
`0.001972` despite passing the two requested positive-excess gates. July 22–30
is heavily inspected development evidence, not a clean holdout. Engineering is
therefore justified only with a full-Brier non-regression check and later
confirmation on the untouched forward window; shipment is not justified.

The feature-conditioned rung was **not run**. The predeclared rule required
both simpler rungs to pass before it could unlock. Because the per-market
constant failed, no feature fit, ridge selection, test score, coefficient, or
second pass exists.

## Source, run root, and leakage declaration

| Field | Frozen value |
| :--- | :--- |
| Source | exact `origin/master` `0948d03ebed4538da0958cf054398f92fc22727f` |
| Topic branch | `codex/workstation-centre-predictability-2026-08-05a` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\centre-predictability-2026-08-05a` |
| Declaration time | `2026-08-01T21:44:20Z`, before any fit or test evaluation |
| Fit window | 2026-07-22 through 2026-07-26, inclusive |
| One-time chronological test | 2026-07-27 through 2026-07-30, inclusive |
| Untouched confirmation window | **2026-08-06 through 2026-08-19, inclusive; not read or evaluated** |
| Fit scale | 10,885 snapshots; 60 market-days |
| Test scale | 8,380 snapshots; 48 market-days |
| Input | accepted post-`rows[-1]` current-serving replay from `disagreement-map-2026-08-03a` |
| Input SHA-256 | `bc1d4e80d65c98274be6d976ead97a391467124304fba14081e47a11aee5b2e8` |

The declaration was written and hashed before fitting. There was one test run,
from `2026-08-01T21:49:37Z` to `21:50:29Z`; it completed successfully and was
not rerun. No test result changed the split, predictor definitions, correction,
metric membership, gate, ceiling denominator, or feature-rung unlock rule.

The fit target was normalized-market expected ordered-band index minus current-
model expected ordered-band index. Market price was a retrospective training
label component and evaluation benchmark only, never an input predictor.
Settlement outcome was used only for frozen test scoring and the explicitly
invalid oracle diagnostic. Rungs 1 and 2 used only market identity and capture
hour, both known at cutoff. They used no outcome, post-cutoff observation,
market price, target-date encoding, future source state, or weather feature.

July 22–30 was already used to derive the disagreement geometry and centre
ceiling. The chronological split measures generalization of these frozen fitted
instruments across dates, but it remains optimistic and is **not an independent
forward holdout**. The nominated August 6–19 window remains clean for a later,
separately authorized confirmation; it must not be replaced after seeing these
results.

## Frozen ladder and pooled result

Positive reductions are improvements. Recovery is the fixed-tail reduction
share divided by the accepted full-window centre ceiling
`0.7497135767583245`.

| Rung | Aggregate positive excess, baseline → corrected | Aggregate reduction | Fixed ≥30-point tail, baseline → corrected | Tail reduction | Recovery of 74.97% ceiling | Severe rows, baseline → corrected | Gate |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| Per-market constant | 1.219155 → 1.990998 | **−0.771844 (−63.31%)** | 0.728976 → 0.774360 | **−0.045384 (−6.23%)** | **−8.30%** | 3,893 → 5,353 | **FAIL** |
| Per-market × hour | 1.219155 → 1.173783 | **+0.045372 (+3.72%)** | 0.728976 → 0.460844 | **+0.268132 (+36.78%)** | **49.06%** | 3,893 → 2,980 | **PASS** |
| Cutoff-feature-conditioned | — | — | — | — | — | — | **LOCKED; not run** |

The requested gate required lower pooled aggregate positive excess, lower
pooled fixed-tail positive excess, and no increase in severe-row count. The
hour-conditioned rung passed all three. The constant failed both Brier
directions and increased severe rows.

The fitted displacement itself was much more predictable with hour
conditioning: test target correlation increased from `0.2838` to `0.6707`, and
RMSE fell from `0.7396` to `0.6207` ordered bands. This supports the earlier
finding that the centre mechanism changes through the day and rejects a single
market-only correction.

## Date stability

Each cell is the daily-normalized reduction in positive excess Brier; positive
is better. The tail membership is the frozen original ≥30-point set.

| Test date | Constant aggregate | Constant tail | Market × hour aggregate | Market × hour tail |
| :--- | ---: | ---: | ---: | ---: |
| 2026-07-27 | −0.177270 | −0.012591 | **+0.033342** | **+0.058625** |
| 2026-07-28 | −0.166005 | −0.005757 | **−0.026904** | **+0.070538** |
| 2026-07-29 | −0.257676 | −0.000245 | **+0.018664** | **+0.042090** |
| 2026-07-30 | −0.170893 | −0.026791 | **+0.020271** | **+0.096879** |

The constant lost on aggregate and tail on every date. Market × hour improved
the tail on all four dates and aggregate positive excess on three; July 28 is
the aggregate exception. This is better than a one-date pooled artifact, but
four already-inspected test dates are too few to establish operational
stability.

## Safety and feasibility diagnostics

The frozen application moved the model expected band index by the predicted
offset using an exponential tilt, then restored the model's original entropy.
If the requested centre/entropy pair was infeasible on the fixed 11-band
support, the snapshot remained unchanged. No outcome-aware application
selector was used.

| Diagnostic | Per-market constant | Per-market × hour |
| :--- | ---: | ---: |
| Exact corrections | 7,794 / 8,380 | 8,027 / 8,380 |
| Infeasible and unchanged | 586 | 353 |
| Support-clipped requests | 42 | 0 |
| New severe rows | 2,582 | 1,065 |
| Severe rows after | 5,353 | 2,980 |
| Total model Brier, baseline → corrected | 2.521446 → 3.235291 | 2.521446 → 2.523419 |
| Net total-model-Brier reduction | **−0.713845** | **−0.001972** |

Exact applications matched requested means within `4e-15` ordered bands and
restored entropy to recorded precision. The hour-conditioned rung repairs more
severe rows than it creates, but 1,065 new severe rows and the slight total-
Brier regression are real warnings. The positive-excess gates answer the
mission as specified; they do not erase those broader costs.

For scale only, a separate outcome-aware strict centre oracle on these test
dates reduced the frozen tail by 72.78%. The hour-conditioned rung captures
50.54% of that test-specific oracle, consistent with its primary 49.06% share
of the accepted 74.97% ceiling. That oracle used the realized outcome to choose
whether to correct each snapshot and is permanently invalid as candidate,
gate, promotion, or release evidence.

## Engineering disposition

Do not engineer or ship a per-market constant and do not revive a global centre
shift. The achievable signal is time-conditioned. After release #1, a research
candidate is justified if it:

- preserves the market × hour baseline as an auditable comparator;
- adds total Brier and new-severe-row protections to the requested aggregate-
  positive and fixed-tail gates;
- uses cutoff-available weather signals with explicit train/serve parity;
- makes no tuning decision from July 27–30; and
- is evaluated once on August 6–19 only after that window closes and its
  completeness is declared without inspecting outcomes.

This experiment does not itself justify feature engineering under its frozen
ladder: rung 3 correctly stayed locked. A later mission may define a new
leakage-safe experiment, but these test scores must not be used to tune it.

## Machine-readable evidence and guardrails

All generated evidence is under the one declared run root outside the mirror:

- `split-declaration.md` — frozen split, predictors, gate, application, and
  untouched window; SHA-256
  `b0c29393c1a95699489f069fedb975556713888ee08e1e2d34e64bb835ca4469`.
- `measure_centre_predictability.py` — one-shot fitting and evaluation
  instrument; SHA-256
  `002875d89c48e6c608ffce2b6516669f73e1829a93a0f5ffd30be92f7d7945a1`.
- `centre-predictability-analysis.json` — full run summary; SHA-256
  `3ba0aed1d711d3d0eea65a51b9cf2e818bda3c24bde03de3fef9fdec663c179f`.
- `rung-results.csv` — pooled ladder results; SHA-256
  `a0ae1fc9381c138c5a0eee1a5a10a077b4156adf9ab68c64beebed91001d477d`.
- `per-date-results.csv` — date-level gate audit; SHA-256
  `0f97a23b0827f43817f073d55b194ae9b9ff42a01dbd94df436de657b5e2c952`.
- `test-snapshot-predictions.csv` — 16,760 rung/snapshot decisions; SHA-256
  `8332886b39f93e3aed9680c2673bde21906323e7db9993ffcaef7aee7e474e3a`.
- `fitted-offsets.csv` — fit-only constant and market/hour instruments;
  SHA-256
  `1596c293ae316c97005a14f82e12dd9c6bd0440a047ed045703ce026253f9042`.
- `validation-summary.json` — independent row/date/gate/hash re-derivation;
  SHA-256
  `1ad82b2665d37653d28a56e5cd1fec4efcd42c18b4ed0783bd1de5b5fe96034c`.

The independent validator passed: it reasserted the exact fit/test dates,
8,380 unique test snapshots per rung, 8 per-date rows, pooled reductions from
the date rows, feasibility and severe-row counts from snapshot decisions,
recovery arithmetic, the feature-rung lock, absence of feature-fit artifacts,
input/script/declaration hashes, and non-use of the untouched window.

`data/` and the mirror remained read-only. No production artifact, serving
change, transform, candidate shipment, PR, merge, master push, promotion,
pointer, scheduler, capture, mirror, or ACL change occurred. No sync credential
was read or exposed.

# Missing-information descriptive checks

Offline research for mission `2026-09-79a`. This is preparation for measurement;
synthetic tests do not establish a market result. The frozen source is
[`missing-information-test-plan-2026-09-21.md`](../../../docs/research/missing-information-test-plan-2026-09-21.md).
The production-host handoff supplied by the owner overrides its illustrative
host timetable, extraction language, transfer location and sampled book dates.

The guarded driver implements archive verification/extraction and checks 1, 2,
4a and 5. Check 3 is conditional on P0 and remains pending; the actual snapshot
artifact trace (4b) and conditional IEM guidance retrieval (4c) require the
production corpus. Do not describe this preparation as a completed mission.

## Execution

Run from this worktree with its exact `scripts/ops/workstation_heavy.ps1`, kind
`weather_heavy`, the project Python, and a base64 JSON argument array:

```text
["-m","tools.research.missing_information.run","preflight"]
["-m","tools.research.missing_information.run","prepare","--input","<absolute-scratch>/downloads","--output","<absolute-scratch>/unpacked"]
["-m","tools.research.missing_information.run","extract","--input","<absolute-scratch>/unpacked","--output","<absolute-scratch>/extracted"]
["-m","tools.research.missing_information.run","analyze","--input","<absolute-scratch>/extracted","--output","<absolute-scratch>/analysis","--iem","<absolute-scratch>/iem"]
```

`prepare` requires `MANIFEST.json` and all three handoff `.tgz` files. It verifies
every SHA-256 before unpacking, refuses path traversal, links, overwrite and
excess expansion, and records a receipt. Use new output directories per attempt;
partial files are retained on failure. The driver checks the frozen plan hash
and writes an output header before reading the analysis inputs. Its research
stages have no network or exchange paths.

The separate light downloader is `python -m tools.research.missing_information.fetch_iem --output <absolute-scratch>/iem`.
It requests routine and special reports separately from the official
[IEM ASOS endpoint](https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?help),
waits at least 1.1 seconds between requests and records URLs, hashes and report
types. Its date padding covers each market's local target-day boundary. It
never treats retrospective IEM observations as values our model had captured.

## Estimands and limitations recorded before the first full run

- Captured temperatures and guidance are already in native settlement units;
  `_c` is a legacy suffix. The code trace is
  `SnapshotStore.source_values` through `row_*_native` and `MarketSpec.unit`.
  The plan's wording to convert these from Celsius is inapplicable. IEM `tmpf`
  and `dwpf` are Fahrenheit and need conversion when used for Celsius deltas.
- Capture rows must fall on their local target date. Missing probabilities,
  duplicate/overlapping bands, conflicting feature records, or invalid model
  mass cannot become an admitted score. Every excluded folder and snapshot
  reason is retained; the filter is exactly boolean `promotion_countable`.
- Brier is the mean binary score across the complete band support per snapshot.
  Snapshot scores collapse to hour cells and then to market-days, equally
  weighted. Raw `market_yes` is primary; normalized market probabilities are a
  sensitivity. The two settlement-source strata remain separate.
- Hour windows are half-open: 06–10 means hours 6 through 9; 13–17 means hours
  13 through 16. Guidance buckets are [00,10), [10,13), [13,17), [17,24).
  The plan's overlapping endpoint notation must be accompanied by an
  inclusive-hour sensitivity before interpreting any boundary-dependent result.
- The primary peak is the first time the captured station maximum equals its
  final available value. The extraction also retains the monotone-envelope
  alternative, decreases and final capture time. It cannot prove the true daily
  peak if the captured series stops early. Pre-07:00 `max_since_7am` may describe
  yesterday; report a target-day-safe sensitivity before calling it a floor
  failure. Neither missing future follow-up nor a missing station max is zero.
- Lag IQRs are empirical dispersion among resolved pairs, not confidence
  intervals. Unresolved pairs are explicitly censored; do not interpret the
  resolved-only median as the full-panel lag. Crossed median/censoring intervals
  remain required before publication of a lag claim.
- Tail snapshots are ranked by excess; their contribution is weighted by the
  number of captures in the hour. The raw-cadence selection is retained as a
  sensitivity. Tail days use summed hour-cell excess. Signed excess is not
  clipped. Odds-ratio intervals condition on the descriptive tail classification;
  a predictive tail claim requires a prospective label and new design.
- NBM CDFs join linear quantile knots to continuous scaled normal tails and
  preserve probability mass. Mean/stddev must be finite and stddev positive;
  report percentile fill separately from full CDF-field fill. Invalid guidance
  is excluded from paired comparisons and cannot become a climatology fallback.
- Point-guidance residual kernels use at least five **earlier** dates in the
  same market, stratum and bucket, one residual per date. This is the explicitly
  authorized diagnostic kernel, not a new forecasting model or candidate.
- Weather tags use the thresholds in the plan. The underspecified pressure-rise
  condition means a positive change; the coastal-stratus proxy means BKN/OVC/VV
  below 5,000 feet during 06–10 local at a coastal market. Held continuous
  disagreement/spread tags use >2 Celsius-equivalent degrees. These conventions
  require sensitivity analysis before a tag can select a follow-on feature.
- Crossed date × market resampling uses 2,000 independent multinomial draws on
  each axis. Descriptive 95% intervals and 80%-power MDE use the centered
  bootstrap distribution. Power is for prespecified effects, never the observed
  effect. These are exploratory calculations; there is no alpha-ledger entry.
- Market movement before METAR/SPECI would not uniquely establish a private paid
  feed or an unclosable gap. Guidance-bust association does not establish that
  nobody knew pre-day. Report the frozen reading alongside these identification
  limits. Candidate E (trader identity) has no test in this plan and is untested.

The owner authorized adding only the exact driver module to the PowerShell
admission allowlist and matching Codex-hook allowlist, with validation tests.
Host identity, principal, shared mutex, Job containment, poison recovery, live
argument rejection and cleanup are unchanged. This change is local research
authority, not production adoption or a hook installation.

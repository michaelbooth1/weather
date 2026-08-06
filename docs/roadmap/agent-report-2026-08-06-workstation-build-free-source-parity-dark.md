# Workstation free-source feature parity dark build - 2026-08-06

## Verdict

**BUILD COMPLETE, DARK BY DEFAULT, AND PARTIALLY FALSIFIED AS FULL PARITY.** The
flag-off path is byte-identical to refreshed `origin/master` across all 2,868
captured feature envelopes. With the flag on, the predeclared severe set falls
from `737.065190` to `688.590985` squared error: a **6.58% reduction**, crossed
date x market 95% interval **[0.49%, 14.14%]**, effective support **D=5,
M=12**. That interval does not cross zero, and the old `12.77%` oracle point is
inside it, but the realized point is materially smaller.

This is not evidence for a fleet-wide retrain or activation. The pooled
daily-first control-minus-flag-on Brier estimate is `-0.003802`, crossed 95%
interval `[-0.037219, +0.025389]`, **D=5, M=12**. **That interval crosses
zero.** The excluded severe lane improves by `7.83%`, but its crossed interval
is `[-1.02%, 17.04%]`, **D=5, M=12**, and **that interval crosses zero**. The
frozen replay could validate only the METAR portion because every available
Toronto ECCC raw-payload receipt failed its pinned payload hash. The correct
result is therefore a useful partial free-source path shipped dark, not a claim
that the `-08-22a` full/oracle restoration was reproduced.

Implementation commit: `3e1f29dc` (`feat: add dark free-source feature parity`)
on branch
`codex/workstation-build-free-source-parity-dark-2026-09-22a`.

## Scope, reservation, and provenance

- Refreshed base: `origin/master` at
  `fbb729bb22c70b3267e1afa002dabb013833dea7`, newer than the required
  `e8022335` floor.
- `docs/operations/reserved-confirmation-window.md` was checked again before
  the final evaluation. It says **NONE ARE CURRENTLY RESERVED**. The run used
  only the frozen July 22-26 development corpus and hours 09:00-14:00.
- I accepted the `-08-20a` and `-08-22a` blindness findings as established. I
  did not re-measure the blindness, change its interpretation, or construct a
  fleet-wide retrain case.
- Frozen manifest SHA256:
  `8cf0d01d222172dadd024b3e55a69494860477785ec100cbe8ae2ed546c1662d`.
  Frozen replay-row SHA256:
  `55fd5104d7aa8240a9714d368ab15dd9bda34d87c4da27d7025b6cdb7c8e9ccd`.
  Frozen floor-trace SHA256:
  `2e9da6e324130494760cd6b2dbe632658f6b29b99615439bab66fa1141519c9b`.
  These are integrity identities, not effect estimates, so date/market
  clustering is not applicable.
- Positive control: all 2,868 captured snapshots replayed, **D=5, M=12**;
  maximum absolute incumbent band-probability error was exactly `0.0`. The
  frozen eligible population was 2,855 snapshots, **D=5, M=12**, with 1,545
  predeclared severe band rows and control squared error `737.065190`, **D=5,
  M=12**. These reproduce the frozen `-08-22a` control population.

## What was built

`WEATHER_FREE_SOURCE_FEATURE_PARITY` is the only activation switch. Unset,
empty, `0`, and unknown values are off; only explicit `1`, `true`, `yes`, or
`on` values enter the new path. The flag is documented as research-only and
must not be enabled in production before the release lock and a separate
activation decision.

The path consumes only the `raw_payload` already present inside a captured
free-source envelope. It performs no fetch and no disk read. Toronto uses one
ECCC SWOB record family when a valid SWOB row exists and otherwise falls back
to METAR. Other markets use METAR. It never combines an ECCC baseline with a
METAR current row, and a present-but-missing field in the chosen source remains
missing rather than being filled from another provider.

The point-in-time guards require a successful non-stale source envelope, a
timezone-aware fetch receipt no later than capture, the exact configured ICAO,
the target local date, observation and receipt times no later than capture, and
an observation no later than the effective cutoff. Invalid time, station,
date, source state, unit, or code fails closed.

### Field semantics

| Feature family | Free-source implementation | Training-semantics verdict |
| --- | --- | --- |
| `rise_from_7am`, `warming_rate_2h`, `hours_at_peak` | Reuses the historical closest-row windows and first-high formula on one cutoff-admitted source. METAR/SWOB Celsius is converted once to the market's native settlement unit. | Populated when the same formula has sufficient same-source rows; otherwise absent. Source cadence remains a real difference from WU, so this is not called observational identity. |
| `dewpoint_c` | METAR `dewp` or SWOB `dwpt_temp`; Celsius converted once to native F for U.S. artifacts and retained as C for Toronto. | Direct observed dew point; legacy `_c` name does not change the artifact-era native-unit contract. |
| `humidity` | Direct SWOB `rel_hum` only. | Toronto-only when SWOB is valid. METAR RH is not derived from temperature/dew point and stays absent. |
| `pressure`, `pressure_trend_3h` | SWOB `stn_pres` in hPa and the same-field three-hour difference. | Toronto-only. METAR altimeter/SLP is not substituted for WU station pressure, so U.S. pressure and trend stay absent. |
| `wind_speed_kmh`, `wind_gust_kmh` | SWOB km/h in Toronto; METAR knots converted to mph for the U.S. artifact lanes. | Preserves the misleading legacy artifact units rather than passing raw knots or forcing km/h. |
| `wind_group`, `wind_shift_3h_degrees` | Direct degrees mapped to the same 16-point cardinal groups; calm/variable and missing direction remain explicit or absent. | Same categorical grouping and circular shift formula as historical reconstruction. |
| `cloud_group` | METAR weather and known sky-cover codes; known SWOB present-weather/cloud-amount codes; `SKC` normalized to training clear semantics. | Recognized codes map through the existing model grouping. Unknown codes stay absent rather than becoming a confident `Other`. |

The unit and field choices follow the public
[Aviation Weather METAR documentation](https://aviationweather.gov/help/data/)
and the
[ECCC SWOB open-data guide](https://eccc-msc.github.io/open-data/msc-data/obs_station/readme_obs_insitu_swobdatamart_en/).
WU remains disabled. No paid provider, paid tier, credential, or new endpoint
was added.

## Dark-off byte proof

This was compared across two checkouts, not merely between two settings on the
new branch:

| Checkout and setting | Captured rows | Aggregate canonical feature-byte SHA256 | Support |
| --- | ---: | --- | --- |
| Base `fbb729bb`, existing behavior | 2,868 | `dc184d83164aa2c754820009cae1c52f895acb104bf97fba1455c475905a2bb8` | D=5, M=12 |
| Implementation `3e1f29dc`, flag unset/off | 2,868 | `dc184d83164aa2c754820009cae1c52f895acb104bf97fba1455c475905a2bb8` | D=5, M=12 |

Every row matched. The first captured row hash was
`32a3aaf472daaa0f530d837900a3f9350143be4555567228c7d6fdcf31d068cb`
and the last was
`9a20a56968fa5f66d3446682676353d8d44ea8e072812a833e489967a6b6ab95`;
these are integrity facts rather than statistical estimates. A unit test also
patches the flag-on builder to raise if the default-off served path enters it,
then compares canonical serialized feature bytes.

**Darkness acceptance passes.** The new import has no activation side effect,
and the guarded block is not evaluated when the flag is off.

## Flag-on severe-tail result

The severe rule was copied without tuning from `-08-22a` and evaluated on its
frozen control/blind arm:

```text
positive model-minus-market squared-error excess
AND abs(model_probability - market_probability) >= 0.30
```

Intervals are 2,000-replicate crossed date x market pigeonhole ratio
bootstraps. `D` and `M` are the effective date and market cluster counts for
every estimate in the row.

| Lane | Control SSE | Flag-on SSE | Reduction | Crossed 95% interval | Effective support | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| All severe | 737.065190 | 688.590985 | **6.5767%** / 48.474204 SSE | **[0.4898%, 14.1445%]** | D=5, M=12; 55 market-days; 1,041 snapshots; 1,545 band rows | Interval does not cross zero. |
| Excluded lane | 434.348864 | 400.333809 | **7.8313%** / 34.015055 SSE | **[-1.0164%, 17.0440%]** | D=5, M=12; 50 market-days; 678 snapshots; 919 band rows | **The interval crosses zero.** |
| Qualified lane | 302.716326 | 288.257176 | **4.7765%** / 14.459150 SSE | **[-17.3569%, 12.4958%]** | D=5, M=7; 17 market-days; 363 snapshots; 626 band rows | **The interval crosses zero.** |

The all-severe result is interval-consistent with `-08-22a`'s `12.77%`, but
its point is about half as large. The excluded-lane `15.23%` oracle point also
falls inside this run's interval, but this run does not reproduce the old
clear-of-zero excluded-lane result. This is exactly the partial-equivalence
finding that the handoff said must not be tuned away.

## Pooled effect and centre guardrail

Daily-first control-minus-flag-on Brier is `-0.003802`, crossed 95% interval
`[-0.037219, +0.025389]`, **D=5, M=12, 60 market-days**. Positive would favor
flag-on; the point is negative. **The interval crosses zero**, so this is not a
distinguishable pooled movement and does not justify a fleet-wide retrain or
activation.

The excluded-lane centre delta, flag-on minus control, is `+0.019592` bands,
crossed 95% interval `[-0.025282, +0.066920]`, **D=5, M=12, 56 market-days**.
**The interval crosses zero.** There is no distinguishable centre movement,
so this does not contradict `-08-22a`'s finding that blindness is not the cool
centre mechanism.

## Per-hour heterogeneity

The metric is daily-first control-minus-flag-on Brier. Every interval below is
crossed date x market; every row has effective **D=5, M=12**.

| Hour | Point | Crossed 95% interval | Market-days | Interpretation |
| ---: | ---: | ---: | ---: | --- |
| 09 | -0.007161 | [-0.069981, +0.052901] | 60 | The interval crosses zero. |
| 10 | +0.003803 | [-0.041189, +0.056279] | 60 | The interval crosses zero. |
| 11 | +0.009059 | [-0.064452, +0.073157] | 60 | The interval crosses zero. |
| 12 | +0.000604 | [-0.066860, +0.061609] | 60 | The interval crosses zero. |
| 13 | -0.021656 | [-0.126091, +0.079744] | 59 | The interval crosses zero. |
| 14 | -0.014068 | [-0.087861, +0.050762] | 59 | The interval crosses zero. |

The repair inherits the previously established hour heterogeneity; no hour is
distinguishable from zero in this five-date corpus.

## Per-market heterogeneity

The metric is daily-first control-minus-flag-on Brier. Each row has effective
**D=5, M=1, five market-days**. The market dimension is necessarily degenerate
at `M=1`, so these are descriptive market slices, not fleet-grade crossed
inference.

| Market | Point | Crossed 95% interval | Interpretation |
| --- | ---: | ---: | --- |
| Atlanta | +0.026481 | [-0.017025, +0.078508] | The interval crosses zero. |
| Austin | +0.073180 | [+0.016935, +0.137391] | Interval does not cross zero. |
| Chicago | -0.018786 | [-0.066580, +0.021846] | The interval crosses zero. |
| Dallas | +0.042886 | [+0.000357, +0.089648] | Interval does not cross zero. |
| Denver | +0.003949 | [-0.033738, +0.043929] | The interval crosses zero. |
| Houston | -0.011503 | [-0.046972, +0.026242] | The interval crosses zero. |
| Los Angeles | +0.043240 | [+0.002371, +0.070600] | Interval does not cross zero. |
| Miami | +0.002206 | [-0.017038, +0.023241] | The interval crosses zero. |
| NYC | -0.014469 | [-0.071419, +0.042481] | The interval crosses zero. |
| San Francisco | -0.033042 | [-0.067375, -0.005872] | Interval does not cross zero. |
| Seattle | -0.055509 | [-0.175241, +0.027668] | The interval crosses zero. |
| Toronto | -0.104259 | [-0.206023, -0.011143] | Interval does not cross zero. |

Five markets have negative points, including NYC and Toronto, as `-08-22a`
led us to expect. This is heterogeneity to preserve, not average away.

## Population and frozen-payload limit

Population is reported on the 2,855 frozen eligible snapshots. Each nonzero
row below has **D=5, M=12, 60 market-days**. Zero rows have no populated
date/market cluster, so their effective populated support is **D=0, M=0**.

| Field | Present / eligible | Population | Effective populated support |
| --- | ---: | ---: | --- |
| `rise_from_7am` | 2,839 / 2,855 | 99.44% | D=5, M=12 |
| `warming_rate_2h` | 2,829 / 2,855 | 99.09% | D=5, M=12 |
| `hours_at_peak` | 2,843 / 2,855 | 99.58% | D=5, M=12 |
| `dewpoint_c` | 2,843 / 2,855 | 99.58% | D=5, M=12 |
| `humidity` | 0 / 2,855 | 0.00% | D=0, M=0 |
| `pressure` | 0 / 2,855 | 0.00% | D=0, M=0 |
| `pressure_trend_3h` | 0 / 2,855 | 0.00% | D=0, M=0 |
| `wind_speed_kmh` | 2,843 / 2,855 | 99.58% | D=5, M=12 |
| `wind_group` | 2,843 / 2,855 | 99.58% | D=5, M=12 |
| `cloud_group` | 2,843 / 2,855 | 99.58% | D=5, M=12 |

All 2,868 METAR snapshot-source payloads hydrated and passed their content
hashes, **D=5, M=12**. All 254 available Toronto ECCC snapshot-source receipts
were rejected because the local payload bytes did not reproduce their pinned
canonical hashes. The ECCC count is an integrity receipt, not an estimated
effect (clustering not applicable). The evaluator did not decode or use those
bytes and fell back to METAR. Consequently the frozen flag-on result contains
no humidity or pressure population and cannot be described as a full
METAR/ECCC restoration. Deterministic tests establish valid ECCC direct-field,
unit, cutoff, source-order, and no-splicing behavior, but tests do not replace
empirical ECCC replay evidence.

## Roll-closure verdict

Retained runtime-identity receipts, not source globs, produce this verdict:

| Changed file | Retained closure evidence | Roll verdict |
| --- | --- | --- |
| `src/weather/model/model_features.py` | Present in snapshot loop receipt (77 files, captured `2026-08-05T05:18:17.776939Z`) and observation-trigger receipt (85 files, captured `2026-08-05T08:30:30.662911Z`); absent from CLOB and CLOB-enrichment receipts. | **Roll-sensitive:** snapshot and observation-trigger. |
| `src/weather/model/free_source_feature_parity.py` | New direct import of `model_features.py`; it enters the same two closures on their next import. | **Roll-sensitive:** snapshot and observation-trigger. |
| `README.md` | Documentation only. | Roll-free. |
| `tests/model/test_free_source_feature_parity.py` | Test only. | Roll-free. |
| This report | Documentation only. | Roll-free. |

`feature_store.py` was not changed. A separate mission is known to add 44 lines
to `model_features.py`; this branch adds one import and one guarded block (25
lines). **That is an explicit overlap.** Resolve it additively during a future
quiet-window integration; do not restructure either mission's work.

Because the model files enter two live capture closures, any future merge must
use `scripts/ops/quiet_window_merge.ps1` in the 01:00-04:00 quiet window and
prove capture recovery before push. This mission does not merge.

## Explicitly not done

- No model candidate was fitted.
- No artifact or release manifest was created, changed, or promoted.
- No held candidate was scored.
- No feature row or sidecar was written to production.
- No production host, mirror, `D:\weather-mirror`, or credential file was read
  or written. In particular, `C:\Users\micha\.weathersync.cred` was not read.
- No WU path was enabled and no paid or credentialed source was added.
- No collector, scheduled task, loop, registration, restart, or production
  state was mutated.
- None of the concurrent-owner files was changed: `forecast_history.py`,
  `forecast_archive.py`, `live_variant_settlement_scorecard.py`,
  `nightly_retrain.py`, `daily_refresh.py`, `operations/base_retrain.py`, any
  `mm_*.py`, or `schema_registry_data.py`.
- No severity threshold was invented or tuned.
- No PR and no merge were created. Only the exact branch is to be pushed.

## Verification

Workstation checks executed:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/model/test_free_source_feature_parity.py tests/model/test_feature_skew.py tests/model/test_feature_store.py
# 53 passed, 686 subtests passed

.\venv\Scripts\python.exe -m compileall -q app src tests
# PASS

.\venv\Scripts\python.exe -m pytest -q tests/operations/test_import_architecture.py::test_project_critical_files_are_tracked_or_ignored tests/model/test_free_source_feature_parity.py
# 9 passed, 20 subtests passed
```

The canonical full suite completed with 3,286 passed, 4 skipped, 840 subtests
passed, and 22 failures. The failures were isolated to local/baseline state:
one settlement-ledger authority collision with a temporary fixture, two denied
writes to an ACL-protected local `data/wunderground` cache, four child
PowerShell execution-policy failures, thirteen experiment-executor sandbox
tests, one pre-commit untracked-critical-file check (which passes after the
commit), and one pre-existing docs-audit link failure. The owner suite and
post-commit architecture check pass.

The documentation audit remains blocked by an unrelated broken link already
present on refreshed `origin/master`:

```text
docs/roadmap/agent-report-2026-08-02-workstation-spec-contract-repair.md:
../../src/weather/reporting/validation/floor_retrain_gate_harness.py#L1079
```

Production verification must remain read-only. These commands use paths that
exist on the production host and avoid repository/data writes:

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
git fetch origin codex/workstation-build-free-source-parity-dark-2026-09-22a
git show --stat --oneline 3e1f29dc
git diff --check fbb729bb22c70b3267e1afa002dabb013833dea7..3e1f29dc
git diff --name-only fbb729bb22c70b3267e1afa002dabb013833dea7..3e1f29dc
.\venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q tests/model/test_free_source_feature_parity.py
```

The frozen replay itself is workstation-owned evidence and intentionally is
not prescribed on the production host: its pinned corpus and ignored scratch
receipt were not written into production or committed as a sidecar.

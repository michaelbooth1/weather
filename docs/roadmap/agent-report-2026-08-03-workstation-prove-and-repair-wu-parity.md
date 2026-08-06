# Agent report 2026-08-03 — prove, then repair, exact WU parity

## Verdict

**Exact public-WU parity does not hold under the required point-in-time
contract. No serving implementation was made.**

The public page-backed WU history collector passes the retrospective parts of
the contract on one metric and one English-unit market: v1 payload shape,
station identity, requested units, artifact-era row normalization, values,
categories, and missingness. It fails the gating condition that the observations
were known by the forecast row's cutoff. Both captured packets used for the
proof were retrieved about 23.6 hours after the 10:00 local cutoff.

That failure applies to all ten affected fields. A next-day historical response
cannot be substituted into a same-day serving row, even when its values happen
to reproduce what the artifact was trained on. Per the handoff's stop rule, this
branch contains no source repair, fit, retrain, candidate, release-path change,
or parity-gate change.

## Admission and scope

- Base: `master` at `b804513ed2dd2887d6867ad1267ca407d2eb8330`.
- Topic branch: `codex/workstation-prove-repair-wu-parity-2026-08-30a`.
- Declared run root:
  `C:\Users\Michael\Documents\github\weather\scratch\runs\wu-parity-2026-08-30a`.
- The main `data/` ACL was checked before analysis. It retained explicit,
  non-inherited deny entries for write/delete rights for both
  `DESKTOP-RFCD2GH\Michael` and
  `DESKTOP-RFCD2GH\CodexSandboxOffline`.
- Evidence was restricted to the permitted POST-regime date `2026-07-22`.
  No prohibited date was read, enumerated, evaluated, or substituted by the
  proof.
- No provider was called. In particular, neither a paid history endpoint nor a
  paid current-observation endpoint was called.
- `data/` was read-only. The proof wrote only its script and receipt beneath the
  declared run root.

## Proof design

The receipt uses the same captured raw v1 payload twice:

1. The serve side applies the exact row mapping from
   `5735b573^:src/weather/model/model_sources.py::fetch_wu_history`.
2. The train side applies the current public WU archive normalizer, then the
   native-field projection used by the artifact training cache. In particular,
   it selects `temp_native` and `dewpoint_native` before their misleading
   `*_c` aliases and passes WU wind and pressure through without conversion.
3. Both sides independently derive the ten affected 10:00 features. The
   receipt compares values, categories, units/types, and missingness, not just
   a boolean replay result.
4. The packet's `retrieved_at_utc` is compared with the target day's 10:00 local
   cutoff. This is the fail-closed availability test.

The two cases cover both WU unit modes:

| Case | Public-WU raw rows | Source SHA-256 | WU units |
| --- | ---: | --- | --- |
| CYYZ, `2026-07-22` | 27 | `aef1ffa8413f32ceff5124353f6d39154b3493e8f0520460943cec063dee299b` | `m` |
| KATL, `2026-07-22` | 33 | `4ea9e3f4a18893d02f5f9f4bf4c407969ec56a11cf1cbdc0341ab07eae65acb5` | `e` |

Across the 60 observations, all required v1 keys were present, no observation
was rejected by the archive normalizer, and all 13 artifact-era row fields had
zero train/serve mismatches. Null gust values were preserved as null on both
sides; they were not replaced.

## Contract result

| Contract dimension | CYYZ metric | KATL English | Result |
| --- | --- | --- | --- |
| v1 payload shape | required observation keys present | required observation keys present | PASS |
| Station identity | wrapper and every `key`/`obs_id` = `CYYZ` | wrapper and every `key`/`obs_id` = `KATL` | PASS |
| Requested unit identity | wrapper = `m` | wrapper = `e` | PASS |
| Artifact-era row normalization | 27 rows, 0 mismatches | 33 rows, 0 mismatches | PASS |
| Feature value/category/missingness | all ten equal | all ten equal | PASS |
| Known by 10:00 local cutoff | captured 23.588 h late | captured 23.616 h late | **FAIL** |

The cutoff was `2026-07-22T14:00:00Z` for both cases. CYYZ was captured at
`2026-07-23T13:35:15.496247Z`; KATL was captured at
`2026-07-23T13:36:58.278269Z`. These are valid retrospective history packets,
not point-in-time serving packets. Observation valid time is not a substitute
for producer availability time.

## Field-by-field result at 10:00

Every value contract passes retrospectively. Every field nevertheless fails
**exact serving parity** because the packet that supplies it was future-known at
the row cutoff.

| Field | CYYZ train = serve | KATL train = serve | Exact result |
| --- | --- | --- | --- |
| `rise_from_7am` | `2.0` native C delta | `3.0` native F delta | FAIL PIT |
| `warming_rate_2h` | `1.0` native C delta | `3.0` native F delta | FAIL PIT |
| `hours_at_peak` | `10.0` hours | `0.13333333333333333` hours | FAIL PIT |
| `dewpoint_c` | `11.0` native C | `72.0` native F | FAIL PIT |
| `humidity` | `68.0` percent | `76.0` percent | FAIL PIT |
| `pressure` | `988.61` hPa/mb | `28.92` inHg | FAIL PIT |
| `pressure_trend_3h` | `2.0` hPa/mb delta | `0.05000000000000071` inHg delta | FAIL PIT |
| `wind_speed_kmh` | `31.0` km/h | `8.0` mph | FAIL PIT |
| `wind_group` | `W-NW` | `S-SW` | FAIL PIT |
| `cloud_group` | `Mostly cloudy/overcast` | `Mostly cloudy/overcast` | FAIL PIT |

The receipt records `value_equal=true` and `missingness_equal=true` for all 20
case-field comparisons. That proves retrospective normalization compatibility;
it does not license a current-day serving restoration.

## The three traps

### 1. The feature names lie — re-verified

The English case is decisive:

- `dewpoint_c=72.0` is Fahrenheit, not Celsius.
- `wind_speed_kmh=8.0` is mph, not km/h.
- `pressure=28.92` is inHg, not hPa.

The metric case remains native metric: `dewpoint_c=11.0 C`,
`wind_speed_kmh=31.0 km/h`, and `pressure=988.61 hPa/mb`. The proof performs no
semantic conversion behind the legacy names.

### 2. The July 2 station fallback is not parity evidence — re-verified

The bounded July 2 change (`2a878d91`) derives a separate
`station_observations` source containing current temperature and
max-since-07:00. It does not populate WU history rows and does not provide the
dewpoint, humidity, pressure/trend, wind, or cloud contracts required here.
Current code preserves that separation. It can protect the trusted observed
high, but it cannot establish full artifact-era feature parity.

### 3. Paid access remains disabled — re-verified

`fetch_wu_history()` and `fetch_wu_current()` still invoke
`paid_weather_provider_disabled(...)` before their dead legacy network code.
This task did not change those methods and made no paid-provider call. The
retrospective page-backed collector is not evidence that either paid live route
is supported.

## Consequence for repair sequencing

The no-refit Phase R condition is blocked. A compliant public-WU repair would
first need a captured, producer-available current-day packet whose receipt is at
or before each serving cutoff, with later observations rejected and the same C
and F contract proven again. This task was forbidden from using a fresh date,
so it cannot manufacture that missing proof.

If the defect is repaired now with the supported free live sources, the
METAR/ECCC retrain contract is forced. Those sources have different payloads,
station semantics, cadence, units, row normalization, categories, and
missingness. They may be good inputs, but they cannot be inserted under the WU
feature names and served by existing artifacts. They require a new captured
point-in-time train/serve contract and a retrained artifact. No such retrain was
started here.

## What the repair would be worth

The available causal result does **not** support selling restoration as a mean
model-quality win: blinding cost `+0.009899` overall and `+0.008210` in the
excluded lane, both intervals crossed zero, and the excluded-lane centre moved
warmer rather than reproducing the observed cool displacement.

The evidence supports the narrower framing. Restoration is a correctness fix,
and the fields carry severe-tail information: the prior causal measurement
reduced blind-defined severe-tail squared error by `12.77%` overall and
`15.23%` excluded, concentrated in pressure, `rise_from_7am`, and dewpoint. That
tail/correctness case survives; a headline average-score claim does not.

## Evidence and verification

- Receipt:
  `scratch/runs/wu-parity-2026-08-30a/wu_parity_receipt.json`
  (`SHA-256 b3b633e9a261686755f137645a5825e49ebaa183bd27250adb5891a8ab82d908`).
- Proof script:
  `scratch/runs/wu-parity-2026-08-30a/prove_wu_parity.py`
  (`SHA-256 72295938c9710174c72dd8235c5f4fb62484b2fc1b1568b2b4598cff80b1725f`).
- Receipt summary:
  `payload_shape_all=true`, `station_identity_all=true`,
  `unit_contract_all=true`, `row_normalization_all=true`,
  `feature_values_all=true`, `point_in_time_all=false`, therefore
  `exact_public_wu_parity=false`.

No source code was changed after the failed proof condition, so source/model
tests were intentionally not expanded into implementation verification. The
documentation audit is the relevant tracked-change check.

## Roll sensitivity

The only tracked file touched is this report under `docs/roadmap/`. It does not
match any `src/weather/runtime_identity.py::SOURCE_PATTERNS` entry. The ignored
run-root proof files also do not match those patterns. **No touched file is
roll-sensitive.**

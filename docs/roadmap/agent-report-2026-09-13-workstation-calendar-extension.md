# Agent report 2026-09-13 — workstation calendar extension

**Disposition: `PARTIAL_RESEARCH_EXTENSION_WITH_EXPLICIT_GAPS`.** All 96
pre-registered Open-Meteo Previous Runs request units completed and all
11,154,528 requested long rows remain represented. The corpus contains
10,682,595 finite provider values and 471,933 explicit missing cells. All
missingness is in January 2024; every other requested month is complete. There
were no transport retries, HTTP retries, permanent request failures, or
response-integrity failures.

This was a forecast-data-only mission. No outcome, settlement, market-price,
or market-probability value was opened. No model was fitted, selected, scored,
evaluated, recalibrated, or frozen. No 2026 input was read or modified. The
filename date follows the operator-specified report path; collection occurred
on 2026-09-02.

## Git and immutable plan identity

| Item | Exact value |
| --- | --- |
| Required source branch | `origin/codex/workstation-multiyear-nwp-residual-2026-09-88a` |
| Required source tip | `30386b5f082abbecda99c6357bccde1308771448` |
| Required source tree | `b373970f5912284d6852c9fbb145952727cdc04e` |
| Collection branch | `codex/workstation-collect-calendar-extension-2026-09-89a` |
| P0 plan commit | `1c9608beffb40b7f69ce70672180d6e98664f0be` |
| P0 plan tree | `51584dd02e94696013001d49fb646ed0a632df6a` |
| P0 commit time | `2026-09-02T17:03:27-04:00` |
| Final tip and tree | Reported in the outer handback because a commit cannot contain its own identity |

The exact 96-unit plan and the collector/wrapper code needed to execute it were
committed before the first provider request. The wrapper remains a closed
allowlist: it accepts only the original multi-year plan or this exact new
path/file-hash/plan-hash tuple. It was not changed to accept arbitrary plans.

| Plan binding | Exact value |
| --- | --- |
| Plan | `docs/roadmap/previous-runs-calendar-extension-plan-2026-09-89a.json` |
| Canonical plan SHA-256 | `ee9c39bdadf69a23c3a506bc75cbd3651ecd777318f06a5fd7e457f3c533cf66` |
| Plan file SHA-256 | `e31e8fcb7d08f4da7c714340e071f2af85ceabb70d22d0d5faf1c60f8f08270c` |
| Endpoint | `https://previous-runs-api.open-meteo.com/v1/forecast` |
| Source | `open_meteo_previous_runs` |
| Issue-time basis | `fixed_lead_day_offset` |
| Availability status | `HISTORICAL_FIRST_AVAILABILITY_UNPROVEN` |
| Request units | `96` = 12 markets × 2 years × 4 segments |
| Target dates | 252 in 2024; 251 in 2025; 503 total |
| Market-days | `6,036` |
| Fields / leads / cadence | 11 / 1–7 / hourly |
| Requested long rows | `11,154,528` |
| Output root | `C:\Users\Michael\Documents\Codex\inputs\pit-11field-2024-2025-calendar-extension` |
| Execution profile | `workstation_research_collection_v1` |

The exact eleven-field surface excludes `precipitation_probability`. Each unit
binds the market, latitude/longitude, timezone, native temperature unit,
`km/h` wind request unit, exact year and segment dates, 77 field/lead series,
endpoint, parameter hash, request hash, retry limits, timeouts, raw-byte cap,
and overall runtime. No request supplied an issue, availability, cycle, run, or
publication time.

## P0 proof before provider access

The existing read-only corpus was terminally reverified before the new plan
was created. All 745 retained files rehashed successfully, its canonical
manifest reproduced the required
`d41bd21efb7a62396851fe016a215db1ac8bea7de97f387333902aba7a35bb00`,
and zero integrity errors were found. Its manifest-file hash remained
`25b7b50a733b2f714651bdd4fdb0724aa805fe684c0265e396d90f9d45e28c73`;
its final-verification file hash remained
`a1cdfc4daa29c3b5ecd750a8dcf28c95538269b17317ccb8b6c9e574ad2b4421`.

The new root did not exist, and free space was 273,335,848,960 bytes
(254.564 GiB), above the 10 GiB minimum. No provider request preceded the P0
commit. The existing corpus was never a collection target and was not
overwritten.

## Collector and execution boundary

The dedicated wrapper bound the exact tracked plan and host-assignment hashes,
assigned Windows host and attending principal, exact collector module, exact
endpoint, and new protected output root. It used the host-global
`Global\WeatherProjectHeavyWorkloadV1` mutex, durable poison-state checks, and
kill-on-close Windows Job containment. The generic offline allowlist was not
weakened.

Requests were sequential. Each had a 10-second connect timeout, 120-second
read timeout, and 64 MiB raw-body ceiling; the run had a four-hour bound. Only
transport failures, HTTP 429, and HTTP 5xx were retryable, for at most three
attempts with Retry-After or bounded 5/15-second fallback delays. Other 4xx
responses and validation failures were terminal. No retry was needed.

Every completed unit retains the raw response, response-header diagnostics,
normalized eight-column CSV, self-hashed receipt, and resume state. Receipts
bind raw and normalized byte counts and SHA-256 values, exact plan/request/
parameter hashes, retrieval time, counts by field and lead, and the complete
month/field/lead denominator. Completed units cannot be overwritten and resume
requires full artifact revalidation.

## Corpus identity and size

| Proof | Exact value |
| --- | --- |
| Created at | `2026-09-02T17:11:03.515624-04:00` |
| Disposition | `PARTIAL_RESEARCH_EXTENSION_WITH_EXPLICIT_GAPS` |
| Corpus manifest canonical SHA-256 | `501e5d0e22a0a21c9b0828e28dfa13b9ebc0043ab5c1e9335dda1d619689b448` |
| Corpus manifest file SHA-256 | `023c1a3fefa50b241a1a7a7234eb0c258d5e02c630d7468d057c0303e625fbd2` |
| Final-verification canonical SHA-256 | `7c59cdb7583aadb0a4f97a7f22b910521dfe04dbee6cd53a05fc5d3a2a6e1323` |
| Final-verification file SHA-256 | `9aa25a50611d03f5766e290c272fa6f0d6129f539610fa7db6db999d78996589` |
| Retained-inventory canonical SHA-256 | `6b0760c3ac178c8eba61332934773d89042511c237bbb47d5a2982be089b2d20` |
| Coverage-matrix SHA-256 / bytes | `3284fe12a4dc003cd897fc31dac44df2a0a788e50ac2ccd3889cfe407c807cbd` / `1,117,491` |
| Root-metadata file SHA-256 | `537b5173bb92d49e5b91d18ea6fea6488eb9c06aff3e9b455a2c4757f4ae94ce` |
| Retained files / total bytes | `581` / `1,169,659,199` |
| Request / completed units | `96 / 96` |
| Complete-without-gap units | `84` |
| Requested / normalized rows | `11,154,528 / 11,154,528` |
| Non-null / missing rows | `10,682,595 / 471,933` |
| Raw-response bytes | `55,124,205` |
| Normalized CSV bytes | `1,109,307,859` |
| Integrity errors | `0` |

A second invocation took the terminal verification-only path and reproduced
all corpus, inventory, manifest, and verification hashes exactly. It made no
provider request and opened no source outcome. Every retained file was rehashed.

## Complete coverage matrices

Missing values remain in every requested denominator. Percentages are
`non-null / requested`.

### Year

| Year | Requested | Non-null | Missing | Coverage |
| ---: | ---: | ---: | ---: | ---: |
| 2024 | 5,588,352 | 5,116,419 | 471,933 | 91.555060% |
| 2025 | 5,566,176 | 5,566,176 | 0 | 100.000000% |

### Market

| Market | Requested | Non-null | Missing | Coverage |
| --- | ---: | ---: | ---: | ---: |
| Atlanta | 929,544 | 890,120 | 39,424 | 95.758781% |
| Austin | 929,544 | 890,197 | 39,347 | 95.767064% |
| Chicago | 929,544 | 890,197 | 39,347 | 95.767064% |
| Dallas | 929,544 | 890,197 | 39,347 | 95.767064% |
| Denver | 929,544 | 890,274 | 39,270 | 95.775348% |
| Houston | 929,544 | 890,197 | 39,347 | 95.767064% |
| Los Angeles | 929,544 | 890,351 | 39,193 | 95.783632% |
| Miami | 929,544 | 890,120 | 39,424 | 95.758781% |
| NYC | 929,544 | 890,120 | 39,424 | 95.758781% |
| San Francisco | 929,544 | 890,351 | 39,193 | 95.783632% |
| Seattle | 929,544 | 890,351 | 39,193 | 95.783632% |
| Toronto | 929,544 | 890,120 | 39,424 | 95.758781% |

### Segment

| Segment | Requested | Non-null | Missing | Coverage |
| --- | ---: | ---: | ---: | ---: |
| 2025 Jan 1–Feb 28 | 1,308,384 | 1,308,384 | 0 | 100.000000% |
| 2024 Jan 1–Feb 29 | 1,330,560 | 858,627 | 471,933 | 64.531250% |
| Mar 1–May 9 | 3,104,640 | 3,104,640 | 0 | 100.000000% |
| Sep 1–Oct 31 | 2,705,472 | 2,705,472 | 0 | 100.000000% |
| Nov 1–Dec 31 | 2,705,472 | 2,705,472 | 0 | 100.000000% |

### Month

| Month | Requested | Non-null | Missing | Coverage |
| --- | ---: | ---: | ---: | ---: |
| January | 1,374,912 | 902,979 | 471,933 | 65.675403% |
| February | 1,264,032 | 1,264,032 | 0 | 100.000000% |
| March | 1,374,912 | 1,374,912 | 0 | 100.000000% |
| April | 1,330,560 | 1,330,560 | 0 | 100.000000% |
| May | 399,168 | 399,168 | 0 | 100.000000% |
| September | 1,330,560 | 1,330,560 | 0 | 100.000000% |
| October | 1,374,912 | 1,374,912 | 0 | 100.000000% |
| November | 1,330,560 | 1,330,560 | 0 | 100.000000% |
| December | 1,374,912 | 1,374,912 | 0 | 100.000000% |

### Field

Every field has the same result: 1,014,048 requested, 971,145 non-null, 42,903
missing, and 95.769135% coverage.

| Field |
| --- |
| `temperature_2m` |
| `cloud_cover` |
| `shortwave_radiation` |
| `wind_speed_10m` |
| `cape` |
| `direct_radiation` |
| `diffuse_radiation` |
| `wind_gusts_10m` |
| `precipitation` |
| `vapour_pressure_deficit` |
| `et0_fao_evapotranspiration` |

### Lead

| Lead days | Requested | Non-null | Missing | Coverage |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1,593,504 | 1,535,589 | 57,915 | 96.365557% |
| 2 | 1,593,504 | 1,532,421 | 61,083 | 96.166750% |
| 3 | 1,593,504 | 1,529,253 | 64,251 | 95.967942% |
| 4 | 1,593,504 | 1,526,085 | 67,419 | 95.769135% |
| 5 | 1,593,504 | 1,522,917 | 70,587 | 95.570328% |
| 6 | 1,593,504 | 1,519,749 | 73,755 | 95.371521% |
| 7 | 1,593,504 | 1,516,581 | 76,923 | 95.172714% |

The matrices locate the provider gap without denominator shrinkage: it is
confined to the beginning of the provider's January 2024 Previous Runs history,
affects every requested field, grows with lead, and does not remove a market,
month, field, lead, or request unit.

## Required positive controls

### Existing-corpus hash-bound temperature row: PASS

One already-retained Toronto row was reproduced from the existing corpus's raw
response and normalized projection. No new request was made and neither source
file changed.

| Binding | Exact value |
| --- | --- |
| Unit | `toronto--2024--may10-jun30` |
| Local timestamp / field / lead | `2024-05-10T00:00` / `temperature_2m` / `1` |
| Value / native unit | `11.3` / `°C` |
| Source / issue basis | `open_meteo_previous_runs` / `fixed_lead_day_offset` |
| Normalized-row SHA-256 | `259bd6ddeac0f6d9f50e76997be2537152f5e152029b83d3efb3136a73560885` |
| Raw-response file SHA-256 before/after | `e232d253c33ea26a2be1fb7a235ec7cea4b05fd696bc61f78967778142aa2f4a` / identical |
| Normalized CSV SHA-256 before/after | `432604768ecdc7417c4964e8d01353f64e6b0c722a8b2f6336291da8cec5c46c` / identical |

### Scope and 2025 feature controls: PASS

Plan generation, strict loading, and focused tests prove all 96 ranges end
before May 10 or begin after August 31. No request contains 2026 and no request
contains `precipitation_probability`.

The feature-only 2025 check read the new coverage matrix, not outcomes or
market data. All 8,316 2025 coverage cells have status `COMPLETE`; 5,566,176 of
5,566,176 requested rows are non-null across 12 markets, 11 fields, and seven
leads. No outcome, settlement, price, probability, or model artifact was
opened.

## ACL and root proof

The new output root is a real non-reparse directory with protected ACLs and
owner SID `S-1-5-21-1221641991-3242046124-397692008-1001`. After terminal
verification, the wrapper installed exactly one explicit, non-inherited deny
for `CodexSandboxOffline` SID
`S-1-5-21-1221641991-3242046124-397692008-1003`, with container/object
inheritance and rights `Write`, `Delete`, and
`DeleteSubdirectoriesAndFiles`. The terminal and independent verification runs
both returned `acl_protected: true` and `matching_rule_count: 1`.

## Next experiment pre-registration — not executed

- Training data: all available 2024 eleven-field dates.
- Untouched evaluation: only the new 251 outside-window 2025 dates.
- The spent May–August 2025 terminal evaluation remains excluded and may not be
  reused or pooled.
- Model family: the same temperature-residual baseline versus eleven-field
  residual challenger, with identical feature construction and fixed
  hyperparameters.
- Primary leads: 2–7. Sensitivity: leads 1–7.
- No fit, score, evaluation, outcome access, candidate freeze, or distribution
  action occurred in this mission.

## Verification

All pytest and compileall commands used `scripts/ops/workstation_heavy.ps1`.
Provider collection and terminal re-verification used only
`scripts/ops/workstation_research_collection.ps1`.

| Check | Result |
| --- | --- |
| Immutable 96-unit plan committed before HTTP | PASS; commit `1c9608beffb40b7f69ce70672180d6e98664f0be` |
| Fake transport, retry, 429, 4xx, 5xx, malformed/truncated/duplicate/wrong-unit integrity, missing-series, resume, tamper, and atomicity tests | PASS within focused runs |
| Exact plan, endpoint, wrapper allowlist, host/principal, mutex, poison, Job containment, ACL, no-overlap, no-2026, and no-`precipitation_probability` tests | PASS |
| Focused collector/wrapper suite before provider access | PASS: 23 passed |
| Collector plus module-ownership final focused suite | PASS: 27 passed |
| Compileall (`app`, `src`, `tests`) | PASS, exit 0 |
| Final external inventory rehash | PASS: 581 files; zero integrity errors; hashes reproduced |
| Existing-corpus P0 rehash and hash-bound row control | PASS |
| 2025 forecast-feature-only validation | PASS: 5,566,176/5,566,176 non-null rows |
| Agent-document audit | PASS: 18 agent files, 835 Markdown files including this report |
| Roadmap lint/generated-view check | PASS: `Roadmap backlog: OK` |
| Final complete repository suite | Honest non-PASS: 4,338 passed, 23 skipped, 13 warnings, 866 subtests passed, 12 failed in 730.48 seconds |
| Canonical roll verdict | `UNDECIDABLE: no live closure evidence` |

The 12 complete-suite failures are all the unchanged
`tests/operations/test_experiment_executor.py` failures already documented on
the source branch. Its existing failure path moves the staged candidate tree
to quarantine and then attempts to write the terminal result through the old
path, producing `FileNotFoundError`. No failing test exercises the calendar
extension. Two module-size ratchet failures seen in the first complete run were
repaired by documenting both new warning modules and making the audit retain
all warning rows; the final focused suite passed and the final complete rerun
did not reproduce them.

The canonical roll command additionally reported the four absent local live
closure files. That verdict was not manually substituted. This docs/source/
test-only branch was not merged and no production tree was touched.

## Prohibited-actions audit

PASS. The mission contacted only the authorized endpoint. It did not access
outcomes, settlements, market prices, market probabilities, 2026 inputs,
credentials, an exchange, production, or Scheduler. It did not fit, score,
evaluate, recalibrate, or freeze a model; modify the existing corpus or frozen
mirror; use concurrent transport; add raw data to Git; create a release,
pointer, promotion, candidate freeze, alpha allocation, or confirmation
window; or merge any branch.

# Agent report 2026-09-11 — multi-year PIT research collection

**Disposition: `PARTIAL_RESEARCH_CORPUS_WITH_EXPLICIT_GAPS`.** All 120
pre-registered Open-Meteo Previous Runs request units completed and every one
of the 13,789,440 requested long rows remains represented. The corpus contains
5,975,424 finite provider values and 7,814,016 explicit missing cells. There
were no response-integrity failures. Temperature is complete for 2021–2025;
ten additional fields are available for 2024–2025; precipitation probability
is available for 2025 only. Coverage is complete for all twelve markets and
all seven leads within those provider-supported year/field combinations.

This was a collection-only mission. No outcome, settlement, market-price, or
market-probability file was opened. No model was fitted, selected, scored, or
frozen. The filename date follows the operator-specified report path; the
collection itself ran on 2026-09-02.

## Git and plan identity

| Item | Exact value |
| --- | --- |
| Required source branch | `origin/codex/workstation-research-12field-seasonal-challenger-2026-09-86a` |
| Required source tip | `f2722a4ed6c82557cca10325db82e5c66d03788b` |
| Required source tree | `11b69220188449a84929d678b4146c161922da78` |
| Collection branch | `codex/workstation-collect-multiyear-pit-research-2026-09-87a` |
| P0 plan commit | `4bea620d48aa1075a3cafe368b2778568cedeb87` |
| P0 plan tree | `117fd8081d3f635f596e17beefcda2dc67cf9d67` |
| P0 commit time | `2026-09-02T13:43:29-04:00` |
| Collector execution tip | `f3b3980f7c4d9de1ee93602b93592098fcdd3d8c` |
| Collector execution tree | `c3d19f7d9220f70e5dbc0e42eecb45f517f49e97` |
| Final implementation tip before this report | `aec760591c77b79b83cd7c076492061dcbc73db8` |
| Final implementation tree before this report | `08e0debaee4b0c67d6eb13b0de87fcc26066e414` |
| Worktree | `C:\Users\Michael\Documents\github\weather\scratch\w\multiyear-pit-09-87a` |

The final documentation commit and tree are necessarily reported in the outer
handback because a commit cannot contain its own hash.

The immutable plan was committed before the collector had an HTTP transport
and before any provider request. A first wrapper invocation at implementation
commit `8daa9c96` created only the new protected empty output directory, then
failed in PowerShell preflight on a provider-adapter type property. It did not
launch Python and made no provider call. The empty root was preserved, the
fail-closed type check and exact-empty-root resume were tested and committed at
`f3b3980f`, and only then did the first provider call occur.

| Plan binding | Exact value |
| --- | --- |
| Plan | `docs/roadmap/previous-runs-multiyear-collection-plan-2026-09-87a.json` |
| Canonical plan SHA-256 | `20b45f3c0d98a57170a66a237de865374309da67371805fc15204d00f354b09e` |
| Plan file SHA-256 | `924ddd2f1ca5a85def80dcee1296752df3df167f8a37d9ae7566a8c5f7ec303a` |
| Endpoint | `https://previous-runs-api.open-meteo.com/v1/forecast` |
| Source | `open_meteo_previous_runs` |
| Issue-time basis | `fixed_lead_day_offset` |
| Historical availability | `HISTORICAL_FIRST_AVAILABILITY_UNPROVEN` |
| Request units | `120` = 12 markets × 5 years × 2 segments |
| Segments | May 10–June 30; July 1–August 31 |
| Fields / leads / cadence | 12 / 1–7 / hourly |
| Expected rows | `13,789,440` |
| Output root | `C:\Users\Michael\Documents\Codex\inputs\pit-12field-multiyear-2021-2025` |
| Host assignment file SHA-256 | `111367a167628fcd78753f341beac119f81d9b87380989a9299d165daad80a5b` |
| Execution profile | `workstation_research_collection_v1` |

The operator text says “prefer three bounded segments” but enumerates two.
Those two exact segments are contiguous, cover all 114 requested dates, and
needed no smaller provider-limit subdivision. Every unit binds its exact
market, year, segment dates, 84 field/lead variables, latitude, longitude,
timezone, native temperature unit, wind unit, parameter hash, and request
hash. No request contains 2026 or a caller-supplied issue, availability, run,
cycle, or publication timestamp.

## Collector and execution boundary

The new collector is separate from production corpus and serving code. HTTP is
injected for tests; production requests are sequential. Each request has a
10-second connect timeout, 120-second read timeout, 64 MiB raw-body ceiling,
and the run has a four-hour bound. Only transport failures, HTTP 429, and HTTP
5xx are retryable, at most three attempts per unit. Retry-After is honored;
otherwise the two possible inter-attempt delays are 5 and 15 seconds.

`workstation_research_collection.ps1` binds the exact tracked plan file and
canonical/file hashes, exact host assignment hash, assigned Windows host and
attending principal, exact collector module, and exact endpoint. It refuses
the dedicated capture host and shares
`Global\WeatherProjectHeavyWorkloadV1`, the durable poison-state machine, and
kill-on-close Job containment with workstation-heavy and portable-live work.
It grants no portable-live, production, Scheduler, credential, exchange, or
order authority. The generic `workstation_offline_v1` allowlist was not
weakened.

Each completed unit retains the exact raw body, response-header diagnostics,
normalized eight-column CSV, self-hashed receipt, and atomic latest plus
append-only resume state. The receipt binds raw and normalized byte counts and
SHA-256 values, exact plan/request/parameter hashes, retrieval time, counts by
field and lead, the complete month/field/lead denominator, and all retries.
Normalization constructs the unique
`market × target_datetime_local × field × lead_days` matrix from the exact
validated local hourly vector. Duplicate or misaligned times, truncated
series, wrong units, malformed JSON, non-numeric/non-finite values, wrong
timezone, or unexpected collector faults fail closed. A whole missing provider
series becomes blank values without removing its denominator rows.

## Corpus identity and size

| Proof | Exact value |
| --- | --- |
| Created at | `2026-09-02T18:15:44.047865+00:00` |
| Disposition | `PARTIAL_RESEARCH_CORPUS_WITH_EXPLICIT_GAPS` |
| Corpus manifest canonical SHA-256 | `d41bd21efb7a62396851fe016a215db1ac8bea7de97f387333902aba7a35bb00` |
| Corpus manifest file SHA-256 | `25b7b50a733b2f714651bdd4fdb0724aa805fe684c0265e396d90f9d45e28c73` |
| Final-verification file SHA-256 | `a1cdfc4daa29c3b5ecd750a8dcf28c95538269b17317ccb8b6c9e574ad2b4421` |
| Final-verification canonical SHA-256 | `aed0b39ee7c8c8faa4f8f40f97d03fdad6d60d75d42af808733466110d639ee1` |
| Retained-inventory canonical SHA-256 | `0a92a267d5609950302182c53862d8bab77fd95b207e6805a8a2c968a7566933` |
| Coverage-matrix SHA-256 / bytes | `b7a2d4f0b6a9725122fb96d9953f6d25520552bc75779973ce869486d6344429` / `1,625,313` |
| Root-metadata file SHA-256 | `59ddde7d3f0e6607ee9dfe71a02f7994902047fc9899c24d4398e075514f422e` |
| Retained files / total bytes | `745` / `1,432,072,987` |
| Request / completed units | `120 / 120` |
| Complete-without-gap units | `24` |
| Requested / normalized rows | `13,789,440 / 13,789,440` |
| Non-null / missing rows | `5,975,424 / 7,814,016` |
| Raw-response bytes | `71,003,723` |
| Normalized CSV bytes | `1,354,476,392` |
| Integrity errors | `0` |

Every completed receipt, raw body, response-header artifact, normalized CSV,
plan copy, resume record, failed-attempt receipt, coverage matrix, and corpus
manifest is present in the final 745-file content-addressed inventory. The
terminal verifier recomputed sizes and SHA-256 values from disk and returned
`raw_projection_plan_receipt_manifest_rehash: PASS`.

## Complete coverage matrices

Missing values stay in `requested`; none of the following denominators was
shrunk. Percentages are `non-null / requested`.

### Year

| Year | Requested | Non-null | Missing | Coverage |
| ---: | ---: | ---: | ---: | ---: |
| 2021 | 2,757,888 | 229,824 | 2,528,064 | 8.333333% |
| 2022 | 2,757,888 | 229,824 | 2,528,064 | 8.333333% |
| 2023 | 2,757,888 | 229,824 | 2,528,064 | 8.333333% |
| 2024 | 2,757,888 | 2,528,064 | 229,824 | 91.666667% |
| 2025 | 2,757,888 | 2,757,888 | 0 | 100.000000% |

### Market

| Market | Requested | Non-null | Missing | Coverage |
| --- | ---: | ---: | ---: | ---: |
| Atlanta | 1,149,120 | 497,952 | 651,168 | 43.333333% |
| Austin | 1,149,120 | 497,952 | 651,168 | 43.333333% |
| Chicago | 1,149,120 | 497,952 | 651,168 | 43.333333% |
| Dallas | 1,149,120 | 497,952 | 651,168 | 43.333333% |
| Denver | 1,149,120 | 497,952 | 651,168 | 43.333333% |
| Houston | 1,149,120 | 497,952 | 651,168 | 43.333333% |
| Los Angeles | 1,149,120 | 497,952 | 651,168 | 43.333333% |
| Miami | 1,149,120 | 497,952 | 651,168 | 43.333333% |
| NYC | 1,149,120 | 497,952 | 651,168 | 43.333333% |
| San Francisco | 1,149,120 | 497,952 | 651,168 | 43.333333% |
| Seattle | 1,149,120 | 497,952 | 651,168 | 43.333333% |
| Toronto | 1,149,120 | 497,952 | 651,168 | 43.333333% |

### Field

| Field | Requested | Non-null | Missing | Coverage |
| --- | ---: | ---: | ---: | ---: |
| `temperature_2m` | 1,149,120 | 1,149,120 | 0 | 100.000000% |
| `cloud_cover` | 1,149,120 | 459,648 | 689,472 | 40.000000% |
| `shortwave_radiation` | 1,149,120 | 459,648 | 689,472 | 40.000000% |
| `wind_speed_10m` | 1,149,120 | 459,648 | 689,472 | 40.000000% |
| `cape` | 1,149,120 | 459,648 | 689,472 | 40.000000% |
| `direct_radiation` | 1,149,120 | 459,648 | 689,472 | 40.000000% |
| `diffuse_radiation` | 1,149,120 | 459,648 | 689,472 | 40.000000% |
| `wind_gusts_10m` | 1,149,120 | 459,648 | 689,472 | 40.000000% |
| `precipitation_probability` | 1,149,120 | 229,824 | 919,296 | 20.000000% |
| `precipitation` | 1,149,120 | 459,648 | 689,472 | 40.000000% |
| `vapour_pressure_deficit` | 1,149,120 | 459,648 | 689,472 | 40.000000% |
| `et0_fao_evapotranspiration` | 1,149,120 | 459,648 | 689,472 | 40.000000% |

The year and field matrices identify the provider gap exactly: 2021–2023
contain temperature only; 2024 contains every requested field except
precipitation probability; 2025 contains all twelve fields.

### Lead

| Lead days | Requested | Non-null | Missing | Coverage |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1,969,920 | 853,632 | 1,116,288 | 43.333333% |
| 2 | 1,969,920 | 853,632 | 1,116,288 | 43.333333% |
| 3 | 1,969,920 | 853,632 | 1,116,288 | 43.333333% |
| 4 | 1,969,920 | 853,632 | 1,116,288 | 43.333333% |
| 5 | 1,969,920 | 853,632 | 1,116,288 | 43.333333% |
| 6 | 1,969,920 | 853,632 | 1,116,288 | 43.333333% |
| 7 | 1,969,920 | 853,632 | 1,116,288 | 43.333333% |

### Month

| Month | Requested | Non-null | Missing | Coverage |
| ---: | ---: | ---: | ---: | ---: |
| May | 2,661,120 | 1,153,152 | 1,507,968 | 43.333333% |
| June | 3,628,800 | 1,572,480 | 2,056,320 | 43.333333% |
| July | 3,749,760 | 1,624,896 | 2,124,864 | 43.333333% |
| August | 3,749,760 | 1,624,896 | 2,124,864 | 43.333333% |

### Segment

| Segment | Requested | Non-null | Missing | Coverage |
| --- | ---: | ---: | ---: | ---: |
| May 10–June 30 | 6,289,920 | 2,725,632 | 3,564,288 | 43.333333% |
| July 1–August 31 | 7,499,520 | 3,249,792 | 4,249,728 | 43.333333% |

The identical coverage at every market, lead, month, and segment shows that
the missingness is a provider history-depth boundary by field/year, not a
silently lost location, horizon, month, or request segment.

## Retry history

Seven HTTP 429 responses occurred across four units. All were retained with
raw response and response headers, honored the provider's Retry-After value,
and were retried sequentially. There were no transport or 5xx retries and no
4xx response other than 429.

| Unit | Attempt | Class/status | Retrieval time (UTC) | Attempt-receipt file SHA-256 |
| --- | ---: | --- | --- | --- |
| `atlanta--2025--may10-jun30` | 1 | `HTTP_429` / 429 | `2026-09-02T18:09:39.860243+00:00` | `d5327ed4f32d8d475ad7e5047adca22455f834ed470e85441bbcc94049c843ad` |
| `atlanta--2025--may10-jun30` | 2 | `HTTP_429` / 429 | `2026-09-02T18:09:45.376400+00:00` | `492d298b29d05b7deb548e883f5c8d6c7fe6a76b8e50b2a509285cbf3a7f79c7` |
| `chicago--2024--may10-jun30` | 1 | `HTTP_429` / 429 | `2026-09-02T18:10:43.915906+00:00` | `ae147928086ab663b4ecbb65cfa9ab5d162674976804b2766b410bd41046418b` |
| `chicago--2024--may10-jun30` | 2 | `HTTP_429` / 429 | `2026-09-02T18:10:49.419397+00:00` | `5ae44c2ff0b184cca0fe4f8cb9293fe7a4fadffd126fbe60fcc2cf94558d2f0e` |
| `houston--2024--may10-jun30` | 1 | `HTTP_429` / 429 | `2026-09-02T18:12:51.807686+00:00` | `bc842ee47d13f79246e603f378cdf6626020bcfe465f5f89b194f8d3177db7a4` |
| `houston--2024--may10-jun30` | 2 | `HTTP_429` / 429 | `2026-09-02T18:12:57.322589+00:00` | `bf6be3c6f2201de09d42540918fb50e857aef3903846fe9cd71bb1970839f60d` |
| `miami--2023--may10-jun30` | 1 | `HTTP_429` / 429 | `2026-09-02T18:13:56.879940+00:00` | `004877dbdd02139dee1d8e43323d0b66282c5d11e1b03902bac2dc66471da7ae` |

All four units subsequently completed and passed terminal re-verification.

## Required positive controls

### Sealed 2026 column contract: PASS

Only the two original manifests, transfer manifest/receipt, and first header
line of each of the 24 sealed CSVs were read. No sealed 2026 forecast value was
read or changed. Every CSV header is exactly:

```text
market,target_datetime_local,field,lead_days,value,unit,issue_time_basis,source
```

That is byte-for-byte the new normalized column contract. Pre- and
post-collection metadata hashes were identical:

| Sealed metadata | SHA-256 |
| --- | --- |
| Transfer manifest | `1794455e40f967411d05660ff4ac785e1fab48caccb8fbdfb3df7aa31438712a` |
| Transfer-manifest hash sidecar | `c50b0baaf71823d7c89d87becaaecade164a4bd287169a2b23385211267dc748` |
| Transfer receipt | `0fd8c9dc14d07ee76d42bded4ea965b69fdb81668474d41862607a3aec7343ca` |
| Front original manifest | `f1366001341ad6bf96242dc42a9ed47310051079a033e035e850f0f486d1d28d` |
| Back original manifest | `0f52e100a979e5aeb2949d94734682045b5fa294ca0f0cb0d88c1de078ebc735` |

The sealed root remained read-only and was not a collection target.

### Hash-bound temperature overlap: PASS

Immediately before semantic row access, the existing workstation Toronto
archive was bound as
`C:\Users\Michael\Documents\github\weather\data\forecast_history\cyyz\forecast_long.csv`
at SHA-256
`960e53d67c84a2a7fc3e2f5cd83786b1d82e83e5b85355be468995bb002dae2a`.
Its manifest file SHA-256 is
`53f7607366fccbd2311073c28062cdfc9f34511993c10918265bf91c22db545f`.
Only one exact overlapping temperature row was selected:

| Binding | Existing archive | New corpus |
| --- | --- | --- |
| Market | Toronto | Toronto |
| Local valid time | `2021-05-10T00:00:00-04:00` | `2021-05-10T00:00` |
| Field / lead | temperature / 1 | `temperature_2m` / 1 |
| Source | `open_meteo_previous_runs` | `open_meteo_previous_runs` |
| Issue basis | `fixed_lead_day_offset` | `fixed_lead_day_offset` |
| Native unit | `C` | `°C` |
| Value | `5.2` | `5.2` |

The new normalized file was bound at
`356bf06e9008166ad838a8a3d7020c6a8aa1ac70b0873d586b63bb0461b44078`.
Both complete file hashes were identical before and after the row comparison;
neither source was rewritten.

### 2025 feature-only validation: PASS

The 2025 coverage matrix and unit receipts were checked without opening any
outcome or market evidence: 24/24 units are `COMPLETE`, all 4,032
year/market/segment/month/field/lead coverage cells are present, and all
2,757,888 requested rows are non-null. The matrix contains 12 markets, 12
fields, and seven leads with zero missing cells. This is the untouched terminal
evaluation year for the pre-registered next experiment; no evaluation occurred
in this mission.

## ACL and root proof

The output root is a real non-reparse directory. Inheritance is disabled and
the owner is `DESKTOP-RFCD2GH\Michael` (SID
`S-1-5-21-1221641991-3242046124-397692008-1001`). Explicit full-control allows
exist only for the attending identity, SYSTEM, and Administrators. After final
verification the wrapper installed exactly one explicit, non-inherited deny
for `DESKTOP-RFCD2GH\CodexSandboxOffline` (SID
`S-1-5-21-1221641991-3242046124-397692008-1003`) with container/object
inheritance and rights `Write`, `Delete`, and
`DeleteSubdirectoriesAndFiles`. The wrapper's ACL proof reported
`acl_protected: true` and `matching_rule_count: 1`.

A subsequent default-offline `Get-Content` was denied at the protected root;
manifest inspection therefore required the attending identity. No write probe
was attempted after sealing.

## Verification

All pytest and compileall commands used `scripts/ops/workstation_heavy.ps1`.
The provider run and terminal re-verification used only
`scripts/ops/workstation_research_collection.ps1`.

| Check | Result |
| --- | --- |
| Immutable P0 plan before HTTP transport/provider access | PASS |
| Fake transport, success, timeout/transport retry, 429, 4xx, 5xx, truncation, duplicate-time, malformed-JSON, missing-field, wrong-unit, resume, tamper, interrupted-stage/atomicity tests | PASS within focused run (51 passed, 11 skipped) |
| Exact collector profile, host/principal binding, endpoint/module binding, mutex, poison state, kill-on-close containment, PowerShell syntax, and ACL tests | PASS within focused runs |
| Schema registry and agent-document focused suite | PASS (14 passed) |
| Hook-boundary plus collector profile/admission rerun after boundary fix | PASS (37 passed, 11 skipped) |
| Related existing PIT corpus/training contract regression tests | PASS (26 passed) |
| Compileall (`app`, `src`, `tests`) | PASS (exit 0) |
| Final external inventory re-hash | PASS (745 files; zero integrity errors) |
| 2025 feature-only coverage validation | PASS |
| Sealed 2026 header/manifests-only control | PASS; values unread and metadata hashes unchanged |
| Hash-bound one-row temperature overlap | PASS (`5.2 °C == 5.2 °C`; source hashes stable) |
| Agent-document audit CLI | PASS (18 agent files, 833 Markdown files) |
| Roadmap lint/generated-view check | PASS (`Roadmap backlog: OK`; generated report matches sources) |
| Final `git diff --check` | PASS |
| Canonical roll verdict | `UNDECIDABLE: no live closure evidence` (exit 1) |

The complete repository suite was executed once and retained its honest
non-PASS result: **4,313 passed, 23 skipped, 13 warnings, 866 subtests passed,
13 failed** in 460.99 seconds. One failure was caused by the placement of the
new collector helper inside a textual offline-allowlist boundary. That defect
was fixed without adding the collector to the offline allowlist, and the
affected hook/profile suite then passed as reported above.

The other 12 failures all come from
`tests/operations/test_experiment_executor.py`: its existing failure path moves
the staged candidate tree to quarantine and then attempts to write the terminal
result through the old path, producing `FileNotFoundError`. They reproduce in
an isolated 55-test run as 43 passed / 12 failed. This mission did not modify
that executor or test: the current/source-branch blobs are exactly
`f2a823274f5b5d47335bd0682014722258d638b0` and
`e323b5a8c9a5ef44f5f4f5894039e150cfac5593`, respectively. Repairing that
unrelated experiment-sandbox lifecycle is outside this collection-only scope;
the failure is not hidden or converted to a PASS.

The canonical roll verdict came only from:

```powershell
scripts\ops\roll_verdict.ps1 -Branch codex/workstation-collect-multiyear-pit-research-2026-09-87a
```

It returned exit 1 because the snapshot, CLOB, observation-trigger, and CLOB-
enrichment live closure-status files are absent on this non-capture
workstation. No manual roll classification and no merge were substituted.

## Next experiment: pre-registered, not executed

The immutable plan registers only this future design:

- train years 2021–2024;
- untouched terminal evaluation year 2025;
- incumbent-anchored residual correction, not a full pooled replacement refit;
- primary sensitivity at leads 2–7;
- 2026 as external secondary evaluation only, never pooled with 2025.

The missing-field history means any future design must handle the explicitly
different information surfaces: temperature-only in 2021–2023, eleven fields
in 2024, and twelve in 2025. This report makes no claim that such a model has
edge and grants no authority to open outcomes.

## Prohibited-actions audit

| Action | Result |
| --- | --- |
| Outcome, settlement, market-price, or market-probability read | none |
| Model fit, selection, scoring, evaluation, or freeze | none |
| Provider contact outside the exact Previous Runs endpoint | none |
| 2026 provider collection | none |
| Paid provider, key, credential, or proxy workaround | none |
| Historical/stitched forecast endpoint | none |
| Caller-manufactured issue/availability/run/publication time | none |
| Frozen 2026 value read or mutation | none; header/manifests only |
| Existing archive or new corpus rewrite during overlap control | none; pre/post hashes match |
| Production or capture-host contact | none |
| Scheduler mutation | none |
| Exchange contact, order mutation, or alpha allocation | none |
| Release, pointer, promotion, candidate freeze, or confirmation window | none |
| Large data, raw response, normalized CSV, or external receipt added to Git | none |
| Merge or integration execution | none |

The corpus is research-only. Its historical first-availability remains
unproven, current retrieval times are retrieval evidence only, and it cannot
satisfy the production v2 PIT contract without new provider-owned evidence.

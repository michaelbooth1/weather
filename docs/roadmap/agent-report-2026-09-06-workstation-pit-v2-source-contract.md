# Workstation report: PIT v2 free-source contract

**Verdict: NO-GO — `NO_GO_PROVIDER_BOUND_AVAILABILITY_AND_PARITY`.**

No reviewed free source satisfies every P0 requirement. NOAA GFS and ECMWF
Open Data encode a truthful forecast-cycle identity, but neither documents an
immutable historical first-publication/first-availability time for each
artifact, and neither preserves the frozen 12-field hourly semantics across a
free historical archive and the forward-serving surface. Open-Meteo Single
Runs provides explicit run selection, but does not expose historical per-run
availability and cannot populate the frozen 2021–2025 training years under the
same run-preserving surface. The mission therefore stopped before collector
design or implementation.

The filename follows the assigned nominal mission date. The review was executed
on 2026-09-01 EDT.

## Exact foundation and branch identity

```text
required foundation tip   6e23e756f8a2c620df4d821411c923a77afb0553
required foundation tree  e1a1ddd09edb8e97131a74592c05235e44965c99
pre-change branch tip      6e23e756f8a2c620df4d821411c923a77afb0553
pre-change branch tree     e1a1ddd09edb8e97131a74592c05235e44965c99
branch                     codex/workstation-pit-v2-source-contract-2026-09-82a
worktree                   scratch/w/pit-v2-source-contract-09-82a
```

The branch was created directly from the required foundation in the separate
worktree above. The final report-only tip and tree are reported in the outer
handback after this file is committed; a commit cannot contain its own hash.

## Scope and authority actually used

- Read official documentation only. No provider forecast API, metadata API,
  bucket object, catalogue, THREDDS endpoint, or raw forecast file was called or
  downloaded.
- Did not repeat the already-closed Open-Meteo Previous Runs trace. Its response
  exposes no provider run ID, issue timestamp, publication timestamp, or
  availability timestamp. The legacy market-local midnight label was not used.
- Did not fit, retrain, materialize, promote, release, or activate a model.
- Did not read or write production data, Scheduler, exchange, credential, or
  release state.
- Repository authority covers neither Open-Meteo Single Runs nor Model Updates
  nor a NOAA/ECMWF provider call in this mission. No new authority was inferred.

## P0 decision rule

`issue_time_utc` means the provider's forecast reference/initialisation time,
bound to an artifact or to an unambiguous provider run selector. It is not a
derived lead label. `available_at_utc` means defensible evidence that the exact
artifact was publicly usable by that time. A nominal production schedule,
forecast-cycle time, response-retrieval time, HTTP `Date`, or undocumented
object `Last-Modified` value is not historical first-availability evidence.

Every candidate also had to provide a free historical archive and a
forward-serving surface with equivalent model, field, accumulation, cadence,
and derivation semantics. One missing timestamp or one unrepairable semantic
gap is a P0 stop.

## Timestamp matrix

| Surface | Provider artifact/run identity | Truthful `issue_time_utc` | Historical provider-bound `available_at_utc` | Forward availability evidence | P0 |
| --- | --- | --- | --- | --- | --- |
| NOAA deterministic GFS GRIB2 | **Yes.** The dated key/filename binds date, cycle, and `fFFF` lead; GRIB2 Section 1 separately binds reference date/time and its significance. | **Yes.** Require GRIB reference-time significance `1` (start of forecast) and equality with the dated key/cycle. | **No.** The reviewed GFS product/GRIB and archive docs do not document a historical per-artifact first-publication/availability field. | AWS S3 `ObjectCreated` `eventTime` can prospectively bind S3 request completion to an object key, and the Registry exposes `NewGFSObject` SNS. No historical event ledger/replay is documented; delivery is at-least-once and unordered. | **NO-GO** |
| ECMWF Open Data IFS GRIB2 | **Yes.** Dated `HH` cycle paths, filenames, index keys, and GRIB reference time bind model/stream/type/step. | **Yes.** Forecast reference/start time is provider encoded. | **No.** Dissemination windows and “7–9 h after run start” are schedules, not retained per-artifact publication facts. | Progressive current dissemination can be observed, but no historical first-availability ledger is documented. | **NO-GO** |
| Open-Meteo Previous Runs | **No.** Fixed valid-time offsets are not complete model runs. | **No.** Closed prior finding; no run/init timestamp is returned. | **No.** Closed prior finding; no publication or availability timestamp is returned. | No qualifying provider timestamp. | **NO-GO; not re-traced** |
| Open-Meteo Historical Forecast | **No.** The provider describes a stitched time series from successive runs. | **No.** No explicit run selector. | **No.** No historical run-availability evidence. | Not a run-preserving serving surface. | **NO-GO** |
| Open-Meteo Single Runs | **Conditional.** Required `run=YYYY-MM-DDThh:mm` identifies UTC model initialisation. The JSON response does not echo run identity, so a collector would have to bind the canonical request URI to the raw bytes. | **Yes only with that request binding.** The docs explicitly define `run` as initialisation/reference time. | **No.** The docs explicitly distinguish initialisation from public availability and give only typical delay ranges. | Model Updates exposes model-level latest-run availability on the queried API server only. It is not documented as an immutable timestamp for the exact Single Runs artifact and has no history. | **NO-GO** |
| Open-Meteo `data_run` open-data layout | **Yes.** The provider path embeds `<model>/<YYYY/MM/DD/hhmmZ>`. | **Yes.** The run directory is the reference time. | **No.** Per-run completion metadata is not documented to contain first public availability. Public AWS run retention is three months; unspecified extended archives are available directly from Open-Meteo, but no reviewed free-access, retention, or historical-availability contract covers them. | Prospective observation might establish a local upper bound, not historical provider-bound evidence. | **NO-GO** |
| Open-Meteo Model Updates metadata | Latest run only. | Latest initialisation only. | **No history.** No documented past-run query or immutable ledger. | Current `last_run_availability_time` exists, with eventual-consistency warnings. | **NO-GO as a training source** |

The decisive timestamp failure is common: run time answers “what forecast cycle
is this?” while availability answers “when could the model have known it?” No
reviewed source makes the latter historically reconstructible without invention.

## Archive and train/serve-parity matrix

| Candidate | Historical access | Forward access | Equivalent semantics over 2021–2025 and serve time | Disposition |
| --- | --- | --- | --- | --- |
| NOAA GFS | NCEI documents a 0.5° period of record from 2006, but only about two years are online; older data require HAS/archive/tape ordering and some custom/physical fulfillment may carry fees. Cloud/NODD 0.25° access is a trailing short window. | Current 0.25° products run four cycles/day, hourly through the early horizon. | **No.** Long-history grid/cadence and access path differ from current serving, model implementations change by date, and official history does not establish equivalent `sflux` coverage or first availability. | NO-GO |
| ECMWF Open Data | Official free portal retains only the latest 12 runs (about 2–3 days). Full historical access requires a Service Agreement; the public cloud mirror has no documented complete-retention contract. | Current IFS Open Data is free, real-time, and CC BY 4.0. | **No.** An open licence does not make full-archive delivery free: ordinary full-history access uses a Service Agreement and service charges, while waivers are discretionary. Free launch began in 2022 at 0.4°, changed to 0.25° with expanded fields in 2024, and output is 3-/6-hourly. | NO-GO |
| Open-Meteo Single Runs — GFS | Listed archive begins 2026-04-02. | Same endpoint serves explicit current runs. | **No.** It cannot populate the fixed 2021–2025 training population, regardless of its current field breadth. | NO-GO |
| Open-Meteo Single Runs — ECMWF IFS HRES | Listed from 2024-03-14 as Cycle 49R1 hindcasts; Cycle 50R1 begins 2026-05-12 06Z. | Same endpoint serves current explicit runs. | **No.** It lacks the full fixed years, changes model-cycle semantics, omits documented precipitation probability on the ECMWF surface, and has no historical availability record. | NO-GO |
| Open-Meteo `data_run` | Public AWS per-run retention is documented as three months; the README mentions extended direct archives without a reviewed free-access or retention guarantee. | Current run objects are published prospectively. | **No.** Native OM-file fields and API-derived fields are not one proven 2021–serve contract; historical availability is absent. | NO-GO |

## Frozen 12-field matrix

The project contract requires 24 hourly local rows per target day. “Derived”
below is not automatically disqualifying, but it would require one frozen,
versioned formula and the same inputs and interval semantics in train and serve.

| Frozen field | NOAA deterministic GFS | ECMWF direct Open Data IFS | Open-Meteo endpoint/GFS-family docs; exact one-model explicit-run coupling unproved |
| --- | --- | --- | --- |
| `temperature_2m` | Native `TMP` at 2 m. | Native `2t`. | Listed at endpoint/family level. |
| `cloud_cover` | Native `TCDC`; instantaneous versus interval-average selector must be frozen. | Native `tcc`. | Listed at endpoint/family level. |
| `shortwave_radiation` | Native interval-average surface `DSWRF`. | `ssrd` is accumulated; conversion and output interval must be frozen. | Listed at endpoint/family level. |
| `wind_speed_10m` | Derived magnitude of 10 m `UGRD`/`VGRD`. | Derived magnitude of `10u`/`10v`. | Listed as provider-derived from components. |
| `cape` | Native `CAPE`, but parcel/layer selector must be frozen. | Only `mucape`; not proved equivalent to generic CAPE. | Listed for an applicable GFS-family model surface. |
| `direct_radiation` | Candidate sum `VBDSF + NBDSF` from the NCO f001 `sflux` inventory (page last updated 2021); equivalence plus current and historical artifact parity are unverified. | Absent from the exhaustive free deterministic list. | Listed at endpoint/family level. |
| `diffuse_radiation` | Candidate sum `VDDSF + NDDSF` from the same dated inventory; equivalence plus current and historical parity are unverified. | Absent; cannot be recovered from `ssrd` alone. | Listed at endpoint/family level. |
| `wind_gusts_10m` | `GUST` is labelled surface, not explicitly 10 m; semantic mismatch unresolved. | `10fg` is maximum since prior post-processing, at the free 3-/6-hour cadence. | Listed. |
| `precipitation_probability` | No generic PoP appears in the reviewed deterministic pgrb2/pgrb2b/sflux inventories. `CPOFP` is frozen-precipitation percentage, not precipitation probability. | The only published probability products are 24-hour ensemble thresholds at coarser steps. Deriving a probability from raw members would require a new frozen threshold/interval contract and historical member parity. | Listed as an Open-Meteo GFS/GEFS calculation; not proved to come from the same exact explicit-run model/artifact and not a raw deterministic-GFS field. |
| `precipitation` | Native accumulated `APCP`; accumulation window/PDT must be frozen. | Native accumulated `tp`; interval differencing is required. | Listed at endpoint/family level. |
| `vapour_pressure_deficit` | Derived from 2 m temperature plus dew point or RH. | Derived from `2t` and `2d`; no native VPD field. | Listed as provider-derived. |
| `et0_fao_evapotranspiration` | No native FAO-56 ET0. `PEVPR` is potential evaporation rate, not equivalent. | Absent; formula-derived only. | Listed as provider-derived FAO-56 ET0. |

Open-Meteo's endpoint and GFS-family documentation reaches the names of all 12
fields, but it does not prove that one selected explicit-run model/artifact
supplies all 12 together. That breadth also does not repair the missing
2021–2025 explicit-run archive or historical availability. NOAA fails exact
deterministic field coverage on precipitation probability, and ECMWF lacks
several fields and hourly cadence.

## Existing v2 foundation audit

The foundation is a fail-closed staging substrate, not a truthful collector:

| Existing behavior | Finding |
| --- | --- |
| Immutable request plan | Pinned to Previous Runs and marks network/provider probe authority false. Each request says provider-contract probing is still required. |
| Issue evidence | `stage_response` accepts caller-supplied `issue_evidence`; it checks presence, ordering, and cutoff, but does not derive or authenticate the timestamps from provider bytes. A string value `fixed_lead_offset` is a schema label, not proof. |
| Tests | Fixtures provide invented `gfs-20210509-00z`, `issue_time_utc`, and `available_at_utc` values to test gate behavior. They are positive-control fixtures, not source evidence. |
| Raw bytes and receipts | The substrate already hashes raw bytes, writes bodies and self-hashed receipts atomically, verifies byte/hash/row counts, and skips a unit only after re-verification. |
| Retry/resume | `resume_ledger` is request-hash keyed, but no non-test transport consumes it. |
| Network boundary | The corpus module intentionally has no HTTP client and `stage_response` has no non-test caller. |

Adding an injected transport around this substrate would not solve the evidence
defect: it would still require a source-specific, provider-bound derivation of
both timestamps. Because no candidate passed P0, the conditional collector
design/implementation phase was not entered. No module, schema, retry policy,
resource wrapper, or provider fixture was added.

## Official primary documentation reviewed

### NOAA GFS

- [NCEP GFS product names and cycle convention](https://www.nco.ncep.noaa.gov/pmb/products/gfs/)
- [NCEP current 0.25° pgrb2 field inventory](https://www.nco.ncep.noaa.gov/pmb/products/gfs/gfs.t00z.pgrb2.0p25.f003.shtml)
- [NCEP 0.25° pgrb2b field inventory](https://www.nco.ncep.noaa.gov/pmb/products/gfs/gfs.t00z.pgrb2b.0p25.f003.shtml)
- [NCEP f001 sflux field inventory (page last updated 2021)](https://www.nco.ncep.noaa.gov/pmb/products/gfs/gfs.t00z.sfluxgrbf001.grib2.shtml)
- [NCEP GRIB2 Section 1 identification](https://www.nco.ncep.noaa.gov/pmb/docs/grib2/grib2_doc/grib2_sect1.shtml)
- [NCEP GRIB2 reference-time table](https://www.nco.ncep.noaa.gov/pmb/docs/grib2/grib2_doc/grib2_table1-2.shtml)
- [NCEI GFS periods of record and access](https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast)
- [NCEI GFS 0.5° archive metadata](https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc%3AC00634)
- [NOMADS access and retention description](https://nomads.ncep.noaa.gov/info.php?page=help)
- [NOAA GFS open-data registry entry](https://registry.opendata.aws/noaa-gfs-bdp-pds/)
- [Official AWS GFS key-layout sample](https://github.com/aws-samples/aws-opendata-samples/blob/main/notebooks/noaa-gfs/noaa_gfs_quickstart.ipynb)
- [Amazon S3 event timestamp and object-binding schema](https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-content-structure.html)
- [Official GFS implementation history](https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/gfs/implementations.php)
- [NCEP production status](https://www.nco.ncep.noaa.gov/pmb/nwprod/prodstat/)

### ECMWF Open Data

- [ECMWF Open Data subset, fields, cycles, and rolling retention](https://www.ecmwf.int/en/forecasts/datasets/open-data)
- [ECMWF file naming, index format, and pre-50r1 convention](https://confluence.ecmwf.int/spaces/DAC/pages/272310539/ECMWF+open+data+real-time+forecasts+from+IFS+and+AIFS)
- [ECMWF dissemination schedule](https://confluence.ecmwf.int/spaces/DAC/pages/272310483/Dissemination+schedule)
- [Official ECMWF Open Data client documentation](https://github.com/ecmwf/ecmwf-opendata)
- [ECMWF/ecCodes edition-independent reference-time keys](https://codes.ecmwf.int/grib/format/edition-independent/2/)
- [ECMWF GRIB2 Section 1 identification](https://codes.ecmwf.int/grib/format/grib2/sections/1/)
- [ECMWF GRIB2 significance-of-reference-time table](https://codes.ecmwf.int/grib/format/grib2/ctables/1/2/)
- [ECMWF `ssrd` parameter semantics](https://codes.ecmwf.int/grib/param-db/?id=169)
- [ECMWF historical archive access](https://www.ecmwf.int/en/forecasts/accessing-forecasts/order-historical-datasets)
- [ECMWF archive tariffs](https://www.ecmwf.int/en/forecasts/accessing-forecasts/payment-rules-and-options/tariffs)
- [ECMWF open-data cloud registry entry](https://registry.opendata.aws/ecmwf-forecasts/)
- [ECMWF 2022 free-open-data launch](https://www.ecmwf.int/en/about/media-centre/news/2022/ecmwf-makes-wide-range-data-openly-available)
- [ECMWF 2024 0.25° and parameter expansion](https://www.ecmwf.int/en/about/media-centre/news/2024/ecmwf-releases-much-larger-open-dataset)

### Open-Meteo explicit-run surfaces

- [Single Runs API](https://open-meteo.com/en/docs/single-runs-api)
- [Model Updates metadata](https://open-meteo.com/en/docs/model-updates)
- [GFS API field/model semantics](https://open-meteo.com/en/docs/gfs-api)
- [ECMWF API field/model semantics](https://open-meteo.com/en/docs/ecmwf-api)
- [Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api)
- [Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api)
- [Forecast API JSON return contract](https://open-meteo.com/en/docs)
- [Open-Meteo open-data run layout and retention](https://github.com/open-meteo/open-data)
- [Open-Meteo first-party Single Runs controller](https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Controllers/ForecastapiController.swift)

## Verification

Only documentation and the owning roadmap item changed. No Python/source code
changed, so the user-required full suite condition was not triggered.

| Check | Result |
| --- | --- |
| Roadmap regenerate/lint | PASS — `Roadmap backlog: OK`; generated `docs/roadmap/active-backlog.md`. |
| Roadmap generated-view check | PASS — `Roadmap backlog: OK (generated report matches sources)`. |
| Focused roadmap test through `workstation_heavy.ps1` | PASS — `12 passed in 0.20s`. |
| Repository compileall through `workstation_heavy.ps1` | PASS — exit `0`, no output, for `app src tests`. |
| Agent-doc audit | PASS — `18 agent files, 831 Markdown files`. |
| `git diff --check` | PASS — exit `0`; only Git's informational CRLF-to-LF warning for the generated backlog. |
| Full suite | Not run; no code changed. |

The first regenerate/lint invocation failed closed after the item disposition was
updated without its canonical `ROADMAP.md` row. The row was synchronized as the
roadmap instructions require; the regeneration, generated-view check, and
focused test then passed. Both Python verification workloads named by the
mission—pytest and compileall—ran through the canonical
`scripts/ops/workstation_heavy.ps1` wrapper and its
`workstation_offline_v1` lease.

Canonical roll command executed in this isolated workstation worktree:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch codex/workstation-pit-v2-source-contract-2026-09-82a
```

```text
UNDECIDABLE: no live closure evidence
  missing closure evidence: data\snapshots\loop_supervisor_status.json
  missing closure evidence: data\snapshots\clob_loop_supervisor_status.json
  missing closure evidence: data\snapshots\observation_trigger_supervisor_status.json
  missing closure evidence: data\snapshots\clob_enrichment_status.json
exit code: 1
```

That is the canonical workstation result. It is not replaced with a hand-made
roll classification. The cumulative branch inherits the foundation changes, so
production must run the same command against the pushed ref before any merge
decision. Pushing the topic branch does not change the production working tree.

## Handback

The source search is closed as **NO-GO**, while item 330 remains **PARTIAL**.
The smallest valid next input is not collector code: it is provider-owned proof
of an immutable historical availability ledger plus a free archive/forward
field-and-cadence contract covering the frozen years. If that proof appears,
the collector can then bind the provider run key and timestamp evidence to raw
bytes, request hash, atomic receipt, and resume state. Until then, training or
retraining would reproduce the existing information defect.

No production data, Scheduler task, provider credential, exchange operation,
model fit, corpus publication, promotion, release, branch merge, or history
rewrite occurred.

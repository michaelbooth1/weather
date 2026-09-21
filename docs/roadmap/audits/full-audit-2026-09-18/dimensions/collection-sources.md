# Audit dimension: Data collection and sources (`collection-sources`)

Date: 2026-09-18. Auditor: read-only subagent on the live production host.
Scope: `src/weather/collection/` (16 files) and `src/weather/sources/` (28 files), plus the
minimum of adjacent code needed to trace one instance of each claim end to end
(`src/weather/io.py`, `src/weather/operations/daily_refresh_source_steps.py`,
`daily_refresh_resources.py`, `event_metadata_validation.py`, `location_config_refresh.py`,
`capture_resource_gate.py`, `loop_jsonl_repair.py`, `src/weather/market/market_registry.py`,
`src/weather/reporting/source_gates/settlement_source_audit.py`, `config/locations.json`,
`config/location_market_events.json`, `scripts/ops/register_daily_refresh.ps1`, `scripts/ops/daily_refresh.ps1`).

Overall grade for this dimension: **C**. The live-capture machinery is genuinely well engineered
(grade B on its own). The grade is pulled down by one stale foundational assumption (what the market
actually resolves on), a torn-write gap in the snapshot tapes at exactly the moment the disk is about
to fill, and a settlement-restore design that scales with total history instead of with one day.

## Method and constraints

- Tools: Read, Grep, Glob with explicit paths under `src/`, `tests/`, `docs/`, `scripts/`, `config/`.
  Shell limited to `git log`, `git show <rev>:<path> | head`, and one non-recursive `ls`.
- No python, no tests, no network, no `data/` access (my brief did not grant it). Therefore every
  statement about *live* behaviour (what is on disk, whether a failure has actually occurred) is
  labelled `inferred`. Everything labelled `verified_in_code` was read line by line.
- "A grep is not a trace": for each structural claim I opened the definition, at least one caller,
  and the reader side. Where I only grepped, I say so.

---

## Findings (most severe first)

### F1 (HIGH, new) - The market no longer names Weather Underground as its resolution source; the project still does

**Claim.** The project's own production-generated snapshot of live Polymarket Gamma metadata records
`resolutionSource = https://www.weather.gov/wrh/timeseries?site=<icao>` for all 12 core markets
(CYYZ, KLGA, KATL, KAUS, KORD, KDAL, KBKF, KHOU, KLAX, KMIA, KSFO, KSEA). The same generated file
recorded Weather Underground history URLs on 2026-08-15, 2026-08-19 and 2026-08-22 and weather.gov
from the 2026-08-26 snapshot on. Nothing in `src/`, `tests/`, or `docs/` mentions `wrh/timeseries`;
the canonical domain guide still defines WU as the modeled settlement source; nothing detects
drift between the static settlement config and the live resolution source.

**Evidence.**
- `config/location_market_events.json:5` - `generated_at_utc 2026-09-18T22:00:03Z` (working tree, production generated).
- `config/location_market_events.json:34579` - Toronto 2026-09-18 event: `"resolution_source_url": "https://www.weather.gov/wrh/timeseries?site=cyyz"`.
- Same file, lines 1507 (katl), 2383 (kaus), 6775 (kord), 8239 (kdal), 9115 (kbkf), 12043 (khou),
  17311 (klax), 21115 (kmia), 24619 (klga), 27835 (ksfo), 29587 (ksea): all weather.gov.
  Counts: 115 weather.gov entries vs 7 wunderground.com entries (jinan, taipei, zhengzhou only).
- `git show 4e6956a5f:config/location_market_events.json` (2026-08-15), `d58b64971` (08-19),
  `a414d5648` (08-22): first event's `resolution_source_url` = `https://www.wunderground.com/history/daily/nl/schiphol/EHAM`.
  `git show 3e1b54126:...` (08-26) and `HEAD` (09-13): `https://www.weather.gov/wrh/timeseries?site=eham`.
  (I could only view the first ~60 lines of historical revisions under the shell whitelist, so the
  switch date is verified for the first location only; the all-12 statement is verified for the
  current working-tree snapshot.)
- `config/locations.json:37-39, 107-109, 144-146, ...` - static config still says
  `"source_type": "wunderground_history"` with WU URLs.
- `src/weather/market/market_registry.py:43` - `resolution_source: str = "wu_history"` default;
  `:431-435` only validates that the id is listed in `sources`.
- `docs/operations/AGENT_CONTEXT.md:22-25` - "The modeled settlement source is the highest whole-degree
  value printed by the configured Weather Underground history source".
- `src/weather/operations/event_metadata_validation.py:495-507` - `resolution_source_url` is compared
  only between the *generated* snapshot and *live* Gamma. Both move together at each refresh, so a
  wholesale change of resolution source can never persist as a mismatch.
- `src/weather/reporting/source_gates/source_family_inventory.py:1519` - the only other consumer checks
  that a URL is *present*, not what it points at.
- Grep of `src/weather` for `synopticdata|mesowest|api.weather.gov/stations|wrh/timeseries`: no collector
  for the NWS timeseries product exists.

**Why it matters.** NWS timeseries and WU history draw on the same airport sensors but are different
products (different observation sets, rounding paths and revision behaviour), so their whole-degree
daily maxima can differ by a band. Three things in this project depend on the identity of the
resolution product: (a) the hard observed *floor* that WU history is allowed to set
(`AGENT_CONTEXT.md:25`), which is the project's single shipped forecast win and also the mechanism
behind its worst historical defect (zero probability on the realised band); (b) the label itself;
(c) "effective WU printed cutoff" alignment of intraday features.

**What already mitigates it (credit where due).** Labels are reconciled against Polymarket's actual
winning band (`settlement_source_audit.py:207-212`, `:323-336`), and `promotion_countable` requires
`reconciliation_status == "match"`. So a WU/NWS divergence should surface as a *mismatch and a
non-countable day*, not as a silently wrong label. That converts the risk from "wrong truth" into
"fewer countable dates" - which is the project's binding constraint - plus an unguarded floor.

**What I could not determine.** Whether the rule *text* on Polymarket changed along with the
`resolutionSource` field (no network), and whether reconciliation mismatches have risen since
2026-08-22 (no `data/` access). Both are cheap for the owner to check.

**Recommendation.** Treat as an owner decision, not a code patch: (1) read one live market's rules
text and confirm the resolution product; (2) compare WU daily max vs the retained IEM ASOS/METAR
series for the same ICAO on dates since 08-22 and count band disagreements and reconciliation
mismatches; (3) add a drift check that fails loudly when the live `resolutionSource` host differs
from `config/locations.json`'s `settlement.resolution_source_url` host; (4) record the outcome in
ESTABLISHED_FINDINGS / AGENT_CONTEXT either way.

Basis: verified_in_code (repo files and git history). Impact: inferred. Confidence: high on the fact, medium on impact.

---

### F2 (HIGH, new; memory cost partially acknowledged) - Settling one day rebuilds all of WU history for all 12 markets, un-isolated

**Claim.** `run_public_wu_settlement_restore_step` calls `store.rebuild_normalized_files()` for every
market on every run, including when nothing was fetched. That function loads every raw day file ever
collected into a list, normalises all of it, rewrites every monthly hourly partition, the daily CSV,
and a manifest that re-hashes every partition. The call sits outside the step's per-market
`try/except`, and `iter_raw_records()` has no error handling, so one unreadable raw file for one
market raises out of the loop and no later market is processed.

**Evidence.**
- `src/weather/operations/daily_refresh_source_steps.py:184-240` - the fetch is inside `if ranges:` and a
  `try`, but line 240 `hourly_rows, daily_rows = store.rebuild_normalized_files()` is at loop level,
  unconditional and unguarded.
- `src/weather/sources/wu_history.py:396-417` - `records = list(self.iter_raw_records())`, full normalise, full rewrite.
- `src/weather/sources/wu_history.py:419-423` - `json.load` per raw file with no `try`
  (contrast `raw_dates()` at `:622-638` and `write_manifest` at `:516-522`, which both tolerate bad files).
- `src/weather/sources/wu_history.py:526-537` - manifest re-reads and SHA-256s every partition each time.
- `src/weather/operations/daily_refresh_resources.py:56-62` - the project already budgets this step at
  60 min, 4096 MB private, 2048 MiB *admission* working set, rationale "per-market full-history WU
  normalization rebuild; measured corpus requires isolation".

**Why it matters.** Cost grows with every collected day on a 16 GB host whose primary risk is
memory. A step that must be *admitted* against a 2 GiB reservation before it can settle yesterday is
a step that gets deferred under pressure, and each deferred day is a settlement hole that the next
run does not backfill (the step only targets one date). The live briefing reports 10 of the last 14
dates unsettled. I did **not** verify that this step is the cause (no `data/` access); I am saying
the design makes it a credible contributor and an avoidable one.

**Recommendation.** Make the restore incremental (normalise only the target date's raw file, append or
replace that date's rows, update only the touched partition's manifest entry); move the rebuild
inside per-market isolation so one bad file costs one market; make `iter_raw_records` skip-and-report
like its siblings.

Basis: verified_in_code; link to the live hole inferred. Confidence: high on the code, low-medium on causation.

---

### F3 (HIGH, new) - Snapshot tapes are not torn-write safe, nothing counts the damage, and capture never looks at free disk

**Claim.** `SnapshotStore.append_jsonl` streams a record token-by-token into an append handle and
writes the newline last, with no check that the file currently ends in a newline. If the writer dies
mid-record (capture children are killed on timeout or working-set breach; the disk can fill), the
file ends in a partial line and the *next* successful append is concatenated onto it. Every reader
skips unparseable lines silently, so one torn write costs two records and the second loss is
invisible. `collection_health.py` contains no malformed-line accounting at all, and nothing under
`src/weather/collection/` checks free disk space.

**Evidence.**
- `src/weather/collection/snapshot_store.py:2547-2558` - append; `durable=False` by default (no fsync) for
  `snapshots.jsonl`, features, components, explanations, forecasts, source status and `replay_inputs`
  (`:892`, `:936`, `:949`, `:964`, `:984`, `:994`, `:1002`); only payload index rows pass `durable=True` (`:1911`, `:2008`).
- `src/weather/collection/snapshot_store.py:133-153` - `_iter_json_text_chunks` yields per `iterencode` token, so a
  large record reaches the OS as many writes.
- `src/weather/collection/snapshot_store.py:3099-3103` - the project's own comment: a healthy writer can be
  inside one snapshot transaction for more than five minutes.
- `src/weather/collection/snapshot_capture_batch.py:197-228` - children run under `timeout_seconds` and a
  working-set ceiling; `capture_timeout` and `capture_resource_budget` are first-class outcomes, i.e. kills happen.
- Readers that drop bad lines without counting: `snapshot_store.py:2598-2614`, `snapshot_tracker.py:312-326`, `io.py:690-705`.
- Grep of `collection_health.py` for `malformed|JSONDecodeError|invalid_lines|corrupt`: no matches.
  `snapshot_artifact_integrity` (`collection_health.py:504-599`) checks the long CSV only.
- Grep of `src/weather/collection` for `disk_usage|ENOSPC|free_bytes|No space`: no matches. The disk gate that
  exists (`operations/capture_resource_gate.py:34-35`, 30 GiB / 30 days) admits *heavy batch work*; the capture loop
  imports only `available_memory_bytes` from it (`snapshot_tracker.py:46`).
- The multi-tape write is not transactional: long CSV (`:886`), wide CSV (`:887`) and `snapshots.jsonl` (`:892`) are
  appended before `replay_inputs` (`:1002`). The comment at `:996-1000` ("persisted first so no served row can
  reference an absent captured input") is true only relative to the variant tape written after it.
- History: `docs/operations/python-runtime-audit-baseline.json:91-102` and `ops_fix_todo_2026_07_03.md:103` record
  past `No space left on device` events on this host.
- `operations/loop_jsonl_repair.py:31-44` - the repair tool targets loop sidecars, not per-event snapshot tapes; it also
  rewrites in place (`:131`) and skips the backup if an older `.malformed.bak` exists (`:123-126`).

**Why it matters.** The briefing says ~21 GB free, ~5.9 GB/day, about four days. Captured inputs are the
one class of data this project cannot re-fetch. The first ENOSPC will tear the tail of every tape being
written, the first post-recovery append will destroy one more record per tape, and no health surface
will say so.

**Recommendation.** Before each append, if the file is non-empty and its last byte is not `\n`, write a
`\n` first (one `seek`, one byte) and count the event; add a malformed-line counter to collection
health for the JSONL tapes; add a cheap free-space floor to the capture child that returns an explicit
`skipped: disk_floor` result instead of writing; consider serialising small records to one string and
issuing a single `write`.

Basis: verified_in_code. Confidence: high on the mechanism; occurrence to date unknown.

---

### F4 (MEDIUM, known_accepted for the policy; sub-defects new) - WU acquisition is a single-point scrape of WU's own web API key

**Claim.** Settlement data is obtained by requesting the public WU history page with a hard-coded Chrome
User-Agent, parsing the page's `const data = {...}` runtime config to lift WU's own `API_KEY`, then
calling the provider's data-API host with `/v1/location/<id>/observations/historical.json`, `Referer` and
`Origin` set to wunderground.com. No key is stored in the repo (good), but the method is exposed to
any page redesign, bot mitigation, or terms enforcement, and there is no second settlement source.
Two code defects sit on top: a page-layout change raises `RuntimeError`, which
`failure_class_for_exception` classifies as `transient` (no status code), so a permanent break is
retried and logged as transient every day; and the CLI `public-backfill` catches only
`requests.RequestException`, so that same `RuntimeError` aborts the run even with `--continue-on-error`.

**Evidence.** `src/weather/sources/wu_history.py:95-98` (constants), `:256-259` (UA), `:267-272` (Referer/Origin),
`:274-291` (key extraction and the `RuntimeError`), `:301-333` (two-step fetch, no internal retry),
`:155-174` (status `None` -> `TRANSIENT_FAILURE`), `:1110-1122` (CLI exception scope).
Policy basis: `docs/operations/AGENT_CONTEXT.md:39-42`; `wu_history.py:86-94`.

**Note.** If F1 is confirmed, this exposure may be largely unnecessary: the named resolution product
would be a US-government page backed by the same ASOS/METAR feeds the project already collects from IEM.

Basis: verified_in_code. Confidence: high.

---

### F5 (MEDIUM, new) - `forecast_history backfill` replaces good archives with partial ones and exits 0

**Claim.** `backfill()` swallows any per-year exception (prints, continues with zero rows), then
overwrites the daily CSV, the long CSV, the daily-issue CSV and the manifest in place with only what
this run fetched. The CLI does not inspect the result. A run during an Open-Meteo outage or free-tier
rate limit therefore shrinks or empties the forecast-history inputs used by features, calibration and
the train/serve parity check, non-atomically, with exit code 0.

**Evidence.** `src/weather/sources/forecast_history.py:781-796` and `:815-817` (swallowed errors),
`:831-836` (`daily_path.open("w")`), `:844-846` and `:636` (`write_csv` in place), `:877-878` (manifest in place),
`:1297-1310` (no exit status). Consumers: `model/model_features.py:28`, `calibration/pooled_feature_assembly.py:64`,
`reporting/scorecards/train_serve_feature_parity.py:39`. A separate `coverage` command (`:1311-1320`) can detect the
loss afterwards, but the prior data is already gone.

**Why now.** The project's own notes say the season-window re-fetch "must still be RUN"; that is this code path, on the free tier.

Basis: verified_in_code. Confidence: high.

---

### F6 (MEDIUM, new) - The first WU fetch of a date is frozen forever, with no completeness test

**Claim.** `raw_dates()` treats a date as present if its raw file parses and `observations` is a list of
any length. With `skip_existing=True` (the default for the settlement step) such a date is never
refetched. The settlement step accepts `row_count > 0`. The target date is "yesterday in Toronto" for
all 12 markets. The only thing stopping a Pacific market from being frozen mid-day is the scheduled
09:30 start; the wrapper script itself permits the settlement stage from 00:30 local, when the Pacific
day still has 2.5 hours to run. The project has separately established that the WU series is not
append-only, so an early fetch can differ from the finalised page.

**Evidence.** `wu_history.py:622-638`, `:734-744`; `daily_refresh_source_steps.py:134-143`, `:173`, `:187-191`;
`operations/settled_day_freshness.py:190-197`; `scripts/ops/register_daily_refresh.ps1:21` (09:30);
`scripts/ops/daily_refresh.ps1:97-103` (00:30 lower bound).

Basis: verified_in_code. Confidence: medium (depends on how often off-schedule runs happen).

---

### F7 (LOW, new) - Atomic-write discipline is inconsistent across source stores, and existence is used as coverage

- `io.write_json_atomic` (`io.py:353-377`): temp + replace but no fsync, and a failed `write_text` leaves the unique
  temp file behind. WU raw settlement payloads use it (`wu_history.py:375`).
- In-place raw writes followed by existence-based skip: `reanalysis_history.py:166` with filename-derived coverage at
  `:169-179`; `metar_history.py:270-273`; `eccc_history.py:33-45`; also `asos_one_minute.py:682`, `noaa_ghcnh_history.py:206`.
  A file torn by power loss or ENOSPC is thereafter "covered". Reanalysis partly compensates with
  `raw_normalizable_dates()` / `raw_only_day_count`; METAR does not.
- Done properly: `wu_history.py:436-440`, `:481-486`, `:718-722`; `snapshot_store.py:2505-2535`; `historical_schema.py:250`.

### F8 (LOW, new) - One implausible auxiliary field discards the whole WU observation
`wu_history.py:769-770`: a row is dropped if *any* of temp, dew point, heat index, wind chill is out of bounds.
A bad dew point can therefore remove the row carrying the day's maximum temperature from the settlement
summary. The quarantine is recorded in the manifest (`:488-512`, `:566-569`) but is not surfaced in the
settlement step's per-market status (`daily_refresh_source_steps.py:253-276`).

### F9 (LOW, latent) - `eccc_history` write mode is hard-wired to May/June
`eccc_history.py:21` `TARGET_MONTHS = (5, 6)` and `:82` `open("a" if month == 6 else "w")`. Extending the months
for the planned July/August window makes every month other than June truncate the year's file.

---

## Checklist from the brief

| Question | Answer | Basis |
|---|---|---|
| How is WU fetched? | Public history page scraped for WU's runtime API key, then JSON API call. No key in repo; redaction tested. | verified (`wu_history.py:237-333`; `tests/sources/test_historical_sources.py:128,614`) |
| Is it verified that Polymarket resolves on the same WU page/station/units? | Outcome-level yes (winning band reconciliation). Source-level no, and the live metadata now names a different product (F1). | verified |
| Every HTTP call has a timeout? | Yes for every `requests.get` / `urlopen` in `sources/` (19 call sites checked by grep, 6 opened). `collection/` makes no direct HTTP calls. | verified by grep + sample |
| Bounded retry/backoff? | Shared helper `io.request_with_retries` (3 attempts, exponential, honours `Retry-After`, 429 and 5xx only). METAR/ASOS have their own bounded loops. WU client itself has none; the settlement step wraps it (2 retries, 5 s x 2^n). `ReanalysisClient.fetch_range` has none. | verified |
| Atomic writes? | Mixed (F7). CAS blobs are exemplary. | verified |
| Partial JSONL tolerance on read? | Yes everywhere, but silently and uncounted; append side unprotected (F3). | verified |
| Open-Meteo rate limits? | Live path: shared cross-process cooldown file, `rate_limited` / `rate_limited_cache` / `provider_cooldown` statuses on a source-status tape, fleet health distinguishes "rate limited with fresh family coverage". Good. Backfill path: F5. | verified (`snapshot_tracker.py:238,1698`; `snapshot_store.py:1226-1266`; `collection_health.py:664-700, 932-974`) |
| Schema-drift detection? | CSV header widening is handled safely (`snapshot_store.py:2489-2545`). WU page drift raises loudly but is mislabelled transient (F4). Resolution-source drift undetected (F1). | verified |
| Timezone handling? | Sound: epoch -> market IANA tz (`wu_history.py:997-1002`); METAR requests an extra UTC day for western zones (`metar_history.py:202-204`); pre-local-day guard in capture (`snapshot_tracker.py:139-158`). Caveat: settlement target date is Toronto-yesterday fleet-wide (F6). | verified |
| Dedupe? | Snapshot duplicate-id detection in health; METAR `dedupe_records`; CAS dedupes by content hash; WU is one file per local day so no cross-file duplicates. | verified |
| Station mapping / supplemental stations? | Strong registry contract with required provenance, role check, adoption windows and a guard against pointing at the canonical root. | verified (`supplemental_stations.py:12-28, 46-71, 110-117`) |
| Source failure: loud or silent? | Live capture: loud (explicit failed/skipped/BLOCK results, source-status rows). Backfills: silent in F5; WU settlement: loud BLOCK. | verified |
| Disk full? | Capture does not check; appends tear (F3). Heavy batch work is gated at 30 GiB, which the host is already below. | verified |

## Strengths

1. **Content-addressed payload store** - staged file, fsync, hard-link publish, then size and digest
   re-verification; concurrent writers converge on one blob (`snapshot_store.py:1352-1433`).
2. **HTTP hygiene** - explicit timeouts on every call site found, one shared bounded retry helper that
   honours `Retry-After` (`io.py:46-124`).
3. **WU failure taxonomy with regression tests** - page-backed 404 kept retryable so an edge outage cannot
   poison a date, a recovery command for rows written before the fix, key never persisted, redaction tested
   (`wu_history.py:111-201, 689-732`; `tests/sources/test_historical_sources.py:128-160, 614-741`).
4. **Capture loop architecture** - single-writer locks with live-owner and age-bound recovery, bounded isolated
   children with memory ceilings, per-market failure isolation, explicit outcomes instead of omissions,
   runtime-fingerprint guard (`snapshot_tracker.py:1474-1491`; `snapshot_capture_batch.py:147-250`; `snapshot_store.py:3061-3107`).
5. **Settlement truth anchored to the market's own outcome**, plus a careful supplemental-station registry
   (`settlement_source_audit.py:207-212, 323-336`; `supplemental_stations.py`).

## Not covered

- Read only in part or not at all: `forecast_payload_cas.py`, `forecast_payload_fetch_fanout.py`, `forecast_archive.py`,
  `forecast_tracker.py`, `historical_backfill_plan.py`, `historical_backfill_runner.py`, `live_variant_predictions.py`,
  `triggered_snapshot_queue.py`, most of `snapshot_store.py` (3,100 lines) and `collection_health.py`;
  in `sources/`: `nbm_probabilistic_tmax.py`, `official_guidance_collection.py`, `marine_context.py`, `marine_water_contrast.py`,
  `mrms_precip.py`, `grib_probe.py`, `eccc_gridded.py`, `eccc_swob_history.py`, `asos_one_minute.py`, `noaa_ghcnh_history.py`,
  `open_meteo_archives.py`, `forecast_training_corpus.py`, `forecast_training_variants.py`, `reanalysis_synoptic.py`,
  `historical_coverage.py`, `historical_schema.py`, `daily_summary.py`.
- The live HTTP fetchers for forecasts and current observations live in `src/weather/model/model_sources.py`, outside
  this dimension's directories; I did not audit them.
- No `data/` access: I could not confirm whether torn lines, frozen partial days, or reconciliation mismatches exist today.
- No network: I could not read Polymarket's rule text or WU's terms.

## Open questions for the owner

1. Does the Polymarket rules text for the 12 markets now name the NWS timeseries page? If so, since which event date?
2. Since 2026-08-22, how many market-days have `reconciliation_status = mismatch`, compared with before?
3. Did capture BLOCK on `resolution_source_url_mismatch` between the switch and the next six-hourly config refresh?
4. How large is the WU raw corpus per market today, and how long does the restore step take?
5. Has any `capture_timeout` or `capture_resource_budget` kill coincided with a malformed tail line in a snapshot tape?

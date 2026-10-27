# Data layer v2 plan

**Living plan, canonical.** Owner mandate 2026-10-14 ~20:40 EDT (relayed by master-agent): build the best data layer we
can, capturing as much helpful data as possible, RAM- and storage-mindful. Drafted 2026-10-14 by a 15-agent design
workflow on `c2771ab02`; the production addendum below binds over the body where they differ.

How to keep it true:
- **Edit in place; never fork a dated copy.** When a step lands, a receipt replaces a "not measured", or a date moves,
  change the row and say how (e.g. `S1 landed <sha> 10-19`). Build status and receipts live here; today's critical
  path and decisions stay in [STATE_OF_PLAY](STATE_OF_PLAY.md); measured results go to the
  [findings digest](FINDINGS_DIGEST.md) and [established findings](ESTABLISHED_FINDINGS.md) as usual.
- **§9 owner questions stay listed until a relayed owner answer arrives.** Nothing in §9 is acted on before then; the
  answer is recorded in [DECISION_LOG](DECISION_LOG.md) and the question is marked answered here, not deleted.
- Roll classes here are predictions; the binding verdict is `scripts\ops\roll_verdict.ps1 -Branch <b>` at landing.
- Evidence behind the pilot: [more-markets desk study](../research/more-markets-desk-study-2026-10-14.md)
  (liquidity census, MDE/K1 scaling, storage, foreign feasibility).

> **Production-agent addendum (2026-10-14 21:5x EDT, capture host; binds over the text below where they differ)**
> 1. **Calendar correction.** Pyup B is the 10-16 night (00:30) and cutover C the 10-17 night; neither night takes any other host work (G5/G7). S0(g) is therefore NOT on the 10-16 night.
> 2. **S0(g) host stat, taken now (stat only, no content read):** C: free 158.4 of 930.6 GiB; RAM free 7,153 of 16,125 MiB; commit 12.0 of 31.75 GiB. `data\wunderground\<icao>\last_good_sources.json` is ~36 MB for each of the 11 US stations (cyyz 0.6 MB), ~400 MB in all: an efficiency lead (S0 should check how often it is rewritten whole). Still owed: one pre-09-30 closed event's `observation_payloads` size.
> 3. **Pilot route (workstation read of 88a enumeration, c2771ab02).** Config-only via `config/markets.json` is rejected: `all_specs()`/REGISTRY has 172 call sites, so every loop would adopt the pilot cities as full markets. The env-var route needs a new task action. `--extra-conditions` is capped at 32 ids with daily churn. The pilot list must be read by 88a only, from a **default config path inside `maker_evidence_capture.py`** (id, slug_prefix, tz). **No task-argument change**, because `register_maker_evidence_capture.ps1` must not be run: it writes PT1M over the live PT5M. A pilot that needs new arguments waits for the registrar PT5M fix plus an owner yes. REGISTRY, the events file and capture closures stay untouched.
> 4. **88a stream cap.** `maker_evidence_store.py` DEFAULT_STREAM_CAP is 300 MB/day for the whole universe, while the measured raw update rate (09-23 amendment) is ~1.96 GB/day, so the cap already binds. S2+S9 must state the post-pilot per-city update coverage and either revisit the cap or accept the dilution explicitly, with a receipt.
> 5. **Embargo disclosure (§ risks, item 13).** A design subagent fetched the live public HKO since-midnight CSV once at 2026-10-15 00:40Z. It is not our venue/88a/panel/settlement/snapshot/wallet evidence, Hong Kong is not a built-in market, nothing was stored or carried forward, and it is disclosed to the owner. Process rule adopted: no live settlement-instrument fetch by desk agents during an embargo.

Read-only desk synthesis at master `c2771ab02`, 2026-10-14, with both review rounds applied. No `data\` reads, no embargoed content, nothing in the repo edited. Every number is tagged **(measured: source)**, **(est.)** with its derivation, or **not measured**. All roll classes are predictions; the binding verdict is `scripts\ops\roll_verdict.ps1 -Branch <b>` at landing time, taken from the production checkout.

Spot-checked during finalization: `MAX_RAW_BYTES = 500_000_000` and `DEFAULT_STREAM_CAP = 300_000_000` (`src/weather/market/maker_evidence_store.py:19-20`); served AWC `hours` capped at 24 (`src/weather/model/model_sources.py:1485`); rclone crypt keys already kept off Drive (`docs/operations/DECISION_LOG.md` 2026-10-02 row). Every other review citation is used as the reviewers gave it. Each one is traced before the step that depends on it.

## 0 Judge's scorecard

| Criterion (1-10) | A Value-first | B Efficiency-first | C Integrity-first |
| --- | --- | --- | --- |
| Value captured (non-backfillable first) | **9**: widest coverage (51 ICAOs, all venue cities, Phase D) | 7: same core, narrower (12+5 stations) | 8: same core, plus the evidence envelope that makes the value usable later |
| Efficiency (bytes/RAM per unit information) | 7: good moves, but adds many families before the savings are banked | **9**: "pay first, then add", explicit caps, heartbeat semantics, measurement pack | 7: same moves, less ordering discipline |
| Integrity (PIT, attribution, embargo-by-construction) | 7: ID-1 manifests, no reader contract | 7: code manifest and panel, no reader contract | **9**: row envelope, seal chain, one PIT/embargo reader |
| Feasibility on this host and calendar | 6: a roll-sensitive landing nearly every night 10-19..10-27 | 7: realistic nights, but the first-seen log needs a watcher roll | 7: fewest rolls; flags the free-space discrepancy |
| Roll risk | 5 | 6 | **8** |
| **Total** | 34 | 36 | **39** |

**Decision.** Design C is the base, because the owner called this "the foundation of all our work" and integrity is what makes a stored byte worth keeping. From A: the complete family table, the phased venue expansion with byte-gated phases, the 51-ICAO first-seen log in a roll-free process, and the headroom arithmetic. From B: "pay first, then add" for the two expensive venue families, the workstation measurement pack as step 0, the "unchanged ≠ not captured" heartbeat rule, the RAM floor rule, and the shed order. The review round added a per-night lease timetable, integration-attempt machinery, fetch-side embargo enforcement, reuse of the existing embargo code, the 88a working-set latch, min-temperature labels, a served-payload PIT extractor, and the rewards trigger moved ahead of any 88a widening.

**Conflicts resolved explicitly**

1. *Where the first-seen observation log lives.* A separate recorder (OB-1, roll-free) comes first. At S10 the watcher becomes the **sole** AWC writer for the 12 built-ins and the recorder keeps the other 39 stations. The two journals join on `(station, obs_time, raw_hash)`. Snapshot children never depend on another process: they fall back to their own fetch when the shared cache is older than N seconds, and they record which path served.
2. *Pilot enumeration.* `config/capture_families.json` rows, read at the default path with no new CLI argument, reloaded every cycle, with `config_sha256` stamped in manifests. **During the 88a panel window (to UTC 10-30) the 12 built-ins stay enumerated from `all_specs()`. Config may only add recorder-only rows.**
3. *L2 delta budget.* No daily truncation cap. VR-2 uses a per-(token, hour) budget, a priority order and explicit cap/gap rows. Its size comes from S0(a) so that the budget binds in under 5% of hours. It does not land before the S0(a) receipt and the Ethernet decision.
4. *Evidence host shape.* One `WeatherEvidenceHost` task supervises **long-lived** per-family children under a real hard-commit Job cap. Websockets stay in their existing processes. Light HTTP batch jobs run as bounded scheduled tasks, not under the heavy lease.
5. *Lowest-temperature series.* The pilot code ships a generic `(series, location)` universe source. The lowest series is a config flip, and it waits for S9 (rewards change-trigger) and for min labels in LB-1.
6. *HRDPS for Toronto.* The workstation extracts it nightly (the host has no GRIB decoder and no approved wheel path), and the host stores only KB extracts. The PIT key is the run time from the filename, with `availability_basis=provider_stamp`.
7. *Book write-on-change (venue hash heartbeat).* This is an owner decision and is not on the critical path. Lossless moves come first.
8. *Label regime.* The panel runs in shadow with `label_instrument_version` and `label_kind` recorded from day one. Ledger idempotence needs an owner yes. Switching the instrument is a separate pre-registered decision after MG-1's look (by 11-15).
9. *Free space.* Runway is stated at both 142 GiB (106 documented on 10-06 plus ~36 from 91a) and 159 GiB (from the brief). Every phase gate re-reads `Get-Volume` free bytes.
10. *Open-Meteo run identity.* A sidecar `meta.json` journal comes first (roll-free). `run_init` is recorded only for single-model requests. Blended `best_match`/seamless payloads store the vector of per-model meta samples and are marked `blend_unresolved`.
11. *Embargo source of truth.* There is no third copy. PL-1 imports `maker_core/shadow/admission.py` `EMBARGO_WINDOWS` (FULL/OUTCOME kinds) and `weather.mg1_reserved_window`. Fetchers consult the same module before any request.

---

## 1 Executive summary

1. We write ~20x the information we keep: ~11.9 GiB/day written, ~4-5 GiB/day retained before NTFS, ~0.4-0.6 GiB/day of actual information (measured: efficiency-audit-2026-09-27.md:46-51). The plan fixes the write path and spends the freed disk on data that cannot be fetched again later.
2. Non-backfillable data starts first, cheapest first: foreign-city venue books and rewards (5 pilot cities, ~40 MB/day), METAR first-seen times for 51 airports, the Gamma Rules/resolutionSource journal, Open-Meteo run identity, DWD MOSMIX station MOS (2-day upstream retention), and HKO/JMA native observations. Together they add under 0.1 GiB/day.
3. A served-payload PIT extractor (FC-11) turns the raw Open-Meteo bytes we already keep (all 21 fields, including the 9 "PIT-wall" fields, since 08-08) into a columnar PIT table. This is the cheapest unblock for the retrain lane.
4. Everything new goes through one store pattern copied from 88a: hourly segments, gzip at seal, sha256 manifests, change-only bodies with heartbeats, byte budgets, disk-band brake.
5. Every new row carries first-seen time, provider/run time, an availability basis with an explicit PIT policy, parser version, raw-bytes hash, config hash and code-manifest hash. One reader, built on the project's existing embargo code, enforces PIT. The fetchers enforce the embargo too.
6. Adding a family stops restarting capture. One planned quiet-window roll splits the schema registry. After that, new families are new processes, new modules and config only.
7. The two expensive venue families (T+1/T+2 all-band books, L2 deltas) wait until the savings have landed and been measured, until the rewards change-trigger has cut 88a REST load, and until the 88a working set sits below 50% of its latch.
8. Labels: a multi-instrument panel for max **and min** across all 51 airports, in shadow. The venue has paid on weather.gov WRH since ~08-23 while we label from WU (EF §10c). The US exact-degree question (Q-09) stays undecidable unless the owner approves a disagreement-only WRH read.
9. Budgets: new families ≤1.5 GiB/day retained at full build-out (≤0.1 in Phase A). The existing lane is cut to ≤1.5 GiB/day, for a net ≤3 GiB/day. Runway is ≈60-80 days depending on the true free-space figure. New resident RAM is ≈0.4-0.5 GiB, held by a hard commit cap that is proven with a kill receipt.
10. Heavy-lease minutes are scarce, so a per-night lease timetable is part of the plan. Light HTTP jobs never take the lease. Reclaims wait until the 91a backlog is spent.
11. Backfillable sources (grids, NBH/NBS/MOS, GOES, MRMS, soundings, AFD) are not captured live. They are documented as archive-backed and fetched on the workstation when a pre-registered test needs them.
12. Owner questions gate parts of the plan: the Open-Meteo licence, WU intraday (S22), wallet identity, page tokens and registration keys, the WRH disagreement read, settlement backfill and the learning-lane unblock (Q-11), and the replay_cache and forecast_payloads deletes.

---

## 2 Principles

1. **Capture what cannot be recovered; re-acquire what can.** Rank by irreplaceability × exit-criteria value × expected value × 1/bytes. Archive-backed sources carry an availability-time rule instead of a live feed.
2. **Write each change once, and never lose the fact that we looked.** Bodies are change-only with references, and raw bytes are stored once in a CAS. Every poll writes a compact heartbeat row `(capture_id, captured_at, batch_hash, unchanged)`, so "unchanged" and "not captured" never look the same.
3. **Compress at seal, never after the fact.** Plain per-key segments, gzip-6 at seal, verified sha256. There are no long-lived per-token gzip streams. Long-window codecs run only serially at close under the lease, with stdlib `lzma` on the host.
4. **Every row is attributable.** Each row carries `first_seen_utc`, `provider_time|run_init`, `availability_basis`, `parser_version`, `raw_ref`, `config_sha256`, `code_manifest_sha`. PIT policy depends on the basis and uses the project's vocabulary (EF §1m, `forecast_training_corpus.py`):
   - `live_receipt`: `first_seen_utc` is authoritative for PIT.
   - `provider_stamp` / `s3_lastmodified`: usable for PIT only as stamp + a declared per-source latency margin, tagged `HISTORICAL_FIRST_AVAILABILITY_UNPROVEN`. These rows are never pooled with `live_receipt` rows in one fit unless the feature table has a basis column.
   - `archive_proxy`: refused for PIT training; allowed for labels and referees.
   - `stitched_no_issue`: refused for PIT.
5. **One reader, existing embargo code, fetch-side enforcement.** `read(family, as_of_utc, purpose)`, where `purpose ∈ {capture_check, outcome_join, candidate=<name>}`, hides rows with `first_seen_utc > as_of`. Windows come from `EMBARGO_WINDOWS` (FULL vs OUTCOME) and `mg1_reserved_window`, and a ratchet asserts the copies agree. Outcome-blind operational reads stay permitted. Every fetcher and backfiller checks the same windows **before** it sends a request.
6. **New families never restart the graded loops.** New modules, their own process, schema in `weather/schema_families/`, enumeration from `config/`. No edits to `io.py`, `supervisor.py`, `runtime_identity.py`, `paths.py`, `market_registry.py`, `schema_registry*`. A served-request change is allowed only when the parsed source block is byte-identical on recorded inputs, with a parser/source version bump.
7. **Served requests are frozen.** New forecast captures use new shadow source keys. Parity, release binding, probability mass and captured-input hashes stay untouched until a schema bump with a parity proof.
8. **Every family declares its caps.** RAM hard-commit cap, byte budget (per hour or per key, not per day), disk-band brake, request budget against a host-wide Polymarket and provider bucket, storage class, schema name, adoption model, licence note, embargo scope. All of it lives in `config/capture_families.json` and is checked by one ratchet.
9. **Measure before you size.** Writer-side counters replace directory walks. Every "not measured" below becomes a receipt before the family it gates lands. Available RAM, commit and free bytes come from `status.ps1`/`Get-Volume` in every gate receipt.
10. **Pay first, then add.** The expensive venue families land only after the savings are measured and the REST load is cut.
11. **Evidence is never thinned or rewritten.** Canonical families are permanent. Compress-and-retain only with hash verification. During the 88a hold (UTC 09-27..10-30) we only add files. Families referenced by `replay_inputs` are `never_offload`.
12. **Point products on the host, grids on the workstation.** MOSMIX 13 KB/run, HKO 1.5 KB, TAF ~1 KB. GRIB decoding, omfiles and zstd stay on the workstation until an owner-approved pin exists after cutover C.
13. **Light work is not heavy work.** HTTP fetches with KB writes run as bounded scheduled tasks (Job cap, 10-minute bound). The heavy lease is reserved for suites, merges, codecs, reclaims and bulk reads.
14. **Landed is not running.** Every new task, loop or registry-driven `.ps1` gets a redeploy row and a running-identity check.

---

## 3 Family table

Roll class key: **RF** roll-free (new process/modules, config, .ps1, docs). **RS** roll-sensitive (loop-imported; 01:00-04:00 via the integration-attempt runbook and `quiet_window_merge.ps1`). **88a-R** explicit 88a restart (stop the worker, let the frozen PT5M trigger restart it; never `register_maker_evidence_capture.ps1`; only 00:30-01:00, never in an LFC session window or its 30-minute update windows, gap recorded in the panel notes). **FP** fresh process. **LT** light scheduled task (no lease). Every landing of any class goes through `quiet_window_merge.ps1` in a named slot. `docs_light_path.ps1` is for Markdown-only diffs.

### 3a Platform (prerequisites)

| Family | Status | What | Cadence | Format | Bytes/day | RAM | PIT | Value case | Roll |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PL-1 `weather.evidence` writer + reader | new | Domain-neutral segment journal in **new modules**, modelled on `maker_evidence_store`: writer lock, plain per-key segments rotated hourly or at 100 MB, verified gzip at seal, manifest (sha256/bytes/records/offset), change-only bodies + heartbeat rows, cap/gap rows in-journal, daily seal chained by `prev_seal_sha256`. Reader `read(family, as_of_utc, purpose)` imports `EMBARGO_WINDOWS` + `mg1_reserved_window`; per-basis PIT policy (§2.4); fetch-side `embargo_guard(family, event_date)` | library | `.jsonl` → `.jsonl.gz` + `manifest.json` | <1% overhead | ≤8 MiB buffer/family | defines PIT | Makes later tests leak-free | RF (verdict) |
| PL-2 schema_families split | change | Loop-needed specs frozen in core; `weather/schema_families/<family>.py` not imported by loops; audit aggregates both; `landing_preflight_rollclass_schema` classifies family-only diffs roll-free | once | Python | 0 | 0 | schema version per row | Every new SchemaSpec rolls all 4 closures today (DELEGATION_CONTRACT.md:187-194) | **RS once** |
| PL-3 `config/capture_families.json` + ratchet | new | Per family: task, entry module, status path, lock, adoption model, RAM cap, byte budget, band policy, request budget (host-wide Polymarket and provider buckets, swarm-expansion :188), storage classes, schemas, embargo scope, licence. Read by `roll_verdict.ps1`, `status.ps1`, `staleness_sweep.ps1` and the resource gate; drops retired `clob_enrichment`. **A test asserts that the registry-driven `roll_verdict` reproduces today's verdict for the current tree before it becomes binding.** Adds the `config/scheduled_tasks.json` rows and OPERATING_REFERENCE regeneration that `tests/operations/test_ops_script_ratchets.py` requires | static, per cycle | JSON | 0 | 0 | `config_sha256` stamped | Replaces hand-wiring in ~10 places | RF (config/.ps1); per-task redeploy row (scheduled tasks run frozen script text) |
| PL-4 code/config identity CAS | new | At process/child start: `{path: git blob sha1}` for loaded repo + config files; stored once; referenced by manifests and status | per start | gz JSON + CAS | ~0 after first tens of MB (not measured) | negligible | which code served | 89/413 fingerprints resolve (EF §1k) | RF new families; RS when wired into snapshot loop |
| PL-5 per-family telemetry | new | Writer-side counters (bytes appended, segments sealed, peak RSS, cap-hit hours) in throttled status; daily per-family ledger. **No `data_retention_inventory` walk in Stage A.** If an inventory is wanted it runs at most weekly as a leased, Job-capped one-shot outside Stage A | continuous | small JSON | <100 KB | 0 | n/a | Turns every "not measured" into a receipt; 10-02 ~23 GiB burn unexplained | RF new; CLOB counters land with S8b |
| PL-6 `WeatherEvidenceHost` task | new | S4U/Limited, IgnoreNew, priority 10, fixed RepoRoot, writer lock. Parent only supervises **long-lived** per-family children. Each child sits in a Job object with **hard commit limit** (reuse the Stage-A/snapshot containment code, not `windows_kill_on_close_job.ps1`, which sets only KILL_ON_JOB_CLOSE, nor `long_job_guard.py`'s soft working-set limit). `WeatherMemoryCommitGuard` excludes `-m weather.*` workers (HOST_LOAD_POLICY rule 3), so this cap is the only bound. Optional channels pause 09:30-11:55 and when available physical < 5,120 MiB + declared caps | 1-min repetition (supervisor) | n/a | n/a | parent ≤64 MiB; child caps set from the S0(i) workstation bench ([receipt](../research/data-layer-v2-s0-2026-10-15/README.md)): the 88a/exec-tape import set commits ~23 MiB; any numpy importer commits ~775-816 MiB uncapped (OpenBLAS per-thread buffers), ~17 MiB with `OPENBLAS_NUM_THREADS=1`, so numpy children need the cap | n/a | One Scheduler row, one RAM envelope, no per-minute Python launches | RF (registrar .ps1); **kill receipt before S4** |

### 3b Venue (International Polymarket)

| Family | Status | What | Cadence | Format | Bytes/day | RAM | PIT | Value case | Roll |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VR-1 88a recorder, generic universe | change | Recorder-only rows from `capture_families.json` (default path, no new CLI args) `(location_id, series, slug prefix, tz, horizons, band policy)`, reloaded per cycle. **The 12 built-ins stay on `all_specs()` through 10-30**, with a ratchet that built-in ids and per-city selection size cannot change under any config state. P1 pilot London/Shanghai/Paris/Seoul/Tokyo; P2 all T+1/T+2 bands for 12 cities; P3 lowest series; P4 remaining cities in tranches of 10 by volume. Branched from master **after #177 lands**. Before S2, check the 10-01 maker-P&L pre-registration for a code-identity/behaviour freeze; if one exists, S2 waits until after 10-30 or gets an owner amendment | 60 s books/rewards (change-triggered after S9), WS trades | `maker_evidence_v2` (unchanged) | measured 0.8 MB/cond-day, 7.1-7.7 MB/city-day (swarm-expansion-2026-10-01.md:58). P1 ≈40 MB; P2 ≈+0.3 GB; P3 ≈+0.1 GB; P4 ≈+0.5 GB (est.) | measured 47 MiB at 96 cond. Full build-out is **several thousand conditions** (12 × ~33 bands × 3 days × 2 series + 39 cities), not ~1,200, so RAM, REST and cap are re-derived from P1 receipts; provisional cap 384 MiB | as received; not backfillable | Venue rank 1-2 | 88a-R; RF for graded loops (verdict) |
| VR-1 latch guard | new rule | 88a stops **all** capture, the 12 built-ins included, when the uncompressed working set reaches `MAX_RAW_BYTES = 500_000_000` (maker_evidence_store.py:20). Each phase is gated on `peak_raw_working_bytes` (read through `status.ps1`, not a data walk) < 50% of that. Any change to `MAX_RAW_BYTES`/`ROTATE_BYTES`/`DEFAULT_STREAM_CAP` is an 88a code change that needs its own verdict and an owner yes | per phase | n/a | n/a | n/a | n/a | Prevents a widening from blacking out built-in capture inside the panel window | n/a |
| VR-2 L2 delta journal | new | `book`/`price_change`/`tick_size_change` frames the exec tape discards (`execution_tape_store.py:158-160, 861-862`). A bounded in-memory queue feeds a **separate writer thread/process** that drops and counts on overflow, so trade retention is never blocked. Plain per-market segments with per-token grouping, gzip at seal. Policy: every `price_change`, books on change only. **Budget per (token, hour)**, priority under pressure T+0 near-close > T+1 rewarded bands > rest; an explicit `cap`/`gap` row in-journal. Policy pre-registered before S0(a) | event-driven | PL-1 segments | S0(a) measured one night ([receipt](../research/data-layer-v2-s0-2026-10-15/s0a-l2-delta-bytes.md), 01Z-11Z only): raw payload ≈3.1 GB/day for the T+0 exec-tape universe (264 tokens), ≈7.0 GB/day with T+1; per-(token, hour) p95 1.8 MB (T+0) / 1.9 MB (T+0+T+1), p99 7.7 / 5.7 MB; a p95 budget drops 45% / 26% of bytes (heavy tail); post-gzip not measured; US daytime hours not sampled | ≤128 MiB, queue-bounded | not backfillable | Only route to cancel-vs-fill and f (EXREG :282) | **RS** (exec-tape closure); needs S0(a) receipt + Ethernet decision (DECISION_LOG 10-02) first |
| VR-3 Gamma event + Rules journal | new | Change-only, hash-keyed `/events` replies (rules, resolutionSource, negRisk, dates, clobRewards, umaResolutionStatus, closedTime, outcomePrices, volume/liquidity) for both series, 51 cities; daily `closed=true` sweep **skipping event dates in embargo windows** (fetch-side guard); source-change gate (WARN first) vs `locations.json`. **Writes only its own journal under `data/`.** `WeatherLocationConfigRefresh` stays the sole writer of `config/location_market_events.json` (exec tape reads it fail-closed, 36 h max age, `execution_tape_capture.py:41,66-81,106-118`). Deriving the file from the journal later is a separate change to `location_config_refresh.py`, landed normally. No task ever runs `git commit` | 15 min; daily | PL-1 change-only | est. 5-20 MB/day (not measured) | evidence-host child | not backfillable | WU→WRH switch found ~4 weeks late (EF §10c) | RF / LT |
| VR-4 venue-wide rewards sweep + dated economics | new | `/rewards/markets/current` all ~39 pages (6.7 MB/sweep) stored change-only per condition; publishes a per-condition change flag; dated `exchange_economics` copies | 15 min; daily | PL-1 change-only | est. ≤10 MB/day gz (not measured) | child | current-only upstream | Feeds S9 trigger (−80% 88a REST) | RF |
| VR-5 trade reconciliation + prices-history backfill | new | Nightly data-api `/trades?market=<cid>` per captured condition keyed by `transactionHash` (wallet stripped pending owner). CLOB `/prices-history` 1-min **only for closed events**, once per token, deduped through raw CAS, per-night request cap, starting with 12 built-ins + pilots. **Fetch-side embargo guard**: no event date in UTC 09-30..10-15 | nightly | daily `.jsonl.gz` / CAS | est. 5-30 MB/day | ≤256 MiB | `archive_proxy` | Repairs dark gaps | LT (rate-capped ≤4 MiB/s, 00:30-01:00 slot) |
| VR-6 CLOB raw book tape | change | Hourly `.jsonl.gz` parts at write + manifest; drop embedded `token` row (~27%), join on `clob_token_id`; Gamma event cached 10 min (−~17k GETs/day); trim constant policy payload from `clob_capture_status.jsonl` from a UTC day boundary. Hash-heartbeat dedup **owner yes, gated on S0(b)** (§9 Q5: a lossless-reconstruction test with a receipt). **S0(b) passed 10-15** on 2026-08-05 (3 events, 246k rows): 0 mismatches at heartbeat 0/300/900/3,600 s, 48-49% of plaintext bytes kept; the venue hash never stayed fixed while content changed ([receipt](../research/data-layer-v2-s0-2026-10-15/README.md)); post-gzip saving not measured. Reader census first (markout, MM preflight, latest-input, exec-join) | 60/15 s | hourly gz parts | written 3.2-3.3 GiB/day plaintext → 0 plaintext; retained ≈0.25 → ≈0.18 GiB/day (est. from 10.97x measured, clob_raw_tape_tiering.py:9-12) | <16 MiB/market | not backfillable | Removes the 3.3 GiB/day sawtooth that sets the daily low | **RS** (CLOB closure) |
| VR-7 clob_tokens map | change | Static identity once/day or on change; Gamma quotes as a complete batch when a non-timestamp field changes **plus a heartbeat row per poll** (`capture_id, captured_at, batch_hash, unchanged`); `_latest_time_group` and the gap audit read heartbeats (the #118 NO-GO cause was freshness inferred from row presence); CSV twin retired after reader migration | on change + heartbeat | jsonl, gz at close | written ~1-1.5 GiB/day → est. ≤0.1 (unchanged share **not measured**) | negligible | quote series kept | Largest single write waste | **RS**; #118 ≥10-18 |
| VR-8 order_books_summary / long twins | change | Summary gz at write, later Parquet at close (workstation-built until a host wheel pin exists) with named rebuild source; long `.csv.gz` twin-parity delete only where the jsonl.gz twin proves parity, **excluding UTC 09-27..10-30, on or after 10-31**, except ~93 folders with no raw JSONL | per poll | csv.gz → Parquet | ~0.56 GiB/day plaintext → ~0.11 gz (est.) | negligible | derivative | ~0.45 GiB/day + 29-35 GiB one-time | RS (capture) / FP |
| VR-9 maker shadow tapes | change | `storage_classes` row (canonical_evidence); closed-day verified gzip; drop duplicate book capture where VR-1 holds the same band-minute | 60 s | gz at close | 126-380 MB/day → est. 15-40 MB (ratio not measured) | unchanged | unchanged | Unclassified disk slope | RF + shadow code |
| VR-10 own-account session evidence | new (envelope only) | Every attended LFC session writes its authoritative reader set and wallet-ledger snapshot into a canonical_evidence family with the PL-1 envelope (no new trading authority) | per session | PL-1 | KB | 0 | `live_receipt` | G13: the only identifier of f; gives VR-2 a join target | RF |

### 3c Observations

| Family | Status | What | Cadence | Format | Bytes/day | RAM | PIT | Value case | Roll |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OB-1 METAR/SPECI first-seen log | new | One multi-id AWC request/min for 51 ICAOs with **hours=2** for first-seen detection, plus one long sweep per station per hour that covers 00:00 local for every station (36 h if AWC accepts it, **not measured**; otherwise 24 + 12; S0(e): AWC documents no `hours`/`ids` cap, 400 results per request, 30 days of history). One row per new/changed report: station, obs_time, report_time, `first_seen_utc`, rawOb, T-group tenths, 6/24 h max-min groups, type (routine/SPECI/COR), SLP-group flag, hash. The finality snapshot (state at first datapoint of D+1 local) is tagged `instrument=awc_proxy_of_wrh` and is a **panel member, not the canonical label** (AWC ≠ Synoptic ingest) | 60 s poll, rows on change; hourly sweep | per-UTC-day PL-1 segment | stored ≈0.1 MB/day gz (est.); inbound est. 50-100 MB/day (hours=36 every minute would be ~1.9 GB/day, est.) | child | `live_receipt`; not backfillable (EF §10h) | Obs rank 1; labels for pilots and lows from day one | RF. At S10 the watcher becomes sole AWC writer for the 12 built-ins |
| OB-2 US 5-min ASOS near-real-time | new | `api.weather.gov/stations/<icao>/observations` (User-Agent only) for 11 US stations; implements declared-but-missing `nws_observations` | 5 min | PL-1 | <1 MB/day gz (est.) | child | first-seen not backfillable | Staleness loses ~40%/h of remaining-rise value (EF §10q) | RF |
| OB-3 native foreign/Toronto obs | new | HKO `latest_since_midnight_maxmin.csv` + `rhrread`; JMA bosai AMeDAS 10-min near RJTT; ECCC SWOB AUTO + CYTZ/CYKZ/Toronto City with per-file cache (fetch new names only) | 10 min; 1-5 min listing | PL-1 + CAS | HKO measured ≈1.5 KB/file → ≈220 KB/day; others est. ≤1-2 MB/day | child | latest-only upstream | Sub-degree max precision near band edges | RF |
| OB-4 observation raw-blob policy | change | Stop writing a whole-day blob per change (quadratic); new bytes go to OB-1; existing CAS frozen and compressed in place | n/a | CAS | **not measured** (one stat of a pre-09-30 closed event) | 0 | lossless | Fix quadratic growth first | RS (with DS-1) |
| OB-5 marine context | keep | Retain raw via forecast raw-retention flag; NDBC realtime2 hourly tail-parsed | hourly | existing | small | 0 | yes | Pays off only through a retrain using marine columns | RS (bundle) |
| Mesonets/PWS, GOES, MRMS values, soundings | keep (not captured) | Archive-backed or need keys; workstation research only | n/a | n/a | 0 | 0 | `s3_lastmodified` + margin | EF §10q | n/a |

### 3d Forecast / NWP

| Family | Status | What | Cadence | Format | Bytes/day | RAM | PIT | Value case | Roll |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FC-1 Open-Meteo run-identity sampler | new | `.../data/<model>/static/meta.json` per model, **30-60 min aligned to run availability** (not 10 min: ~1,440 calls/day); `run_init` assigned only to single-model requests; blended products store the per-model meta vector, `blend_unresolved` | 30-60 min | PL-1 change-only | <1 MB/day | negligible | `live_receipt` | Run identity is unrecoverable later | RF |
| FC-11 served-payload PIT extractor | new | Closed-day fresh process reads `forecast_payloads` manifests + CAS blobs and writes a compressed Parquet PIT table (market, source, model, fetched_at, run_init or null/`blend_unresolved`, valid_time, field, value, `availability_basis=live_receipt`) for all 21 served fields incl. the 9 PIT-wall fields (already requested, model_sources.py:1525-1545), GEFS members, NWS grid/hourly, ECCC citypage. Backlog since 08-08 on the workstation; on the host one closed day per night (outcome-blind, allowed in the MG-1 window) | nightly | Parquet (built on workstation until a host wheel pin; host writes gz JSONL) | KB-MB/day | ≤512 MiB, lease | `live_receipt` | Unblocks EXREG row 24 / L7 / G3, orders 7, 12, 15 | FP |
| FC-2 shadow ensembles | new | **New source key**: `ecmwf_ifs025` ENS, `icon_seamless_eps`, `gem_global_ensemble` (+AIFS ENS), T2m + daily max, `forecast_days=4`; 12 cities + pilots; fetched outside 12:00-18:00 | 4x/day | CAS + member table | est. 3-10 MB/day (not measured) | child | past-date ensembles return 0/24 | Spread for tail/mass work | RF; licence risk accepted (§9 Q1) |
| FC-3 per-model members | new | Shadow AIFS, GraphCast, IFS, AIGFS, ICON, GEM, JMA, UKMO, MF, CMA, KMA for T2m and the 9 fields; **only what S0(d) shows is not already in the served payload** (S0(d) map: other fields, unrequested models, members beyond GEFS T2m, daily max/min, 15-min T) | 4x/day | CAS + columnar | est. 5-15 MB/day | child | no provider documents first-availability (EF §1m) | Per-model members for the retrain lane | RF; licence risk accepted (§9 Q1) |
| FC-4 DWD MOSMIX_L | new | Single-station KMZ (TX/TN, hourly TTT to 240 h) for every settlement airport with an id (RJTT=47671; rest mapped in S0) | 4 runs/day | KMZ in CAS + extract | measured 13.3-13.6 KB/run → ≈2.8 MB/day for 51 | trivial | upstream ~2 days | Only free station MOS for non-US cities | RF; licence is CC BY 4.0 per DWD's current legal notice, not GeoNutzV (S0(f)) |
| FC-5 Toronto native guidance | new | CYYZ UMOS/PROGNOS GeoJSON per run (evidence host); HRDPS point extract **on the workstation** nightly for yesterday's 4 runs, KB extract shipped to host | per run; nightly | extract rows + hash | <1 MB/day stored on host | UMOS child | `provider_stamp` + margin | Toronto has no NBM; S13 never scored | RF / workstation |
| FC-6 TAF TX/TN | new | AWC TAF for 51 airports, raw + parsed | nightly batch + 6-hourly for pilots | PL-1 | ≈0.3 MB/day | trivial | provider issue time | Forecaster max/min for ~1 KB | LT |
| FC-7 Previous Runs forward fetch | new | Daily pull of yesterday, all 12 free PIT fields × leads 1-7 (`forecast_history.py:692` requests temperature only); reviewed adoption of the staged `C:\tmp\pit-refetch-2026-08-10` corpus after hash verification | daily | CSV/Parquet | KB/day | ≤256 MiB | fixed-lead offset; `HISTORICAL_FIRST_AVAILABILITY_UNPROVEN` | Series frozen since 06-23 (EF §1e) | LT |
| FC-8 NBM NBP path | change | Parser v2 (#190); 83b held-cycle reuse; CAS compress-on-write; strip `raw_payload` from `last_good_sources.json` and skip the save when unchanged (S0: `model_sources.py:596-619` rewrites the whole ~36 MB file every pass, est. 5.2 GB/day writes per US station at the 10-min default; host cadence not confirmed); day-2 max offline | 6 files/day | CAS | ≈210 MB/day → est. ≤40 MB; network ≈40 GB/day → ≈0.2 GB (EF §10l) | removes repeated 35 MB loads | v1 rows flagged | Largest avoidable burn | **RS** |
| FC-9 served payloads + projections | keep (storage change) | **KEEP ALL** raw served payloads; compress per-market blobs at write; `generationtime_ms` outside hashed body; rows only on hash change; twins stop after reader migration | unchanged | CAS | ≈69 MiB/day logical → est. ≤15 MiB | unchanged | sole archive | Irreplaceable | RS; after parity proof |
| FC-10 Open-Meteo S3 `data_run/` reader | new (feasibility) | CC-BY per-run point reads as licence-clean exact-run path; **workstation only** (omfiles not on host). S0(h): feasible; 70 models, no KMA, no members; 90-day expiry; range reads supported; needs the `omfiles` wheel (GPL-2.0) + range shim | per run | OM range reads | est. 15-30 MB/day (bytes per point not measured) | not measured | exact run identity | Optional (licence risk accepted, §9 Q1; no longer an exit requirement) | later |
| Grids/MOS/AFD/soundings/RTMA | keep (not captured) | Archive-backed; workstation only | n/a | n/a | 0 | 0 | proxy + margin | Soundings and MOS TESTED-NULL; AFD KILL (2026-10-25, EF §10ah); **RTMA/URMA NOT TESTED** (corrected 2026-10-26, [exhaustion register](EXHAUSTION_REGISTER.md) S32) | n/a |

### 3e Labels, settlement, integrity

| Family | Status | What | Cadence | Format | Bytes/day | RAM | PIT | Value case | Roll |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LB-1 multi-instrument label panel | new | Per station-day, 51 ICAOs, **`label_kind ∈ {max, min}`**: WU daily (where restored), METAR-all, **METAR-hourly = routine reports carrying an SLP group** (WRH "Hourly Data" rule, EF §10c, derived from rawOb; no minute window; foreign WRH cities use METAR-all, documented 50/50), IEM 6 h composite, 1-min ASOS (US), CLI/CF6 (US, LST-flagged referee), HKO Daily Extract, **ECCC climate-daily for Toronto (all months)**, OB-1 finality proxy, venue winner (referee). Agreement flags; `label_instrument_version`; local-day start explicit per tz; every finality-proxy vs IEM-D+2 difference recorded as a COR event. Driven from `locations.json`. Missing-range sweep **skips embargo dates** at fetch time. **Shadow only.** Runs as a light task 00:30-01:00; the Stage-A step only reads `label_panel.jsonl` (fail-soft WARN on absence) | daily D+1, re-read D+2 | raw gz + `label_panel.jsonl` | ≈0.5-2 MB/day | ≤256 MiB | finality proxy `live_receipt`; others `archive_proxy` | Venue pays on WRH while we label on WU; lows need min labels from P3's first day | LT + Stage-A read step |
| LB-1 caveat | n/a | The US exact-degree question (Q-09) **cannot close under this plan** unless the owner approves a disagreement-only WRH page read (one GET per station-day only where METAR-all and METAR-hourly disagree at the degree, est. 5-10% of days) | n/a | n/a | n/a | n/a | n/a | Says plainly what the panel cannot decide | owner Q4 |
| LB-2 IEM METAR history refresh | change | Revive `data/metar` (stopped 06-30): raw text, `report_type` 3,4, sky, p01i, peak_wind; 51 ICAOs; 15 s spacing | nightly (shares LB-1) | gz CSV | ≈0.5 MB/day | ≤256 MiB | `archive_proxy` | 480/480 degrees, 504/504 bands (EF §10c) | LT |
| LB-3 settlement ledger | change | Exclude `finalized_at_utc` and whole-file hashes from the label hash (`settlement_ledger.py:1213-1219, 1325`); append only on content change; record `label_instrument_version`; countability unchanged | daily | JSONL | shrinks | lower | n/a | Real revisions buried in churn | FP; **owner yes** |
| LB-5 settlement coverage | new | Daily outcome-blind count of post-10-09 market-days lacking a `promotion_countable` ledger row; with owner yes, `settlement_backfill_one` per missing day under the lease. For embargo dates the step writes ledger rows only; no agent reads the outcomes | daily | status count | ~0 | FP | n/a | URGENT EXREG orders 1 and 6 need countable dates; each lost day pushes 11-23/~12-02 later | FP; **standing owner yes** (§9 Q8: always fill; writes outcome-blind, no reading of reserved-date contents); Q-11 to be scheduled |
| LB-4 declared settlement config | change | After MG-1 look: normalize `source_type` spellings; generate the declared block from VR-3 Rules; record the venue's "Hourly Data" definition in `resolution_view` for 11 US cities; **read and record the US and Toronto Rules finality clauses** (documented today only for five foreign WRH cities) | once | config | 0 | 0 | n/a | 39 cities declare WU while the venue names WRH | RF |
| WU-1 WU intraday as-of | new (gated) | Hourly public-page history, token redacted, raw gz, no serving use | hourly | raw gz | est. ≤20 MB/day | child | not append-only | Q-21/L18 anchor | RF; in scope (§9 Q2): shadow, redacted, token never logged |
| DS-0 stage-vector sidecar | new | Additive-only JSONL family written by the snapshot child for **post-processing stages not already persisted** (audit `distribution_stage_attribution.py` first); no change to `replay_inputs` hash semantics. Allowed under the MG-1 reservation (served vectors and captures exempt) | per serve | PL-1 | not measured (est. small) | negligible | `live_receipt` | L17/L19, EXREG order 16; non-backfillable; ~6 weeks earlier than DS-1 | **RS** (bundled with S10) |
| DS-1 served-path refactor | change (later) | `replay_inputs` references OB-1 by **segment sha256 + row-range digest** (so `captured_input_hash` still pins content), or keeps delta-embedding (new rows since the last snapshot) if the parity proof prefers self-containment. MRMS listing removed; FC-1 run_init in manifest; PL-4 wired in; OB-4 policy | served | schema bump | ≈0.9 GiB/day logical → est. 0.4-0.6 (not measured) | lower | hash continuity via bump + parity proof, **including a replay with the OB-1 segment restored from Drive** | Quadratic blobs | **RS**; after MG-1 window |
| MRMS listing in replay rows | retire | Zero information (`available=False` always, `mrms_precip.py:274-330`) | n/a | n/a | −0.1-0.2 GB/day logical (est.) | lower | nothing lost | | RS (with DS-1) |

### 3f Storage lane (existing bytes)

| Family | Status | What | Cadence | Format | Bytes/day | RAM | PIT | Value case | Roll |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CP-1 close-time long-window codec | change | S0(c) bench done: xz-6 is 1.2-3.4x better than gzip-6 (16-27 MiB/s on JSONL, ~4 MiB/s on forecast blobs); zstd not available; host uses stdlib `lzma` (zstd only after an owner wheel pin); compress-and-retain closed `replay_inputs`/`variant_predictions`; codec-aware opener | nightly, one chunk | `.xz` + manifest | est. ≤0.05 GiB/day retained (**not measured**); historical ≈+20 GiB over LZNT1 (est.) | ≤512 MiB | lossless | Largest canonical family (82.5 GiB) | FP; after 91a backlog |
| CP-2 clob_tokens backlog gzip | change | gzip closed `clob_tokens.csv/.jsonl` (20-74x vs ~3x). **Reader census first**: `market_latest_inputs.py:326`, `market_making_preflight.py:824`, `portable_live_candidate_preflight.py:101,231`, `public_capture_inputs.py:137` must read only open days or go through `closed_market_day_archive.py:188` | at most one night in three, after the 91a backlog is spent | `.gz` | one-time ≈+35 GiB over LZNT1 (est.) | FP | lossless | | FP |
| CP-3 approved reclaims | retire | `replay_cache` 32.3 GiB **only by owner-signed exact manifest**; long-CSV twins only with twin parity and excluding UTC 09-27..10-30, **on/after 10-31**; logs/failed stages ~12 GiB **excluding exam roots and pinned worktrees** (drive-offload-2026-10-02.md:176); LOCAL_WITH_CLOUD_COPY 1.55 GiB after reader-safety fixes. **The legacy `forecast_payloads` dedupe is removed from this row** (it is the only issue-time archive; owner question with restore-verified hashes) | one bounded chunk/night, lease | exact manifests + checksums | ≈45-75 GiB one-time (est., after removing the ~30 GiB dedupe and gating replay_cache on a manifest) | bounded | lossless | Funds venue expansion | RF ops |
| CP-4 tiny-file consolidation | change | `price_history_raw` 3.46M files / 21.3 GiB, `fetch_fanout` ~650k → tar per event subtree | after 91a backlog | tar.gz | not measured; file count −~1000x | FP | lossless | MFT slack | FP |
| CP-5 91a (WOF/LZX evaluation) | change | Gate met: S0(c) measured LZX 3.0-7.3x over LZNT1 on every family tested; add native path + verifier extension in the renewal | nightly | NTFS WOF | est. +50-100 GiB (not measured) | bounded | transparent | | pinned-deployment review |
| Snapshot CSV/JSONL twins | change (later) | Parquet projections via `closed_market_day_archive`; retire plain CSVs only after drive-offload D1 and reader migration (labels/settled_days treat a missing CSV as a missing day; census by name) | nightly | Parquet | ≈0.43 GiB/day (est.) | FP | derivative | | FP + reader migration |

---

## 4 Budgets

### 4a Disk per day (retained, after compression)

| Item | Today | Target | Source |
| --- | --- | --- | --- |
| Existing lane, before NTFS | ~4-5.3 GiB/day | n/a | storage-plan-2026-09-23.md; swarm-expansion :40-58 |
| Existing lane, after 91a | ~1.4-3.2 GiB/day | **≤1.5 GiB/day** after VR-6/7/8, FC-8/9, VR-9, CP-1 | est. |
| Written bytes | ~11.9 GiB/day | ≤6 GiB/day | measured 10-01; targets est. |
| New Phase A | 0 | **≤0.10 GiB/day** | est. from measured unit costs |
| New Phase C (P2 0.3 + P3 0.1 + VR-2 per S0(a)) | 0 | **≤0.65 GiB/day** provisional | est.; VR-2 raw measured at ≈3.1 GB/day (T+0) to ≈7.0 GB/day (T+0+T+1) by S0(a), so it fits only at ≈11-26x gzip (not measured) |
| New Phase D | 0 | **≤0.50 GiB/day** | est. ≈8 MB/city-day/series |
| New families ceiling | n/a | **≤1.5 GiB/day** | plan |
| **Net steady target** | +2.3 to +4.5 GiB/day (est.) | **≤3.0 GiB/day** | plan |

### 4b Headroom

Before every gate, read `Get-Volume` free bytes, the 24 h trail low, available RAM and commit from `status.ps1`, and put them in the gate receipt. The 159 GiB and ~7 GB figures come from the brief, not from receipts (10-01 measured 8.3 GB free RAM, swarm :49).

| Scenario | Free now | To Green floor (75) | + one-time reclaims (CP-3 ≈45-75, CP-2 ≈35, CP-1 ≈20) | Runway at 3 GiB/day |
| --- | --- | --- | --- | --- |
| Documented (106 + ~36 from 91a) | 142 GiB | 67 GiB | ≈100-130 GiB | ≈55-65 days |
| Brief | 159 GiB | 84 GiB | ≈100-130 GiB | ≈60-70 days |

- After the reclaims the Drive cold tier becomes a monthly campaign from about late November or December. That needs the event-day manifest backlog (48 of 1,357 folders) fixed first.
- The 91a backlog ends ~10-20..24 (est.) and the policy expires 10-30. An unresolved failed attempt blocks every later night, so it must be resolved the same morning.
- Bands (24 h trail low): Green ≥75, Amber 60-75, Red 50-60, Critical <50 GiB. **Shed order:** Amber → VR-2 per-hour budgets halve (priority order kept), nightly backfills pause. Red → VR-2 stops, VR-1 P2 falls back to 10 conditions/city, optional evidence-host channels stop. Critical → 88a's own brake. Canonical history is never shed.
- **Phase gates:** Phase C opens only when (a) 7 days after S8c are within budget, measured by `Get-Volume` deltas at the 24 h low, WeatherClobRawTapeTiering hand-back receipts and 91a manifest sizes (PL-5 CLOB counters ship with S8b); (b) the 24 h low is ≥90 GiB; (c) 88a `peak_raw_working_bytes` is <250 MB; (d) S9 has run 3 days with zero 429s. Phase D opens at ≥85 GiB with the existing lane ≤1.5 GiB/day.

### 4c RAM (16 GB physical; snapshot admission needs 5,120 MiB for two 1,792 MiB slots + 1,536 MiB reserve; Stage-A children need expectation + 1.5 GiB, WU restore 4,096 MiB)

| Worker | Hard cap (Job commit limit) | Expected | Source |
| --- | --- | --- | --- |
| Evidence host parent | 64 MiB | ~30 | est. |
| Evidence host long-lived children | ~23 MiB commit for the 88a/exec-tape import set (S0(i), workstation); numpy importers need `OPENBLAS_NUM_THREADS=1` | ≤100 each | est. |
| VR-1 88a after P1-P4 | provisional 384 MiB, re-derived from P1 | 150-250+ | measured 47 MiB @96 cond.; extrapolated |
| VR-2 writer | +128 MiB, queue-bounded | ≤60 | est. |
| Watcher convergence (S10) | +16 MiB | ≤10 | est.; watcher RSS not measured |
| **Steady new resident** | **≤~1 GiB caps** | **≈400-500 MiB** | n/a |
| Nightly fresh children (FC-11, CP-1/2, LB-5) | ≤512 MiB, one at a time, lease only | n/a | plan |

Rules:
- Caps are enforced by the Stage-A/snapshot hard-commit containment code, proved with a kill receipt before S4. `WeatherMemoryCommitGuard` does not cover `-m weather.*` workers.
- Declared ceilings are added to `capture_resource_gate`'s reserve.
- Optional channels pause 09:30-11:55, whenever available physical RAM < 5,120 MiB + declared caps, and whenever available RAM is <5.6 GiB at the 24 h low on 2 days.
- Offsets: FC-8 removes repeated 35 MB bulletin loads; the `last_good` strip still needs to be verified with a stat. Long-window codecs never run per open stream.

### 4d Network and API budgets

- **Host-wide Polymarket request bucket** (swarm-expansion :188) shared by every caller and declared in PL-3. 88a REST ≈1.9 req/s today, ~83% of it the per-condition `/rewards` GET. **S9's trigger lands with or before S2**, taking it to ≈0.3 req/s before any widening. **Any HTTP 429 on any Polymarket caller stops all widening until root-caused** (the approved swarm guard, :227).
- NBM ≈40 GB/day → ≈0.2 GB/day after 83b (EF §10l). OB-1 inbound est. 50-100 MB/day. Every nightly bulk fetch (VR-5, FC-7, LB-2) is capped at 4 MiB/s, confined to its slot, and aborts on any capture reconnect increase (Wi-Fi shows ~8 reconnects/h). HRDPS bytes stay on the workstation link.
- Open-Meteo free tier: 10,000 calls/day weighted. The evidence host keeps a **hard daily meter that stops shadow calls at a fixed fraction of the measured production call count**, before any 429. A provider 429 trips the shared family cooldown that gates served fetches (`model_sources.py:457-475`). Shadow fetches run outside 12:00-18:00. FC-10 is preferred once it is feasible.
- IEM: 15 s spacing (86a saw 429). AWC: 100 req/min documented; OB-1 uses ~1-2% of it.
- Workstation measurements share the home egress: confirm the exec-tape and 88a connection counts first, use one connection, run outside 12:00-18:00, and stop on any production reconnect spike.

### 4e Retention

- All new recorder families are `canonical_evidence`: permanent, gzip at seal, sha256 manifests, `storage_classes` rows (ratchet over `capture_families` path patterns). `.gz` files leave 91a scope.
- Families referenced by `replay_inputs` after DS-1 (OB-1, FC-1 journal) are **`never_offload`**.
- Batch families are `source_history_with_provenance`, HOT. CAS raw is never GC'd.
- During the 88a hold (UTC 09-27..10-30) we only add files. Projections name a rebuild source.
- The cold tier is used only through a restore-verified archive. The rclone crypt keys are already off Drive (DECISION_LOG 2026-10-02); the restore-verify condition stays.

### 4f Per-night lease timetable (capture host)

| Slot | Owner | Rule |
| --- | --- | --- |
| 00:30-01:00 | light scheduled tasks (LB-1/LB-2, FC-6, FC-7, VR-3 close sweep, VR-5), 88a restarts | no lease; Job cap; 10-min bound each; never overlapping a lease holder's start |
| 01:00-04:00 | **exactly one integration attempt** (pre-gated suite + merge), RS or RF | one lease holder; integration-attempt runbook |
| 04:00-04:45 | one bounded nightly fresh process (FC-11 day, CP-1/CP-2/CP-3 chunk) | lease; only after the 91a backlog is spent for CP items; CP-2/CP-4 at most one night in three |
| 04:45-06:45 | tiering reserve | untouched |
| 06:50-09:00 | 91a | untouched |

The rule ("every suite/merge night costs a 91a night", swarm :52) is honoured by keeping merges out of 06:50-09:00.

---

## 5 Efficiency moves with estimated savings

| # | Move | Saving | Basis |
| --- | --- | --- | --- |
| M1 | Writer-side per-family counters (PL-5) | turns every "not measured" into a receipt | plan |
| M2 | One segment writer for every new family | 5-20x less disk than snapshot-style plaintext | measured gzip 4.9-20x (storage-plan-2026-09-23.md) |
| M3 | Market-invariant fetches (AWC multi-id hours=2; meta.json per model; one rewards sweep) | fetch count independent of city count; OB-1 inbound ~1.9 GB → ~0.1 GB/day (est.) | plan |
| M4 | Point products on host; grids on workstation | 50-1,000x fewer host bytes | free-universe sweep |
| M5 | clob_tokens on-change + heartbeat; drop embedded token row | written −1.9 to −2.4 GiB/day | est.; unchanged share not measured |
| M6 | Hourly gzip of raw books + Gamma cache | removes 3.3 GiB/day sawtooth; −~17k GETs/day | measured sawtooth |
| M7 | NBM 83b reuse + CAS compress + last_good strip | network −~40 GB/day; disk −~0.15 GiB/day | EF §10l |
| M8 | 88a rewards change-trigger + 1 s grouped fsync | REST −80%; IOPS −90% | swarm-expansion B/C#2 |
| M9 | Long-window codec at close (stdlib lzma); gzip for clob_tokens backlog | retained −~0.2 GiB/day; +~20 / +~35 GiB historical | codec ratios measured (S0(c)); retained bytes est. |
| M10 | Do not capture backfillable sources live | 0 host bytes | p0.md:28-46 |
| M11 | SWOB per-file cache; NDBC hourly tail-parse; DS-1 refs | removes quadratic re-downloads | not measured |
| M12 | Approved reclaims with exact manifests | ≈45-75 GiB one-time | storage-value-assessment-2026-09-26, reduced |
| M13 | Shared WS subscriber (5 → 3 sockets) | halves ~15 GB/day inbound | **owner decision** |
| M14 | Per-market fast interval | −~2 GB/day written | **lossy; owner decision** |
| M15 | Long-lived evidence children instead of per-minute launches | removes thousands of Python starts/Defender scans per day | review; not measured |
| M16 | FC-11 extracts what we already keep | retrain-lane PIT table at ~0 new fetch | model_sources.py:1525-1545 |

---

## 6 Non-backfillable data to start capturing first (ranked)

| Rank | Data | Why it is lost each day | Cost | Earliest |
| --- | --- | --- | --- | --- |
| 1 | Venue books + rewards + trades for 5 pilot cities (VR-1 P1) | `/orderbook-history` indicative only; rewards current-only | ≈40 MB/day | 10-21 night (with S9) |
| 2 | METAR/SPECI first-seen, 51 ICAOs + finality proxy (OB-1) | report-to-availability lag not in any archive (EF §10h) | ≈0.1 MB/day stored | 10-22 |
| 3 | Gamma Rules/resolutionSource journal (VR-3) | 6-hourly overwrites only | 5-20 MB/day | 10-22 |
| 4 | Open-Meteo run identity (FC-1) | unrecoverable later | <1 MB/day | 10-22 |
| 5 | DWD MOSMIX_L (FC-4) | upstream keeps ~2 days | ≈2.8 MB/day | 10-22 |
| 6 | HKO/JMA/SWOB native obs (OB-3) | latest-only | ≤2 MB/day | 10-22 |
| 7 | Venue-wide rewards sweep + dated economics (VR-4) | current-only | ≤10 MB/day | 10-21 (with S9) |
| 8 | Stage-vector sidecar (DS-0) | served stage vectors not reconstructable | small | 10-29 night (with S10) |
| 9 | Lowest-temperature series (VR-1 P3) with min labels | as rank 1 | ≈0.1 GiB/day | after S9 + LB-1 min (~10-24) |
| 10 | Shadow ensembles + members (FC-2/FC-3) | past-date ensembles return 0/24 | 3-25 MB/day | licence risk accepted |
| 11 | US 5-min ASOS first-seen (OB-2) | first-seen not backfillable | <1 MB/day | 10-22 |
| 12 | T+1/T+2 all-band books (VR-1 P2) | ~2/3 of bands never captured | ≈0.3 GB/day | after Phase C gate, after OD28 (≥11-02) |
| 13 | L2 book deltas (VR-2) | frames discarded today | per S0(a) | ≥11-03 night |
| 14 | Code/config identity (PL-4), own-account session envelope (VR-10) | served code not reconstructable | ~0 | with each family |
| 15 | WU intraday as-of (WU-1) | not append-only | ≤20 MB/day | in scope (§9 Q2) |
| — | FC-11 (backlog extraction) and FC-7 forward fetch | backfillable or already kept; highest exit-criteria value per byte, so they run in parallel and are not ranked | KB/day | FC-11 workstation from 10-15; FC-7 10-23 |

---

## 7 Build sequence

**Every capture-host landing** goes through the integration-attempt runbook (`docs/operations/INTEGRATION_ATTEMPT_RUNBOOK.md`):
- a frozen per-attempt manifest and pre-registered `WeatherIntegrationSuite_*`/`Merge_*` one-shots;
- a workstation pre-gate by 21:30 bound to the night's base SHA (OD34/OD35);
- a merge simulation on **host git 2.45** (merge-tree + commit-tree);
- the 50 GiB suite floor judged at the daily low;
- the journal-pin check (WeatherManualOrderJournal exits 3 if a merge touches one of its five pinned files);
- the `roll_verdict.ps1` verdict;
- then `quiet_window_merge.ps1` in its §4f slot.

Only Markdown-only docs use `docs_light_path.ps1`. A failed attempt freezes the night and is resolved by 09:00.

Calendar:
- 10-15 night: #177
- 10-16: pyup B; 10-17: cutover C (G5 no-merge both nights)
- 10-18: #190/#182/#172 (#118 ≥10-18)
- #162 ≥10-19
- 88a hold to UTC 10-30; panel OUTCOME window 10-15..11-13
- 91a renewal week of 10-26; OD28 DST re-registration ~10-30 (no .ps1/task changes that day)
- 05-F3 skips the sequencer on the 10-31→11-01 night; OD30 forbids merge/suite 01:45-02:15 on 11-01
- MG-1 look by 11-15

| # | Step | Who | Earliest | Roll | Verify |
| --- | --- | --- | --- | --- | --- |
| S0 | **(b)-(f), (h)-(k) done 10-15; [receipts](../research/data-layer-v2-s0-2026-10-15/README.md). (a) done 10-16 ([receipt](../research/data-layer-v2-s0-2026-10-15/s0a-l2-delta-bytes.md); one night, 01Z-11Z full hours, ended by the reconnect abort rule at 12:56Z). The rest of (g) owed.** **Measurement pack** (workstation, no host load): (a) L2 delta bytes from one public market-channel connection started **no earlier than 2026-10-16 00:00Z**, outside 12:00-18:00, aborted on production reconnect spikes, byte totals only; (b) unchanged venue-hash and token-quote fractions on a **closed day before 09-30**; (c) codec bench on copies of pre-09-30 files; (d) trace one served Open-Meteo payload for fields and members (deliverable: field map feeding FC-11/FC-3); (e) MOSMIX id map, AMeDAS station for RJTT, TAF TX/TN, **AWC `hours`/`ids` ceilings and bytes/request**, a Synoptic-vs-AWC report-set difference on a few pre-09-30 station-days; (f) licence sheet (Open-Meteo, verified against the current terms page, DWD, JMA, HKO, Met Office, Meteostat); (g) **one host stat** in the admitted window: `last_good_sources.json` sizes, one pre-09-30 closed event's `observation_payloads` size, and the `Get-Volume`/`status.ps1` RAM/commit reading recorded in STATE_OF_PLAY; (h) S3 `data_run/` feasibility; (i) `python -X importtime` + RSS for the evidence-host import set; (j) read the 10-01 maker-P&L pre-registration for an 88a code-identity freeze; (k) confirm exec-tape and 88a WS connection counts | workstation via `workstation_heavy.ps1`; host stat by ops | 10-15 (workstation); host stat 10-16 00:30-01:00 | none | receipts in findings digest / storage plan; each replaces a "not measured" before its family lands |
| S0b | **FC-11 backlog extraction** on the workstation (pre-09-30 and post-10-15 days only for any analysis; extraction itself is outcome-blind) | workstation | 10-16 | none | PIT table row counts match manifest counts per day |
| S1 | **S1 built 3055f9fca on branch `claude/dlv2-s1-platform-stack6-20261015` (base `claude/integration-20261018-stack6` @ cf8cfe6ae), not landed;** owner: [platform contract](DATA_LAYER_V2_CONTRACT.md), which records the WMO finding (ids unchanged) and what S1 deferred (`storage_classes.py` rows: deferred-reachable from the snapshot loop, not roll-free). **Roll-free platform:** registry finding to resolve: `config/locations.json` WMO ids disagree with the DWD catalogue for Munich and São Paulo, and Kuala Lumpur, Chengdu and Taipei have no DWD entry ([S0(e)](../research/data-layer-v2-s0-2026-10-15/s0ef-stations-and-licences.md)); `capture_families.json`, `storage_classes` rows, registry-driven `roll_verdict`/`status`/`staleness_sweep` (with the verdict-reproduction test), `scheduled_tasks.json` rows + OPERATING_REFERENCE regeneration, ratchet, DATA-LAYER V2 contract doc, embargo-agreement ratchet | workstation; host by `quiet_window_merge.ps1` | 10-19 night 00:30-01:00 RF slot (or 10-20), after #190's stage | RF (confirm) | `agent_docs_audit` passes; ratchet fails on an unclassified path; verdict unchanged for the current tree; **per-task redeploy row executed and running identity checked** |
| S2+S9 | **S2+S9 built on branch `claude/dlv2-s2-s9-pilot-20261015` (base S1 `claude/dlv2-s1-platform-stack6-20261015` @ 658592038, because the recorder-only block, its ratchets and the Q11 status identity extend S1's registry, contract and `status.ps1`), not landed;** owner: [platform contract](DATA_LAYER_V2_CONTRACT.md#recorder-only-rows) and [passive maker evidence capture](passive-maker-evidence-capture.md). Addendum 4 receipt: pilot tokens never join the raw update stream (extras inside UTC windows only), so per-city update coverage is unchanged and the 300 MB stream cap is not diluted; cap unchanged. Deferred: VR-4 dated `exchange_economics` copies. **88a: rewards change-trigger + VR-4 sweep + grouped fsync, then recorder-only pilot P1** (one 88a change on the post-#177 head): built-ins on `all_specs()`, P1 rows from config, latch telemetry exposed; one 88a-R at 00:30-01:00 | workstation; host integration attempt + ops restart | 10-21 night (10-20 is S3) | 88a-R; RF for graded loops (verdict); RS if the verdict says so | 24 h: REST ≤0.4 req/s; zero 429s anywhere; 5 pilot partitions sealed + gzip-verified; ≤10 MB/city-day; RSS ≤80 MiB; `peak_raw_working_bytes` recorded; 12 built-ins' selection unchanged (ratchet + check); held segments untouched; no graded-loop readoption; restart gap recorded in panel notes |
| S3 | **S3 built `52b358b11` on branch `claude/dlv2-s3-schema-registry-20261015`; rebased for landing as `claude/dlv2-s3-schema-registry-stack6-20261015` on the S1 roll_verdict fix `d69842131` (stack6 + S1), core parity digest re-pinned for stack6's `feature_store` v1.17 (645 core schemas), not landed** (core frozen with a parity digest; families in `weather/schema_families/`; strict audit aggregates both; `classify_schema_path`; real `roll_verdict.ps1` returns ROLL-FREE for a dummy family diff in a fixture test). **Schema registry split (PL-2)** + classifier + test | workstation; integration attempt | 10-20 night | **RS once** | strict schema audit passes; dummy family diff → ROLL-FREE; all three workers recovered |
| S4 | **Evidence host + first families:** PL-1 (embargo imports, fetch guard, per-basis PIT), PL-4, PL-5, PL-6 with hard commit cap; OB-1, OB-2, OB-3, FC-1, FC-4, VR-3 (journal only) | workstation; host registrar | 10-22 night RF slot | RF | **kill receipt** for a child exceeding its cap; reader property tests (first_seen > as_of invisible; FULL window refused; OUTCOME window refuses `outcome_join` and allows `capture_check`; stitched/archive_proxy refused for PIT); fetch guard refuses an embargo event date; seal chain across day roll; 72 h ≤0.1 GiB/day total; first-seen rows for all 51 stations; served replay hashes unaffected; optional channels pause in 09:30-11:55 |
| S5 | **Light batch lane:** LB-1 (max + min, SLP-row hourly rule, ECCC climate-daily) + LB-2 + FC-6 + FC-7 (+ reviewed `C:\tmp` corpus adoption) + VR-5 as light tasks 00:30-01:00; Stage-A read-only step for `label_panel.jsonl`; FC-5 UMOS on evidence host, HRDPS extract on workstation | workstation; host landing | 10-23 night | LT / RF (verdict) | panel rows for every station-day D-1, both kinds; panel reproduces 86a counts on pre-embargo dates; each task ≤10 min and ≤256 MiB; zero requests for embargo event dates (guard log); bulk fetch ≤4 MiB/s; no evaluation join in UTC 09-30..10-15 or the OUTCOME window |
| S6 | **Lowest series (P3)** config flip + `location_config_refresh` lowest-tag discovery; 88a-R at 00:30-01:00 | config; ops restart | 10-24 (after S2+S9 day-3 receipts and S5 min labels) | RF config + 88a-R | partitions sealed; ≤0.1 GiB/day; REST within bucket; peak raw < 50% latch; min labels present from day one |
| S7 | **Forecast shadow pack:** FC-2, FC-3 (only fields S0(d) shows are not served), hard Open-Meteo meter | workstation; evidence host | licence risk accepted (§9 Q1); not before 10-24 | RF | served payload hashes unchanged; meter stops shadow before any 429; zero 429s on served sources; `run_init`/`blend_unresolved` correct |
| S8 | **Venue write-path efficiency, one per night:** (a) VR-7 clob_tokens on-change + heartbeat (#118 revised); (b) VR-6 hourly-gzip books + token-row drop + Gamma cache + status-row trim + PL-5 CLOB counters; (c) FC-8 83b reuse + CAS compress + last_good strip. Reader census in each attempt manifest | workstation; integration attempts | 10-25, 10-26, 10-27 nights | **RS** each | (a) no false gap alarms over 24 h, `_latest_time_group` reads heartbeats; (b) no plaintext `order_books.jsonl` at 06:00; markout, MM preflight, latest-input, exec-join readers pass; (c) NBM downloads ≤~10/day; savings from `Get-Volume` deltas, tiering receipts, 91a manifests; 24 h low rises ~3 GiB |
| S10 | **Watcher convergence + DS-0 sidecar:** watcher sole AWC writer for the 12 built-ins (recorder keeps 39); join on `(station, obs_time, raw_hash)`; snapshot children fall back to own fetch on stale cache and record which path served; served AWC window widened only if the parsed source block is byte-identical, with metar parser/source version bump; DS-0 stage-vector sidecar (missing stages only) | workstation; integration attempt | 10-29 night | **RS** | each report once with `first_seen_utc`; trigger behaviour unchanged; served distributions parity **and** canonical digest of filtered rows unchanged on recorded inputs; stale-cache fallback exercised; sidecar rows for every serve |
| S11 | **Reclaims + close-time codecs** (one chunk/night, 04:00-04:45, only after the 91a backlog is spent): CP-3 with date/path exclusions and owner-signed replay_cache manifest; twin/log deletes on/after 10-31; CP-2 after reader census; CP-1 lzma + codec-aware opener; CP-5 decision in the 91a renewal | host ops; reader via workstation | from ~10-24 (backlog permitting) through November | RF ops; reader per verdict | hash-verified manifests; no file from UTC 09-27..10-30 or exam roots/pinned worktrees touched; a closed day replays byte-identical in normalized payload; cumulative gain recorded (no fixed ≥90 GiB target) |
| S12 | **Phase C:** P2 config flip + 88a-R (after OD28, ≥11-02); VR-2 (needs S0(a) receipt, Ethernet decision, pre-registered budget policy) | config + ops; VR-2 workstation + integration attempt + `adopt_execution_tape_after_merge.ps1` | P2 ≥11-02; VR-2 ≥11-03 night | P2 RF + 88a-R; VR-2 **RS** | gate per §4b; after: 88a RSS within re-derived cap; peak raw < 50% latch; VR-2 budget binds <5% of hours; cap/gap rows present; overflow drop-and-count tested; trade tape gap-free; reconnect rate unchanged |
| S13 | **Phase D:** P4 tranches of 10 cities by volume, both series | config + 88a-R | ~11-10, one tranche/week | RF + 88a-R | ≤8 MB/city-day/series; 24 h low ≥85 GiB; peak raw < 50% latch; zero 429s |
| S14 | **LB-3 ledger idempotence + LB-5 settlement coverage** | workstation; Stage-A fresh process | ~10-28, after owner yes | FP (verdict) | ledger appends only on content change; `verify_ledger_history` passes; coverage count emitted; no agent reads embargo outcomes |
| S15 | **DS-1 served-path refactor** (digest-pinned refs or delta-embedding), MRMS removal, FC-1 run_init in manifest, PL-4 wired in, OB-4; LB-4 after 11-15 | workstation with parity proof | after the MG-1 window (~12-02) | **RS**, schema bump | `captured_input_hash` continuity; replay parity on a closed pre-bump day **including one with the OB-1 segment restored from Drive** |
| S16 | Snapshot twins → Parquet; retire plain CSVs after D1 and named reader migration | workstation | November | mixed | corpus counts unchanged per reader |

**S2+S9 workstation dry run (measured 2026-10-15, master Q2).** Method: the branch's
`maker_evidence_capture --dry-run --duration-seconds 5400 --recorder-only-config <copy>` on
the 32 GB workstation, root `C:\wt\workstation-chat\l-data\s2s9-dryrun\scratch\run-20261015`
(outside the repository; nothing written to `data/`), with the config copy setting the pilot
on, the sweep on and `event_driven` built-ins (honoured before the hold only because the root is
scratch). Public endpoints only: no auth, credentials, order or settlement instruments. Run
2026-10-15 20:41:36Z-21:43:43Z (3,726 s, 62 cycles, 0 failed cycles); it ended early, not at
90 min, when the final `status.json` replace raised `PermissionError` (see finding below). Both
hour segments sealed with `manifest.json.gz`. Counted from the journalled request rows; bytes are
journal sizes; per-day figures scale the 1.035 h run linearly.

- **REST:** 1,518 requests, all HTTP 200, zero 429s. 0.407 req/s over the whole run; 0.374 req/s
  after a 900 s warm-up, against the 0.4 budget. Steady req/s by endpoint: core books 0.085,
  pilot books 0.034, core `/rewards/markets/<cid>` 0.107, pilot `/rewards/markets/<cid>` 0.024,
  sweep `/rewards/markets/current` 0.040, core Gamma events 0.050, pilot Gamma events 0.034.
  Until UTC 10-30 the shipped config keeps built-ins on the legacy every-minute read
  (≈2 req/s, 120 reads/min), so the 0.4 budget applies only after the post-hold
  `built_in_reward_cadence` flip.
- **Sweep:** 4 passes of 38 pages each (152 pages, ~15 min apart), 18,679-18,800 conditions per
  pass. Churn between passes: 3,089 / 2,659 / 3,018 conditions changed (14-16%) and
  1,047 / 699 / 989 removed.
- **Bytes:** pilot partitions (5 cities, 72 tokens; `-pilot` journals, pilot `book-<token>`,
  `universe-pilot-*`) 22.5 MB plain / 0.93 MB gzip in the run, ≈523 MB/day plain and
  ≈21.6 MB/day gzip, ≈4.3 MB/city-day gzip (gate ≤10). Sweep journals (`rewards_sweep`,
  `rewards_sweep_page`, `rewards_current`) 0.59 MB plain / 0.12 MB gzip, ≈13.6 MB/day plain and
  ≈2.8 MB/day gzip (VR-4 estimate ≤10). The pilot trade socket carried ~6k messages and ~3.9 MB
  received per 5 min.
- **Finding (open, not fixed on this branch):** the run died on Windows `os.replace` of
  `status.json.tmp` over `status.json` (`atomic_json`, unchanged base code) while an outside
  reader had `status.json` open. The production recorder has the same exposure to a concurrent
  `status.ps1` or cockpit read; a bounded retry on `PermissionError` is the candidate fix, and it
  is roll-sensitive (88a), so it needs an owner decision.

Decidable-date consequences (all assume every target date is countable): Q-14 census ~30 days after S2 (≈11-20); L8 T+1 read ~20 dates after S12 (≈11-25); label agreement ~30 settled days after S5 (≈11-22). LB-5 and Q-11 determine whether these dates hold.

---

## 8 Risks and kill criteria

| Risk | Mitigation | Kill / stop criterion |
| --- | --- | --- |
| Disk is binding; sizes are estimates | per-family budgets, bands, gates on `Get-Volume`/receipts | family >2× budget 3 days → off by config flip; 24 h low <75 → shed order; <60 → new families off; <50 → no landings |
| Lease overbooking pushes 91a/tiering or freezes nights | §4f timetable; light tasks never leased; reclaims after the 91a backlog | any job overlapping 04:45-09:00 → stop it, record, owner |
| Roll risk (S3, S8a-c, S10, VR-2, DS-1) | one attempt per night through the runbook | verdict ≠ ROLL-FREE on an RF night → do not land; unexpected STALE_CODE outside 01:00-04:00 from v2 → freeze v2 landings |
| 88a latch blacks out built-in capture | peak raw < 50% `MAX_RAW_BYTES` gate per phase | peak raw ≥250 MB → stop widening, revert last phase by config |
| 88a restarts inside the panel window | restarts only 00:30-01:00, not in LFC windows; gap noted; built-ins on `all_specs()` | any built-in selection change → revert same day, owner |
| RAM: admission failures cost settlement days | hard commit caps with a kill receipt; pause 09:30-11:55 and on low available | available <5.6 GiB at the 24 h low on 2 days → optional channels pause; child over cap → killed, family off |
| IP/rate limits on the shared egress | rewards trigger before widening; host-wide bucket; Open-Meteo meter before 429; 4 MiB/s bulk cap | **any 429 on any Polymarket caller → stop all widening until root-caused**; any served-source 429 attributable to shadow → shadow off same day |
| Licence | S0(f) sheet records the terms; owner accepted the free-API risk (§9 Q1); FC-10 optional | terms change materially → owner |
| Parity | new source keys; served-request change only with byte-identical parse + version bump | any served distribution changed → revert that night |
| Embargo leakage | **fetch-side guard + reader**, both importing `EMBARGO_WINDOWS`/`mg1_reserved_window`; ratchet that copies agree; S0 dates named | any embargoed fetch or join → result void, recorded in retracted claims. **Disclosure:** a desk agent fetched the live HKO since-midnight CSV once at 2026-10-15 08:40 HKT = **00:40Z, inside the embargo**. HKO HQ is the Hong Kong settlement instrument but there is no ledger, so it is not literally venue/88a/panel/settlement/snapshot/wallet content. Values were not carried forward. Owner ruling needed. Process rule from now on: size measurements use HEAD requests or documentation, never a live settlement-instrument fetch during an embargo |
| 88a hold UTC 09-27..10-30 | add files only | any write to a held segment → stop, owner |
| Config adoption invisible | per-cycle reload, `config_sha256`, `config_adopted` event | manifest without `config_sha256` fails ratchet |
| Landed is not running | per-task redeploy rows; running-identity check | registry-driven script not running after redeploy → that verdict is not binding |
| Missing-CSV-as-missing-day readers | named reader census before any rename/compress | corpus counts differ → revert |
| Label regime switch could worsen labels | panel shadow; SLP-row rule; Q-09 disclosed as undecidable without WRH read | n/a |
| Finality proxy ≠ resolver state | `awc_proxy_of_wrh` tag; COR events recorded; Rules finality clauses read before LB-4 | n/a |
| DS-1 makes replay depend on external journal | digest-pinned refs; `never_offload`; restored-from-Drive replay in proof | replay irreproducible → keep delta-embedding |
| Calendar collisions (10-15..10-19, OD28, 05-F3, OD30) | dates above | unresolved failed attempt → no v2 landing that night |
| Host wheel drift after cutover C | GRIB/omfiles/zstd/Parquet workstation-only | any host wheel needs a separate owner-approved pin |
| Greps are not traces | trace one instance before building on each claim (incl. the SLP-row rule, AWC ceilings) | n/a |
| Lazy imports in snapshot children | v2 modules never imported by serving path; PL-4 covers children | n/a |

---

## 9 Open owner questions

Answered questions stay listed with their answer; open ones are not acted on until a relayed owner answer arrives.


1. **Open-Meteo licence.** ANSWERED (owner 10-14 ~21:25 EDT, relayed by master-agent; DECISION_LOG 2026-10-14): accept the risk ("this is mainly research still even if we trade real money"). Keep the free API; FC-10 is optional, not an exit requirement. S0(f) still records the current terms.
2. **WU intraday (S22).** ANSWERED (master-agent from host run-state status fields, at the owner's direction; owner 10-14 ~21:25 EDT, relayed by master-agent; DECISION_LOG 2026-10-14): `public_wu_settlement_restore` runs in Stage A (10-14: PASS, 12/12 markets, target 10-13, 0 errors), so the redaction landed. WU-1 is in scope: shadow, redacted, token never logged.
3. **Wallet identity.** ANSWERED (owner 10-15 10:39 EDT "All as recommended", relayed by master-agent; DECISION_LOG 2026-10-15): **keep** taker/maker addresses from public data-api trades (VR-5). The 10-14 "3" was Q8.
4. **Page tokens, registration keys, WRH disagreement read.** Free-registration keys: ANSWERED YES (owner 10-14 ~21:25 EDT, relayed by master-agent; DECISION_LOG 2026-10-14); the owner does the sign-ups from the [sign-up list](free-registration-signup-list.md); keys live only in `config/local/` (git-ignored) or the environment, never in git, never opened by agents. Disagreement-only WRH page read (est. 5-10% of station-days): ANSWERED (owner 10-15 10:39 EDT "All as recommended", relayed by master-agent; DECISION_LOG 2026-10-15), **yes**, behind the fetch-side embargo guard, embargo dates excluded; closes Q-09.
5. **Book write-on-change heartbeat.** ANSWERED YES (owner 10-14 ~21:25 EDT, relayed by master-agent; DECISION_LOG 2026-10-14), "once test show we lose nothing": lands only after S0(b) shows a lossless reconstruction, with a receipt.
6. **Shared WS subscriber (M13).** Approve the evidence-semantics change?
7. **Ledger idempotence (LB-3).** ANSWERED (owner 10-15 10:39 EDT "All as recommended", relayed by master-agent; DECISION_LOG 2026-10-15): **yes**, with LB-5 ~10-28.
8. **Settlement coverage (LB-5) and learning-lane unblock (Q-11).** ANSWERED YES as a standing rule (owner 10-14 ~21:25 EDT, relayed by master-agent; DECISION_LOG 2026-10-14, mapped from the owner's "3"): always fill missing countable rows, including after 10-09; backfill writes stay outcome-blind and nobody reads reserved-date contents until the window ends. Q-11: schedule it.
9. **Label instrument switch** after MG-1's look: pre-register a WRH-equivalent regime?
10. **Lowest series.** ANSWERED (owner 10-15 10:39 EDT "All as recommended", relayed by master-agent; DECISION_LOG 2026-10-15): **confirmed**, the 10-02 decision covers the S6 recorder-only lane (~10-24).
11. **Adoption model for new families.** ANSWERED (owner 10-15 10:39 EDT "All as recommended", relayed by master-agent; DECISION_LOG 2026-10-15): **yes**, explicit restart with running-vs-disk identity in status.
12. **Free space.** CLOSED from state (DECISION_LOG 2026-10-15): 158.4 GiB free at the 10-14 host stat; no replay_cache or twin delete has run (they need Q15's signed manifest / 10-31).
13. **Hong Kong embargo disclosure.** ANSWERED (owner 10-15 10:39 EDT "All as recommended", relayed by master-agent; DECISION_LOG 2026-10-15): **accepted** as disclosed; no evidence voided; the no-live-fetch rule stands.
14. **Phase D scope.** All remaining venue cities, or stop after the 16 that out-trade the median built-in?
15. **Reclaims.** `forecast_payloads` CAS dedupe: ANSWERED (owner 10-15 10:39 EDT "All as recommended", relayed by master-agent; DECISION_LOG 2026-10-15), **refused permanently** (the only issue-time archive). The exact replay_cache manifest is still signed when presented.
16. **88a panel freeze.** ANSWERED (owner 10-15 10:39 EDT "All as recommended", relayed by master-agent; DECISION_LOG 2026-10-15): no amendment needed (S0(j): the 10-01 pre-registration freezes no 88a code); the owner signed the clarification that the P1 pilot bands are outside its 12-market stratum.

---

## Appendix: Review dispositions

**Review 1 (operations/feasibility)**

| # | Defect | Disposition |
| --- | --- | --- |
| 1 | Lease overbooking, no timetable | **Applied**: §4f timetable; light tasks unleased; CP-2/CP-4 after 91a backlog, ≤1 night in 3; named slots |
| 2 | VR-3 second writer of `location_market_events.json` | **Applied**: journal only; config refresh sole writer; no task commits |
| 3 | P1/P3 before rewards trigger | **Applied**: S9 merged into S2; P3 after S9; swarm 429 guard verbatim; host-wide bucket in PL-3 |
| 4 | S1 via light path | **Applied**: all non-Markdown landings via `quiet_window_merge.ps1` in a slot; S1 moved to 10-19/20 |
| 5 | VR-2 open streams / backpressure / daily cap | **Applied**: plain segments gzip at seal, decoupled queue, drop-and-count, sized from S0(a), Ethernet precondition |
| 6 | 88a `MAX_RAW_BYTES` latch | **Applied** (verified `maker_evidence_store.py:20`): VR-1 latch guard + gates |
| 7 | Job caps don't exist | **Applied**: reuse Stage-A/snapshot hard-commit containment, kill receipt, pause rules, receipts in gates |
| 8 | Reclaims ignore owner conditions | **Applied**: exclusions, dates, signed manifest; forecast_payloads dedupe removed to owner Q15; fixed target dropped |
| 9 | Embargo only in reader | **Applied**: fetch-side guard; S0 dates named |
| 10 | 88a restart mechanism | **Applied**: default config path, no new args, PT5M trigger, 00:30-01:00, post-#177 branch |
| 11 | S10 two writers / cache dependency | **Applied**: watcher sole writer for 12, join key, stale-cache fallback |
| 12 | `data_retention_inventory` walk | **Applied**: removed from Stage A |
| 13 | Host wheels (GRIB/omfiles/zstd) | **Applied**: workstation-only; stdlib lzma on host |
| 14 | VR-2 11-01 / OD28 / 05-F3 / OD30 | **Applied**: VR-2 ≥11-03, P2 ≥11-02, no .ps1 on OD28 day |
| 15 | Per-minute child launches | **Applied**: long-lived children; importtime bench S0(i) |
| 16 | Frozen script text / redeploy | **Applied**: redeploy rows + verdict-reproduction test |
| 17 | LB-1 inside Stage A | **Applied**: light task 00:30-01:00; Stage A reads only |
| 18 | Open-Meteo shadow 429 hits served | **Applied**: hard meter before 429, FC-1 30-60 min, outside 12:00-18:00 |
| 19 | Workstation WS dry run same egress | **Applied**: S0(a)/(k) one connection, abort rule |
| 20 | No bulk download cap | **Applied**: 4 MiB/s cap, slot-confined, reconnect abort |
| 21 | AWC 36 h unverified | **Applied** (verified served cap at 24, `model_sources.py:1485`): not measured; 24+12 fallback |
| 22 | Crypt keys stale | **Applied** (verified DECISION_LOG 2026-10-02): Q12 and risk row removed; restore-verify kept |
| 23 | HKO fetch time inside embargo | **Applied**: 00:40Z stated; HEAD/docs rule |
| 24 | CP-2 reader census | **Applied**: named readers in CP-2 and S11 |
| Missing items (runbook machinery, timetable, verify rows, Job cap, request bucket, fetch-side embargo, receipts, journal pin, latch, wheels, calendar, Ethernet, reader census) | **Applied** throughout §3, §4f, §7 header, §8 |

**Review 2 (integrity/science)**

| # | Defect | Disposition |
| --- | --- | --- |
| 1 | Daily cap biases L2 to morning | **Applied**: per-(token, hour) budget, priority, in-journal cap rows, pre-registered policy. Changing 88a's existing 300 MB stream cap is **not applied** here: it is an 88a code change, recorded as a latch/caps rule needing a verdict + owner yes |
| 2 | US labels unidentifiable; minute filters | **Applied**: SLP-row hourly rule, foreign filter dropped, Q-09 disclosed, disagreement read as owner Q4, `resolution_view` in LB-4 |
| 3 | Third embargo copy | **Applied**: import `EMBARGO_WINDOWS`/`mg1_reserved_window`, purpose argument, FULL/OUTCOME, agreement ratchet |
| 4 | Per-basis PIT policy | **Applied**: §2.4 with project vocabulary |
| 5 | FC-11 extractor missing | **Applied**: FC-11 + S0b; ranked as top exit-value item |
| 6 | OB-1 inbound bytes | **Applied**: hours=2 per minute + hourly long sweep |
| 7 | S2 in panel window | **Applied**: built-ins stay on `all_specs()`, ratchet, pre-registration check (S0(j), Q16) |
| 8 | VR-7 heartbeat | **Applied** |
| 9 | Min labels for lowest series | **Applied**: `label_kind`, min instruments, P3 waits for them |
| 10 | Finality proxy | **Applied**: `awc_proxy_of_wrh`, panel member only, finality clauses read in LB-4 |
| 11 | DS-1 external dependency | **Applied**: digest-pinned refs or delta-embedding, `never_offload`, Drive-restore replay |
| 12 | Stage-vector sidecar earlier | **Applied**: DS-0 with S10 |
| 13 | Circular Phase C gate | **Applied**: receipts from `Get-Volume`/tiering/91a; gate 7 days after S8c |
| 14 | REST before trigger; condition count | **Applied**: S9 with S2; RAM/REST re-derived from P1 |
| 15 | VR-3 out-of-tree file is RS | **Applied in Review 1's form** (journal only, no move). **Rejected**: "commit it from the writer", because no scheduled task may commit to master |
| 16 | Ranking ignores exit criteria; settlement coverage | **Applied**: LB-5, owner Q8, ranking note |
| 17 | S10 served window change | **Applied**: byte-identical parse rule, version bump, digest continuity in verify |
| 18 | VR-5 request volume | **Applied**: closed events only, deduped, per-night cap, built-ins + pilots first |
| 19 | Blended run identity | **Applied**: `blend_unresolved` |
| 20 | Runway at both figures | **Applied**: §4b table. **Rejected in part**: "first S1 light-path receipt" (S1 is not a light-path landing); the Get-Volume reading moved to S0(g) |
| Missing items (FC-11, coverage/Q-11, min labels, Toronto ECCC daily, US finality, DS-0, embargo reuse, panel pre-check, PIT basis, WRH read, own-account envelope VR-10, never-offload, AWC ceilings + Synoptic diff, licence verification) | **Applied** throughout |

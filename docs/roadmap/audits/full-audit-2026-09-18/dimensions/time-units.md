# Audit dimension: time zones, DST, settlement-day boundaries and units (key: time-units)

Auditor: subagent, read-only. Date of audit: 2026-09-18/19. Host: live 16 GB production host, protected window.
No project file was modified. No Python, pytest, .ps1 or CLI was executed. `data/` was not read (the brief did not allow it).
Every claim below cites `path:line`. Where I reasoned about runtime behaviour without running code, I say so.

## 1. Scope covered

- `src/weather/time.py`, `src/weather/units.py`, `src/weather/point_in_time_contract.py` (first 1,284 of 1,829 lines; it is a hash/contract verifier, the time handling in it is `_parse_utc` and date arithmetic only).
- `src/weather/market/market_registry.py` (12 markets, IANA zones, units), `market_config.py` (default target date).
- Capture stamping: `collection/snapshot_store.py`, `collection/snapshot_tracker.py`.
- Grading: `collection/collection_health.py`, `backtesting/settlement_ledger.py`, `backtesting/settlement_io.py`, `backtesting/settled_days.py`, `operations/settlement_hole_check.py`, `operations/settled_day_freshness.py`, `scripts/ops/streak_status.py`.
- Scoring/analytics hour derivation: `backtesting/tape_scoring.py`, `reporting/hourly/hourly_model_scoring.py`, `reporting/hourly/ten_minute_model_performance.py`, `calibration/afternoon_residual_centering.py`, `reporting/research/skill_gap_decomposition.py`, `reporting/research/quotable_edge.py`, `market/taker_edge_permission.py`, `market/live_observation_normalization.py`.
- Model: `model/model_constants.py`, `model/model_sources.py` (time and unit sites), `model/model_distribution.py` (cutoff logic), `model/model_base.py` (print-minute aliasing), `model/model_presentation.py` (band parser), `model/feature_store.py` (fallback chains).
- WU store: `sources/wu_history.py`, `sources/daily_summary.py`.
- Ops windows: `scripts/ops/quiet_window_merge.ps1`, `workload_admission.ps1`, `health_watchdog.ps1`, `status.ps1`, `chain_recovery_run.ps1`, `training_window*.ps1`, `integration_attempt_contract.ps1`, `register_*.ps1` trigger times; Python `international_live_time_window.py`, `storage_recovery_night_contract.py`, `nightly_retrain.py`, `clob_order_book_tiering.py`, `market_making_evidence.py`, `market_making_run.py`.
- Docs checked for prior knowledge: `docs/operations/ESTABLISHED_FINDINGS.md`, `RETRACTED_AND_FALSE_LEADS.md`, `HOST_LOAD_POLICY.md`, `OPERATING_REFERENCE.md`, `docs/roadmap/active-backlog.md`, two 09-71a roadmap docs, and the owner-memory note `timezone-fix.md`.

## 2. Method

Grep (explicit paths only) for `datetime.now(`, `utcnow`, `date.today`, `ZoneInfo(`, `America/`, hard-coded offsets, `timedelta(hours=24)`, `86400`, `1440`, DST vocabulary, `temp_c`, `capture_minute`, label regexes, `int(round(`, conversion formulas. Then for each structural claim I opened the producer and at least one consumer and traced one instance end to end. Python datetime semantics I rely on (documented CPython behaviour, not executed here): for two aware datetimes that share the SAME tzinfo object, comparison and subtraction are done on naive wall-clock fields and ignore UTC offset and `fold`; `ZoneInfo("X")` is cached so `spec.tz` is the same object every call; datetimes parsed by `fromisoformat` from strings with an explicit offset carry a fixed-offset tzinfo and therefore compare/subtract correctly in absolute time.

## 3. Census: naive versus aware datetimes

- `datetime.now(` occurs 451 times across 276 files under `src/weather`.
- Naive `datetime.now()` (no tz, not followed by `.astimezone()`): 36 sites. `datetime.utcnow()`: 2 (`collection/data_ingestion.py:50`, `backtesting/replay_ablation.py:472`). `date.today()`: 4 (`collection/historical_backfill_plan.py:669,762`, `sources/forecast_history.py:235`, `operations/release_admissibility_clock.py:742`). Host-local-aware `datetime.now().astimezone()`: 14 (live-session runner/sealers, `settlement_hole_check.py:62`, `event_day_archive_coverage.py:469`, `documentation_transaction.py:57`).
- So roughly 92% of clock reads pass a tz. Of the 36 naive sites, 30+ are report banners or metadata stamps (`Generated at`, `trained_at`).

The five riskiest naive/host-local sites, traced:
1. `operations/clob_order_book_tiering.py:83` `datetime.now().date()` decides which event days are "settled" for tiering. Traced: deliberately host-local, documented at :70-82, and backed by the real invariant `MIN_QUIET_SECONDS = 7200` at :88-96 because a Pacific day ends 03:00 ET. Sound.
2. `reporting/promotion/promotion_corpus.py:51` `_as_of_date` defaults to the host-local date as the settled-folder cutoff. Correct only while the process runs on a Toronto-zoned host. Latent host-tz dependency, not a live bug.
3. `backtesting/settled_days.py:59` `datetime.now(TORONTO_TZ).date()`; `discover_settled_folders` treats `target_date < Toronto today` as settled (:91). Between 00:00 and 03:00 ET a Pacific market's day D is still running but is "settled" by this rule. The settlement stage runs at 09:30 ET (`scripts/ops/register_daily_refresh.ps1:21`) so production is safe; any caller between 00:00 and 03:00 ET (Stage B is registered for 00:35, :23) would see unfinished western days as settled.
4. `calibration/pooled_artifact_io.py:208`, `pooled_training.py:1678,1834,2120` write naive local `trained_at`. Consumers (`.get("trained_at")`, 11 sites) are display/metadata only; no gate parses it. Cosmetic, but `weather/time.parse_datetime` would read it as UTC if anyone ever gates on it (4-5 h error that changes on 11-01).
5. `calibration/pooled_candidate_scoring.py:652,779,972,1092` default `experiment_start_date` to the naive host-local date. Label only.

## 4. Findings

### F1 (HIGH, new) Band-label parsing is sign-blind; Toronto's winter ladder will be mis-parsed everywhere

The canonical market-bin parser drops the minus sign:

- `src/weather/model/model_presentation.py:167` `digits = [int(value) for value in re.findall(r"\d+", label)]`, then :170-178 builds `kind/value/value_hi` from those digits. `clean_label` (:803-809) does not preserve or normalise a sign.
- This parser feeds the tape: `collection/snapshot_store.py:774` `bins = model_client.market_bins(event)`; :779-784 computes `model_probability` per bin from those values; :813-814 persists them as `bin_value_c` / `bin_value_hi_c`.
- The ledger has its own unsigned copy: `backtesting/settlement_ledger.py:573` (`parse_band_label`), used by `winning_band_from_frame` :618-642 and `band_value_hi` :600-602.
- CLOB token metadata: `market/market_microstructure_capture.py:145` (`label_bin_metadata`).
- Other unsigned copies: `backtesting/settlement_io.py:64`, `backtesting/replay.py:155`, `operations/observation_trigger.py:1367` (`^(eq|lte|gte):(\d+)`) and :1373, `reporting/casebooks/disagreement_casebook.py:159` (grep-level).
- Four sites went the other way and use `-?\d+`, which breaks the two-degree Fahrenheit labels instead: `"76-77"` parses as `[76, -77]`: `market/taker_bot_scoring.py:13`, `market/mm_paper_scoring.py:211`, `market/taker_bot_strategy_evaluation.py:118`, `backtesting/snapshot_analytics.py:739` (last one grep-level). Those are reached only when the explicit `bin_value_hi` field is empty (`taker_bot_scoring.py:21-28`).

Consequence, traced through `resolve_outcome` (`settlement_io.py:75-86`): a Toronto ladder such as "-5 C or below, -4 C ... 4 C, 5 C or higher" produces `lte 5`, duplicate `eq 4/3/2/1` pairs, and `gte 5`. The model's P(bucket = +3) is recorded against the band that means -3; `lte 5` resolves YES for almost any cold outcome, so `winning_band_from_frame` returns the "or below" band first; reconciliation against Polymarket then cannot be `match` (`settlement_ledger.py:55`), so every such Toronto day is non-countable, and per-band probabilities, edges and scores on the tape are wrong.

Why it has not fired: every label in `config/location_market_events.json` is warm-season (first ladder, lines 48-298: "16 C or below" ... "26 C or higher", 11 one-degree bands, so the bottom band sits about 5 C under the forecast). A grep of that file for a negative or 0-5 C label returns nothing, and no test contains a negative label (grep of `tests/`). The project has never seen a cold market.

When it fires (inferred from the 11-band ladder plus Toronto climatology, not measured): the first negative band appears once the forecast high is about 4 C or lower, typically mid/late November; from December to March it is every day. US markets are exposed only on rare sub-zero-Fahrenheit ladders. Whether Polymarket renders the sign as ASCII `-` or U+2212 is unverified (no network); a fix must accept both and must not treat the range hyphen in "76-77" as a sign.

Basis: parser and data flow verified_in_code; label format and first-fire date inferred. Known status: new (not in ESTABLISHED_FINDINGS, RETRACTED, active-backlog, or tests).

### F2 (MEDIUM, new) `captured_at_local` is Toronto time for every market, and the settlement ledger grades its "12:00-18:00 local" window in that offset

- Producer: `collection/snapshot_store.py:649` `now = datetime.now(TORONTO_TZ)` inside `maybe_write`, the only capture write path (`snapshot_tracker.py:227` is the sole caller); `:794` writes `"captured_at_local": captured_at.isoformat()`; `:295` snapshot ids carry the same offset. Corroboration in a committed doc: `docs/roadmap/high-so-far-cutoff-direction-2026-09-71a-manifest.json:293,317` shows a san-francisco snapshot id `20260609T171152-0400`; :980-983 a denver id `...-0400`.
- Consumer (authority path): `backtesting/settlement_ledger.py:335-341` `captured_times` = `parse_times(captured_at_local)` (fixed -04:00 tzinfo), `:1168-1169` passes them to `coverage_summary(..., target_date=target_date)`; `collection/collection_health.py:123` `local_window(target_date, first.tzinfo)` and `:155-159` build 12:00 and 18:00 in the FIRST CAPTURE'S tzinfo, i.e. Toronto's offset. `settlement_ledger.py:205-217` does the same for the 14:00-17:00 "peak_heating_window". There is no `spec.tz`/`astimezone` anywhere in `settlement_ledger.py` (grep).
- The ledger nevertheless records the window as `"12:00-18:00 local"` / `"14:00-17:00 local"` (`settlement_ledger.py:45-46,315`).

Effect: for the 8 non-Eastern markets the certified window is 11:00-17:00 (Central), 10:00-16:00 (Denver), 09:00-15:00 (LA, SF, Seattle) market-local, and the "peak" window is 11:00-14:00 Pacific. A capture outage at 15:30-17:30 PDT, the hours when western highs are usually set, is invisible to `coverage_clean`, `quality_grade`, `material_coverage_grade` and `promotion_countable`, while a harmless 09:30 PDT gap is graded as a settlement-window gap. The live fleet monitor does it correctly (`collection_health.py:456-470` converts to `spec.tz` first), so the advisory view and the authority ledger disagree about what was graded. Only Toronto-market build_label tests exist (`tests/market/test_market_day_labels.py:239-313`).

Magnitude is unknown without reading ledgers (not permitted here): capture is 24 h at 10-minute cadence so most days grade the same either way. This is the residue of the 2026-06-06 "thread spec.tz everywhere" fix, which explicitly left the tracker clock as "market-agnostic" (owner memory `timezone-fix.md`).

### F3 (MEDIUM, new) Legacy hour-of-day analytics read the Toronto wall clock as the market's local hour

- `backtesting/tape_scoring.py:39-43` `capture_minute` = `parsed.hour*60+parsed.minute` of `captured_at_local`; `:203-216` stores `capture_minute` and `cutoff_hour = minute // 60`; `:78-97` `fixed_cutoff_rows` selects by it.
- Consumers that treat it as local: `reporting/hourly/hourly_model_scoring.py:148-160` (`hour_regime`, 9-14 = "ramp_midday"), `:364-379` (docstring says "each local hour"); `reporting/hourly/ten_minute_model_performance.py:122-126,973-977`; `calibration/afternoon_residual_centering.py:34-35,52-54` (selects "afternoon 15-18" rows by the same hour); `backtesting/replay_backtest.py:447-459`; plus `model_history`, `settled_day_root_cause`, `price_free_model_learning`, `winner_underpricing_casebook`, `feature_quality_quarantine` (grep-level).
- For LA/SF/Seattle "09-14" in these reports is 06:00-11:59 local; Denver 07-12; Central 08-13.

Important limit on this finding: the research path that produced the headline primary-slice numbers does it right. `reporting/research/skill_gap_decomposition.py:1084-1094,1134` converts with `export_captured.astimezone(spec.tz)` before taking `.hour`; `quotable_edge.py:564` uses the model's market-local `effective_cutoff_hour`; `market/taker_edge_permission.py:103-113` uses `spec.tz`. So I am NOT claiming ESTABLISHED_FINDINGS section 0/1 numbers are wrong; I am claiming any per-hour table produced by the tape_scoring family mixes lead times across time zones, and nobody reading it is told.

### F4 (LOW, new) What actually fires on 2026-11-01 (fall-back) and 2027-03-14 (spring-forward)

Verified not to break on 11-01: WU rows are bucketed from epoch `valid_time_gmt` through `astimezone(tz)` (`sources/wu_history.py:997-1002`, `model_sources.py:1051-1054`), so the 25-hour local day is bucketed correctly; `SnapshotStore.is_due` subtracts a ZoneInfo `now` from a fixed-offset parsed time (`snapshot_store.py:1061-1081`) so cadence is absolute; heartbeat ages go through `weather/time.age_minutes` on offset-bearing ISO strings (`snapshot_tracker.py:561-562`); `capture_recovery_check.py:68-73,197-203` is pure UTC; no `timedelta(hours=24)` or hard-coded -4/-5 offset exists in `src/weather` (grep: only `sources/asos_one_minute.py:157,281` assumes 1,440 minutes per local day). The intraday cutoff grid is 07-20 local (`model_constants.py:26`), all after the 02:00 transition.

Will fire:
a. Ledger and streak window on the transition day. `collection_health.py:123` and `scripts/ops/streak_status.py:175-177` take the tzinfo of the FIRST capture. The pre-local-day guard (`snapshot_tracker.py:146-158`) means the first capture of the 11-01 tape is just after local midnight, still on the daylight offset, so for all 12 markets the graded window on 2026-11-01 is one hour earlier than labelled (Toronto: 11:00-17:00 EST; on top of F2 for western markets, e.g. 08:00-14:00 PST). On 2027-03-14 it is one hour late. One day each, harmless unless a gap falls in the boundary hour.
b. `early_hour_coverage_summary` (`collection_health.py:259-363`) converts every time to the same ZoneInfo (:269-276) and then sorts/subtracts, which is wall-clock arithmetic. Fall-back: the two 01:xx hours interleave, no false gap, a real outage in that hour can be masked, `coverage_ratio` exceeds 1. Spring-forward: 01:50 -> 03:00 is 10 real minutes but 70 wall minutes (> 15 tolerance, :311) and only about 42 captures exist against `minimum_count` 48 (:307), so every market gets `status=BLOCK`, `counts_toward_early_hour_evidence=False` for that date (consumed by promotion decisions, daily learning, fleet gates; 10 files).
c. PowerShell local-DateTime arithmetic. `scripts/ops/status.ps1:1157` `((Get-Date) - [datetime]$status.last_heartbeat).TotalSeconds` with the guard `$ageSeconds -ge 0` at :1160: a heartbeat stamped 01:5x EDT read at 01:0x EST yields a negative age, so the S4U fallback path (:1134-1170) cannot prove the loop alive until its next heartbeat (up to ~10 min for the snapshot loop, :1145) and `capture loop DOWN` (:1234) can flag falsely. Nothing automated restarts on that flag (watchdog only logs). Relative deadlines of the form `(Get-Date).AddSeconds(n)` (`quiet_window_merge.ps1:3687-3701`, and the 01:00-04:00 window maths at :1385,1399-1401) stretch by 60 minutes if they straddle 02:00 EDT, and shrink on spring-forward. Wall-clock boundary polling (`chain_recovery_run.ps1:142,187-204`, `workload_admission.ps1:596-607`, `health_watchdog.ps1:50-55`) is DST-safe by construction.
d. `training_window_contract.ps1:86-88` pins the one-shot to exactly 01:00:00 local and has no ambiguous/invalid-time guard, although the project already wrote one (`integration_attempt_contract.ps1:989-1007`, tested at `tests/operations/test_integration_attempt_scripts.py:957-963`). 01:00 on 2026-11-01 is ambiguous. The training window is currently disabled, so this only matters if someone schedules that night.

DST test coverage in the repo: two places only (`tests/market/test_maker_incentive_feasibility.py:303`, the integration-attempt script test). Nothing for the ledger, collection health, streak or status paths. `docs/operations/` mentions DST once (`INTEGRATION_ATTEMPT_RUNBOOK.md:107`).

### F5 (MEDIUM, known_open) `*_c` names hold Fahrenheit for 11 of 12 markets, and the suffix means two different things

- Live source rows alias native into `_c`: `model/model_sources.py:1061-1064` (`"temp_c": temp_native`), :1086 (`"max_c": history_max`), :1113-1120 (`temp_c`, `max_24h_c`, `max_since_7am_c`, `dewpoint_c`), :1436, :1487; replay reconstruction does the same (`backtesting/replay.py:399-402,430-433,448-453`); the tape columns `top_temp_c`, `bin_value_c`, `bin_value_hi_c`, `wu_history_high_c` are native (`snapshot_store.py:803,813-814`).
- The WU store uses the same suffix for TRUE Celsius: `sources/wu_history.py:772-775,792-795` (`temp_c = native_to_c(...)`), daily summary `max_temp_c`/`max_temp_bucket_c` :833-841.
- Readers bridge the two with silent fallback chains that treat `_c` as native: `model/feature_store.py:576-590,608-613`, `sources/wu_history.py:892-897` (`row_temp`), `sources/daily_summary.py:36-54`.
- The project knows: `sources/daily_summary.py:1-7` documents it and `is_legacy_wu_c_lie` (:31-33) special-cases the old schema; `market_registry.py:8-12` documents native-unit operation. Today the chains resolve correctly because `*_native` is always present. The trap is for the next writer (mostly agents): a row that lacks `temp_native` but carries a true-Celsius `temp_c` would be read as Fahrenheit without any error.

Conversion and rounding, otherwise healthy: one canonical `round_half_up = floor(x + 0.5)` (`units.py:23-28`), used for buckets; no banker's-rounding `round()` decides a band anywhere in `model/` (grep: only `residual_distribution_v1.py:566-567`, on already-integral values); the `int(round(` sites elsewhere operate on integral values. Absolute versus delta conversions are kept apart (`market_registry.py:88-98`, `calibration/pooled_density_training.py:441-464`). Conversion formulas are duplicated in about nine modules instead of importing `units.py` (`variant_prediction_runtime.py:277,287`, `continuous_density.py:21,25`, `residual_distribution_v1.py:417`, `model_sources.py:2267-2269`, `nbm_probabilistic_tmax.py:233`, ...), all consistent today. METAR Celsius is converted to native unrounded (`model_sources.py:1320`) and only bucketed later, which is the right order.

### F6 (LOW, new framing of a known season gap) Every hour-indexed model rule is wall-clock and was fitted on daylight-time data only

`model_distribution.py:1536-1593` (`intraday_cutoff_hour`, `intraday_blend_weight`, `tail_target_weight`, `history_signal_weight`, `forecast_signal_weight`), the learned lock-in curve and `LATE_LOCKIN_FULL_HOUR = 17` described in `model_constants.py:60-87` are keyed on the local wall-clock hour. The training archive is May-June (project records: archive 05-10..06-30, zero Jul/Aug), all daylight time. After 2026-11-01 the sun is one hour "earlier" on the wall clock, on top of the seasonal shift, so lock-in and tail weights arrive about an hour late relative to the physical peak. Direction is conservative (under-confident after the peak), it is not a crash, and the standing decision is no model-alpha work; recorded so nobody rediscovers it as a mystery in November. Basis: inferred.

### F7 (LOW, new) Toronto-centric operating windows applied to markets three hours west

- `health_watchdog.ps1:52,93-94` escalates capture/memory flags to CRITICAL only during 12:00-18:00 host-local; the Pacific 12:00-18:00 is 15:00-21:00 ET, where the same flag is HIGH.
- `market/market_making_run.py:1929-1935` `paper_until_utc(target_date, specs)` ignores `specs` and ends the paper loop at 20:00 America/Toronto (= 17:00 PT); `market/market_making_evidence.py:19-20,50` classifies active-day evidence on a 07:00-20:00 Toronto window for every market.
- `HOST_LOAD_POLICY.md:111-131` is explicitly an America/Toronto map; the combined protected block 12:00-00:05 ET does cover the western heating peak, so host protection itself is adequate. This finding is about labelling/escalation, not load.

### Smaller items (report only)
- `collection/forecast_archive.py:280,299` default `target_date=TARGET_DATE`, which is evaluated once at import (`model/model_constants.py:12-15`). Callers at :245,402,413,415,604 rely on the default; a long-lived process would stamp "HH:MM"-only legacy rows with its import-day date. Only legacy row shapes reach it.
- `market_registry.py:137` still has the dead duplicate `REGISTRY = {... (TORONTO, NYC)}` before the real one at :394 (already noted in the owner's memory; still present).
- `operations/daily_refresh_cli.py:461` help text says "yesterday UTC"; the code uses Toronto yesterday (`settled_day_freshness.py:190-197`).
- `model/feature_store.py:539-555` `row_minute_of_day` takes `.hour` of whatever offset the ISO string carries; a UTC-stamped row without a `time` key would yield a UTC minute-of-day. Current producers emit market-local offsets.
- `model_presentation.py:750-755` `bin_sort_key` returns -1 for `lte`, which mis-sorts once negative `eq` values exist (part of F1's fix surface).
- `x.get("bin_value_c") or x.get(...)` patterns (`taker_bot_scoring.py:20`, `observation_trigger.py:1363`) treat a numeric 0 as missing; the 0 C band then falls back to label parsing. Harmless today, entangled with F1.
- `sources/asos_one_minute.py:157,281` `expected_minutes=1440` is wrong on both DST days (1,500 / 1,380).
- `market/live_observation_normalization.py:72-86` decides "before the 07:00 max-since-7am reset" from `captured_at_local.hour` (Toronto). The two dispositions it chooses between are both untrusted downstream (:155-159) and the paid WU-current feed is disabled, so no live effect.
- `sources/wu_history.py:819` sorts a day's rows by the `valid_time_local` STRING; on the fall-back day the two 01:xx hours interleave. Only `first_time`/`last_time` depend on order.

## 5. Strengths (genuine)

1. One shared, correct clock helper: `src/weather/time.py:6-42` (UTC now, offset-aware parsing, mixed naive/aware age handling); heartbeats and capture stamps always carry an explicit offset, which is what makes the Python core DST-safe.
2. Per-market IANA zones in one registry (`market/market_registry.py:101-303`, `tz` property :45-47); model `now`, WU day bucketing and target-date resolution all use `spec.tz` (`model_sources.py:1033,1051-1054`, `wu_history.py:356-371`, `market_config.py:60-80`), and the day-boundary stray-capture problem was found and guarded (`snapshot_tracker.py:139-158`).
3. `operations/international_live_time_window.py:46-81` is a model of how to do it: refuses naive datetimes, orders in UTC, evaluates wall-clock containment in a ZoneInfo. Same quality in `storage_recovery_night_contract.py:60-65,90-95` and `nightly_retrain.py:405-427,1760-1769`.
4. The ops layer already contains a correct DST guard with a test (`integration_attempt_contract.ps1:989-1007`), and the hard-stop loops poll the wall clock against a wall-clock boundary rather than sleeping a computed duration (`chain_recovery_run.ps1:187-204`).
5. Units: a single half-up rule (`units.py:23-28`), explicit absolute/delta separation (`pooled_density_training.py:441-464`), and an honest, documented repair of the old "Fahrenheit in `_c`" daily summaries (`sources/daily_summary.py:1-64`).
6. `clob_order_book_tiering.py:70-96` documents exactly why a date cutoff is insufficient for western markets and backs it with a quiet-time invariant.

## 6. Not covered / open questions

- No `data/` reads, so F2's real-world magnitude (how many western market-days changed grade) is unmeasured. A bounded offline recomputation on the workstation copy would size it.
- Polymarket's exact rendering of negative bands (ASCII hyphen vs U+2212, "or below" wording) is unverified; no network.
- Open-Meteo's handling of DST inside a `timezone=` response (single `utc_offset_seconds` per response) was not verifiable offline; affects only which hour lands on which side of local midnight in forecast archives.
- Windows Task Scheduler behaviour for a daily trigger inside the repeated 01:00-02:00 hour was not tested; the only fixed 01:00 trigger found is the disabled training window (CLOB enrichment at 01:00 is a 15-minute repetition trigger, `register_clob_enrichment.ps1:57`).
- `point_in_time_contract.py` lines 1285-1829, `reporting/` beyond the files listed, `market/mm_*` time handling, and the 413 test files (only grepped) were not read.
- I did not execute any code; the datetime-semantics conclusions in F4b and F4c are reasoning from documented CPython/.NET behaviour.

## 7. Recommended order of work (no changes made)

1. Before mid-November: one signed, range-aware label parser in one module, used by all eleven sites in F1, with tests for "-3 C", "-10 C or below", "0 C", U+2212, and "76-77 F".
2. In `build_label` (and `streak_status.py`) convert capture times to `spec.tz` before `coverage_summary`, exactly as `summarize_folder` already does; add a Seattle and a DST-day test. Decide whether to regrade history or only go forward, and say so in the ledger schema.
3. Either rename `captured_at_local` semantics in docs ("capture host local, America/Toronto") or add a true `captured_at_market_local`; make `tape_scoring.capture_minute` convert via `spec.tz`.
4. Replace same-tzinfo arithmetic in `early_hour_coverage_summary` with UTC arithmetic; compute `minimum_count` from real elapsed minutes.
5. In `status.ps1` compare heartbeats as `[datetimeoffset]`/UTC (the file already does this at :2363-2366 for other markers).

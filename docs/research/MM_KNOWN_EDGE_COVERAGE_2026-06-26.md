# Market-Making Known-Edge Coverage

Date: 2026-06-26

Scope: fixed post-settlement drill `data/mm_runs/2026-06-25/20260626T020148684548Z`, later June 26 diagnostics, and the June 27 target-date repair addendum. No live orders were placed.

## Baseline Post-Settlement State

The stable one-shot drill passed preflight across all 12 markets and emitted one paper quote:

- Rows: 132.
- Quote-permission rows: 1.
- Live-trade-permission rows: 0.
- Reason counts: 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 10 `NO_QUOTE_MISSING_BOOK`, 1 `QUOTE_HARVEST_MID`.
- Event gate: clear on all rows.
- Evidence mode: `post_settlement_evaluation`, so this is not countable live-forward evidence.

The one quoted row:

- Market: Dallas.
- Band: `92-93 F`.
- Side: `TWO_SIDED`.
- Permission: `harvest_only`.
- Policy reason: `QUOTE_HARVEST_MID`.
- Promotion state: `SHADOW`.
- Known-edge reason: `awaiting_paper_markouts`.
- Bid: 0.9895 for 5 contracts.
- Ask: 0.999 for 5 contracts.
- Quote risk: 4.9525 USDC.
- Expected reward score: 1.0.
- Expected rebate value: 0.0.

Interpretation: this is useful as a paper target for the next active window, but it does not justify live capital.

## June 27 Target-Date Repair Addendum

Latest safe shadow drill: `data/mm_runs/2026-06-27/20260627T055820610723Z`.

This run came after refreshing the default June 27 event-metadata artifact, forcing target-date snapshots, and refreshing public target-date CLOB books/features for all 12 configured markets. It is still keyless `shadow --once` operator-drill evidence, not live-forward promotion evidence.

- Preflight: `WARN`.
- Quote rows: 132.
- Quote-permission rows: 0.
- Live-trade-permission rows: 0.
- No-quote reasons: 55 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 44 `NO_QUOTE_STALE_INPUT`, 33 `NO_QUOTE_INFORMATION_EVENT`.
- Paper diagnostic: `data/backtest/mm_paper_shadow_20260627T055820_after_metadata_snapshot_refresh.json`.
- Known-edge diagnostic: `data/backtest/mm_known_edge_shadow_20260627T055820_after_metadata_snapshot_refresh.json`.
- Latest readiness report: `data/backtest/mm_live_readiness_20260627T055820_after_metadata_snapshot_refresh.md`, status `BLOCK`.

The known-edge map output for this run still has 17 records: 7 `harvest_only`, 3 `edge_research`, and 7 `no_quote`. Its permission counts are unchanged from the accepted map. That is not evidence to broaden permissions; it is evidence that the current map, event gates, and promotion gates are correctly fail-closed.

Latest selected-market follow-up: `data/mm_runs/2026-06-27/20260627T061148175884Z`.

This Austin/Dallas/Houston subset was run after the information-event window cleared. It passed preflight and produced 16 harvest-only quote-permission rows, 17 no-quote rows, and 0 live-trade-permission rows. Per-market quote permissions were Austin 4, Dallas 4, and Houston 8. The remaining blocked rows were 10 `NO_QUOTE_DISAGREEMENT_SHADOW` and 7 `NO_QUOTE_MISSING_BOOK`; all 33 rows had event gate action `none`. Its score `data/backtest/mm_paper_shadow_20260627T061148_subset_austin_dallas_houston.json` still has 0 fills and fill evidence `BLOCK`, so the subset is a paper markout target only.

Current market split:

| Market | Rows | Policy reason | Coverage state | Required action |
|---|---:|---|---|---|
| atlanta | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block/no_quote/BLOCK` | keep blocked until promotion gate passes |
| chicago | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block/no_quote/BLOCK` | keep blocked until promotion gate passes |
| miami | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block/no_quote/BLOCK` | keep blocked until promotion gate passes |
| nyc | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block/no_quote/BLOCK` | keep blocked until promotion gate passes |
| toronto | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `missing_known_edge_record/no_quote/BLOCK` | collect countable markouts before map change |
| austin | 11 | `NO_QUOTE_INFORMATION_EVENT` | `event_gate_suppress/harvest_only/SHADOW` | wait through information event and re-evaluate in countable paper |
| dallas | 11 | `NO_QUOTE_INFORMATION_EVENT` | `event_gate_suppress/harvest_only/SHADOW` | wait through information event and re-evaluate in countable paper |
| houston | 11 | `NO_QUOTE_INFORMATION_EVENT` | `event_gate_suppress/harvest_only/SHADOW` | wait through information event and re-evaluate in countable paper |
| denver | 11 | `NO_QUOTE_STALE_INPUT` | `source_freshness_model_gap/harvest_only/SHADOW` | collect clean CLOB tape before judging coverage |
| los-angeles | 11 | `NO_QUOTE_STALE_INPUT` | `promotion_block/no_quote/BLOCK` | collect clean CLOB tape before judging coverage |
| san-francisco | 11 | `NO_QUOTE_STALE_INPUT` | `promotion_block/no_quote/BLOCK` | collect clean CLOB tape before judging coverage |
| seattle | 11 | `NO_QUOTE_STALE_INPUT` | `promotion_block/no_quote/BLOCK` | collect clean CLOB tape before judging coverage |

Coverage interpretation:

- Toronto remains the true missing-record coverage cell: 11 rows require countable markouts before any map change.
- Atlanta, Chicago, Miami, and NYC are true promotion-block cells: keep them blocked until the promotion gate passes.
- Austin, Dallas, and Houston have `harvest_only` permission in the map. In the all-market 05:58Z run they were suppressed by an information event; in the selected 06:11Z subset they emitted shadow quote permissions after the gate cleared. This is useful paper-target evidence, not live authorization.
- Denver, Los Angeles, San Francisco, and Seattle cannot be promoted or rejected from this run because counted target-date CLOB gaps dominate first. Their immediate work item is a clean continuous CLOB tape and strict audit pass for the target date.
- The `harvest_only/SHADOW` markets are shadow-only candidates after event gates, freshness, and tape evidence pass.
- No June 27 row supports `edge_research` promotion or live trading.

## June 26 Active-Date Addendum

Latest June 26 current-date shadow drill: `data/mm_runs/2026-06-26/20260626T134201734227Z`.

- Preflight: `PASS`.
- Quote-permission rows: 9.
- Live-trade-permission rows: 0.
- No-quote rows: 123.
- No-quote reasons: 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 2 `NO_QUOTE_DISAGREEMENT_SHADOW`.
- Quoted rows: Dallas `87 F or below`, `88-89 F`, `90-91 F`, `96-97 F`, `98-99 F`, `100-101 F`, `102-103 F`, `104-105 F`, and `106 F or higher`.
- Quote type: two-sided `QUOTE_HARVEST_MID`, `harvest_only`, capped to 1.75 shares per side by the early-hour guardrail.
- Bounded score: `data/backtest/mm_paper_shadow_20260626T134201734227Z_20260626.json` found 18 quote legs, 0 conservative fills, 0 queue-estimated fills, reward score 12.26505, counterfactual reward 109.2508 USDC, and fill evidence `BLOCK`.

Interpretation: model freshness can now clear, but known-edge coverage still blocks 121 of 132 current-date rows. The Dallas current-date quotes are useful shadow targets for markout collection; they are not live authorization and not promotion-grade evidence.

## June 26 Countable Daily-Roll Addendum

Point-in-time countable active-day daily-roll diagnostic folder: `data/mm_runs/2026-06-26/20260626T135556165467Z`.

- Mode: `paper-live-forward`.
- Evidence mode: `active_day_live_forward`.
- Latest status check after guarded recovery: status `started`, PID 29180, latest run folder `data/mm_runs/2026-06-26/20260627T031938117215Z`, evidence mode `post_settlement_evaluation`, latest tick rows 132, useful-work liveness `SKIPPED`, live-forward gate `BLOCK`, `current_counts_toward_live_forward_gate = false`, supervisor state `RUNNING`, supervisor action `noop`, and runtime identity matching current source. The active-day folder `data/mm_runs/2026-06-26/20260626T231738340378Z` remains diagnostic countable-window evidence, while the current runtime is noncountable post-settlement evidence.
- Previous fixed bounded diagnostic artifact: `data/backtest/mm_paper_daily_roll_20260626T135556165467Z_known_edge_dims_20260626.json`.
- Fixed bounded diagnostic result: 4,092 quote rows, 0 quote legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 0, exchange economics `PASS`, paper freshness `PASS`, fill evidence `PASS` only because no quote legs existed, live-forward paper days 1, and model-variant scoring `SKIPPED (skip_model_variants)`.
- Fixed bounded diagnostic no-quote split: 4,070 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 22 `NO_QUOTE_STALE_INPUT`; quote-blocker diagnostics found 2,046 `promotion_block/no_quote/BLOCK` rows, 1,364 `missing_known_edge_record/no_quote/SHADOW` rows, and 682 `missing_known_edge_record/no_quote/BLOCK` rows.
- The new `mm_quote_blocker_diagnostics_v0.8` section reads exact policy-match dimensions when quote tapes include `known_edge_match_*`, keeps diagnostic-only inferred dimensions separate, runs a dry-run comparison against the current default known-edge map, reports nearest-record dimension gaps for inferred misses, adds coverage action items, and adds blocker-overlap rows joining no-quote reason, event gate, known-edge permission, known-edge reason, and promotion state. Known-edge record hours are now canonicalized so map records such as `17:00Z` compare as the same hour as active rows with `17`.
- Previous bounded quote diagnostic from the active daily-roll tape before `mm_quote_intent_v0.3`: `data/backtest/mm_paper_active_latest_20260626_quote_diag.json`, from `data/mm_runs/2026-06-26/20260626T160337445814Z`, scored 4,224 accumulated quote rows, 0 quote legs, 0 quote-permission rows, 0 conservative fills, 0 queue-estimated fill legs, exchange economics `PASS`, paper freshness `PASS`, live-forward paper days 1, 3,916 known-edge permission-blocked rows, 308 stale-input rows, and 44 event-gate-suppressed rows. It skipped fill simulation and model-variant scoring, so it is historical blocker evidence only. The diagnostic loaded the then-current `data/backtest/mm_known_edge_map.json` with 238 records and found 0 inferred known-edge record matches and 2,112 inferred missing-record rows that still missed that map. The current accepted map now has 17 records; use current-map diagnostics for present readiness decisions.
- v0.3 quote-schema probe: `%TEMP%\weather-mm-v03-probe\2026-06-26\codex-v03-probe` wrote `mm_quote_intent_v0.3` rows with exact `known_edge_match_*` fields, and the final `data/backtest/mm_paper_v03_probe_20260626_quote_diag.json` found 132 blocked rows, 0 quote-permission rows, 88 known-edge permission-blocked rows, 44 stale-input rows, and 0 event-gate-suppressed rows after moving model-freshness inputs aged into `WARN`. The exact fields now show `hour_utc = 16`, source freshness `true/all_fresh`, and still-missing band-distance, taxonomy, and book buckets where policy inputs do not provide them.
- Current-source v0.3 event-window shadow probe: `data/mm_runs/2026-06-26/20260626T165003338813Z` wrote exact match fields and scored to `data/backtest/mm_paper_shadow_20260626T165003338813Z_v03_current.json`. It found 132 blocked rows, 0 quote-permission rows, 132 known-edge permission-blocked rows, 0 stale-input rows, 132 event-gate-suppressed rows, 0 inferred known-edge record matches, and 66 inferred misses. Exact missing dimensions remain `hour_utc = 16`, missing band-distance/taxonomy/book bucket, blank `known_edge_match_regime`, and `source_freshness_state = all_fresh`; the rendered no-quote output regime is `none`. Inferred nearest-record gaps point to stale paper-slice hour/regime/taxonomy/book mismatches.
- Current-source v0.3 WU/SWOB shadow probe: `data/mm_runs/2026-06-26/20260626T170013329405Z` scored to `data/backtest/mm_paper_shadow_20260626T170013329405Z_v03_current.json` with 132 blocked rows, 0 quote-permission rows, 121 known-edge permission-blocked rows, 11 stale-input rows, 11 event-gate-suppressed rows, 0 inferred known-edge record matches, and 66 inferred misses. This demonstrates that fresh exact match fields can coexist with a moving model-freshness blocker.
- Current-source active daily-roll score after the v0.8 backoff recheck: `data/backtest/mm_paper_active_20260626T231738340378Z_v08_backoff_recheck.json` selected `data/mm_runs/2026-06-26/20260626T231738340378Z`. It scored 4,807 quote rows, 0 quote legs, 0 quote-permission rows, 4,345 known-edge permission-blocked rows, 462 stale-input rows, 1,243 event-gate-suppressed rows, 0 inferred known-edge record matches, and 2,376 inferred misses. The top required-action buckets are `keep_blocked_until_promotion_gate_passes` for 2,178 promotion-blocked rows, `collect_countable_markouts_before_map_change` for 1,441 missing SHADOW cells, and `collect_countable_markouts_before_map_change` for 726 missing BLOCK cells. The hour normalization removed false same-hour gap text but did not create quote permission.
- Current-source one-shot during `INFO_EVENT_METAR_PRINT`: `data/mm_runs/2026-06-26/20260627T004704070519Z` passed preflight with 132 quote rows, 0 quote-permission rows, 0 live-trade-permission rows, 88 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 44 `NO_QUOTE_INFORMATION_EVENT`, and 132 event-gate-suppressed rows during `INFO_EVENT_METAR_PRINT`. Its score `data/backtest/mm_paper_shadow_20260627T004704070519Z_current_source.json` has 0 stale-input blockers, 0 inferred known-edge record matches, and 11 inferred misses. Required-action buckets are 77 `keep_blocked_until_promotion_gate_passes` rows and 11 `collect_countable_markouts_before_map_change` rows.
- Latest current-source one-shot after the information-event gate cleared: `data/mm_runs/2026-06-26/20260627T010734537264Z` passed preflight with 132 quote rows, 6 harvest-only quote-permission rows, 0 live-trade-permission rows, 88 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 34 `NO_QUOTE_MISSING_BOOK`, 4 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED`, and 6 `QUOTE_HARVEST_MID` rows. The allowed cells were Austin `94-95 F`, Austin `96-97 F`, Dallas `94-95 F`, Dallas `96-97 F`, Houston `92-93 F`, and Houston `94-95 F`. Its score `data/backtest/mm_paper_shadow_20260627T010734537264Z_current_source.json` still has 88 known-edge blockers, 0 stale-input blockers, 0 inferred known-edge record matches, 11 inferred misses, and required-action buckets of 77 `keep_blocked_until_promotion_gate_passes` rows plus 11 `collect_countable_markouts_before_map_change` rows. The six quote permissions are noncountable shadow/operator-drill evidence and do not change the map without countable markouts.
- Latest June 27 selected-market one-shot after the information-event gate cleared: `data/mm_runs/2026-06-27/20260627T061148175884Z` passed preflight with 33 quote rows, 16 harvest-only quote-permission rows, 0 live-trade-permission rows, 10 `NO_QUOTE_DISAGREEMENT_SHADOW`, 7 `NO_QUOTE_MISSING_BOOK`, and no event-gate suppressions. Its score `data/backtest/mm_paper_shadow_20260627T061148_subset_austin_dallas_houston.json` has 17 blocked rows, 0 inferred known-edge misses, 32 unresolved resting quote legs, and fill evidence `BLOCK`. This reinforces Austin/Dallas/Houston as the near-term paper subset, but does not change the accepted map or live gate.
- Pre-recovery fixed paper-live-forward post-settlement score: `data/backtest/mm_paper_postsettlement_latest_20260627T020932_current_source.json` was generated at `2026-06-27T02:10:06Z` from `data/mm_runs/2026-06-26/20260627T011838375104Z`; it has 5,016 quote rows, 118 quote-permission rows, 0 live-trade-permission rows, 2,926 known-edge blockers, 473 stale-input blockers, 1,303 event-gate-suppressed rows, 0 inferred known-edge record matches, and 330 inferred misses. The quote permissions are noncountable post-settlement evidence and do not change map permissions.
- Latest regenerated recovered paper-live-forward post-settlement score: `data/backtest/mm_paper_postsettlement_recovered_20260627T0233_competitor_source.json` was generated from `data/mm_runs/2026-06-26/20260627T021842583677Z`; it has 1,320 quote rows, 17 quote-permission rows, 0 live-trade-permission rows, 693 known-edge blockers, 264 stale-input blockers, 0 inferred known-edge record matches, 110 inferred misses, and a CLOB-calibrated competitor score. The quote permissions are noncountable post-settlement evidence and do not change map permissions.

Interpretation: the current-source scorer can explain the active-day blocker. The continuous daily-roll loop recovered from stale-code backoff after guarded recovery, but it is still noncountable post-settlement evidence. The latest clean one-shot current-source artifact has no stale-input blocker and emits six harvest-only shadow permissions, and the fixed recovered paper-live-forward score captures noncountable quote permissions, but active daily-roll evidence remains quote-starved and uncountable. The primary blocker in scored rows is still known-edge/promotion permission under the default map, with missing books/cadence gaps preventing broader harvest coverage. Live permissions remain correctly false.

## Active-Row Map Coverage Drift

The current accepted `data/backtest/mm_known_edge_map.json` has 17 records: 7 `harvest_only`, 3 `edge_research`, and 7 `no_quote`. Its Dallas record is now broad enough to allow Dallas harvest rows:

- `market_id = dallas`
- `cutoff = *`
- `hour_utc = *`
- `band_distance_bucket = *`
- `band_type = *`
- `casebook_taxonomy = *`
- `regime = *`
- `source_freshness_state = *`
- `permission = harvest_only`
- `reason = awaiting_paper_markouts`

That means Dallas is no longer primarily a known-edge coverage miss in the latest moving folder. The current Dallas split is 200 `NO_QUOTE_MISSING_BOOK`, 99 `NO_QUOTE_INFORMATION_EVENT`, 33 `NO_QUOTE_STALE_INPUT`, 19 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED`, and 1 `QUOTE_HARVEST_MID`. The remaining known-edge blockers are concentrated in other markets with `promotion_block` or `missing_known_edge_record` states. The latest generated known-edge candidate map has 217 records, including many CLOB-recon harvest candidates, but that output is diagnostic only. Do not replace the accepted 17-record map with the generated candidate map just to restore quotes; first prove active-row cells with countable paper markouts and promotion-gate evidence.

## Blocker Map

| Market | Rows | Status | Action |
|---|---:|---|---|
| atlanta | 11 | Missing known-edge records | Build shadow evidence or keep no-quote |
| austin | 11 | Missing known-edge records | Build shadow evidence or keep no-quote |
| chicago | 11 | Promotion block | Inspect promotion/paper evidence |
| dallas | 1 quote, 10 missing-book | Collect active-window markouts; fix book gaps |
| denver | 11 | Missing known-edge records | Build shadow evidence or keep no-quote |
| houston | 11 | Missing known-edge records | Build shadow evidence or keep no-quote |
| los-angeles | 11 | Promotion block | Inspect promotion/paper evidence |
| miami | 11 | Promotion block | Inspect promotion/paper evidence |
| nyc | 11 | Promotion block | Inspect promotion/paper evidence |
| san-francisco | 11 | Promotion block | Inspect promotion/paper evidence |
| seattle | 11 | Promotion block | Inspect promotion/paper evidence |
| toronto | 11 | Missing known-edge records | Build shadow evidence or keep no-quote |

Missing known-edge records cover the full active band set for Atlanta, Austin, Denver, Houston, and Toronto. Promotion blocks cover all bands for Chicago, Los Angeles, Miami, NYC, San Francisco, and Seattle.

## Dallas Missing-Book Rows

Dallas has harvest-only permission across all 11 bands, but only one band produced a quote. The other ten rows had token ids and condition ids but no usable book spread, so policy emitted `NO_QUOTE_MISSING_BOOK`.

| Band | Mid | Depth 1pct | Fair probability | Edge |
|---|---:|---:|---:|---:|
| 85 F or below | 0.0005 | 1195.09 | 0.0 | -0.0005 |
| 86-87 F | 0.0005 | 1386.22 | 0.0 | -0.0005 |
| 88-89 F | 0.0005 | 108.71 | 0.0 | -0.0005 |
| 90-91 F | 0.0005 | 2005.09 | 0.0 | -0.0005 |
| 94-95 F | 0.0005 | 2461.30 | 0.0001637907 | -0.0003362093 |
| 96-97 F | 0.0005 | 1741.69 | 0.0000031652 | -0.0004968348 |
| 98-99 F | 0.0005 | 2010.29 | 0.0000000065 | -0.0004999935 |
| 100-101 F | 0.0005 | 2068.83 | 0.0 | -0.0005 |
| 102-103 F | 0.0005 | 2072.73 | 0.0 | -0.0005 |
| 104 F or higher | 0.0005 | 2072.73 | 0.0 | -0.0005 |

These missing-book rows should not be forced into quotes. They should be diagnosed as book/midpoint quality gaps and then re-scored in paper.

## One-Run Paper Score

Before the streamed-casebook and compact-leg runtime fixes, the full promotion-grade `weather.market.mm_paper` command timed out after 300 seconds on the full historical corpus. The explicit one-run score completed quickly:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-25\20260626T020148684548Z --json-out data\backtest\mm_paper_quote_starvation_20260626T020148684548Z.json --report-out data\backtest\mm_paper_quote_starvation_20260626T020148684548Z.md --fills-out data\backtest\mm_paper_quote_starvation_fills_20260626T020148684548Z.csv --known-edge-out data\backtest\mm_known_edge_quote_starvation_20260626T020148684548Z.json --known-edge-report-out data\backtest\mm_known_edge_quote_starvation_20260626T020148684548Z.md
```

Result:

- Runtime: 4.4 seconds.
- Run folders: 1.
- Quote rows / legs: 132 / 2.
- Conservative fills: 0.
- Queue-estimated fill legs: 0.
- Gate status: `OPEN`.
- Paper-score freshness: `NO_ACTIVE_DAY`.
- Fill evidence completeness: `BLOCK`.
- Missing-size trade rows: 1,944.
- Missing-book queue legs: 1.
- Missing-trade-size queue legs: 0.
- P&L, reward, and rebate estimates: 0.

The latest regenerated recovered one-run known-edge map produced 217 records: 177 `harvest_only`, 37 `no_quote`, and 3 `edge_research`. That map is diagnostic only; it should not replace the standard map until promotion-grade full-corpus scoring is made reliable.

## Full-Corpus Scoring Bottleneck

`discover_run_folders(data/mm_runs)` found 37 candidate folders, 36 eligible and 1 excluded. Several eligible quote tapes are large:

- `data/mm_runs/2026-06-23/20260623T165025535344Z`: about 105 MB of quote tape.
- `data/mm_runs/2026-06-21/20260621T153607128252Z`: about 83 MB of quote tape.
- `data/mm_runs/2026-06-24/20260624T233003009128Z`: about 82 MB of quote tape.
- `data/mm_runs/2026-06-22/20260622T233019900796Z`: about 14 MB of quote tape.
- Post-settlement roll `20260626T015632370043Z`: useful for bounded diagnostics, not countable active-window evidence.

Bounded and summary-only scoring are available for diagnostics, and full-corpus standard model-variant scoring now writes a current report. It remains blocked for promotion because fill evidence is incomplete and model-variant promotion is blocked:

- explicit `--run-folder` for current diagnostics,
- `--latest-n` for recent runs,
- `--target-date` / `--run-target-date` filtering,
- `--evidence-mode` filtering,
- bounded reports that disclose `diagnostic_selection_not_full_corpus`,
- `--skip-model-variants` for faster operational diagnostics, with model-variant bakeoff disclosed as `SKIPPED (skip_model_variants)`,
- `--skip-fill-simulation --skip-model-variants` for full-corpus quote/no-quote and reward-score diagnostics, with fill evidence disclosed as `SKIPPED (skip_fill_simulation)`,
- streamed casebook loading, compact quote legs, and quote-row release reduce memory pressure enough for the current full-corpus standard model-variant report to write,
- cached CLOB/trade joins for queue companion scoring remain useful follow-up work.

The full summary-only run completed in about 176 seconds with 628,481 quote rows, 71,828 quote legs, 35,914 quote-permission rows, reward score 165,800.676275, paper freshness `PASS`, fill evidence `SKIPPED`, and model-variant scoring `SKIPPED`. Its known-edge map had only 17 records and is diagnostic only.

The later full-corpus fill/queue/markout run with `--skip-model-variants` wrote `data/backtest/mm_paper_full_promotion_skip_variants_compact_legs_20260626.json`: 636,005 quote rows, 71,836 quote legs, 44 conservative fills, 13,045 queue-estimated fill legs, paper freshness `PASS`, fill evidence `BLOCK`, reward score 165,822.476275, counterfactual reward 999.397309 USDC, and model-variant scoring `SKIPPED`.

The later standard full-corpus model-variant run wrote `data/backtest/mm_paper_full_standard_model_variants_release_quotes_20260626.json`: 636,005 quote rows, 71,836 quote legs, 44 conservative fills, 13,045 queue-estimated fill legs, paper freshness `PASS`, fill evidence `BLOCK`, model-variant scoring `PASS`, 39,534 model-variant quote rows, 264 model-variant quote legs, 32 model-variant conservative fills, and model-variant promotion `BLOCK`.

The regenerated standard report now exposes the fill-evidence blocker surface directly: 8,893 missing-size trade rows, 2,182 missing-book queue legs, 26 missing-trade-size queue legs, and 0 unresolved resting quotes. The top missing-size events are Dallas June 25, Denver June 23, Denver June 21, Austin June 23, Atlanta June 21, and Houston June 21; the largest missing-book queue gaps are early-hour `YES_ASK` slices. Until those gaps close, the known-edge map is useful for harvest-only/no-quote research but not for live reward-farming promotion.

Skip-model-variant reports are not model-promotion evidence, and skip-fill reports are not fill, P&L, or known-edge promotion evidence. Until model-variant promotion and fill evidence both pass, use explicit `--run-folder` or bounded target-date scoring for targeted diagnosis and do not treat bounded, summary-only, or skip-variant known-edge maps as the standard map.

The earlier bounded active-day promotion-grade score selected `data/mm_runs/2026-06-25/20260626T015448206993Z` and found 132 quote rows, 0 quote legs, 0 quote-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_INFORMATION_EVENT`, and reward score 0. Quote-blocker diagnostics showed all 132 rows were event-gate suppressed, 121 were known-edge permission-blocked, and 11 harvest-only rows were suppressed by the event gate, with top known-edge states 66 `promotion_block/no_quote/BLOCK`, 33 `missing_known_edge_record/no_quote/SHADOW`, 22 `missing_known_edge_record/no_quote/BLOCK`, and 11 `awaiting_paper_markouts/harvest_only/SHADOW`. The current June 26 countable daily-roll addendum above is the latest active-day blocker.

The earlier June 26 shadow drill selected `data/mm_runs/2026-06-26/20260626T132648384687Z` and found 132 quote rows, 0 quote legs, 0 quote-permission rows, 121 `NO_QUOTE_STALE_INPUT`, 11 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, and reward score 0. That was a stale-model diagnostic, not the current quote-permission state.

The latest June 26 shadow drill selected `data/mm_runs/2026-06-26/20260626T134201734227Z` and found 132 quote rows, 18 quote legs, 9 quote-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 2 `NO_QUOTE_DISAGREEMENT_SHADOW`, reward score 12.26505, and fill evidence `BLOCK`. This makes the current known-edge blocker actionable again: the model-freshness gate cleared, but most markets/bands still lack permission or promotion evidence.

## Go / No-Go Impact

PASS:

- Target-date snapshot/model/source capture can now reach all 12 markets.
- Target-date CLOB capture can discover all 12 markets.
- Shadow/paper modes still emit no live permission.
- The latest diagnostics identify true coverage blockers separately from stale-input blockers.

WARN:

- The latest June 27 shadow run has preflight `WARN`, not `PASS`.
- Four markets are directly blocked by known-edge/promotion state: Toronto, NYC, Atlanta, and Miami.
- Eight markets are blocked by counted CLOB tape gaps before coverage can be judged.
- Reward score, fill evidence, and queue evidence remain absent for the latest run because no quote permissions were emitted.

BLOCK:

- Latest June 27 quote-permission rows: 0.
- Latest June 27 live-trade-permission rows: 0.
- Latest readiness status: `BLOCK`.
- Fill-evidence completeness and actual payout evidence.
- Countable live-forward days.
- Model-variant promotion for edge mode.
- Known-edge map broadening from noncountable evidence.
- Live capital.

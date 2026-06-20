# Roadmap Open And Blocked Audit - 2026-06-18

This snapshot reviews all numbered roadmap items after the data-layer audit.
Status scan: 154 total items, 137 `COMPLETE`, 14 `PARTIAL`, and 3 `OPEN`.

## Status Taxonomy

Roadmap item states are `COMPLETE`, `PARTIAL`, and `OPEN`.
`COMPLETE` means the item has accepted implementation evidence or an explicit
final disposition, including superseded or intentionally discontinued work.
Legacy terminal labels should be written as `COMPLETE`; there is no separate
terminal state. `PARTIAL` means useful work exists but the acceptance condition
is not met. `OPEN` means the item still has primary
implementation or infrastructure work left.

## 2026-06-19 Continuation Update

Item 146's local tape-backup capacity and restore-drill blocker is cleared by
the current evidence. `data/backtest/tape_backup_status.json` is `OK`, restore
SLA is `OK`, `3357` files restore with zero schema failures, all 6 required
CLOB artifact classes restore, and fleet observability reports tape backup as
`OK`. In the rows below, older references to Item 48 or Item 146 being blocked
by tape-backup capacity are superseded: the remaining storage caveat is durable
external/NAS/cloud backup-root configuration, not local manifest capacity.

The settled-day freshness P0 also moved after repair. The current
`data/backtest/settled_day_freshness.json` is `WARN`, not `FAIL`: all 12 June
18 markets are complete and the missing replay-status count is 0. Daily
learning remains `BLOCKED`, but its first P0 is now the hourly performance
gate; fleet observability remains `CRITICAL` because collection coverage gaps
remain.

Item 147's time-split alpha candidate now has a direct candidate-hourly audit
over regenerated Item-69 rows.
`data/backtest/item147_time_split_alpha_hourly_candidate_performance_report.md`
passes the candidate early-hour gate on 44 F-family market-days, with
00:00-08:00 candidate Brier `0.0511` versus current `0.0555` and market
`0.0519`. This proves the current Item 147 aggregate baseline is not hiding an
early-hour candidate regression. The refreshed staged promotion refresh uses
strict variant-ID matching before applying that evidence:
`hourly_performance_mitigation.applied=true` and
`candidate_hourly_matches=true`, so the hourly-performance blocker drops out of
the staged readiness blocker list while the operational table still shows
current-serving hourly gate `BLOCK` and candidate hourly gate `PASS`. It does
not clear Item 48 readiness by itself: Austin, Los Angeles, NYC, San Francisco,
and Seattle remain blocked in staged promotion evidence, Dallas/Miami remain
shadow, aggregate market skill is still open, and live-forward SLO still blocks.

The live-forward SLO blocker is not stale-loop noise. A
`2026-06-19T14:45:41-04:00` `snapshot_tracker --status` check showed the
snapshot supervisor `RUNNING`, process alive, current runtime identity, latest
snapshot age `2.6` minutes, zero missing/stale live variant-prediction markets,
and healthy source-family status. The blocker is countability: the
12:00-18:00 local active window was still open, all 12 markets were `AT_RISK`,
`covers_afternoon=false`, and already-recorded intra-window max gaps ranged
from `18.5` to `28.5` minutes against the 15-minute effective tolerance. These
missed live snapshot rows cannot be reconstructed into proof-grade live
evidence from local tapes. Keep the loop running, rerun fleet observability
after 18:00 local, and require a clean future live day or an explicit
cadence/SLO policy change before counting broad live-forward evidence.

The post-window check confirms that expectation. The report
`data\backtest\fleet_observability_after_2026_06_19_window_report.md`
generated after 18:00 local remains `CRITICAL`; broad live-forward SLO is
`BLOCK` and does not count. Snapshot coverage blocks all 12 markets, with
Toronto first (`9` gaps, max `25` minutes) and all market max gaps still above
the effective 15-minute tolerance. CLOB discovery, CLOB book freshness,
observation-trigger health, latest model rows, variant prediction freshness,
and afternoon-window coverage pass. The generated source-status repair command
was also run:
`python -m weather.collection.snapshot_tracker --backfill-source-status --overwrite-source-status`
rebuilt `200,226` source-status rows across `177` folders, but the refreshed
report
`data\backtest\fleet_observability_after_2026_06_19_source_status_backfill_report.md`
still reports `CRITICAL` because `open_meteo` remains degraded for all 12
markets and snapshot coverage remains the first blocker. June 19 is therefore
not recoverable as broad live-forward proof from metadata backfill alone.

The source-status recovery guidance is now more precise. `collection_health`
retains per-family fresh/failed/fallback source lists, and fleet observability
maps Open-Meteo cache fallback to root cause `open_meteo_provider_fallback`
with owner `Open-Meteo quota / forecast source collector`. The refreshed
diagnostic report
`data\backtest\fleet_observability_after_2026_06_19_source_status_recovery_detail_report.md`
still blocks broad live-forward evidence, but it shows the true source-status
repair layer: all 12 markets have Open-Meteo family fallback sources
(`open_meteo`, `open_meteo_multimodel`, `global_ensemble`, or `eccc_gem`),
and the recovery command is now `python -m weather.collection.snapshot_tracker
status` for provider/source-loop diagnosis rather than another source-status
backfill.

Open-Meteo-family provider pressure now has a future-live mitigation too.
`weather.model.model_sources` reuses last-good Open-Meteo-family forecast
cache for the full configured source TTL before making another provider call:
`90` minutes for `open_meteo`, and `120` minutes for `global_ensemble`,
`open_meteo_multimodel`, and `eccc_gem`. This replaces the old 10-minute
pre-provider reuse window that could turn a still-valid forecast cache into a
429-backed `rate_limited_cache` fallback row. Regression coverage proves an
80-minute `open_meteo` cache skips the provider call while a 95-minute cache
refreshes live. A real-cache probe against the June 19 market roots, with
provider calls disabled, showed the new policy would skip `27/36`
Open-Meteo-family calls; the remaining 9 were already beyond their TTL and
still correctly require a provider refresh. This hardens future live-forward
source freshness, but it does not change the already-captured June 19 source
status rows.

The source cache loader now has corrupt-cache quarantine as the companion log
hygiene fix. If `last_good_sources.json` cannot be decoded, or if it decodes to
a non-object root, `weather.model.model_sources` moves it to
`last_good_sources.corrupt.*.json` and returns an empty cache for that cycle
instead of repeatedly logging the same parse error. This targets the
loop-integrity samples that showed `Error loading last good sources cache`
console text during observation-trigger runs. The current 12 market cache files
all parse under the production Python loader, so this pass did not move any
live cache file; the mitigation is for future corrupt or partially written
cache states.

The live-forward recovery commands are executable now. `fleet_observability`
and market-making preflight were emitting the invalid positional status form,
but the CLI only accepts `--status`. The constants and tests now use `python -m
weather.collection.snapshot_tracker --status`. I also restarted the snapshot
supervisor from stale code onto the current source tree after these
source-fetch changes: stale PID `37592` stopped, PID `44504` started, and the
follow-up status reported `RUNNING`, `runtime_code_state=current`, and
`runtime_identity_matches_current=true`.
`data\backtest\fleet_observability_after_snapshot_restart_rate_limit_detail_2026_06_19_report.md`
is still `CRITICAL` because the June 19 snapshot gaps are already baked in,
but its recovery checklist uses the corrected command and classifies
Open-Meteo rate-limited source rows under `Open-Meteo quota / forecast source
collector` with explicit `rate_limited_sources`.

Open-Meteo-family fetches are also sequential within each live capture now.
Unrelated sources still fetch in parallel, but `open_meteo`,
`open_meteo_multimodel`, `global_ensemble`, and `eccc_gem` run as one
same-provider group so a 429 on one source activates the shared cooldown before
later expired family sources can call the provider. The cache path still wins
before cooldown, so TTL-valid family cache remains `fresh_cache`. This is
future live-forward hardening for the same source-status gate; it does not
retroactively make June 19 countable.

The source-status blocker is now narrowed to the actual coverage loss.
`collection_health` distinguishes rate-limited Open-Meteo-family rows with
fresh same-family coverage from families that have no usable fresh source, and
fleet observability now reports `blocking_family_count` separately from
affected family count. The refreshed report
`data\backtest\fleet_observability_after_rate_limit_family_coverage_2026_06_19_report.md`
is still `CRITICAL`, but `source_status_freshness` now blocks 1 market instead
of all 12. The remaining source-status blocker is Toronto, where
`eccc_gem`, `global_ensemble`, and `open_meteo` are rate-limited and no fresh
Open-Meteo-family source remains in the latest status row. Snapshot coverage
still blocks all 12 markets, so June 19 remains unusable as broad live-forward
proof.

The Toronto cache root cause also has a forward fix. Earlier replay inputs had
successful `global_ensemble` rows, but the later Toronto
`last_good_sources.json` lost all Open-Meteo-family keys, consistent with
concurrent writers replacing the cache with a narrower source set.
`model_sources.save_last_good_sources` now takes the repo's writer lock,
reloads and merges the current disk cache under that lock, and only then does
the atomic replace. If the lock is busy, it skips the save rather than
clobbering unrelated source entries. Tests cover merge preservation and busy
lock behavior. The snapshot supervisor was restarted after this change as
well; stale PID `39072` was stopped, PID `35236` started, and status returned
`RUNNING` with current runtime identity.

The next fleet refresh,
`data\backtest\fleet_observability_current_2026_06_19_after_cache_lock_report.md`,
is still `CRITICAL`. Snapshot coverage still blocks all 12 markets, and
source-status still blocks only Toronto. That refresh exposed a second
publication-lag edge case: ECCC SWOB listed a current-hour CYYZ XML file before
the file was retrievable, so one per-file 404 forced the whole SWOB source into
cache fallback even though earlier same-day SWOB rows were available.
`fetch_eccc_swob` now skips individual listed SWOB XML 404s, keeps valid
earlier same-day rows as live data, and records skipped-file metadata in the
payload. The snapshot supervisor was restarted again after this fix: stale PID
`35236` stopped, PID `38648` started, and status returned `RUNNING` with
current runtime identity and zero consecutive errors. This hardens future
source-status evidence; it does not recover June 19 broad live-forward proof.

The snapshot supervisor recovery cadence is now hardened for the next active
window. `data\snapshots\diagnostics.jsonl` showed the largest June 19 snapshot
holes lining up with repeated stale-code restarts during development, while
steady-state capture cycles were not the bottleneck. The Windows registration
script now runs the short `snapshot_tracker --ensure` check every 2 minutes
instead of every 10 minutes, keeping the actual capture loop interval at 10
minutes. The local `WeatherSnapshotLoopSupervisor` task was re-registered and
its repeating trigger reports `PT2M`; the loop was restarted from stale PID
`38648` to PID `33816` and returned `RUNNING` with current runtime identity.
This does not make June 19 countable, but it reduces future stale/dead-loop
recovery time below the 15-minute live-forward tolerance.

Item 35's full continuous-density v0.7 lane is now fully evidenced and
rejected. `data\backtest\item35_density_full_candidate_v0_7.pkl` trained over
`76,865` rows, and
`data\backtest\item35_density_full_replay_v0_7_report.md` replayed all
`76,879` pinned market rows with zero missing candidate rows. The result is
`BLOCK / DO_NOT_CUT_OVER`: aggregate candidate Brier `0.045390` versus current
`0.042669` and market `0.037323`; daily-first candidate `0.044628` versus
current `0.041916` and market `0.036667`. Toronto still regresses current by
`+0.003174`, and forecast-profile guardrails block Austin, Denver, NYC,
San Francisco, Seattle, and Toronto. The conservative bridge shadow policy
improves aggregate to `0.042463` but still trails market by `+0.005140`, so it
is not a model-readiness unblock.

The Item 134/135 forecast-profile branch is now fully scored across all local
hours. The all-hour forecast-profile candidate scored all 67,430 F-family rows
with zero missing candidate rows, but still reports `BLOCK / DO_NOT_CUT_OVER`:
daily-first candidate `0.0421` versus current `0.0434` and market `0.0378`
(`+0.0043` versus market). Atlanta, Denver, and Houston pass; Dallas,
Los Angeles, and Miami remain shadow; Austin, Chicago, NYC, San Francisco, and
Seattle remain blocked. The all-hour cutoff-regime report removes the old
final-lock-in evidence gap, and final lock-in passes on 44 market-days, but
early (`+0.0034`), midday (`+0.0123`), and late (`+0.0074`) still miss market
tolerance. This rules out broad all-hour forecast-profile weighting as the next
Item 48 unblock.

The existing-variant basket path is also rejected. The new
`variant_basket_selection_validation_v0.1` report selects among Item 147
time-split alpha, Item 134 all-hour forecast-profile, Item 135 all-hour
regime-weighted, and current-serving rows on June 7/8, then evaluates June
12/13 for the five blocked Item 48 markets. The selected basket remains
`blocked`: later-date candidate `0.0465` versus market `0.0359`, gap
`+0.0106`, with all five markets blocked. Even the diagnostic eval oracle
stays outside tolerance at `+0.0092`, so existing branch selection is not the
next unblock. Slice-key policies are also rejected: the best selected slice
policy (`cutoff_regime`) still has a `+0.0101` market gap, and the best eval
oracle (`settlement_distance_bucket`) still has a `+0.0074` market gap.

The forecast-side rank repair path is rejected as well. The new
`forecast_side_rank_validation_v0.1` report boosts only the candidate's
top-ranked band inside inference-available forecast-pressure sides, selected on
June 7/8 and evaluated on June 12/13 for the five blocked Item 48 markets. The
selected policy worsens daily-first holdout from baseline `0.0465` to
`0.0516` versus market `0.0359`, widening the market gap from `+0.0106` to
`+0.0157` and regressing current by `+0.0012`. Even the diagnostic eval oracle
stays outside tolerance at `+0.0060`, so this is not the next unblock.

Item 32's 2026 pressure-level refresh caveat is now repeatably evidenced. The
new `pressure_level_cache_status_v0.1` command checked the June 1-13 replay
window with remote NOAA HEAD metadata. Local `air.2026.nc` and `hgt.2026.nc`
match the current remote file sizes exactly, both remote files are still
modified on March 19, 2026, and requested metric coverage is `0/13` complete
with latest cached metric date `2026-03-17`. This means the local cache is not
stale; upstream NOAA has not published replay-window pressure coverage yet.

CLOB capture continuity now has a per-folder status tape for future evidence.
`weather.market.market_microstructure` writes `clob_capture_status.jsonl`
with schema `clob_capture_status_v0.1` for every token/book capture attempt,
including failure-stage/error rows before exceptions re-raise. The refreshed
fleet audit
`data\backtest\data_layer_audit_after_clob_capture_status_report.md` is
`WARN` and shows the boundary clearly: `12/177` folders have capture-status
rows, but `0/165` training-ready folders do; raw token/book coverage remains
`96/177` and `84/177` overall, `84/165` and `72/165` training-ready. This
improves future CLOB root-cause logging for Items 35/48/156, but it does not
retroactively clear the missing train-side midpoint evidence blocker.

## Open And Locally Unblocked

These items have next steps that can be advanced from the repo and local
artifacts without waiting for a new settlement day, live account, or external
storage change.

| Item | Current state | Next unblock action |
| ---: | :--- | :--- |
| 32 | All-market reanalysis sidecars, aggregate evidence, positive-market lane contract, lane-aware training/replay plumbing, rich 2024/2025 sidecar coverage, pressure-level NetCDF4 cache support, and corrected active-feature source-family accounting are live. The full no-pressure lane is now fully scored rather than untested: sequential hour-sharded training completed hours `07` through `20`, the 14-shard merge wrote `data\backtest\item32_reanalysis_rich_no_pressure_full_merged_candidate.pkl` with 217,126 postprocess fit rows, 262 adjacent contexts, and 220 market-bias contexts, and the final artifact strips the temporary merge payload. The pinned replay still stayed `BLOCK / DO_NOT_CUT_OVER`: aggregate candidate `0.0431` versus market `0.0379`, daily-first candidate `0.0430` versus market `0.0378`, and daily-first market gap `+0.0052`, worse than the no-pressure recent-120 diagnostic (`+0.004893`). The merged replay inventory is `PASS` with zero blocking active families, so the remaining blocker is model quality, not lineage/parity. Houston and Los Angeles pass; Atlanta, Dallas, Denver, and Miami remain shadow; Austin, Chicago, NYC, San Francisco, and Seattle remain blocked. Parallel shard fan-out hit a MemoryError, so future shard training should stay sequential or memory-capped. Local tape backup capacity is no longer the gating issue; Item 146 now owns external backup-root durability. The pressure-level cache status command shows local 2026 pressure files match remote NOAA sizes but June 1-13 replay-window metric coverage is still `0/13`, latest cached metric date `2026-03-17`. | Stop widening reanalysis features and stop rerunning broad no-pressure. Repair the measured Austin/Chicago/NYC/San Francisco/Seattle market gaps while preserving Houston/Los Angeles and avoiding regressions in Atlanta. Rerun `pressure-level-status --check-remote` and refresh the 2026 pressure cache only after NOAA files grow or their modified timestamps advance beyond March 19, 2026. |
| 126 | Clean-checkout guard is implemented but failing on newly untracked project-critical files. | Track, move, or ignore the listed source/script/test files, then rerun the architecture guard. |
| 136 | Reliability shadow report is live; quote-risk surfacing remains local wiring. | Add the active reliability reason to quote-risk reports, then rerun the reliability report and focused quote tests. |
| 138 | Weak-family disposition policy is live; the active artifact still includes weak broad families. | Retrain or prune the served candidate under the disposition policy, then replay to prove weak families are excluded or regime-gated. |
| 139 | Registry-driven active-shadow refresh is OK, but it composes existing exports. | Execute registry prediction functions inline from the current promotion corpus before evidence-growth scoring. |
| 140 | Live variant tape contract and persistence are live; runtime execution is not. | Add a snapshot-time runner that maps registry `live_runtime` values to executable variant predictions. |
| 147 | Early-hour failure is diagnosed and the time-split alpha version of the hour-7/no-Austin plus exact-winner candidate is now the strongest no-market F-family lane. It clears aggregate blocked validation: replay `PARTIAL_PASS / PER_MARKET_ONLY`, daily-first candidate `0.040257` versus market `0.037830`, gap `+0.002427`. A staged promotion refresh with strict precomputed-candidate corpus matching and serving gauntlet enabled now produces 4 promote, 2 shadow, and 5 blocked decisions; serving is `PASS_WITH_SHADOWS`. Market-scoped residual alpha checks block for all five blocked markets, and `item147_blocked_market_repair_diagnostics` now classifies Austin/Los Angeles/San Francisco as current-fallback market gaps, Seattle as winner underpricing, and NYC as a smaller near/cool forecast-pressure gap. The raw-alpha fallback probe for Austin/Los Angeles/San Francisco also blocks: direct raw alpha worsens all three replay gaps, and the stricter split check either selects current fallback or regresses current. Contextual exact-row validation also blocks. Forecast-side rank validation also blocks and worsens daily-first holdout from baseline `+0.0106` to selected `+0.0157` versus market; even the eval oracle stays outside tolerance at `+0.0060`. CLOB-only anchor validation finds eval-oracle value but no split-selected policy because train-side CLOB midpoint coverage is `0.0000`; eval-side coverage is `0.2413`, CLOB beats candidate on covered eval rows (`0.0538` versus `0.0780`), and eval oracle would shrink daily-first gap to `+0.0044`. The folder-level audit shows why: all June 7/8 blocked-market train folders are missing raw `order_books` tapes and `clob_tokens`; June 12 is partial/one-sided, and June 13 is the first broadly usable midpoint day. Full `market_yes` anchoring shrinks selected gap to `+0.0035`, but remains no-edge serving-safety evidence and still blocks Los Angeles/NYC. | Stop using residual/raw alpha sweeps, exact-row context tuning, or forecast-side rank boosting as the next unblock. Keep the aggregate baseline, then build direct winner/market-signal repair for Seattle, near/cool forecast-pressure repair for NYC, newly trained or newly sourced non-current fallback skill for Austin/Los Angeles/San Francisco, and a CLOB midpoint collection-continuity repair before any market-informed anchor is promotion-safe. |
| 152 | Active-day bot runs can stop on disk pressure or market-discovery failures while daily-roll status remains stale `started`. | Add disk-headroom preflight, terminal child-exit status, blank-token/inactive-event CLOB discovery gates, and zero-trade root-cause reporting. |
| 153 | Live high comparisons can use decreasing or raw decimal observations instead of settlement-normalized monotonic highs. | Add a monotonic high ledger, settlement-bin normalization helpers, revision-event reporting, and live model-vs-observation regression tests. |

## Blocked Or Evidence-Gated

These items should not be marked complete until the named gate clears.

| Item | Blocker | How to unblock |
| ---: | :--- | :--- |
| 32 | Rich Open-Meteo history and pressure-level fields are populated for the 2024/2025 training window across all active markets, and the Item 32 inventories now pass with zero active blockers. The full no-pressure lane is also scored end-to-end: hours `07` through `20` were trained as shards, merged into a 14-hour artifact with 217,126 postprocess fit rows, and replayed on 67,430 F-family rows with zero missing candidate rows. That evidence still blocks promotion. Aggregate candidate Brier is `0.0431` versus current `0.0435` and market `0.0379`; daily-first candidate is `0.0430` versus current `0.0434` and market `0.0378`, leaving a `+0.0052` market gap. The full no-pressure result is worse than the bounded no-pressure recent-120 diagnostic (`+0.004893` daily-first market gap). Houston and Los Angeles pass; Atlanta, Dallas, Denver, and Miami stay shadow; Austin, Chicago, NYC, San Francisco, and Seattle remain blocked. High-disagreement guardrails still block Chicago (`+0.0067`), Denver (`+0.0062`), NYC (`+0.0188`), San Francisco (`+0.0045`), and Seattle (`+0.0147`) versus market. The 2026 pressure status report confirms the local cache is current against NOAA but has no June 1-13 pressure metrics yet (`0/13`, latest `2026-03-17`). | Treat broad no-pressure/reanalysis training as a scored dead end for now. Repair Austin plus the Chicago/NYC/San Francisco/Seattle market gaps directly while preserving Houston/Los Angeles and avoiding Atlanta regression; rerun pinned replay and inventory only after those targeted changes. For pressure, rerun `pressure-level-status --check-remote` and refresh only after NOAA files grow or their modified timestamps advance beyond March 19, 2026. |
| 35 | The all-market direct native-band lane remains the useful path, and the source-state blocker is now separable from the model-quality blocker. The source-guarded Toronto-alpha diagnostic keeps source-state ablation `READY` and moves Toronto to PASS, but the stricter source-guard time-split validation rejects it as a promotion path: readiness `BLOCK`, selected eval candidate `0.045334` versus market `0.039270`, daily-first market gap `+0.006072`, and Toronto selects alpha `0.00` rather than the diagnostic `0.30` while remaining blocked versus market (`+0.008679`). Market-scoped source-guard replays show the blocker shape: Chicago improves current but trails market by `+0.003315`, NYC trails by `+0.019104`, San Francisco is full current fallback and trails by `+0.005168`, Seattle trails by `+0.014495`, and Toronto regresses current while trailing market by `+0.004847`. A bounded all-market exact-winner source-guard artifact improves NYC (`0.055162 -> 0.052357`), Seattle (`0.038628 -> 0.037886`), and Toronto (`0.038274 -> 0.037871`) but still blocks and still leaves Toronto worse than current. A larger bounded pass now confirms that more all-market history is not the unblock: recent-120 stays `BLOCK` with daily-first market gap `+0.003611`, recent-365 worsens to `+0.003946`, and full unbounded training times out without an artifact. A split-safe winner-boost policy search rejects simple EQ multipliers, and the richer contextual winner validation also blocks. CLOB-only anchoring is not split-stable because train-side CLOB midpoint coverage is `0.0000`; eval-side coverage is `0.1761`, CLOB beats candidate on covered eval rows (`0.0492` versus `0.0909`), but eval oracle still leaves NYC/Seattle blocked. The folder audit classifies 9 of 15 Item 35 CLOB folders as missing raw tape/token maps, so this is a collection continuity blocker. The new data-layer raw CLOB gate now exposes the broader continuity gap too: `177` folders have derived CLOB features, but only `96` token-artifact days and `84` raw-book artifact days; among `165` training-ready folders, only `84` have token artifacts and `72` have raw-book artifacts. Live-pilot preflight now fails closed when target-date derived CLOB rows exist without raw token/book artifacts. Full `market_yes` anchoring shrinks selected gap to `+0.0011` and passes Seattle/Toronto but still blocks NYC and is no-edge market-price evidence. | Keep the source-freshness guardrail and the optimized all-market exact-winner family as bounded evidence, but do not spend the next pass on wider all-market history, generic/contextual exact-row multipliers, or market-price anchoring as model edge. Add richer winner repair for NYC/Seattle, a Toronto current-regression guard, and CLOB train-side raw-tape/token collection continuity before attempting another candidate. San Francisco still needs non-current signal, and Chicago/Toronto need broader market-gap repair. Mark Item 35 `COMPLETE` only after the candidate beats current per market and lifts Toronto without replay-row tuning. |
| 48 | F-family/all-market promotion readiness still fails per-market and operational gates, but the Item 147 time-split alpha replay and staged serving refresh move the F-family aggregate gate forward: blocked validation `PASS`, aggregate gap `+0.002446`, daily-first gap `+0.002427`, cutover decision `PER_MARKET_ONLY`, serving gauntlet `PASS_WITH_SHADOWS`, and decisions of 4 promote / 2 shadow / 5 blocked. Model blockers are Austin, Los Angeles, NYC, San Francisco, and Seattle; Dallas/Miami remain shadow. Generated residual-calibration experiment manifests now have scored blocked-market evidence, all five blocked-market residual alpha checks still fail later-date market tolerance, and the repair diagnostic identifies exact/current-fallback slices to target next. The new `winner_underpricing_casebook_v0.1` report scanned `30,569` blocked-market rows and found `387` concrete early cases where the market ranked the eventual winner top-two but the candidate underweighted or over-spread it: Seattle has average winner gap `+0.2555`, NYC `+0.1849`, Austin `+0.1683`, Los Angeles has the largest case count (`110`) with spread gap `+0.7639`, and San Francisco remains a smaller non-current-signal case set. The follow-up `forecast_pressure_tilt_validation_v0.1` report rejects a shallow all-band forecast-relative tilt: selected later-date daily-first Brier worsens from baseline `0.0465` to `0.0512` versus market `0.0359`, and every blocked market remains outside tolerance. The new `candidate_rank_sharpening_validation_v0.1` report rejects simple candidate top-rank concentration/flattening too: selected daily-first holdout worsens from baseline `0.0465` to `0.0493` versus market `0.0359`, widening the market gap from `+0.0106` to `+0.0134`. The new `forecast_side_rank_validation_v0.1` report rejects the narrower forecast-side rank version as well: selected daily-first holdout worsens to `0.0516` versus market `0.0359`, widening the gap to `+0.0157`, and even the eval oracle remains outside tolerance at `+0.0060`. The all-hour forecast-profile replay also blocks: it scores all 67,430 F-family rows and improves current, but daily-first candidate `0.0421` still trails market `0.0378` by `+0.0043`; Atlanta/Denver/Houston pass, Dallas/Los Angeles/Miami remain shadow, and Austin/Chicago/NYC/San Francisco/Seattle remain blocked. The all-hour cutoff-regime report removes the final-lock-in evidence gap and final lock-in passes, but early (`+0.0034`), midday (`+0.0123`), and late (`+0.0074`) still miss market tolerance. The existing-variant basket selector also blocks: selected later-date candidate `0.0465` versus market `0.0359`, gap `+0.0106`, all five markets blocked, and even the eval oracle remains outside tolerance at `+0.0092`; slice-key branch policies also block, with best selected gap `+0.0101` and best eval-oracle gap `+0.0074`. The raw-alpha fallback diagnostic rules out simply turning the raw candidate back on for Austin/Los Angeles/San Francisco. The Item 35 source-guard blocker pass and bounded exact-winner diagnostics confirm the direct-band lane can reduce NYC/Seattle underpricing, but not enough yet: recent-120 still trails market by `+0.003611` daily-first and recent-365 worsens to `+0.003946`, while the Item 147 time-split alpha lane remains the stronger aggregate baseline. Split-safe winner-boost and contextual winner-validation checks rule out generic or context-keyed exact-row multipliers. CLOB-only anchor validation shows useful later-date value but zero train-side midpoint coverage, so no split-stable selected policy exists yet; the folder audit traces this to missing raw book/token tapes on June 7/8. The data-layer audit now makes this failure mode visible across the fleet (`96/177` token-artifact days, `84/177` raw-book days; `84/165` and `72/165` on training-ready folders), and live-pilot preflight rejects target-date derived CLOB evidence without raw token/book artifacts. Full market-price anchoring helps Austin/San Francisco/Seattle but still blocks Los Angeles/NYC and is no-edge serving-safety evidence. Local backtest headroom was restored by pruning `17264418975` bytes of unmanifested same-disk backup partials and gzip-tiering 10 settled full-depth CLOB books; bounded replays are no longer blocked by local scratch space. The Item 32 no-pressure recent-120 replay adds a negative broad-lane signal: it remains `BLOCK / DO_NOT_CUT_OVER` with daily-first market gap `+0.004893`. Live-forward SLO still blocks, external backup-root durability remains partial, and production current-serving hourly performance remains `BLOCK`; the Item 147 candidate-hourly report mitigates the hourly blocker only for the staged candidate with strict variant-ID matching. | Repair the five remaining F-family market gaps with direct model/source changes, using the casebook targets for warm/cool-side winner-rank repair in Seattle/NYC and newly sourced or trained non-current skill for Austin/Los Angeles/San Francisco; do not use residual, raw-alpha, wider all-market exact/source-guard training, generic winner-multiplier, contextual exact-row tuning, candidate rank-sharpening, forecast-side rank boosting, single all-band forecast-pressure tilts, broad all-hour forecast-profile weighting, simple cutoff-regime blending, existing-variant branch or slice selection, market-price anchoring as model edge, or broad reanalysis sweeps. Preserve the aggregate gate pass, improve CLOB raw-tape/token collection continuity if market-informed anchors are used, continue storage/tiering, then rerun the staged promotion refresh. Separately require a countable live-forward SLO report, durable external backup-root evidence, and either production hourly gate repair or candidate-matched hourly mitigation before readiness can become `READY`. |
| 67 | MM-2 cannot complete without real eligible-account lifecycle and financial evidence. | Run heartbeat/post-only/cancel-all/user-stream probes and paid-vs-predicted reconciliation with credentials kept outside the repo. |
| 134 | The all-hour forecast-profile candidate scored all 67,430 F-family rows with zero missing candidate rows and improves current, but still fails daily-first market tolerance (`+0.0043`) and high-disagreement guardrails for Austin, Denver, NYC, San Francisco, and Seattle. | Improve or constrain the lane until daily-first market tolerance and per-market high-disagreement gates pass; do not rerun broad all-hour forecast-profile as the next unblock without a targeted repair. |
| 135 | The all-hour regime-weighted lane now has final-lock-in evidence, and final lock-in passes on 44 market-days. Acceptance still blocks because early (`+0.0034`), midday (`+0.0123`), and late (`+0.0074`) exceed market tolerance. | Reduce early/midday/late market deltas within tolerance; final-lock-in row coverage is no longer the blocker. |
| 136 | Degraded-source rows are sparse and Houston blocks risk-slice reliability. | Collect/backfill more degraded-source evidence or improve the shrinkage policy on risk rows. |
| 137 | Official-guidance inputs are below coverage and lineage thresholds. | Backfill or collect NWS, multi-model, ECCC, and MRMS rows until coverage plus replay gates pass. |
| 144 | Guardrail has policy/report evidence but no conservative live-forward fill markouts. | Collect scoreable early-hour fill rows with 30m and settlement markouts. |
| 146 | Local tape-backup capacity is no longer blocked. Cleanup removed 67 unmanifested same-disk backup partials totaling `17264418975` bytes, all settled full-depth CLOB books are gzip-tiered, `data/backtest/tape_backup_status.json` is `OK`, restore-drill SLA is `OK`, `3357` files restore with zero schema failures, and fleet observability reports tape backup as `OK`. The item remains partial because `data\tape_backups` is still a same-workstation backup root, so workstation-loss durability and documented growth headroom are not proven. | Move the backup root to external/NAS/cloud storage with growth headroom, rerun `weather.operations.tape_backup run --verify-checksums`, refresh fleet observability and daily learning, and keep the local zero-missing-critical/restore-pass evidence green. |
| 156 | CLOB midpoint continuity now has a dedicated owner because Items 35, 48, and 147 all hit the same split-stability blocker. Item 35's blocker audit has 15 folders, only 5 with midpoint availability, 9 missing raw tape/token maps, and train-side midpoint coverage `0.0000`; Item 147's audit has 20 folders, 8 with midpoint availability, 10 missing raw tape/token maps, and train-side midpoint coverage `0.0000`. The fleet data-layer audit exposes the broader raw-artifact gap: `96/177` folders have token artifacts and `84/177` have raw-book artifacts; among `165` training-ready folders only `84` have token artifacts and `72` have raw-book artifacts. `clob_coverage_audit_v0.2` now emits the chronological split coverage gate, and `market_anchor_time_split_validation_v0.2` now returns readiness `BLOCK` when `clob_midpoint` is evaluated but train-side midpoint coverage is below the `0.0500` selector threshold. The refreshed Item 147 anchor report still blocks with train coverage `0.0000`, train anchor rows `0`, and eval coverage `0.2413`. `promotion_refresh` now also blocks readiness for a candidate replay lane marked `uses_market_features=true`, so market-informed candidates cannot satisfy weather-only core promotion readiness. | Keep the CLOB supervisor and token discovery green through enough future settled days to create train-side midpoint evidence, rerun CLOB continuity/anchor validation only after train-side coverage clears the threshold, and keep market-informed output separate from no-market model-promotion evidence. |

## Immediate Sequence

1. Finish local hygiene first: Item 126.
2. Update scheduled evidence quality: Items 139 and 140.
3. Fix active-day run correctness: Items 152 and 153.
4. Advance model-learning work that does not need new external state: Item
   147's direct blocked-market repair, Item 138, and targeted Item 32
   market-gap repair.
5. Treat Items 35, 48, 67, 134-137, 144, 146, and 156 as evidence gates; do not mark
   them complete by code-only changes.

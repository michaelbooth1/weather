# 48. F-Family Promotion Readiness And Serving Parity [PARTIAL 2026-06-20 - MARKET, SLO, AND CLOB CONTINUITY BLOCKED]

Goal: separate the implemented family-pooled pipeline from the unresolved proof
that it is ready for broader promotion.

Source: `data/backtest/f_family_promotion_refresh_report.md` now emits explicit
promotion-readiness blockers. The current report generated
`2026-06-16T05:44:55Z` keeps readiness `OPEN`: aggregate candidate Brier trails
market Brier by `+0.0042`, seven F markets remain `KEEP_SHADOW`, and no F
market is `BLOCK_CANDIDATE`. Miami's candidate-block remediation was completed
in item 82 by holding Miami on current-serving probabilities. The refreshed
promotion report ranks generated candidate gap drivers by market, cutoff hour,
band type, settlement distance, and source freshness; the latest canonical
refresh intentionally skipped the serving gauntlet and CLOB overlay, while the
Item 82 full replay preserves the CLOB-taxonomy diagnostic evidence.

Why this matters: broader F-family promotion changes serving behavior across
multiple markets. Readiness needs per-market proof, live-forward countability,
and serving parity so a strong aggregate replay does not hide market-specific
or operational regressions.

- [x] Reduce the F-family aggregate candidate-vs-market Brier gap to <= 0 on
  pinned rows, or keep the gap explicitly marked as a readiness blocker.
- [ ] Move shadow markets to `PROMOTE_CANDIDATE` only when each market beats
  current replay, clears trust/sample gates, and is not worse than market prices
  within the promotion tolerance.
- [x] Keep candidate-blocked markets at zero; if a future market blocks, keep
  the generated `BLOCK_CANDIDATE` detail and split market-specific remediation
  into its own roadmap item.
- [x] Add generated decomposition for the largest candidate-vs-market gap
  drivers by market, cutoff hour, band type, settlement distance, and CLOB
  taxonomy in the promotion refresh `Candidate Gap Drivers` table.
- [x] Feed those generated gap-driver cells into item 47's known-edge map and
  paper permission report; tracked by item 54.
- [x] Add source-freshness gap attribution once replay rows carry freshness
  state; completed in item 53.
- [ ] Keep the promotion refresh report as the acceptance artifact: readiness is
  not complete until `readiness.status` is `READY`, serving parity is
  non-blocking, and no F market has an unexplained `KEEP_SHADOW` or
  `BLOCK_CANDIDATE`.

Implementation update (2026-06-15 UTC): `src.promotion_refresh` preserves
candidate replay slices and writes a `Candidate Gap Drivers` table plus a
dedicated `Source Freshness Slice` table to
`data/backtest/f_family_promotion_refresh_report.md`. The current top generated
drivers include at-settlement rows, CLOB taxonomy `wu_lag_catchup_miss`, exact
bands, the aggregate `all_fresh` source-freshness cohort, 07:00 rows, and
market-level gaps for Seattle/NYC/Miami. The source-freshness slice also
surfaces failed/stale groups including `failed:wu_history`,
`failed:wu_history;stale:metar`, and `stale:metar`.

Permission-cell update (2026-06-15 UTC): item 54 completed the consumption path
from generated source-freshness gap rows into `mm_known_edge_map.json`,
`mm_known_edge_map.md`, quote-intent permission records, and market-making run
preflight diagnostics. Item 48 remains open for the underlying promotion
readiness blockers: aggregate candidate-vs-market Brier, per-market shadow
actions, and unexplained `KEEP_SHADOW` / `BLOCK_CANDIDATE` cells.

Miami block update (2026-06-16 UTC): item 82 cleared the Miami
`BLOCK_CANDIDATE` cell with an explicit current-serving fallback. The canonical
promotion refresh generated `2026-06-16T05:44:55Z` now reports 4 promote, 7
shadow, and 0 blocked F markets. Miami remains `KEEP_SHADOW` with candidate
Brier equal to current Brier (`0.025046`, delta `+0.000000`) and still trails
market Brier (`0.023776`). Item 48 remains open for readiness because the
aggregate candidate still trails market by `+0.0042` and seven F markets remain
shadow.

Readiness-detail update (2026-06-16 UTC): `src.promotion_refresh` now carries
generated `shadow_market_details` / `blocked_market_details` in
`readiness`, and the Markdown report renders `Shadow/Block Explanation Detail`
directly under `Promotion Readiness Blockers`. The refreshed artifact generated
`2026-06-16T08:32:56Z` still reports 4 promote, 7 shadow, and 0 blocked F
markets, with aggregate candidate-vs-market Brier still blocked at `+0.0042`.
The seven shadow markets now have explicit generated blockers in the readiness
section:

- Austin, Chicago, NYC, and Seattle: not proven better than market on pinned
  rows.
- Dallas and Miami: not proven better than current replay.
- San Francisco: not proven better than current replay and not proven better
  than market on pinned rows.

Item 48 remains open for empirical readiness: the candidate must either clear
the aggregate market-price gap and move shadow markets through the gates, or
continue to report those blockers without serving promotion.

No-market lane selection update (2026-06-16 UTC): item 86 selected
`item50_pooled_forecast_v3_candidate` as the canonical no-market shadow lane
from `data/backtest/item86_no_market_bakeoff_multi_variant_shadow_report.md`.
The report is clean (`OK`, zero warnings/errors) and compares item 50, item 70,
item 71, item 73 policy bridge, item 82 Miami fallback, and the control over the
same 67,430 unique observations. Item 50 is best among active no-market
variants versus current replay (`-0.0016` daily-first Brier delta), but it still
trails market by `+0.0041`, so this is a shadow-lane decision rather than a
promotion approval. Item 48 remains open until the selected lane clears the
aggregate market-price gap and per-market shadow blockers.

Acceptance: the F-family promotion report has no readiness blockers, every
promoted market has pinned market-or-better evidence, and any remaining shadow
market has a concrete, generated blocker rather than ambiguous roadmap text.

## 2026-06-18 audit disposition

The Python audit found the promotion-readiness machinery, generated blocker
details, source-freshness attribution, shadow-lane selection, and report
acceptance artifact already implemented. The remaining unchecked boxes are not
missing code paths: they require the candidate to clear the generated readiness
gates and move shadow markets to `PROMOTE_CANDIDATE` only after pinned
market-or-better evidence exists. Until the replay artifact reports
`readiness.status` as `READY`, this item correctly remains an empirical
promotion blocker.

## 2026-06-18 source-family preflight refresh

Item 32's all-market reanalysis sidecar refresh removed
`reanalysis_synoptic` from the source-family promotion-preflight blocker set.
The reconstructed replay-input fallback in the source-status backfill repaired
six older Toronto folders, the forecast-payload backfill rebuilt manifests for
105 legacy folders, and narrow settled-source ablations supplied observation,
marine, and ECCC-family evidence.

The artifact-aware refresh generated `2026-06-18T17:24:54Z` now loads the
active candidate replay artifact before deciding whether a source family can
block promotion. `data/backtest/source_family_inventory.json` reports
`PASS`: 0 active model-input families are blocked. The active model contract has
99 trained features, with active source-family usage from
`settlement_observation`, `forecast_baseline`, `open_meteo_expanded`, and the
`clob_microstructure` overlay. `nws_grid`, `multi_model_guidance`,
`mrms_precip`, `marine_context`, and `eccc_gridded` still have lineage/parity
holds, but they are not active inputs in the current pooled candidate artifact
and remain diagnostic/live-only until backfilled or retrained.

Item 48 remains blocked because promotion readiness still fails daily-first
validation, candidate-vs-market tolerance, the current live-forward collection
SLO, settled-day/collection freshness, and hourly performance gates. The
tape-backup capacity gate was later cleared locally on 2026-06-19:
`data/backtest/tape_backup_status.json` is `OK` and fleet observability reports
tape backup as `OK`. Durable off-workstation backup-root configuration remains
tracked in Item 146.

## 2026-06-18 current promotion-refresh blocker state

The current canonical refresh,
`data/backtest/f_family_promotion_refresh_report.md`, was generated at
`2026-06-18T20:45:00Z`. It remains `OPEN` and `DO_NOT_CUT_OVER`: aggregate
candidate Brier is `0.0421` versus market Brier `0.0379`, so the candidate
still trails market by `+0.0042` even though it beats current replay by
`-0.0015`. Daily-first blocked validation remains `BLOCK` because the
candidate is not within market tolerance.

Current market actions are explicit and generated:

- `PROMOTE_CANDIDATE`: Atlanta, Denver, Houston, and Los Angeles.
- `KEEP_SHADOW`: Dallas and Miami, both not proven better than current replay.
- `BLOCK_CANDIDATE`: Austin, Chicago, NYC, San Francisco, and Seattle, all
  blocked by daily-first market-tolerance validation.

The regenerated source-family inventory at `2026-06-18T20:26:14Z` still reports
`PASS` with 0 active model-input blockers. That means Item 48's remaining
blockers are empirical promotion quality and operations gates, not
source-family lineage/parity.

2026-06-19 check: after the Item 32 rich 2024/2025 refresh, the canonical
inventory was regenerated again with `data\backtest\pooled_candidate_replay_latest.json`
and still reports `PASS` with 0 active model-input blockers. The separate Item
32 experimental inventory saved at
`data\backtest\item32_reanalysis_rich_2024_2025_source_family_inventory.json`
also reports `PASS` after active model usage was tightened to count only
imputer-retained artifact features. Source-family lineage/parity is therefore
not the current Item 48 blocker; empirical replay quality, live-forward SLO,
settled-day/collection freshness, hourly performance, and external backup-root
durability still are.

Follow-up implementation wired those P0 gates directly into
`weather.reporting.promotion_refresh`: the report now reads
`source_family_inventory.json` and `fleet_observability.json`, renders an
`Operational Promotion Gates` table, and keeps readiness open when the
live-forward SLO or tape-backup SLA is not green. The generated readiness
blockers in that pass were:

- `candidate_market_skill`: aggregate candidate trails market by `+0.0042`.
- `blocked_validation`: daily-first candidate is outside market tolerance.
- `per_market_shadow`: Dallas and Miami remain shadow.
- `per_market_block`: Austin, Chicago, NYC, San Francisco, and Seattle remain
  blocked.
- `live_forward_slo`: fleet observability reports `BLOCK`.
- `tape_backup_sla`: at that time, tape backup reported
  `INSUFFICIENT_BACKUP_CAPACITY` (`106794554808` bytes short). This was later
  cleared locally by the 2026-06-19 restore-pass evidence; external backup-root
  durability remains Item 146.
- `hourly_performance_gate`: early-hour model Brier trails market by `0.0159`,
  above the `0.0030` gate.

Follow-up hourly remediation work added a no-market `forecast_centering` probe
to `weather.reporting.hourly_model_performance`. The regenerated hourly audit
still blocks promotion, but the probe improves early-morning Brier by `-0.0032`
and log-loss by `-0.1012` over 5,159 rows without using market prices. This
does not clear Item 48 yet because it is only replay-probe evidence; the next
Item 48 unblock step is to promote that transform into a candidate lane and
rerun daily-first promotion gates with midday/late guardrails.

The promoted Item 147 candidate now has that evidence. The generated artifact
`data/backtest/item147_forecast_centering_candidate.pkl` enables no-market
forecast centering on the Item 50 F-family band candidate, and
`data/backtest/item147_forecast_centering_replay_report.md` replays it against
the full promotion corpus. It remains `BLOCK / DO_NOT_CUT_OVER`: aggregate
candidate Brier improves only from the active baseline `0.042100` to `0.042035`,
daily-first Brier improves from `0.042049` to `0.041982`, and the candidate
still trails market by `+0.004166` aggregate / `+0.004152` daily-first.

This is useful blocker evidence rather than promotion evidence. Cutoff hour `7`
improves from Brier `0.064117` to `0.063753`, nearly reaching market tolerance,
but hour `8` regresses and Austin worsens from market gap `+0.004058` to
`+0.005576`. Item 48's next model unblock is therefore a narrower market/cutoff
residual repair that preserves the hour-7 lift without broad hour-8 or Austin
regression; the same live-forward SLO and Item 146 external backup-root
durability work still remain.

The narrowed follow-up artifact
`data/backtest/item147_forecast_centering_hour7_no_austin_candidate.pkl`
preserves the hour-7 centering only and falls Austin back to current-serving
probabilities. Its full replay,
`data/backtest/item147_forecast_centering_hour7_no_austin_replay_report.md`,
still reports `BLOCK / DO_NOT_CUT_OVER`, but improves the evidence boundary:
aggregate candidate Brier is `0.042010` versus current `0.043554` and market
`0.037869`; daily-first candidate Brier is `0.041957`, still `+0.004128`
worse than market. Hour `7` now clears market tolerance with gap `+0.002572`,
and Austin no longer regresses versus current, but Austin still trails market
by `+0.005212` and hours `8`/`9` remain above market tolerance. The next Item
48 model unblock is a targeted no-market hour-8/hour-9 and Austin market-gap
repair; operations blockers from live-forward SLO and Item 146 external
backup-root durability still remain.

The next combined artifact,
`data/backtest/item147_hour7_no_austin_exact_winner_candidate.pkl`, adds Item
70's exact-winner catch-up table to that narrowed hour-7/no-Austin lane. Its
full replay,
`data/backtest/item147_hour7_no_austin_exact_winner_replay_report.md`, is the
strongest Item 48 model-repair evidence so far, but still reports
`BLOCK / DO_NOT_CUT_OVER`: aggregate candidate Brier is `0.041716` versus
current `0.043554` and market `0.037869`; daily-first candidate Brier is
`0.041661`, still `+0.003831` worse than market and above the `0.0030`
tolerance.

This combined replay reduces the blocked market set from Austin, Chicago, NYC,
San Francisco, and Seattle to Austin, NYC, San Francisco, and Seattle. Chicago
now clears market tolerance (`0.038289` versus market `0.036314`), while Dallas
and Miami remain shadow because they are not proven better than current. The
remaining model blockers are Austin's current fallback still trailing market
by `+0.005212`, NYC's market gap `+0.016578`, San Francisco's gap `+0.005168`,
Seattle's gap `+0.013863`, and hour `8`/`9` gaps of `+0.004466` and
`+0.003250`. Exact-winner catch-up is also over-broad: it improves
settlement-distance-0 to `0.3277` versus current `0.3486`, but regresses the
one-above guardrail to `0.0765` versus current `0.0714`.

Item 48 therefore remains an empirical promotion blocker. The next model
unblock is not another broad centering/bridge blend; it needs market-specific
Austin/NYC/San Francisco/Seattle repair, hour-8/hour-9 tolerance, and an
exact-winner constraint that preserves one-above safety. The live-forward SLO
and Item 146 external backup-root durability gates still remain separate
operational blockers.

## 2026-06-19 Item 32 rich+pressure replay check

Item 32's pressure-level backfill now gives the reanalysis/synoptic lane real
2024/2025 training-window coverage for 850 hPa temperature, 500 hPa height, and
1000-500 hPa thickness. The rich+pressure artifact
`data/backtest/item32_reanalysis_rich_pressure_2024_2025_lane_candidate.pkl`
retains those pressure fields in every hourly model, and the matching
source-family inventory
`data/backtest/item32_reanalysis_rich_pressure_2024_2025_source_family_inventory.json`
reports `PASS` with zero active family blockers and 40 active
`reanalysis_synoptic` features.

That clears the source-family/pressure-population question for Item 48, but not
the promotion-readiness gate. The matching pinned replay remains
`BLOCK / PARTIAL_PASS / DO_NOT_CUT_OVER`: aggregate candidate Brier is
`0.042960` versus market `0.037869` (`+0.005092`), and daily-first candidate
Brier is `0.042899` versus market `0.037830` (`+0.005070`). Per-market actions
are unchanged from the rich-only replay: Atlanta, Austin, Houston, and Los
Angeles are cutover-ready; Dallas, Denver, and Miami remain shadow; Chicago,
NYC, San Francisco, and Seattle remain blocked.

The current Item 48 unblock remains model-quality and operations work:
market-specific repair for NYC/San Francisco/Seattle/Chicago plus the broader
hour-8/hour-9 and Austin issues from Item 147, then live-forward SLO and Item
146 external backup-root durability before readiness can become `READY`.

## 2026-06-19 Item 35 replay-blend diagnostic

The Item 35 all-market direct-band diagnostic replay shows a better model
boundary, but it is not promotion evidence for Item 48 because the
current-blend alphas were selected on the pinned replay rows. The diagnostic
artifact `data/backtest/item35_direct_band_all_market_replay_blend_candidate.pkl`
reports `PARTIAL_PASS / PER_MARKET_ONLY`: aggregate candidate Brier is
`0.040297` versus current `0.042739`, and daily-first candidate Brier is within
market tolerance at `+0.002926` versus market. Austin and Toronto move to PASS
in that diagnostic, but Chicago, NYC, San Francisco, and Seattle remain
blocked, while Dallas and Miami remain shadow.

This narrows the model-quality path for Item 48 but does not change readiness:
the next promotion-safe candidate needs a predeclared or out-of-sample blend
policy and must still clear the live-forward SLO and Item 146 external
backup-root durability gate.

## 2026-06-19 all-market diagnostic promotion refresh

The Item 35 replay-blend diagnostic was also run through an all-market
promotion refresh as a non-serving boundary check:
`data/backtest/item35_replay_blend_promotion_refresh_report.md`. This remains
diagnostic rather than promotion evidence because the current-blend alphas were
selected on the pinned replay rows.

The refresh reports readiness `OPEN`, candidate verdict `PARTIAL_PASS`,
market-only verdict `PARTIAL_PASS`, and cutover decision `PER_MARKET_ONLY`.
It would promote Atlanta, Austin, Denver, Houston, Los Angeles, and Toronto;
keep Dallas and Miami in shadow; and block Chicago, NYC, San Francisco, and
Seattle. Aggregate candidate Brier is `0.040297` versus current `0.042739`
and market `0.037323`; the daily-first market gap is within tolerance, but
broad readiness still fails because the aggregate candidate trails market by
`+0.0030`.

Operational gates in that generated pass still blocked readiness independently
of model quality: live-forward SLO was `BLOCK`, tape backup SLA was
`INSUFFICIENT_BACKUP_CAPACITY` with `106794554808` bytes short, and the hourly
performance gate was `BLOCK` because early-hour model Brier trailed market by
`0.0159`. The tape backup SLA was later cleared locally by the 2026-06-19
restore pass, but Item 48 still stays `PARTIAL`: the strongest current
diagnostic boundary is clearer, while a predeclared or out-of-sample blend plus
the live/freshness, external-backup-root, and hourly gates are still required
before readiness can become `READY`.

## 2026-06-19 time-split blend anti-overfit check

The predeclared/out-of-sample blend requirement was tested with
`weather.reporting.current_blend_validation` and the resulting artifact
`data/backtest/item35_direct_band_all_market_time_split_blend_candidate.pkl`.
The selection used earlier market-days and evaluated later market-days inside
the pinned replay export, so it is still development evidence rather than
promotion evidence.

The time-split validation blocks:
`data/backtest/item35_current_blend_time_split_validation_report.md` reports
later-date candidate Brier `0.045052` versus current `0.046663` and market
`0.039270`, with a `+0.005782` market gap. The normal full replay for the
time-split artifact also blocks:
`data/backtest/item35_direct_band_all_market_time_split_blend_report.md`
reports aggregate candidate Brier `0.040707` versus current `0.042739` and
market `0.037323`, with daily-first market gap `+0.003331`.

This keeps Item 48 blocked on model quality even before operations gates:
Atlanta and Houston pass, Dallas/Denver/Los Angeles/Miami remain shadow, and
Austin/Chicago/NYC/San Francisco/Seattle/Toronto remain blocked. The replay
selected diagnostic remains useful for direction, but the time-split check says
the next acceptable Item 48 candidate needs direct model repair, not another
alpha sweep over the same rows.

## 2026-06-19 holdout market-bias candidate

The next direct model-repair attempt is
`data/backtest/item35_direct_band_all_market_market_bias_candidate.pkl`, which
fits a market/hour/kind bias calibration on historical holdout rows instead of
selecting from replay rows. The historical holdout gate enabled 240 contexts
and improved Brier from `0.033564` to `0.032008` with no market-level
regression inside that gate.

The pinned replay still blocks Item 48:
`data/backtest/item35_direct_band_all_market_market_bias_replay_report.md`
reports `BLOCK / PARTIAL_PASS / DO_NOT_CUT_OVER`. Aggregate candidate Brier is
`0.041721` versus current `0.042739` and market `0.037323`, and daily-first
candidate Brier is `0.040986` versus market `0.036667` (`+0.004319`). The
positive change is narrower but real: Austin and Los Angeles now pass, joining
Atlanta and Houston. The remaining model blockers are Chicago, NYC, San
Francisco, Seattle, and Toronto; Dallas, Denver, and Miami remain shadow.

This does not advance promotion readiness because Toronto regresses current
(`0.038703` candidate versus `0.036925` current), degraded-source rows regress
current serving, and the operational live-forward SLO, external backup-root
durability, and early-hour performance gates still block. The next model attempt should
preserve the Austin/Los Angeles lift while adding source-state/Toronto
guardrails and repairing Chicago/NYC/San Francisco/Seattle.

## 2026-06-19 source-freshness guardrail candidate

The source-freshness guardrail variant
`data/backtest/item35_direct_band_all_market_market_bias_source_guard_candidate.pkl`
keeps the holdout-trained market-bias calibration but blends every non-`all_fresh`
row back to current serving. Its replay,
`data/backtest/item35_direct_band_all_market_market_bias_source_guard_replay_report.md`,
still blocks promotion but separates one blocker: source-state ablation returns
to `READY`, with degraded-source rows exactly current-safe.

The model-quality gate remains blocked. Aggregate candidate Brier is
`0.041675` versus current `0.042739` and market `0.037323`; daily-first market
gap is `+0.004275`. Atlanta, Austin, Houston, and Los Angeles pass; Dallas,
Denver, and Miami remain shadow; Chicago, NYC, San Francisco, Seattle, and
Toronto remain blocked. This means Item 48's next model step is no longer
generic source-state safety; it is targeted market skill for Toronto and the
four remaining US blockers, plus the unchanged operational gates.

## 2026-06-19 Toronto-alpha diagnostic boundary

The source-guarded Toronto-alpha probe
`data/backtest/item35_direct_band_all_market_source_guard_toronto_alpha_candidate.pkl`
adds Toronto alpha `0.30` on top of the source-freshness guardrail. This is
diagnostic only because the alpha came from replay-row evidence, not a
promotion-safe holdout policy.

Its replay
`data/backtest/item35_direct_band_all_market_source_guard_toronto_alpha_replay_report.md`
still blocks broad promotion, but narrows the model blocker set: source-state
ablation remains `READY`, Toronto moves to PASS (`0.035937` candidate versus
`0.036925` current and `0.033427` market), and cutover-ready markets are
Atlanta, Austin, Houston, Los Angeles, and Toronto. Dallas, Denver, and Miami
remain shadow; Chicago, NYC, San Francisco, and Seattle remain blocked.

Aggregate candidate Brier is `0.041388` versus current `0.042739` and market
`0.037323`; daily-first market gap remains `+0.003997`, still above the
`0.0030` tolerance. Item 48 therefore remains blocked on empirical model
quality and operations gates. The next promotion-safe candidate needs a
predeclared or holdout-selected Toronto policy plus direct Chicago/NYC/San
Francisco/Seattle repair.

## 2026-06-19 source-guard time-split rejection

The promotion-safe follow-up tested the source-guard row export
`data/backtest/item35_market_bias_source_guard_variant_rows.csv` with
`data/backtest/item35_source_guard_time_split_validation_report.md`. That row
CSV was later deleted by `data/backtest/backtest_artifact_cleanup_manifest_4.json`
as rebuildable after retaining the paired replay export JSON/report and the
time-split report. The validation selects alphas on earlier market-days and
evaluates later market-days, so it is still development evidence rather than
promotion evidence, but it is a stricter anti-overfit check than the replay-row
alpha sweep.

The check remains `BLOCK`: selected eval-row candidate Brier is `0.045334`
versus current `0.046663` and market `0.039270`, and daily-first market gap is
`+0.006072`. The key Item 48 impact is Toronto: the split selects Toronto
alpha `0.00`, not the diagnostic `0.30`, and later Toronto rows remain blocked
against market (`0.051904` candidate/current versus `0.043225` market).

Therefore the Toronto-alpha probe stays diagnostic only and should not be used
as a promotion policy. Item 48 remains blocked on model quality, live-forward
SLO, external backup-root durability, and hourly performance. The next candidate needs a
holdout-selected Toronto repair plus direct Austin/Chicago/Houston/Los
Angeles/NYC/San Francisco/Seattle market-gap fixes.

A follow-up Item 35 source-guard blocker-market replay pass now gives the next
repair split for the all-market/direct-band lane. Chicago, NYC, San Francisco,
Seattle, and Toronto were replayed individually against
`data/backtest/item35_direct_band_all_market_market_bias_source_guard_candidate.pkl`;
all five stayed `BLOCK / DO_NOT_CUT_OVER`. Chicago improves current but trails
market by `+0.003315`, NYC improves current but trails market by `+0.019104`,
San Francisco is full current fallback and trails market by `+0.005168`,
Seattle barely improves current and trails market by `+0.014495`, and Toronto
regresses current while trailing market by `+0.004847`. The repair diagnostic
`data/backtest/item35_source_guard_blocker_repair_diagnostics_report.md`
classifies NYC/Seattle as winner-underpricing cases, San Francisco as a
current-fallback market gap, and Chicago/Toronto as broader market-gap cases.
This reinforces the same Item 48 posture: do not spend the next pass on alpha
tuning; build direct winner/market-signal repairs and newly sourced or newly
trained non-current skill.

A bounded all-market exact-winner source-guard diagnostic now gives a first
direct model-repair signal for that posture. The training path can now produce
an Item 35 all-market exact-winner artifact while preserving the source-state
guardrail. The recent-40 artifact
`data/backtest/item35_all_market_exact_winner_source_guard_recent40_candidate.pkl`
improves the blocker-market replays versus the prior source-guard candidate:
NYC Brier moves `0.055162 -> 0.052357`, Seattle `0.038628 -> 0.037886`, and
Toronto `0.038274 -> 0.037871`. It still blocks because NYC trails market by
`+0.016299`, Seattle by `+0.013753`, and Toronto still regresses current while
trailing market by `+0.004445`. This is useful directionally, but not an Item
48 readiness unblock. A full no-cap training/replay run needs a longer window,
and the candidate family still needs stronger winner repair plus a Toronto
current-regression guard.

The follow-up split-safe winner-boost policy search confirms that a shallow EQ
multiplier is not enough. `data/backtest/item35_exact_source_guard_recent40_winner_boost_validation_report.md`
selects no boost for NYC and Toronto (`factor 1.00`) and an aggressive
`all_eq` factor `8.00` for Seattle, but all three later-date holdouts still
block: NYC `+0.027894` versus market, Seattle `+0.014745`, and Toronto
`+0.003864`. That keeps the next Item 48 model work in the same lane:
new market/source signal and richer winner modeling, not another generic
winner-multiplier sweep.

The richer contextual version of that idea is also rejected. The new
`weather.reporting.contextual_winner_validation` report,
`data/backtest/item35_exact_source_guard_recent40_contextual_winner_validation_report.md`,
fits exact-row factors on earlier market-days using only inference-available
forecast-pressure, disagreement, source-count, source-freshness, and cutoff
contexts. It still blocks: NYC improves only to a `+0.0269` market gap,
Seattle overfits and worsens to `+0.0218`, and Toronto worsens to `+0.0046`.
Daily-first holdout worsens versus the baseline exact-source-guard rows
(`+0.0145` versus `+0.0129`). This rules out contextual exact-row postprocess
tuning as the next Item 48 unblock; the remaining promotion work needs direct
market/source features or a changed model architecture for NYC/Seattle and
non-current skill for the fallback markets.

The same contextual exact-row check was run on the Item 147 blocked-market row
exports for Austin, Los Angeles, NYC, San Francisco, and Seattle:
`data/backtest/item147_blocked_markets_contextual_winner_validation_report.md`.
It also blocks. Daily-first holdout worsens from a `+0.0106` market gap to
`+0.0127`. NYC improves slightly (`+0.0132` versus market) but remains far
outside tolerance, while Seattle worsens to `+0.0215` and San Francisco
worsens to `+0.0132`. Austin and Los Angeles remain blocked at `+0.0076` and
`+0.0080`. This confirms the Item 147/48 repair should not be another
context-keyed exact-row calibration pass.

The market-informed anchor boundary was tested next with
`weather.reporting.market_anchor_validation`. CLOB-only validation
(`data/backtest/item147_blocked_markets_clob_anchor_validation_report.md`)
still blocks under `market_anchor_time_split_validation_v0.2` because
earlier-date selection chooses no CLOB anchor for all five blocked markets and
the explicit train-side CLOB anchor gate is `BLOCK`: coverage `0.0000` versus
the `0.0500` minimum, with `0` train anchor rows. Eval-side coverage is
`0.2413`; on those eval rows, CLOB Brier is `0.0538` versus candidate
`0.0780`. The eval-only oracle would shrink daily-first market gap from
`+0.0106` to `+0.0044`, with Austin beating market and San Francisco inside
tolerance, but NYC and Seattle still outside tolerance. This points to CLOB
coverage/stability work, not immediate promotion.

The folder-level root-cause report
`data/backtest/item147_blocked_markets_clob_coverage_audit_report.md` confirms
why the CLOB midpoint cannot be trusted yet: every June 7/8 train folder for
Austin, Los Angeles, NYC, San Francisco, and Seattle is missing the raw
`order_books` tape and `clob_tokens` map. Those folders have generated
`clob_features_long.csv` shells, but token coverage, feature-available
coverage, and midpoint coverage are all `0.0000`. June 12/13 has raw CLOB
tapes, but June 12 remains partial or one-sided; June 13 is the first broadly
usable midpoint day. This makes the CLOB path an operations/data-continuity
unblock before it is a promotion candidate.

Allowing full `market_yes` anchoring
(`data/backtest/item147_blocked_markets_market_anchor_validation_report.md`)
also remains `BLOCK`, though it shrinks daily-first market gap to `+0.0035`.
Austin, San Francisco, and Seattle pass under the selected market-price anchor,
but Los Angeles (`+0.0046`) and NYC (`+0.0141`) still block. Because
`market_yes` is the benchmark price itself, this is a serving-safety/risk
boundary rather than model edge; because the report also evaluates
`clob_midpoint`, the v0.2 train-side CLOB coverage gate remains `BLOCK`. Item
48 therefore still needs direct model/source repair plus CLOB stability
evidence before another staged promotion refresh is worth treating as
readiness evidence.

Follow-up readiness guard: `promotion_refresh` now also blocks readiness when
the candidate replay lane itself is marked `uses_market_features=true`. This
does not change scoring or shadow-reporting for CLOB/market-informed lanes, but
it prevents a market-informed candidate from satisfying the weather-only core
promotion-readiness artifact. Market-informed evidence can still support
quote/risk gates and serving-safety diagnostics; Item 48 promotion readiness
still requires no-market model evidence plus operational gates.

## 2026-06-19 Item 147 time-split alpha replay

The F-family Item 147 line now has a stronger no-market candidate:
`data/backtest/item147_time_split_alpha_candidate.pkl`. It starts from the
hour-7/no-Austin exact-winner artifact and applies alphas selected on earlier
market-days by
`data/backtest/item147_hour7_no_austin_exact_winner_time_split_validation_report.md`.
The validation itself still blocks on later-date rows, so this remains
diagnostic/development evidence rather than promotion evidence.

The official pinned replay is still useful because it moves the aggregate gate:
`data/backtest/item147_time_split_alpha_replay_report.md` reports
`PARTIAL_PASS / PER_MARKET_ONLY`; blocked validation is `PASS`; aggregate
candidate Brier is `0.040315` versus current `0.043554` and market `0.037869`;
daily-first candidate Brier is `0.040257` versus market `0.037830`, gap
`+0.002427`, now inside the `0.0030` tolerance.

Item 48 remains blocked because per-market promotion is still not clean and
operations gates are unchanged. Cutover-ready markets are Atlanta, Chicago,
Denver, and Houston; Dallas and Miami remain shadow; Austin, Los Angeles, NYC,
San Francisco, and Seattle remain blocked. The next model repair is
market-specific rather than aggregate: Austin and San Francisco need better
than current fallback, Los Angeles is just outside tolerance, NYC needs a
small exact-winner/alpha improvement, and Seattle remains the largest
underpricing gap. Live-forward SLO, Item 146 external backup-root durability,
settled-day/collection freshness, and hourly performance gates still have to
clear before readiness can become `READY`.

## 2026-06-19 guarded promotion-refresh retry

The local generated-artifact disk blocker from Item 154 was cleared for this
retry:
`data/backtest/backtest_artifact_retention_report.md` is `PASS` with the 1 GB
reserve met after cleanup-manifest deletion of rebuildable generated artifacts.

I retried a full guarded promotion refresh for
`data/backtest/item147_time_split_alpha_candidate.pkl` with isolated Item 147
output paths. The run wrote the promotion corpus and trust artifacts:
`data/backtest/item147_time_split_alpha_promotion_corpus.json` and
`data/backtest/item147_time_split_alpha_promotion_trust.json`, but it exceeded
the 10-minute execution window before a candidate replay, final refresh JSON,
or Markdown report was produced. The long-running Python process was stopped
explicitly after verifying its command line.

That staged workflow is now implemented in `promotion_refresh` via
`--precomputed-candidate-json` with a strict corpus-hash match. Re-running the
refresh against the matching `complete,manual_override` corpus and the existing
`data/backtest/item147_time_split_alpha_replay.json` candidate evidence
completed with serving gauntlet enabled:
`data/backtest/item147_time_split_alpha_staged_serving_promotion_refresh_report.md`.
The report keeps readiness `OPEN`, but the blocker is now explicit rather than
a missing refresh artifact. Decisions are 4 promote, 2 shadow, and 5 blocked:
Atlanta/Chicago/Denver/Houston are `PROMOTE_CANDIDATE`; Dallas/Miami remain
`KEEP_SHADOW`; Austin/Los Angeles/NYC/San Francisco/Seattle are
`BLOCK_CANDIDATE`. Serving gauntlet status is `PASS_WITH_SHADOWS`.

Readiness blockers are now: aggregate candidate still trails market by
`+0.0024` despite daily-first tolerance passing, Dallas/Miami shadow cells,
the five blocked markets, live-forward SLO `BLOCK`, Item 146 external
backup-root durability, and the hourly performance gate. Disk headroom was no longer the
local P0 for this retry; the later raw CLOB audit section below supersedes
that with the current local retention state.

The refresh now emits market-skill diagnostics for every non-promoted F market,
not just NYC/Seattle. Generated next-experiment artifacts exist for Seattle,
Austin, San Francisco, NYC, Los Angeles, Miami, and Dallas under
`data/backtest/experiments/*_residual_calibration_daily_first.json`. The
largest remaining market gaps are Seattle `+0.0136`, Austin `+0.0052`, San
Francisco `+0.0052`, NYC `+0.0035`, and Los Angeles `+0.0033`; Miami is a
shadow cell with `+0.0013` versus market and Dallas is market-better but still
shadow because it is not better than current replay.

Follow-up market-scoped residual checks turned the five blocked-market
manifests into scored evidence. One-market promotion corpora and row exports
were generated for Austin, Los Angeles, NYC, San Francisco, and Seattle, then
validated with the earlier-date/later-date current-blend harness:
`data/backtest/item147_austin_residual_calibration_time_split_report.md`,
`data/backtest/item147_los-angeles_residual_calibration_time_split_report.md`,
`data/backtest/item147_nyc_residual_calibration_time_split_report.md`,
`data/backtest/item147_san-francisco_residual_calibration_time_split_report.md`,
and
`data/backtest/item147_seattle_residual_calibration_time_split_report.md`.
All five checks block. Later-date market gaps are Austin `+0.008258`, Los
Angeles `+0.008074`, NYC `+0.014129`, San Francisco `+0.005479`, and Seattle
`+0.016751`. This means residual alpha calibration is not the next readiness
unblock. Austin/Los Angeles/San Francisco need non-current fallback skill, while
NYC/Seattle need direct winner/market-signal repair.

The follow-up blocked-market repair diagnostic is now repeatable in
`weather.reporting.blocked_market_repair_diagnostics` and generated
`data/backtest/item147_blocked_market_repair_diagnostics_report.md` over 30,569
blocked-market rows. It classifies Austin, Los Angeles, and San Francisco as
`current_fallback_trails_market` with 100% current-fallback share, Seattle as
`winner_underpricing_vs_market` with a `-0.0978` winner-probability gap versus
market, and NYC as a smaller market-gap repair. The top repair slices are:
Seattle exact/settlement-distance-0/all-fresh early rows, San Francisco midday
and warm-side rows, Austin near-forecast settlement-distance-0 rows, Los
Angeles low-disagreement early settlement-distance-0 rows, and NYC
near-forecast/cool-side rows. That is the concrete model-quality work before
another staged promotion refresh is worth running.

The current-fallback markets were then probed with a raw-alpha diagnostic
artifact, `data/backtest/item147_fallback_markets_raw_alpha_candidate.pkl`,
that changes Austin, Los Angeles, and San Francisco from current fallback to
raw-candidate alpha `1.00`. Market-scoped replays reject the probe:
Austin worsens from candidate Brier `0.041416` to `0.045258`, Los Angeles
worsens from `0.032469` to `0.034064`, and San Francisco worsens from
`0.046408` to `0.052121`. All three remain `BLOCK / DO_NOT_CUT_OVER`.

The stricter time-split alpha checks also block:
`data/backtest/item147_raw_alpha_austin_time_split_report.md` selects alpha
`0.15` but still trails market by `+0.008293`,
`data/backtest/item147_raw_alpha_los-angeles_time_split_report.md` selects
alpha `0.00` and trails market by `+0.008074`, and
`data/backtest/item147_raw_alpha_san-francisco_time_split_report.md` selects
alpha `0.80` but regresses current by `+0.009885` while trailing market by
`+0.015364`. This rules out hidden raw-candidate skill as an Item 48 unblock.
Austin/Los Angeles/San Francisco need newly trained or newly sourced
non-current skill; Seattle and NYC still need direct winner/market-signal
repair.

Verification:
`python -m pytest -p no:cacheprovider tests\calibration\test_promotion_refresh.py tests\calibration\test_pooled_candidate_replay.py tests\reporting\test_multi_variant_shadow.py tests\reporting\test_backtest_artifact_retention.py tests\backtesting\test_replay.py -q`
passed with `109 passed` before the raw-alpha diagnostic; the focused
raw-alpha/reporting follow-up is covered by
`python -m pytest tests\reporting\test_blocked_market_repair_diagnostics.py tests\reporting\test_current_blend_validation.py -q`.

## 2026-06-19 Item 35 bounded exact/source-guard replay check

The Item 35 all-market exact-winner/source-guard lane was tested at larger
bounded training windows to see whether it could become the Item 48 model
repair. It did not.

The recent-120 artifact
`data/backtest/item35_all_market_exact_winner_source_guard_recent120_candidate.pkl`
is the better of the two new runs, but still reports
`BLOCK / DO_NOT_CUT_OVER` on the pinned promotion corpus: aggregate candidate
Brier `0.041011` versus current `0.042739` and market `0.037323`; daily-first
candidate `0.040278` versus market `0.036667`, gap `+0.003611`, still above
the `0.0030` tolerance.

The wider recent-365 artifact
`data/backtest/item35_all_market_exact_winner_source_guard_recent365_candidate.pkl`
trained on 61,311 source rows and also blocked. It was worse than recent-120:
daily-first market gap `+0.003946`, aggregate market gap `+0.004024`, NYC
gap `+0.0166`, Seattle `+0.0137`, San Francisco `+0.0052`, Austin `+0.0051`,
and Toronto `+0.0046` while regressing current by `+0.0011`.

This reinforces the current Item 48 path. The strongest aggregate lane remains
the Item 147 time-split alpha candidate, not a wider all-market exact/source
guard. The remaining unblock is market-specific: Seattle and NYC need direct
winner repair; Austin, Los Angeles, and San Francisco need newly trained or
newly sourced non-current fallback skill; Toronto needs a current-regression
guard before any all-market path can claim Item 35 lift. The CLOB coverage
audit also remains relevant because market-informed anchoring has no
train-side midpoint evidence while June 7/8 raw book/token tapes are missing.

Local generated-artifact pressure was cleaned after the replay pass. The
retention tool first deleted `active_variant_shadow_long.csv`, then a manual
cleanup removed 17 older rebuildable row-level shadow CSV exports while
retaining their paired JSON/Markdown reports and model artifacts. The follow-up
report
`data/backtest/backtest_artifact_retention_after_item35_recent365_manual_cleanup_report.md`
is `PASS` under the local 500 MB reserve. This is local headroom only; Item
146 still owns external backup-root durability.

That local headroom was temporarily lost after the raw CLOB audit and ongoing
capture loops:
`data/backtest/backtest_artifact_retention_after_clob_raw_gate_report.md` was
`BLOCK` with `371.6 MB` free, a `105.3 MB` shortfall against the 500 MB reserve,
and zero automatic cleanup candidates. The retention classifier now recognizes
source-state ablation CSVs as rebuildable row exports when a retained replay
report references them. Applying
`data/backtest/backtest_artifact_cleanup_manifest_after_source_ablation_cleanup.json`
and `data/backtest/backtest_artifact_cleanup_manifest_after_row_export_cleanup.json`
deleted 19 rebuildable row/shadow exports totaling `156.9 MB` while retaining
paired reports/manifests. The final no-cleanup retention report
`data/backtest/backtest_artifact_retention_after_row_export_cleanup_final_report.md`
is `PASS`: free space is `490.0 MB` and the 500 MB reserve shortfall is `0 B`.

The later Item 32 no-pressure training attempt exposed a local headroom
problem, but that specific blocker has been cleared. The tape-backup cleanup
manifest `data/backtest/tape_backup_unmanifested_cleanup_applied.json` removed
67 unmanifested same-disk backup partials totaling `17264418975` bytes, and
all settled full-depth CLOB books are now gzip-tiered. The follow-up retention report
`data/backtest/backtest_artifact_retention_after_backup_cleanup_and_tiering_report.md`
is `PASS`, and `data/backtest/tape_backup_status.json` is now `OK` with
restore-drill SLA `OK`, zero missing critical files, and all 6 required CLOB
artifact classes restored. Fleet observability also reports tape backup as
`OK`. Durable external backup storage remains Item 146's completion caveat
because `data\tape_backups` is still a same-workstation backup root, and the
duplicate dashboard processes should still be cleaned up separately, but local
backtest headroom and tape-backup capacity are no longer the immediate blockers
for another bounded replay.

The Item 32 no-pressure recent-120 replay adds another negative model signal
for Item 48's broad readiness path: it improves current by about `0.00077`
Brier but remains `BLOCK / DO_NOT_CUT_OVER`, with daily-first market gap
`+0.004893`. Atlanta, Houston, and Los Angeles pass; Austin, Chicago, NYC, San
Francisco, and Seattle block. That reinforces the current path: the aggregate
Item 147 lane remains stronger than another broad reanalysis-family sweep, and
readiness still needs direct blocked-market repair before a staged promotion
refresh can become `READY`.

## 2026-06-19 raw CLOB artifact gate

The F-family market-informed repair path now has an operational guard for the
missing raw-tape/token failure mode found in the blocked-market CLOB audits.
`data_layer_audit` now records raw CLOB token and book artifact presence, the
Markdown report exposes composite token/raw-book day counts, and the live-pilot
preflight fails closed when a target date has derived CLOB features/book rows
without raw token and raw book artifacts.

Fresh audit evidence:
`data\backtest\data_layer_audit_after_clob_raw_artifact_gate_report.md`
shows `177` folders with derived CLOB features, but only `96` token-artifact
days and `84` raw-book artifact days. On the `165` training-ready folders, the
counts are `84` token-artifact days and `72` raw-book artifact days. This keeps
the promotion blocker honest: future live evidence cannot satisfy the CLOB
proof path with derived shells alone, but Item 48 still needs actual historical
CLOB continuity plus direct repairs for Austin, Los Angeles, NYC, San
Francisco, and Seattle before another promotion refresh can become `READY`.
The CLOB continuity work is now tracked explicitly in Item 156; Item 48 keeps
ownership of the no-market model repair and promotion-refresh readiness gates.

Verification:
`python -m pytest tests\market\test_market_making_run.py tests\reporting\test_data_layer_audit.py -q`
passed with `42 passed`.

## 2026-06-19 backup and settled-day gate refresh

The local operational gate order changed after the tape-backup and settled-day
repairs:

- `data/backtest/tape_backup_status.json` is `OK`, restore-drill SLA is `OK`,
  and fleet observability reports tape backup as `OK`.
- `data/backtest/settled_day_freshness.json` improved from `FAIL` to `WARN`:
  all 12 June 18 markets are complete, missing labels/ledgers/tapes/replay
  status counts are `0`, and only WU daily-summary source-lag warnings remain.
- `data/backtest/daily_learning.json` remains `BLOCKED`, but the first P0 gate
  is now hourly performance: early-hour model Brier trails market by `0.0159`
  above the `0.0030` gate.
- `data/backtest/fleet_observability.json` remains `CRITICAL` because 11
  collection alerts still report afternoon-window coverage gaps. Tape backup
  is no longer among the critical alerts, and settled-day freshness is now a
  warning.

Commands run:
`python -m weather.operations.settled_day_freshness repair --target-date 2026-06-18 --snapshots-root data\snapshots --labels-csv data\backtest\market_day_labels.csv --ledger-root data\settlements`;
`python -m weather.operations.replay_status_backfill --snapshots-root data\snapshots --as-of 2026-06-19`;
`python -m weather.operations.settled_day_freshness report --target-date 2026-06-18 --snapshots-root data\snapshots --labels-csv data\backtest\market_day_labels.csv --ledger-root data\settlements --json-out data\backtest\settled_day_freshness.json --report-out data\backtest\settled_day_freshness_report.md`;
then fleet observability and daily learning were refreshed.

## 2026-06-19 Item 147 candidate-hourly evidence

The Item 147 time-split alpha candidate now has a candidate-specific local-hour
audit, so the early-hour P0 blocker is no longer ambiguous for that candidate.
`weather.reporting.candidate_hourly_performance` consumes the regenerated
`data/backtest/item147_time_split_alpha_variant_rows.csv` export and scores
the first available row per market-day-band-local-hour.

`data/backtest/item147_time_split_alpha_hourly_candidate_performance_report.md`
reports `PASS` for the candidate early-hour gate: 44 F-family market-days,
4,356 00:00-08:00 checkpoint rows, candidate Brier `0.0511`, current Brier
`0.0555`, market Brier `0.0519`, candidate delta versus current `-0.0044`,
and candidate delta versus market `-0.0008`. Winner probability improves from
current `0.3916` to candidate `0.4369`, matching market `0.4353`.

This is useful but not sufficient for Item 48 readiness. The production
current-serving hourly gate remains `BLOCK` in `daily_learning.json`, but
`promotion_refresh` can now mitigate that blocker for a specific candidate only
when the candidate-hourly report is passed explicitly and its `variant_ids`
match the replayed candidate's `candidate_shadow_variants.variant_id`.

The refreshed staged Item 147 promotion refresh consumes
`data/backtest/item147_time_split_alpha_hourly_candidate_performance.json`.
It keeps readiness `OPEN`, but removes the hourly-performance blocker from the
readiness blocker list with `hourly_performance_mitigation.applied=true` and
`candidate_hourly_matches=true`. The report still shows both operational rows:
current-serving hourly gate `BLOCK` and candidate hourly gate `PASS`. Remaining
readiness blockers are aggregate candidate market skill, Dallas/Miami shadow
status, Austin/Los Angeles/NYC/San Francisco/Seattle per-market blocks, and
live-forward SLO. Tape backup is now `OK` in this refreshed staging evidence.

The next readiness move is still direct blocked-market repair followed by a
staged promotion refresh; the candidate-hourly report proves that the current
aggregate baseline is not hiding an early-hour regression.

Validation:
`python -m pytest tests\calibration\test_promotion_refresh.py tests\reporting\test_candidate_hourly_performance.py tests\operations\test_schema_registry.py -q`
passed with `34 passed`, and
`python -m weather.reporting.candidate_hourly_performance --variant-rows data\backtest\item147_time_split_alpha_variant_rows.csv --json-out data\backtest\item147_time_split_alpha_hourly_candidate_performance.json --report-out data\backtest\item147_time_split_alpha_hourly_candidate_performance_report.md`
reported `Candidate hourly gate: PASS`.

## 2026-06-19 live-forward SLO status check

The live-forward blocker is current and should not be treated as a stale
report artifact. At `2026-06-19T14:45:41-04:00`,
`python -m weather.collection.snapshot_tracker --status` reported the snapshot
supervisor `RUNNING`, the loop process alive, runtime identity matching current
code, latest snapshot age `2.6` minutes, and zero missing/stale live variant
prediction markets. Source-family degradation was also clear in the tracker
status payload.

The remaining failure is coverage/countability. The active SLO window is
`2026-06-19T12:00:00-04:00` through `2026-06-19T18:00:00-04:00`, so it cannot
pass before 18:00 local. All 12 markets were still `AT_RISK` at the status
check, `covers_afternoon=false`, and every market had already recorded one or
more intra-window gaps beyond the 15-minute effective tolerance. Market max
gaps ranged from `18.5` minutes to `28.5` minutes: Atlanta `18.5`, Austin
`19.4`, Chicago `19.9`, Dallas `20.0`, Denver `25.1`, Houston `25.1`, Los
Angeles `28.5`, Miami `22.8`, NYC `19.8`, San Francisco `25.1`, Seattle
`27.3`, and Toronto `20.0`.

This is not locally repairable as proof-grade live-forward evidence from the
existing tapes: source-status and forecast-payload backfills can repair
metadata, but they cannot recreate missed live model/market snapshot rows. Keep
the loop running through 18:00 local, rerun fleet observability after the
window closes, and require either a clean future live day or an explicit
cadence/SLO policy change before Item 48 can count broad live-forward evidence.

## 2026-06-19 blocked-market casebook evidence

`weather.reporting.winner_underpricing_casebook` now generates concrete early
snapshot cases for the five remaining blocked Item 147 markets. The report
`data/backtest/item147_blocked_markets_winner_underpricing_casebook_report.md`
scanned `30,569` blocked-market rows and found `387` cases where the market
ranked the eventual winner in the top two bands but the candidate underweighted
or over-spread it. This keeps the next Item 48 model-repair work specific:
Seattle has the largest average winner gap (`+0.2555`), NYC has rank failures
without broad spread, Austin and Los Angeles show near-forecast misses, and
San Francisco remains a narrow non-current-signal problem.

This is development evidence only; readiness stays `OPEN`. It rules in a more
specific next candidate direction: direct warm/cool-side winner-rank repair for
Seattle and NYC plus newly sourced or newly trained non-current skill for
Austin, Los Angeles, and San Francisco, followed by the staged promotion
refresh.

Follow-up validation rejected the shallow version of that idea.
`data/backtest/item147_blocked_markets_forecast_pressure_tilt_validation_report.md`
tests forecast-relative probability tilts selected on earlier market-days and
evaluated later. It remains `BLOCK` and worsens daily-first holdout from
baseline candidate `0.0465` to selected tilt `0.0512` versus market `0.0359`.
All five blocked markets remain outside tolerance, with Seattle worsening to a
`+0.0298` market gap. Item 48 should therefore not spend the next pass on a
single all-band forecast-pressure tilt over existing candidate rows.

Candidate-rank sharpening was tested next and also rejected.
`data/backtest/item147_blocked_markets_candidate_rank_sharpening_validation_report.md`
selects top-k/power rank-shaping policies on June 7/8 and evaluates June 12/13
using only candidate ranks, bin type, and cutoff regime. It remains `BLOCK` and
worsens daily-first holdout from baseline candidate `0.0465` to selected
candidate `0.0493` versus market `0.0359`, widening the market gap from
`+0.0106` to `+0.0134`. Austin, NYC, San Francisco, and Seattle all worsen or
remain outside tolerance; Los Angeles remains blocked. Item 48 should therefore
not spend the next pass on candidate top-rank concentration/flattening either.

The all-hour forecast-profile lane and its cutoff-regime derivative are now
scored as well. `data/backtest/item134_forecast_profile_all_hours_replay_report.md`
scores 67,430 F-family rows from hour `07` through `20` with zero missing
candidate rows. It remains `BLOCK / DO_NOT_CUT_OVER`: daily-first candidate
Brier is `0.0421` versus current `0.0434` and market `0.0378`, leaving a
`+0.0043` market gap. Atlanta, Denver, and Houston pass; Dallas, Los Angeles,
and Miami remain shadow; Austin, Chicago, NYC, San Francisco, and Seattle
remain blocked. High-disagreement guardrails still block Austin, Denver, NYC,
San Francisco, and Seattle.

The all-hour cutoff-regime report
`data/backtest/item135_cutoff_regime_weighting_all_hours_report.md` removes
the old final-lock-in evidence gap but still blocks acceptance. Final lock-in
passes on 44 market-days with a `+0.0002` market gap, while early (`+0.0034`),
midday (`+0.0123`), and late (`+0.0074`) miss the `+0.0030` market-tolerance
threshold. This rules out broad all-hour forecast-profile weighting or simple
regime blending as the next Item 48 unblock; the remaining work is still direct
blocked-market repair.

An existing-variant basket selector was tested after that. The report
`data/backtest/item147_blocked_markets_variant_basket_selection_validation_report.md`
selects among the Item 147 time-split alpha rows, Item 134 all-hour
forecast-profile rows, Item 135 all-hour regime-weighted rows, and current
serving on June 7/8, then evaluates June 12/13 for the five blocked markets.
It remains `blocked`: selected later-date daily-first Brier is `0.0465`
versus current `0.0505` and market `0.0359`, with a `+0.0106` market gap and
all five markets blocked. The eval oracle also blocks at `+0.0092`, so simply
picking among existing no-market variant branches is not enough. Austin is the
one exception with an oracle all-hour forecast-profile pass (`+0.0027`), but
that gain reverses across the train/eval split and is not selectable yet.
The regenerated report also scores slice-key policies. The best selected
slice policy, `cutoff_regime`, still leaves a `+0.0101` market gap, and the
best eval oracle, `settlement_distance_bucket`, still leaves `+0.0074`.
Existing market/slice branch selection is therefore rejected, not just the
coarser per-market selector.

The forecast-side rank version of the casebook hypothesis was tested next in
`data/backtest/item147_blocked_markets_forecast_side_rank_validation_report.md`.
It only boosts the candidate's top-ranked band inside inference-available
`forecast_bucket_pressure` sides, with policy/factor selection on June 7/8 and
evaluation on June 12/13. This also blocks and worsens the selected holdout:
daily-first candidate moves from baseline `0.0465` versus market `0.0359` to
selected `0.0516`, widening the market gap from `+0.0106` to `+0.0157` and
regressing current by `+0.0012`. The diagnostic eval oracle is still outside
tolerance at `+0.0060`; only San Francisco has an eval-only pass, and that
policy is not selected from earlier dates. Item 48 should therefore not spend
the next pass on forecast-side rank boosting over existing candidate rows. The
remaining model path is new model/source signal for Austin/Los Angeles/San
Francisco fallback gaps and NYC/Seattle winner repair, with CLOB continuity if
market-informed anchors are evaluated separately from no-market promotion.

## 2026-06-19 CLOB capture-status logging boundary

The CLOB raw-artifact gate now has a capture-attempt status tape. Each
`weather.market.market_microstructure` token/book capture writes
`clob_capture_status.jsonl` with schema `clob_capture_status_v0.1`; failures
record the stage and error before the capture command re-raises. The refreshed
data-layer audit
`data\backtest\data_layer_audit_after_clob_capture_status_report.md` exposes
that status coverage separately from raw token/book coverage: `12/177` folders
have capture-status rows, but `0/165` training-ready folders do. Raw CLOB
coverage remains `96/177` token-artifact days and `84/177` raw-book days,
with `84/165` and `72/165` on training-ready folders.

This advances Item 48's long-term logging and CLOB continuity diagnostics, but
it does not clear promotion readiness. Historical train-side midpoint evidence
is still absent for the blocked-market anchor splits, so CLOB-informed repairs
remain market-informed shadow/quote evidence until Item 156 creates
threshold-clearing train-side coverage. The no-market readiness path still
needs direct Austin/Los Angeles/NYC/San Francisco/Seattle model repair plus a
countable live-forward SLO report.

## 2026-06-19 post-window live-forward and density refresh

The after-window fleet report
`data\backtest\fleet_observability_after_2026_06_19_window_report.md` keeps
fleet status `CRITICAL` and the broad live-forward SLO at `BLOCK`. The
12:00-18:00 local window is no longer pending; it failed countability. All 12
markets are `PARTIAL` for snapshot collection, and the first blocker is
Toronto `snapshot_coverage_gap` with `9` gaps and max gap `25` minutes.
Per-market max gaps remain beyond the 15-minute effective tolerance: Toronto
`25`, NYC `20`, Atlanta `19`, Austin `19`, Chicago `20`, Dallas `20`, Denver
`25`, Houston `25`, Los Angeles `28`, Miami `23`, San Francisco `25`, and
Seattle `27` minutes.

The same report shows the useful boundary: CLOB discovery, CLOB book freshness,
observation-trigger health, latest model-row freshness, variant prediction
freshness, and afternoon-window coverage all pass. The remaining live-forward
blockers are snapshot cadence gaps and source-status freshness. I ran the
generated repair command
`python -m weather.collection.snapshot_tracker --backfill-source-status --overwrite-source-status`;
it rebuilt `source_status_long` artifacts for `177` folders with `200,226`
rows. The refreshed report
`data\backtest\fleet_observability_after_2026_06_19_source_status_backfill_report.md`
still reports `CRITICAL`: source-status freshness remains `BLOCK` for all 12
markets because `open_meteo` is still degraded, and snapshot coverage remains
the first blocker. Metadata backfill is therefore not enough to make June 19
countable; Item 48 still needs a clean future live-forward day or an explicit
cadence/SLO policy change, plus source-status repair that clears the degraded
Open-Meteo family.

Follow-up observability wiring now separates this blocker from stale metadata.
`source_family_degradation` retains per-family fresh/failed/fallback source
lists, and fleet recovery rows classify Open-Meteo cache fallback as
`open_meteo_provider_fallback` owned by `Open-Meteo quota / forecast source
collector`. The refreshed report
`data\backtest\fleet_observability_after_2026_06_19_source_status_recovery_detail_report.md`
still stays `CRITICAL`, but the broad recovery gate now shows
`source_status_freshness` blocked for all 12 markets by Open-Meteo fallback
sources such as `open_meteo`, `open_meteo_multimodel`, `global_ensemble`, and
`eccc_gem`, with repair/diagnosis through `snapshot_tracker --status` rather
than the already-failed source-status backfill. This does not make June 19
countable; it makes the remaining source-status blocker actionable at the
provider/quota/cache layer instead of mislabeling it as a missing artifact.

Future live-source mitigation is now wired as well. The Open-Meteo-family
fetch budget used to reuse last-good cache only when it was younger than 10
minutes, even though forecast-source TTLs are `90` minutes for `open_meteo`
and `120` minutes for `global_ensemble`, `open_meteo_multimodel`, and
`eccc_gem`. That meant a TTL-valid 60-70 minute forecast cache could still
trigger a provider call, receive HTTP 429, and be logged as
`rate_limited_cache` fallback. `weather.model.model_sources` now reuses
Open-Meteo-family cache for the full per-source TTL before making another
provider call. Regression tests cover both sides: an 80-minute `open_meteo`
cache skips the provider call and remains `fresh_cache`, while a 95-minute
cache refreshes live.

A real-cache probe against the June 19 market roots with provider calls
disabled showed the new policy would have skipped `27/36` current
Open-Meteo-family calls. The remaining 9 were already beyond their source TTL
and still correctly require refresh. This is future live-forward hardening,
not retroactive proof: the June 19 source-status rows remain degraded because
they were captured before this mitigation.

The last-good source cache loader now also self-quarantines invalid cache
files. Fleet observability's loop-integrity samples showed repeated
`Error loading last good sources cache` console text from prior corrupt cache
reads, which is bad both for source fallback and long-term log hygiene.
`weather.model.model_sources` now moves JSON-decode failures and non-object
cache roots aside as `last_good_sources.corrupt.*.json` and returns an empty
cache for that cycle, so the loop can resume with a clean cache file on the
next successful source fetch instead of emitting the same parse error
indefinitely. Regression tests cover malformed JSON and non-object JSON roots.
The current 12 market cache files parse successfully under the production
Python loader, so no live cache file needed quarantine during this pass.

I also corrected the generated live-forward repair commands and restarted the
snapshot loop onto the current code. `weather.reporting.fleet_observability`
and market-making preflight now emit the executable
`python -m weather.collection.snapshot_tracker --status` form instead of the
invalid positional status form. The running snapshot supervisor was restarted
onto the current source tree after these source-fetch changes; the latest
restart stopped stale PID `37592` and started PID `44504`, and the follow-up
`--status` reported `state=RUNNING`, `runtime_code_state=current`, and
`runtime_identity_matches_current=true`. The refreshed report
`data\backtest\fleet_observability_after_snapshot_restart_rate_limit_detail_2026_06_19_report.md`
still blocks broad live-forward evidence on historical snapshot gaps, but its
recovery checklist now uses `--status`, and Open-Meteo rate-limit degradation
is owned by `Open-Meteo quota / forecast source collector` with
`rate_limited_sources` listed explicitly.

Open-Meteo-family live fetches are now same-cycle throttled too. The source
adapter still runs unrelated sources in parallel, but `weather.model.model_sources`
partitions `open_meteo`, `open_meteo_multimodel`, `global_ensemble`, and
`eccc_gem` into a sequential group. That makes the existing shared provider
cooldown effective inside a single capture cycle: after one family source gets
HTTP 429, later expired same-family sources are stopped by provider cooldown
instead of issuing more provider calls. TTL-valid same-family cache is still
served before the cooldown check, so a cached `eccc_gem` forecast can remain
`fresh_cache` even if `open_meteo` just rate-limited. Tests cover both the
cooldown suppression and the TTL-valid cache preservation paths.

The source-status gate now separates provider-rate-limit noise from true
family loss. `weather.collection.collection_health` treats an Open-Meteo
family as non-blocking when rate-limited sources still have fresh same-family
coverage and there are no failed, fallback, or unknown rows; it also emits
`blocking_family_count` and `provider_cooldown_source_count` so fleet
observability can show both affected and actually blocking families. The
refreshed report
`data\backtest\fleet_observability_after_rate_limit_family_coverage_2026_06_19_report.md`
is still `CRITICAL`, but the source-status recovery gate moved from 12 blocked
markets to 1. Snapshot coverage remains the first blocker across all 12
markets, while source-status now blocks only Toronto because its Open-Meteo
family has zero fresh family coverage in the latest row.

The Toronto check exposed a separate cache sustainability issue: replay inputs
showed successful `global_ensemble` rows earlier in the evening, but
`data\wunderground\cyyz\last_good_sources.json` later contained only
observation and non-Open-Meteo forecast keys. The likely cause was concurrent
last-good cache writers replacing the whole file with narrower source sets.
`weather.model.model_sources` now wraps `last_good_sources.json` writes in the
existing writer-lock primitive, reloads and merges the current disk cache under
that lock, then atomically replaces the file. If the lock is busy, the save is
skipped rather than risking a destructive overwrite. Regression tests cover
merge preservation and the busy-lock path. After this cache-save fix, the
snapshot supervisor was restarted again from stale PID `39072` to PID `35236`;
the follow-up `--status` check reported `state=RUNNING`,
`runtime_code_state=current`, and `runtime_identity_matches_current=true`.

A subsequent fleet refresh after the cache-lock restart,
`data\backtest\fleet_observability_current_2026_06_19_after_cache_lock_report.md`,
still reports `CRITICAL`: historical snapshot coverage gaps block all 12
markets, and Toronto remains the only source-status blocker. The source-status
shape narrowed further but exposed an official-observation publication-lag
case: the latest SWOB directory listed the 23:00Z CYYZ XML file before the file
was fetchable, so the per-file 404 caused the whole `eccc_swob` fetch to fall
back despite valid earlier same-day SWOB rows. `fetch_eccc_swob` now skips
individual SWOB XML 404s from a directory listing, preserves earlier valid
same-day rows as live source data, and records the skipped-file count/list in
the source payload. This is another future live-forward hardening fix, not a
retroactive June 19 proof: the snapshot coverage gaps are already baked in,
and Open-Meteo still needs fresh-family recovery or a future clean live day.
The snapshot supervisor was restarted onto this fix as PID `38648`, with
`state=RUNNING`, `runtime_code_state=current`, and zero consecutive errors.

The snapshot-cadence root cause is now clearer from
`data\snapshots\diagnostics.jsonl`: the largest June 19 coverage holes aligned
with repeated stale-code supervisor restarts during active development, not a
slow steady-state capture cycle. `scripts\ops\register_snapshot_supervisor.ps1`
now registers the short-lived `--ensure` task every 2 minutes instead of every
10 minutes while leaving the detached snapshot loop's capture interval at 10
minutes. This gives stale/dead loop recovery multiple chances before the
15-minute live-forward tolerance is breached. The local Windows task
`WeatherSnapshotLoopSupervisor` was re-registered and its repeating trigger now
reports interval `PT2M`; after the script change, the loop was restarted from
stale PID `38648` to PID `33816`, and status returned `RUNNING` with current
runtime identity and zero consecutive errors. This is future SLO hardening,
not retroactive June 19 proof.

The full Item 35 continuous-density v0.7 artifact is also rejected as an Item
48 promotion lane. `data\backtest\item35_density_full_replay_v0_7_report.md`
scored all `76,879` pinned market rows with zero missing candidate rows but
returned `BLOCK / DO_NOT_CUT_OVER`: daily-first candidate Brier `0.044628`
versus current `0.041916` and market `0.036667`, a `+0.007961` market gap.
Toronto still regresses current by `+0.003174`, and forecast-profile guardrails
block Austin, Denver, NYC, San Francisco, Seattle, and Toronto. The
conservative bridge only reaches `0.042463`, slightly better than current but
still `+0.005140` worse than market, so it remains shadow serving-safety
evidence rather than a readiness unblock.

The blocked-market repair diagnostic now emits explicit repair actions for the
residual Item 48 market blocks. The refreshed retained export
`data\backtest\item147_blocked_market_repair_actions_report.md` covers
`30,569` later-date rows across the five blocked markets and records:
Austin, Los Angeles, and San Francisco need `add_non_current_market_signal`
because they are full current fallback while market prices still win; Seattle
needs `repair_winner_probability_mass`; NYC needs
`repair_largest_market_gap_slice` rather than another broad all-market blend.
No current-regression guard fires on this row set. This does not clear the
readiness gate, but it makes the next promotion-refresh attempt market-specific
instead of repeating the rejected broad density/exact-winner lanes.

Verification:
`python -m pytest tests\reporting\test_blocked_market_repair_diagnostics.py tests\operations\test_schema_registry.py -q`
passed with `10 passed`, and the strict schema audit for
`blocked_market_repair_diagnostics_v0.1` reported `unregistered_versions=0`.

## 2026-06-19 post-window backup refresh

The new CLOB capture-status tape briefly reopened the tape-backup gate:
`data\backtest\fleet_observability_current_2026_06_19_1949_report.md`
reported `MISSING_CRITICAL_FILES` because twelve live
`clob_capture_status.jsonl` files were now classified as critical CLOB tape
evidence but were not yet in the latest backup manifest. I ran the backup job
against `data\tape_backups`:
`python -m weather.operations.tape_backup run --source-root . --backup-root data\tape_backups --status-out data\backtest\tape_backup_status.json --status-report data\backtest\tape_backup_status_report.md --restore-out data\backtest\tape_restore_drill.json --restore-report data\backtest\tape_restore_drill_report.md`.

That cleared the local backup gate again. The updated manifest hash is
`458b1982459b2aed96d2ec1a41694f0b4ae29d29ee307628858ef45d5a49375d`; the
restore drill passed with `3,369` restored files; `tape_backup_status.json`
reports `OK`, restore SLA `OK`, zero missing critical files, and all six
required CLOB artifact classes restored.

The canonical fleet and learning reports were refreshed afterward:
`data\backtest\fleet_observability_report.md` and
`data\backtest\daily_learning_report.md`. Item 48 still remains `PARTIAL`:
fleet status is `CRITICAL`, but now the critical alerts are the twelve
snapshot-cadence gaps rather than tape backup. Broad live-forward SLO is still
`BLOCK` because all 12 markets are `PARTIAL`, with Toronto first at `9` gaps
and max gap `25` minutes. Source-status freshness is still a secondary blocker
for five Open-Meteo-family markets, while latest model rows, variant
prediction freshness, CLOB book capture, observation trigger, and tape backup
are green.

Daily learning remains `BLOCKED` with four blockers. The first P0 gate is
still the current-serving hourly performance gate, while the broad
live-forward SLO remains non-countable on `snapshot_coverage_gap`. The next
Item 48 operational unblock is therefore a clean future live-forward day under
the 2-minute supervisor recovery policy plus Open-Meteo source-family recovery;
the model unblock remains the market-specific Austin/Los Angeles/NYC/San
Francisco/Seattle repair before another staged promotion refresh can become
readiness evidence.

## 2026-06-19 forecast-side winner-boost validation

Item 147's blocked-market repair diagnostic pointed at Seattle winner-mass
underpricing and NYC/San Francisco forecast-side market gaps, so the next
promotion-readiness check tested an inference-available EQ multiplier rather
than another replay-row oracle. `weather.reporting.winner_boost_validation`
now includes forecast-pressure/cutoff policies such as `near_forecast_eq`,
`warm_side_eq`, `cool_side_eq`, and early/midday variants while still avoiding
settlement-derived fields.

The generated report
`data\backtest\item147_winner_boost_forecast_side_validation_report.md`
remains `BLOCK`. Earlier-date policy selection overfits: later-date
daily-first Brier worsens from baseline `0.0465` to selected `0.0519`, versus
current `0.0504` and market `0.0359`. Austin is slightly better but still
outside market tolerance; Los Angeles, NYC, San Francisco, and Seattle all
remain blocked.

Promotion readiness is therefore unchanged. This result narrows the model
unblock path: a simple forecast-side EQ boost is rejected, so the remaining
work is direct market-specific model/source repair plus the already-open live
SLO and source-status recovery gates.

## 2026-06-19 Item 32 branch basket refresh

The blocked-market variant basket was refreshed with the Item 32
reanalysis-rich no-pressure branch added to the existing Item 147/134/135
branches:
`data\backtest\item147_blocked_markets_variant_basket_with_item32_validation_report.md`.
The report selects among current serving and the retained no-market variants
on June 7/8, then evaluates June 12/13 for Austin, Los Angeles, NYC, San
Francisco, and Seattle.

Readiness stays blocked. The selected basket is unchanged at daily-first Brier
`0.0465` versus current `0.0505` and market `0.0359`, leaving a `+0.0106`
market gap and all five markets blocked. The diagnostic eval oracle improves
slightly to `+0.0085` with Item 32 available, but still misses tolerance.
Austin is the only promising Item 32 clue: eval-oracle Item 32 reaches a
`+0.0005` Austin market gap, but the train split still selects current, so it
is not eligible readiness evidence.

Item 48 therefore remains `PARTIAL`. The next model unblock is not selecting
among current retained branches; it is making the Austin reanalysis signal
split-stable while separately repairing NYC/Seattle winner/slice gaps and
finding a current-safe non-current signal for San Francisco and Los Angeles.

The regenerated report now includes leave-one-market-day stability. This
confirms the Austin signal is promising but still not readiness evidence:
Item 32 is selected in 3 of 4 Austin held-out-day cuts, but the selected
aggregate remains blocked at `+0.0054` versus market and slightly regresses
current. The Austin eval oracle would pass at `-0.0002`, so the next promotion
candidate should try to make that reanalysis lift selectable without the weak
June 7/13 behavior. Los Angeles is near tolerance but still blocked at
`+0.0037`; NYC, San Francisco, and Seattle remain blocked under leave-one-day
selection and even oracle checks. Promotion readiness is unchanged until those
market-specific repairs clear a full pinned refresh plus the live SLO gates.

The guarded-branch extension narrows the Austin path further. A fixed Item 32
`all_fresh_midday_late` guard passes the Austin local market tolerance at
`+0.0024` and improves current, but the train-selected leave-one-day guard
still misses at `+0.0034`. That means Item 48 should not promote this evidence
yet, but it has a concrete next candidate to test: wire a predeclared Austin
all-fresh midday/late reanalysis guard into a replayable artifact and rerun the
full promotion refresh. Los Angeles has a similar near-miss (`not_near_forecast`
fixed guard `+0.0021`, train-selected `+0.0031`), while NYC, San Francisco,
and Seattle remain far from readiness under these guarded branches.

## 2026-06-19 Austin guarded replay refresh

The Austin all-fresh midday/late reanalysis guard is now in a replayable
artifact and has full pinned replay evidence:
`data/backtest/item32_reanalysis_austin_guard_replay_report.md`. The replay
uses `current_blend_context_alpha` to keep Austin on current serving except
for all-fresh midday/late rows, where the Item 32 reanalysis branch is active.

This improves the Item 48 model state but does not clear readiness. Austin
moves from blocked to `PASS`: candidate Brier `0.03849` versus current
`0.04099` and market `0.03620`, a `+0.00228` market gap. The candidate action
set becomes Austin, Houston, and Los Angeles cutover-ready; Atlanta, Dallas,
Denver, and Miami remain shadow; Chicago, NYC, San Francisco, and Seattle
remain blocked.

Overall readiness is still `PARTIAL`: the full replay remains
`BLOCK / DO_NOT_CUT_OVER` with aggregate daily-first market gap `+0.00512`.
Operational live-forward/source-status gates also remain open. The next Item
48 model unblock is now smaller: preserve the Austin guarded policy and repair
Chicago/NYC/San Francisco/Seattle before rerunning a staged promotion refresh.

## 2026-06-20 UTC combined guard/raw-alpha replay refresh

The next promotion-readiness model refresh cloned the Austin guarded artifact
to `data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_candidate.pkl`,
kept Austin's `all_fresh` midpoint/late context rule, opened Chicago and NYC
to raw candidate alpha, and left San Francisco on current fallback after the
prior raw-alpha regression.

The pinned replay
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_replay_report.md`
still reports `BLOCK / DO_NOT_CUT_OVER`, but improves the promotion baseline:
aggregate candidate Brier is `0.04141` versus current `0.04349` and market
`0.03787`; daily-first candidate Brier is `0.04136` versus current `0.04344`
and market `0.03783`, a `+0.00353` market gap. Candidate cutover-ready markets
remain Austin, Houston, and Los Angeles; Atlanta, Dallas, Denver, and Miami
remain shadow; Chicago, NYC, San Francisco, and Seattle remain blocked.

The refreshed repair-action report
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_repair_actions_report.md`
updates the readiness backlog: Chicago is now
`market_gap_without_clear_winner_signal`, NYC and Seattle remain
`winner_underpricing_vs_market`, and San Francisco remains
`current_fallback_trails_market`. Item 48 therefore stays `PARTIAL`: this is a
better model baseline for the next refresh, but readiness still needs those
four market gaps plus the live-forward/source-status operational gates cleared.

I also reran the current-blend time-split gate after teaching it the same
`current_blend_context_alpha` semantics used by replay:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_current_blend_validation_report.md`.
The result is still `BLOCK`: selected daily-first market gap is `+0.00527`,
worse than the combined replay baseline's `+0.00491`, and Austin, Chicago,
Los Angeles, NYC, San Francisco, and Seattle remain holdout blocks. Promotion
readiness should therefore keep the combined replay as the current model
baseline and move to market-specific repairs, not another alpha-grid sweep.

I also generated a development-only context-guard scan:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_context_guard_validation_report.md`.
It selects raw/current guards on earlier market-days using only inference-time
slice keys and evaluates later market-days. This scan also blocks and slightly
worsens the combined baseline (`+0.00509` selected daily-first market gap
versus `+0.00491` baseline). The remaining readiness blockers are not cleared:
Chicago's best guard is still `+0.00461` versus market, NYC and Seattle remain
well outside tolerance, and San Francisco has no raw candidate rows in this
artifact. The next promotion refresh should wait for new market-specific signal
or features, not another guard selection over this export.

The source-family inventory was rerun for the combined Item 32 replay and now
checks the artifact's reanalysis lane contract directly:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_source_family_inventory_report.md`.
The source-family preflight is `PASS`; `reanalysis_synoptic` is active with 36
features, lineage/parity/ablation all pass, and the artifact's no-pressure lane
is consistent with the settlement-scored market gates. This clears a promotion
evidence weakness for the staged candidate, but it does not change Item 48
readiness: the replay remains `DO_NOT_CUT_OVER`, four model markets are still
blocked, and the operational live-forward/source-status gates remain open.

I then reran a staged promotion refresh using the precomputed combined replay
and staged source-family inventory:
`data/backtest/item48_item32_combined_guard_chicago_nyc_raw_promotion_refresh_report.md`.
This run skipped a fresh serving gauntlet and did not export another variant
CSV; it is promotion-readiness evidence for the current candidate state, not a
production cutover. The result is still `OPEN`: candidate verdict `BLOCK`,
market-only verdict `PARTIAL_PASS`, and cutover decision `DO_NOT_CUT_OVER`.
The candidate action set is unchanged at 3 promote (Austin, Houston, Los
Angeles), 4 shadow (Atlanta, Dallas, Denver, Miami), and 4 blocked (Chicago,
NYC, San Francisco, Seattle). Source-family preflight is now `PASS`, but
readiness remains blocked by aggregate market skill (`+0.0035`), daily-first
blocked validation, the four blocked markets, live-forward SLO, and the
current-serving hourly-performance gate.

## 2026-06-20 UTC candidate-hourly mitigation refresh

I generated candidate-hourly evidence for the combined Item 32
guard/raw-alpha candidate:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_hourly_candidate_performance_report.md`.
The candidate-hourly gate passes on 44 market-days and 4,356 early-morning
rows: variant Brier `0.0543` versus current `0.0553` and market `0.0519`,
variant log-loss trails market by only `+0.0087` inside the `0.0100`
tolerance, and ECE is `0.0062` versus the `0.1200` cap.

The staged promotion refresh was rerun with that candidate-hourly report:
`data/backtest/item48_item32_combined_guard_chicago_nyc_raw_promotion_refresh_with_candidate_hourly_report.md`.
Readiness remains `OPEN`, but the prior hourly-performance readiness blocker
is now mitigated because the candidate-hourly gate is `PASS` and the variant
ID matches `item32_reanalysis_austin_guard_chicago_nyc_raw`. The operational
gate table still reports the current-serving hourly gate as `BLOCK`, but now
also shows `Hourly gate mitigation | APPLIED`.

The remaining promotion blockers are therefore narrower and unchanged on model
quality/ops: aggregate candidate trails market by `+0.0035`, daily-first
blocked validation still fails, Atlanta/Dallas/Denver/Miami remain shadow,
Chicago/NYC/San Francisco/Seattle remain blocked, and live-forward SLO is
still `BLOCK`. Candidate cutover remains `DO_NOT_CUT_OVER`; Item 48 stays
`PARTIAL` until those gates clear.

Focused validation:
`python -m pytest tests\calibration\test_promotion_refresh.py tests\reporting\test_candidate_hourly_performance.py tests\operations\test_schema_registry.py -q`
passed with 35 tests. The broader shared reporting/calibration slice
`python -m pytest tests\reporting\test_source_family_inventory.py tests\calibration\test_promotion_refresh.py tests\reporting\test_current_blend_validation.py tests\calibration\test_pooled_candidate_replay.py tests\reporting\test_variant_basket_selection_validation.py tests\reporting\test_blocked_market_repair_diagnostics.py tests\operations\test_schema_registry.py -q`
passed with 105 tests. The scoped strict schema audit for the touched reporting
and replay modules reported `registered=192 discovered=212
unregistered_versions=0`.

## 2026-06-20 UTC reproducible context-guard rejection

I registered `weather.reporting.context_guard_validation` and regenerated the
combined Item 32 context-guard report with two-condition policies:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_context_guard_validation_report.md`.
This is development evidence only, but it is now reproducible instead of an
ad hoc scan.

The report remains `BLOCK`: train-selected context guards worsen daily-first
market gap from the observed baseline `+0.0049` to `+0.0054`. It does not
rescue the promotion blockers. Chicago's best eval oracle guard is still
`+0.0047` versus market, NYC is `+0.0195`, San Francisco is current-only at
`+0.0056`, and Seattle is `+0.0161`. The selected policies also make Austin,
Houston, and Los Angeles fail on the holdout split, so Item 48 should not try
another guard-selection promotion refresh over this candidate export.

The next promotion-readiness model work remains direct repair: keep the Austin
guarded replay baseline, add real Chicago slice signal, repair NYC/Seattle
winner probability mass, and source a non-current San Francisco signal before
rerunning staged promotion readiness. The operational side still needs the
live-forward SLO blocker cleared before readiness can become `READY`.

## 2026-06-20 UTC loop-log repair and current-code restart evidence

I repaired the operational logging side of the Item 48 live-forward blocker
without changing readiness. The initial post-restart fleet report
`data/backtest/fleet_observability_after_snapshot_restart_report.md` still
reported `CRITICAL`: source-status proof was green, but live-forward SLO was
`BLOCK` from `snapshot_coverage_gap` across all 12 active markets. It also
showed loop artifact integrity debt: 852 malformed console-log lines across
the snapshot, CLOB, and observation-trigger loops.

`weather.operations.loop_jsonl_repair` now refuses to rewrite a managed loop's
console log while its matching writer lock belongs to a live process unless
`--allow-active` is passed. The first repair pass exposed why that guard is
needed: rewriting the active CLOB console log left one NUL-filled malformed
line at the writer's old file offset. I stopped/restarted the CLOB writer,
repaired the final line, and then restarted CLOB and observation-trigger after
the code change so their runtime identities matched the current tree. I also
fixed the observation-trigger supervisor's stop/start path so a stopped or
dead writer PID has its writer lock removed before the next detached watcher
starts; without that cleanup, restarted watchers exited immediately with
`duplicate_writer_blocked`.

The final evidence is:

- `data/backtest/loop_jsonl_repair_final_fixed_supervisor_audit.md`: `PASS`,
  malformed lines `0` across the three managed loop console logs.
- `data/backtest/fleet_observability_after_observation_lock_fix_report.md`:
  loop artifact integrity `OK`, malformed lines `0`, duplicate writers `0`.
- The same fleet report still has `Current-Code Soak Proof` `BLOCK`, but the
  remaining reasons are historical restart budget and duplicate-writer incident
  counts, not stale/dead loops or malformed logs. All three managed loops are
  `RUNNING`, current-code, single-writer, and at zero consecutive errors.

Item 48 therefore remains `PARTIAL`: live-forward SLO is still blocked by the
non-recoverable June 19 snapshot cadence gaps, and promotion readiness still
needs a future clean active-day soak plus the existing model-quality blockers
before any `READY` claim.

## 2026-06-20 UTC winner-underpricing repair targeting

I regenerated the combined Item 32/48 winner-underpricing casebook after adding
all-case dominant-pattern reporting:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_winner_underpricing_casebook_report.md`.
It scans `24,530` rows and finds `312` early winner-underpricing cases across
the still-blocked Chicago, NYC, San Francisco, and Seattle promotion markets.

This supports the same promotion-readiness direction as the prior repair
diagnostics but with better targeting:

- NYC and Seattle should get direct winner-mass repair before another staged
  promotion refresh. NYC has `131` cases, mostly all-fresh and cool-side; the
  repeated `eq:88.0-89.0` and `eq:94.0-95.0` winner bands have average
  underpricing gaps of `+0.2492` and `+0.1873`. Seattle has `113` cases,
  mostly warm-side, with `eq:74.0-75.0` and `eq:64.0-65.0` carrying gaps of
  `+0.2116` and `+0.2494`.
- Chicago should remain a slice-repair task rather than a generic mass
  sharpening task because its average spread gap is negative (`-0.1355`).
- San Francisco remains a non-current signal task: all `24` cases are
  `near_forecast` and `high_disagreement`, with positive spread gap but only a
  small average winner gap (`+0.0509`).

This is not promotion evidence. Item 48 remains `PARTIAL` until model-quality
gates, daily-first validation, and the live-forward SLO/clean active-day soak
all clear.

Because the casebook report changed source identity, I also refreshed the
operational evidence after restarting the observation watcher onto the current
tree:
`data/backtest/fleet_observability_after_casebook_pattern_refresh_report.md`.
The report is still `CRITICAL` from non-recoverable June 19
`snapshot_coverage_gap`, but observation-trigger health is now `PASS`, loop
artifact integrity remains clean (`0` malformed lines, `0` duplicate writers),
and all three managed loops are `RUNNING`, `current`, single-writer, and at
zero consecutive errors. Current-code soak remains `BLOCK` only because of
historical restart-budget and duplicate-writer incident counts.

## 2026-06-20 UTC contextual winner repair validation

I extended `weather.reporting.contextual_winner_validation` to
`contextual_winner_time_split_validation_v0.2` with `band_key` contexts and an
eval-oracle diagnostic, then regenerated:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_contextual_winner_validation_report.md`.

The selected split-safe contextual factors are not promotion evidence, but they
move the aggregate model-quality gate in the right direction: daily-first
holdout improves from baseline `0.0434` to `0.0426` versus market `0.0385`,
shrinking the market gap from `+0.0049` to `+0.0041`. Promotion readiness still
cannot advance because Chicago (`+0.0097`), NYC (`+0.0207`), San Francisco
(`+0.0056`), and Seattle (`+0.0164`) remain outside tolerance, and the
live-forward SLO/clean active-day soak remains blocked.

The important promotion implication is negative: do not rerun staged promotion
refresh on this contextual postprocess yet. The eval oracle shows target-day
band-key mass can clear the blocked markets diagnostically, but train-selected
factors do not identify the right later-date bands. The next promotable repair
needs a real inference-time band-selection signal, then a full pinned replay
and staged promotion refresh.

I also regenerated fleet observability after the contextual-winner source
change:
`data/backtest/fleet_observability_after_contextual_winner_v0_2_refresh_report.md`.
The report is still `CRITICAL`, but the operational blocker shape is now
current-code evidence rather than stale-loop ambiguity. Loop artifact integrity
is `OK` with malformed lines `0` and duplicate writers `0`; snapshot, CLOB,
and observation-trigger loops are all `RUNNING`, `current`, single-writer, and
at zero consecutive errors. The remaining active-day countability blockers are
non-recoverable June 19 `snapshot_coverage_gap` across 12 markets,
historical restart-budget/duplicate-writer incident counts in current-code
soak, and `MISSING_CRITICAL_FILES` tape backup status. Item 48 therefore stays
`PARTIAL` until a future clean active-day soak and the model-quality blockers
both clear.

## 2026-06-20 UTC winner-band row-signal promotion check

I added `weather.reporting.winner_band_signal_validation` and generated the
combined Item 32/48 report:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_winner_band_signal_validation_report.md`.
It tests a pooled logistic row model over inference-time row shape and
forecast/source context, with transform selection on `2026-06-08` and later
holdout scoring on `2026-06-12` / `2026-06-13`.

The result is `BLOCK` and should not trigger staged promotion refresh. The
pre-eval selector chooses `baseline`; the only aggregate improvement,
`row_norm` (`0.0424` versus baseline `0.0434`), is eval-only diagnostic
hindsight and still leaves Chicago `+0.0075`, NYC `+0.0175`, Seattle
`+0.0180`, Houston `+0.0064`, and Los Angeles `+0.0051` versus market.
San Francisco improves to `+0.0024` under that eval-only row signal, so it is
useful for targeting but not enough for readiness.

Promotion implication: keep Item 48 out of `READY`. The next refresh needs a
real target-day band-selection signal and a full pinned replay, not a generic
row-shape classifier layered on the current export.

After adding the row-signal validator, I refreshed all managed loops and
regenerated fleet observability again:
`data/backtest/fleet_observability_after_winner_band_signal_refresh_report.md`.
The report remains `CRITICAL`, but the current-code evidence is clean for the
new source fingerprint `1e38db421dace6a5`: loop artifact integrity is `OK`,
malformed lines `0`, duplicate writers `0`, and snapshot/CLOB/observation
loops are `RUNNING`, `current`, single-writer, and at zero consecutive errors.
The remaining blockers are still June 19 `snapshot_coverage_gap`, historical
restart-budget/duplicate-writer incident counts, and tape backup status
`MISSING_CRITICAL_FILES`.

## 2026-06-20 UTC CLOB continuity check for promotion readiness

I regenerated the exact combined replay CLOB coverage audit with split
classification counts:
`data/backtest/item32_35_48_combined_replay_clob_coverage_audit_report.md`.
The v0.3 promotion implication is negative and concrete. The train side of the
current replay window has no usable CLOB evidence and no local restore source:
all `24` June 7/8 folders are `missing_raw_clob_tape_and_token_map`, with
`0.0000` midpoint coverage, zero raw-book folders, zero token-map folders, and
`0/24` full raw restore availability in local backup manifests. The June 12/13
eval side is partially informative (`0.2380` midpoint row coverage, `16`
midpoint-available folders, `8` one-sided/no-midpoint folders), and all `24`
eval folders have raw restore sources, but that is not split-safe selection
evidence.

Item 48 therefore stays `PARTIAL` and should not run a staged promotion
refresh that depends on CLOB/microstructure repair from the current export.
The next promotion-readiness unblock is to restore/backfill train-side raw
CLOB books and token maps from an external/off-machine source, or collect fresh
clean train/eval market days, then rerun CLOB coverage, full pinned replay,
staged promotion refresh, and the live-forward SLO/clean active-day soak.
Until then, CLOB can be cited only as diagnostic eval-side targeting evidence,
not as promotable readiness evidence.

I also regenerated fleet observability under the v0.3 restore-audit source
fingerprint:
`data/backtest/fleet_observability_after_clob_coverage_v0_3_restore_audit_refresh_report.md`.
The report remains `CRITICAL`, but current-code loop health is clean for source
fingerprint `acccd8c28ec22b2a`: loop artifact integrity is `OK` with malformed
lines `0` and duplicate writers `0`; snapshot, CLOB, and observation-trigger
loops are all `RUNNING`, `current`, single-writer, and at zero consecutive
errors. The remaining operational blockers are the non-recoverable June 19
`snapshot_coverage_gap`, historical restart-budget/duplicate-writer incident
counts in current-code soak, and tape backup status `MISSING_CRITICAL_FILES`.

## 2026-06-20 UTC reanalysis sidecar coverage promotion check

I added a replay-window sidecar audit for the reanalysis/synoptic layer and
generated:
`data/backtest/item32_reanalysis_sidecar_coverage_audit_report.md`.
The promotion implication is mixed but useful. For the June 7-13 combined
replay window, all 12 markets have full core antecedent weather, rich
Open-Meteo archive, and teleconnection sidecar coverage. The remaining
reanalysis data blocker is narrower: all 12 markets have `0.0%` pressure-level
coverage for NOAA PSL 850 hPa temperature, 500 hPa height, and 1000-500 hPa
thickness, with last complete pressure-level coverage on `2026-03-18`.

Item 48 therefore remains `PARTIAL`: staged promotion should not run on a
claim that pressure-level reanalysis is available for the replay target
window, and the model-quality/CLOB continuity gates still block readiness.
The next promotion refresh must wait for a pressure-level cache refresh and
sidecar rebuild, or explicitly declare a no-pressure reanalysis lane, then
rerun source-family inventory, Item 27 gates, full pinned replay, and staged
promotion refresh.

I refreshed fleet observability after adding the sidecar coverage audit:
`data/backtest/fleet_observability_after_reanalysis_sidecar_coverage_audit_refresh_report.md`.
The report remains `CRITICAL`, but current-code loop health is still clean for
source fingerprint `8ddc6e8f6ae42e83`: loop artifact integrity is `OK` with
malformed lines `0` and duplicate writers `0`; the three managed loops are
all `RUNNING`, `current`, single-writer, and at zero consecutive errors. The
remaining operational blockers are unchanged: June 19 `snapshot_coverage_gap`
across 12 markets, historical restart-budget/duplicate-writer incident counts
in current-code soak, and tape backup status `MISSING_CRITICAL_FILES`.

## 2026-06-20 UTC v0.7 density row-export promotion check

I reran the full v0.7 density replay with candidate row export enabled:
`data/backtest/item35_density_v0_7_row_export_replay_report.md`. This remains
`BLOCK / DO_NOT_CUT_OVER`: aggregate candidate Brier is `0.04539` versus
current `0.04267` and market `0.03732`, and daily-first candidate Brier is
`0.04463` versus current `0.04192` and market `0.03667`.

The row-level repair diagnostics are promotion-negative. The report at
`data/backtest/item35_density_v0_7_repair_diagnostics_report.md` leaves nine
markets blocked: Austin, Chicago, Denver, Los Angeles, Miami, NYC,
San Francisco, Seattle, and Toronto. The same export also shows current
regression in nine markets and winner underpricing versus market in eight
markets, while
`data/backtest/item35_density_v0_7_winner_underpricing_casebook_report.md`
finds `673` strict early underpricing cases across Austin, Los Angeles, NYC,
San Francisco, and Seattle.

Item 48 therefore stays `PARTIAL`; this v0.7 artifact should not be staged for
promotion. The readiness unblock is the same as Item 35: restore or collect
split-safe CLOB/microstructure continuity, build a target-day band-selection
repair that passes current-regression checks on later dates, rerun the full
pinned replay, then refresh staged promotion only after model-quality and
live-forward operational gates both clear.

## 2026-06-22 proof packet mapping

Proof-packet blocker: `weather_only_model_proof_packet.market_dispositions`.
Item 48 is the owner for the canonical per-market PROMOTE/SHADOW/BLOCK
decision table; staged promotion refreshes do not count as readiness progress
unless they change that packet field or clear its first blocker.

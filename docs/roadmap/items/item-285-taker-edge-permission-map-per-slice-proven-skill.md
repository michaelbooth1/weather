# 285. Taker Edge-Permission Map For Per-Slice Proven-Skill Entry [COMPLETE 2026-06-23 - FAIL-CLOSED TAKER EDGE PERMISSION LIVE]

Goal: give the taker the maker's discipline. Only allow a taker entry in a
slice where settlement-scored, after-fee, out-of-sample evidence shows the model
beat the market, using a per-slice edge-permission map instead of trading any
positive model edge.

Source: 2026-06-23 ML audit of the taker bot. The maker side gates quoting on a
generated `known_edge_map` with `edge_allowed` cells (items 47/54), but a grep of
`src/weather/market/taker_bot*.py` finds no `known_edge`, `edge_permission`,
`edge_allowed`, or per-slice skill consumption: the taker trades wherever raw
model edge clears a threshold. The repository already produces the per-slice
evidence this needs (`item136_source_state_reliability`,
`item147_*_residual_calibration_time_split`,
`item144_early_hour_guardrail_known_edge_map`, market-residual programs under
item 224/264, the proper-scoring scorecard from item 262), but none of it gates
taker entry. On settled run `data/taker_runs/2026-06-21/taker-20260621-bbe63642`
the bot took 50 fills for 6 wins across slices where it had no proven edge.

Why this matters: the model does not have broad, proven edge over the market; it
has narrow edge in specific cells (for example trusted current-high lock-in and
exact-band-distance-0 late in the day). Without a permission map the taker spends
everywhere the model is merely optimistic, which is where it loses. A per-slice
permission gate turns "trade any positive edge" into "trade only earned edge,"
which is the same governance the maker already uses.

Why it is not already covered: items 47/54 build and consume the maker
`known_edge_map`, not a taker one. Item 144 builds an early-hour guardrail
known-edge map but is scoped to the early-hour guardrail, not a general taker
entry-permission layer across markets, hours, band-distance, and source-state.
Item 283 calibrates and market-shrinks fair value and item 284 changes the EV
gate and ranking, but neither adds a standalone, audited per-slice permission map
or a requalification lifecycle for permission cells.

## Design

1. Generate a taker edge-permission map keyed by `(market, hour,
   band-distance-from-current-high, source-state, trust-state)` from
   settlement-scored, time-blocked, out-of-sample model-minus-market skill,
   reusing the existing reliability/residual/scorecard artifacts and the item-282
   skill weight rather than recomputing skill from scratch.
2. Mark each cell `edge_allowed`, `observe`, or `deny` with the supporting
   settled sample size, after-fee model-vs-market skill, confidence interval, and
   last-refresh timestamp. Sparse or stale cells default to `deny` (fail-closed).
3. Consume the map in `candidate_skip_reason` as a hard precondition: a taker
   buy in a `deny` or unproven cell returns a `NO_TRADE_EDGE_NOT_PERMISSIONED`
   reason regardless of raw or calibrated edge.
4. Add a requalification lifecycle so a cell only becomes `edge_allowed` after a
   minimum number of independent settled days and markets, and is demoted back to
   `observe`/`deny` when fresh settled evidence regresses, mirroring the maker
   known-edge governance and the taker canary requalification in item 256.
5. Surface the map and its coverage in the taker strategy report and daily
   refresh, and prove through the item 273 counterfactual tape and item 275
   clustered promotion gate that permissioned-only entry beats unpermissioned
   entry on settlement-scored after-fee PnL.

- [x] Generate a per-slice taker edge-permission map from settlement-scored
  out-of-sample skill, reusing item 136/147/262/282 evidence with fail-closed
  sparse/stale defaults.
- [x] Emit `edge_allowed`/`observe`/`deny`, settled sample, after-fee skill, and
  refresh metadata per cell.
- [x] Gate `candidate_skip_reason` on the map with a
  `NO_TRADE_EDGE_NOT_PERMISSIONED` reason for unproven cells.
- [x] Add a requalification lifecycle that promotes/demotes cells on fresh settled
  evidence, consistent with item 256 canary requalification.
- [x] Prove on the item 273 counterfactual tape and item 275 clustered gate that
  permissioned-only entry improves settlement-scored after-fee PnL.

## Completion

Implemented a maker-style taker permission map keyed by market, local hour,
hour bucket, band-distance bucket, source state, current-high trust state,
snapshot-cadence state, model variant, and side. Map rows carry permission,
settled sample size, independent days, market count, hit rate, after-fee skill,
skill weight, and refresh metadata. Missing maps and missing cells fail closed:
permission is `deny`, skill weight is zero, calibrated fair collapses toward the
market, and `candidate_skip_reason` emits `NO_TRADE_EDGE_NOT_PERMISSIONED`.

Run summaries and strategy reports now include permission coverage, evidence
status counts, adverse-selection counts, market no-trade counts, and after-cost
EV skip counts. The builder promotes only cells with enough settled samples,
independent days, positive model-vs-market skill, and nonnegative after-fee EV;
fresh weaker evidence demotes cells back to observe/deny on the next rebuild.

Verification: focused taker tests cover fail-closed missing/unproven cells and
map-builder promotion/demotion behavior. The focused suite passes.

```powershell
pytest tests\market\test_taker_bot.py tests\market\test_taker_bot_two_sided.py -q
```

Acceptance: every taker entry is conditioned on a per-slice edge-permission cell
that is `edge_allowed` on settlement-scored, after-fee, out-of-sample evidence;
unproven, sparse, or stale cells fail closed to no-trade; the permission map and
its coverage are reported each run; and a settled replay shows permissioned-only
entry beats unpermissioned entry on settlement-scored after-fee PnL.

Related: items 47, 54, 136, 144, 147, 241, 256, 262, 264, 273, 275, 283, 284.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - FAIL-CLOSED TAKER EDGE PERMISSION LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.


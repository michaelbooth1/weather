# 192. Taker Active-Policy Warm-Tail Kill Switch And Arm Cutover [COMPLETE 2026-06-21 - ACTIVE DEFAULT CUT TO LOW-PRICE TAIL-CAPPED ARM]

Goal: prevent the active-paper taker bot from spending on raw model warm-tail
edges in known weak slots until a settlement-scored strategy arm is promoted
and enforced as the active default.

Source: the settled 2026-06-20 log audit. The active taker run
`taker-20260620-3d3450f0` filled 50 raw-edge buys, spent `66.9901` USDC, and
settled all 50 to zero payout for `-66.9901` USDC net P&L. The losses clustered
in Toronto, NYC, Atlanta, and Miami, with 12 fills at local hour 07 and 38 fills
at local hour 09. At the fill snapshots the bot bought warmer bands while the
market was usually more centered on the eventual winning band; for example,
Toronto bought `24 C` at model `45.2%` / ask `41.0%` while the final `23 C`
band had model `7.5%` and market `39.5%`.

The refreshed full-tape strategy bakeoff over 131,857 input rows blocked
`raw_edge_control` at about `-64.6` USDC settled net P&L, while
`calibrated_edge` mechanically passed at `+1.9` USDC and
`low_price_tail_capped` mechanically passed at `+5.7` USDC. The global
`partial_target_date_labels` blocker still prevents promotion from this day
alone, but it is enough evidence that the active raw-edge default should not
continue without an explicit arm cutover decision.

Why this matters: items 166 and 167 added settlement-scored bakeoffs and
risk-adjusted sizing, but the active-paper default still allowed raw-edge
warm-tail exposure on a day where the model trailed the market. A trading bot
needs the promotion gate and the runtime policy to agree; otherwise completed
research controls do not protect the live-shadow run.

## Design

1. Make the active taker policy load a named strategy arm from the
   settlement-scored bakeoff registry, not an implicit raw-edge control.
2. Add a weak-slot kill switch using the current 10-minute watchlist and hourly
   gate status; block or sharply cap warm-side buys during failing local slots.
3. Add a market-centered warm-tail guard: if the model-favored buy is above the
   market modal/market-centered band cluster, require reliability-adjusted edge,
   candidate-arm approval, fresh CLOB continuity, and a small tail budget.
4. Prevent repeated same-snapshot and adjacent warm-tail cluster fills unless a
   new observation, material price improvement, or passed strategy arm justifies
   the additional exposure.
5. Extend daily taker finalization to compare the active default against the
   best passed bakeoff arm and block the next active-paper run when the active
   default loses to a safer arm on settled evidence.

- [x] Add active strategy-arm selection to taker run config and reports.
- [x] Wire the 10-minute weak-slot and hourly performance gates into taker
  decision rows as hard block/cap inputs.
- [x] Implement market-centered warm-tail distance and adjacent-cluster caps for
  C and F market bands.
- [x] Replay 2026-06-20 through the active policy candidate and prove the
  warm-tail loss is blocked or materially capped versus `-66.9901` USDC.
- [x] Add tests covering the June 20 Toronto/NYC/Atlanta/Miami fill pattern and
  the active-arm cutover guard.

Acceptance: the active-paper taker bot cannot run a raw-edge default when the
settlement-scored bakeoff has not promoted it, June 20 warm-tail fills are
blocked or capped in replay, and daily reports show the active arm, weak-slot
gate state, warm-tail kill-switch decisions, and next-run promotion/block
status.

Completion note 2026-06-21: active taker defaults now resolve to
`low_price_tail_capped`, run configs/reports carry active strategy and
performance-gate state, and taker finalization blocks unsafe raw-edge next-run
policy use when settled bakeoff evidence does not promote it. The 2026-06-20
low-tail replay capped loss to `-3.00` USDC versus the original `-66.9901`
USDC. Focused taker and daily-roll tests pass.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - ACTIVE DEFAULT CUT TO LOW-PRICE TAIL-CAPPED ARM`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.


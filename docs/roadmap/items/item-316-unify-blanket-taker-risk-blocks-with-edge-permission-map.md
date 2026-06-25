# 316. Unify The Blanket Tail/Warm/Weak-Slot Taker Blocks With The Per-Slice Edge-Permission Map [OPEN 2026-06-25 - BLANKET BLOCK-ALL TAIL/WARM/WEAK GUARDS IGNORE THE PROVEN-EDGE MAP]

Goal: replace the blunt "block all tails, warm-tails, and weak slots for every
strategy" guards with a data-driven rule that defers to the per-slice
edge-permission map, so a slice trades exactly when it has proven settlement-
positive out-of-sample edge and is blocked otherwise - instead of a permanent
blanket block.

Source: 2026-06-25 gate audit. `weather.market.taker_bot_strategy_registry` sets
`bad_tail_no_go_block_strategy_families="*"`,
`weak_slot_guard_block_strategy_families="*"`, and
`market_centered_warm_tail_block_strategy_families="*"` - blanket blocks on all
tails, warm-tails, and weak slots regardless of proven edge. These were the
correct short-term response to the taker's winner's-curse losses (items 192/235/236),
but they are blunt: they cannot distinguish a proven-positive slice from a losing
one. Items 283-285 built the calibrated fair value and the per-slice
edge-permission map that can distinguish them, yet the guards still fire as
universal blocks independent of that map.

Why this matters: a permanent blanket `*` block means the bot can never trade
even a slice with repeated settlement-positive out-of-sample evidence - it
permanently trades nothing in those families, so the calibration and permission
machinery built in 283-285 cannot actually unlock any earned edge. The long-term
solution is "block unless the permission map proves it," which stays fail-closed
(nothing proven means still blocked) while letting proven edge through. This is a
concrete case of a shortcut guard substituting for the harder calibrated control.

Why it is not already covered: item 285 builds the edge-permission map and gates
entry on it; items 192/235/236 own the tail/warm guards. But the guards still
apply blanket `*` blocks that fire even on a permission-allowed slice, so the two
controls are not unified. No item makes the tail/warm/weak guards consult the
permission map.

## Design

1. Make `bad_tail_no_go`, `market_centered_warm_tail`, and `weak_slot_guard`
   consult the edge-permission map: a slice in these families is permitted only
   if the map marks it `edge_allowed` on settlement-scored, after-fee,
   out-of-sample evidence; otherwise it is blocked (fail-closed).
2. Replace the default `block_strategy_families="*"` with "block unless
   permissioned," removing the hard-coded universal block as the default.
3. Keep the universal block available as an explicit operator kill-switch
   override, not the default state.
4. Govern unblocking with the permission map's promotion/requalification
   lifecycle, so a slice re-blocks automatically if fresh settled evidence
   regresses.
5. Add tests proving an unproven slice stays blocked and a permission-proven
   slice trades through the formerly-blanket guard.

- [ ] Make the tail/warm/weak guards consult the edge-permission map for
  per-slice permission.
- [ ] Replace the default `*` block with "block unless permissioned," keeping an
  explicit kill-switch override.
- [ ] Tie unblocking to the permission map's requalification/demotion lifecycle.
- [ ] Add tests for unproven-slice-blocked and proven-slice-allowed paths.

Acceptance: the tail, warm-tail, and weak-slot taker guards block a slice unless
the per-slice edge-permission map proves settlement-positive out-of-sample edge
for it; the blanket `*` block is no longer the default (an explicit kill-switch
remains); a permission-proven slice trades through the guard while an unproven one
stays blocked; and a slice re-blocks when fresh settled evidence regresses, proven
by tests.

Related: items 167, 192, 235, 236, 283, 284, 285.

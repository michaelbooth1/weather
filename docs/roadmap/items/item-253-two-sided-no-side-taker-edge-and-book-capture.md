# 253. Two-Sided (NO-Side) Taker Edge And Book Capture [COMPLETE 2026-06-22 - NO-SIDE FADE ARM, BOOK CAPTURE, AND SETTLEMENT INVERSION LIVE]

Goal: stop the taker bot from ignoring half of its model's tradeable edge. The
bot is structurally **buy-YES only**; it never takes the NO side of a band the
model thinks the market has **over**priced, even though that is positive expected
value under the same model. Capture the NO-token book and add a gated two-sided
strategy arm so the existing champion/challenger loop can settle whether fading
overpriced bands is profitable.

Source: the 2026-06-22 taker log audit (June 18-22 runs). A code scan of
`src/weather/market/taker_bot_*.py` found no NO-side, sell, or complementary-token
path — every fill is `BUY_EDGE` on the YES token, gated on
`fair_probability - best_ask > min_edge`. The bot acts only when the model says a
band is **under**priced (`fair_yes > ask_yes`) and does nothing when the model
says a band is **over**priced (`fair_yes < market_yes`, i.e. `fair_no > ask_no`),
which is the symmetric, equally-tradeable case.

Why this matters:
- These weather markets routinely spread probability over many warm bands while
  the model concentrates. That structure means there are usually several bands
  the model prices well **below** the market — exactly the NO-side opportunities
  the bot currently discards. On the June 20 warm-bust day the market over-priced
  the high warm bands; a calibrated NO-side fade of those bands is the natural,
  largely uncorrelated complement to the (losing) YES-side warm-tail buys.
- It roughly doubles the edge surface without new model work: the NO-side edge is
  computed from the same `model_probability`.

Why it is not already covered: items 234-241/248-252 gate, recalibrate, fee-model,
and bakeoff the existing **YES-buy** arms. None add the NO side. A roadmap scan
finds two-sided/NO-side trading only under market-making (items 45, 67), not the
taker.

## Data-capture gap (prerequisite)

The taker candidate tape (`orders_long.csv`) logs only the traded token's book
(`clob_token_id`, `best_bid`, `best_ask`, `ask_size_at_best`). It records the
band's `clob_no_token_id` but **not** the NO-token book, so NO-side edge cannot be
measured or replayed today. The CLOB microstructure capture already records both
tokens' books; this item surfaces the NO-token best ask/size into the taker
decision rows so the bakeoff and settlement scoring can evaluate the NO side.

## Design

1. Capture the NO-token best bid/ask/size into the taker candidate decision tape
   alongside the existing YES-token book, with provenance and freshness.
2. Add a gated `fade_overpriced` / `two_sided` strategy arm to the registry that,
   for each band, also evaluates buying the NO token when
   `fair_no - ask_no >= min_edge` under the **same** calibration-confidence,
   current-high-trust, and warm-tail gates as the YES side (items 234, 236).
3. Score the new arm in the daily champion/challenger bakeoff (item 238) and the
   market-benchmark/no-trade scoreboard (item 241); promote only on settlement-
   scored evidence (item 234), never on MTM.
4. Start as a tiny-budget probe with strict per-band caps: NO-side loses exactly
   where the model is overconfident-low, so it must earn budget through repeated
   settled days, like the low-price-tail arm.
5. Add tests for NO-edge computation, the NO-book capture fields, and a fixture
   day where the YES side loses but the NO-side fade of the same overpriced bands
   wins.

- [x] Surface the NO-token book into the taker candidate tape.
- [x] Add the gated two-sided/`fade_overpriced` strategy arm.
- [x] Wire it into the daily bakeoff and the benchmark/no-trade scoreboard.
- [x] Tiny-budget probe + per-band caps + settlement-only promotion.
- [x] Tests including a YES-loses/NO-wins fixture.

## Completion 2026-06-22

Implemented and verified. The taker can now evaluate and (paper) take the NO side
of an over-priced band, scored under the same gates and settlement-only promotion
as the YES-buy arms.

- New module `weather.market.taker_bot_two_sided`:
  - `no_book_fields` captures the NO-token book — a real captured NO book when
    present, else the no-arbitrage complement of the YES book
    (`no_ask = 1 - yes_bid`, `no_bid = 1 - yes_ask`), with a `no_book_source`
    provenance tag.
  - `no_side_input_row` synthesizes a NO-side candidate (`fair -> 1 - fair_yes`,
    book -> NO book, traded token -> NO token, `taker_side=NO_BUY`) that flows
    through the **existing** YES decision/gate pipeline unchanged, so the band
    identity and every current-high / source / warm-tail / continuity gate apply.
  - `no_edge`, `no_buy_settlement_outcome`, `two_sided_enabled` helpers.
- Settlement correctness: `settlement_outcome_for_order` now **inverts** the
  outcome for `side == NO_BUY` (a NO buy on band X wins when settlement is not in
  X). This is the critical payout fix.
- `base_order_row` reads `side` from `input_row.taker_side` (default `YES_BUY`),
  so YES-only behaviour is byte-identical unless an arm enables two-sided.
- `apply_taker_budget` augments the candidate set with synthesized NO-side rows
  only when `two_sided_enabled` is set; the NO rows carry the NO book in their
  standard book columns, so the NO side lands on the candidate tape.
- New gated registry arm `fade_overpriced` (family `two_sided`, status `shadow`,
  `two_sided_enabled=True`, `min_edge=0.08`, tiny per-order/per-token/per-market
  caps, `risk_adjusted_entry_enabled`). As a registry arm it is automatically
  scored by the daily champion/challenger bakeoff (item 238) and the
  market-benchmark/no-trade scoreboard (item 241), and is promotable only on the
  settlement-only quality gate (item 234).
- Tests: `tests/market/test_taker_bot_two_sided.py` (9 cases incl. synthetic vs
  captured NO book, NO-edge sign, candidate synthesis, settlement inversion, the
  YES-loses/NO-wins fixture, and the registered arm). Full `tests/market`
  suite green (183 passed). An end-to-end `apply_taker_budget` check confirms an
  over-priced YES-24 band (fair 0.30 / ask 0.60) is skipped on YES
  (`NO_TRADE_EDGE_TOO_SMALL`) while the NO side is bought (`BUY_EDGE`, fair_no
  0.70 / no_ask 0.45 / edge +0.25) — exactly the edge the YES-only bot discarded.

Follow-on closed by item 257: the taker candidate tape now carries real captured
NO-token best bid/ask/depth provenance when available, and two-sided promotion
or scale-up requires fresh real NO-book depth rather than synthetic complement
depth alone.

Acceptance: the taker can evaluate and (when settlement-scored evidence supports
it) take the NO side of over-priced bands; the NO-token book is captured for
replay; and the two-sided arm competes in the champion/challenger bakeoff under
the same settlement-only quality and risk gates as the YES-buy arms.

Related: items 238, 234, 236, 241, 165, 166, 167, 21; `[[market-making-track]]`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-22 - NO-SIDE FADE ARM, BOOK CAPTURE, AND SETTLEMENT INVERSION LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.


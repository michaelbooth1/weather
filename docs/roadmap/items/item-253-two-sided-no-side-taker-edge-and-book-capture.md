# 253. Two-Sided (NO-Side) Taker Edge And Book Capture [OPEN]

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

- [ ] Surface the NO-token book into the taker candidate tape.
- [ ] Add the gated two-sided/`fade_overpriced` strategy arm.
- [ ] Wire it into the daily bakeoff and the benchmark/no-trade scoreboard.
- [ ] Tiny-budget probe + per-band caps + settlement-only promotion.
- [ ] Tests including a YES-loses/NO-wins fixture.

Acceptance: the taker can evaluate and (when settlement-scored evidence supports
it) take the NO side of over-priced bands; the NO-token book is captured for
replay; and the two-sided arm competes in the champion/challenger bakeoff under
the same settlement-only quality and risk gates as the YES-buy arms.

Related: items 238, 234, 236, 241, 165, 166, 167, 21; `[[market-making-track]]`.

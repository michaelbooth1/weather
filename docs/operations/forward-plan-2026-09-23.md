# Forward plan — 2026-09-23

- **Owns:** the owner's 2026-09-23 two-pillar strategy, the next 30 days of work that follows from it, its kill rules and the
  owner decisions it needs.
- **Read when:** choosing the next mission, writing a handoff, or deciding whether a piece of work serves the strategy.
- **Do not use for:** today's state (`STATE_OF_PLAY.md`), measured results (`FINDINGS_DIGEST.md`), or the mechanics of any
  lever (the linked owners). Background: the 2026-09-23 read-only audits (local to the production host, not in Git).

## Strategy (owner, 2026-09-23)

- **Pillar A — forecast.** Make the forecast as good as our own free information allows. Its first money use is **timing**,
  not price: when information arrives and when a band is effectively decided.
- **Pillar B — maker and rewards.** Earn liquidity rewards as a maker and **pull quotes at smart times** (around airport
  observations, NBM and model updates, and bands becoming decided) to avoid informed fills. Pillar B does not need a
  forecast that beats the market.

## What we know (2026-09-23)

- The venue's reward split follows the formula we model: RE-1 session 1 accrued 0.117 against 0.105/0.125 predicted, and
  the venue's own percentage sat within ~10% of ours; YES and NO books mirror (mission 86c, digest).
- Competition is the binding variable: qualifying depth at our levels grew 4x in 40 minutes; selection-time projections decay.
- Taker fee was read as 0 on the public tape (retired 2026-09-24: takers pay `0.05 x p(1-p)`, makers 0, 25% maker rebates; EF §10o); public maker markouts are +0.19 c/share at 5 minutes and -0.43 c to settlement (same-day
  events only, 2026-09-20; `R` not frozen then). **The thesis depends on the rare large informed fill, not the average.**
- The forecast still trails the market (1.44-1.48x morning, higher afternoon); raw NBM beats the served model on morning
  rows; the NBM parser repair (layers 2-3) is built and blocked on disk.
- `info_event_calendar.py` (item 68) already implements pull windows, but only paper `mm_policy` uses it; it assumes METAR
  at :52 for every station, applies observation pulls to T+1/T+2 bands, and has no band-decided or NBM events.

## Next 30 days, in order

1. **Finish RE-1** (now 30 sessions / 60 attempts by 09-30 on the current tip; formal verdicts from 09-26). Originally: a
   full six-hour session at session-1 competition accrues about 0.64, still below the 1-dollar minimum; a payment test may
   need a less contested band or a larger size (owner decision).
2. **Disk** ([storage plan](storage-plan-2026-09-23.md)): inventory by data family, compress-and-retain, Drive archive until
   the daily low holds at 70 GiB or more. Everything that lands waits on this.
3. **NBM layers 2 then 3** in quiet windows once disk allows. Every NBM candidate's forward clock starts on the layer-2 date.
4. **Passive maker-evidence capture** (before the RE-0 poller stops on 09-30): per-minute reward records (stored on change)
   and both-token books for the top ~10 reward bands per local day-ahead 0/1/2, public trades, and 30-minute windows before
   and after each session; order-book update stream capped per day; brakes tied to the storage bands; tens of MB per day.
   Measure the update-stream volume from the tape's discard counter first.
5. **Freeze `R`, then the fill-toxicity desk study** (pre-registered): simulate a slow 20-share quote at ±1.5 c, repriced
   each minute; a fill when public trades print through it; markouts at 1/5/30 minutes and settlement; five
   information-event classes plus placebo windows. Primary estimand: adverse loss per quoted minute inside versus outside
   event windows at 30 minutes, date-clustered. Pulling is supported if the ratio's lower bound is at least 2 and its net
   value is positive; pulling is not the lever if the upper bound is at most 1.5. Same-day tape only until item 4 has
   accumulated T+1/T+2 dates.
6. **Timing outputs from the forecast stack** (pillar A serving pillar B): T1, the observation and guidance clock per station
   (measured METAR minutes; NBM 01/07/13/19Z); T3, the probability a band is already decided. Evaluate against a clock-only
   baseline, then as a pre-registered withdraw-policy counterfactual (markout avoided versus reward minutes lost).
7. **Statistics canon repair:** date-clustered inference with markets fixed for decisions (the crossed design as a
   sensitivity); retire the 98.88/1.12 citations and the ~504-date requirement (neither 504 nor 39 is citable); fee (EF §10o)
   amendment; two-tier ship rule (owner decision).
8. **Forecast candidates in forward shadow:** a zero-parameter baseline board (raw NBM with the observed floor, all day, plus
   a rolling per-market centre correction), then a pooled guidance-anchored residual model with state-dependent spread.
9. **Live-path qualification kit** (mission 87a) adopted after RE-1, with PR 85's execution modules under their own roll
   verdict.
10. **Settlement hardening:** land the signed band parser (`016e1c92c`, rebased as 95b `codex/signed-band-parser-20260924`) before Toronto's first sub-zero high; add a
    resolution-source change alarm.

## Kill rules

- **K1 (pillar B):** the best pull policy's net value per band-day has a date-clustered upper bound below zero: stop the
  maker build and keep capture only.
- **K2:** the median settled reward on T+1 bands at a size we can fund is below the owner's floor (to be set): stop.
- **K3:** once quoting, realized fill losses exceed twice the shadow prediction: pause and re-derive.
- The RE-1 stop rule as restated in the [addendum](../research/liquidity-reward-epoch-addendum-2026-09-23.md).

## Owner decisions

Decided 2026-09-23:

1. **`R` frozen as a rule, computed later** — [fill-toxicity-R-rule-2026-09-23.md](../research/fill-toxicity-R-rule-2026-09-23.md).
2. **Passive maker-evidence capture approved** (item 4 above; sized for the disk, brakes on the storage bands).
3. **K2's dollars-per-band-day floor is deferred** until the capture and sessions give data; K2 is inactive until set.
4. **Payment tests may use any band and any size**, within the dedicated testing wallet: **100 pUSD total, all of it for
   testing** (later: wallet guard 200; cap 10 sessions/20 attempts on 09-23, then 30/60 on 09-24; end date stays; DECISION_LOG). A size or selection change is a new dated pre-registration and a new
   code tip with a fresh owner preflight; owner later the same day moved session 2 onto the 84h tip `1310ca6bf` (more data is worth the balance).
5. **One multi-domain market maker** (owner 2026-09-24): weather first, then YouTube view markets and other reward markets.
   Build the shared foundation (venue, market-universe plugins, fair-value/information-clock plugins, one quoting engine,
   portfolio risk, execution safety) and migrate **before RE-2 or unattended quoting**. Mission 90a (2026-09-24,
   `origin/codex/maker-architecture-map-20260924` @ `2cb8a0a0e`) maps the code and gives a gated ten-step migration plus the
   review checklist every maker handoff must pass; five owner decisions precede the implementation handoff (base, caps,
   quoting without fair value, emergency-cancel scope, RE-2/unattended criteria).
   The workstation carries implementation and research whenever no RE-1 session is running. **Standing design rule:** new
   maker code (venue, pricing, repricing, risk, execution, evidence) is domain-neutral; weather specifics enter only through a
   market-universe or fair-value/information-clock interface. YouTube has no model ready and no maker logic yet: it is a
   future plugin, not an input to current work.

Decided 2026-09-24: RE-1 and the maker migration are judged by the owner as results arrive — no pre-registered pooled
verdict rule and no migration gates (second-opinion audit findings 2 and 11 declined). Still open: the two-tier ship rule and closing the α ledger as historical; later, RE-2 authorization and whether unattended
quoting is wanted at all.

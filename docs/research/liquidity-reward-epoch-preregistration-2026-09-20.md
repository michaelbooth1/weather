# Liquidity-reward epoch RE-1 - pre-registration (2026-09-20)

Status: **FROZEN BEFORE ANY LIVE ORDER. NOT AUTHORIZED.** This document designs one bounded live
measurement. It grants no authority: `docs/operations/STATE_OF_PLAY.md` "Current authority" decides
whether anything may run, and today it says no live trading. Every ceiling change named here is a
proposal awaiting a dated owner decision. International Polymarket only. Native unit pUSD.
Parent plan: [item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md) W3/W4/W6.
Safety protocol: [the live pilot runbook](../operations/INTERNATIONAL_MM_LIVE_PILOT.md), unchanged
except where "Envelope changes requested" says so.

## Question

Does the venue **pay** liquidity rewards to a small two-sided quoter on a weather temperature band,
in what unit, and at what fraction `k` of what our desk model predicts for the same minutes?

Both desk studies (item 330, 2026-09-20) stop at the same three unverified assumptions:

| | Assumption the desk model makes | How RE-1 tests it |
| --- | --- | --- |
| U1 | `rate_per_day` is pUSD per UTC day, paid out | Earnings row and wallet credit for the session's UTC day |
| U2 | Our share of a band's pool is `Q_own / (Q_own + Q_displayed competitors)` | Paid amount divided by the model's prediction for the same resting minutes |
| U3 | A 20-share maker is eligible and clears the payout minimum | Venue order-scoring status during the session; a payment arriving at all |

A configured pool of about 2,800 per day with thin displayed competition is the kind of free money
that is normally competed away. The prior is that the model is missing something. RE-1 exists to
find out what, for about 20 pUSD of reserved capital.

## Treatment (frozen)

- **One condition** (one temperature band of one event), chosen by the mechanical rule below.
- **Two resting post-only GTC limit BUYs**, the two-sided quote expressed as backed buys:
  YES at `mid - d` and NO at `(1 - mid) - d`, each rounded **away** from the midpoint to the tick.
  Size of each leg = the band's `rewards_min_size` (20 shares). No sell orders of any kind.
- **Distance** `d`: target 2 cents. A leg is left alone while it rests between 1.0 and 3.5 cents
  from the current midpoint (reward maximum spread is 4.5). It is cancelled and replaced only when
  it leaves that window. Minimum 60 s between voluntary re-quotes. Every resting quote is
  re-validated against a fresh book at least every 120 s (the existing TTL becomes a staleness
  bound, not an order lifetime). A post-only rejection is never chased: wait one cycle and
  recompute; three consecutive rejections end the session.
- **Duration**: 120 minutes of quoting, end time fixed and journaled before the first order.
- **Fill policy**: the first fill event of any lifecycle state on either leg ends quoting:
  cancel-all, reconcile, hold the inventory to settlement. No taker exit, no flattening, no
  re-entry. Rewards accrued up to that minute still count. Maximum inventory is one leg.
- **Dead-man**: exchange heartbeat at 5 s cadence for the whole session, as in Stage 1. Any missed
  acknowledgment, user-stream silence, stale book, geoblock change or reconciliation mismatch is
  the runbook's cancel-all-and-stop.
- **Capital**: both legs reserve `20 x (1 - 2d)` = 19.2 to 19.6 pUSD. With the midpoint restricted
  to 0.20-0.80 one leg costs at most 15.6. Worst case (one leg fills, resolves against us):
  15.6 pUSD. Both legs filling is a locked profit of `20 x 2d`. Expected trading cost if filled,
  from the public tape: about 0.43 c per share held to settlement, that is about 0.09 pUSD, with a
  binary spread of several pUSD around it.

## Selection rule (frozen, mechanical, run 30 minutes before launch)

Inputs: a fresh International economics snapshot and live books. No human picks the band; the
attending owner may only veto the whole session.

1. Universe: rewarded conditions of the configured events with `rewards_min_size <= 20`,
   `rate_per_day >= 40`, `rewards_max_spread >= 3` cents, event date today or tomorrow market-local.
2. Filters: two-sided book; displayed spread <= 6 cents; midpoint within 0.20-0.80; tick 0.01;
   no active information-event gate; for a same-day band, market-local time earlier than 09:00.
3. Rank: same-day before next-day; then location in the frozen order `los-angeles, seattle,
   san-francisco, denver`, then every other location; then highest `rate_per_day`.
4. Take the first row. Journal the full ranked table and its hash before credentials are resolved.

Why that order: the launch slot is early morning Eastern, which is pre-dawn in the western
markets, hours before the day's high is informed by observations; and those four carry the least
adverse short-horizon markout on the 30-date public tape. Same-day 20-share bands rotate between
cities from day to day (Atlanta and Los Angeles on 09-16, Denver on 09-17, Austin and Seattle on
09-20), so a named city cannot be frozen in advance. Every next-day event carries 20-share bands
at about 100 per day per event, so the fallback `next-day Los Angeles, highest-rate band` always
exists.

## Measurements

| | What | Source | When |
| --- | --- | --- | --- |
| M1 | Venue says each leg is scoring | authenticated order-scoring status | every 60 s |
| M2 | Venue-stated reward percentage for the condition, if the interface exists | authenticated rewards percentages | every 60 s |
| M3 | Modelled share for each resting minute, `single` and `many` bounds | `weather.market.reward_share_estimate` formulas on the captured public book with our actual resting prices | after the session |
| M4 | Earnings row for the condition and UTC day; total earnings; wallet pUSD delta; asset address | authenticated user earnings, balance reads, the cash identity of the runbook's Stage 3 | on a later UTC date |
| M5 | Fills, fees, markouts at 1, 5, 30 minutes and settlement | user stream, REST, public capture | as they occur |
| M6 | Minutes with both legs resting, re-quotes, rejections, heartbeat gaps | session journal | continuous |

## Frozen prediction and decision rule

At session end, **before any payout can be known**, compute and hash
`P_many` and `P_single` = sum over two-sided resting minutes of `rate_per_day / 1440 x share`.
Planning value: rate 50-90 per day, 120 minutes, share 0.3-0.5 gives **1.3 to 3.8 pUSD**.
The payout minimum is 1 pUSD. `k = paid / P_many`.

| Verdict | Condition | Pre-committed consequence |
| --- | --- | --- |
| `PAID_AS_MODELLED` | `k >= 0.5` | Proceed to RE-2 (below). Desk model stands, scaled by `k`. |
| `PAID_DILUTED` | `0.1 <= k < 0.5` | Rescale the desk model by `k`; proceed to RE-2 only if the rescaled economics clear `H`. |
| `NOT_PAID` | paid = 0, M1 true on >= 80% of resting minutes, `P_many >= 2.0` | The desk model is wrong by more than the payout minimum can explain. No further live work on this thesis without a named mechanism. |
| `INCONCLUSIVE` | anything else: `P_many < 2.0` with no payment, M1 false, under 60 two-sided minutes, campaign changed mid-session, evidence incomplete | One re-run per named cause. RE-1 is capped at **three sessions in total**, every one reported. |

M2, when available, is reported beside `k` as `k_share` = venue percentage / modelled share. It is
descriptive: it cannot turn `NOT_PAID` into a pass, but it is the fastest reading of U2 and does
not depend on the payout minimum.

**RE-2**, only after a paid verdict and a new dated owner authorization: the W6 calibration
cohort - same treatment, up to three bands, at most five attended sessions and two payout cycles
inside fourteen days. `R` (execution-tape markout pre-registration) is frozen from RE-2's paid
reward per filled share before anyone re-reads the markout numbers.

**Hurdle and stop (owner to set; defaults proposed):** `H` = 1.00 pUSD net per day per 100 pUSD
deployed across the RE-2 cohort, trading losses included. **If no epoch has returned a paid
verdict by 2026-10-31, the maker track closes** and the project reverts to cheap capture only,
pending an owner decision on whether it continues at all.

## What this cannot show

Zero or one fill says nothing about adverse selection on our own quotes. One band on one morning
does not generalize to 100-share bands, to afternoon hours, or to other days' competition. A paid
reward is feasibility evidence, never `PROFITABLE`
([pilot preregistration](INTERNATIONAL_MM_PILOT_PREREGISTRATION.md) claim boundary applies in full).
Every session is reported, including zero-payment and aborted ones.

## Envelope changes requested (each needs a dated owner decision)

| Ceiling | Today | Requested for RE-1 | Why |
| --- | --- | --- | --- |
| Per-order notional | 10 | **16** | A 20-share leg costs up to 15.6 with the midpoint in 0.20-0.80 |
| Per-band notional | 10 | **20** | Two 20-share legs reserve 19.2-19.6 |
| Per-event notional | 25 | 25 (unchanged) | One band |
| Daily loss | 25 | 25 (unchanged) | Worst case 15.6 |
| Wallet | 100 | 100 (unchanged); **dedicated wallet, funded 50-100** | Keeps the isolated-wallet control on `master`; makes reward and cash attribution unambiguous |
| Quote lifetime | one 120 s TTL | **one 120-minute session**, quotes re-validated every <= 120 s, heartbeat dead-man throughout | Rewards are sampled per minute; one TTL is two samples |
| Order count | one or two | two resting at any time; at most **40 submits** per session | Bounds re-quoting |

Unchanged: post-only, no naked sell, no retry on an ambiguous response, attended, typed
eligibility and stage confirmations, geoblock check before credentials and before the first
submit, home tunnel down, cancel-all to zero and position reconciliation at the end.

## Update rule

Changing the treatment, selection rule, prediction formula, verdict thresholds or session cap
after the first RE-1 order creates a new dated pre-registration. This one remains the
interpretation contract for every order placed under it.

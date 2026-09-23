# Liquidity-reward epoch RE-1 - pre-registration (2026-09-20)

Status: **FROZEN BEFORE ANY LIVE ORDER. NOT AUTHORIZED.** This document designs one bounded live
measurement. It grants no authority: `docs/operations/STATE_OF_PLAY.md` "Current authority" decides
whether anything may run, and today it says no live trading. International Polymarket only.
Parent plan: [item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md) W3/W4/W6.
Safety protocol for any repository-run order: [the live pilot runbook](../operations/INTERNATIONAL_MM_LIVE_PILOT.md).

## Question

Does the venue **pay** liquidity rewards to a small two-sided quoter on a weather temperature band,
in what asset, and at what fraction `k` of what our desk model predicts for the same minutes?

| | Assumption the desk model makes | How RE-1 tests it |
| --- | --- | --- |
| U1 | `rate_per_day` is dollars per UTC day, paid out | Earnings row and wallet credit for the session's UTC day |
| U2 | Our share of a band's pool is `Q_own / (Q_own + Q_displayed competitors)` | Paid (or accrued) amount divided by the model's prediction for the same resting minutes |
| U3 | A 20-share maker is eligible and clears the 1-dollar payout minimum | The venue marking the orders as scoring; a payment arriving at all |

A configured pool of about 2,800 per day with thin displayed competition is the kind of free money
that is normally competed away. The prior is that the model is missing something. RE-1 exists to
find out what, for about 20 dollars of reserved capital.

## What public reads already showed (2026-09-20, no order, no credential)

The venue publishes a reward record per condition (`GET /rewards/markets/<condition_id>`) with a
`market_competitiveness` number this project had never captured.

- **Same-day bands:** competitiveness was 0 on five of eight read at about 15:50Z, including the two
  largest (Los Angeles 220 per day, New York 193 per day). Its definition is unverified and it is
  **not** our competing Q-score in other units: on next-day bands it read 0.01-0.17 where the book
  gives a competing Q of 10-30, and 2-4 where the book gives 100-400. Treat it as ordinal at most.
- **Reward settings move during the day.** Seattle 70-71 read 92 per day with a 20-share minimum in
  our 14:02Z snapshot and 113 per day with a **100-share minimum** two hours later; Austin flipped
  the same way. Per-band rates drift as the event pool follows the favoured bands. **Same-day
  20-share bands are a morning transient, not a population**: the desk estimate of 71-158 per day
  for them rests on a static daily rate and is too high. Next-day bands kept a 20-share minimum.
- **Next-day bands are contested.** Scoring live books with the estimator's own formulas, a
  two-sided 20-share quote 1.5-2 cents out would hold a share of **0.01-0.10 in ten of twelve
  cities and 0.18-0.34 only in Los Angeles**. At 40-54 per day per band that is 0.5-6 dollars per
  band per day, not 70-150.
- The per-condition record names reward asset `0x2791...4174`; `/rewards/markets/current` names
  `0xC011...2DFB`. Which asset is credited is part of U1.

**RE-0 (running since 2026-09-20, zero risk, ends by itself 2026-09-30):** a credential-free poll of
the reward record for every rewarded weather band every 15 minutes, and an hourly dry run of the
selection rule below, to host-local folders on the capture host. By launch they give rate, minimum
size, competitiveness and modelled share by band and hour. They select nothing.

## Treatment (frozen)

- **One condition** (one temperature band of one event), chosen by the mechanical rule below.
- **Two resting limit BUYs**, the two-sided quote expressed as backed buys: YES at `mid - d` and NO
  at `(1 - mid) - d`, each snapped **away** from the midpoint to the tick. Size of each leg = the
  band's reward minimum (20 shares). No sell orders of any kind. Post-only wherever the interface
  offers it; never a marketable price.
- **Distance** `d`: target 1.5 cents (so 1.5 or 2.0 after snapping). A leg is left alone while it
  rests 1.0-3.0 cents from the current midpoint (reward maximum spread is 4.5); it is cancelled and
  replaced only when it leaves that window, at most **four re-quotes** per session.
- **Duration**: 360 minutes of quoting inside one UTC day, end time fixed before the first order.
  Two hours at these shares predicts less than the 1-dollar payout minimum and could not be read.
- **Fill policy**: the first fill on either leg ends quoting: cancel the other leg, hold the
  inventory to settlement. No taker exit, no re-entry. Rewards accrued to that minute still count.
- **Stop at once** if the band's reward minimum rises above 20 shares, the rate falls below 40, the
  book goes one-sided, or the venue's geoblock state changes (home tunnel stays down throughout).
- **Capital**: both legs reserve `20 x (1 - 2d)` = about 19.4 dollars. Midpoint restricted to
  0.20-0.80, so one leg costs at most 15.8. Worst case (one leg fills and resolves against us):
  15.8. Both legs filling is a locked profit of `20 x 2d`. Expected trading cost if one leg fills,
  from the public tape: about 0.43 c per share held to settlement, about 0.09 dollars, with a
  binary spread of several dollars around it.

## Selection rule (frozen, mechanical, run 30 minutes before launch)

Inputs: the venue's live per-condition reward record and live books. No human picks the band; the
attending owner may only veto the whole session. Implementation: `re1_select.js` (public reads).

1. Universe: rewarded conditions of the configured events for **tomorrow's** event date with
   reward minimum <= 20 shares, rate >= 40 per day, reward maximum spread >= 3 cents. Same-day
   bands are excluded: their minimum flips to 100 shares during the morning, stranding the quote.
2. Filters: two-sided book; displayed spread <= 6 cents; midpoint within 0.20-0.80; tick 0.01.
3. Score each survivor with the estimator's formulas at the treatment's prices against the live
   book and compute `predicted = rate / 1440 x 360 x share_many`. Require `predicted >= 2.0`.
4. Rank by `predicted`, highest first; ties by the frozen location order `los-angeles, seattle,
   san-francisco, denver`, then condition id. Take the first row. Save the full table and its
   SHA-256 before the first order. **No survivor means no session that day.**

Expected pick, from every dry run so far: **next-day Los Angeles, one of the two central bands.**
Los Angeles also has the only all-positive short-horizon maker markout on the 30-date public tape
(5 minutes +0.19 to +0.47 c; 30 minutes +0.07 to +0.58 c).

## Measurements

| | What | Source | When |
| --- | --- | --- | --- |
| M1 | Venue marks each leg as scoring | order-scoring status (interface: the rewards indicator on the order; API: `get_orders_scoring`) | at placement, then every 30-60 minutes |
| M2 | Venue-stated earning percentage and accrued earnings for the condition | the account's rewards page; API: `list_user_earnings_and_markets_config`, `get_reward_percentages` | during and at the end of the session |
| M3 | Modelled share for each resting minute, `single` and `many` bounds, with our own size removed from the level it sits on | `re1_watch.js`: live reward record and book each minute, estimator formulas | continuous |
| M4 | Earnings row for the condition and UTC day; total earnings; wallet delta in **both** candidate assets | rewards page or `list_user_earnings_for_day`; balances before, after, and after the payout | on a later UTC date |
| M5 | Fills, fees, markouts at 1, 5, 30 minutes and settlement | account history; public capture | as they occur |
| M6 | Minutes with both legs visible in the public book, re-quotes, alerts | `re1_watch.js` journal | continuous |

The pinned SDK (`polymarket-client` 0.6.0) already exposes every authenticated reader named above;
none is wired into this repository yet.

## Frozen prediction and decision rule

> **Amended 2026-09-23 (owner-approved, before any payment was observable):** see
> [the interpretation addendum](liquidity-reward-epoch-addendum-2026-09-23.md) — `BELOW_PAYOUT_MINIMUM`, both reward
> assets, graded adequacy, and a restated stop rule. Every session is reported under both.

`re1_watch.js` accumulates `P_many` and `P_single` = sum over minutes in which both legs are visible
of `rate(t) / 1440 x share(t)`, and at session end writes them with the journal's SHA-256 - before
any payout can be known. Planning value from the 2026-09-20 dry runs: **2.4 to 3.5 dollars.**
`k = paid / P_many`.

| Verdict | Condition | Pre-committed consequence |
| --- | --- | --- |
| `PAID_AS_MODELLED` | `k >= 0.5` | The desk model stands, scaled by `k`. Go to RE-2. |
| `PAID_DILUTED` | `0.1 <= k < 0.5` | Rescale the desk model by `k`; RE-2 only if the rescaled economics clear `H`. |
| `NOT_PAID` | paid = 0, legs marked scoring, `P_many >= 2.0` | The model is wrong by more than the payout minimum can explain. No further live work on this thesis without a named mechanism. |
| `INCONCLUSIVE` | anything else: `P_many < 2.0` with no payment, legs never marked scoring, under 180 visible two-sided minutes, reward settings changed mid-session, evidence incomplete | One re-run per named cause. RE-1 is capped at **three sessions in total**, every one reported. |

**Reward day (owner, from use, 2026-09-22):** the venue's liquidity rewards reset and are paid daily at 20:00
Eastern, i.e. 00:00 UTC in daylight time - the reward day is the UTC day. Session 1 (started about 01:40Z
2026-09-23) lies wholly inside reward day 2026-09-23 and its payment is expected at 00:00Z 2026-09-24. A second
session in the same UTC day adds to the same daily total and the same payment only if it quotes the **same
condition**; earnings on any other condition that day make `link_reward_payment` stop at
`other_condition_accruals` (`re1_payout_evidence.py`), so the day cannot be linked.

M2's accrued earnings, if the venue shows them below the payout minimum, are reported beside `k`
as `k_accrued`. They can sharpen `INCONCLUSIVE`; they cannot turn `NOT_PAID` into a pass.

**RE-2**, only after a paid verdict and a new dated owner authorization: item 330's W6 cohort - the
same treatment on up to three bands, at most five sessions and two payout cycles inside fourteen
days. `R` (execution-tape markout pre-registration) is frozen from RE-2's paid reward per filled
share before anyone re-reads the markout numbers.

**Hurdle and stop (owner set both to these defaults on 2026-09-22, before any RE-1 order):** `H` = 1.00 dollar net per day per 100
deployed across the RE-2 cohort, trading losses included. **If no epoch has returned a paid verdict
by 2026-10-31 the maker track closes** and the project reverts to cheap capture only, pending an
owner decision on whether it continues at all.

## Two ways to execute the same frozen treatment

| | RE-1M - by the owner's hand | RE-1A - by repository code |
| --- | --- | --- |
| What | The owner places the two limit orders in the venue's own interface; `re1_select.js` names the band and both prices, `re1_watch.js` watches the public book and says when to re-quote or stop | A sealed, attended session under the pilot runbook |
| Exists today | Yes. Both tools are written and smoke-tested; they read public data only | **No.** Neither `master` nor the maker candidate can rest a quote: the only submit path is one far-from-mid order per sealed stage, one token per adapter, a single-use capability burned before signing, a 240-second session ceiling, a 60-second geoblock receipt, a sealer that rejects anything named stage 2, no re-quote loop, no reward-aware pricer, no network reader for earnings or order scoring |
| Build | None | Two-token adapter; budgeted multi-submit capability; stage-2 runner, template and sealer stage; mid-relative pricer; re-quote loop with heartbeat; a long-session profile with in-loop geoblock refresh; seven cap sites and six ratchet tests; earnings and order-scoring readers. Several weeks at this project's landing rate, all of it safety-critical |
| Controls | Size only: about 19 dollars reserved, 15.8 worst case. No dead-man heartbeat, no sealed journal; evidence is the public-book journal plus the account's own history and rewards page | Every runbook control, plus the envelope changes below |
| Authority | The owner's own action on the owner's own account. It is outside the repository's staged protocol and proves nothing about that protocol | A dated Stage authorization in `STATE_OF_PLAY.md` |

**Order of work: RE-1M first.** It answers U1-U3 in days for the price of a lunch, and its answer
decides whether the RE-1A build is worth starting. Building a quoting engine to test a thesis that
one afternoon can kill would repeat the pattern the 2026-09-18 audit describes.

### Envelope changes RE-1A would need (each a dated owner decision; none needed for RE-1M)

| Ceiling | Today | Requested | Why |
| --- | --- | --- | --- |
| Per-order notional | 10 | **16** | A 20-share leg costs up to 15.8 with the midpoint in 0.20-0.80 |
| Per-band notional | 10 | **20** | Two 20-share legs reserve about 19.4 |
| Per-event 25, daily loss 25, wallet 100 | | unchanged | One band |
| Quote lifetime | one 120 s TTL inside a 240 s session | one 360-minute session, quotes re-validated every <= 120 s, heartbeat dead-man throughout, geoblock receipt refreshed in-loop | Rewards are sampled per minute |
| Submits | one per sealed stage | at most 12 per session | Two legs plus four re-quotes of both |
| Wallet | | dedicated, funded 50-100 | Keeps the isolated-wallet control on `master` |

## What this cannot show

Zero or one fill says nothing about adverse selection on our own quotes. One band on one day does
not generalize to 100-share bands, to same-day bands, or to other days' competition. A paid reward
is feasibility evidence, never `PROFITABLE`
([pilot preregistration](INTERNATIONAL_MM_PILOT_PREREGISTRATION.md) claim boundary applies in full).
Every session is reported, including zero-payment and aborted ones.

## Update rule

Changing the treatment, selection rule, prediction formula, verdict thresholds or session cap after
the first RE-1 order creates a new dated pre-registration. This one remains the interpretation
contract for every order placed under it.

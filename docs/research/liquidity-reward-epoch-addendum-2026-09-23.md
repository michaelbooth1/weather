# RE-1 interpretation addendum — 2026-09-23

Status: **owner-approved 2026-09-23, before any RE-1 payment was observable** (session 1's reward day is 2026-09-23 UTC; the
venue pays at 00:00Z 2026-09-24). This addendum amends the verdict interpretation of
[the RE-1 pre-registration](liquidity-reward-epoch-preregistration-2026-09-20.md) under its own update rule (a change
after the first order creates a new dated pre-registration). **It is written after the evidence below was seen, and says
so:** an early accrual reading of about 40% of prediction (owner, ~22:20 ET 09-22), and session 1 ending on a fill
(`reason: fill`, `cleanup_ok: true`, prediction sha256 `be81609a…`). No payment, payout read or `collect-evidence`
output existed when it was written. Session 1 is reported under **both** the frozen table and this addendum.

## Why

A read-only audit (2026-09-23, `MASTER_AUDIT.md` findings D4-01..D4-05, traced against `0a7531baf`) found that the
frozen table measures the plumbing more than the payout:

1. **False NOT_PAID.** `payout_verdict` (`re1_evidence.py`) returns NOT_PAID whenever `paid == 0` and `P_many >= 2`.
   The venue pays nothing below its 1-dollar daily minimum, so any true `k` below about 0.43 on a 2.34 prediction pays
   0 and is scored "the model is wrong by more than the payout minimum can explain" — exactly the case the minimum
   explains. The venue-reported accrual (`k_accrued`) is computed beside it and ignored.
2. **One asset only.** `link_reward_payment` (`re1_payout_evidence.py`) matches pUSD credits only; the per-condition
   reward record names USDC.e as the reward asset. A USDC.e payment could never verify.
3. **All-or-nothing adequacy.** One failed read among ~1,800 unretried requests sets `evidence_complete = false`; any
   intraday reward-rate change sets `reward_terms_changed`, although `P_many` already integrates `rate(t)` per minute.
4. **The 2026-10-31 stop rule** counted every INCONCLUSIVE, including plumbing failures, as "no paid verdict".

## Amended verdicts (per session; `P_many` is already the sum over visible two-sided minutes)

| Verdict | Condition |
| --- | --- |
| `PAID_AS_MODELLED` | adequate, `k = paid / P_many >= 0.5` (unchanged) |
| `PAID_DILUTED` | adequate, `0.1 <= k < 0.5` (unchanged) |
| `BELOW_PAYOUT_MINIMUM` | `paid = 0` and the venue-reported earnings for the reward day, all conditions, are below 1 dollar. Judged on `k_accrued = accrued / P_many` with the same bands: `ACCRUED_AS_MODELLED` (≥ 0.5), `ACCRUED_DILUTED` (0.1–0.5), `ACCRUED_LOW` (< 0.1). |
| `NOT_PAID` | adequate, legs marked scoring, venue-reported earnings for the day **≥ 1 dollar**, and `paid = 0` by the end of the D..D+3 window; **or** venue-reported earnings exactly 0 while at least 180 two-sided scoring minutes were observed. |
| `INCONCLUSIVE` | anything else (named cause, one re-run per cause as before). |

**Payment asset:** a credit in either USDC.e (`0x2791…4174`) or pUSD (`0xC011…2DFB`) counts; the exact-amount,
single-condition, unique-credit rule is otherwise unchanged.

**Adequacy:** a session is adequate if at least 95% of its elapsed minutes have a public-book sample, cleanup is proven,
and neither the reward minimum size nor the maximum spread changed; reward-rate changes are integrated, not voiding.
A session under 180 two-sided minutes (for example ended by a fill) is reported with its `k` / `k_accrued` and flagged
`SHORT`; it is not voided, but a `SHORT` session alone cannot produce `NOT_PAID`.

## Stop rule, restated by the owner

The maker track closes on **`NOT_PAID` in an adequate session**, or on **`k_accrued < 0.1` in two adequate sessions**.
`INCONCLUSIVE`, `SHORT` and `BELOW_PAYOUT_MINIMUM` with `k_accrued >= 0.1` do not count toward closing it. If no adequate
verdict exists by 2026-10-31, the owner reviews the track; it does not close automatically.

## Implementation

**Status:** implemented by mission 84g on `c771cbb42` (accepted 2026-09-23; 255 focused tests); `collect-payout` prints
`verdict_frozen` and `verdict_amended` side by side.

`payout_verdict` and `link_reward_payment` are amended before the first `collect-payout` / `collect-evidence` run for
session 1 (earliest 00:00Z 2026-09-26 under the reconciler's D+3 rule), with the frozen-table result printed beside the
amended one. Nothing in the live quoting path changes. The hurdle `H` and every RE-2 condition are unchanged.

## Venue mechanics from public documentation (research 2026-09-23, not an amendment)

From docs.polymarket.com (liquidity rewards, pUSD, contracts, rewards API) and the Polymarket help centre (article 13364466):
the payout minimum is **1 dollar per UTC day, and earnings below it are not paid and do not roll over** (per-market vs
per-day total not stated); the epoch is the UTC day, paid about midnight UTC (20:00 ET in daylight time, 19:00 ET after
2026-11-01); collateral moved from USDC.e to **pUSD** on 2026-04-28, and pUSD is the expected reward asset (the earnings
API `asset_address` is authoritative); the book is sampled once a minute at a random offset and share = our `Q_min` over all
makers' `Q_min`, summed over the day (the model RE-1 uses); `Q_one` = YES bids + NO asks, `Q_two` = YES asks + NO bids,
single-sided liquidity scores at 1/c (c = 3) only with the midpoint in [0.10, 0.90], two-sided required outside it; an order
must be live for an undocumented minimum duration before it scores. Answered by mission 86c: the YES and NO books mirror (37 of 42 minutes exact;
recomputing from both changed `P_many` by -0.03%). Consequence for session 1: its 0.12 earned is below the minimum and will not
be paid; it is judged on `k_accrued` under this addendum.

# D3 — configured liquidity-reward ceiling (measured 2026-09-19 ~12:30, no network, no python)

**Source:** the project's own `exchange_economics_snapshot.json` — `data/backtest/` (refreshed 2026-09-19 14:08Z) and the
copy each maker daily roll saved under `data/mm_runs/<date>/<run>/` (31 days between 2026-08-15 and 2026-09-19).
Field: `markets[].liquidity_rewards.current_daily_rate_usdc` = sum of `active_configs[].rate_per_day` from
`clob.polymarket.com/rewards/markets/current`; config asset address is the pUSD token. Summed with a 12-line node script.

| | Configured pool per day |
| --- | --- |
| Same-day events (12 events, 35–46 rewarded bands) | **2,800** (200 per event; 400 for NYC and Los Angeles) |
| T+1 events | ~1,200 |
| T+2 events (listed since 08-29) | ~800 |
| **All active** | **~4,800 / day** (4,000 before 08-29) |

Stable every one of the 31 days sampled (2,717–2,830 same-day; one 11-event day at 2,394).
Today: 129 of 352 conditions rewarded; max distance 4.5 cents everywhere; min size 100 shares on 26 same-day bands and
20 shares on the other 15 same-day bands and on every T+1/T+2 band. Per-band rates run 1 → 246 per day.

**What the canonical docs say instead:** `docs/research/MARKET_MAKING_PLAN.md:100-108` — "~$1.00/day per event … Fleet
total ~$16/day … liquidity rewards are a subsidy, not a business" (measured 2026-06-13). Item 330 records the 09-11
inventory (136 allocations) **without a dollar total**. The July `NOT_VIABLE_CURRENT_TRACK` verdict and the zero-edge
sensitivity table (break-even 88.99% "at $1 reward") were computed against that June figure.
**The configured pool is ~175x (same-day) to ~300x (all active) larger than the number the economics case rests on,
and has been for at least five weeks.** Nobody summed the column.

**What this is NOT:** a receivable. The pool is split among all makers by Q-score share (size x closeness to the
adjusted midpoint, sampled each minute; two-sided required outside 0.10–0.90; single-sided divided by 3 inside). No paid
reward has ever been observed by this project (`actual_payout_evidence: false`). Unit/asset of `rate_per_day` should be
confirmed against one paid epoch before it is treated as dollars.

**What it changes:** the binding unknown is no longer "is the pool worth anything" but **"what share can a capped quoter
win"**. A 1% share of the same-day pool is ~28/day; 5% is ~140/day. The 20-share-minimum bands (15 same-day + all T+1/T+2,
~2,000+/day of pool) are reachable under small caps; the 100-share bands (1,601/day today) need ~$50-100 per side.
Cheapest next measurement (D6): from captured books, the competing qualifying depth within 4.5c of the midpoint per
rewarded band per minute → our Q-share for a 20-share and a 100-share two-sided quote → expected reward/day, next to
the D4 markout (what those resting quotes lose to informed flow).

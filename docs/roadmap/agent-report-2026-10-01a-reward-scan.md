# 2026-10-01a — reward-terms scan: weather vs YouTube views (one public read)

**VERDICT: both domains run on identical scoring rules (max spread 4.5 c, c = 3, single-sided scoring only
inside a 0.10–0.90 midpoint band). They differ in how the pool is concentrated. Weather spreads 5,200/day
over 151 bands and puts the 100-share size floor on the same-day bands. YouTube spreads 850/day over 12
bands. Its two richest bands (241 and 259/day) carry a 20-share floor, and the remaining 10 carry 50.**
This is a single snapshot, so it says nothing about our share or about competitor depth.

Scope: International Polymarket only, public unauthenticated GETs, no credentials, no order calls. Run on
the workstation, requested 2026-10-01 15:42:32Z, last response 15:43:20Z, 85 requests, all HTTP 200.

## Raw evidence (outside git)

`scratch/reward-scan-20261001-final/` at the root of the workstation main clone (git-ignored; this session's sandbox refused writes
under `data/`). It holds 87 files, about 12 MB. Each response is stored verbatim as
`<request-UTC-timestamp>_<name>.json|html`, and `index.json` records the URL, status, request/receipt
times, size and SHA-256 for each one. `joined_summary.json` is the per-market join, and `reward_scan.py`
is the script that produced it.

| File | SHA-256 |
| --- | --- |
| `index.json` | `01b50779661f575c5706fdb240aa02c926885d3ec55842b6ee5bc779434509e1` |
| `joined_summary.json` | `14cb7488ecd8bbedfab2c019764cb7c02326cf1fbd4b623e8d60125e145277c8` |

Sources:
- `clob.polymarket.com/rewards/markets/current`: every page, 19,071 reward rows. This is the authority
  for per-market rate, max spread and min size.
- Gamma `events/slug/...`: event and market metadata, with `rewardsMinSize`/`rewardsMaxSpread` and the
  top of book.
- Gamma `public-search?q=youtube views` and `events?tag_slug=youtube`: YouTube discovery.
- `docs.polymarket.com/programs/liquidity-rewards`: the midpoint band and scoring rules, which the API
  does not expose.

**Weather coverage:** the 12 configured cities (`market_registry.all_specs()`) for event dates October 1,
2 and 3, which gives 36 events and 396 bands. This clone's `config/location_market_events.json` stops at
09-30, so the slugs were built from its own `highest-temperature-in-<city>-on-<month>-<day>-2026`
pattern. **YouTube coverage:** every open `youtube`-tagged views event, 6 events and 39 bands, of which
35 were accepting orders.

## Terms side by side

| Term | Weather (36 events) | YouTube views (6 events) |
| --- | --- | --- |
| Rewarded bands / live bands | 151 / 396 | 12 / 35 |
| Pool per day (sum of `rate_per_day`) | **5,200** | **850** |
| Per-event pool | 200 per same-day city (400 NYC, LA); 100 per T+1/T+2 city | 500 (Gaming wk-1), 300 (next video d-1), 50 (next video wk-1); 0 on three events |
| Per-band rate | 1–229, median 24 | 1–259, median 31 |
| Max spread (`rewards_max_spread`) | 4.5 c on every band | 4.5 c on every band |
| Min size (`rewards_min_size`) | 100 on 31 same-day bands (2,200/day); 20 on 10 same-day and all 110 T+1/T+2 bands (3,000/day) | 20 on 2 bands (500/day); 50 on 10 bands (350/day) |
| Midpoint band (docs) | [0.10, 0.90]: single-sided scores at Q/3; outside it only two-sided scores; c = 3.0 "on all markets" | same |
| Rewarded mids inside 0.10–0.90 | 112 / 151 (31 below 0.10) | 10 / 12 |
| Unrewarded mids | all below 0.10 or no book | 4 in band; the rest are tails or have no book |
| Tick / order minimum | 0.001 on 252 bands, 0.01 on 144 / 5 | 0.001 on 19 bands, 0.01 on 16 / 5 |
| Rewarded top-of-book spread | median 3.0 c (max 36) | median 2.0 c (max 5) |
| Config start date | 2026-10-01 on every rewarded band (configs re-issued for the epoch) | same |
| 24 h volume (all bands, Gamma) | ~355k | ~118k |

Gamma's `rewardsMinSize`/`rewardsMaxSpread` agreed with the CLOB row on every rewarded band in both
domains. Every reward row carries a single config, all in the same asset.

## What differs, and why it matters for item 330

1. **Concentration.** One YouTube event (MrBeast Gaming week 1, closing 10-03 23:59Z) puts 500/day on
   just two adjacent bands (30–35 M and 35–40 M, mids 0.455 and 0.51) with a 20-share floor. That
   per-band rate exceeds any weather band, including LA same-day 78–79°F at 229 with a 100-share floor.
   Per qualifying share it is the cheapest reward on either domain. It is also where informed flow on a
   near-resolution event should be heaviest.
2. **Size floor placement is reversed.** Weather charges the 100-share floor where the money is (same-day,
   2,200 of 2,800). YouTube's high-floor (50) bands carry only 350/day. The finding from EF §10a still
   holds: a 20-share two-sided quote does not fit a 10 pUSD per-band cap, and a 50- or 100-share floor
   fits even less.
3. **Allocation within an event is uneven and tracks the book.** Rates concentrate on the near-money
   brackets in both domains: LA same-day 112 / 229 / 59 on the brackets around 0.25 / 0.51 / 0.16.
   Weather leaves every bracket with a mid below 0.10 unrewarded. YouTube leaves three whole events at
   zero: two expiring Gaming day-N events and the long-dated 143–145 B total-views ladder.
4. **Weather pool vs EF §10a.** Same-day 2,800 and T+1 1,200 match. **T+2 is 1,200 today, not about 800**,
   so the all-active pool is 5,200 against the recorded about 4,800. This is a single observation. Do not
   update EF until a second day agrees.

## Not established

- Our achievable share, competitor depth at each distance, and whether the YouTube concentration holds
  after a new video is announced. The scan read only Gamma top of book, not `/book`.
- Whether today's per-band weights are recomputed intraday. All configs show `start_date` 2026-10-01, but
  this single read cannot tell daily re-issue apart from intraday re-weighting.

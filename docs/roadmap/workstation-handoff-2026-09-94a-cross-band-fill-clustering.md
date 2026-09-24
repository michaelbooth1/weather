# Workstation handoff 2026-09-94a — cross-band fill clustering from public trade history

Written 2026-09-24 by the production agent. Serves open questions **Q-06, Q-12, Q-13** (`docs/operations/OPEN_QUESTIONS.md`).
EF §10n: open orders are limited to cash per market, not across markets, and every weather band is its own market, so the
same cash can back many bands. The binding risk becomes fills landing on several bands at once. This mission measures how
often that happens, from public data, before any over-committed design exists. Research only.

## 1. Data (public, read-only, throttled to one request per second per host)

Public trade history (Polymarket data API / CLOB public trades) for every configured weather event and band, local event
dates 2026-08-15 to yesterday, T+0/T+1/T+2 as of each trade. Cache under the worktree's ignored `data/`. No authenticated
endpoint, no `.env`, no order code.

## 2. Measure

1. **Co-occurrence:** for each minute, the number of bands (same event; same city across dates; across cities) with a trade
   at or through the touch. Distribution of "k bands hit within 60 s / 5 min", by day-ahead and time of day.
2. **Conditional hazard:** P(a trade on band j within Δt | a trade on band i), for same event, same city other date, and other
   cities; Δt = 1, 5, 30 minutes.
3. **Information clock:** alignment with each station's routine METAR minute (89b `weather.market.observation_clock` on
   `origin/codex/observation-clock-20260923`), NBM 01/07/13/19Z and GFS/HRRR publication times (as 92a measured them);
   direction (are the same-event bands hit on the side consistent with one information shock?).
4. **Worst-case cash call:** for a hypothetical book of k bands x 20 or 75 shares at +-1.5 c, the largest notional that would
   have filled within 60 s and 5 min, per event, per city-day and across the book — the numbers a per-event,
   per-information-cluster and global cap would be set from.
5. **Mutually exclusive baskets (Q-12):** for NO quotes on 2-3 adjacent bands of one event, how often more than one fills,
   and the realised loss under the basket formula vs the sum of reserves.

## 3. Deliverables and boundaries

Branch `codex/fill-clustering-20260924` from `origin/master` (push authorized): a `tools/` script that rebuilds every table
from the cache, and `docs/roadmap/agent-report-2026-09-94a-cross-band-fill-clustering.md` (verdict first, tables, recommended
cap values with the evidence for each, limitations). Descriptive only: report counts and clustering, date x market clustered
where any interval is shown. Nothing heavy while an RE-1 session is running.

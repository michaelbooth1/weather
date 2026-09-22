# Workstation handoff 2026-09-86b — reward capacity curve from public books

Written 2026-09-22 by the production agent. Read-only public data; no order, no credential, no account read.
Runs on the workstation in parallel with the RE-1 campaign and must not disturb it.

## 1. Why

RE-1 measures one number, `k = paid / P_many`, for one 20-share two-sided quote on one band. Whether a paid
verdict is worth building on depends on what the same rule predicts at scale: how many bands qualify per hour, what
modelled share and dollars a quote of 20, 50, 100 and 200 shares would earn on each, and how much capital that ties
up. Digest §maker: next-day 20-share bands are contested (modelled share 0.01-0.10 in ten of twelve cities,
0.18-0.34 only in Los Angeles); the pool is about 2,800 dollars a day. Nobody has turned that into a capacity curve.
Once RE-1 returns `k`, the curve scaled by `k` is the RE-2 sizing input and the long-term go/no-go.

## 2. What to build

1. **A public sampler** (`tools/` script or `src/weather/market/` module with tests) that every 15 minutes reads,
   for every weather reward market the venue lists for today and tomorrow: the per-condition reward record
   (`GET https://clob.polymarket.com/rewards/markets/<condition>`, same shape checks as `mm_stage2_selection.reward()`)
   and both books. It reuses the canonical RE-1 selection and prediction code (`Re1PublicBooks` in `re1_rehearsal.py`,
   the ranking and `predicted_360_minutes` in `mm_stage2_selection.py`) unchanged — **no re-implementation of the share formula**; if a size other than 20
   needs a code path, add a pure function next to the canonical one and prove it returns the canonical value at 20.
   Journal every response with its SHA-256. Send a descriptive `User-Agent`. Throttle to one request per second.
2. **The curve**, from at least 24 hours of samples: per hour and per size, qualifying bands, modelled share,
   predicted dollars per six hours, capital tied up and worst-case loss; totals per day at the best one, three and
   ten bands; the hour-of-day availability pattern. Also summarise the production host's hourly selection logs if
   the owner copies them over (optional).
3. **Sensitivity**: how the curve moves if competitors add the same size (share dilution), stated as a formula
   from the canonical scoring, not a guess.

## 3. Rules

- Branch `codex/reward-capacity-curve-20260922` from `475a626e4` (the RE-1 session tip, which carries `re1_rehearsal.py` and `mm_stage2_selection.py`; master does not); own worktree, never the session worktree; nothing adopted.
- **The sampler must be stopped before the owner starts RE-1 `live` and stay stopped while `live` runs** (it shares
  the network path the session's latency budgets measure); run it now until 19:45 ET and again after the session.
- No full suite before 19:00 ET 2026-09-22 or during a live session; focused tests only.
- Every number is modelled, never paid: label it so. Do not read the 2026-08-10 execution tape markouts (`R` is
  not frozen). No `.env`, no authenticated endpoint, no order path imported.

## 4. Report

`docs/roadmap/agent-report-2026-09-86b-reward-capacity-curve.md`: verdict first in bold (modelled dollars per day at
20/50/100/200 shares on the best 1/3/10 bands, with capital); sample window and count; the parity proof at 20
shares; what was NOT done. Hand back the tip; keep the sampler's journals in the worktree's ignored `data/`.

# Workstation handoff 2026-09-92a — RE-1 campaign analysis (sessions 1-6)

Written 2026-09-24 by the production agent. The owner paused live runs after session 6 for fixes and analysis. Six posted
sessions produced: one 42-minute unpaid session (09-23), several short or refused attempts, three fills on low-competition
bands (full 75 YES in Miami 90-91°F Sep 25; partial 18.4 NO in session 8's band; session 1's partial 5.57 NO), and the first UTC
day above the 1-dollar minimum (owner saw 1.40 on 2026-09-24). The question is **which bands are worth quoting and for how
long**, answered from our own journals. Research only: nothing is traded, served or adopted.

## 1. Input

A **copy** of the campaign root made by the owner (never the live root):
`C:\Users\Michael\Documents\re1-analysis-copy-20260924\` containing `session-*\journal.jsonl`, `prediction.json`,
`selection.json`, `user-stream.jsonl` and `reconciliation.json`. Journals are guard-cleaned (no secrets); still, never open
`.env` or credential files, and do not print full order/maker identifiers in the report beyond the first 8 characters.
Public market data for the same windows may be fetched read-only and throttled (one request per second per host).

## 2. Questions

1. **Accrual vs model:** per session, the modelled `P_many`/`P_single` against the venue's accrual records in the journal;
   per-minute share path; when and how fast competing qualifying depth arrived (minutes to half-share).
2. **Fills:** for each fill, time, side, price, size; the taker (first 8 chars) and whether the same takers recur; the band's
   mid path from 30 minutes before to 120 minutes after; the markout at +5/+30/+120 minutes and at settlement where known.
   Line each fill up against the information clock (station METAR minutes from 89b `weather.market.observation_clock` on
   `origin/codex/observation-clock-20260923`, NBM 01/07/13/19Z, GFS/HRRR publication times) and say which, if any, preceded it.
3. **Selection features vs outcome:** at pick time, competing Q, visible two-sided depth within max spread, spread, recent mid
   movement (from the selection snapshot and the first minutes), local time and day-ahead. Which features separate the bands
   that filled quickly from those that ran? Report counts honestly (n is tiny); no p-values dressed as findings.
4. **Recommendation:** a concrete selection-rule change for the next sessions (for example a minimum competing Q, a minimum
   existing two-sided depth, a mid-stability window, day-ahead preference), with the evidence for each threshold and what it
   would have excluded among the six sessions.

## 3. Deliverables and boundaries

Branch `codex/re1-campaign-analysis-20260924` from `origin/master` (push authorized): a small `tools/` script that rebuilds
every table from the copy, and the report `docs/roadmap/agent-report-2026-09-92a-re1-campaign-analysis.md` (verdict first,
tables, the recommendation, limitations). No live commands (`preflight`, `live`, `cancel-only`, `reconcile`, `collect-*`),
no `.env`, no changes to RE-1 code, and nothing heavy while an RE-1 session is running.

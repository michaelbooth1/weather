# Workstation handoff 2026-09-88a — passive maker-evidence capture

Written 2026-09-23 by the production agent. **Owner-approved 2026-09-23** ([forward plan](../operations/forward-plan-2026-09-23.md)
item 4, decision 2). Build on the workstation; it will **run on the production capture host** as a scheduled task that the
production agent registers after landing. Public, read-only venue data only.

## 1. Why

Pillar B (maker rewards with quotes pulled at smart times) is decided by two unknowns: where competition settles on the
bands we would quote, and whether fill losses cluster around information events. Today only the local-today event is taped
(audit D8-01); the T+1/T+2 bands RE-1 quotes have no tape, reward-term history is one overwritten daily file plus a scratch
poller that stops 2026-09-30, and the order-book update stream is discarded. RE-1 session 1 showed qualifying depth growing
4x in 40 minutes (mission 86c), so minute resolution matters.

## 2. Build (branch `codex/maker-evidence-capture-20260923` from `origin/master`)

1. **Universe per cycle:** for each configured city, the reward-eligible bands of local day-ahead 0, 1 and 2; keep the top
   10 by modelled 20-share reward (canonical estimator) with **at least 3 per day-ahead**, plus any band named in an
   `extra_conditions` file (the production agent writes the RE-1 session band and two matched controls there for 30
   minutes before and after each session).
2. **Every minute:** both-token books for the universe (batched where the public API allows; otherwise sequential with a
   per-request timeout), and the per-condition reward record (`/rewards/markets/<condition>`) **stored only when it
   changes** (hash compare). Public trades for the universe's conditions at the existing tape's cadence if not already
   captured.
3. **Order-book update stream:** subscribe for the universe's tokens; keep raw events under a hard daily byte cap
   (configurable, default 300 MB/day before compression); when the cap is hit, stop the stream for the day and record it.
   First measure the current stream volume from the existing tape's discard counter and report it.
4. **Storage:** append-only, one directory per UTC day, gzip on day close, every response hashed (SHA-256) in a manifest;
   classified in the data-storage-class contract as canonical evidence. Target tens of MB/day compressed.
5. **Brakes:** read free space before each cycle; follow [the storage plan](../operations/storage-plan-2026-09-23.md) bands —
   in Red drop the update stream, in Critical stop entirely and write a status file. Never block or slow the capture
   supervisors (lowest process priority; bounded memory).
6. **Reuse, do not fork:** use the existing public-read code paths (`weather.http` if landed, else the RE-1-style bounded
   reader with a User-Agent); tolerate exact duplicate rows in paginated listings by dropping and logging them (the 86b
   failure), refuse only true conflicts.
7. **Operations:** a `scripts/ops/register_*.ps1` for a scheduled task (not loop-imported, so no capture roll), a status
   file read by `status.ps1`, and the owning doc updated (`docs/operations/` capture/retention docs).

## 3. Tests and verification

Unit tests with recorded public shapes (duplicate pagination, reward-record change detection, byte cap, disk brakes); a
30-minute live dry run on the workstation writing to a scratch directory, reporting bytes per minute, request counts and
latencies. No credentials, no authenticated endpoint, no order code imported.

## 4. Boundaries

Never touch the RE-1 session worktree or campaign root; never run during an RE-1 `preflight` or `live` (the 30-minute dry
run must finish before 19:45 ET on session days); no `.env`. Report: `docs/roadmap/agent-report-2026-09-88a-passive-maker-evidence-capture.md`
with verdict first, measured bytes/day, the update-stream volume, test counts, the roll verdict attempt, and the tip.

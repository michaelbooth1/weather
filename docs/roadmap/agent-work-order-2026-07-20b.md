# Agent Work Order — 2026-07-20b (conservative `data/` cleanup)

Composed by the operations master agent. The operator authorized a **conservative
cleanup of `data/`: delete only what is genuinely not needed or is duplicated.**
It is expected to reclaim little — that is fine. **Default to KEEP.** Protecting
live capture (the 14-day Toronto streak) and the irreplaceable evidence base
outranks freeing any amount of space. When in doubt, keep it or quarantine it.

## Where you work (unusual — read carefully)

`data/` is untracked and exists ONLY in the main checkout
`c:\Users\micha\Desktop\github\weather`, so this task runs **against the main
checkout, not an isolated worktree.** Therefore:

- Touch ONLY untracked files under `data/`, and ONLY in the allowed categories below.
- Do NOT modify any tracked file, `src/`, `config/`, `venv/`, `.git/`, or the
  git working state. Do NOT commit, merge, push, or run any scheduler/loop/
  release action. This is a filesystem hygiene task only.
- Capture loops are WRITING to `data/` continuously. You must not race or
  interfere with them.

## HARD PROTECTIONS — never delete, move, or modify

- `data/snapshots/**` — the replay corpus (the model-improvement engine). Off limits.
- `data/mm_runs/**`, `data/taker_runs/**` — canonical maker/taker tapes.
  Provenance-fat BY DESIGN (required for point-in-time countability); never strip
  or thin them.
- `data/settlements/**`, and all evidence/ledger/label/status/manifest artifacts
  under `data/backtest/**` (e.g. `daily_refresh_*.json`, `settled_day_freshness.json`,
  `market_day_labels.csv`, `fleet_observability.json`, anything matching
  `*status*.json`, `*manifest*.json`, `*ledger*`, `*.lock`).
- `data/forecast_payload_cas/**` — a content-addressed store (already deduplicated
  by design). Do not touch.
- Anything within the **streak window**: any file whose market-day / content date
  is **2026-07-14 or later**, and anything **modified in the last 7 days**.
- Any file currently referenced by a live loop or by an active manifest.
- Raw weather-source captures (`metar`, `eccc`, `eccc_swob`, `noaa_ghcnh`,
  `wunderground`, `reanalysis`, `forecast_history`, `marine_water_contrast`) —
  keep unless a file is provably a byte-identical duplicate or a temp download
  artifact (`*.part`, `*.crdownload`, zero-byte).

If a candidate is ambiguous or you cannot prove it is safe, it goes to quarantine
(Tier B) or is left untouched — NOT hard-deleted.

## Memory-safe scanning (mandatory)

Do NOT run `Get-ChildItem data -Recurse` / `Get-ChildItem data -Recurse -File` or
any pipeline that materializes the whole file list — on 2026-07-20 that pattern
ballooned to multiple GB and starved capture into a near-crash. Use a streaming
walk that accumulates only integers, e.g.:

```python
import os
root = "data"
for e in sorted(os.scandir(root), key=lambda x: x.name):
    if e.is_dir():
        tot = 0
        for dp, _, fns in os.walk(e.path):
            for fn in fns:
                try: tot += os.path.getsize(os.path.join(dp, fn))
                except OSError: pass
        print(f"{tot/1e9:8.2f} GB  {e.path}")
```

Pace your I/O; this competes with capture disk writes. If free physical memory
drops below ~3.5 GB or any capture loop status goes stale/errored during your
work, STOP immediately and report.

## Phase 1 — inventory & proposal (no deletions)

Produce a categorized candidate manifest (path, size, category, justification,
reversibility). Categories to look for:

- **Tier A (safe to hard-delete):** `__pycache__/`, `*.pyc`, `.pytest_cache/`,
  `*.tmp`, `*.partial`, `*.part`, `*.crdownload`, editor backups (`*~`),
  `Thumbs.db`, `.DS_Store`, truly zero-byte orphaned files, and empty
  directories — but ONLY where they are NOT inside a hard-protected path and NOT
  a live/partial write from a currently-running process.
- **Tier B (quarantine, do NOT hard-delete):** byte-identical duplicate files
  (hash-verified; identify the canonical copy and quarantine the stray),
  regenerable caches (e.g. replay caches derivable from canonical inputs),
  rotated/old logs under `data/logs/**` clearly beyond any retention window and
  older than 30 days, superseded one-off intermediate analysis outputs, and any
  clearly-stale contents of `data/archive/**`.

## Phase 2 — act (conservatively)

1. **Verify capture is healthy first**: `data/snapshots/loop_status.json`,
   `data/snapshots/clob_loop_status.json`,
   `data/snapshots/observation_trigger_status.json` — all fresh
   (clob/observation < 180 s, snapshot < 600 s) with zero consecutive errors. If
   not, STOP.
2. **Tier A:** hard-delete only the unambiguous junk above. Record every path + size.
3. **Tier B:** MOVE (do not delete) to
   `C:\tmp\data-cleanup-quarantine-2026-07-20\` preserving relative paths, and
   write a `quarantine-manifest.csv` (original path, size, category, reason).
   The master/operator reviews the quarantine and deletes it later. Never
   hard-delete Tier B.
4. Re-verify capture health after (same checks as step 1).

## Report

Write `docs/roadmap/agent-report-2026-07-20b.md` (create it as an untracked file
or hand the operator the text — do not commit): free space on `C:` before/after,
the top-level `data/` size breakdown, the full Tier A deletion manifest and
Tier B quarantine manifest (per category, with sizes and byte totals), loop
health before/after, and a "candidates I deliberately did NOT act on, and why"
section for operator review. If total reclaimed is small, say so plainly —
that is the expected and acceptable outcome.

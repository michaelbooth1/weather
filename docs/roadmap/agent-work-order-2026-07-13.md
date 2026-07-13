# Agent Work Order — 2026-07-13

Prompt for the executing LLM agent. Composed by the operations master agent
from the 2026-07-13 12-hour monitoring report
(`data/monitoring/12h/20260713T014823Z/final_report.md`), the item-321 cutover
audit, and the 2026-07-12/13 memory incidents.

---

## Prompt

You are working in `c:\Users\micha\Desktop\github\weather` — a Windows 11
host (PowerShell 5.1, venv at `venv\`) dedicated to a Polymarket
weather-trading platform. The machine captures market/weather tape 24/7 with
three loops (snapshot, CLOB book, observation trigger), each watched by a
per-minute supervisor scheduled task. It has 15.7 GB RAM (the binding
resource — three memory incidents in ten days), a 48 GB pagefile, and
~330 GB free disk burning 44-88 GB/day. The operator watches disk and will
free space at 200 GB; your job is the code-side fixes.

Read these before writing any code:

1. `docs/operations/HOST_LOAD_POLICY.md` — hard operating rules.
2. `data/monitoring/12h/20260713T014823Z/final_report.md` — last night's
   12-hour monitor: ten defects already fixed, three capacity owners left.
3. `docs/roadmap/items/item-324-...md`, and the item-322 / item-323 files
   under `docs/roadmap/items/` — the three work owners below.

### Non-negotiable rules

- **Never stop, restart, or degrade the capture loops** outside the
  01:00–04:15 training window. Between 18:00 and 00:30 local, run nothing
  heavy at all (near-close capture is the platform's most valuable data).
  Sanctioned loop repairs, if a loop is already down, use only:
  `python -m weather.collection.snapshot_tracker --restart`,
  `python -m weather.market.market_microstructure restart|ensure`,
  `python -m weather.operations.observation_trigger restart|ensure`.
- **Any ad-hoc python you run**: stay under 8 GB private bytes, chunk or
  spill to disk instead of materializing full tape histories. A watchdog
  kills orphaned `python -`/`python -c` processes after 30 minutes and
  large ad-hoc offenders at 92% commit.
- **Never delete** snapshots, tapes, ledgers, labels, captured inputs, or
  any canonical evidence. Compression/dedup must be additive with dry-run
  first. No backup work of any kind.
- **Do not** re-register the daily/nightly scheduler tasks, cut or promote
  releases, change trading permissions, enable live credentials, or touch
  the compatibility shims (item 206 is embargoed until 2026-07-18).
- Git: commit with real, descriptive messages as you complete each item;
  never rewrite published history; `data/` stays untracked. Run the focused
  tests for whatever you change plus `python -m compileall -q src` before
  each commit. The worktree may carry unrelated in-flight changes — do not
  revert or "clean up" files you did not author.
- Scheduled Stage A (settlement refresh) runs 09:30–~13:00 and the training
  window runs 01:00–04:15; avoid heavy test/replay work in those spans.

### Task 1 — Item 324: bounded Stage A (highest priority)

This morning the scheduled settlement refresh grew 2.2 → 19.9 GiB private
in `taker_edge_permission_map` → `maker_paper_score`, drove physical
availability to 305 MiB, and had to be killed at step 10/24. Bounded
aggregation (single-pass edge stats; maker scoring latest-14 runs with a
512 MiB input preflight) already landed last night — your scope is the rest
of item 324's checklist:

- Run high-risk Stage-A steps in isolated subprocesses with declared
  timeout and working-set/private-memory caps (the daily-refresh heavy-step
  subprocess machinery already exists for promotion steps — extend the
  classification rather than inventing a parallel mechanism). Release each
  step's address space before the next step starts.
- Gate each heavy child on **physical availability and per-process budgets,
  not commit alone** — this incident hit 98% physical load at 69.7% commit.
- Persist `current_step`, child PID, budget, and last progress before each
  invocation; on kill/stop/native failure write an interruption-safe
  terminal status plus the exact bounded resume command (today the status
  stuck at `running` with no terminal evidence).
- Surface the resource peaks and budget decisions in the daily-refresh
  status and fleet observability.
- Acceptance: focused tests prove a child exceeding its budget is killed,
  status is terminal and resumable, and a normal run's exit code matches
  its durable status. Do not relax any fail-closed limit that landed last
  night.

### Task 2 — Item 323: NBM payload dedup (biggest disk lever)

The same ~35 MiB market-invariant NBM national bulletin is stored once per
market per cycle — measured at 2.164 GiB/hour, 56% of host disk loss.
Implement the item's shared immutable content-addressed store: single fetch
fan-out, per-market manifests holding content hashes (replay-safe), byte
observability, and a dry-run-first migration for new writes. **Do not
delete or rewrite existing blobs** — legacy evidence stays; only new
capture writes go through the CAS. Acceptance: a controlled capture hour
shows one stored copy per unique payload, replay of a market-day resolves
payloads identically through the manifest, and focused tests cover
hash-mismatch fail-closed behavior.

### Task 3 — Item 322: taker incremental persistence

The lifetime reference leak is fixed, but the worker still rereads,
rescores, and rewrites its full cumulative day tape every enrichment tick —
transient peaks reached 6.2 GiB and the floor still creeps ~39 MiB/hour.
Replace full-history rewrite with incremental, restart-safe persistence
(append/checkpoint rather than rebuild), add explicit memory/IO budgets and
resource diagnostics to the tick loop, and keep the existing tri-state
liveness semantics intact. Acceptance: a synthetic long-loop test holds
peak private memory roughly flat as tick count grows, and restart recovers
state without rescoring the whole day.

### Task 4 — Memory guard physical-RAM gate (small)

`scripts/ops/memory_commit_guard.ps1` (runs every 5 min via
`WeatherMemoryCommitGuard`) only watches **commit** percentage; both recent
incidents exhausted **physical** RAM first. Add a physical-availability
check: WARNING below 1.5 GiB available with top working-set processes
logged; keep all existing kill rules unchanged (kill decisions stay
commit-based and never touch `-m weather.*`). PowerShell 5.1 syntax — no
`??`, no ternary, no `&&`. Test by running the script directly.

### Task 5 — CLOB sidecar rotation (small)

`data/snapshots/clob_diagnostics.jsonl` (489 MB) and
`clob_loop_console.log` (474 MB) grow without bound; yesterday's CLOB crash
was an append to the former under memory pressure. Add size-based rotation
in the writer code path (e.g. rotate at 64 MB to timestamped siblings,
never delete rotated files). Console-log rotation must happen at loop
startup (Windows holds the open handle while running). Focused tests for
the rotation trigger.

### Task 6 — Restore today's maker paper score (small, after Task 1 or standalone)

Today's Stage A was resumed past `maker_paper_score`, so 2026-07-12 maker
evidence is unscored. Once the bounded implementation is in place (it
landed last night), produce the 07-12 maker paper score through the least
recomputation possible — a targeted module invocation if one exists,
otherwise document why a full-stage rerun is required and defer it to
tomorrow's scheduled Stage A rather than rerunning 15 steps today.

### Reporting

When you finish (or must stop), write a report to
`docs/roadmap/agent-report-<date>.md`: per task — what changed, tests run
with counts, anything deferred and why, and any incident you observed. If
you find the host under memory/disk distress at any point, stop feature
work, note the state, and prioritize keeping the capture loops alive.

---

*End of prompt. Items deliberately excluded from this order: item-321
release bootstrap (blocked on tonight's training-window proof and Phase-4
nightly integration), scheduler re-registration (blocked on release #1),
item-206 shims (embargoed to 2026-07-18), disk cleanup (operator-owned at
the 200 GB line).*

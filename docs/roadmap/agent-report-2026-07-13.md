# Agent Report — 2026-07-13

This run stayed in research/paper/no-live-trading modes except for the exact
runaway-process containment, verified stale-lock repair, ignored runtime-status
correction, and direct memory-guard acceptance run described below. It did not
restart capture loops, re-register scheduled tasks, promote a release, change
trading permissions, enable credentials, delete evidence, run a migration, or
perform backup work.

## Task 1 — Item 324: bounded Stage A

Status: **PARTIAL**. The code-side isolation and admission contract is complete;
the representative scheduled Stage-A inventory/soak remains outstanding.

- Declared an explicit timeout, private-memory ceiling, working-set ceiling,
  physical reserve, and commit ceiling for every Stage-A step. High-risk steps
  now run one at a time through the existing isolated-subprocess machinery so
  each address space is released before the next step.
- Added fail-closed Windows Job Object enforcement plus aggregate process-tree
  working-set sampling, timeout/tree termination, and lifetime I/O/peak
  receipts. A missing working-set sample fails closed.
- Required fresh capture-loop evidence, commit below 70%, and available
  physical memory equal to the child working-set ceiling plus a 1.5 GiB
  capture reserve before launch. Capture and physical checks repeat after the
  child exits.
- Preserved the existing latest-14 maker evidence window, 512 MiB maker input
  preflight, and every other fail-closed limit. Resource overrides can only
  make the physical reserve or commit ceiling stricter.
- Made the durable status resumable before child user code runs: current step,
  child PID, owner/run identity, budget, last progress, terminal
  `interrupted` state, and the exact bounded resume command are persisted.
  Verified terminal child results are recovered before advancing, while an
  unverified or resource-failed child cannot advance the chain.
- Added step peaks, elapsed time, lifetime read/write bytes, bounded result
  metrics, admission decisions, and failure reasons to daily-refresh status
  and fleet observability. Standalone fleet refreshes recover the latest
  resource receipt from durable daily status.
- Kept the item partial because unit tests do not establish representative
  production-corpus peaks, disk I/O/cardinality, or a full scheduled soak.

Verification:

- Final focused resource/isolation gate: `26 passed, 2 subtests passed`.
- Broader daily-refresh run during development: `113 passed`; three
  date-sensitive active-variant tests failed outside the changed surface and
  were not weakened or rewritten.
- `python -m compileall -q app src tests`: passed.
- Agent-doc audit: passed (`18` agent files, `428` Markdown files).
- Schema audit: `475` registered, `792` discovered, `0` unregistered, `7`
  explicitly excluded versions.

Commit: `765bac8c ops: isolate and bound Stage-A refresh steps`.

## Task 2 — Item 323: shared NBM payload CAS

Status: **PARTIAL**. New NBM writes deduplicate through the shared CAS; a
controlled capture hour and cross-process fleet-wide single network fetch
remain outstanding.

- Added a repository-owned raw-byte SHA-256 CAS with fully flushed staging,
  atomic same-volume hard-link publication, convergent concurrent puts, and
  fail-closed verification for missing, corrupt, symlinked, size-mismatched,
  or ref/path-mismatched blobs.
- Added forecast manifest v2 rows retaining each market's capture/source
  timing, request/cycle, market/date, replay-complete NBM station/target
  extraction identity, raw-byte digest/reference, and created/reused plus
  logical/physical/avoided byte evidence. Legacy and non-attested sources stay
  on the market-local path.
- Added explicitly capture-scoped same-process request fan-out. Concurrent
  markets in one scope receive one network result and retain its original
  network fetch time/cache provenance. Unscoped calls coalesce only in-flight
  work, so a later capture pass refetches and can observe same-URL provider
  updates. Production fleet markets still execute in isolated children, so
  this does not yet prove one network request across the live fleet.
- Made shared-CAS cleanup unconditionally fail closed; generic canonical
  review cannot authorize deletion. Event-day manifests now record unique
  external CAS dependencies and block backup/restore claims until referenced
  blobs are included and verified.
- Kept migration inventory-only and explicitly non-authoritative outside its
  scanned snapshot scope. Shared rows are counted only after ref/hash/size and
  source-specific replay validation. There is no apply, rewrite, GC, or delete
  mode, and observed unreferenced blobs are not labeled globally unreachable.
- Added compact byte observability to snapshot status, runtime monitoring,
  retention inventory, and data-layer audit projections.

Verification:

- Corrective focused run: `102 passed, 25 subtests passed`.
- Final staged-slice gate: `86 passed`.
- Independent proof-boundary follow-up: `97 passed` across tamper, cleanup,
  event, migration, fan-out, NBM, capture, path, and architecture coverage.
- `python -m compileall -q src`: passed.
- Agent-doc audit: passed (`18` agent files, `429` Markdown files).
- Strict schema audit: `0` unregistered versions; staged diff check passed.

The controlled live capture hour was deferred during the 11:34 preflight
because the snapshot loop was down/degraded and the protected Stage-A span was
active. The dry-run migration command was not run against runtime evidence,
and no legacy blob was copied, rewritten, or deleted.

Commits:

- `1fc7daa9 storage: deduplicate NBM payloads through shared CAS`.
- `7ffc27a8 storage: harden shared CAS proof boundaries`.

## Task 3 — Item 322: incremental taker persistence

Status: **PARTIAL**. Incremental/restart-safe persistence and accelerated
boundedness tests are complete; the representative multi-hour paper soak
remains outstanding.

- Kept `orders_long.csv` and the counterfactual CSV as append-only canonical
  evidence. Added a rebuildable SQLite checkpoint/index so ordinary ticks
  materialize only the new batch and the policy-bounded filled-position set;
  a current restart reads zero tape bytes and an uncheckpointed crash recovers
  only the tail.
- Added a durable one-tick outbox before either tape append. Orders,
  counterfactual rows with exact real-action attribution, and both budget
  ledgers complete idempotently across every append/checkpoint crash window.
- Made settlement benchmarks refreshable in immutable-label generations,
  bounded to 128 groups per tick. Label arrival/correction/disappearance and
  tail/migration races fail closed; promotion is blocked while any group is
  stale. One-time legacy migration streams canonical tapes and does not seed
  authoritative state from a report projection.
- Made `--fresh` archive the prior complete generation to a sibling root
  outside active-run discovery before starting a clean checkpoint. Nothing is
  deleted.
- Preserved canonical NO-side strategy/market/hour slices, promotion and
  benchmark fields, legacy backfill, and disabled-counterfactual cumulative
  behavior.
- Added explicit private/working-set, per-tick tape/process I/O, duration,
  warmup, and post-warmup slope budgets. Diagnostics include PID plus a
  process-instance UUID so a replacement worker resets its slope baseline
  while cumulative run counters remain intact. Daily-roll and fleet surfaces
  remain advisory and preserve the existing tri-state liveness semantics.

Verification:

- Final combined taker/daily-roll/storage/fleet gate: `169 passed, 33 subtests
  passed`.
- Independent corrective taker run: `89 passed, 8 subtests passed`; schema
  registry `7 passed`; daily-roll/storage `35 passed, 25 subtests passed`.
- The incremental suite includes zero-read restart, tail recovery, crash-phase
  exactness, settlement races, fresh archival, process reset, NO-side parity,
  and a 600-tick growing-tape regression with roughly flat measured peak.
- `python -m compileall -q src`: passed.
- Strict schema audit: `477` registered, `798` discovered, `0` unregistered,
  `7` explicitly excluded versions.
- Agent-doc audit and staged diff check: passed.

The multi-hour live-paper soak was not run during Stage A. It must still record
PID continuity, private/working-set peaks and slope, tick duration, and tape
I/O against the declared budgets; no live taker worker or trading evidence was
restarted or modified here.

Commit: `5e627404 market: make taker persistence incremental and restart-safe`.

## Task 4 — physical-memory warning in the memory guard

Status: **COMPLETE**.

- Added a warning below 1.5 GiB available physical RAM and logged the five
  largest working-set processes.
- Kept physical pressure warning-only. The existing 85% commit warning, 92%
  commit/ad-hoc private-memory action, orphan rule, and `-m weather.*`
  exclusion remain the only termination paths.
- Updated scheduled-task description/documentation without registering or
  changing the installed task.

Verification:

- Focused script-contract tests: `2 passed`.
- Both PowerShell scripts parsed under the Windows PowerShell 5.1 parser.
- Direct script run with an artificially high physical threshold produced a
  warning with top working sets and `action=none`; commit action thresholds
  were set above 100% and orphan grace to 1,000,000 minutes for the test.
- `python -m compileall -q app src tests`: passed.

Commit: `26013c8c ops: warn on low physical memory`.

## Task 5 — CLOB sidecar rotation

Status: **COMPLETE**.

- Added 64 MiB no-delete rotation to the diagnostics writer before append.
- Added timestamped collision-safe sibling names; all rotations are retained.
- Added console rotation only at managed loop startup, after live-writer
  validation and before Windows opens the new detached child handle.
- Did not restart the running CLOB loop, so the new console behavior will take
  effect at its next normally managed startup.

Verification:

- Full focused market-microstructure suite: `57 passed`.
- `python -m compileall -q app src tests`: passed.
- Agent-doc audit: passed.

Commit: `4d1e6c64 ops: rotate CLOB sidecar logs safely`.

## Task 6 — 2026-07-12 maker-paper score

Status: **DEFERRED** without starting the scorer.

The targeted command exists and preflight selected two completed 2026-07-12
post-settlement evaluation runs with 52,847,387 bytes of quote/variant input,
well below the 512 MiB input ceiling. At 11:34 local, host admission had 5.52
GiB free physical RAM and 43.7% commit, but capture admission failed because
the snapshot loop was inactive/degraded with a missing writer lock, one
consecutive error, and stale-code identity evidence. CLOB and observation
capture were healthy. Running with an offline/no-capture mode would also be
false because those two loops were active. No score artifact was written and
the current aggregate maker report was not overwritten.

The least-recomputation follow-up remains this targeted, non-overwriting
invocation after capture admission is healthy and outside a protected heavy
window (shown across lines only for readability):

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper `
  --target-date 2026-07-12 `
  --evidence-mode post_settlement_evaluation `
  --exchange-economics-target-date 2026-07-12 `
  --json-out data\backtest\mm_paper_target_20260712.json `
  --report-out data\backtest\mm_paper_target_20260712.md `
  --fills-out data\backtest\mm_paper_fills_target_20260712.csv `
  --known-edge-out data\backtest\mm_known_edge_map_target_20260712.json `
  --known-edge-report-out data\backtest\mm_known_edge_map_target_20260712.md
```

A 15-step/full-stage rerun is unnecessary.

## Incidents and operational state

At approximately 10:51 local, available physical RAM fell to 0.81 GiB
(94.9% physical load) while commit was initially 68.9% and then reached 79.5%.
The exact surviving owner was PID 45264,
`python -m weather.operations.daily_refresh run ... --stage settlement
--resume-from-step settlement_source_audit`, at approximately 14.4 GiB private
bytes and 4.0 GiB working set. Its owning scheduled task was no longer running.
After verifying the command, owner PID, and absence of child processes, only
PID 45264 was terminated. CLOB/observation capture was not restarted or
signaled; memory recovered to roughly 5 GiB available and commit returned to
the high-40% range.

The canonical stale-lock repair verified dead owners before removing the
daily-refresh and long-job locks and clearing their stale state. Because the
ignored status artifact predated the new interruption-safe implementation, it
was then manually corrected to terminal `interrupted` with pinned target date
`2026-07-12` and exact next bounded resume step
`hourly_model_performance`. Its retained historical progress counters are not
fully normalized (`completed_step_count=14`, `total_step_count=13`), so this is
a safe resume receipt rather than claimed clean new-schema evidence. No tape,
ledger, label, captured input, or other canonical evidence was deleted or
rewritten.

Later read-only checks found the snapshot PID gone, its writer lock absent,
and the per-minute supervisor still returning success without force-restarting
the stale-code process. CLOB and observation heartbeats remained current with
zero consecutive errors. The snapshot loop was deliberately not restarted
outside the 01:00–04:15 training window; all remaining work was limited to
lightweight focused tests and source/documentation changes.

At the final 12:25 local readback, the host had 5.26 GiB available physical
RAM, 42.8% commit, and 349.7 GiB free disk. The latest snapshot status still
named a dead PID with one consecutive error; CLOB and observation heartbeats
were current with zero consecutive errors. The independently scheduled noon
location-config refresh also updated `config/location_market_events.json` and
`config/locations.json`; those unrelated generated changes were preserved in
the worktree and deliberately excluded from every commit above.

Final roadmap generation/lint reported `OK`, and the active backlog now lists
Items 322, 323, and 324 as `PARTIAL` with their remaining soak/fan-out proof
owned explicitly.

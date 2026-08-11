# Agent report 2026-08-09 — rotate the other two managed-loop sidecars

**Verdict: IMPLEMENTED; ROLL-SENSITIVE. The snapshot and observation-trigger loops now share the established 64 MiB non-deleting sidecar policy with CLOB, and diagnostics rotation no longer clears restart-circuit state. This branch must merge through the quiet-window procedure.**

## Handback

- Branch: `codex/workstation-rotate-the-other-two-loops-logs-2026-09-35a`
- Implementation commit: `0ecf6aeb20f78fb362e5c3f3bb27513f8461da6a`
- Base: `origin/master` at `89dd19a3aecffb07e6ecc8d44a98702bf1734590`
- Scope: 12 files; six importable Python files, five focused test files, and `docs/operations/HOST_LOAD_POLICY.md`.

The existing CLOB helper generalized cleanly. Its CLOB-agnostic implementation now lives in `weather.io`; the old `rotate_clob_sidecar` name remains as a thin compatibility wrapper. The established behavior is preserved: the same 64 MiB threshold, UTC timestamped collision-safe siblings, rename rather than copy, and no deletion. CLOB diagnostics still rotate before append and the console still rotates before launch. The existing CLOB-focused tests pass after extraction.

Snapshot now declares rotation for `diagnostics.jsonl` before append and `loop_console.log` before launch. Observation-trigger declares rotation for `observation_triggers.jsonl` and `observation_trigger_diagnostics.jsonl` before append, and `observation_trigger_console.log` before launch. Startup rotation occurs before the child console handle is opened. Append-opened JSONL also rotates immediately before reopening, which bounds files even during long-lived loop runs and directly addresses the 2026-08-09 failure mode. Console files remain startup-only because their handles stay open during the child process.

The staleness-sweep contract remains intact: paths and timestamped sibling naming are unchanged, so `logs/live_append_oversized`, `logs/live_console_oversized`, and `logs/cold_storage_eligible` continue to classify the same files.

## Breaker safety state (§4b)

Rotation does **not** reset the restart budget. `recent_recovery_events` now combines the live diagnostics file with recovery events from every retained timestamped diagnostics sibling. Each immutable archive is indexed once in a small restart-budget history cache so the supervisor does not rescan a large archive on every guard evaluation; the archives remain authoritative, and a missing or unwritable cache causes a safe re-read.

`test_recovery_guard_keeps_rotated_diagnostics_in_restart_budget` creates recovery events, rotates the diagnostics file, and proves the guard remains circuit-open from the archived events. Cache/read-through tests also cover live-plus-rotated history and the non-deleting rotation behavior.

## Falsifier results and production evidence

- The helper contains no CLOB-specific path or handle assumption, so three copies were not required.
- Source inspection found no external truncation or rotation that already bounded these sidecars. The staleness sweep reports their risk class but does not mutate them.
- Startup-only rotation cannot reliably bound append-opened JSONL during a long-lived process. The incident update makes the safe trigger explicit: rotate immediately before the next append-open. Console logs remain startup-only.
- Production had already renamed `diagnostics.jsonl` at 625 MB and `observation_triggers.jsonl` at 753 MB on 2026-08-09, leaving the live append-open risk temporarily at zero. This branch prevents regrowth past the policy threshold. The 366 MB snapshot console and 1,047 MB observation-trigger console remained live disk costs. These are production-agent measurements supplied by the handoff, not new workstation measurements; no production data was read or changed for this report.
- No model or research estimate was produced, so date/market clustering and interval treatment are not applicable.

## Architecture ratchet

The import-architecture test statically enumerates module-level `.jsonl` and `.log` managed-loop paths for snapshot and observation-trigger and requires each path to have a declared trigger. It also checks the CLOB policy exactly. Adding a fourth sidecar without a policy now fails the test.

## Roll verdict

The required script was run unmodified against the exact branch and exact `origin/master` base in an isolated copy containing read-only copies of the retained supervisor status files:

```text
branch:   codex/workstation-rotate-the-other-two-loops-logs-2026-09-35a
changed:  13 file(s); 6 importable
closures: loop, clob_loop, observation_trigger
  ROLL  src/weather/collection/snapshot_tracker.py  -> loop,observation_trigger
  ROLL  src/weather/io.py  -> clob_loop,loop,observation_trigger
  ROLL  src/weather/market/market_microstructure.py  -> clob_loop
  ROLL  src/weather/market/market_microstructure_constants.py  -> clob_loop
  ROLL  src/weather/operations/observation_trigger.py  -> observation_trigger
  ROLL  src/weather/operations/supervisor.py  -> clob_loop,loop,observation_trigger
  WARN  dormant closure clob_enrichment (313.6h old) is SUBSUMED: all 21 of its files are also covered by a live closure, so its dormancy cannot affect this verdict

VERDICT: ROLL-SENSITIVE
```

Per-file verdict: the six source files above are roll-sensitive in the closures printed by the script. `docs/operations/HOST_LOAD_POLICY.md` and all five changed test files are roll-free. Extracting the helper touches the CLOB closure, as predicted; the operational rotation semantics listed above are preserved.

## Verification

From the repository root with the project interpreter:

```powershell
.\venv\Scripts\python.exe -m pytest tests\operations\test_runtime_utilities.py tests\operations\test_supervisor.py tests\collection\test_loop_supervisor.py tests\operations\test_observation_trigger.py tests\market\test_market_microstructure.py tests\operations\test_import_architecture.py -q
# 210 passed, 16 subtests passed in 18.73s

.\venv\Scripts\python.exe -m compileall -q app src tests
# PASS

.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
# Agent docs audit: PASS (18 agent files, 734 Markdown files)

git diff --check origin/master...codex/workstation-rotate-the-other-two-loops-logs-2026-09-35a
# PASS

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\ops\roll_verdict.ps1 -Branch codex/workstation-rotate-the-other-two-loops-logs-2026-09-35a
# VERDICT: ROLL-SENSITIVE (full output above)
```

The full suite completed with `3426 passed, 4 skipped, 19 failed, 830 subtests passed in 330.94s`. The non-green tests are outside this change's behavior: PowerShell execution-policy failures in daily-refresh/training/provenance script tests; 12 existing Windows experiment-executor output-tree failures that reproduced with a short `C:\tmp` base; and two module-size ratchets whose expected warning count is 20 while the checkout already has 21. None of the touched modules newly crossed that ratchet's threshold. The complete owner-package set above is green.

## Explicitly not done

No task registration, production write, loop restart, production-state mutation, archive deletion, merge, promotion, or live-trading action was performed. This workstation only implemented, tested, committed, and pushed the mission branch. The production agent retains merge timing, restart, recovery verification, and archive-retention decisions.

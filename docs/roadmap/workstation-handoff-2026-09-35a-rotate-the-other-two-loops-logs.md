# Workstation handoff 2026-09-35a — the 2026-07-12 log-rotation fix was applied to one loop out of three

Written 2026-08-06 by the production agent. Read on `origin/master` and execute.

## 1. Goal

**Give the snapshot and observation-trigger loops the same bounded log rotation the CLOB loop
got after the 2026-07-12 incident** — so an append to a multi-gigabyte sidecar cannot crash the
loop that gates the streak.

## 2. This is a live repeat of an incident we already paid for

On 2026-07-12 the CLOB loop crash-looped on an `OSError: [Errno 22]` while appending to
`clob_diagnostics.jsonl` at **489 MB**, under memory pressure from a runaway ad-hoc job. The
snapshot loop stalled for ~75 minutes of fleet gap. `HOST_LOAD_POLICY.md` records the fix:
sidecars now rotate at 64 MiB to timestamped siblings.

**That fix went into `market_microstructure.py` and nowhere else.** `rotate_clob_sidecar` has
exactly three references, all inside that module. `snapshot_tracker.py` and
`observation_trigger.py` have **no rotation of any kind** — the only `max_bytes` in the latter is
an unrelated source-cache bound.

Measured on the production host 2026-08-06 21:29, all four **actively being written**:

| Size | File | Loop |
| ---: | --- | --- |
| **1,017 MB** | `observation_trigger_console.log` | observation-trigger |
| **723 MB** | `observation_triggers.jsonl` | observation-trigger |
| **584 MB** | `diagnostics.jsonl` | snapshot |
| **363 MB** | `loop_console.log` | snapshot |

**The largest is more than double the file that caused the original crash**, and it is on a loop
whose failure costs a streak day — the project's #1 operational objective.

Found by `scripts\ops\staleness_sweep.ps1`, which is new; nothing had been watching these.

## 2b. UPDATE 2026-08-09 — IT HAPPENED. This is no longer a predicted risk.

**Three days after this handoff was written, the exact failure it predicted took the snapshot
capture loop down for 5 hours 54 minutes** (04:32 → 10:26), on the file it named:

```
PermissionError: [Errno 13] Permission denied:
  data\snapshots\diagnostics.jsonl          <- 625 MB
  ... in append_jsonl:  with path.open("a", encoding="utf-8") as handle:
```

It then compounded: the supervisor retried, hit the same oversized file each time, **exhausted its
6/6 restart budget and opened the circuit.** The budget window is 24 h, so **it would not have
self-healed until ~04:31 the next day.** It was found only because a merge driver refused to push
onto a host whose capture heartbeat had not advanced. Today's streak day survived only because the
outage fell entirely before the 12:00 graded window.

**Three things this teaches that change the design:**

1. **The crash mode is REOPENING a large file, not writing to one.** `append_jsonl` does
   `with path.open("a")` on **every** append. A console redirect opens its handle once at process
   start and holds it, so it has no reopen to fail. **Therefore: `.jsonl` sidecars are the crash
   risk and must rotate first; oversized `.log` console files are a disk cost, not a crash cost.**
   Size alone is the wrong priority signal — `observation_trigger_console.log` is the *largest*
   file at 1,047 MB and the *least* dangerous.
2. **The failure was transient, which is why it is so dangerous.** When inspected hours later the
   file was not locked and had normal attributes. A scanner holding a 625 MB file during one append
   is enough. **You cannot reproduce this on demand; do not design a test that requires reproducing
   it.** Test the rotation, not the crash.
3. **A NEW DEFECT, and it must be fixed in this same change** — see §4b.

## 4b. The restart circuit breaker's state lives in the file you are about to rotate

`supervisor.py` derives the breaker from **`recent_recovery_events(spec.diagnostics_path, ...)`**
over a rolling `restart_budget_window_hours`. The diagnostics sidecar is therefore **both a log and
the safety state.**

When the production agent rotated `diagnostics.jsonl` to clear the outage, the breaker's memory went
with it — the count fell to zero and the circuit closed. **That was convenient exactly once, because
the root cause had just been fixed by hand. As an automatic behaviour it is dangerous: a loop that
crash-loops fast enough to grow its own diagnostics past the rotation threshold would rotate away
the evidence of its own crash-looping and reset the breaker that exists to stop it.**

**Requirement: rotation must not clear restart-budget state.** Either read recovery events across
the live file *and* its rotated siblings within the window, or persist the breaker count outside the
rotated file. **State this explicitly in the report with a test that proves a rotation does not
reset the budget.** Do not treat it as incidental.

## 2c. Current sizes, and what production already did by hand

Manually rotated on 2026-08-09 (renamed, nothing deleted), so **the live crash risk is currently
zero and nothing prevents regrowth**:

| File | Was | Now |
| --- | ---: | --- |
| `diagnostics.jsonl` | 625 MB | rotated; live file recreated small |
| `observation_triggers.jsonl` | 753 MB | rotated; live file recreated on next event |
| `loop_console.log` | 366 MB | **still live** — console, disk cost only |
| `observation_trigger_console.log` | 1,047 MB | **still live** — console, disk cost only |
| 4 rotated archives | — | **2,372 MB**, cold-storage candidates, no crash risk |

`staleness_sweep.ps1` now separates these three classes: `logs/live_append_oversized` is
**CRITICAL** (crash risk), `logs/live_console_oversized` is WARN (disk), and
`logs/cold_storage_eligible` aggregates the archives. **Keep those three names working** — if your
change alters where or how sidecars are named, update that check in the same branch.

## 3. Start from this — do not re-derive it

- The working reference implementation is **`rotate_clob_sidecar` in
  `src/weather/market/market_microstructure.py:196`**. Read it first. It reserves a timestamped
  sibling, handles name collisions, renames rather than copies, and **does not delete prior
  rotations** — retention is deliberate and must be preserved.
- Rotation happens **at managed loop startup**, before Windows opens the new child handle
  (`HOST_LOAD_POLICY.md`). That ordering exists so rotation never races an open handle. **Keep
  it.** Do not rotate mid-run from inside the writing process.
- The 64 MiB threshold is the established precedent. Use it unless you can show why these
  sidecars need a different bound; if you change it, say why.

## 4. Prioritised work

### P0 — cheapest falsifier: can the existing helper simply be reused?

`rotate_clob_sidecar` is CLOB-named but may be CLOB-agnostic in behaviour. **If it generalises,
lift it to a shared module and call it from all three loops.** If it cannot — because of
CLOB-specific path or handle assumptions — say exactly what is CLOB-specific, because that
changes this from a small refactor into three implementations and the operator should know.

**Do not copy-paste it three times.** A rotation policy in three places drifts, and this defect
exists precisely because one loop got a fix the others did not.

### P1 — wire it into the two uncovered loops

Snapshot: `diagnostics.jsonl`, `loop_console.log`.
Observation-trigger: `observation_triggers.jsonl`, `observation_trigger_console.log`.

Preserve startup-time rotation ordering and non-deleting retention for both.

### P2 — a test that fails if a fourth sidecar is added without rotation

The root cause here is not the missing rotation, it is that **nothing made the omission
visible**. A ratchet that enumerates loop sidecar paths and asserts each is covered by a
rotation policy is worth more than the fix itself. `tests/operations/test_import_architecture.py`
already holds architecture ratchets — follow that pattern.

## 5. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. Mission-specific:

- **Delete nothing.** Existing oversized files are evidence and are covered by retention policy;
  the production agent will handle disposal separately. Rotation must not delete prior siblings.
- **ROLL-SENSITIVE and you must say so per file.** `snapshot_tracker.py` and
  `observation_trigger.py` are both in capture closures. Run
  **`scripts\ops\roll_verdict.ps1 -Branch <branch>`** and paste its output; do not derive the
  verdict by hand.
- Do not touch: `sources/forecast_history.py`, `calibration/**`, `operations/base_retrain.py`,
  `operations/nightly_retrain.py` (`-09-20a`/`-09-33a`, awaiting merge);
  `reporting/research/` (`-09-34a`, running); `reporting/casebooks/` (`-09-32a`);
  `reporting/source_gates/`, `operations/daily_refresh*.py`, `sources/wu_history.py` (awaiting
  merge); `market/**` beyond lifting the shared helper.
- **Changing `market_microstructure.py` to extract the helper rolls the CLOB loop too.** That is
  acceptable if the extraction is behaviour-preserving — say explicitly that it is, and how you
  know.

## 6. What would falsify this mission

- **The helper cannot be generalised** without CLOB-specific assumptions leaking. Report what is
  specific and stop before writing three copies.
- **These sidecars are not actually unbounded** — e.g. something outside the loop truncates them
  on a schedule we have not found. Then the sizes have another explanation and the fix is wrong.
  Check before building.
- **Rotation at startup cannot bound them** because the loops restart rarely enough that a
  sidecar exceeds the threshold within a single run. If so the fix needs a different trigger
  point, and that is a design change worth reporting rather than improvising.

## 7. Branch and report

- Branch: `codex/workstation-rotate-the-other-two-loops-logs-2026-09-35a`
- Report: `docs/roadmap/agent-report-2026-08-06-workstation-rotate-the-other-two-loops-logs.md`

Per `DELEGATION_CONTRACT.md` §5, with `roll_verdict.ps1` output pasted in, and production-host
reproduction paths. **Commit and push at whatever hour you finish.**

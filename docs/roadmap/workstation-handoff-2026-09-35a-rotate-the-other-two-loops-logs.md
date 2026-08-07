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

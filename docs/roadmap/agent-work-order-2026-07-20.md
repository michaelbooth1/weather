# Agent Work Order — 2026-07-20 (item 206: compatibility-shim expiration removal)

Composed by the operations master agent. Item 206 owns executing the
compatibility-shim removal window. The migration-window embargo expired
2026-07-18, so removal is now permitted. Item 127 defined the inventory and the
2026-07-18 expiration policy but deliberately deleted nothing; this work order
executes the removal.

Authoritative references (read BOTH first):
- `docs/roadmap/items/item-206-compatibility-shim-expiration-removal-execution.md`
  — the execution checklist and acceptance criteria.
- `docs/roadmap/compatibility-shim-inventory.md` — the shim inventory with
  batch/class groupings.

## Current state (re-verified by master on 2026-07-20)

- Caller-scan gate CLEAN: `pytest tests/operations/test_import_architecture.py::test_first_party_surfaces_do_not_call_compatibility_shims -q` → **1 passed** (zero first-party callers).
- `python -m weather.operations.structure_inventory` → `tracked=1456 source_py=405 shims=103` (still 103 shims, matching the 2026-07-12 pre-scan).
- 2026-07-12 schtasks dump: every `Weather*` task action invokes
  `venv\Scripts\pythonw.exe -m weather.<module>` or `powershell.exe -File scripts\ops\<script>.ps1`;
  zero actions reference `src/*.py` wrappers, root `app.py`, or root script shims.

Unless your fresh re-scan surfaces a new caller or external dependency, the
entire 103-shim inventory is removal-eligible.

## Task

Follow the item-206 execution checklist. Concretely:

1. **Re-verify clean (fresh, from your branch):**
   - Run the caller-scan test above — must be `1 passed`.
   - Enumerate the shim set: `python -m weather.operations.structure_inventory --out <your-worktree>\shim_inventory.json`
     (write the JSON INSIDE your worktree or a temp dir — do NOT write under `data/`, and do NOT
     pass `--report data\...`). Extract the shim file list from the JSON.
   - Re-dump scheduled tasks (`Get-ScheduledTask | %{ $_.Actions }` or `schtasks /query /fo LIST /v`)
     and grep the actions for any `src/*.py`, root `app.py`, or root script shim reference.
   - Grep README, `docs/operations/`, CI configs, `scripts/`, `tests/`, and reusable tools for
     compatibility-shim usage. Record what you checked.

2. **Remove eligible shims:** delete the shim classes whose fresh caller scan is
   clean and that have no external dependency. Expect all 103 to be eligible;
   delete them in coherent batches (e.g., flat `src/*.py` wrappers, root helper
   wrappers, `app.py`, root script shims).

3. **Record retentions:** for ANY shim you retain, add a concrete dependency,
   owner, and next-review date to `docs/roadmap/compatibility-shim-inventory.md`.
   The acceptance bar: after this runs, every shim class is either deleted or
   retained with a documented current dependency — none survives merely because a
   step was skipped.

4. **Make removals stick:** update the import/path-architecture tests
   (`tests/operations/test_import_architecture.py` and any structure/ratchet
   tests) so a deleted shim cannot silently reappear (assert absence / canonical-only
   surfaces). Update `compatibility-shim-inventory.md` to reflect the new counts.

5. **Refresh item + backlog:** update the item-206 header to mark it executed
   (dated), and regenerate any derived roadmap/backlog index per the existing
   tooling so it stays consistent. Keep these edits inside your branch.

6. **Verify:** run the import-architecture suite, the structure-inventory /
   ratchet tests, and a focused suite covering anything you touched. Every batch
   under host `commit_percent < 70`. Report exact pass counts.

## Rules

Same repository, isolation, and rules as
`docs/roadmap/agent-work-order-2026-07-16.md` (read it first):

- Work in a **NEW worktree** on branch `item206-shim-removal-2026-07-20`, based
  on **current `master`**.
- **No edits to the main worktree.** No scheduler/loop/release actions. **No
  `data/` writes** (inventory JSON goes in your worktree or temp, never `data/`).
- Focused tests only, host `commit_percent < 70`.
- **Do NOT merge or push.** The master audits the branch and merges.

**Capture-safety note for the master agent (not the delegate):** the removed
files are shims with zero first-party callers, so they should NOT appear in any
capture loop's `source_scope_files` — meaning the merge is expected to be
**roll-free** (dead-code + docs). Verify at merge time: check every deleted path
against the snapshot/clob/observation loop `source_scope_files`; if none are
loop-loaded, this can merge any time. If (unexpectedly) a deleted file is
loop-loaded, merge in the 01:00-04:00 quiet window only. Also check for conflicts
against the open delegate worktree branches before merging — a shim touched by
another in-flight branch would conflict.

### Reporting

Write `docs/roadmap/agent-report-2026-07-20.md` in your branch: fresh re-scan
results (caller-scan, inventory counts, schtasks/docs grep), the list of deleted
shim batches with counts, any retained shims with their documented dependency,
test pass counts, and branch/commit ids.

---

*Context: this is pure maintenance-debt reduction and does not touch the model
or the streak clock. It is queued AFTER the 19a maker-projection merge is adopted
and stable. Nothing here is worth any capture-roll risk — if in doubt, retain a
shim and flag it rather than force a removal.*

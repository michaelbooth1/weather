# 206. Compatibility Shim Expiration Removal Execution [COMPLETE 2026-07-20 - ALL 103 SHIMS REMOVED, ABSENCE RATCHETS LIVE]

Goal: execute the compatibility-shim removal window after 2026-07-18 rather
than leaving the expiration policy as a completed plan with no active owner.

Source: item 127 completed the shim inventory and expiration policy. It also
explicitly did not remove any shim class because the default expiration date is
2026-07-18. No active roadmap item owns the post-expiration caller scan,
operator dependency check, and batch removal.

Why this matters: a dated compatibility policy only reduces maintenance debt if
the project actually revisits it after the migration window. Otherwise flat
`src/*.py` wrappers, root helper wrappers, `app.py`, and root script shims stay
discoverable forever despite first-party docs moving to canonical paths.

## Design

1. On or after 2026-07-18, rerun the first-party caller scan from item 127.
2. Check scheduled tasks, README, active operations docs, CI, tests, scripts,
   and reusable tools for compatibility-shim usage.
3. Remove eligible shim batches whose caller scan is clean and whose external
   dependency check has no known blocker.
4. For any retained shim group, record the concrete dependency, owner, and next
   review date in `compatibility-shim-inventory.md`.
5. Update import/path architecture tests so removed shims cannot reappear
   accidentally.

- [x] Rerun the compatibility caller scan after 2026-07-18.
- [x] Check known local scheduled tasks and operator launch paths for shim use.
- [x] Refresh `docs/roadmap/compatibility-shim-inventory.md` with owner,
  dependency, and next-review metadata for any retained shim batch.
- [x] Remove eligible `src/*.py`, root helper, `app.py`, and root script shim
  batches.
- [x] Document any retained shim groups with a concrete dependency and next
  review date.
- [x] Update tests and docs so removed shims remain retired.

## 2026-07-18 Execution Checklist

Run these after the expiration date:

1. `python -m pytest tests/operations/test_import_architecture.py::test_first_party_surfaces_do_not_call_compatibility_shims -q`
2. `python -m weather.operations.structure_inventory --report data\backtest\structure_inventory_report.md`
3. Review local Task Scheduler entries, desktop shortcuts, and operator notes
   for direct `src/*.py`, root `app.py`, or root script shim calls.
4. Delete only the shim classes with a clean first-party scan and no external
   dependency.
5. Record any retained shim class in
   `docs/roadmap/compatibility-shim-inventory.md` with owner, dependency, next
   review date, and blocker.

Acceptance: after the expiration date, every shim class is either deleted or
retained with a current owner, external dependency, and next review date; no
expired shim remains solely because the execution step was missed.

## Completion Notes

Executed on 2026-07-20 from branch
`item206-shim-removal-2026-07-20`, based on master commit `6e31b8af`.

- The required caller gate passed (`1 passed`). The fresh structure inventory
  reported `tracked=1457 source_py=405 shims=103` and enumerated 103 unique
  paths. The tracked count is one above the work-order pre-scan because that
  base commit added the work-order file itself.
- All 215 local Task Scheduler actions, including 17 `Weather*` tasks, were
  checked against the exact shim list and `-m src.*`; there were zero hits.
  Eleven top-level desktop shortcuts also had zero weather/shim targets.
- README, operations docs, CI, app, scripts, tests, tools, and reusable runbooks
  had no active shim dependency. A broader canonical-source scan found one
  stale generated recommendation for `scripts/register_clob_supervisor.ps1`;
  it now emits the canonical `scripts/ops/register_clob_supervisor.ps1` path.
- Removed all 103 eligible files: 85 flat `src/*.py` wrappers, root `app.py`,
  three root helpers, and 14 direct `scripts/*` shims. No shim was retained.
- Import/path and structure-inventory ratchets now require the retired classes
  and exact inventory path list to remain empty.
- Verification passed: import architecture (`21 passed`), structure inventory
  plus schema registry (`13 passed`), data-layer audit plus roadmap backlog
  (`40 passed`), `compileall`, and the agent-doc audit. The post-removal
  structure inventory reported `shims=0 paths=0`.

## 2026-07-12 ownership and pre-scan

This item now has an owner: the operations agent executes the checklist on
2026-07-18 (it runs the daily log reviews and holds the reminder in its
memory index). Removal remains embargoed until that date per this item's own
migration-window contract; nothing was deleted today.

Pre-scan results so the execution day is mechanical:

- `python -m pytest tests/operations/test_import_architecture.py::test_first_party_surfaces_do_not_call_compatibility_shims -q`
  passed with `1 passed` — no first-party callers remain.
- `python -m weather.operations.structure_inventory --report
  data\backtest\structure_inventory_report.md` reported `tracked=1324
  source_py=361 shims=103`.
- Task Scheduler review (full `schtasks` dump, 2026-07-12): every Weather*
  task action invokes `venv\Scripts\pythonw.exe -m weather.<module>` or
  `powershell.exe -File scripts\ops\<script>.ps1`. Zero actions reference
  `src/*.py` wrappers, root `app.py`, or root script shims.

Unless a shim gains a caller between now and July 18, the whole inventory is
removal-eligible on the day.

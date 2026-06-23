# 206. Compatibility Shim Expiration Removal Execution [OPEN 2026-06-21 - JULY 18 REMOVAL WINDOW NEEDS OWNER]

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

- [ ] Rerun the compatibility caller scan after 2026-07-18.
- [ ] Check known local scheduled tasks and operator launch paths for shim use.
- [ ] Refresh `docs/roadmap/compatibility-shim-inventory.md` with owner,
  dependency, and next-review metadata for any retained shim batch.
- [ ] Remove eligible `src/*.py`, root helper, `app.py`, and root script shim
  batches.
- [ ] Document any retained shim groups with a concrete dependency and next
  review date.
- [ ] Update tests and docs so removed shims remain retired.

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

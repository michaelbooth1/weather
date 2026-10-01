# 110o part 4 — CI workflows (owner decision 4, D8) [DONE]

**Verdict: DONE, roll-free. `retrain.yml` and `settlement-audit-qualification.yml` are removed; `ci.yml` (and, for the
same reason, `windows-qualification.yml`) no longer cancels an in-progress `master` run.** The one test that named
`retrain.yml` and the three docs that described it are updated. No production data, credentials, Scheduler state or
venue call was touched.

Branch `codex/110o-ci-workflows-20260929`; handoff
[workstation-handoff-2026-09-110o](workstation-handoff-2026-09-110o-repo-health-owner-decisions.md) part 4; audit rows
D8-F4, D8-F5, D8-F6 ([D8](audits/repo-health-audit-2026-09-26/dimensions/D8.md)), D6-15, wide-audit CI-3.

## What changed

| File | Roll | Change |
| --- | --- | --- |
| `.github/workflows/retrain.yml` | roll-free | Deleted. Manual-dispatch only since 2026-07-29, `lfs: false` so it would have trained and uploaded against LFS pointer files, Toronto/NYC only. |
| `.github/workflows/settlement-audit-qualification.yml` | roll-free | Deleted. Its push trigger (`codex/bounded-settlement-audit-*`) matched no branch; its Linux leg re-ran the full suite that `ci.yml` already runs. |
| `.github/workflows/ci.yml` | roll-free | `cancel-in-progress: ${{ github.ref != 'refs/heads/master' }}` — superseded PR runs still cancel, master runs always finish (CI-3 / D8-F6). |
| `.github/workflows/windows-qualification.yml` | roll-free | Same concurrency expression, so each landed master commit keeps its Windows receipt. |
| `tests/operations/test_import_architecture.py` | roll-free | `ACTIVE_DOC_FILES` no longer lists the deleted `retrain.yml`. |
| `docs/development.md` | roll-free | CI section: removed-workflow note and the master no-cancel rule. |
| `docs/operations/artifact-storage-policy.md`, `docs/operations/git-lfs-policy.md` | roll-free | No longer describe `retrain.yml` as present. |

Workflows, tests and docs are outside every capture closure (delegation contract §3): no production module changes, so
the whole branch is **roll-free**; production confirms with `scripts\ops\roll_verdict.ps1 -Branch codex/110o-ci-workflows-20260929`.

## Coverage argument for the settlement-audit removal

The D8 skeptic pass noted that the removed workflow had a Windows leg over 15 settlement/io test files. That leg ran on
hosted runners and never replaced the production acceptance contract. Executable Windows coverage of those owners
still comes from the production-host bounded suite, which runs **every** tracked test natively on Windows, and all 15
files remain in `ci.yml`'s full Linux run. The only loss is the hosted Windows junit artifact for PRs touching those
paths; if that is wanted, the list can be appended to `windows-qualification.yml` (not done: it would widen that
receipt's declared `native_launch_regressions_only` scope).

## Verification

Focused, fixtures only, from the worktree with the main clone's venv (a few files, not a heavy command):
`agent_docs_audit` PASS; `roadmap_backlog --fail-on-lint --check` OK; `pytest` over `test_agent_docs_audit.py`,
`test_import_architecture.py`, `test_module_size_audit.py`, `test_path_policy.py`, `test_schema_registry.py`,
`test_structure_inventory.py`, `tests/app/test_app_architecture.py`: 61 passed. The PR's full GitHub CI is the
qualification of record.

## What was NOT done

No registration, no production write, no restart, no merge. No workflow was added or re-triggered by hand.

## Production steps

1. Confirm the PR's CI is green on the exact head and `roll_verdict.ps1` returns roll-free.
2. Land on the roll-free light path when the exam-period merge policy in STATE_OF_PLAY allows. Nothing to activate.
3. After landing, the next two quick master pushes should both show completed (not cancelled) `CI` runs.

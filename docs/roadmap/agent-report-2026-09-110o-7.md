# 110o part 7 — branch lifecycle rule and merged-branch status check (owner decision 7, D8) [DONE]

**Verdict: DONE, roll-free. `docs/git-workflow.md` now owns the branch lifecycle rule (merged `codex/*` retired within
7 days of landing, archive-tag first for anything not in `master`, deletion by production through the one-shot push
task with a receipt) and the `archive/*`, `deployed/*`, `preserve/*` namespaces. `status.ps1` warns when merged
branches are overdue.** No branch or tag was created or deleted; production executes deletions.

Branch `codex/110o-branch-lifecycle-20260929`; handoff
[workstation-handoff-2026-09-110o](workstation-handoff-2026-09-110o-repo-health-owner-decisions.md) part 7; audit rows
D8-F10, D8-F13 and proposed ratchet 4 ([D8](audits/repo-health-audit-2026-09-26/dimensions/D8.md)).

## What changed

| File | Roll | Change |
| --- | --- | --- |
| `docs/git-workflow.md` | roll-free | "Branch lifecycle" rule and reserved-namespace table inside *Git authority*. |
| `src/weather/operations/merged_branch_retirement.py` | roll-free (new module; imported by nothing) | Read-only CLI. A branch is overdue when its tip is an ancestor of the first-parent `origin/master` commit that was current 7 days ago, so age runs from **landing**, not from the tip date. Three git calls, no fetch, no writes. |
| `scripts/ops/status.ps1` | roll-free (`.ps1`) | New section before the sweep findings: calls the CLI and adds a `$warns` line (never a `$flags` line, so the verdict is unchanged). |
| `tests/operations/test_merged_branch_retirement.py` | roll-free | Fixture git repo with controlled commit dates: landed-before-cutoff, same tip date but later landing, window older than history, unmerged and `preserve/*` excluded, CLI JSON and failure. |
| `tests/operations/test_status_script.py` | roll-free | The section is a warning, not a verdict flag. |

Production confirms with `scripts\ops\roll_verdict.ps1 -Branch codex/110o-branch-lifecycle-20260929`.

## Measured on the workstation clone (cached refs, fetched 2026-09-29)

`python -m weather.operations.merged_branch_retirement`: 31 merged `codex/*` branches on `origin/master`; **0** landed
more than 7 days ago. With `--max-age-days 3` it lists exactly the 10 branches D8-F10 named (e.g.
`codex/docs-github-pr-cleanup-110d-20260925`), which is the positive control. The CLI takes ~0.2 s. The status
section was executed in isolation against this clone: no warning at 7 days, one warning line at 3 days.

## Verification

`agent_docs_audit` PASS; `roadmap_backlog --check` OK; pytest over the new test, `test_status_script.py`-adjacent static
test and the repo-wide audits (`test_agent_docs_audit`, `test_import_architecture`, `test_module_size_audit`,
`test_path_policy`, `test_schema_registry`, `test_structure_inventory`, `tests/app/test_app_architecture`). The PR's CI is
the qualification of record.

## What was NOT done

No registration, no production write, no restart, no merge, no ref deletion, no tag push. The recorded-retirement
manifest for the currently merged branches is production's to write when the check first warns.

## Production steps

1. CI green on the exact head; `roll_verdict.ps1` roll-free; land on the roll-free light path when the exam-period merge
   policy allows.
2. After landing, `status.ps1` shows the WARN line once a merged branch passes 7 days (the 09-24..26 set crosses on
   2026-10-01..03). Then: `git fetch --prune origin`; `python -m weather.operations.merged_branch_retirement --json`;
   write a recorded-retirement manifest (format `docs/roadmap/branch-retirement-2026-08-11.md`) from its output; delete
   the listed remote refs through the guarded one-shot push task; file its receipt with the manifest.

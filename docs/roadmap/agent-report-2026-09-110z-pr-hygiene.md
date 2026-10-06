# Agent report 2026-09-110z part 3 — open-PR hygiene report

Answers [workstation handoff 2026-09-110z](workstation-handoff-2026-09-110z-reward-scan-and-read-tools.md), part 3.
Branch `codex/pr-hygiene-report-20260928`, code commit `7751c5f40d8ceda8f2452851f4cfa33c29bfa764`, draft PR
[#131](https://github.com/michaelbooth1/weather/pull/131). Written 2026-09-29 on the 32 GB workstation.

## Verdict

**DELIVERED AND EXERCISED READ-ONLY AGAINST THE REAL QUEUE.** `python -m weather.operations.pr_hygiene` reports,
for each open PR:

- ancestry into the base;
- `git merge-tree` conflicts, with paths;
- commits behind the base;
- age and idle days, and the CI rollup;
- linked tracker records and handoffs;
- a file-class roll heuristic and a proposed action.

One allow-list admits only exact read-only `gh pr list` and `git` command shapes. It never fetches, closes,
merges, pushes or comments. `roll_verdict.ps1` remains the only roll verdict.

## What was built

| File | Purpose |
| --- | --- |
| `src/weather/operations/pr_hygiene.py` | `check_command` allow-list, per-PR inspection, action rules, Markdown and JSON output |
| `tests/operations/test_pr_hygiene.py` | 16 tests. A **real temporary git repository** (merged, conflicting, Python and docs branches) with a recorded `gh` response; the test proves no ref changed. Also refusal of mutating or malformed commands, heuristic classes, and failure paths |
| `docs/operations/pr-hygiene.md` + README/docs map/ownership rows | Canonical runbook |

**Roll heuristic:**

| Changed paths | Class |
| --- | --- |
| any `src/weather/schema_registry*.py` | `sensitive_all_closures` |
| other `src/**.py` | `possibly_sensitive` |
| only docs, Markdown, `config/`, `.ps1` and `tests/` | `roll_free` |
| anything else | `unclassified` |

**Proposed actions,** first match wins:

1. `close_as_already_in_base`
2. `fetch_then_rerun`
3. `merge_base_into_branch_and_resolve`
4. `fix_ci`
5. `wait_for_ci`
6. `review_or_close_stale` (idle 14 days or more)
7. `merge_base_into_branch` (150 or more commits behind)
8. `production_review_then_land_any_hour` (roll-free)
9. `production_review_then_roll_verdict_and_quiet_window`

**Work records:** `docs/roadmap/work/W-*.yaml` do not exist on `origin/master` yet (tracker PR #110 is open), so
today's reports say "no work records in this checkout". Handoff links come from ids such as `110z` in a PR's
title or branch.

## Observed on the real queue (2026-09-29 ~18:17Z, base `origin/master` `b0032a90`)

This was a read-only run (`gh pr list` plus local refs) and an operational snapshot, not a finding: 31 open PRs.

- **8 conflict with master:** #78, #81–#85, #107, #124.
- **5 of those are also CI-failing, all RE-1:** #78, #82–#85, each 372 commits behind.
- **#80 and #86 are over 150 commits behind** but have no conflicts.
- **Most of the rest are `wait_for_ci`:** GitHub checks were queued or in progress across the queue.
- **#127 (110x) was the only PR at "production review":** green, 9 behind, `sensitive_all_closures`.
- **No PR's head is already an ancestor of master.** Squash- or rebase-landed PRs cannot be detected this way,
  as the runbook says.

## Per-file roll verdict

| File | Closures | Verdict |
| --- | --- | --- |
| `src/weather/operations/pr_hygiene.py` | none (new; nothing imports it) | roll-free (confirm with `roll_verdict.ps1`) |
| `tests/…`, `docs/…`, `README.md` | none | roll-free |

## What was NOT done

- Nothing was closed, merged, pushed, labelled or commented on any PR.
- The tool itself ran no fetch; the session fetched once, by hand, beforehand.
- No registration, production write or merge.

## Verification

- `pytest tests/operations/test_pr_hygiene.py`: 16 passed, run directly.
- Focused set plus repo-wide audits through `scripts\ops\workstation_heavy.ps1`: 110 passed.
- GitHub CI on the PR head: see the handback reply.

## Reproduction

```powershell
git fetch origin
.\venv\Scripts\python.exe -m pytest -q tests\operations\test_pr_hygiene.py
.\venv\Scripts\python.exe -m weather.operations.pr_hygiene --base origin/master --limit 100 --out data\pr_hygiene
```

## Open questions served

None.

# Open-PR hygiene report

Status: canonical runbook. Owns `weather.operations.pr_hygiene`.
Read when triaging the open pull-request queue before a landing night. The report
is advisory: **it never fetches, closes, merges, pushes or comments**, and its roll
class is a heuristic. `scripts\ops\roll_verdict.ps1 -Branch <b>` stays the only
roll verdict ([delegation contract](DELEGATION_CONTRACT.md) §3).

## What it reports

For every open PR (`gh pr list --state open`, at most `--limit`, default 100):

| Column | Source |
| --- | --- |
| Age, idle | `createdAt`, `updatedAt`, in days |
| CI | `statusCheckRollup`: `failing` if any check failed, else `pending`, `passing` or `none` |
| In base | `git merge-base --is-ancestor <head> <base>`; a squash- or rebase-landed PR still reads `no` |
| Behind | `git rev-list --count <head>..<base>` |
| Conflicts | `git merge-tree --write-tree --name-only <base> <head>` exit code, plus conflicted paths |
| Roll class | Changed paths from `git diff --name-only <base>...<head>`: any `src/weather/schema_registry*.py` is `sensitive_all_closures`; other `src/**.py` is `possibly_sensitive`; only docs, Markdown, `config/`, `.ps1` and `tests/` is `roll_free`; anything else is `unclassified` |
| Work | Tracker records `docs/roadmap/work/W-*.yaml` whose `pr` or `branch` matches, and `docs/roadmap/workstation-handoff-2026-*-<id>-*.md` for a handoff id (such as `110z`) in the title or branch |

The proposed action is the first that applies: `close_as_already_in_base`,
`fetch_then_rerun` (head commit absent locally), `merge_base_into_branch_and_resolve`,
`fix_ci`, `wait_for_ci`, `review_or_close_stale` (idle 14 days or more),
`merge_base_into_branch` (150 or more commits behind),
`production_review_then_land_any_hour` (roll-free) or
`production_review_then_roll_verdict_and_quiet_window`.

`check_command` is the single allow-list for external commands: those exact `gh`
and `git` shapes with validated SHAs and refs. `git merge-tree --write-tree` writes
only unreferenced tree objects to the local object store, which `git gc` removes;
no ref, branch, index or working-tree file changes.

## Commands

Fetch first yourself; the tool reads local refs only:

```powershell
git fetch origin
.\venv\Scripts\python.exe -m weather.operations.pr_hygiene
.\venv\Scripts\python.exe -m weather.operations.pr_hygiene --base origin/master --limit 100 --out data\pr_hygiene
```

It prints the Markdown table and writes `pr_hygiene_<UTC stamp>.json` and `.md` to
`--out` (default `data/pr_hygiene/`). It needs an authenticated `gh` with read
access to the repository.

## Update this file when

The columns, action rules, allow-listed commands, roll heuristic or output path change.

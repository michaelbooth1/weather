# Mission 100c — separately frozen fill-toxicity panel B

**PASS — panel selection, closure refusal and output identity verified with synthetic inputs only.**
Panel A remains the default. Panel B is fixed to September 25–October 8, 2026, inclusive, and cannot
be scored until every date in that full window is closed in every registered market. No production
run, production-data access or `.env` access occurred.

Answers [handoff 100c on the reviewed master](https://github.com/michaelbooth1/weather/blob/af631be2505d1a96142b0ee8bc11895f25587853/docs/roadmap/workstation-handoff-2026-09-100c-fill-toxicity-panel-b.md)
and implements [Clarification 12](../research/fill-toxicity-desk-study-preregistration-2026-09-23.md#clarification-12-2026-09-25-owner-approved-before-any-panel-b-read-or-scoring).
There are zero empirical date clusters, market clusters or market-days in this handback. No empirical
estimates or intervals were calculated; existing inference and underpowered rules are unchanged.

## Provenance and scope

- Branch: `codex/fill-toxicity-desk-study-20260923`.
- User-requested reset target, Clarification 12 authority and new `FROZEN_REF`:
  `0df1264910a36b75d01474f63f86b71920e22541`.
- Verified implementation tip: `2b37cae88db885c09eae287c578e9cec04ab97cf`.
- Handoff read from `origin/master` at `af631be2505d1a96142b0ee8bc11895f25587853`.
- Subsequent commits contain this report and its generated correspondence-index entry. The final
  publication tip is given in the task handback and verified with
  `git ls-remote --exit-code origin refs/heads/codex/fill-toxicity-desk-study-20260923`.

The existing topic worktree was clean before the explicitly requested checkout/reset. No unrelated
changes were discarded. Work stayed on top of the exact requested tip; no master merge was performed
in this mission. The Clarification 12 text was preserved, not re-frozen or rewritten.

## Resulting contract

`fill_toxicity_desk_study.py` owns `PANELS`: A = August 15–September 23; B = September 25–October 8.
`--panel {A,B}` defaults to A. Omitted `--max-dates` uses that panel's complete range; explicit bounds
are 1–40 for A and 1–14 for B. The CLI and Python entry points retain A as their default.

Panel B can be planned with `--dry-run` even before its first date. It plans 14 dates across all
12 current registry markets (168 date-market entries); A still plans its original 480 entries.
Planning remains metadata-only and uses the unchanged 100b sealed 88a terms adapter for either panel.
No new source, freshness rule, sampling rule, estimator, threshold, horizon or exclusion was added.

The scoring gate uses the study's existing close notion: the next local midnight in each market's
timezone. It checks **the full B window**, independently of `--max-dates` or the supplied event subset.
The CLI refuses before reading a support manifest; `run_study` independently refuses before input
inventory, tape reads or output creation. This clock check does not claim settlement capture is
complete: production still owns the once-only run after the last date settles and is captured,
under the lease, earliest approximately the October 9 night.

Caller-built plans are validated before reads: every event date must belong to the selected panel,
any explicit event panel must agree, and start/end must match that market's local date boundaries.
This prevents relabelling A events as B or pooling dates from both panels. Reports remain immutable
in a new or empty output directory; neither panel is appended to the other's prior output.

JSON reports, Markdown reports, dry-run output and every intermediate record contain `panel`,
`panel_start` and `panel_end`. A `study_panel` intermediate header retains panel identity even if no
event is admitted. These bounds always describe the frozen panel, including a `--max-dates` subset.
The report's `frozen_ref` names the exact Clarification 12 commit above.

## Verification

**116 passed, 2 deselected in 54.80 seconds**, covering the study and import-architecture tests.
Existing tests were left untouched; new tests were appended. The two unchanged 100,000-trade stress
controls were excluded from this focused selector change (their prior 100b verification is separate).
Focused compileall and `git diff --check` passed.

New controls prove exact A/B constants and authority; default-A equality; disjoint dates; 14 B dates;
per-panel `--max-dates` limits; B dry-run before the window; early scoring refusal including a
one-date subset; refusal one second before the last local close; acceptance at that close using an
empty synthetic plan; A/B JSON, Markdown and every intermediate field; and refusal of cross-panel
or mismatched date/time plans before reads. End-to-end synthetic one-date studies for both panels
exercise quotes, exposures, fills and windows without a production input.

Reproduce from the reviewed checkout on the assigned workstation:

```powershell
$studyRepo = (Get-Location).Path
$studyRoot = Split-Path -Parent ((git rev-parse --path-format=absolute --git-common-dir).Trim())
$studyArgs = @('-m','pytest','tests/market/test_fill_toxicity_desk_study.py',
  'tests/operations/test_import_architecture.py','-q','-k','not large and not hundred',
  '--basetemp',(Join-Path $studyRoot 'scratch/test-100c'))
$studyEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
  (ConvertTo-Json -Compress -InputObject $studyArgs)))
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./scripts/ops/workstation_heavy.ps1 `
  -Kind pytest -PythonPath (Join-Path $studyRoot 'venv/Scripts/python.exe') `
  -ArgumentsBase64 $studyEncoded -RepoRoot $studyRepo
```

Tests create only synthetic temporary inputs. Capture-host verification must use its own admitted,
time-gated path; this workstation result is not production qualification or scoring authority.

## Roll disposition and boundaries

The repository command
`scripts/ops/roll_verdict.ps1 -Branch codex/fill-toxicity-desk-study-20260923 -Base origin/master`
returned **UNDECIDABLE, exit 1: no live closure evidence**. All four capture closure files are absent
on this workstation. Production must rerun that tool before integration; no closure was inferred.

| Changed file | Disposition |
| --- | --- |
| `src/weather/market/fill_toxicity_desk_study.py` | UNDECIDABLE locally; production closure verdict required |
| `tests/market/test_fill_toxicity_desk_study.py` | No local production-closure claim; included in branch verdict |
| This report and generated `docs/roadmap/correspondence-index.md` | Markdown, roll-free |

No schema-registry change, registration, Scheduler change, production write, production read,
restart, capture loop, production/master merge, venue request, order, credential or `.env` access,
mirror read/write, fitting or promotion. The production agent retains the single panel-B scoring
run after the frozen window; this mission neither performed nor scheduled it.

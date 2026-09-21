# Workstation handback 2026-09-83c — integrated guidance stack

**Layer 1: READY FOR HOST QUALIFICATION. Layers 2 and 3: PARTIAL — the full
suite stops during collection because the accepted 82a research trace imports
a private parser name removed by Part A. No gate was relaxed.**

The assigned merges and owned repairs are complete. Section 3 decisions were
kept as given, including feature schema v1.17. There were no unexpected merge
conflicts. The new full-suite failure is outside the research-tool ownership
granted by this mission; it is reported under handoff section 6.

## Branches and measured gates

Base: `origin/master` = `e28530af67c7371fc7b2c08bbd0e26cfe72a28f9`.
All three worktrees were created from that base with
`GIT_LFS_SKIP_SMUDGE=1`, then combined using merge commits.

| Layer / branch | Tested implementation tip | Full suite |
| --- | --- | --- |
| 1 — `codex/integrate-1-research-20260921` | `c04200081e87b4607c149cb502ce34b4ad7410cf` | 5,835 passed, 34 skipped, 923 subtests passed; 1 warning; 2,772.26 s |
| 2 — `codex/integrate-2-parser-20260921` | `c6c58155faf6f78c6ba714eff1abebc8ee28ef18` | 0 executed; 1 collection error; 9.88 s |
| 3 — `codex/integrate-3-reuse-20260921` | `f1e7350ad77bfaf1cd860821c31aa4b56634f405` | 0 executed; 1 collection error; 8.77 s |

This report and its receipts form a documentation-only leaf after the layer-3
implementation tip above. The pushed branch/PR head identifies that leaf;
the table identifies exactly what the full suites executed. No later code
change is claimed qualified by an earlier run.

[Full-suite receipts and XML hashes](guidance-integrate-83c/full-suite.json)
retain both collection tracebacks. All three compileall, agent-documentation
and generated-roadmap checks passed. Full suites used the workstation wrapper
and distinct basetemps; completed test directories were removed, and collection
failures/inventory-only checks that never created a basetemp left none behind.

Cumulative whitespace checking reports trailing spaces in the four inherited
83a P0 raw bulletin fixtures. Their original bytes were preserved; the new
83c edits pass whitespace checking.

Layers 2 and 3 parity each returned the accepted **BLOCK**, exit 1: 4/4 known
defects rediscovered, 100 known blocking findings, **0 unexpected blocking
findings, 0 coverage blockers**, 221 compared features across 29 fixture cases.
[Parity summaries](guidance-integrate-83c/parity.json) retain the report hashes.
These are unchanged gate results, not permission to promote or score anything.

The layer-3 focused run had 437 passed, 11 skipped, 40 subtests passed and one
inventory-smoke failure. The harness requires the literal double-quoted main
guard; the tool used a single-quoted equivalent. Normalizing that spelling
inside the owned tool fixed it: the inventory rerun passed all 6 tests.
The smoke kind remains `compile_main_guard`; the harness was not weakened.
Combined parser/reuse, clock rejection, window and storage tests passed in
the focused run. Full-suite qualification of layers 2/3 remains blocked.

## New integration blocker — outside ownership

Exact failing collection module:
`tests/reporting/test_nbm_target_trace.py`.

It imports `tools/research/nbm_target_trace/run.py`, whose line 25 imports
`_slot_index_for_target`. Part A renamed that helper to
`_slot_index_for_target_v1`; the old name no longer exists.

The owning repair is in **`tools/research/nbm_target_trace/run.py`**, which is
outside the 83a/83b/83c owned-file lists. The failure is introduced by combining
the otherwise separately accepted branches: layer 1 passes, layers 2 and 3 fail
the same collection gate. No test was skipped or altered to hide it.

An import-only compatibility alias in the live parser would not reconcile the
trace's meaning. Its T1 loop also calls the now-v2 default parser while deriving
its chosen group with the original helper and hard-coding token zero. Its
historical 82a reproduction should explicitly bind both v1 functions, for
example by importing `_slot_index_for_target_v1` and
`parse_nbp_station_tmax_v1` under its existing local names, with a test that
pins that historical dispatch. This is a concrete follow-up for the research
owner, **not an applied change or a rerun of the study**. The live default
must remain v2. The historical evidence and all five source branches were left
unchanged.

## Merge conflicts and owned repairs

| File | Resolution |
| --- | --- |
| `.codex/hooks/pre_tool_use_host_load.py` | Union of the three exact research `.run` names and `tools.research.nbm_target_fix`, once each. |
| `scripts/ops/workload_admission.ps1` | Same exact union; no broad prefix or wildcard admission. |
| `tests/operations/test_codex_host_load_hook.py` | Retained extraction of both weather/tools module strings so equality checks the entire union. This parsing regex does not authorize modules. |
| `src/weather/model/model_sources.py` | Kept A's explicit v2 parse and `NBPClockError` handling, then B's use-time age calculation after the try/except, including clock-rejected payloads. |
| `docs/roadmap/agent-report-2026-09-83b-workstation-finish-the-guidance-repair.md` | Kept Part A exactly. Part B is preserved exactly as [the distinct Part B report](agent-report-2026-09-83b-workstation-finish-the-guidance-repair-part-b.md); its relative receipt links still resolve because its directory did not change. |

The workload-admission test's exact-name set now contains the fourth exact
name, one per line. The research inventory has one new entry using the existing
network-free compilation/main-guard smoke. No other harness behavior changed.

The window diagnostic now computes unavailable counts from emitted rows and
handles an empty candidate list. Its regression forces all 192 combinations
unavailable. The ordinary rerun emitted 192 rows with zero healthy-unavailable;
`window.csv` content matched the retained table, so it was not rewritten.

The storage registry adds exactly
`forecast_payload_cas/nbp_cycle_index/**/*.json` as an
`analysis_projection`, rebuilt from the original receipt and verified blob.
Deletion requires a reviewed exact-path cleanup manifest. Tests and the two
owning storage documents reflect that contract; no cleanup was enabled.

The combined reused-bulletin regression proves explicit parser v2, original
network timestamps, truthful zero-download attribution, original-capture
`cycle_age_hours = 0.5` in the raw wrapper, and use-time age in the diagnostic
feature. A second control proves clock-rejected reused payloads also receive
use-time age while retaining unavailable status and raw provenance.

## Real national-bulletin cost

One already-retained 83a file, `nbp-20260917T07Z.txt`, **34,724,479 bytes**,
SHA-256 `4ed1513243a636a7eac49f2ad0da9df962b0a889aa0cfa502e55439cdb0c277d`.
Its original sidecar receipt was verified before the probe. No national file
was downloaded or added to Git. Measured at `59ff83f2`; subsequent changes
were the main-guard spelling and documentation only.

| Operation, one call | Wall seconds | tracemalloc peak bytes |
| --- | ---: | ---: |
| (a) CAS blob read and hash | 0.054775 | 70,237,837 |
| (b) `_complete_nbp` | 0.523849 | 9,402 |
| (c) Whole `fetch_reusable_nbp` | 3.173433 | 70,255,364 |
| Ordinary per-scope path, same bytes from a download stub | 2.679495 | 71,567,712 |

[Raw measurement receipt](guidance-integrate-83c/national-bulletin-cost.json).
Wall time was measured with tracing enabled; these are single workstation
measurements, not capture-host latency estimates. The ordinary first-fetch
path does not call the reuse reader or completeness scan, so (a)/(b) are not
additional executed stages of that baseline. Both whole calls use the same
existing CAS blob; setup/warming and the retained input allocation are outside
the measured interval. Whole-call traced current allocations were 34,735,317
bytes for reuse and 34,733,152 for ordinary fetch.

**The scan is below one second, so it remains unchanged on reuse.** First-fetch
completeness and all receipt/hash/length/cycle checks also remain. Reuse is
slower than a zero-network download stub here; this does not measure real
network latency or negate the retained 33-to-1 fixture download reduction.
The probe made zero network requests and exactly two stub calls (warm-up and
ordinary baseline).

`_nbp_reuse_stations()` is evaluated once for each cross-process reuse attempt
and passed to index keying, validation, scanning and publication. A first-fetch
and reuse call-count test passes. `all_specs()` simply returns a list from
the in-memory `REGISTRY`; it does **not** read disk on each call.

## Roll, source preservation and exclusions

The tool returned **UNDECIDABLE: no live closure evidence** for all layers.
It names four absent supervisor status files: snapshot fleet, CLOB loop,
observation trigger and CLOB enrichment. It exits before JSON export in this
case; exact text is retained for [layer 1](guidance-integrate-83c/roll-layer-1.txt),
[layer 2](guidance-integrate-83c/roll-layer-2.txt) and
[layer 3](guidance-integrate-83c/roll-layer-3.txt).
[Per-file inventory](guidance-integrate-83c/roll-inventory.json) records the
same lack of closure proof for every changed path. No roll-free verdict is
inferred by hand, including for layer 1; production must rerun its tool.

Unchanged source tips: 79a `7a78ff1b56c11c0ad90800ce0433b2ad44901488`;
81a `7edd82ebb37bdc423fd7978a4b64344a833f07c1`;
82a `2e84063668f71bb54d4c4a07a1cced8091a450bd`;
Part A `2e17ce0eba891b028a968ac45895d3c203ea7dda`;
Part B `62e8ff04442a9ae81a47d008fcb86c5a59d56b34`.

No candidate, fit, retirement, promotion, re-score, outcome read or weather
request was performed. No observed-high floor, replay/migration/parity gate,
artifact, forecast writer schema or capture scope was changed. No production
or mirror write, Scheduler registration, restart, credential access, exchange
call, live order, master merge/push or mission-80b merge occurred. The main
checkout remains clean at its pre-mission commit. Source branches were not
rebased, rewritten or otherwise modified.

## Reproduction

Run from each integration worktree on the assigned non-capture workstation.
Production qualification uses the production host's own admitted runner and
roll verdict; these workstation commands grant no production execution
authority. The project interpreter is found from the common Git checkout:

```powershell
$repo = (Resolve-Path .).Path
$common = git rev-parse --path-format=absolute --git-common-dir
$python = Join-Path (Split-Path $common -Parent) 'venv/Scripts/python.exe'
function Invoke-83c($kind, [string[]]$arguments) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
        (ConvertTo-Json -InputObject $arguments -Compress)))
    & "$repo/scripts/ops/workstation_heavy.ps1" -Kind $kind -PythonPath $python -ArgumentsBase64 $encoded -RepoRoot $repo
}
$temp = 'C:/tmp/83c-' + [guid]::NewGuid().ToString('N').Substring(0,6)
Invoke-83c pytest @('-m','pytest','-q','--basetemp',$temp)
# Retain the result, verify $temp is the exact owned non-reparse directory,
# then remove only that completed test directory with Remove-Item -LiteralPath.
Invoke-83c compileall @('-m','compileall','-q','app','src','tests','tools/research')
& $python -m weather.operations.agent_docs_audit
& $python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
& scripts/ops/roll_verdict.ps1 -Branch (git branch --show-current) -Base origin/master
```

For layers 2/3, use a fresh output path for each diagnostic. The parity command
is expected to exit 1 with exactly the known-defect BLOCK described above:

```powershell
Invoke-83c weather_heavy @('-m','weather.reporting.scorecards.train_serve_feature_parity','--input',"$repo/tests/fixtures/train_serve_feature_parity_known_defects_v0.1.json",'--run-root',"$repo/scratch/83c-parity-reproduce")
Invoke-83c weather_heavy @('-m','tools.research.nbm_target_fix','window','--output',"$repo/scratch/83c-window-reproduce")
```

For layer 3, set `$retainedFile` to the existing national file named in the cost
section, with its original adjacent `.json` receipt. Do not fetch it again:

```powershell
Invoke-83c weather_heavy @('-m','tools.research.nbm_target_fix','reuse-cost','--cache',$retainedFile,'--output',"$repo/scratch/83c-cost-reproduce")
$temp = 'C:/tmp/83c-' + [guid]::NewGuid().ToString('N').Substring(0,6)
Invoke-83c pytest @('-m','pytest','-q','tests/collection/test_nbp_cycle_reuse.py','tests/operations/test_storage_classes.py','tests/sources/test_nbm_target_fix.py','tests/operations/test_codex_host_load_hook.py','tests/operations/test_workload_admission_script.py','tests/operations/test_research_harness.py','--basetemp',$temp)
```

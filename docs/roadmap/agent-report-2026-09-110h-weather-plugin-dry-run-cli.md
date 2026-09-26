# 110h — bounded weather-plugin dry-run CLI handback

**PASS for fixture-tested implementation. Ready for the production agent's leased diagnostic run; no real-data, economic or live-readiness result is claimed.**

Executed [handoff 110h](workstation-handoff-2026-09-110h-weather-plugin-dry-run-cli.md) from
`origin/master` at `965374a0edc6fcb65d66e257be9e404cc9af8d60`.
Open-question IDs: none assigned. Reserved-window status at intake: NONE RESERVED.

## Branch and delivered commits

- Branch: `codex/weather-maker-plugin-20260925`; existing isolated worktree
  `scratch/w/weather-maker-plugin-110b` under the workstation checkout.
- Fast-forwarded its clean local branch to published `c734e5c2bd38bc0975b47598e1f5d10e0911efb6`.
- Merged current master first: `07f8a173`. Only conflict: the generated correspondence index.
  Kept master's generated copy for the merge commit, then regenerated with the complete merged history:
  `9fa2bfce`. No history rewrite.
- Initial implementation: `39f05c0b968fbca29356d93f164db36940587b82`.
- Final tested implementation: `c8bace28a49c281b16442c1d56e4092847daad1f`, including the final-review fix
  that keeps future corrupt/missing bulletin failures from changing earlier decisions.
- This report and its subsequent regenerated-index commit are documentation-only.
  Resolve final publication with `git ls-remote --exit-code origin refs/heads/codex/weather-maker-plugin-20260925`.
- Existing draft [PR #96](https://github.com/michaelbooth1/weather/pull/96) is the review surface;
  Phase 0 is now on master, so master is the integration target.

## Result and limitations

The entrypoint is `weather.market.maker_plugin.dry_run`. Its diagnostic caller lives outside the
provider package, retaining the adapters' contracts-only imports. It reads sealed 88a manifests,
verifies only consumed journal/shard files, reconstructs sharded and unchanged bodies, and handles raw/gzip files.
It never opens an unsealed segment, status file, temporary file, raw stream journal, arbitrary manifest payload path,
credential or venue connection. Handles close before another file opens or a provider/policy runs.

Supporting joins use captured long rows, forecast rows, explanation sidecars, source-payload manifests,
hash-addressed retained NBP blobs, observation-trigger records and settlement ledger revisions. Per-event source
coverage distinguishes loaded rows from matching point-in-time rows. NBP availability is no earlier than its first
retained manifest capture. Corrupt NBP/clock inputs cannot silently turn into fallback or an empty information clock.
Files that change during a read refuse. Missing inputs stay missing.

For each segment/event/captured minute, the JSON includes descriptors, fair values or Unavailable reasons,
clock events, Pending/facts, available probability-mass sums and band denominators, and actual `decide()` output.
Markdown also lists each event's mass sum, source coverage, per-condition leg count and policy/input reasons.
Split minutes at segment boundaries are flagged. Not-evaluable bands are separate from zero-leg policy decisions.
The profile object is `informed_v0`, with the correct literal name `informed-v0`.

The runner discloses independent hypothetical 100-unit portfolio caps, zero inventory/resting orders, and captured
books treated as post-only capable. It is not a portfolio/fill replay. The default hazard is None because 88a does not
provide a measured conservative bound: `MISSING_CONSERVATIVE_FILL_BOUND` is expected unless an earlier gate refuses.
The optional hypothetical-hazard control is labelled synthetic, and the policy validates it unchanged.
No guessed hazard or calibrated trust grade is introduced.

T+0 still refuses absent/conflicting `release_calibration_method` and excludes `market_shrink`. The CLI does not
read ambient release artifacts or invent this field. Missing T+1/T+2 band metadata, oversized supporting files,
unretained bulletins and incomplete ledger chains remain reportable coverage blockers.

The combined JSON/Markdown output cap includes terminal summaries. Input bytes count decompressed reads and rereads;
64 MiB per-file/decoded-segment bounds and a bounded supporting-input cache limit materialization. Time is checked
between bounded chunks, records and provider calls; finishing the report can add a small flush overhead.
Caps retain parseable PARTIAL reports. Exit 0 means processing completed, including any disclosed coverage gaps;
exit 2 means partial, input error, no event-minute coverage or invalid arguments.
The [canonical CLI contract](../operations/maker-core-contracts.md#bounded-weather-plugin-dry-run) owns full paths and limits.

## Verification

- Final focused run: **1,258 passed, 12 skipped**, 16.34 seconds, through `workstation_heavy.ps1`.
  Includes plugin 110b/110c/110e tests, the 20 new CLI fixtures, 88a capture fixtures, all core fixtures,
  and all four requested repository audits.
- The 12 skips are the existing explicit RE-1 replay skeletons. New scenarios are invented 2030 fixtures;
  the existing 110c suite also checks its previously tracked public NBP parser controls.
- Positive control: three two-leg quotes with explicitly hypothetical hazard and unavailable fair value;
  default-hazard control: six zero-leg decisions across two captured minutes.
  Complete NBP fixture event mass sums to one; missing band metadata is marked partial.
- Adversarial checks cover unsealed/status/tmp avoidance, gzip, sharded books, unchanged references, bad hashes,
  escaping/cyclic/missing references, future capture clocks, missing T+0 provenance, corrupt NBP refusal,
  stale-book clock preservation, market selection, all three caps, output reuse/overlap refusal,
  input immutability, blocked network access and handle closure before policy evaluation.
- Focused compileall and `git diff --check` passed. The documentation audit test executes the same
  repository `audit_repo()` checks, including correspondence/backlog parity, through the supported wrapper.
- Temporary fixture directories were resolved and checked before removal after completed runs.
  The initial deep temp path hit Windows path-length limits; the final run uses the short owned
  `C:/tmp/wh110h` directory. An intermediate invocation had a mistyped test path and collected no tests;
  the corrected complete invocation above passed.

Exact focused test arguments, run under the workstation wrapper documented in `docs/development.md`:

```text
-m pytest tests/market/test_maker_plugin.py tests/market/test_maker_plugin_110c.py tests/market/test_maker_plugin_110e.py tests/market/test_maker_plugin_dry_run.py tests/market/test_maker_evidence_capture.py tests/maker_core tests/operations/test_schema_registry.py tests/operations/test_import_architecture.py tests/operations/test_agent_docs_audit.py tests/operations/test_path_policy.py -q --tb=short --basetemp C:/tmp/wh110h
-m compileall -q src/weather/market/maker_plugin src/weather/market/maker_plugin_runner.py src/weather/market/maker_plugin_capture.py src/weather/market/maker_plugin_sources.py src/weather/schema_registry_recent_data.py tests/market/test_maker_plugin_dry_run.py
```

No empirical dates, market clusters, market-days, Brier scores, fitted parameters, intervals or profitability estimates
were produced. The frozen later scoring protocol is unchanged.

## Exact production command

Run from the **production repository root after guarded adoption of this branch**, during the admitted
00:30–09:00 window with at least 45 minutes plus cleanup time remaining. The production agent owns that
adoption and verifies paths locally; this workstation has not accessed them. This command reads UTC
2026-09-25 across the built-in markets. The output must be absent or empty; preserve a previous attempt
and choose a new output directory for any subsequent run.

`-B` prevents Python import-cache writes outside the output directory. `PYTHONPATH` selects this exact
checkout's source packages without modifying the installed environment. Lease bookkeeping is owned by
the admission helper; the diagnostic Python process writes only its two reports under the specified output.

```powershell
$repo = (Resolve-Path .).Path
$python = Join-Path $repo 'venv\Scripts\python.exe'
$priorPythonPath = $env:PYTHONPATH
. (Join-Path $repo 'scripts\ops\workload_admission.ps1')
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload 'WeatherPluginDryRun-110h'
if ($null -eq $lease) { throw 'Dry run not admitted; do not start Python.' }
try {
    $env:PYTHONPATH = Join-Path $repo 'src'
    & $python -B -m weather.market.maker_plugin.dry_run `
        --date 2026-09-25 `
        --data-root (Join-Path $repo 'data') `
        --output (Join-Path $repo 'data\alerts\weather-plugin-110h-20260925') `
        --max-seconds 2700 `
        --max-output-bytes 200000000 `
        --max-input-bytes 1073741824
    $dryRunExit = $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $priorPythonPath
    Exit-WeatherHeavyWorkloadLease -Lease $lease
}
Write-Output "Dry-run exit code: $dryRunExit (0 complete; 2 inspect partial/coverage/error report)"
```

The production agent should inspect both reports and their coverage denominators before interpreting decisions.
This run performs no scoring and cannot establish an edge or authorize orders.

## Per-file adoption disposition

No retained production closure was supplied or read. **Actual closure membership is UNDECIDABLE here**;
production must run `scripts\ops\roll_verdict.ps1 -Branch origin/codex/weather-maker-plugin-20260925`
before integration. Do not infer roll freedom from a new module or from this fixture result.

| Incremental 110h file | Disposition |
| --- | --- |
| `src/weather/market/maker_plugin/dry_run.py` | UNDECIDABLE without production closure evidence |
| `src/weather/market/maker_plugin_capture.py` | UNDECIDABLE; bounded local reader |
| `src/weather/market/maker_plugin_sources.py` | UNDECIDABLE; supporting-input joins |
| `src/weather/market/maker_plugin_runner.py` | UNDECIDABLE; offline composition/reporting |
| `src/weather/schema_registry_recent_data.py` | **Additive-only** registration; existing entries unchanged. Treat as potentially roll-sensitive until the mechanical verdict. |
| `tests/market/test_maker_plugin_dry_run.py` | UNDECIDABLE; fixture-only test code |
| `README.md` | Documentation, roll-free by standing policy |
| `docs/operations/maker-core-contracts.md` | Documentation, roll-free |
| `docs/operations/package-boundaries.md` | Documentation, roll-free |
| This report; `docs/roadmap/correspondence-index.md` | Documentation/generated documentation, roll-free |

Earlier plugin paths retain their [110b](agent-report-2026-09-110b-weather-maker-plugin.md) and
[110c](agent-report-2026-09-110c-maker-contract-and-policy-fixes.md) dispositions; they remain part of the cumulative branch review.

**Not done:** no production/mirror input reads or writes, credential or .env reads, venue calls, registration,
Scheduler changes, worker starts/restarts, model fitting, scoring, promotion, live trading, production-master merge,
or runtime adoption. The authorized master-into-topic merge is recorded above. Production runs the real diagnostic.

# 111a — weather plugin: fixes from the first real-data dry run

**PASS for fixture-tested fixes to all five defects. The plugin still does not land: a production re-run
must evaluate bands end to end first (command below). No real-data, economic or live-readiness result is claimed.**

Executed handoff 111a (`docs/roadmap/workstation-handoff-2026-09-111a-plugin-dry-run-fixes.md` on
`origin/codex/handoff-110h2-20260928`) against its evidence folder
`docs/roadmap/evidence-110h-dry-run-20260926/` on the same branch. Both were read there; neither is copied here.
Workstation (32 GB, non-capture) only: fixtures, no production data, credentials, `.env`, Scheduler or venue.

## Branch

- Branch `codex/weather-maker-plugin-20260925` (draft [PR #96](https://github.com/michaelbooth1/weather/pull/96)),
  from its published tip `3b8c7b92d07ad0f94f3b45b95459ae03ab2022a5`, worked in a new isolated worktree.
- Fix commit `9813128e`; `origin/master` merged in `907a1b34` (conflicts: `package-boundaries.md`, kept both sides;
  the generated correspondence index, taken from master then regenerated). Fast-forward pushes only; no rewrite.
- Resolve the final head with `git ls-remote --exit-code origin refs/heads/codex/weather-maker-plugin-20260925`.

## The five defects

1. **NBP path (1,269 `nbp:FileNotFoundError`).** Confirmed from code: v2 manifest rows with
   `payload_storage_scope=shared_market_invariant` live in the shared store at
   `forecast_payload_cas/sha256/<xx>/<key>.blob`. The path is now built by the store's own `shared_payload_ref`,
   and the row's CAS kind, `sha256-raw-bytes` algorithm, encoding, media type, ref and station/target identity
   (`validate_nbm_shared_manifest_identity`) are checked. **What the hash covers:** the exact national NBP text
   bytes, with no newline stripping and no JSON envelope; `payload_bytes` is their length. The legacy `.json` hash
   covers canonical JSON without its trailing newline and is kept for market-local rows. Each blob is streamed once
   per run with a running SHA-256, a byte count and strict UTF-8. Only requested station blocks are retained, and the
   provider gets the verified station extract with the national hash as lineage. A refused blob is never reread.
   `raw_payload_path` is never followed.
2. **`descriptor:missing_captured_band_metadata` for T+1/T+2 (44).** The production hypothesis was wrong about
   the mechanism. The runner never opened CLOB token files. Band metadata came only from `snapshots_long.csv`, and
   the evidence shows zero point-in-time snapshot rows for T+1/T+2 events (0/1969 and 0/1980 at 00:01Z), so there
   was nothing to find. The fix streams `clob_tokens.jsonl` (else `clob_tokens.csv`, raw or gzip) line by line and
   stops at the first complete token batch. A complete batch has both outcomes for every condition, identical native
   bin fields and no negative label. The 64 MiB whole-file cap is unchanged and a 1 MiB line cap applies; a
   93.5 MB file costs about one 64 KiB chunk. Snapshot rows still win when present at a later clock. A first batch
   after the minute stays a reported coverage limit (`unavailable.lead<N>.*`).
3. **`descriptor:missing_point_in_time_input` for T+0 (33): a genuine coverage limit, now named.** The error came
   from `WeatherUniverse._book`: no captured book at or before the minute for that band's tokens. 88a
   (`maker_evidence_capture.build_universe`) books only the selected universe. That is at most ten reward-eligible
   bands per city, and eligibility is `reward_rate(reward, now.date())` on the **UTC** date. At 00:01Z the local T+0
   event (e.g. Atlanta 25 Sep, still 20:01 EDT) remains in discovery, whose events are keyed by local date. But a
   reward window ending on the target date no longer counts on the UTC date, so none of its bands is booked.
   Unselected bands are unbooked all day for the same reason. The runner now reports `descriptor:book_not_captured`.
   Changing 88a selection is capture-side production code, outside this handoff; this is recorded for the owner.
4. **`settlements:file_byte_limit` (7).** Each market's ledger is streamed once per run. Only rows for run-window
   events (target within date −1 to +3) that were recorded by the end of the run date are retained. Later revisions
   cannot be point in time.
5. **Input budget.** The 1 GiB was spent on per-event rereads. They included seven failed ≤64 MiB ledger reads and
   the shared trigger journal reread for every event. An LRU of about three events thrashed against ~33 events per
   minute, and every minute rescanned all segment captures. Now:
   - Each event's supporting files load once per run, under an explicit `--max-cache-bytes` (default 512 MiB).
     Evictions, reloads, hits and peak are reported as `cache.*`.
   - Each file's identity is rechecked after its read, and a changed file refuses.
   - Rows that cannot be point in time are not loaded: those after the run date, and forecast or NBP manifest rows
     more than 48 h before it.
   - Segments are indexed once, so a minute reads no files.
   - Providers are built once per cached event and keep the only copy of its rows.
   - Every source reports `input_bytes.<source>` and `files_read.<source>`.
   - `--minute-stride` (default 1) is an explicit, reported sampling knob. Caps were not raised.

   Provider semantics are unchanged. The forecast fallback's per-event row index is checked against the verbatim
   pre-111a scan by a randomized parity test that includes malformed rows. Timestamp parsing is memoized.

## Verification

- New `tests/market/test_maker_plugin_111a.py` (28 tests) drives the production writers themselves:
  - Shared-CAS layout from `SharedForecastPayloadCAS.put`, cross-checked by `resolve_forecast_payload_bytes`. Its
    fair values equal the legacy layout's, and it is read once over two minutes.
  - Blob hash, byte-count, ref, identity and missing defects fail closed.
  - Over-cap token files in JSONL and gzip CSV via `token_rows_from_event` and `write_token_rows`. The old
    whole-file path is shown to fail; the new path reads ≤128 KiB.
  - A token batch after the minute; an over-cap ledger with an out-of-window row and a post-run revision.
  - T+0 `book_not_captured`; single load per run; cache overflow; minute stride; fallback parity.
- Existing plugin suites unchanged in intent: one test adapted to pass a `CaptureIndex`; `layout()` gained an
  optional uncaptured-token set.
- Through `scripts\ops\workstation_heavy.ps1`: **1,426 passed, 12 skipped** (the existing RE-1 replay skeletons).
  Scope: all plugin suites (110b/110c/110e/110h/111a), 88a capture, microstructure, shared-CAS and payload-persistence
  tests, `tests/maker_core`, and the schema-registry, import-architecture, agent-docs, path-policy and module-size
  audits. The correspondence-index `--check` passes. The full suite ran in GitHub CI (`test`, `native-launch`), which
  was green on `90edc16c`; the final head's CI is required green before handback.
- **Synthetic scale benchmark (scratch only, invented 2030 data, not production):**
  - Load: 11 F markets × 2 in-window events × 11 bands, 88a-like minute captures and supporting files sized like
    the evidence.
  - 60 simulated minutes: 1,320 records, 23 s including all first loads, 15 MB output, about 231 MB input read
    once, about 640 MB peak working set.
  - A full day at stride 1 therefore fits the 2,700 s cap, but output would exceed the 200 MB default.
    Stride 5 (≈110 MB) fits every default cap except input (see command).

## Exact production re-run command

Run from the production checkout during the admitted 00:30–09:00 window with the shared lease. Use a **new detached
worktree at the pushed head**, `python -B -P`, a module-path probe and a **new** output directory. Fill `$sha` from
`git ls-remote` above and pick an unused `$wt` outside `data/`. The production agent owns verifying local paths;
this workstation has not accessed them.

```powershell
$repo = (Resolve-Path .).Path
$sha = '<pushed head of codex/weather-maker-plugin-20260925>'
$wt = Join-Path $repo 'scratch\w\111a-rerun'
git -C $repo fetch origin codex/weather-maker-plugin-20260925
git -C $repo worktree add --detach $wt $sha
$python = Join-Path $repo 'venv\Scripts\python.exe'
$priorPythonPath = $env:PYTHONPATH
. (Join-Path $repo 'scripts\ops\workload_admission.ps1')
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload 'WeatherPluginDryRun-111a'
if ($null -eq $lease) { throw 'Dry run not admitted; do not start Python.' }
try {
    $env:PYTHONPATH = Join-Path $wt 'src'
    $probe = & $python -B -P -c "import weather.market.maker_plugin_runner as m, maker_core; print(m.__file__); print(maker_core.__file__)"
    if (@($probe | Where-Object { -not $_.StartsWith((Join-Path $wt 'src')) }).Count) { throw "Module path probe failed: $probe" }
    & $python -B -P -m weather.market.maker_plugin.dry_run `
        --date 2026-09-26 `
        --data-root (Join-Path $repo 'data') `
        --output (Join-Path $repo 'data\alerts\weather-plugin-111a-20260926') `
        --max-seconds 2700 `
        --max-output-bytes 200000000 `
        --max-input-bytes 4294967296 `
        --max-cache-bytes 536870912 `
        --minute-stride 5
    $dryRunExit = $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $priorPythonPath
    Exit-WeatherHeavyWorkloadLease -Lease $lease
}
Write-Output "Dry-run exit code: $dryRunExit (0 complete; 2 inspect partial/coverage/error report)"
```

Why these flags:

- `--minute-stride 5` keeps a full day inside the 200 MB output cap.
- `--max-input-bytes 4294967296` is an explicit budget, not a silent cap raise. Per-event inputs were about 10 MB
  each, but the sealed segments' decompressed size and each national NBP blob's size (about 8–12 distinct cycles in
  the window) are unknown here.
- If the run stops on `input_byte_cap`, the `input_bytes.*` rows name the source.
- Run with `--minute-stride 1 --max-output-bytes 700000000` only if the host's free space allows.

What to check in the reports:

- `nbp_blobs.verified` > 0 and no `nbp:` reasons.
- `band_tokens.events_with_batch`.
- `descriptor:book_not_captured` counts by `unavailable.lead<N>`.
- Evaluated bands with `decision` present. `MISSING_CONSERVATIVE_FILL_BOUND` is expected at the default hazard.
- `cache.reloads` = 0.
- Remove the worktree afterwards (`git worktree remove $wt`).

## Per-file adoption disposition

No production closure was read. **Actual closure membership is UNDECIDABLE here.** Production must run
`scripts\ops\roll_verdict.ps1 -Branch origin/codex/weather-maker-plugin-20260925` before integration.

| Changed in 111a | Disposition |
| --- | --- |
| `src/weather/market/maker_plugin/{fair_value,inputs,universe}.py` | UNDECIDABLE; pure provider changes |
| `src/weather/market/maker_plugin_{capture,sources,runner}.py` | UNDECIDABLE; diagnostic runner only |
| `tests/market/test_maker_plugin_111a.py`, `test_maker_plugin_dry_run.py` | Test code |
| `docs/operations/{maker-core-contracts,package-boundaries}.md`, fixtures README, this report, index | Documentation, roll-free |

**Not done:**

- No production or mirror reads or writes, and no credential or `.env` access.
- No venue calls, Scheduler changes, 88a capture changes, scoring, fitting, promotion or live trading.
- No production merge.
- The 88a UTC-date reward-eligibility behaviour (defect 3) is reported, not changed.

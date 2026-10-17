# 111j — weather plugin: why the production re-run evaluated no band, and fair-value binding without a release pointer

**PASS (fixtures only) for two plugin defects fixed and three results explained as genuine limits or designed
behaviour. The plugin still does not land: the production re-run below must show `end_to_end.lead1` > 0 first.
The T+0 release-unbound result is correct behaviour, not a defect. No release is inferred, and T+0 does not
affect `informed-v0` decisions in any case. No real-data, economic or live-readiness result is claimed.**

Mission 111j came from the owner's dispatch prompt of 2026-09-30. There was no separate handoff file. Its facts
come from the production re-run of branch `codex/weather-maker-plugin-20260925` at `134be204` (date 2026-09-26,
`--minute-stride 5`, 130 s). That run evaluated no band end to end:

- 0 legs on 7,371 decisions;
- `fair_value:served_snapshot_release_unbound` on 7,367 of them;
- `descriptor:missing_captured_band_metadata` 65,912;
- a band token batch for 24 of 48 events.

Those are the production agent's figures (`data/alerts/weather-plugin-111a-20260926/`). This workstation did not
read them. Every conclusion below is traced from code and fixtures. Where one depends on those figures, it says so.

Measured values: none. This mission makes no measurement, so no date x market clustering applies. The only
numbers are the production figures above and fixture counts.

## Causes, traced from code

### 1. T+1/T+2 events have nothing captured before their local day (root cause of the band and NBP gaps)

Production capture is **local-T+0 only**:

- `snapshot_tracker.capture_snapshot` refuses an event whose target is after the market-local today in auto mode
  (`src/weather/collection/snapshot_tracker.py:146-148`).
- The CLOB loop captures each market's `market_local_date` event
  (`market_microstructure.py`, `capture_market_books(target_date=None)` → `PolymarketClient` default date).
- 88a's discovery projection keeps no band label (`maker_evidence_public.discovery_projection`: id,
  conditionId, active, closed, enableOrderBook, clobTokenIds, outcomes, reward fields).

So on run date R, a T+1/T+2 event folder has no point-in-time snapshot, token, forecast or NBP manifest rows. The
110h evidence already showed this (0 point-in-time rows at 00:01Z for every 09-26 and 09-27 folder). Two plugin
defects follow from it.

**Why exactly 24 of 48 events had a token batch** (12 markets; an R-dependent fact about the run, consistent
with the figures, not re-read). During UTC 2026-09-26, the evaluated targets per market are 09-25, 09-26, 09-27
and 09-28, which is 48 events. The CLOB loop first captures an event at its local midnight. That is on or before
09-27 00:00Z only for the 09-25 and 09-26 targets (24 events). The 111a loader stopped at the run-date end
(`when > self.day_end`), so the 09-27 and 09-28 events could never have a batch.

**`missing_captured_band_metadata` 65,912** is therefore every T+1/T+2 band-minute. For example, 12 markets × 2
events × ~11 bands × 288 minutes is about 76k before fewer-band events and missing minutes. This order-of-magnitude
check is not a reconciliation of the exact count.

### 2. Defect: T+1/T+2 NBP bulletins were looked for only in the T+1/T+2 event's own folder (fixed)

`Sources.for_event` read `forecast_payloads.jsonl` from the evaluated event's folder only. That folder is empty
before its local day. But an NBP cycle is a national product, and the copy the snapshot loop captures for the T+0
event carries the T+1 (and possibly T+2) maxima. The design reads "the newest retained NBP bulletin whose TXN row
holds D's maximum", not "captured in D's folder".

**Fix:** `Sources.market_bulletins` reads the NBP manifests of every run-window event folder of the market once
per run (`nbp_pool_manifests`).

- Each manifest is verified against the event it was captured for: shared-CAS identity, byte count, SHA-256, and
  the legacy JSON identity.
- Station extracts are deduplicated by text, and the earliest availability wins.
- The provider receives the extract with its own target and selects that target's slot. A cycle without the
  target's maximum is skipped (`target_max_not_in_cycle`), as before.
- An unreadable pooled manifest makes that market's fair value and clock `corrupt_supporting_input`, never fallback.

### 3. Defect in the metadata rule: a later token batch was refused although it describes the same contract (fixed, explicit basis)

With capture as above, no T+1/T+2 band metadata exists at the decision minute from any source. The 111a rule
("a batch after the minute is a coverage limit") therefore made every quoted band (`informed-v0` quotes only
T+1/T+2) unevaluable by construction.

A band is part of its condition's immutable question. The condition id and its two token ids are fixed identities.
So the first complete token batch describes the same contract whenever it was captured.

**Fix:** the first complete batch is now read even after the run date. It is used as **condition identity**
only when all three of these hold:

- there is no band capture at or before the minute;
- that minute's 88a discovery lists **exactly** the batch's condition set;
- each condition has the same YES/NO token ids.

Otherwise every band of the event is `descriptor:band_identity_mismatch`. Partition membership, books, reward terms
and prices all stay point in time.

The basis is reported in several places:

- per band (`band_basis`);
- in the descriptor's `source_hashes.band_basis`;
- in the fair-value input digest;
- as `band_basis.lead<N>.<basis>` and `band_tokens.batch_after_run_date`.

A point-in-time capture still wins. No batch at all is still `missing_captured_band_metadata`. **This changes a
documented 111a rule; the production agent should accept or reject it explicitly.** If it is rejected, T+1/T+2
fair value is unevaluable on current capture, and the only remedy is capture-side (see "Genuine limits").

### 4. `served_snapshot_release_unbound` on 7,367 decisions: correct refusal, not a defect

- Production has no release store. `artifacts/releases/current_release.json` is absent (established findings,
  release-store section).
- `release_serving.get_process_active_serving_bundle` therefore returns `RESEARCH_UNBOUND`, and
  `serving_bundle_lineage` writes `release_id=""`, `release_manifest_sha256=""` and
  `release_identity_status=research_unbound_non_countable` on every source row
  (`src/weather/release_serving.py:899-936`).
- `WeatherFairValue._served` requires `verified_variant_serving_bundle` and refuses.
- Retracted claims already record the same gate on the scorecard: "Do not fix it by relaxing release identity".

The refusal also has no decision effect. `informed-v0` has `eligible_horizons=(1, 2)`
(`src/maker_core/quoting/policy.py:38`), and `HORIZON_NOT_ELIGIBLE` is returned before fair value is read. A new
fixture shows both, built with the production resolver and lineage writer. The 4 remaining decisions carried some
other reason, which cannot be determined here without the report.

### 5. 0 legs on every decision: guaranteed at the default hazard

For `informed-v0`, `MISSING_CONSERVATIVE_FILL_BOUND` is returned whenever `hazard_per_minute is None`
(`policy.py:243-246`). No measured hazard exists (88a retains none), so the dry run correctly passes none. Legs
are therefore not the acceptance criterion. `--hypothetical-hazard-per-minute` makes them appear, labelled
hypothetical.

## How fair value is bound on a host without a release pointer

1. **T+1/T+2 (the only bands `informed-v0` quotes) need no release.** The fair value is the zero-parameter NBP
   read. Its binding is complete without one:
   - `model_id=nbp-v2-piecewise-linear` and the plugin version;
   - the verified national blob hash (`source_payload`);
   - the station-extract hash;
   - the fetch/availability clock and the NBP slot;
   - the band edges and their basis, all inside the `OutcomeView` input digest;
   - the source commit, from the run's detached worktree at the exact pushed SHA.

   No served-model artifact is involved.
2. **T+0 stays `Unavailable(served_snapshot_release_unbound)`.** No release is inferred, and T+0 is outside
   `informed-v0`.
3. If T+0 served probabilities are ever wanted on such a host, the only exact non-release identity captured is
   this:
   - **`model_identity_hash`** on every source row of the snapshot: the SHA-256 over `model_version`,
     `market_id`, `active_model_kind`, `code_hash` and `artifact_hash`
     (`model_identity.model_replay_identity`).
   - Its full `code_files`/`artifact_files` fingerprints are in that event's `replay_inputs.jsonl`. They include
     the SHA-256 of the `probability_calibration<suffix>.json` that served.

   Binding to it would require three things:
   - streaming `replay_inputs.jsonl` and recomputing `identity_hash`;
   - resolving `market_bin.method` (and `enabled` / `preserve_distribution_coherence`) from artifact bytes whose
     SHA-256 equals the captured one, never the current checkout;
   - labelling the lineage as a distinct non-release kind, never `verified_variant_serving_bundle`.

   That is a change to the release-binding invariant (AGENTS.md), so it needs an owner decision. It is **not
   implemented and not recommended now**, because nothing that quotes consumes it.

## Genuine limits (reported, not changed)

- **Live T+1/T+2 band metadata.** The condition-identity basis works in replay only: the batch is captured later.
  A live or forward-shadow maker needs the band label at t. The cheapest source is 88a keeping `groupItemTitle` in
  `discovery_projection`. That is capture-side and roll-sensitive, so it waits until after 10-13 under the exam
  merge policy.
- **T+2 NBP presence is unverified** (design note, EF §10k covers T+1). A cycle without the T+2 maximum is skipped.
  The fallback has no T+1/T+2 `forecasts_long` rows before the local day. The re-run's
  `unavailable.lead2.fair_value:missing_point_in_time_forecast` measures this.
- **Unselected bands are unbooked** (`descriptor:book_not_captured`): 88a books its selected, reward-eligible
  universe only (111a, defect 3).
- **T+0 served lineage:** see above.

## Verification

- New `tests/market/test_maker_plugin_111j.py` (9 tests) uses the production writers:
  - `SharedForecastPayloadCAS.put` plus `parse_market_invariant_attestation(nbp_raw_payload(...))`, with a
    national cycle holding T+0 and T+1 maxima in the T+0 folder and an empty T+1 folder;
  - `token_rows_from_event` plus `MarketMicrostructureStore.write_token_rows`, for a batch after the run date;
  - `EvidenceStore`, for 88a;
  - `get_process_active_serving_bundle` plus `serving_bundle_lineage`, with no pointer.

  It covers:
  - a T+1 band end to end;
  - the T+1 slot actually selected (shifted-column control);
  - a cycle lacking the target;
  - the bulletin location alone;
  - token-id and partition mismatches;
  - point-in-time precedence;
  - no batch at all;
  - an unreadable pooled manifest;
  - research-unbound T+0 plus `HORIZON_NOT_ELIGIBLE`.

  Run against the unfixed `134be204` source, 8 of the 9 fail. The T+0 test documents behaviour that was already
  correct.
- Changes to 111a tests:
  - `test_token_batch_after_minute_is_a_reported_coverage_limit` asserted the rule changed in cause 3. It is now
    `..._is_identity_only`.
  - The compression assertion compares the band projection, because token ids are identity-only.
- Through `scripts\ops\workstation_heavy.ps1`: **1,476 passed, 13 skipped**; the one failure was the new test file
  being untracked, fixed by committing it. The run covered:
  - all plugin suites and 88a capture;
  - microstructure, shared-CAS and payload-persistence;
  - `test_release_serving.py` and `tests/maker_core`;
  - the schema-registry, import-architecture, agent-docs, path-policy and module-size audits.

  The final head's GitHub CI is recorded in the handback reply.

## Exact production re-run command

Run it on the production checkout in the admitted 00:30–09:00 window, under the shared lease. It uses:

- a **new detached worktree** at the pushed head;
- `python -B -P` with a strict module-path probe;
- a **new** output directory.

Fill `$sha` from `git ls-remote --exit-code origin refs/heads/codex/weather-maker-plugin-20260925`. The production
agent owns verifying local paths; this workstation has not accessed them.

```powershell
$repo = (Resolve-Path .).Path
$sha = '<pushed head of codex/weather-maker-plugin-20260925>'
$wt = Join-Path $repo 'scratch\w\111j-rerun'
$out = Join-Path $repo 'data\alerts\weather-plugin-111j-20260926'
if (Test-Path -LiteralPath $wt) { throw "worktree path exists: $wt" }
if (Test-Path -LiteralPath $out) { throw "output exists: $out" }
git -C $repo fetch origin codex/weather-maker-plugin-20260925
git -C $repo worktree add --detach $wt $sha
if ((git -C $wt rev-parse HEAD) -ne $sha) { throw 'worktree is not at the pushed head' }
$python = Join-Path $repo 'venv\Scripts\python.exe'
$src = Join-Path $wt 'src'
$priorPythonPath = $env:PYTHONPATH
. (Join-Path $repo 'scripts\ops\workload_admission.ps1')
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload 'WeatherPluginDryRun-111j'
if ($null -eq $lease) { throw 'Dry run not admitted; do not start Python.' }
try {
    $env:PYTHONPATH = $src
    $probe = @(& $python -B -P -c "import weather.market.maker_plugin_runner as r, weather.market.maker_plugin_sources as s, weather.market.maker_plugin.universe as u, maker_core; [print(m.__file__) for m in (r, s, u, maker_core)]")
    if ($LASTEXITCODE -ne 0 -or $probe.Count -ne 4 -or @($probe | Where-Object { -not $_.StartsWith($src + '\') }).Count) {
        throw "Module path probe failed: $probe"
    }
    & $python -B -P -m weather.market.maker_plugin.dry_run `
        --date 2026-09-26 `
        --data-root (Join-Path $repo 'data') `
        --output $out `
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
git -C $repo worktree remove $wt
```

Accept "evaluates bands end to end" when `report.md` shows:

- **`end_to_end.lead1` > 0.** This is the landing condition. Also record `end_to_end.lead2`.
- `band_basis.lead1.condition_identity` and `band_basis.lead1.point_in_time_capture` both appear, and
  `descriptor:band_identity_mismatch` is absent or explained.
- `band_tokens.events_with_batch` is near 48 and `band_tokens.batch_after_run_date` is near 24. An event whose
  token file was moved by closed-day handling shows as `band_tokens.missing_file`.
- `nbp_blobs.verified` > 0, `files_read.nbp_pool_manifests` > 0, and no `nbp:` or `nbp_pool_manifests:` reasons.
- T+1 fair values show `model_id` `nbp-v2-piecewise-linear`.
- `fair_value:served_snapshot_release_unbound` persists for T+0 (expected), with T+0 decisions
  `HORIZON_NOT_ELIGIBLE`; informed T+1/T+2 decisions are `MISSING_CONSERVATIVE_FILL_BOUND` (0 legs by design).
- `cache.reloads` = 0 and `status` COMPLETE.

The run is falsified if `end_to_end.lead1` is 0 with `band_identity_mismatch` (discovery disagrees with token
capture) or `fair_value:missing_point_in_time_forecast` at lead 1 (the T+0 folders do not retain cycles with the
T+1 maximum). Either is then a genuine capture limit, to be reported, not patched.

## Per-file adoption disposition

No production closure was read. **Actual closure membership is UNDECIDABLE here.** Run
`scripts\ops\roll_verdict.ps1 -Branch origin/codex/weather-maker-plugin-20260925` before integration. From source,
no module outside the plugin imports these files; the only other reference is a schema name in
`schema_registry_recent_data.py`, which is unchanged. No `schema_registry*` file changed.

| Changed in 111j | Disposition |
| --- | --- |
| `src/weather/market/maker_plugin/{fair_value,universe}.py` | UNDECIDABLE; provider changes, plugin-only importers |
| `src/weather/market/maker_plugin_{sources,runner}.py` | UNDECIDABLE; diagnostic runner only |
| `tests/market/test_maker_plugin_111j.py`, `test_maker_plugin_111a.py` | Test code |
| `docs/operations/maker-core-contracts.md`, fixtures README, this report, index | Documentation, roll-free |

## Not done

- No production or mirror reads or writes; no credential or `.env` access.
- No venue calls, Scheduler changes, 88a or snapshot/CLOB capture changes, scoring, fitting, promotion or live
  trading.
- No merge to master.
- No release, pointer or model identity was invented. The T+0 captured-identity binding is specified, not built.
- No `docs/research/maker-replay-*` file was touched.

## Branch and commits

Branch `codex/weather-maker-plugin-20260925` (draft PR #96):

- fix commit `ec08bf75`;
- `origin/master` merged in `62b83321` (docs only);
- report and index in the following commits.

Resolve the final head with `git ls-remote`.

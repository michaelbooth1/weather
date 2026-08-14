# Workstation report 2026-09-65a — panel-floor provenance

## Verdict

**NO CROSS-HOST FLOOR VERDICT IS POSSIBLE FROM THE PANEL ARTIFACT: THE RETAINED
PAIRED PANEL HAS NO FLOOR OR `high_so_far` COLUMN.** The committed extract keeps
all **12,289** snapshot rows and leaves `floor_bucket` and
`floor_source_field` empty on every row. It does not substitute a floor derived
later from replay inputs and call that value panel provenance.

The requested Denver trace nevertheless identifies the panel-side mechanism.
For Denver `2026-06-08` snapshot `20260608T030552-0400`, later replay rebuilt
`high_so_far = 91` from the captured `wu_current.max_since_7am_c = 91` while WU
history was unavailable. The same record had current temperature `68`; the
current-max diagnostic quarantined the 91 for that 23-degree gap, but the
observed-floor path had already admitted it. Raw HGB probability on the
realized `82-83°F` band was `0.006300351957866627`; the captured served
probability was `0.5206313021403224`; exact distribution calibration hard-zeroed
both buckets 82 and 83 below replay floor 91, yielding the panel's `0.0`.

This is **not** the `forecast_high`/post-snapshot leakage shape. The 91 was in
the immutable source payload captured at the snapshot. The problem is that the
panel feature row and floor were reconstructed later under replay code; they
were not the feature row or floor recorded by serving in June. Production still
owns the authoritative served-floor join. This report supplies the join keys,
the missing-floor fact, and the trace rather than claiming that cross-host
verdict.

This was an instrument/provenance audit. There was **no candidate, fitted
parameter, endpoint comparison, or accept rule**. Reading C was permitted on
those grounds and spent no alpha. Campaign accounting remains **7 of 20 spent,
13 available**; decision 10 remains **CLOSED UNUSED** and is not reassigned.

## Committed extract

| Property | B | C |
| --- | ---: | ---: |
| Snapshot rows | **4,636** | **7,653** |
| Date clusters | 23 | 27 |
| Market clusters | 12 | 12 |
| Market-days | 204 | 320 |
| Latest target date | 2026-06-30 | 2026-07-30 |

Nothing is pooled across the `2026-07-31` boundary. The exact census and code
trace are not statistical endpoints, so crossed intervals, observed-effect
power, and campaign MDE are not applicable.

The artifact is
`docs/roadmap/pit-panel-floor-2026-09-65a.csv`, with its manifest and checksum
beside it. It has the exact requested columns and **990,983 bytes**, below the
explicit 1,000,000-byte cap. No row was dropped. To fit the full roster,
probabilities are serialized to nine significant digits; the maximum absolute
serialization error is `4.999590741405768e-10`, declared in the manifest.

| Evidence | SHA-256 |
| --- | --- |
| Panel-floor CSV | `966ff8cb85c03121022341cc87da6ccaabdc67609d744bbc001b95f4ba96eaad` |
| Manifest JSON | `9361c19f5b7a900c9e3a519ce36dadec5e3b65a667a99743b51f3bfb9f8bc59b` |
| Checksum file | `fdd2577b1d51f87abaf25d0e5f5f61470608fc573074bf36dde633b9fe208809` |
| Extract script | `9cef1db40ad8396237b2de9e690afe86a2b5ed2758d629d8aac1309097e95d1b` |
| Retained paired input | `4352e77692893c3ac36add9653eabfe0d014de7a02bf083ec6c10e2944dc4e88` |
| Retained repaired band rows | `9a70ac80143a7eea9b14003b2f992413d622b167ce35ea4be54273cfdf3e27ae` |

Band identity is restored by an exact full-row-key join to the retained repaired
`band-score-rows.csv` from the same `-09-44a` run. The sole `outcome == 1` row
identifies the realized band; no outcome value is emitted. Missing two-degree
upper edges are parsed from `range_label`, matching
`market_microstructure_features.py:99-120`. The artifact contains no market
price, other outcome, or fitted quantity.

## Where `feature_row` comes from

### The named master chain

The chain in the handoff is a later reconstruction from captured inputs:

1. `snapshot_store.py:2953-3018` builds the replay payload. Its contract says
   the merged `sources` are exactly what `estimate_distribution` consumed, and
   the payload records the build's `built_at` plus those sources. The payload is
   appended to `replay_inputs.jsonl` at `snapshot_store.py:3058`.
2. `backtesting/replay.py:66-79` loads captured `replay_inputs.jsonl` first and
   only fills absent snapshot IDs from the separately labelled reconstructed
   file. `parse_built_at` at `:87-98` recovers the exact model-build `now`.
3. `pooled_candidate_replay.py:632-762` loads the manifest-pinned snapshot IDs.
   At `:699` it indexes replay records; at `:705` it excludes labelled
   reconstructions unless the manifest explicitly permits them; and at
   `:717-762` it calls `_record_feature_row` and stores the result by
   `(market_id, snapshot_id)`.
4. `_record_feature_row` at `pooled_candidate_replay.py:589-625` parses
   `built_at`, reads `record["sources"]`, derives the effective cutoff, and calls
   `model.extract_live_features(sources, cutoff_hour, now=now)` at `:607`.
   Therefore `feature_row` is **not the feature row captured at serving**. It is
   rebuilt later from the captured merged sources and captured build time under
   the replay code/model artifacts in use for the run.
5. The handoff's final chain is literal at
   `pooled_candidate_replay.py:1319-1342`: fetch that rebuilt feature row,
   parse the band at `:1320`, call `band_prediction_record` at `:1322`, and pass
   `band_row["observed_floor_bucket"]` into calibration at `:1334`.
   `variant_prediction_runtime.py:354-408` reads
   `record["high_so_far"]` at `:363`, rounds it into `floor_bucket` at `:369`,
   and exposes it as `observed_floor_bucket` at `:408`.

### The retained paired panel's exact producer

The `-09-44a` panel used a retained one-off measurement rather than emitting
the `pooled_candidate_replay` feature row. Its ignored source is
`scratch/runs/market-gap-seasonal-2026-09-34a/measure_market_gap_seasonal.py`,
SHA-256 `1de8b986d4bd75a38879345bb83f068e956b13f7d2454cdd5e3249f5a6d93c13`.

- `pin_cell` at `:352` reads **only** each market-day's captured
  `replay_inputs.jsonl` (`:357`), not `replay_inputs_reconstructed.jsonl`.
- At `:1217-1233` it takes the retained record, performs full model replay, and
  separately calls `extract_live_features(record["sources"], effective_hour,
  now=parse_built_at(record))`.
- `scratch/runs/gap-remeasure-repaired-2026-09-44a/analyze_paired.py`, SHA-256
  `d9005f28be77ffb1aa87a043847c6bf54ef40cc9353b0971643cb13b00259478`,
  assigns the predecessor's later-replay probability to `control_probability`
  and the repaired later-replay probability to `repair_probability` at
  `:152-153`, then writes `paired-band-rows.csv` at `:158`.

So the exact panel has full-fidelity **captured source records**, not approximate
source reconstruction, but its feature row and floor semantics are still
reconstructed later. The paired CSV retained neither one.

## Is the replay floor point-in-time?

**The input evidence is point-in-time; the derived row is later.** A value only
observed after the snapshot cannot enter this path:

- the replay record contains the source payload captured before the model write
  and the exact `built_at` used by that model build;
- `model_base.py:23-30` filters observation rows to the effective cutoff;
- `model_base.py:46-123` constructs `effective_observed_high` only from
  cutoff-aligned WU history, the captured current/station temperature, and the
  captured current/station max-since-07:00;
- forecasts and climatology are not arguments to that observed-high helper;
- `variant_prediction_runtime.py:363-369` keeps `forecast_high` separate and
  derives the floor only from `high_so_far`.

The Denver failure is therefore not a future actual observation reaching
`high_so_far`. It is a captured-value semantics problem exposed by later code:
`INTRADAY_CUTOFF_HOURS` begins at 07:00
(`model_constants.py:26`), and `intraday_cutoff_hour` returns that first value
when wall time is earlier (`model_distribution.py:1536-1539`). With empty WU
history, `effective_observed_high_context` admits `current_max` whenever the
effective cutoff is at least 7 (`model_base.py:79-80`). Thus a captured
pre-reset max-since-07:00 can become the replay floor even though it is
available at the snapshot rather than after it.

The remaining temporal caveat is code provenance: replay applies later feature
and floor code to an older captured record. Point-in-time input capture does
not prove identity with the floor served under the historical code version.

## Denver `2026-06-08`, one snapshot end to end

Chosen panel row: `B / denver / 2026-06-08 /
20260608T030552-0400`, record hash
`b78d94c54bb63f1d72d414c5795946351ec705421b2838fcc7c48652f3bf3e26`.

1. **Captured inputs.** The model build time was
   `2026-06-08T01:05:51.818932-06:00`. WU history was unavailable. The captured
   `wu_current` payload, fetched at `01:05:51-06:00`, had observation time
   `00:56:58-06:00`, `target_date_match=true`, `temp_c=68`, and both
   `max_24h_c=91` and `max_since_7am_c=91`.
2. **Cutoff and floor reconstruction.** No WU rows existed, so the pre-07:00
   model build received effective cutoff 7. `effective_observed_high_context`
   took max(current temperature 68, current max 91), producing
   `high_so_far=91`. `band_prediction_record` would therefore report
   `observed_floor_bucket=91` with source field `high_so_far`.
3. **Quarantine did not revoke the floor.** `current_max_trust_features` at
   `feature_store.py:347-420` classified the 23-degree max/current gap as
   `current_max_current_temp_gap`, disposition `quarantined`, and set
   `current_max_quarantined_flag=1`. That trust calculation controls
   `trusted_current_max`; it runs separately from the already-derived
   `effective_observed_floor_high`. `model_distribution.py:185-195` carries both
   values, and `:283-300` includes the effective observed bucket in
   `hard_floor_bucket` even when the trusted-current-max floor is absent.
4. **Realized band.** The retained tape row is `kind=eq`, `value=82`, blank
   explicit upper edge, label `82-83°F`. The label fallback makes
   `value_hi=83`. Settlement is 82°F, the lower degree, so this is the one
   realized band.
5. **Probability path.** The raw HGB projection on that band was
   `0.006300351957866627`. The captured serving tape carried
   `0.5206313021403224`. Later replay first applies a soft `1e-6` multiplier
   below the floor (`model_distribution.py:952-956`, `:1457-1460`), so that
   step alone does not make an exact zero. The exact zero occurs at
   `apply_exact_distribution_calibration`:
   `model_distribution.py:536-547` passes floor 91, and
   `calibration_runtime.py:351-410` explicitly sets every bucket below the floor
   to `0.0`. Buckets 82 and 83 are both below 91, so their band projection is
   exactly `0.0`. The paired control and repair rows are both zero.

This explains Denver's panel probability without the lost-upper-edge defect
and without a forecast leaking into `high_so_far`. It also explains why the
blind-feature repair was irrelevant to the zero. It does **not** replace the
production floor tape: the committed panel artifact still has no retained
floor column for the production join.

## Verification

The bundled Codex runtime is Python 3.12; nothing was installed and no network
endpoint was called.

- The generator passed `py_compile`.
- A second complete generation reproduced the CSV hash exactly.
- An independent PowerShell `Import-Csv` pass found 12,289 unique snapshot
  keys, B=4,636, C=7,653, latest date `2026-07-30`, zero non-empty floor values,
  and zero non-empty floor-source values.
- `git diff --check` passed.
- `python -m weather.operations.agent_docs_audit` passed after the report was
  added.

## Roll verdict

`scripts\ops\roll_verdict.ps1 -Branch
codex/workstation-is-the-panel-floor-the-served-floor-2026-09-65a` returned
exit **0**, **ROLL-FREE**. This host's local `master` is intentionally behind
the requested `origin/master`, so the cumulative comparison reported 57 files
and seven importable upstream files; the script classified all seven `free`.
The mission's artifact commit from base `8b0180ba` is exactly four files, none
importable. The final report adds one Markdown file and cannot enter a retained
Python closure.

| Changed file | Snapshot | CLOB | Observation-trigger | CLOB-enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `docs/roadmap/pit-panel-floor-2026-09-65a.csv` | none | none | none | none | Roll-free evidence CSV |
| `docs/roadmap/pit-panel-floor-2026-09-65a-manifest.json` | none | none | none | none | Roll-free evidence manifest |
| `docs/roadmap/pit-panel-floor-2026-09-65a.sha256` | none | none | none | none | Roll-free checksum |
| `tools/research/build_pit_panel_floor_extract_09_65a.py` | none | none | none | none | Roll-free one-off research tool |
| `docs/roadmap/agent-report-2026-08-20-workstation-panel-floor-provenance.md` | none | none | none | none | Roll-free Markdown |

## Explicitly not done

- No replay, floor, calibration, scoring, serving, or probability-mass code was
  changed. The serving floor was not weakened.
- No candidate, fitted parameter, endpoint comparison, accept rule, alpha
  allocation, release, promotion, activation, pointer, order, or trade was
  produced.
- No production `data/`, workstation mirror, settlement ledger, snapshot tape,
  release store, scheduled task, collector, supervisor, or live process was
  written, registered, started, restarted, or mutated.
- No provider or exchange endpoint was called and nothing was installed.
- No PR, merge, master update, production checkout change, or branch deletion
  was performed.

## Reproduction and production-host acceptance

On the workstation holding the retained paired evidence:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
Set-Location $repo
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

Get-FileHash -Algorithm SHA256 `
  .\scratch\runs\gap-remeasure-repaired-2026-09-44a\paired-band-rows.csv
Get-FileHash -Algorithm SHA256 `
  .\scratch\runs\gap-remeasure-repaired-2026-09-44a\band-score-rows.csv
& $python .\tools\research\build_pit_panel_floor_extract_09_65a.py
Get-FileHash -Algorithm SHA256 `
  .\docs\roadmap\pit-panel-floor-2026-09-65a.csv

$rows = Import-Csv .\docs\roadmap\pit-panel-floor-2026-09-65a.csv
$rows.Count
($rows | Where-Object stratum -eq 'B').Count
($rows | Where-Object stratum -eq 'C').Count
($rows | Where-Object { $_.floor_bucket -ne '' }).Count
```

Expected input hashes and output hash are in the evidence table; expected
counts are `12289`, `4636`, `7653`, and `0`.

Production-host acceptance uses committed paths only; the ignored raw panel is
not claimed to exist there:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-is-the-panel-floor-the-served-floor-2026-09-65a'
$report = 'docs/roadmap/agent-report-2026-08-20-workstation-panel-floor-provenance.md'

git rev-parse $branch
git show "${branch}:$report"
git show "${branch}:docs/roadmap/pit-panel-floor-2026-09-65a.sha256"
git show "${branch}:docs/roadmap/pit-panel-floor-2026-09-65a-manifest.json"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

Artifact/script commit: `d6303771b32479059e9b6ee7d6693a6435ad57b8`.

Branch:
`codex/workstation-is-the-panel-floor-the-served-floor-2026-09-65a`.

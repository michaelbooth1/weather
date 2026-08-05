# Agent Report - 2026-07-22 Workstation Distribution-Stage Attribution

## Outcome

**ACTIONABLE AS A HISTORICAL DIAGNOSTIC; BLOCKED AS CURRENT-CODE EVIDENCE.** A
memory-bounded scan scored 6,670,906 stage-attribution rows from 533 settled
folders (569 scanned). The largest broad historical gains came from
`feature_blend`, while `forecast_pull` exposed a sharpness/calibration
tradeoff: it improved Brier by `-0.00779` but worsened log loss by `+0.07028`
and narrowed effective band spread by `-0.04506`.

That tradeoff is important, but it cannot justify a current serving change.
There are zero current-code feature-model component rows. The 270,897
feature-model forecast-shape rows end on 2026-06-21 and carry stale/missing
runtime identity.

## Design and provenance

- Read-only input: the 2026-07-22 workstation snapshot mirror described in
  `agent-report-2026-07-22-workstation-phase0-parity.md`.
- Output:
  `scratch/workstation-research-output/workstream_a/stage_attribution/distribution_stage_attribution.json`.
- Output SHA-256:
  `03459CB29C24F81AEFE4FCC595B7CC52417AB3AFFDCBC977152AF6142DE33C31`.
- Unit: probability-band attribution row, with deltas against the immediately
  preceding recorded stage for the same snapshot.
- The scan holds one event folder at a time; it does not materialize the full
  corpus.

The mixed-identity 569-folder scan is not bound by a sealed per-input inventory
or a full start/completion execution-identity manifest. Only the resulting
output file is hashed here. This limits the scan to historical diagnostics even
apart from the stale/missing row identities described below.

Because these are recorded component tapes from multiple historical code
identities, the rows are neither a randomized ablation nor a clean
current-code replay. Counts are useful for locating failure modes; causal
claims require regenerated component tapes on a pinned current-code corpus.

## Overall result

Across 5,824,126 rows with a preceding stage, the recorded pipeline's mean
adjacent-stage deltas were Brier `-0.00403`, log loss `-0.01019`, and eventual
winner probability `+0.03706`. These mixed-stage totals should not be treated
as a candidate score because stages activate on different subsets and code
eras.

| Component | Rows | Brier delta | Log-loss delta | Winner-p delta | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- |
| feature_blend | 822,118 | -0.01619 | -0.05476 | +0.14364 | largest broad historical gain |
| current_observed_floor | 846,450 | -0.00290 | -0.01353 | +0.02110 | broad modest gain |
| late_day_lockin | 842,974 | -0.00160 | -0.00538 | +0.01969 | modest positive when recorded |
| forecast_pull | 271,788 | -0.00779 | +0.07028 | +0.09672 | Brier gain bought with severe tail overconfidence |
| final_model | 846,780 | -0.00009 | +0.00028 | -0.00164 | essentially neutral / slightly worse log loss |
| current_max_boundary_guard | 4,048 | +0.00005 | +0.00008 | -0.00076 | small historical regression |
| high_has_stood_lockin | 2,486 | -0.03418 | -0.09282 | +0.30473 | strong but extremely selective |

Forecast pull's late/final log-loss regression appears across nearly every US
market rather than in one isolated city. Toronto is the notable small
improvement. The output also identifies 621 blocked bottom-location
winner-mass guardrail cases; the largest includes NYC on 2026-06-10, where
forecast pull reduced eventual-winner probability by about `0.529` and
worsened Brier by about `0.073`.

## Current-identity gate

`forecast_shape_scope.status` is `BLOCK`:

- current-code component rows: `0`;
- current-code feature-model forecast-shape rows: `0`;
- stale feature-model forecast-shape rows: `270,897`;
- latest such row: 2026-06-21 06:49:36 UTC.

The generated unblock action now requires a nonzero, complete current-code
feature-model component population on the pinned corpus, with zero current-code
feature-model forecast-shape rows. Explicit runtime identity and paired
per-fleet-date inference remain required before this can become decision
evidence.

## Engineering result

`distribution_stage_attribution` now aggregates one folder at a time. The old
implementation reached roughly 27 GB while retaining millions of rows; the
bounded implementation completed the full scan. Focused tests cover semantic
equivalence, row bounding, malformed/partial inputs, current-identity scope,
and report assembly.

## Disposition

1. Do not tune serving constants from the mixed-identity stage means.
2. Use the current pinned replay experiments for decisions.
3. Treat forecast pull as the highest-priority sharpness/calibration target:
   preserve its Brier lift while explicitly guarding log loss and bottom-band
   winner mass.
4. Regenerate component tapes under one current identity before calling any
   stage causal or promotable.

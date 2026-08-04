# Chain payload BLOCK triage — 2026-08-04, before the lock

On 2026-08-03 the daily chain ran **all 23 steps `ok`** and still terminated
`deferred / upstream_pipeline_not_successful`, because five steps reported `BLOCK` inside
`$chain.summary`. Step status says a step *executed*; the payload carries the verdict. Reading step
status alone says "healthy" and is wrong.

The open question was: **which of these clear when the release pointer is created, and which are
real defects?** Spending the 7-day build window without knowing would have been careless. Triaged
against the host on 2026-08-04 07:20–07:35.

**Conclusion: none of the five blocks the lock.** They split into two groups with completely
different causes and completely different futures.

## Group A — release-pointer dependent. The lock IS the fix.

### `live_variant_settlement_scorecard`

Reported `eligible_prediction_coverage = 0.0`, `valid_prediction_partition_count = 0`, and
`missing_or_invalid_partition_count = 103564` of 103564 — with
`missing_expected_snapshot_partition_count = 0`. **Nothing is missing; everything is invalid.** Its
12 blockers are one per market, each `invalid_eligible_partitions: N of N eligible partitions
failed validation`.

The source rows say why. From
`data/snapshots/highest-temperature-in-atlanta-on-august-2-2026/variant_predictions_long.csv`:

```
release_id                   : (empty)
release_manifest_sha256      : (empty)
release_pointer_sha256       : (empty)
release_sequence             : (empty)
release_identity_status      : research_unbound_non_countable
release_identity_reason      : no active release pointer; diagnostic capture is
                               release-unbound and non-countable
serving_model_binding_status : release_unbound_legacy_base_model
serving_model_binding_reason : no verified active-release base-model serving graph is bound
```

**The partitions fail validation precisely because there is no active release pointer.** The system
is correctly stamping pre-release capture as non-countable. This is the designed pre-release state,
identical in kind to `active_release_verification_failed` — the first of the 69 blockers in
`production_readiness_gate.json`, which `status.ps1` already documents as expected.

**Expect it to clear when release #1 creates the pointer.** If it does *not* clear after the
pointer exists, that is a real defect and worth escalating.

## Group B — the model trails the market. These will NOT clear on the lock.

### `ten_minute_model_performance`

`ten_minute_performance_gate` = BLOCK on 2 blockers, over 564 corpus market-days:

| Gate | Measured | Tolerance |
| --- | ---: | ---: |
| `weak_slot_brier_regression` | model trails market by **0.0176** | 0.0030 |
| `weak_slot_logloss_regression` | model trails market by **0.0833** | 0.0100 |

Remediation recorded by the gate itself: *"keep promotion blocked; run predawn weak-slot
remediation candidate."*

**The gate is working correctly and blocking promotion for the right reason.** This is the
project's standing central condition — we do not beat the market — and no release pointer changes
it. It clears when the model improves, not before.

Worth noting from the same payload, because it is the clearest statement of the real gap:
`partition_market_top_is_winner_rate = 0.4324` versus
`partition_model_top_is_winner_rate = 0.2877`, with `winner_catchup_gap = -0.1104`. The market's
mode is winner 43% of the time; ours 29%.

`candidate_ten_minute_gate` is **PASS** — the candidate lane is fine. It is the served lane that
trails.

### `hourly_model_performance`

`hourly_performance_gate` = BLOCK, same family of check. Not separately traced; treat as Group B
unless shown otherwise.

### `rollup_freshness`

1 blocker, `latest_required_artifact = ten_minute_model_performance`. Downstream of Group B rather
than an independent finding.

### `trading_evidence`

BLOCK carrying `mm_maker_countability_gate_status = BLOCK` and `taker_quality_status = BLOCK`, with
`mm_paper_gate_status = OPEN` and `taker_pnl_evidence_status = SETTLEMENT_SCORED_ZERO_FILL`. Mixed;
the maker-countability half is release-bound, the taker half reflects zero fills. Not lock-blocking
either way.

## What this means for the build window

- **Do not treat Group A as a defect.** It is the pre-release state and the lock resolves it.
- **Do not wait for Group B to clear.** It cannot. Release #1 freezes the June base models; it does
  not improve them. Promotion stays blocked after the release, and that is expected — see
  `release-one-does-not-refresh-base-models` in memory.
- **Do check Group A actually clears once the pointer exists.** That is the cheap, high-value
  verification immediately after the build, and nobody has ever observed it happen.

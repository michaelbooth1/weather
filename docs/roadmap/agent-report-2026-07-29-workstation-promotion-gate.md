# Workstation promotion-gate and serving-floor report — 2026-07-29

## Implemented gate table

| Gate criterion | Implemented threshold and consequence | Candidate lane actually scored | Code path |
| --- | --- | --- | --- |
| Family admission | The candidate and decision builders retain only markets whose native unit equals `family_unit`; the current run is `F`. A non-family market is not scored. | Lane-independent routing | `pooled_candidate_scoring.py::family_unit_matches`; `pooled_candidate_replay.py::attach_pooled_candidate_probabilities`; `promotion/readers.py::_family_specs` |
| Pinned-corpus integrity | Zero corpus warnings; failure makes the global replay gate false. | Lane-independent identity evidence | `pooled_candidate_replay_diagnostics.py::replay_gate_status` |
| Same-identity replay fidelity | If same-identity rows exist, maximum L1 must be `<= 0.01`; failure makes the global replay gate false. | Incumbent replay identity, not candidate skill | `pooled_candidate_replay_diagnostics.py::replay_gate_status` |
| Candidate rows exist | No scored `candidate_p` rows is an immediate `BLOCK`. | Post-blend | `pooled_candidate_replay_diagnostics.py::market_verdict` |
| Blocked split audit | `split_audit.ok` must be true. Any leakage finding makes blocked validation fail. | Lane-independent population audit | `pooled_candidate_scoring.py::blocked_candidate_validation_gate` |
| Daily-first evidence | At least 2 `(market_id, target_date)` groups. Fewer makes blocked validation fail. | Lane-independent count over scored post-blend rows | `pooled_candidate_scoring.py::daily_first_candidate_comparison`; `::blocked_candidate_validation_gate` |
| Daily-first versus incumbent | Candidate Brier minus current Brier must be `<= 0.003`. Failure makes blocked validation fail. | Post-blend `candidate_p` | `pooled_candidate_scoring.py::blocked_candidate_validation_gate` |
| Daily-first versus market | Candidate Brier must be `<= market Brier + 0.003`. Failure makes blocked validation fail. | Post-blend `candidate_p` | `pooled_candidate_scoring.py::blocked_candidate_validation_gate` |
| Row-weighted versus incumbent | Candidate Brier minus current Brier must be `<= 0.003`. Failure is an immediate `BLOCK`. | Post-blend `candidate_p` | `pooled_candidate_replay_diagnostics.py::market_verdict` |
| Blocked validation aggregate | The complete daily-first blocked gate must pass. Failure is an immediate `BLOCK`. | Post-blend for skill criteria | `pooled_candidate_replay_diagnostics.py::market_verdict` |
| Proven improvement | Candidate Brier minus current Brier must be `< 0`; otherwise the market stays `SHADOW`. | Post-blend `candidate_p` | `pooled_candidate_replay_diagnostics.py::market_verdict` |
| Row-weighted market tolerance | Candidate Brier must be `<= market Brier + 0.003`; otherwise the market stays `SHADOW`. | Post-blend `candidate_p` | `pooled_candidate_replay_diagnostics.py::market_verdict` |
| Trust | Location trust must be `>= 25`; otherwise the market stays `SHADOW`. | Lane-independent location evidence | `pooled_candidate_replay_diagnostics.py::market_verdict` |
| Decision materialization | A family market can receive `PROMOTE_CANDIDATE` only from `PASS`; global replay failure or blocked-validation failure converts an apparent pass to `BLOCK`. | Inherits the post-blend verdict | `reporting/promotion/decisions.py::build_family_decisions` |

The lane attribution is unambiguous. `attach_pooled_candidate_probabilities`
normalizes the candidate, saves that value as `candidate_preblend_p`, optionally
calls `apply_current_blend_guardrail`, normalizes again, and leaves the blended
value in `candidate_p`. Every skill function above reads `candidate_p`.
`candidate_preblend_p` is exported but never passed to the promotion gate.

The pinned run's lane-independent global identity evidence is green: zero
corpus warnings and same-identity maximum L1 `0.00000 <= 0.01000` over 5,923
snapshots. Those are identity checks, not POST skill scores.

### Requested markets on the exact POST population

The POST population is selected by captured runtime-commit ancestry, not date:
128,271 valid band rows in 11,661 partitions after excluding the one POST
collision partition. The frozen candidate vector and regime bridge did not
change during the pass.

| Criterion | Atlanta actual | Atlanta | Toronto actual | Toronto |
| --- | ---: | --- | ---: | --- |
| Family admission | native `F`, run family `F` | PASS | native `C`, run family `F` | NOT EVALUATED |
| Scored candidate rows | 10,428 rows / 948 snapshots | PASS | 0 rows / 0 snapshots | NOT EVALUATED |
| Blocked split audit | 0 leaks across 9 splits; required 0 | PASS | no F-family candidate population | NOT EVALUATED |
| Daily-first days | 7; required `>= 2` | PASS | 0; no candidate lane | NOT EVALUATED |
| Daily-first candidate Brier | `0.049159572` | — | missing | NOT EVALUATED |
| Daily-first versus incumbent | `0.049159572 - 0.079214538 = -0.030054966`; limit `<= +0.003` | PASS | missing | NOT EVALUATED |
| Daily-first versus market | `0.049159572 - 0.032483947 = +0.016675625`; limit `<= +0.003` | **FAIL by 0.013675625** | missing | NOT EVALUATED |
| Row-weighted candidate Brier | `0.050799658` | — | missing | NOT EVALUATED |
| Row-weighted versus incumbent | `0.050799658 - 0.072405528 = -0.021605870`; limit `<= +0.003` | PASS | missing | NOT EVALUATED |
| Proven better than incumbent | `-0.021605870 < 0` | PASS | missing | NOT EVALUATED |
| Row-weighted versus market | `0.050799658 - 0.035166853 = +0.015632805`; limit `<= +0.003` | FAIL / SHADOW criterion | missing | NOT EVALUATED |
| Location trust | 55; required `>= 25` | PASS | not used because Toronto is outside the family candidate run | NOT EVALUATED |
| Effective candidate result | blocked validation fails market tolerance | **BLOCK** | the F-family decision builder contains no Toronto candidate | **NO TORONTO VERDICT** |

Toronto is not a second failing candidate. It is absent by construction from
the F-family artifact, allowlist, and candidate vector. Reporting Toronto's
separate C-family serving-gauntlet or early-hour numbers here would answer a
different question and would violate the POST-only comparison contract. A
Toronto candidate verdict requires a canonical C-family candidate run.

## Pre-blend counterfactual

**No: the same Atlanta candidate still would not pass if the gate saw its
pre-blend output. No criterion verdict flips.**

Holding the POST population, incumbent, market, split audit, day count, and
trust fixed gives:

| Criterion | Post-blend | Pre-blend counterfactual | Verdict change |
| --- | ---: | ---: | --- |
| Daily-first candidate Brier | `0.049159572` | `0.036841072` | — |
| Daily-first delta versus incumbent | `-0.030054966` PASS | `-0.042373466` PASS | none |
| Daily-first delta versus market | `+0.016675625` FAIL | `+0.004357125` FAIL against `+0.003` | none; pre-blend still misses by `0.001357125` |
| Row-weighted candidate Brier | `0.050799658` | `0.041170031` | — |
| Row-weighted delta versus incumbent | `-0.021605870` PASS | `-0.031235497` PASS | none |
| Proven improvement over incumbent | PASS | PASS | none |
| Row-weighted delta versus market | `+0.015632805` FAIL | `+0.006003178` FAIL against `+0.003` | none |

The blend is materially harmful on this POST slice, but it is not the sole
promotion blocker. The large apparent lift remains diagnostic evidence, not a
deployability claim: the blocked split audit is clean, but the candidate still
fails the market tolerance and no active replay contract was built here.
Mission 3's condition is therefore false, so no bypass/projection candidate was
scoped or implemented.

## Serving-path below-floor result

**Actionable sentence: treat the incumbent's below-floor emission as an urgent
serving correctness defect—7,225 of 11,600 POST snapshots with an observed WU
floor published impossible mass, including every floor-bearing snapshot from
local hours 18 through 23.**

This is not inferred from the offline candidate lane:

1. `snapshot_tracker.capture_snapshot` builds the real
   `TorontoHighTempModel` output.
2. `SnapshotStore.write` calls `model_client.bin_probability` for every live
   market band and writes that value directly as
   `snapshots_long.csv:model_probability`.
3. All 128,271 persisted band probabilities exact-joined the frozen
   `recorded_probability` control. Maximum absolute difference was
   `1.1102230246251565e-16`; serving simplex maximum error was
   `6.661338147750939e-16`.
4. Runtime commit and source fingerprint matched the accepted POST bridge for
   every joined snapshot.

### Frequency and mass

| Population | Value |
| --- | ---: |
| POST serving snapshots | 11,661 |
| Snapshots with a numeric printed WU floor | 11,600 |
| Snapshots with no floor yet | 61 |
| Snapshots emitting below-floor mass `> 1e-12` | 7,225 |
| Violation share among floor-bearing snapshots | **62.2845%** |
| Mean below-floor mass per violating snapshot | 0.182520391 |
| Median below-floor mass per violating snapshot | 0.062957937 |
| Maximum below-floor mass | **0.997957938** |
| Cumulative mass across repeated snapshot emissions | 1,318.709823 |

The cumulative value sums repeated predictions and is not a single
probability. The per-snapshot mean, median, and maximum describe the emitted
distribution defect.

Every F market is affected:

| Market | Violating / floor-bearing | Share | Cumulative mass |
| --- | ---: | ---: | ---: |
| Atlanta | 518 / 944 | 54.87% | 142.482610 |
| Austin | 546 / 1,133 | 48.19% | 56.040705 |
| Chicago | 706 / 1,121 | 62.98% | 114.871268 |
| Dallas | 609 / 1,108 | 54.96% | 201.420181 |
| Denver | 600 / 1,075 | 55.81% | 150.621430 |
| Houston | 712 / 1,094 | 65.08% | 171.459429 |
| Los Angeles | 734 / 1,092 | 67.22% | 128.292348 |
| Miami | 1,008 / 1,084 | 92.99% | 99.723156 |
| NYC | 584 / 911 | 64.11% | 88.329770 |
| San Francisco | 768 / 1,094 | 70.20% | 104.721689 |
| Seattle | 440 / 944 | 46.61% | 60.747238 |

The defect occurs at every market-local hour and becomes nearly universal late
in the day:

| Local-hour group | Violating / floor-bearing | Share | Cumulative mass |
| --- | ---: | ---: | ---: |
| 00–02 | 935 / 1,527 | 61.23% | 211.943719 |
| 03–08 | 513 / 3,151 | 16.28% | 1.246862 |
| 09–14 | 1,681 / 2,784 | 60.38% | 62.359704 |
| 15–17 | 1,287 / 1,329 | 96.84% | 192.528989 |
| 18–23 | **2,809 / 2,809** | **100.00%** | 850.630549 |

### Why the floor is already observed

For the 11,600 numeric cases, the accepted integrity bridge reconstructed
`high_so_far` exactly from cutoff-aligned rows in the captured
`replay_inputs.jsonl:sources.wu_history.data.rows`; all 61 null cases also
matched. These are configured Weather Underground prints available to the
serving transaction, not future labels or supporting-source substitutions.
`ROUND_HALF_UP(high_so_far)` is therefore a hard lower bound on the eventual
daily maximum.

The code audit identifies the extraction mismatch that lets the incumbent
violate it:

- the feature path computes `high_so_far = max(temp)` from cutoff-aligned WU
  history rows in `model_features.py::extract_live_features`;
- the distribution/floor path instead asks `row_max_native(history)` for a
  top-level maximum in `model_distribution.py::_estimate_distribution_result`;
- all 11,600 POST snapshots with a numeric row-derived floor had a blank
  `snapshots_long.csv:wu_history_high_c` top-level audit value;
- with `observed_floor_bucket=None`, both
  `distribution_hard_floor_stage` and
  `calibration_runtime.hard_bin_probability` have no floor to enforce.

Thus the model possessed the observed WU rows and persisted the correct
row-derived feature, while the serving distribution took a different,
unpopulated extraction route. This is a train/serve/input-contract correctness
defect, not a choice to price future warming.

## Lock hardening

The reviewed hash-keystone dependency was stacked first because it owns the
live-PID lock logic. The lock now preserves a readable live owner for up to
3,600 seconds, then treats the lock as stale even if that PID is occupied.
Dead PIDs remain immediately recoverable, and malformed/torn locks retain the
existing five-minute fail-closed behavior. This bounds recycled-PID stalls
without shortening legitimate large-payload protection.

The lock file still records only a PID. A process-name check was not added:
`python.exe` would not distinguish a recycled writer from another Python
process, while the requested one-hour bound directly prevents an indefinite
stall.

Focused verification:

```text
tests/collection/test_captured_input_hash.py
11 passed in 0.70s
```

## Evidence and limits

Declared output root:
`C:\Users\Michael\Documents\github\weather\scratch\agent-runs\workstation-promotion-gate-2026-07-31a`

| Output | Bytes | SHA-256 |
| --- | ---: | --- |
| `promotion_gate_post_counterfactual.json` | 67,756 | `c9da3f83cd038905af89c86b0ece5cb7735b6b08cbed7f9c6f9fade7d364fd63` |
| `production_serving_floor_post.json` | 49,144 | `5e4b01f6915aa71dc044056f84aac64f6b14c03e895f727fd102e7e53d4220fd` |

This cycle performed read-only measurement over `data/` and wrote only under
the declared output root plus this report/code/test change. It made no vendor
calls, fit, promotion, pointer, serving, scheduler, capture, mirror, ACL, or
trading change. The analyzed July 2–10 evidence is outside the handoff's
same-day mirror-staleness window; no workstation/source divergence claim is
made.

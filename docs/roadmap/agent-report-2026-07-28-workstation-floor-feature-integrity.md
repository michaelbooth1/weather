# Agent report - 2026-07-28 workstation floor-feature integrity

Status: **STORED AND RECONSTRUCTED `high_so_far` DISAGREE. THE
STORED CAPTURE-TIME RECORD IS NOT CLEAN, BUT THE RECONSTRUCTION ALSO
BACKFILLS VALUES THAT WERE NOT STORED. LOCALIZATION AND `-27g` MISSIONS 2-3
WERE NOT RUN.**

This report executes
`docs/roadmap/workstation-handoff-2026-07-28e-is-the-floor-feature-broken-in-production.md`
from exact `origin/master`
`92769649a3d281af023cbe428cec6f4f6261bd42` on topic branch
`codex/workstation-who-breaks-floor-2026-07-27g`.

## Stored-versus-reconstructed answer first

**`STORED_RECONSTRUCTED_DISAGREE_STOP`**.

The complete 18,793-row comparison has only three states:

| State | Rows | Population share |
| :--- | ---: | ---: |
| Stored null, reconstructed numeric | **7,091** | **37.732%** |
| Both numeric and exactly equal | 11,601 | 61.730% |
| Both null | 101 | 0.537% |
| Numeric disagreement | **0** | **0.000%** |

The maximum numeric absolute delta is exactly `0`. The disagreement is
therefore not a different maximum among mutually available values. It is
whether a value existed at capture time: stored `feature_vector.high_so_far`
is null in 7,192 rows, versus 101 nulls in the frozen reconstruction.

The primary record was selected for all 18,793 snapshots from
`snapshots.jsonl::feature_vector.high_so_far`. All 129 `features.jsonl`
sidecars were present, all 18,793 matching sidecar records were selected,
and every sidecar value corroborated its primary snapshot value. Selection
bound market-day/event identity, snapshot ID, model and feature-schema
identity, and normalized capture instant. The two declared duplicate-ID
collisions were resolved only by their already frozen exact capture
instants.

This is a real disagreement and not a binding failure. Every pinned primary
and sidecar file completed a stable one-pass read; all fixed inputs and the
comparison wrapper were unchanged through the run; the independent retry
postcheck passed; and the final gate deliberately grants no downstream
authority.

## The shape is a sharp capture-era boundary

The missing stored values are broad across markets and local hours but sharp
in calendar/runtime time:

- From June 28 through July 1, every one of 5,931 stored values is null.
- On July 2, 1,200 of 1,677 stored values are null; 1,198 of those are
  reconstructed as numeric.
- From July 3 through July 10, stored and reconstructed values agree on
  every row, including shared nulls.
- Across the exact runtime boundary, all 7,131 earlier captures have a null
  stored value. Reconstruction is numeric on 7,091 and null on 40.
- All 11,662 later captures agree: 11,601 exact numeric pairs and 61
  both-null pairs.

The last capture in the all-null runtime era is Dallas at
`2026-07-02T17:56:46.255747-04:00`, runtime commit `4085a8fb6813` and source
fingerprint `4914e1613f499255`. The first capture in the matching era is
Houston at `2026-07-02T18:14:19.095727-04:00`, runtime commit
`89f3b908a245` and source fingerprint `942d88f6369d5817`.
The transition is therefore bracketed to 17 minutes 32.839980 seconds.
The model version (`v0.5.10 HGBC feature-based ML model`) and feature schema
(`toronto_feature_store_v1.15`) are unchanged across all 18,793 rows.

That is an observed correlation, not a causal attribution. Per the handoff,
the disagreement terminal forbids the replay-input localization needed to
say whether the boundary reflects extractor behavior, source availability,
process state, a restart, or another captured-input difference.

All 11 markets are materially affected. Market-level mismatch shares range
from 36.093% in Los Angeles to 41.481% in NYC. Mismatch shares also span
every market-local hour, from 28.338% at hour 23 to 44.935% at hour 13.
The population is therefore not a small western-market/early-hour pocket;
the apparent hour variation is subordinate to the capture-era break.

## Which trajectory is clean? Neither

The stored path is much more nullable; the reconstructed path is more
numerically complete and therefore exposes more non-monotonic numeric
trajectories.

| Pathology | Stored | Reconstructed | Set relationship |
| :--- | ---: | ---: | :--- |
| Null values | 7,192 | 101 | all 101 reconstructed nulls are also stored null; 7,091 stored-only |
| Decreases | 286 across 73 market-days | 703 across 128 market-days | all 286 stored decreases are shared; 417 reconstructed-only |
| Value-after-null resurrections | 27 across 22 market-days | 45 across 40 market-days | all 27 stored resurrections are shared; 18 reconstructed-only |
| Late nulls | 3,525 across 64 market-days | 27 across 26 market-days | all 27 reconstructed late nulls are shared; 3,498 stored-only |
| Running-envelope violations | 3,358 | 7,349 | all 3,358 stored violations are shared; 3,991 reconstructed-only |
| Direct anomaly rows | 3,828 | 748 | 579 shared, 3,249 stored-only, 169 reconstructed-only |

The worst stored decrease is `66.02 -> 55.04 F`, a `10.98 F` drop, at San
Francisco `2026-07-04T15:27:41.720694-04:00`. The reconstructed worst drop
remains `95.0 -> 82.04 F`, or `12.96 F`, at Houston
`2026-07-02T14:22:55.547979-04:00`.

The narrowed settlement gate passes on both representations: each has zero
rounded settlement exceedances. Raw exceedances remain diagnostic only:
1,502 stored versus 1,640 reconstructed, with the same largest raw excess
of `0.46 F`.

## Interpretation and limits

The simple “reconstruction-only, persisted production evidence clean” world
is ruled out. The persisted capture-time feature record itself contains 286
decreases, 27 resurrections, and extensive nulling. The opposite
claim—that current reconstruction faithfully reproduces the historical
capture feature—is also ruled out on 37.732% of the population.

This result does **not** make the stored value authoritative merely because
it was persisted. In particular:

- it does not prove that the 7,091 reconstructed numeric values were
  available to, or should have been used by, the live model at those
  historical instants;
- it does not identify which captured observation set or code path produced
  the runtime boundary;
- the persisted snapshot feature vector is strong capture-path evidence,
  corroborated by the feature sidecar, but this comparison does not prove
  byte-for-byte identity with the predictor's internal feature object; and
- it does not establish that the floor defect caused model
  underperformance. No prediction, attribution, projection, or scoring was
  authorized.

The affected share is plainly not “too few to matter,” so the sixth
mechanism does not die on prevalence. It remains untested as a causal
explanation because the first comparison gate stopped the workflow.

## Hard stop boundary

| Operation | Result |
| :--- | :--- |
| Stored-versus-reconstructed comparison | **STOP - disagreement** |
| Replay-input source localization | **NOT RUN** |
| Candidate-vector stat, hash, or scan | **none** |
| `-27g` Mission 2 construction and attribution | **NOT RUN** |
| `-27g` Mission 3 projection and rescoring | **NOT RUN** |
| Model prediction, fitting, or serving replay | **none** |
| Vendor requests | **0** |
| Writes below `data/` | **0** |
| Apply, deletion, or compression against real data | **none** |
| Model/blend/serving/config/release changes | **none** |

The final gate records `candidate_vector_access = NOT_STAT_OR_HASHED`,
`localization_executed = false`, `missions2_or_3_executed = false`, and
`downstream_authority = false`.

## Admission, retries, and evidence

The declared output root is:

`scratch/workstation-research-output/who-breaks-floor-20260728e-retry1-92769649`

Before any successful stored-feature scan, the fresh admission recorded
35.893% committed memory, 16.131 GiB available physical memory, 39.973 GiB
available commit, 63.742 GiB free disk, zero Python or robocopy processes,
no training/restore or mirror process, and both deny-write ACL entries on
`data/`.

The earlier packet
`who-breaks-floor-20260728e-92769649` is preserved as non-authorizing
evidence. It stopped after the first primary record when it incorrectly
treated the corroborating sidecar's local feature-build timestamp as the
outer capture timestamp. The retry predeclared normalized-instant matching.
A subsequent metadata-only attempt stopped before data access because
sandboxed Git rejected the user-owned worktree; that receipt binding is
preserved in `pre_scan_git_identity_failure.json`. The final wrapper uses a
process-local `safe.directory` value for the single pinned worktree and does
not change global Git configuration.

The retry also corrected an important schema distinction before the final
scan: primary `snapshots.jsonl` local/UTC fields name the capture instant,
whereas `features.jsonl.captured_at_local` names the earlier feature-build
instant and its UTC field names the capture instant. The final binder joins
the sidecar by capture UTC and corroborates its build instant against the
primary nested feature vector. Its self-test covers offset-equivalent
instants, naive timestamps, duplicate JSON keys, malformed values, nested
identity, collision selection, sidecar build/capture semantics, exact
pathology sets, rounded-bound gating, and fail-closed postcheck publication.

| Evidence | Bytes | SHA-256 |
| :--- | ---: | :--- |
| Retry predeclaration | 6,104 | `2ac44c5a00d3935e289158c9a648ced1637ef39c07a999610bc23beb2fbe1eb4` |
| Fresh host admission | 2,538 | `3272b28b1ebcfd2aed7ba2e4c2307515a219aab734d0dff7dc40b769f9f93735` |
| Final comparison wrapper | 29,424 | `345cf05172f7b69439bd604425ee1ba63e746c02c709ebd89ca055e9956639a3` |
| Self-test receipt | 1,581 | `0bc0040b57aa6bebc19585b2a5bdce3036e27a471c4fade5306d392a5744fe08` |
| Stored-file receipt | 89,805 | `235f0964c6f8ea8327b8751d7f75c0fd683603f7ca89559d6ae32e5f5456fc7b` |
| Row-level comparison | 6,527,259 | `81113eec7cb88302ddbae7edb5d6b84c1948cc10a0348ae0e9f24add066c0e94` |
| Final comparison gate | 10,498 | `0476fe4bea543cb94e7978a1e9e652eef90184ea1e5aef91be8e60fc7e423d0f` |
| Final comparison receipt | 13,646 | `1f96a180e3fde891047b0b462bd4590bc654071a45c96e1c69eeaf59490aa886` |

## NOT DONE and next admissible step

- **NOT DONE:** source localization for the observed runtime-era boundary.
- **NOT DONE:** a decision about which historical representation should
  define any subsequent floor estimand.
- **NOT DONE:** `-27g` Missions 2 and 3.
- **NOT PROVEN:** mechanism, model-score impact, deployability, promotion
  readiness, or release safety.
- **NOT CHANGED:** data, model, floor order, blend, alpha, config, artifact,
  release, pointer, collector, scheduler, sizing, cap, trading, or serving
  state.

Per the handoff, the next step requires a new operator decision or handoff.
This run authorizes no localization retry and does not silently prefer or
exclude either representation.

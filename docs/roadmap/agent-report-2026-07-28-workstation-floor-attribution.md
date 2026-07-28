# Agent report - 2026-07-28 workstation settlement churn and floor attribution

Status: **THE LITERAL SIX-FIELD SEMANTIC SETTLEMENT GATE FAILED.
`reconciliation_status` MOVED IN ALL 129 MARKET-DAYS. SETTLEMENT CHURN
DOES NOT EXPLAIN `NOT_ACCOUNTED_FOR`. MISSION 1 AND MISSIONS 2-3 WERE NOT
RUN.**

This report executes
`docs/roadmap/workstation-handoff-2026-07-28c-settlement-revision-churn.md`
from exact `origin/master`
`d0f0002553e74e6ba53e5d0dda935d3ad760fd44` on topic branch
`codex/workstation-who-breaks-floor-2026-07-27g`.

## Required answers first

1. **No, the declared substantive settlement tuple is not stable across
   revision history.** Five fields are stable, but the handoff explicitly
   included `reconciliation_status`, and that field changes in every one of
   the 129 native-F market-days.
2. **No, this churn does not explain
   `NOT_ACCOUNTED_FOR_BY_PREDECLARED_EVALUABLE_FUNCTIONS`.** The sampled
   captured inputs contain no final settlement label, the accepted bounded
   prediction path removes settlement-derived labels before attaching
   probabilities and rejoins them afterward, and all six sampled semantic
   tuples at the candidate-vector production boundary equal their current
   values.
3. **Missions 2 and 3 could not resume.** The new Phase 0 gate failed before
   the respecified Mission 1 gate, replay-corpus pass, or candidate-vector
   pass. Normalizing away `not_requested`, excluding early revisions, or
   dropping `reconciliation_status` after observing it would contradict the
   handoff.

The persisted terminal is:

```text
FAIL_SEMANTIC_SETTLEMENT_STABILITY_STOP_BEFORE_REPLAY
```

## Semantic settlement verification

A fresh packet was frozen before the full audit at:

`scratch/workstation-research-output/who-breaks-floor-20260728c-d0f00025`

The strict audit read each of the 11 settlement ledgers once, verified each
complete append-only history with the checked-in ledger verifier, then read
the 129 current settlement sidecars. Size and modification time remained
stable through every read. It found:

| Scope | Observation |
| :--- | ---: |
| Promotion-manifest entries | 141 |
| Native-F market-days | 129 |
| Native-F snapshots represented | 18,793 |
| Markets | 11 |
| Complete ledger rows strict-parsed | 8,151 |
| Relevant settlement-history rows | 2,193 |
| Records per relevant event | 17 |
| Ledger history-verification blockers | 0 |
| Current sidecar/current ledger tuple mismatches | 0 |

Every relevant event has a legacy record plus revisions 1 through 16. The
field-by-field result is:

| Semantic field | Events with a change | Transitions |
| :--- | ---: | ---: |
| `target_date` | 0 | 0 |
| `settlement_bucket` | 0 | 0 |
| `settlement_high` | 0 | 0 |
| `winning_band` | 0 | 0 |
| `winning_band_kind` | 0 | 0 |
| `reconciliation_status` | **129** | **259** |

The status transitions are:

| Transition | Count |
| :--- | ---: |
| `match -> not_requested` | 128 |
| `not_requested -> match` | 129 |
| `match -> fetch_error` | 1 |
| `fetch_error -> not_requested` | 1 |

The extra excursion is Atlanta 2026-07-09: revision 9 is `match`, revision
10 is `fetch_error`, revision 11 is `not_requested`, and the next revision
returns to `match`. All other events use the two-state
`match -> not_requested -> match` pattern. All current records are `match`.

The manifest agrees with the current ledger on all five fields it carries.
It carries no `reconciliation_status` for any of the 129 entries, so it
cannot verify the sixth field. The copied current semantic snapshot has 129
records and semantic content SHA-256
`deaf71cd71eb81185f78109110f20a24f03e60fde6fabe6aa5a4c7e86ecdebb0`,
but is deliberately marked `INADMISSIBLE_HISTORY_DRIFT`; it is diagnostic
evidence, not a downstream-authorizing freeze.

### Dallas and the handoff host-state difference

Dallas 2026-06-30 confirms the common pattern. Its bucket `95`, high `95`,
winner `94-95 F`, and winner kind `eq` never move. Its status is `match`
through revision 10, `not_requested` at revision 11, and `match` from
revision 12 through the current revision 16.

The data visible on this workstation is older than the host state described
in the handoff:

| Topology fact | This workstation |
| :--- | ---: |
| Snapshot folders | 646 |
| Current `settlement.json` sidecars | 621 |
| Sidecars written on 2026-07-28 | 0 |
| Latest sidecar write | 2026-07-27 22:30:10Z |
| Dallas latest revision | 16 |

The handoff's later Dallas revision 17 and July 28 rewrite are not present
here. That prevents verification of that exact later revision, but does not
weaken the stop: the locally available history already disproves literal
six-field stability.

## Churn hypothesis: rejected

The bounded first cut inspected one captured replay record across six
market-days, including both prior gate failures:

| Market/date (target date) | Snapshot | First settlement finalization after capture | Rev14/current: bucket / high / band / kind / status |
| :--- | :--- | ---: | :--- |
| Los Angeles 2026-06-28 | `20260628T030303-0400` | 342.713 h | `71 / 71.0 / 70-71 F / eq / match` |
| Dallas 2026-06-30 | `20260701T002709-0400` | 273.312 h | `95 / 95.0 / 94-95 F / eq / match` |
| Atlanta 2026-07-02 | `20260702T120026-0400` | 237.757 h | `98 / 98.0 / 98-99 F / eq / match` |
| Denver 2026-07-05 | `20260705T123647709010-0400` | 165.151 h | `94 / 94.0 / 94-95 F / eq / match` |
| Miami 2026-07-08 | `20260708T114603482778-0400` | 93.996 h | `92 / 92.0 / 92-93 F / eq / match` |
| Seattle 2026-07-10 | `20260710T133425712512-0400` | 44.190 h | `76 / 76.0 / 76-77 F / eq / match` |

No sample had a settlement-ledger revision at capture. All first finalized
at `2026-07-12T13:45:50.583676Z`. By the approximately
`2026-07-25T18:05:10Z` candidate-vector production boundary, revision 14
was already present for each sample. Each revision-14 six-field tuple equals
the current revision-16 tuple. Revisions 14 through 16 differ only in
volatile finalization/evidence and derived revision metadata after masking
`finalized_at_utc`,
`evidence.five_time_provenance.label_finalized_at`, and
`evidence.raw_resolution_hashes.daily_summary_sha256`.

The predeclaration bounded this as a small cross-market sample but did not
case-pin the six IDs or state a deterministic selection rule. The sample is
therefore diagnostic rather than independently selection-reproducible. The
mechanism conclusion below also rests on the checked-in prediction boundary,
not on frequency estimates from these six cases.

Each sampled replay record has `recorded_distribution` and weather sources,
but none has `settlement_bucket`, `settlement_high`, `winning_band`,
`winning_band_kind`, `reconciliation_status`, a settlement `label_hash`, or
settlement revision metadata. The checked-in implementation corroborates
that boundary:

- `snapshot_store.py:2909-2974` builds captured replay input from identity,
  release/runtime identity, build time, `recorded_distribution`, and
  `sources`; it does not add settlement labels.
- `pooled_candidate_replay.py:262-270` defines settlement-derived row fields.
- `pooled_candidate_replay.py:1662-1689` separates those labels and removes
  them from prediction rows.
- `pooled_candidate_replay.py:1735-1766` removes labels, attaches candidate
  probabilities, and only then rejoins the labels.
- `pooled_candidate_replay.py:3194` forces that deferred join in the bounded
  production flow.

Thus settlement revision churn can disturb settlement lineage, admission,
or later scoring, but it cannot change the prediction probability vector
produced from the captured weather inputs. The proposed mechanism dies.

### The Dallas record mismatch remains independent

The earlier Dallas failure is still real and remains unexplained by
settlement churn:

| Binding | SHA-256 |
| :--- | :--- |
| Manifest-pinned replay-record hash | `97e254a7e03b9e03eec69a7a1bab43308d396d43e40ff7c8f27cdaba63a75b00` |
| Current canonical replay-record hash | `95864f97f05956b957dc72fd00c1df9edeb7242f8fe66d36f91575989823a901` |

The current Dallas replay record has no embedded `captured_input_hash`.
`promotion_corpus.py:152-158` hashes the replay-record object itself, while
settlement is resolved and hashed separately. A semantic settlement freeze
therefore cannot repair, explain, or safely waive this mismatch. Even if the
six-field gate had permitted status normalization, the prior respecified
Mission 1 packet would still lack a valid replay-record binding.

## Hard stop and unrun work

| Operation | Result |
| :--- | :--- |
| Six-field history stability | **FAIL** |
| Admissible semantic settlement freeze | **NOT ISSUED** |
| Respecified complete-population Mission 1 | **NOT RUN** |
| Complete replay-corpus pass | **0** |
| Candidate-vector content scan | **0** |
| Mission 2 construction/localization | **NOT RUN** |
| Mission 2 alpha attribution | **NOT RUN** |
| Mission 2 incumbent characterization | **NOT RUN** |
| Mission 3 projection and rescoring | **NOT RUN** |
| Model prediction, fitting, training, or serving replay | **none** |
| Vendor requests; order-book/full-book reads | **0** |
| Program writes below `data/` | **0** |
| Fresh pre-audit deny-write ACL receipt | **NOT CAPTURED** |
| Apply, deletion, or compression against real data | **none** |

The Phase 0 audit itself did not stat, hash, or open the candidate vector and
did not open the replay corpus. The separate hypothesis first cut directly
read only the six selected replay records and their settlement histories; it
did not make a replay-corpus pass. Existing output-file metadata and a
downstream receipt bracketed the candidate-vector production time, but the
vector contents were not opened.

This packet did not bind a fresh host-admission or deny-write ACL receipt
before the audit. The prior `-28b` admission recorded two deny-write entries,
and a post-audit read-only check found the same two entries still present.
That is useful corroboration but is not retroactive proof that the ACL was
continuously active during this pass. The program receipt proves that the
audit issued no `data/` writes; it does not substitute for the missing fresh
ACL admission. The ACL guardrail is therefore **NOT PROVEN for this packet**,
although the executed behavior remained read-only.

## Evidence and receipts

| Evidence | Bytes | SHA-256 |
| :--- | ---: | :--- |
| Predeclaration | 5,961 | `d3f5c6f063c1ae6945826089633bc0e36446109c75a8ffeee9dfce347b88ad61` |
| Semantic audit harness | 29,100 | `047cd993dd6dbe66c0588cf6df37f8b9d1ebe7ddae364f95128a972319103b07` |
| Corpus-free self-test receipt | 905 | `c5c5c20f6aa3d482c396aefebb0e071eaa47d20481b31db28a7589cfc3bcbb70` |
| Ledger scan | 2,387 | `64eaddb52c5bf822beb69ced0e5a9d9396d29d4431382debd97fefac29eb4cab` |
| Inadmissible current semantic snapshot | 116,929 | `7c75c155b06ad9aa4f5c7431f586f214106aaa6d654f55a53d089d08f32197e1` |
| Semantic transitions | 51,612 | `259b12fa61694f5645220939b25874458c47d1c8aae38e33f70bcb74a4588a76` |
| Semantic gate | 10,365 | `c76a3ac95f3b6f96486cf952897c25287039eac36ea49d3eb9d0400e21050010` |
| Semantic receipt | 7,031 | `e56d3ab25e65ab5568d458b36cd1c042773b96091c59763dd7ab810e0acc3ee9` |

The gate and receipt bind unchanged fixed inputs before and after the pass,
record zero `data/` writes, and preserve the two prior failed packets
unchanged.

## NOT DONE and next admissible step

- **NOT DONE:** an admissible semantic settlement freeze under the six-field
  contract.
- **NOT DONE:** the complete respecified floor gate and null distribution.
- **NOT DONE:** the unchanged Mission 2 and Mission 3 analyses.
- **NOT PROVEN:** any priced benefit from floor projection.
- **NOT CHANGED:** settlement data, model, blend, alpha, floor order, config,
  artifact, release, pointer, collector, scheduler, trading, or serving
  state.

The next step requires owner authority, not another retry: decide whether
`reconciliation_status` is genuinely semantic for this purpose or whether a
new, explicitly narrower freeze contract should exclude it. Independently,
restore or deliberately refreeze the Dallas replay record under a coherent
captured-input binding. Missions 2 and 3 remain blocked until both a valid
settlement contract and the complete respecified Mission 1 gate pass.

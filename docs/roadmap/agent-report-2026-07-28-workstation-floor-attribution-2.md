# Agent report - 2026-07-28 Dallas collision and floor attribution retry

Status: **DALLAS IS RESOLVED AS AN ORDER-SENSITIVE DUPLICATE-KEY
SELECTION, NOT CORRUPTION. AUSTIN REPRODUCES IT. THE FRESH FIVE-FIELD
SETTLEMENT FREEZE PASSED, BUT THE COMPLETE RESPECIFIED MISSION 1 FLOOR
GATE FAILED. MISSIONS 2 AND 3 WERE NOT RUN.**

This report executes
`docs/roadmap/workstation-handoff-2026-07-28d-dallas-record-nondeterminism.md`
from exact `origin/master`
`56e4d1e1bd7e59e0ae210e244028b090f138460a` on topic branch
`codex/workstation-who-breaks-floor-2026-07-27g`.

The persisted Mission 1 terminal is:

```text
FAIL_RESPECIFIED_LEAKAGE_GATE_STOP_BEFORE_SCORING
```

## The three record answers

### 1. Dallas maps to exactly two replay records

Yes. The key
`dallas|2026-06-30|20260701T002709-0400` occurs twice, on adjacent lines
160 and 161 of a stable 165-record `replay_inputs.jsonl`:

| Physical line | Promotion canonical record SHA-256 | Interpretation |
| ---: | :--- | :--- |
| 160 | `95864f97f05956b957dc72fd00c1df9edeb7242f8fe66d36f91575989823a901` | the hash previously reported as current |
| 161 | `97e254a7e03b9e03eec69a7a1bab43308d396d43e40ff7c8f27cdaba63a75b00` | the unique manifest-pinned match |

All 165 physical records parsed, and the file remained stable through the
read. Both target records carry the required Dallas identity.

### 2. The records differ, and both reported hashes are real

Yes. The two records are neither byte-identical nor canonically identical.
They differ at 144 leaf paths:

| Area | Differing paths |
| :--- | ---: |
| `runtime_guard` | 71 |
| `runtime_identity` | 36 |
| `sources` | 29 |
| build/capture timestamps | 3 |
| `snapshot_cadence` | 1 |
| `snapshot_cadence_quality` | 3 |
| `trigger_context` | 1 |

The source differences are principally fetch times, latencies, cache/run
ages, and MRMS age. Cadence and runtime identity also differ. The
`recorded_distribution` and `model_identity` are identical.

Neither legacy record carries `captured_input_hash_algorithm` or
`captured_input_hash`; that status is `LEGACY_ABSENT`, not a failed
self-hash.

The checked-in loader preserves captured JSONL order and its documented
snapshot index uses later-duplicate-wins semantics. Promotion construction
uses that index and therefore selects line 161, which exactly matches the
manifest. The earlier streaming Mission 1 validator compared line 160
against the manifest's single selected-record hash and stopped before
reaching line 161.

The defect is consequently precise: replay-record selection is dependent on
duplicate insertion order, while the manifest pins only the selected
last-wins record. A validator that tests every raw occurrence independently
does not reproduce that contract. Reversing two distinct duplicates would
change the selected record hash, but this audit does **not** show that the
physical file order changed. It shows that both hashes are genuine and that
the previous mismatch came from consumer semantics, not corrupted data.

The related tape contract is different: tape hashing retains all rows for a
collision key in their frame order. It is also order-sensitive, but it does
not use the replay-record last-wins reduction.

### 3. Austin behaves the same way

Yes. The key
`austin|2026-07-03|20260703T093322-0400` also occurs exactly twice on
adjacent lines in a stable file:

| Physical line | Promotion canonical record SHA-256 | Interpretation |
| ---: | :--- | :--- |
| 68 | `daabec53940ab67b4a26438a8527dd8eed5f91585401f6065f9eff91f9e28395` | first, not manifest-pinned |
| 69 | `a1308c1443d0cb1cb7f99e376e108f6d5225fdb9661cd9bf8304cfc3db183b63` | later-wins and uniquely manifest-pinned |

Austin has the same 144-path difference shape, the same identical
`recorded_distribution` and `model_identity`, and the same legacy absence
of captured-input self-hash fields. This independently strengthens the
duplicate-key/order-selection explanation.

Dallas was therefore resolved without exclusion. No snapshot, market-day,
row, or collision half was removed, and no change to the estimand was made
or proposed for owner approval.

## Fresh admitted packet and settlement freeze

The authoritative packet is:

`scratch/workstation-research-output/who-breaks-floor-20260728d-admitted-56e4d1e1`

A first diagnostic collision packet at the similarly named non-`admitted`
root was read before a fresh host admission. It is explicitly
non-authorizing. Rather than reconstructing an ACL receipt, I made a new
predeclaration, captured admission first, and reproduced the collision
result in the authoritative root.

The fresh admission at `2026-07-28T13:53:56.5741527-04:00` bound the exact
commit, branch, output root, and predeclaration. Commit utilization was
36.406%, available physical memory was 13.634 GiB, disk free was
65.031 GiB, no competing Python, mirror, restore, or training process was
present, and the `data/` ACL had two effective deny-write entries.

After the collision PASS, a fresh immutable 129-record projection of the
bound prior strict semantic audit verified zero history changes in each of:

- `target_date`
- `settlement_bucket`
- `settlement_high`
- `winning_band`
- `winning_band_kind`

There were zero manifest mismatches. The frozen semantic content SHA-256 is
`67c4f7c9e75049047fddf1f65c5403b75c1a39fed9d0f3d9cb75c2bd9ed27564`.
`reconciliation_status` was not used.

The handoff's current-sidecar field-absence correction was not used to
authorize this result. A separate non-authorizing, non-receipt-backed
inspection of the local mirror observed explicit
`reconciliation_status: match` fields rather than absence; the promotion
manifest still does not carry that field. The discrepancy is compatible
with the stated same-day mirror lag, so it is not evidence against the host
claim and does not overturn the previous finding that
`reconciliation_status` moves in revision history. The five verified stable
fields are sufficient for the newly specified freeze, and that gate passed.

## Mission 1: complete respecified floor gate

The collision-aware replay pass retained all 18,793 manifest snapshot IDs.
For unique keys it required one record; for the two declared collision keys
it required exactly one candidate matching the manifest hash and selected
that candidate. Any other duplicate remained a hard failure. The synthetic
self-test passed, including manifest-match selection and rejection of an
undeclared duplicate.

The pass read each of the 129 stable replay-input files once:

| Scope | Count |
| :--- | ---: |
| Native-F market-days / replay files | 129 |
| Manifest snapshots reconstructed | 18,793 |
| Replay-input bytes | 8,610,897,941 |
| Non-null `high_so_far` snapshots | 18,692 |
| Null/no-constraint snapshots | 101 |
| Adjacent pairs | 18,664 |
| Adjacent non-null pairs | 18,563 |
| Hour-20 cases | 124 |

The prior null identity check passed: snapshot
`20260628T030303-0400` is Los Angeles at market-local hour 0. It is the
western, early-local case anticipated by the respecification. That explains
that particular initial null, but the complete-population gate found four
independent hard failures:

| Required invariant | Result | Complete-population evidence |
| :--- | :---: | :--- |
| Non-null monotonicity | **FAIL** | 703 decreases across 128/129 market-days; the most negative serialized delta was `95.0 -> 82.04 F` in Houston on 2026-07-02, effectively tied at `12.96 F` by Denver on 2026-06-29 |
| Raw and rounded settlement bounds | **FAIL** | 1,640 raw exceedances across 43 market-days; 0 rounded exceedances; largest raw excess was `0.46 F` |
| No null resurrection | **FAIL** | 45 value-then-null records across 40 market-days |
| Nulls only before local hour 12 | **FAIL** | 27 late nulls across 26 market-days |

There were zero same-build-instant conflicts, zero missing hour-20 keys, and
zero hour-20 high mismatches. The gate counted 2,415 violations in total.
Every one of the 129 market-days had at least one violation.

The raw settlement exceedances have the shape of sub-degree representation
or conversion residue -- for example, `93.02 F` against a `93 F`
settlement -- and all rounded comparisons pass. That observation does not
waive the declared raw bound. More importantly, the 703 decreases, 45 null
resurrections, and 27 late nulls fail independently of settlement
granularity.

### Null distribution

The 101 actual Python `None` values are 0.5374% of the population. They were
treated as no floor constraint: no sentinel, forward-fill, backfill, or
imaginary floor was used.

| Market | Snapshots | Nulls | Null share |
| :--- | ---: | ---: | ---: |
| Atlanta | 1,613 | 6 | 0.3720% |
| Austin | 1,798 | 7 | 0.3893% |
| Chicago | 1,775 | 4 | 0.2254% |
| Dallas | 1,761 | 3 | 0.1704% |
| Denver | 1,761 | 49 | 2.7825% |
| Houston | 1,753 | 5 | 0.2852% |
| Los Angeles | 1,715 | 4 | 0.2332% |
| Miami | 1,741 | 6 | 0.3446% |
| New York City | 1,567 | 6 | 0.3829% |
| San Francisco | 1,726 | 5 | 0.2897% |
| Seattle | 1,583 | 6 | 0.3790% |
| **Pooled** | **18,793** | **101** | **0.5374%** |

Null counts by market-local hour were:

```text
00:33  01:15  02:8  03:1  04:1  05:2
06:4   07:3   08:1  09:3  10:1  11:2
12:0   13:2   14:3  15:1  16:0  17:1
18:1   19:1   20:1  21:0  22:0  23:17
```

## Missions 2 and 3: not run

The `-28b` contract says to stop before scoring if any of the four
respecified invariants fails. All four failed. Consequently:

| Requested work | Result |
| :--- | :--- |
| Candidate-vector stat, hash, or content read | **NOT PERFORMED** |
| Mission 2 clean-by-construction analysis | **NOT RUN** |
| Mission 2 alpha attribution | **NOT RUN** |
| Mission 2 incumbent characterization | **NOT RUN** |
| Mission 3 floor projection | **NOT RUN** |
| Categorical or binary Brier rescoring | **NOT RUN** |
| Reliability/resolution decomposition | **NOT RUN** |
| Priced gap closure or worse-case search | **NOT RUN** |

There is therefore no new attribution or priced projection result to report.
Opening the frozen candidate vector after this terminal would have violated
the gate rather than completed Missions 2 and 3.

## Evidence and receipts

| Evidence | Bytes | SHA-256 |
| :--- | ---: | :--- |
| Authoritative predeclaration | 7,477 | `3e99ee6cbe473f9912cee40b1de54902bc91aebbf13d408eb7a918497912a353` |
| Fresh host admission | 2,702 | `64912bb05e37d041e31c897e752b000d8ac4199fade92e33f0ebdc8de561aff4` |
| Collision harness | 4,216 | `38b3d1059a5d24065e81fd429daf7a493ac02a2d8f46e158bac63d87cea90572` |
| Collision audit | 28,067 | `e53c336768ca8c7f079368424a8f381626d18e46276c643194fdd8b159a15764` |
| Collision differences | 98,222 | `0a0139f07f93598b08312a852c257e6a3605776b2ded6f4715b63052810e4685` |
| Collision gate | 2,149 | `5b0961ce15050881c1feff21c63ff8f8cdafe82ee44db5bff70402774af4cd00` |
| Collision receipt | 7,295 | `4fa7d34684eaa221eff9e9df0ede6ef354807aa343c82f1aff02a112bf3ae96d` |
| Five-field settlement freeze | 37,172 | `dcc3c16f7029b9563985cd69b67147bcbc8d7acf4f51731f83993132c663e855` |
| Five-field settlement gate | 864 | `dc72c559f2dd9c9e45c4dd6979f7da4c0c422f551d88b8c6d82c76d4f0dbfeb4` |
| Five-field settlement receipt | 7,346 | `4ad639c0129817f6989ca7fa2612dff9aebf58c9215250eed4b3aa3ea1e90563` |
| Mission 1 harness | 15,763 | `d722f076879ae461d96c98567d9828acd03d1cca902e362dd18565a33cf56b76` |
| Mission 1 self-test | 1,172 | `013d12803b52964823980ac6b75e41485b40805210b188ffb5c53f4ffe8dff46` |
| Reconstructed floor features | 7,095,312 | `0581a2b403589b2bd10be45682b6f42db57708f2b80be1dd220c38ac8a52b800` |
| Replay-file binding extract | 47,184 | `b103d6cc349b5124cf84ceef2c612a3cc404a313057903fc6fc162688bb1d314` |
| Mission 1 gate | 108,807 | `419ada23b8e248343b4bfd9f2c246776625619a7d0c066d78b11510b37fa4cfb` |
| Mission 1 receipt | 25,698 | `4292bde929d16590a859aa5bfb1e08f73ddb510de8acb5eebb09f0cd447c437a` |

The receipts bind unchanged fixed inputs around the admitted reads and
record zero writes below `data/`.

## NOT DONE and next admissible step

- **RESOLVED:** Dallas and Austin collision-record identity and hash
  selection.
- **PASS:** fresh five-field semantic settlement freeze.
- **FAIL:** complete respecified Mission 1 floor gate.
- **NOT DONE:** Mission 2 localization and incumbent characterization.
- **NOT DONE:** Mission 3 projected counterfactual and decompositions.
- **NOT PROVEN:** any priced benefit from floor projection.
- **NOT CHANGED:** replay inputs, settlement data, model, blend, alpha,
  floor order, config, artifact, release, pointer, collector, scheduler,
  trading, or serving state.
- **NOT PERFORMED:** apply, deletion, compression, vendor or other
  operational network calls, order-book reads, or writes against real data.

The next admissible step is not to exclude Dallas; Dallas is coherent under
the manifest's selected-record contract. It is to diagnose why the
reconstructed `high_so_far` is non-monotone, can disappear after becoming
defined, and can be null late in the market-local day, then obtain an
explicitly revised gate or a corrected ex-ante floor source. Missions 2 and
3 remain blocked until that floor authority passes.

# Workstation floor-informativeness replication report - 2026-08-02

## Declaration - frozen before freshness inventory or score inspection

Declared at `2026-08-02T17:00:26.7282900Z`. The sole output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\floor-informativeness-replication-2026-08-14a`,
outside the replay mirror. `data/` and the mirror remain read-only.

This is replication only. Nothing will be fitted, selected, tuned, or changed.
The frozen inputs are:

- continuation candidate artifact SHA-256
  `d542ec0955f5fa7e7feab8541d78ba124d8f99f7f556cd7f1e0a2290f8275c85`;
- gate `floor_available and floor_removed_mass > 0.20`;
- the held 08-09a harness, including bootstrap seed `20260809`, 10,000
  repetitions, newly-severe cap `1065 / (8380 * 11)`, severe threshold `0.30`,
  and catastrophic rule that no protected slice may regress by more than the
  pooled improvement.

The freshness inventory is restricted to the 12 frozen markets and the exact
permissible date universe `2026-07-31` through `2026-08-05`. July 22-30 is
burned and excluded. August 6-19 is reserved and will not be read, enumerated,
evaluated, or substituted. A date enters the score set only if all 12
market-days are present, `complete`, coverage-clean, promotion-countable, and
settled at inventory time. The exact resulting list will be written below and
committed before any replay probability is scored. It will not be extended or
reduced afterward.

The worth-confirming rule is frozen: all three pooled primary gates must pass,
and per-date deltas must be consistently negative rather than carried by one
day. If fewer than three dates enter, the outcome is **provisional** regardless
of measured direction.

## Pre-committed score set

Metadata inventory completed at `2026-08-02T17:02:10.154352Z`, before any
candidate or incumbent probability was evaluated. The inventory manifest has
SHA-256 `2d29f8add843712f3fafcda934a7d5b43cd254c82e6886fd2a45e6d46e629a9e`
and semantic corpus hash
`4c519d593a7935f172ba1cddce82bd29aab4466e6e59afe0945394d66dd657b0`.

The exact, immutable score set is:

1. `2026-07-31` - 12/12 market-days complete, coverage-clean,
   promotion-countable, and settled.

This list is now closed. It will not be extended or reduced after scoring.
July 31 is the already-scored date and will be restated/reproduced; there are
**zero additional clean dates** available for a fresh replication estimate.

| Permissible date | Inventory result | Disposition |
| :--- | :--- | :--- |
| `2026-07-31` | 12 admitted | **SCORE / restate** |
| `2026-08-01` | 12 missing settlement labels | Missing; do not wait or substitute |
| `2026-08-02` | 12 missing settlement labels | Missing; do not wait or substitute |
| `2026-08-03` | 12 missing tapes | Missing; do not wait or substitute |
| `2026-08-04` | 12 missing tapes | Missing; do not wait or substitute |
| `2026-08-05` | 12 missing tapes | Missing; do not wait or substitute |

With only one calendar date, the outcome is pre-labelled **PROVISIONAL**. The
new-dates-alone estimate is `NOT_EVALUABLE`; it will not be manufactured from
burned July 22-30 evidence or reserved August 6-19 evidence.

## Replication result

**PROVISIONAL; REPLICATION NOT EVALUABLE.** Only the already-scored July 31
date passed the precommitted completeness rules. There are no new dates, so the
experiment cannot say whether the improvement, the hour failures, or the D1
failure recur. The frozen July 31 result reproduced exactly, including the
candidate-row and native-distribution file hashes.

| Date | Status | Market-days | Incumbent Brier | Candidate Brier | Candidate - incumbent |
| :--- | :--- | ---: | ---: | ---: | ---: |
| `2026-07-31` | Restated / reproduced | 12 | 0.056481213 | 0.049621255 | **-0.006859959** |

Because the score set contains only that row, the pooled estimate is the same:
12 market-days, delta `-0.006859959`, with the frozen 10,000-repetition paired
market-day bootstrap upper bound `-0.002075876`. The **new-dates-alone result is
`NOT_EVALUABLE`**: zero dates, zero market-days, and no estimate.

| Frozen primary gate | Pooled result | Evidence |
| :--- | :---: | :--- |
| One-sided 95% market-day bootstrap non-regression | **PASS** | Mean delta `-0.006859959`; upper bound `-0.002075876`. |
| Newly-severe cap | **PASS** | 140 / 23,716 = `0.59032%`, below `1.15535%`; 642 retired > 140 new. |
| Catastrophic protected-slice bar | **BLOCK** | 3 / 53 slices regress by more than pooled improvement `0.006859959`. |

The severe-tail evidence also reproduced: fixed positive excess fell from
`0.335330315` to `0.232344906`, a reduction of `0.102985409`; severe rows fell
from 1,673 to 1,171. This does not override the primary slice block.

| Requested recurrence check | July 31 restatement | New-date evidence | Result |
| :--- | ---: | :--- | :--- |
| `capture_hour=14` | `+0.007065143` | None | **NOT EVALUABLE** |
| `capture_hour=17` | `+0.008626029` | None | **NOT EVALUABLE** |
| `D_class=D1` | `+0.032301766` | None | **NOT EVALUABLE** |

The candidate is **not worth taking to the reserved confirmation window**.
That is not a new negative replication verdict: the frozen rule cannot be met
because one primary gate still blocks and there is no multi-date consistency
evidence. The lane remains held and `NOT_READY`.

## Secondary D1 diagnosis

The D1 regression reproduced exactly on July 31: 98 snapshots across seven
markets moved Brier from `0.053742900` to `0.086044666` (`+0.032301766`),
severe rows from 45 to 105, and fixed-tail positive excess in the wrong
direction by `0.001339703`. This is a restatement, not recurrence evidence.

The mechanism is floor anchoring after the gate qualifies the candidate:

- 67 D1 snapshots qualified and 31 were excluded. Excluded snapshots remained
  exactly equal to the incumbent and contributed zero D1 delta.
- Across the 67 qualified snapshots, the candidate's mean native distribution
  was `P(D0)=0.529727`, `P(D1)=0.105475`, and `P(D>=2)=0.364799`. Although the
  realized continuation was exactly D1, the candidate assigned about five
  times as much probability to no continuation as to one-step continuation.
- In 89 / 98 D1 snapshots the winning market band was one band above the floor;
  only nine shared the floor band. On the 58 qualified above-floor cases, mean
  winner probability fell from `0.443133` to `0.123093` (`-0.320040`) while
  floor-band probability rose from `0.363760` to `0.577260` (`+0.213500`).
  Daily-first Brier moved from `0.055459` to `0.114923` (`+0.059464`), and this
  group accounts for 63 of the D1 slice's 65 newly-severe rows.
- The nine qualified cases whose winner remained in the floor band instead
  improved by `-0.003194`. That contrast localizes the failure to observable
  allocation across the floor-band boundary, not to the gate leaking changes
  into excluded rows.

So the continuation target is not failing because D1 is intrinsically
unrepresentable. The frozen model is under-allocating the exact one-step state
and over-anchoring at the floor precisely when D1 crosses into the next market
band. This is diagnosis only. No refit, threshold change, feature change, or
candidate variant was attempted.

## Evidence and guardrails

The accepted replay contains 2,156 snapshots and 23,716 band rows with zero
corpus warnings. The floor trace covers all 2,156 snapshots, with 2,152 floors
available, 1,643 materially binding, zero floor-above-settlement cases, zero
served-probability mismatch, and zero centre mismatch. The frozen gate
qualified 731 snapshots and excluded 1,425; all 15,675 excluded band rows copy
the incumbent probability text exactly with zero mismatches.

The candidate rows, native distributions, incumbent replay rows, and floor
trace are byte-identical to the corresponding held 08-13a July 31 outputs. The
protected-slice CSV is also byte-identical. This independently reproduces the
prior score rather than merely quoting it.

| Field | Value |
| :--- | :--- |
| Handoff source | `origin/master` `bd52c0d2480e10b30f0cc9ba63c013d3089461a5` |
| Exact held base | `55f5f5ddda9e1a6ce73aa4075f2996eff5e2c7ef` |
| Topic branch | `codex/workstation-floor-informativeness-replication-2026-08-14a` |
| Declaration commit | `c48fa16d` |
| Score-set freeze commit | `c90f6a8f` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\floor-informativeness-replication-2026-08-14a` |
| Declaration time | `2026-08-02T17:00:26.7282900Z` |
| Frozen candidate SHA-256 | `d542ec0955f5fa7e7feab8541d78ba124d8f99f7f556cd7f1e0a2290f8275c85` |
| Frozen gate | `floor_available and floor_removed_mass > 0.20` |
| Reserved confirmation dates | August 6-19; not read, enumerated, evaluated, or substituted |

| Evidence | SHA-256 |
| :--- | :--- |
| Freshness inventory corpus | `2d29f8add843712f3fafcda934a7d5b43cd254c82e6886fd2a45e6d46e629a9e` |
| Incumbent replay rows | `ce3b249f6857b96657820ba0e7c3988359c816338c199352ce1dbc8d0c0ead94` |
| Floor trace | `54d3d7f47cbb19b0686f2ea6b15af3366af43787bf733e0d5da9cc314c982abc` |
| Gated candidate rows | `0aeca914e3f05b2b559e968fe8ae959ca19bae529ca6791030f0d3ed82fd835d` |
| Gated native distributions | `123fd9447ae2992b8a6c404b3a8bafcbd04f8f4fa81906057927662bacfc8457` |
| Harness scorecard | `f9394b2462b09dd451b3a90f051e5646dbd9cc5abcbe7ceafb24060894933050` |
| Protected slices | `e6cf6cc4aad5683bb640463517539da4ae16d095f25911c30c1c9a427fbf8883` |
| D1 diagnosis | `09af36bfa843caaed7babdf53b9f376c726ad2f5061ff4c8a77f6397e5a2c2c7` |

`data/` and the mirror remained read-only. July 22-30 was not scored or used;
August 6-19 was not read or enumerated. No candidate was fitted, selected,
tuned, or changed. No production host, sync credential, paid provider,
release, promotion, pointer, serving, scheduler, capture, mirror topology, or
ACL state was accessed or changed. No PR, merge, or master push was made.

The 41 focused floor-informativeness, continuation-candidate, gate-harness,
schema-registry, and import-architecture tests passed. `app`, `src`, and
`tests` compiled, and the agent-docs audit passed across 18 agent files and 573
Markdown files.

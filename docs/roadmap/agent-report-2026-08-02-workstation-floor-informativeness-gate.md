# Workstation floor-informativeness-gate report - 2026-08-02

## Pre-registration - frozen before development fitting or result inspection

Declared at `2026-08-02T16:18:35.5906455Z`, before inspecting any development-fit,
threshold-selection, or fresh-score result. The sole output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\floor-informativeness-gate-2026-08-13a`,
outside the replay mirror. `data/` and the mirror remain read-only.

The experiment is stacked on the held continuation candidate at exact commit
`1e525a02dfce1ba8c0d58a506877d3a778e8fe58`. Candidate objective, feature matrix,
lossless `F + D` translation, prior conditioning, temperature/blend grids, and
hard-floor stages remain frozen. The only primary change is a cutoff-time gate:
when the incumbent distribution's floor-removed mass is above a development-
selected threshold, use the continuation candidate; otherwise copy every
incumbent band probability exactly. No outcome-derived `D_class` or
`forecast_relative_winner` value may enter gate selection or application.

### Primary threshold-selection protocol

The primary gate is one scalar condition:

> `qualifies = floor_available and floor_removed_mass > T`

`T` will be selected only from the coarse, predeclared set `{0.01, 0.05, 0.20}`.
These cuts are the existing protected-slice boundaries, not values inferred
from the burned July 27-30 score result. No fine search or post-score change is
allowed.

Selection uses only July 22-26 and market-day grouping. Candidate fits are
forward-chained: July 22-23 fit / July 24 validate; July 22-24 fit / July 25
validate; July 22-25 fit / July 26 validate. For each threshold, the three
validation folds are pooled and judged with the frozen harness. Select by this
predeclared lexicographic rule: fewest failed primary gates; then the smallest
one-sided 95% market-day bootstrap upper bound; then the lowest newly-severe
rate; then the fewest catastrophic protected slices; and finally the higher
threshold on an exact tie. Freeze the selected numeric threshold before
reading or scoring any eligible fresh date.

The July 27-30 window is burned and will not be read, fitted, scored, or used to
change `T`. There is no primary hour-based or combined gate. Any such result,
if run at all, will be labeled secondary and exploratory; none is planned.

### Frozen qualification bars

All three bars are conjunctive:

1. **Bootstrap non-regression:** candidate-minus-incumbent daily-first 11-band
   Brier must have a one-sided 95% paired market-day bootstrap upper bound
   `<= 0`, using seed `20260809` and `10,000` repetitions. A non-positive pooled
   improvement cannot qualify.
2. **Newly-severe cap:** with the severe threshold fixed at `0.30`, newly severe
   band rows must be no more than `1065 / (8380 * 11)` = `1.15535%` of scored
   band rows, and retired severe rows must exceed newly severe rows.
3. **Catastrophic protected-slice bar:** no protected slice may regress by more
   than pooled improvement, with tolerance `1e-12`. Protected dimensions remain
   `market`, `capture_hour`, `floor_source`, `binding_strength`,
   `forecast_relative_winner`, and `D_class`; the latter two are evaluation
   labels only and never gate predictors.

After the numeric threshold is frozen, score only the freshest complete,
coverage-clean, promotion-countable POST-regime dates outside July 22-30 that
the mirror actually holds: July 31, plus August 1 only if already present. The
freshness gate is scoped to exactly those dates. Do not wait for or substitute
another date. August 6-19 remains reserved and will not be read, enumerated, or
evaluated. A one-date score is explicitly weak evidence.

## Development selection

The development-only selection completed at `2026-08-02T16:29:37.597938Z`
over 36 validation market-days and 6,523 snapshots. All 168 market/hour groups
were available in each chronological fold. The result file is SHA-256
`44f752331f647d9381221d4b0c3e4fbc84f41a0d2db5a568e9a923764cb68373`.

| Threshold | Brier delta | Bootstrap upper | New severe | Retired | Catastrophic slices | Failed primary gates |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `1%` | -0.000068745 | +0.005132717 | 1,257 (1.75184%) | 1,519 | 23 | 3 |
| `5%` | -0.001895369 | +0.001267434 | 550 (0.76652%) | 1,022 | 8 | 2 |
| `20%` | **-0.003212643** | **-0.000943804** | **124 (0.17282%)** | **834** | **1** | **1** |

The predeclared lexicographic rule therefore selects and freezes **`T = 0.20`**
at `2026-08-02T16:30:05.7612545Z`. The primary gate for fresh scoring is exactly
`floor_available and floor_removed_mass > 0.20`; this value will not change
after fresh evidence is read. This is not a development qualification claim:
the 20% gate still failed the conjunctive catastrophic-slice bar in one of 54
protected slices.

## Fresh-score verdict

**FAIL. Do not qualify the gated lane.** The frozen 20% floor-informativeness
gate passes bootstrap non-regression and the newly-severe cap on July 31, but
it still fails the conjunctive catastrophic protected-slice bar in **3 / 53**
observed slices. The lane therefore remains held and `NOT_READY`.

| Primary gate | Result | July 31 evidence |
| :--- | :---: | :--- |
| One-sided 95% market-day bootstrap non-regression | **PASS** | Brier `0.056481213 -> 0.049621255`; delta `-0.006859959`; upper bound `-0.002075876`. |
| Newly-severe cap | **PASS** | 140 / 23,716 = `0.59032%`, below `1.15535%`; 642 retired, so retired > new. |
| Catastrophic protected slice | **BLOCK** | 3 / 53 slices regress by more than pooled improvement `0.006859959`. |

The 1,425 excluded snapshots contributed 15,675 band rows. All 15,675
`candidate_p` strings exactly equal their incumbent `replayed_p` strings, with
zero mismatches. They therefore contribute **zero newly-severe rows by
construction**. All 140 newly-severe rows come from the 731 qualified
snapshots; there is no gate-crossing leakage.

### Bootstrap and severe-tail movement

The bootstrap did tighten: its upper bound moved from the ungated candidate's
`+0.003147121` to `-0.002075876`, a tightening of `0.005222997`. This is the
intended variance separation, but it is estimated from only 12 market-days on
one target date and cannot override the slice failure.

Fixed severe-tail positive excess fell from `0.335330315` to `0.232344906`, a
reduction of `0.102985409` or **30.71%**. That preserves **52.74% of the prior
58.23% reduction magnitude**. Severe rows fell from 1,673 to 1,171. The tail
gain survives materially, but less than the ungated four-day estimate.

### Precise null

**Null: a coarse gate on cutoff-time floor-removed mass alone, with the lane
restricted to `>20%`, is insufficient to make the frozen continuation
candidate protected-slice-safe on fresh July 31 evidence.** It separates the
pooled win from much of the loss well enough to pass bootstrap and new-severe
gates, but does not remove three concentrated regressions:

| Protected slice | Brier delta | Pooled bar | Severe baseline -> candidate | Finding |
| :--- | ---: | ---: | ---: | :--- |
| `D_class=D1` | +0.032302 | +0.006860 | 45 -> 105 | **BLOCK** |
| `capture_hour=14` | +0.007065 | +0.006860 | 72 -> 89 | **BLOCK** |
| `capture_hour=17` | +0.008626 | +0.006860 | 42 -> 43 | **BLOCK** |

`D_class` is used here only as the frozen outcome-based evaluation label. It
was never available to, or used by, the gate. No hour-based or combined gate
was tried after this failure.

## Evidence and guardrails

The exact fresh-date probe found all 12 July 31 folders and all 12 August 1
folders. The pinned corpus admitted every July 31 market-day as `complete`,
coverage-clean, and promotion-countable. All 12 August 1 folders lacked a
settlement label, so August 1 was not scoreable, was not waited on, and was not
replaced. The resulting score window is only **July 31: 12 market-days, 2,156
snapshots, and 23,716 band rows**. This is explicitly weak one-day evidence.

The accepted replay was regenerated wholly after the July 31 `rows[-1]`
boundary from the pinned inputs, with zero corpus warnings. The floor trace
covered the same 2,156 snapshots, found zero floor-above-settlement cases, and
matched the replayed served probabilities and centres at maximum error `0.0`.
The scorer reused the exact held candidate artifact and matched every parent
artifact SHA-256 before prediction.

Execution caveat against the pre-registration's stricter phrase "will not be
read": the hash-bound accepted development files physically contain July
22-30, so whole-file SHA-256 verification and chunked date filtering traversed
the July 27-30 bytes. Only July 22-26 records were retained, and only July
24-26 records entered threshold metrics; no July 27-30 row was fitted, scored,
materialized into the development OOF output, or used in the choice. This
satisfies the handoff's prohibition on selecting from the burned window, but
the narrower byte-read statement in the local pre-registration was too strong
and is corrected here rather than hidden.

| Field | Value |
| :--- | :--- |
| Handoff source | `origin/master` `fa1dce3e` |
| Exact stacked base | held continuation candidate `1e525a02dfce1ba8c0d58a506877d3a778e8fe58` |
| Topic branch | `codex/workstation-floor-informativeness-gate-2026-08-13a` |
| Pre-registration commit | `a2608a3d` |
| Frozen implementation commit | `bae61edc` |
| Frozen threshold commit | `dc580703` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\floor-informativeness-gate-2026-08-13a` |
| Declaration time | `2026-08-02T16:18:35.5906455Z` |
| Development dates | July 22-26; validation July 24-26 |
| Fresh score date | July 31 only |
| Reserved confirmation dates | August 6-19; not read, enumerated, or evaluated |

| Evidence | SHA-256 |
| :--- | :--- |
| Frozen continuation candidate | `d542ec0955f5fa7e7feab8541d78ba124d8f99f7f556cd7f1e0a2290f8275c85` |
| Development selection | `44f752331f647d9381221d4b0c3e4fbc84f41a0d2db5a568e9a923764cb68373` |
| Fresh corpus | `1819735713d12531f74515a5d3acb40027dc7fe4dee7799050bcb6cdb1264203` |
| Fresh incumbent replay rows | `ce3b249f6857b96657820ba0e7c3988359c816338c199352ce1dbc8d0c0ead94` |
| Fresh floor trace | `54d3d7f47cbb19b0686f2ea6b15af3366af43787bf733e0d5da9cc314c982abc` |
| Fresh gated candidate rows | `0aeca914e3f05b2b559e968fe8ae959ca19bae529ca6791030f0d3ed82fd835d` |
| Harness scorecard | `382b61f5c09af532d71f1ae88da7f110bb45d8ce1667bce65d36f7be5821b2e8` |
| Protected slices | `e6cf6cc4aad5683bb640463517539da4ae16d095f25911c30c1c9a427fbf8883` |

Forty-one focused gate, candidate, harness, schema-registry, and import-
architecture tests passed. `app`, `src`, and `tests` compiled; the agent-docs
audit passed; and the strict source schema audit reported zero unregistered
versions. `data/` and the mirror remained read-only. No July 27-30 score result
entered threshold selection; no August 6-19 date was read or enumerated. No
production host, sync credential, paid provider, release, promotion, pointer,
serving, scheduler, capture, mirror topology, or ACL state was accessed or
changed. No PR, merge, or master push was made.

# Workstation D1-anchor repair report - 2026-08-02

## Pre-registration - frozen before fitting or development-result inspection

Declared at `2026-08-02T17:33:00.1091460Z`. The sole output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\d1-anchor-repair-2026-08-15a`,
outside the mirror. `data/` and the mirror remain read-only.

This mission is build-only. It will read exactly `2026-07-22` through
`2026-07-26`, fit/select only through the same forward folds used by 08-13a,
and freeze one repaired research artifact. It will not read, enumerate, replay,
or score July 27 onward. In particular, July 31 and August 6-19 remain
untouched. No fresh-date probability or result will be produced.

The immutable inputs and controls are:

- stacked base `703075f7e3a906f7a5e6f723974f97b3930e898f`;
- frozen candidate SHA-256
  `d542ec0955f5fa7e7feab8541d78ba124d8f99f7f556cd7f1e0a2290f8275c85`;
- frozen application gate
  `floor_available and floor_removed_mass > 0.20`;
- the existing target, features, parent models, temperature/blend calibration,
  hard floor, and native-to-band conversion.

### Smoothing form

Smoothing applies to the final post-blend, post-hard-floor native continuation
distribution. Let `p0=P(D=0)`, `p1=P(D=1)`, and
`pt=P(D>=2)`. If `p1 >= pt`, the distribution is unchanged. Otherwise, for
strength `s`, transfer `s * (pt - p1) / 2` from the `D>=2` tail to `D1` and
reduce each tail bucket proportionally. `D0` is unchanged exactly. No mass is
created below the trusted floor, and total probability remains one.

This is a local ordinal valley pool, not an outcome-conditioned rule: it uses
only the ordered predicted support and never the realized settlement. It
minimally removes the adjacent-state valley relative to the more distant tail.

The coarse selectable strengths are exactly `{0.50, 0.75, 1.00}`. Strength
`0.00` is retained only as the unsmoothed comparison and cannot be selected.

### Development folds and selection rule

The folds are frozen as:

1. train July 22-23, validate July 24;
2. train July 22-24, validate July 25;
3. train July 22-25, validate July 26.

Every metric is market-day grouped. Selection uses only snapshots qualifying
under the frozen 20% gate and follows this predeclared rule:

1. discard a strength unless qualified D1 validation rows have mean
   `P(D1) >= P(D>=2)`;
2. discard it unless qualified D0 validation rows retain lower daily-first
   Brier and fewer severe rows than the incumbent;
3. among eligible strengths, minimize the D0 daily-first Brier cost relative
   to the unsmoothed candidate, then pooled gated daily-first Brier, then use
   the smaller strength on an exact tie.

If no strength is eligible, no scoreable repair will be claimed. The failure
will be reported plainly. No parameter, criterion, or fallback will be added
after development evidence is inspected.

## Build result

**BUILT AND FROZEN; UNSCORED.** The selected smoothing strength is **`1.00`**.
The final repaired research artifact is:

`C:\Users\Michael\Documents\github\weather\scratch\runs\d1-anchor-repair-2026-08-15a\final\ordinal-repaired-continuation-candidate.pkl`

Its SHA-256 is
**`ba6cd8b7c02a6d6890762b17ab139fb9a3afbf146239b9e617ea192eea4970ef`**.
The artifact declares `score_dates=[]`; no score corpus, score replay, or fresh
metric was produced.

Strength `1.00` was the only predeclared setting that satisfied the structural
D1 criterion. The lower strengths improved D0 and had slightly lower pooled
development Brier, but both left mean `P(D1) < P(D>=2)` and were therefore
ineligible under the frozen selection rule.

The artifact copies the frozen candidate's 168 market/hour model payloads.
Semantic estimator-state comparison confirms all 168 are unchanged. The only
per-model additions are `ordinal_smoothing_form=post_blend_d1_valley_pool` and
`ordinal_smoothing_strength=1.0`. The original artifact, target, features,
temperature, blend, prior, and hard-floor stages are otherwise unchanged. The
20% application gate is not part of the artifact and remains frozen for the
later scorer.

## Development evidence

Across 1,126 gate-qualified validation snapshots, 54 were D1. Their mean native
distribution changed as follows:

| Stage | `P(D0)` | `P(D1)` | `P(D>=2)` | D1 valley gone? |
| :--- | ---: | ---: | ---: | :---: |
| Frozen unsmoothed candidate | 0.375846 | 0.183163 | 0.440990 | **No** |
| Repaired, strength `1.00` | 0.375846 | 0.314576 | 0.309577 | **Yes** |

`P(D0)` is unchanged exactly by construction. The full-strength result has
`P(D1) > P(D>=2)` in aggregate because snapshots that were already monotone are
no-ops; valley snapshots are pooled to equality.

| Strength | D1 `P(D1)` | D1 `P(D>=2)` | Structural result | Qualified-D0 Brier | D0 severe rows | Pooled gated Brier |
| ---: | ---: | ---: | :---: | ---: | ---: | ---: |
| `0.50` | 0.248870 | 0.375284 | **FAIL** | 0.007686 | 55 | 0.046381 |
| `0.75` | 0.281723 | 0.342431 | **FAIL** | 0.006331 | 46 | 0.046455 |
| `1.00` | **0.314576** | **0.309577** | **PASS / selected** | **0.005161** | **34** | 0.046594 |

### D0 cost

There is no observed D0 cost on the development folds. On 875 qualified D0
snapshots, daily-first Brier moved `0.025895980 -> 0.010951541 -> 0.005160710`
(incumbent -> unsmoothed -> repaired). The repair improves on the unsmoothed
candidate by `0.005790831` and on the incumbent by `0.020735269`. Severe rows
moved `666 -> 82 -> 34`.

The result is consistent on each forward validation date:

| Validation date | Qualified D1 | Repaired `P(D1)` / `P(D>=2)` | D0 Brier incumbent / unsmoothed / repaired | D0 severe incumbent / unsmoothed / repaired |
| :--- | ---: | :---: | :--- | :--- |
| `2026-07-24` | 13 | 0.2740 / 0.2740 | 0.020604 / 0.007452 / 0.003094 | 148 / 40 / 14 |
| `2026-07-25` | 23 | 0.3038 / 0.3038 | 0.021796 / 0.015045 / 0.006555 | 204 / 9 / 0 |
| `2026-07-26` | 18 | 0.3576 / 0.3426 | 0.034114 / 0.010432 / 0.005749 | 314 / 33 / 20 |

### Development-selection caveat

There is still a real development-only risk. The structural choice rests on
only 54 qualified D1 snapshots across three dates, and strength `1.00` was
selected on those same folds. It was the only setting that crossed the
predeclared structural boundary, so fresh evidence could show that full valley
pooling is too strong. The result is less suggestive of ordinary Brier chasing
because the selected setting has slightly worse pooled development Brier than
the two structurally invalid settings, the correction is deterministic, and
all three folds agree. None of that substitutes for the untouched 08-16a score
pass.

## Evidence and guardrails

The bounded manifest was constructed from 60 explicit registry-derived folder
paths: 12 markets times July 22-26. It admitted 60 complete,
coverage-clean, promotion-countable market-days, 10,885 snapshots, and 119,735
band rows, with zero feature-quality exclusions. Accepted replay scored all
10,885 snapshots with zero corpus warnings. The matching floor trace covered
all 10,885 snapshots, found 10,837 floors available, zero floors above
settlement, maximum served-probability mismatch `0.0`, and maximum centre
mismatch `0.0`.

One create-only draft build used the descriptive label
`post_blend_d1_valley_pool_v1`. The schema ratchet correctly treated that
suffix as an unregistered schema-looking version. The label was changed to the
version-neutral `post_blend_d1_valley_pool`, and the identical frozen selection
was rebuilt under the `final` subdirectory. Selected strength and every result
metric reproduced exactly. Only the `final` artifact and hashes below are
authoritative.

| Field | Value |
| :--- | :--- |
| Handoff source | `origin/master` `bf3c9a95` |
| Exact stacked base | `703075f7e3a906f7a5e6f723974f97b3930e898f` |
| Topic branch | `codex/workstation-repair-d1-anchor-2026-08-15a` |
| Pre-registration commit | `7f286705` |
| Implementation commit | `2e53f078` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\d1-anchor-repair-2026-08-15a` |
| Declaration time | `2026-08-02T17:33:00.1091460Z` |
| Frozen base candidate | `d542ec0955f5fa7e7feab8541d78ba124d8f99f7f556cd7f1e0a2290f8275c85` |
| Frozen repaired candidate | `ba6cd8b7c02a6d6890762b17ab139fb9a3afbf146239b9e617ea192eea4970ef` |
| Frozen smoothing strength | `1.00` |
| Frozen application gate | `floor_available and floor_removed_mass > 0.20` |

| Evidence | SHA-256 |
| :--- | :--- |
| Development corpus | `8cf0d01d222172dadd024b3e55a69494860477785ec100cbe8ae2ed546c1662d` |
| Development replay rows | `55fd5104d7aa8240a9714d368ab15dd9bda34d87c4da27d7025b6cdb7c8e9ccd` |
| Development floor trace | `2e9da6e324130494760cd6b2dbe632658f6b29b99615439bab66fa1141519c9b` |
| Final selection | `39dcd3346231459810721863cb127d8bb6f1194eee04c55e548cdc1d655aa1b2` |
| Final OOF native distributions | `4d751da7efd5ff0207a625c8518e30babcd09ac376516e86509054fc34883217` |
| Development consistency split | `3b1d4a8743b8facdd8058f2d114ef31e3736d48770c70b7f121260b4e1bd94fd` |
| Final repaired artifact | `ba6cd8b7c02a6d6890762b17ab139fb9a3afbf146239b9e617ea192eea4970ef` |
| Final summary | `bff952713caf51624e93b1f5f012ab2edbf14b51ffb81d8762bc0cfe5abb3884` |

The calibration and gate suite passed 340 tests plus 47 subtests; the schema
and import ratchets passed 28 tests. `app`, `src`, and `tests` compiled, and the
agent-docs audit passed across 18 agent files and 574 Markdown files. Semantic
artifact verification passed for all 168 model groups.

`data/` and the mirror remained read-only. No date outside July 22-26 was read,
enumerated, replayed, evaluated, or substituted. No fresh date was scored. No
production host, sync credential, paid provider, release, promotion, pointer,
serving, scheduler, capture, mirror topology, or ACL state was accessed or
changed. No PR, merge, or master push was made.

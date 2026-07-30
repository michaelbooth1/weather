# Agent report — 2026-07-30 workstation rescued floor

## Verdict

The hard-floor defect is fixed at the shared derivation seam. Feature
extraction and served calibration now share one observation context. When WU
history is empty, both use the already-admitted captured station/current rescue.
When WU history exists, the served hard floor remains aligned to that WU print
and supporting-source disagreement retains its learned soft treatment. The fix
does not invent a forecast or climatology floor, and all 61 genuinely
feature-floorless POST snapshots remain floorless.

This is a material skill change, not correctness-only. Against the exact
pre-change commit on the frozen accepted POST F population:

- incumbent Brier improves from `0.063698529` to `0.057345359`
  (`-0.006353169`);
- configured postblend improves from `0.049848537` to `0.048167753`
  (`-0.001680783`);
- pooled preblend is byte-semantically unchanged at `0.047567961`.

The stopping rule therefore does **not** fire. The result does not close the
specific Atlanta preblend blocker: its daily-first distance to tolerance is
still exactly `0.0013571246053345086`.

No promotion, release pointer, serving process, collector, scheduler, mirror,
ACL, paid-provider setting, PR, merge, or `master` push was changed.

## Git preparation

I fetched and verified `origin/master` at
`c3e8e9f5b71357e6f2e2daa9f7dbb635af0be5f3`, rebased the topic branch onto it,
and pushed the rebased branch before beginning. The pre-change baseline is
`e8fdce38cf4c30aca947fbcc49fad2619d53cc92`; its parent is the requested
keystone-containing `c3e8e9f5`.

Branch:
`codex/workstation-fix-floor-toronto-2026-07-31b`.

The unrelated main-worktree edit to `config/storage_pressure.json` was not
touched.

## Rescue-aware fix

### Red test first

The focused red run was:

```text
python -m pytest -q tests/model/test_estimate_distribution.py \
  -k "station_rescue or missing_wu_rows"
```

It produced two expected failures and one pass:

- Celsius station rescue: feature `high_so_far=26`, served floor `None`;
- Fahrenheit station rescue: feature `high_so_far=91`, served floor `None`;
- no admitted observation: floor remained `None`.

After the fix, the expanded cutoff/rescue selection passed 5/5, and the
distribution plus feature-store suites passed 79/79.

### Implementation

`ModelUtilsMixin.effective_observed_high_context` is now the single derivation
used by both feature extraction and the distribution/calibration floor. It
returns the feature high and the narrower served hard-floor high:

1. select target-date WU rows at the effective cutoff;
2. use the latest cutoff-aligned WU temperature when rows exist;
3. when WU is empty, admit the captured current station observation;
4. from 07:00 onward, allow the captured station/current
   `max_since_7am_native` to rescue that empty-WU path;
5. apply the existing native-unit startup plausibility quarantine;
6. leave the value `None` when no admitted observation exists.

The calibration context records `effective_observed_high`,
`effective_observed_floor_high`, `effective_observed_floor_bucket`, and
`effective_observed_high_source` while retaining the separate WU-only audit
field. Celsius and Fahrenheit regression tests verify feature/floor equality
on the empty-WU rescue path and impossible-band suppression.

The durable source-role documentation now states this explicit empty-WU
exception. When an existing WU print and a supporting source disagree, the
prior learned soft catch-up contract remains unchanged; the rescue is not a
blanket promotion of every support source.

This refactors an existing live feature without changing its schema or trained
feature meaning, so no artifact was regenerated and no release binding was
altered. Replay identity still changes through the distribution-code
fingerprint.

## Frozen POST remeasurement

### Method and integrity

Evidence root:

```text
C:\Users\Michael\Documents\github\weather\scratch\agent-runs\workstation-rescued-floor-2026-07-31c
```

The accepted population is unchanged: 11 F markets, 11,661 snapshots, and
128,271 complete band rows. I replayed each captured input twice:

- baseline: exact detached source at `e8fdce38`, where the served hard floor is
  WU-only but the feature path still has station rescue;
- rescued: the candidate source with the shared derivation.

The pooled preblend artifact is fixed because its native band runtime already
uses persisted `high_so_far`. Each postblend is rebuilt with canonical
`blend_with_current` and configured partition mass restoration, changing only
the incumbent replay input. No post-hoc zero-and-renormalize floor transform
was used.

All lane simplexes have maximum error at or below
`2.220446049250313e-16`. Canonical reconstruction of the frozen old postblend
is within `2.76e-12` of its stored values, below the `1e-10` gate. Input hashes
were unchanged.

### Floors

| Contract | Baseline | Rescued |
| :--- | ---: | ---: |
| Floor-present snapshots | 0 | 11,600 |
| Genuinely floorless snapshots | 11,661 | 61 |
| Current snapshots with impossible mass | 7,225 | 0 |
| Postblend snapshots with impossible mass | 7,193 | 0 |
| Cumulative current mass fully below floor | `1363.939243` | `0` |
| Floorless-snapshot maximum current change | — | `0` |

Rescue provenance is 8,037 `max_since_7am` values, 3,563 cutoff-aligned current
observations, and 61 nulls. Every non-null rescued bucket matches the persisted
feature bucket.

### Brier by market-local hour

The pooled preblend delta is `0` in every cut.

| Hour | Snapshots | Current before | Current after | Current Δ | Postblend before | Postblend after | Postblend Δ |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00-02 | 1,537 | `0.077246578` | `0.077214156` | `-0.000032421` | `0.072092696` | `0.072070181` | `-0.000022515` |
| 03-08 | 3,106 | `0.076604338` | `0.076599600` | `-0.000004738` | `0.072826003` | `0.072819538` | `-0.000006464` |
| 09-14 | 2,761 | `0.070734649` | `0.069196604` | `-0.001538044` | `0.064962562` | `0.064389591` | `-0.000572971` |
| 15-17 | 1,384 | `0.049772406` | `0.033202510` | `-0.016569897` | `0.024391796` | `0.019953234` | `-0.004438562` |
| 18-23 | 2,873 | `0.042444868` | `0.026141184` | `-0.016303684` | `0.010845760` | `0.006731598` | `-0.004114162` |
| Overall | 11,661 | `0.063698529` | `0.057345359` | `-0.006353169` | `0.049848537` | `0.048167753` | `-0.001680783` |

The effect is physically shaped rather than a global remap: negligible before
09:00 and concentrated once the daily high is established.

### Atlanta

| Lane | Weighting | Before Δ vs market | After Δ vs market | Change | Gate |
| :--- | :--- | ---: | ---: | ---: | :--- |
| Preblend | Daily-first | `0.004357125` | `0.004357125` | `0` | Fail; `0.001357125` beyond tolerance |
| Preblend | Row-weighted | `0.006003178` | `0.006003178` | `0` | — |
| Postblend | Daily-first | `0.016675625` | `0.011608803` | `-0.005066822` | Still fail |
| Postblend | Row-weighted | `0.015632805` | `0.014041331` | `-0.001591474` | — |

The answer to “does it close the `0.001357125`?” is **no**. That number belongs
to the already-floor-aware preblend lane, which this base-model fix correctly
does not mutate.

## Point-in-time attestation

The improved scores use no observation the model lacked at emission:

- all 11,600 floor-bearing station items have `fetched_at <= built_at`;
- all 160,830 backing observation rows have raw METAR `DDHHMMZ` or source-valid
  time `<= built_at`;
- zero rows have an actual observation time after build;
- all 11,600 non-null floors match the feature value persisted at that
  snapshot;
- the 61 null-feature snapshots remain null and unchanged.

There is an important cutoff-label nuance. On the empty-WU path,
`high_so_far` is deliberately a captured through-NOW feature. A METAR observed
at 17:52 can carry an hourly display label of 18:00. There are 5,406 backing
rows whose display label is beyond the coarse integer-hour boundary, but their
raw observation time is before build. They are not future information and the
model did hold them at emission. Interpreting “cutoff” as the model-emission
cutoff gives zero post-cutoff observations; interpreting it as top-of-hour
would misclassify those live readings.

For 806 max rescues, the captured max summary does not exactly reconstruct from
the retained backing row temperatures. This is a provenance limitation, not
future leakage: the summary itself and its station item were captured before
build, and every retained backing row is also pre-build. None of the measured
gain is classified unusable.

## WU absence

### Timeline: outage first, policy second

The local read-only scan covers 663 replay files and 98,124 captured records.

| WU-history state | Records |
| :--- | ---: |
| Usable rows | 35,906 |
| Settlement-source auth failure | 4,663 |
| Paid provider disabled | 56,288 |
| Other expected/current-day/unknown failures | 1,267 |

The last usable WU-row capture is Seattle at
`2026-06-27T05:19:11.487861Z`. The first explicit auth failure follows about
9.05 minutes later at `2026-06-27T05:28:14.312281Z`. Auth failures continue
through `2026-06-30T14:03:35.346467Z`; the first
`paid_provider_disabled` capture appears at
`2026-06-30T14:22:17.383070Z`.

So capture did **not** initially stop because of the priced-policy decision. It
stopped in an authentication outage on June 27. The continued absence became a
deliberate policy on June 30. Commit
`5735b573aa284da070fba9b751d3a48f5819aca4` removes paid API-key use,
introduces `paid_weather_provider_disabled`, disables paid backfill, and adds a
free public page-backed WU history client. Its recorded commit time is
`2026-06-30T12:16:08-04:00`. After that transition the absence is visible
expected degradation, not silent drift.

### What the fleet is losing

The causal value of WU is **not identifiable** from the contemporary frozen
corpus:

- the broader pooled report has 206,745 degraded-source rows and no all-fresh
  slice;
- explicitly named WU-failed freshness groups cover at least 204,413 rows, with
  additional groups truncated behind `+N`;
- the source-state ablation has no WU feature group and there is no
  contemporary WU-present overlap.

On that confounded population, candidate Brier is `0.062056114` versus market
`0.037368631`, a gap of `0.024687483`; daily-first gap is `0.026442901`.
Those values are an upper-bound correlation, not the cost of WU. Likewise, the
prior 78.93% statistic is for **forecast**-source disagreement and cannot be
reassigned to missing WU observations.

This cycle does measure one concrete loss that WU absence exposed: failing to
honor the already-captured station rescue cost `0.006353169` incumbent Brier
and `0.001680783` configured-postblend Brier on the accepted POST F population.
That is the cost of the floor-contract bug, not a WU counterfactual.

### Recommendation

Do not re-enable or buy the paid provider. The repository already has a free
public page-backed WU collector. The next valid measurement is a bounded,
research-only overlap capture from that free path, followed by direct
comparison with station rescue. This report did not run that collector or
change any capture setting.

## Verification

- Focused model and calibration suite: 412 passed, 666 subtests passed.
- Rescue, missing-WU, cutoff-alignment, and existing-WU disagreement selection:
  8 passed after the final semantics adjustment.
- Full frozen replay: 11,661 snapshots and 128,271 bands; rescued output SHA-256
  `3c8f85d8eb36e0f91a4ef6945b7c64006fd402a028c932100d51abfbad6bc8ae`.
- `python -m compileall -q app src tests`: passed.
- `python -m weather.operations.agent_docs_audit`: passed (18 agent files, 533
  Markdown files).
- `git diff --check`: passed.

The first whole-repository run reached 3,228 passes, 820 passed subtests, and 4
skips. It exposed three task-relevant existing-WU soft-floor regressions; those
were fixed and the affected tests are included in the clean focused results
above. The remaining 27 failures were pre-existing/environmental workstation
constraints: Windows receipt-stat races, experiment-executor sandbox
restrictions, PowerShell execution policy, and the memory threshold check.

## Evidence

Key artifacts under the declared run root:

- `predeclaration.md`
- `replay_lane.py`
- `baseline_current_replay.json` and `.csv`
- `rescued_current_replay.json` and `.csv`
- `compare_replays.py`
- `rescued_floor_comparison.json` and `rescued_floor_rows.csv`
- `wu_absence_audit.py` and `wu_absence_audit.json`

The mirror and all `data/` inputs remained read-only.

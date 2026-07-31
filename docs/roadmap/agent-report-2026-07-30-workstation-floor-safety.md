# Agent report — 2026-07-30 workstation floor safety

## Verdict

The hard rescued floor passes the requested safety audit.

- F family: **0 / 11,600** enforced floors exceed the realized settled
  bucket.
- Toronto: **0 / 1,213** enforced floors exceed the realized settled bucket.
- The overshoot distribution is empty in both unit families.
- The two Toronto and 61 F-family snapshots without admitted observations stay
  floorless and byte-probability unchanged between the two replay lanes.

This directly tests the failure mode behind the standing prohibition. On this
frozen POST evidence, neither the captured max-since-07:00 rescue nor the
captured current-observation rescue ever excludes the truth. The conditional
hedged fallback therefore does not trigger. I recommend retaining the hard
variant from `b77cfbed`.

The result does not mean every snapshot's multiclass Brier improves. The hard
floor worsens 4,385 F incumbent snapshots, 4,046 F postblend snapshots, and 407
Toronto snapshots while improving the mean. Those regressions are measured
below. In every worst case the floor equals, rather than exceeds, settlement;
the Brier worsening comes from redistribution among still-possible bands, not
from assigning zero probability to the truth.

No promotion, pointer, serving, scheduler, capture, mirror, ACL, paid-provider,
PR, merge-to-master, or master-push action was taken.

## Git preparation

I fetched exact `origin/master`
`617b2aa36b5fbc05223d2173403a6cca9fb5709e`. It diverged from the topic branch,
so rebasing would have rewritten the hard variant. I instead merged it into
`codex/workstation-fix-floor-toronto-2026-07-31b` at `2f2ce551`, preserving
`b77cfbed49ee85cc0009a2058e842dda08036272` unchanged, and pushed that merge
before beginning the audit.

## Mission 1 — hard-floor safety

### Population and settlement join

The audited population is the same accepted 11-market POST F population used
for the rescued-floor replay: 11,661 snapshots and 128,271 complete band rows.
Every snapshot joined to its retained exact `settlement_high` by
`(market_id, target_date, snapshot_id)`. The settlement value was rounded with
the same half-up whole-native-unit contract as the floor; a winning range band
was not treated as an exact settlement value.

Of 11,661 snapshots, 11,600 have a hard rescued floor:

| Rescue source | Enforced floors | Above settlement |
| :--- | ---: | ---: |
| Current/station `max_since_7am` | 8,037 | **0** |
| Cutoff-aligned current observation | 3,563 | **0** |
| No admitted observation | 61 | n/a |

The all-zero result also holds in every local-hour group:

| Local hour | Enforced floors | Above settlement |
| :--- | ---: | ---: |
| 00-02 | 1,503 | **0** |
| 03-08 | 3,095 | **0** |
| 09-14 | 2,750 | **0** |
| 15-17 | 1,382 | **0** |
| 18-23 | 2,870 | **0** |

And in every market:

| Market | Enforced floors | Above settlement |
| :--- | ---: | ---: |
| Atlanta | 944 | **0** |
| Austin | 1,133 | **0** |
| Chicago | 1,121 | **0** |
| Dallas | 1,108 | **0** |
| Denver | 1,075 | **0** |
| Houston | 1,094 | **0** |
| Los Angeles | 1,092 | **0** |
| Miami | 1,084 | **0** |
| NYC | 911 | **0** |
| San Francisco | 1,094 | **0** |
| Seattle | 944 | **0** |

The overshoot-in-buckets distribution is therefore `{}`. There is no
one-bucket or larger over-final tail hidden by the pooled mean.

### Per-snapshot incumbent regressions

Each snapshot's multiclass Brier is the mean squared error across its complete
11-band vector.

| Result | Snapshots |
| :--- | ---: |
| Improved | 7,215 |
| Unchanged | 61 |
| Worsened | 4,385 (37.6040%) |

For the 4,385 worsened snapshots, the after-minus-before Brier delta is:

| Statistic | Delta |
| :--- | ---: |
| Mean | `+0.004017125` |
| Median | `+0.000084388` |
| P90 | `+0.014697162` |
| P95 | `+0.029011253` |
| P99 | `+0.044036685` |
| Maximum | `+0.074697440` |

Worst incumbent case:

```text
dallas|2026-07-03|20260704T000333747013-0400
local hour: 23
source: current_or_station_max_since_7am
floor: 97 F
settlement: 97 F
Brier delta: +0.07469743953649208
```

Across all snapshots, including gains and regressions, the mean delta remains
`-0.0063531694745118114`.

### Per-snapshot postblend regressions

| Result | Snapshots |
| :--- | ---: |
| Improved | 7,554 |
| Unchanged | 61 |
| Worsened | 4,046 (34.6969%) |

For the 4,046 worsened postblend snapshots:

| Statistic | Delta |
| :--- | ---: |
| Mean | `+0.001306516` |
| Median | `+0.000050312` |
| P90 | `+0.005090006` |
| P95 | `+0.008018864` |
| P99 | `+0.016182417` |
| Maximum | `+0.019513284` |

Worst postblend case:

```text
san-francisco|2026-07-09|20260709T180152485059-0400
local hour: 15
source: current_or_station_max_since_7am
floor: 67 F
settlement: 67 F
Brier delta: +0.019513284233363633
```

Across all snapshots the postblend mean delta is
`-0.0016807834173592044`.

## Mission 2 — fallback decision

The fallback condition was “any enforced hard floor above settlement.” The
observed count is zero in F and Toronto, so I did not change the implementation
or run an unrequested hedged counterfactual. The hard implementation is
preserved exactly as the audited `b77cfbed` source.

This recommendation is limited to the frozen POST populations. The captured
sample establishes that the hard floor did not exceed settlement here; it is
not a proof that every future station observation is infallible. Continued
captured settlement comparison should remain a release/readiness monitor.

## Mission 3 — Toronto

### Safety

Toronto's exact July 2-10 POST population contains 1,215 snapshots, 13,365
complete band rows, and nine settled days. Exact replay through pre-hard
`e8fdce38` and the hard source produces 1,213 floors and two unchanged nulls.

| Rescue source | Enforced floors | Above settlement |
| :--- | ---: | ---: |
| Current/station `max_since_7am` | 839 | **0** |
| Cutoff-aligned current observation | 374 | **0** |
| No admitted observation | 2 | n/a |

Every local-hour group is also zero over-final:

| Local hour | Enforced floors | Above settlement |
| :--- | ---: | ---: |
| 00-02 | 147 | **0** |
| 03-08 | 349 | **0** |
| 09-14 | 294 | **0** |
| 15-17 | 139 | **0** |
| 18-23 | 284 | **0** |

Toronto's overshoot distribution is empty. This is the separate Celsius result
the F-family average could not establish.

### Before/after by local hour

| Local hour | Snapshots | Before | Hard | Delta |
| :--- | ---: | ---: | ---: | ---: |
| 00-02 | 149 | `0.089097578` | `0.089184667` | `+0.000087090` |
| 03-08 | 349 | `0.087234539` | `0.087219213` | `-0.000015326` |
| 09-14 | 294 | `0.067098603` | `0.066322436` | `-0.000776167` |
| 15-17 | 139 | `0.026707694` | `0.016570347` | `-0.010137347` |
| 18-23 | 284 | `0.007784946` | `0.000322990` | `-0.007461956` |
| **Overall** | **1,215** | **`0.057095207`** | **`0.054009732`** | **`-0.003085475`** |

The effect has the same late-day physical shape as F. The 00-02 slice is a
small regression rather than an across-the-clock improvement.

Toronto improves 806 snapshots, leaves the two floorless snapshots unchanged,
and worsens 407 (33.4979%). Among the worsened snapshots, mean delta is
`+0.000778800`, median is `+0.000009419`, P95 is `+0.004880980`, and the
maximum is `+0.040334774`.

Worst Toronto case:

```text
toronto|2026-07-04|20260704T170235110565-0400
local hour: 17
source: current_or_station_max_since_7am
floor: 27 C
settlement: 27 C
Brier delta: +0.04033477364639451
```

There is no authorized frozen Toronto postblend artifact. A C-family candidate
run remains explicitly deferred, so this report does not manufacture a
postblend comparison from another family.

## Mission 4 — served lane versus market

On the identical accepted F population and snapshot weighting used for the
served-lane headline:

| Lane | Candidate Brier | Market Brier | Delta vs market | Ratio to market |
| :--- | ---: | ---: | ---: | ---: |
| Baseline incumbent | `0.063698529` | `0.038282302` | `+0.025416227` | **`1.663916x`** |
| Hard rescued floor | `0.057345359` | `0.038282302` | `+0.019063057` | **`1.497960x`** |

At market-day-first weighting across 85 market-days:

| Lane | Candidate Brier | Market Brier | Ratio to market |
| :--- | ---: | ---: | ---: |
| Baseline incumbent | `0.062822275` | `0.035009073` | `1.794457x` |
| Hard rescued floor | `0.053253677` | `0.035009073` | `1.521139x` |

The earlier published `1.664x` ratio is reproduced on the exact population,
and the hard floor reduces it to `1.498x`. It is a substantial improvement,
but the served lane still trails market.

Toronto's snapshot-weighted served ratio moves from `1.242351x` to
`1.175213x` (`0.057095207 → 0.054009732` against market `0.045957402`).
Day-first ratio moves from `1.214326x` to `1.140290x`.

## Integrity and evidence

Declared run root:

```text
C:\Users\Michael\Documents\github\weather\scratch\agent-runs\workstation-floor-safety-2026-07-31d
```

Key artifacts:

- `predeclaration.md`
- `audit_hard_floor.py`
- `hard_floor_safety.json`
- `hard_floor_snapshot_deltas.csv`
- `replay_toronto_lane.py`
- `toronto_baseline_replay.json` and `.csv`
- `toronto_hard_replay.json` and `.csv`
- `compare_toronto_floor.py`
- `toronto_floor_safety.json`
- `toronto_floor_snapshot_deltas.csv`

Both Toronto lane simplexes have maximum absolute error
`2.220446049250313e-16`. All F and Toronto input hashes are identical before
and after their scans. Realized settlement labels are used only for scoring
and the safety join; they are never passed into model replay.

The hard Toronto replay source hashes exactly match the audited hard F replay.
The temporary baseline source is detached at exact `e8fdce38`. All `data/`
inputs remained read-only.

## Verification

- Hard F safety join: 11,661 snapshots, 11,600 enforced floors, zero missing
  settlement labels, zero over-final floors.
- Exact Toronto baseline and hard replays: 1,215 snapshots and 13,365 rows per
  lane; simplex error at most `2.220446049250313e-16`.
- Focused rescued-floor regressions: 5 passed.
- `python -m compileall -q app src tests`: passed.
- `python -m weather.operations.agent_docs_audit`: passed (18 agent files, 535
  Markdown files).
- `git diff --check`: passed.

This audit made no model-code change, so the hedged fallback and a new full
repository test run were not applicable. The broader implementation
verification remains recorded in the rescued-floor handback.

## Recommendation

Retain and merge the hard rescued-floor variant after normal review. The
blocking tail-risk question came back clean in both native unit families, the
served/market ratio improves from `1.664x` to `1.498x`, Toronto improves
materially, and the conditional fallback was not activated.

Keep a release/readiness monitor that joins every captured enforced floor to
eventual settlement and fails closed on any over-final observation. Do not
enable or buy the paid provider. The previously accepted next measurement
remains a bounded research-only overlap from the existing free page-backed WU
collector; propose it separately and do not run it from this handback.

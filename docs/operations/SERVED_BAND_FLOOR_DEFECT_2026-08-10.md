# The realized-band zeros were a serialization defect that ENDED on 2026-06-15

**Written 2026-08-10. CORRECTED the same day — the first version of this document called it a live
serving defect. It is not, and has not been since 2026-06-15.** The correction is recorded in full
below rather than silently applied, because the wrong version was cited in the `-09-64a` handoff.

## What the first version got right, and what it got wrong

| Claim | Status |
| --- | --- |
| 1,017 served snapshots publish exactly `0.0` on the band that settles | **Right** — reproduced exactly |
| The mechanism is a lost two-degree band upper edge reaching `hard_bin_probability` | **Right** — and now confirmed against a field transition and a falsifiable prediction |
| Toronto is a natural control, 1 against 1,016 | **Right**, for a better reason than stated |
| **"Live serving defect"; rate 1.017%** | **WRONG.** The rate is `8.486%` before 2026-06-15 and `0.000%` after |
| "The exact loss point is not yet identified" | **Resolved.** `bin_value_hi_c` was absent from the serialized band record until `28d1c146` |
| Toronto's single case is "a genuine below-floor band that still settled" | **Right by accident** — see the source-glitch trace below |

**The pooled `1.017%` averaged across a regime change and should never be quoted.** It is the
`a-stopped-counter` shape in a new costume: a number that is arithmetically correct over a window
that straddles the fix, and therefore describes nothing that exists now.

## The field transition

`snapshots_long.csv` gained a `bin_value_hi_c` column on **2026-06-15, in all 12 markets at once**.
First commit introducing it in `src/`: **`28d1c146`, 2026-06-15 15:41:05 -0400**, landing with the
band-audit-schema and serving-version-guard item.

| Era | Market-days | Snapshots | Realized-band zeros | Rate |
| --- | ---: | ---: | ---: | ---: |
| **Pre-fix** (`bin_value_hi_c` absent) | 111 | 13,545 | **1,016** | **7.501%** |
| — Fahrenheit only | 99 | 11,973 | 1,016 | **8.486%** |
| — Toronto (Celsius) | 12 | 1,572 | 0 | 0.000% |
| **Post-fix** (`bin_value_hi_c` present) | 552 | 86,561 | **1** | **0.001%** |
| — Fahrenheit only | 506 | **79,133** | **0** | **0.000%** |
| — Toronto (Celsius) | 46 | 7,428 | 1 | 0.013% |

**Zero Fahrenheit occurrences in 79,133 post-fix snapshots.** Sealed window `2026-06-03 → 2026-07-30`.

## The mechanism, now confirmed by prediction rather than by trace

A two-degree band is `[v, v+1]`. The lost-edge path computes `upper = v` and hard-zeros when
`v < floor_bucket`. Because `floor_bucket <= settled high`, a band that settles at its **lower**
degree can never be zeroed — `v < floor <= v` is impossible. **Only bands settling at the upper
degree can be.** That is a falsifiable prediction about which market-days are affected.

**19 of 19 affected pre-fix market-days settle on the upper degree of the winning band.** No
exceptions. Atlanta `2026-06-12` settled `91.0°F` on `90-91°F`; Chicago `2026-06-14` settled
`69.0°F` on `68-69°F`; and so on for all nineteen.

The guard itself was always correct and always documented the case
(`src/weather/calibration/probability_calibration.py:107`):

```
hard_bin_probability('eq', 90, 91, bin_value_hi=91)  -> None   # band stays live
hard_bin_probability('eq', 90, 91, bin_value_hi=None) -> 0.0   # what we served pre-fix
```

**The research and replay paths never had this defect at all.** `band_value_hi`
(`src/weather/market/market_microstructure_features.py:101`) falls back to parsing the upper number
out of `range_label` when the explicit column is missing, and `backtesting/replay.py:145` and
`backtesting/settlement_io.py:59` do the same. Only the serving consumer read the serialized field
without a label fallback. This is why the two surfaces disagreed.

## Toronto's single case is a source glitch, not a band defect

Toronto is the only Celsius market and uses **single-degree** bands (`19 C`, `20 C`) with
`bin_value_hi_c` legitimately blank, so the upper edge cannot be lost. Its one occurrence is
unrelated. At `20260615T104352-0400`, with the day settling at `20.0 C`:

| Snapshot | `wu_max_since_7am_c` | `wu_current_c` | `wu_history_high_c` |
| --- | ---: | ---: | ---: |
| `20260615T103022-0400` | 15.0 | 15.0 | 13.0 |
| **`20260615T104352-0400`** | **(blank)** | **(blank)** | **24.0** |
| `20260615T105538-0400` | 15.0 | 15.0 | 13.0 |

One snapshot lost its live observation, the floor fell back to a **history high of 24.0 C**, and the
distribution collapsed onto `24 C` and `25 C or higher`. Bracketed by 15.0 on both sides.
**One snapshot in 100,040 — but it is inside the 09:00–14:00 primary window.**

*Note on the census rule:* the census matched `eq` bands as two-degree everywhere, which is wrong
for Toronto. The error is conservative — it sums more mass, so it can only miss zeros, never invent
them — and re-checking Toronto under the correct single-degree rule returns the same single
snapshot. The Fahrenheit counts are unaffected.

## The separate question: does the floor ever exceed the day's high?

The floor input is `high_so_far` (`variant_prediction_runtime.py:369`,
`floor_bucket = round_half_up(high_so_far)`), read here from `features_long.csv`.

| Era | Snapshots with a floor | Floor **above** settled high | Rate | Caught by quarantine |
| --- | ---: | ---: | ---: | ---: |
| Pre-fix | 13,545 | 28 | 0.207% | **0** |
| Post-fix | 77,396 | 16 | **0.021%** | **0** |

Small, and much smaller than the band defect ever was. Two things are still worth recording:

- **`current_max_quarantined_flag` fired on none of the 44.** That is not damning on its own — the
  guard is a point-in-time heuristic and cannot know the settled high — but the worst case,
  **Seattle `2026-07-16`, floor `68` against a settled `64`, 8 snapshots, not quarantined**, is the
  kind of gap-to-current-temp divergence the guard exists to catch.
- **Do not quote `wu_max_since_7am_c` as the served floor.** Measured on that column the exceedance
  rate looks like ~19–22%, because **72% of post-fix snapshots no longer populate it** — the
  observation source migrated to `station_max_since_7am_c`. The served floor is `high_so_far`.

  > **CORRECTION, later the same day.** I originally wrote that the ~19–22% was a biased artifact
  > and should not be quoted at all. Wrong — I discarded the answer to a question I had not asked
  > yet. `-09-65a` established that the **replay reconstructs its floor from that very column**, so
  > ~21.8% is the error rate of the research surface's floor, not measurement noise. See
  > **`REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md`**, which also resolves Denver `2026-06-08`.

## What this means for the campaign

**Seattle `2026-07-16` is the paired panel's single C realized-band zero, and it is a floor
exceedance on production too, on the same market-day.** So the panel's zeros are floor-input cases,
not the serialization defect — consistent with the research path never having had it.

**Denver `2026-06-08` — RESOLVED by `-09-65a`, see
`REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md`.** It settled `82.0°F` on band `82-83°F`, the
**lower** degree, where the serialization mechanism cannot produce a zero at any floor, and
production's `high_so_far` never exceeded the settled high. The panel's `0.0` comes from a later
replay reconstructing a floor of **91** from `wu_max_since_7am_c` at **03:05**, when that column
still carries the *previous* day's window. Serving read `68.0` at that snapshot.

## What NOT to do

- **There is nothing to patch in serving.** It was fixed on 2026-06-15 by `28d1c146`. Do not open a
  serving change, and do not touch the floor: it remains the one shipped win (`1.6639 → 1.4980`).
- **Do not treat the 1,016 pre-fix zeros as model error in any evaluation.** They are a
  serialization artifact of the served tape on dates before 2026-06-15. Any scoring that uses the
  served band probabilities across that boundary is scoring two different systems.

## Reproduce

Census, field transition, upper-degree prediction, and floor audit scripts are in the session
scratch. The decisive one-liners:

```powershell
.\venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); from weather.calibration.probability_calibration import hard_bin_probability as h; print(h('eq',90,91,bin_value_hi=91), h('eq',90,91,bin_value_hi=None))"
# -> None 0.0
git log --format='%h %ad %s' --date=short -S bin_value_hi_c --all --reverse -- src/ | Select-Object -First 1
# -> 28d1c146 2026-06-15 add
```

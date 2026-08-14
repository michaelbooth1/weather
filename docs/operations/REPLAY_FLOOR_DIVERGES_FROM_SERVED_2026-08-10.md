# The replay reconstructs a floor we never served — in B. C is clean.

> **Read this first.** Joined to the panel's own rows, the divergence is **81.132% in B and
> 0.000% in C** (5,010 comparable rows, exact agreement). **The primary stratum is unaffected**,
> so `G = 0.021135322` and sections 1c–1g stand. The rest of this document is about B, and about
> a fleet-wide property of the raw column that would bite any future replay.


**Written 2026-08-10 by the production agent, verifying `-09-65a` on the served tape.**
Companion to `SERVED_BAND_FLOOR_DEFECT_2026-08-10.md`, which covers the *serving* defect that
ended 2026-06-15. **This one is about the research surface and it is not fixed.**

## The trace

`-09-65a` reported that the retained panel carries **no floor column at all** — all 12,289 rows
leave `floor_bucket` and `floor_source_field` blank, honestly declared — and that Denver
`2026-06-08`'s zero comes from a **later replay reconstructing a floor of 91** from a captured
`max_since_7am_c` of 91. Verified here, on the exact snapshot `-09-63a` stopped at:

| `20260608T030552-0400`, Denver, settled **82.0°F** | |
| --- | ---: |
| `high_so_far` — **what serving used** | **68.0** |
| `wu_max_since_7am_c` — what the replay reconstructed from | **91.0** |
| `wu_current_c` | 68.0 |

**It is 03:05 in the morning.** Before dawn, "max since 7am" still refers to *yesterday's* 7am
window, so it carries the previous day's high. Serving was never fooled: `high_so_far` tracked
68.0 and topped out at 82.0 for the day — exactly the settled high, never above it.

37 of Denver's 138 snapshots that day pair a `high_so_far` of 65–69 with a `wu_max_since_7am_c`
of 91.0.

## The size of it

Sealed window `2026-06-03 → 2026-07-30`. "Raw" is the reconstructible column
(`wu_max_since_7am_c`; post-fix, `max` with `station_max_since_7am_c`).

| | pre-fix (13,501) | post-fix (61,741) |
| --- | ---: | ---: |
| raw floor **> served floor** | 61.692% | 24.096% |
| **raw floor > SETTLED HIGH** | **21.776%** | **7.478%** |
| **served floor > settled high** | **0.207%** | **0.008%** |

**The floor we serve is above the day's actual high in 8 snapshots per hundred thousand. The floor
a replay reconstructs is above it in 7,478 per hundred thousand — roughly 900x more often.** A
floor above the settled high hard-zeros buckets the day actually reached.

Pre-fix is a clean measurement of `wu_max_since_7am_c` alone, because `station_max_since_7am_c`
does not exist before the July schema.

## The hour profile confirms the mechanism, and finds a second one

`raw floor > settled high`, by local hour:

| | 00 | 01 | 02 | **03** | 04 | 05 | 06 | 07 | 08 | 09 | **10** | **11** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pre | 27.3 | 32.7 | 42.7 | **50.4** | 49.0 | 44.6 | 46.2 | 29.7 | 12.8 | 5.3 | **0.0** | **0.0** |
| post | 11.5 | 15.8 | 20.2 | **36.2** | 37.0 | 35.3 | 31.8 | 12.8 | 4.7 | 3.8 | **0.5** | **0.4** |

| | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pre | 0.8 | 4.6 | 7.9 | 13.0 | 18.9 | 22.5 | 25.7 | 26.1 | 25.3 | 24.7 | 26.1 | 25.5 |
| post | 0.4 | 0.6 | 1.9 | 2.7 | 4.0 | 5.8 | 6.5 | 7.7 | 6.5 | 7.1 | 8.1 | 9.7 |

**Two distinct components:**

1. **Pre-dawn stale carryover**, 00:00–07:00, peaking at **50.4% at 03:00** and falling to
   **0.0% by 10:00** — precisely when "since 7am" becomes a genuine same-day window. This is the
   Denver case and it is unambiguous.
2. **An evening plateau**, ~25% pre-fix and ~7% post-fix from 17:00 on, which cannot be carryover.
   That is the raw observation source reporting a higher daily max than the settlement source
   accepts — a **source disagreement**, not a clock defect. It is unexplained and is its own item.

## Joined to the panel's own rows, it is entirely a B problem — C is clean

I joined production's `high_so_far` onto the panel's own 12,289 `snapshot_id`s (all 12,289 matched,
0 unmatched) and compared it to the reconstructible raw column on the same row:

| Stratum | Comparable rows | raw **differs** from served | raw **above** served |
| --- | ---: | ---: | ---: |
| **B** | 3,816 | **3,096 — 81.132%** | **2,416 — 63.312%** |
| **C** | 5,010 | **0 — 0.000%** | **0 — 0.000%** |

**On C, every comparable row agrees exactly.** So for the primary stratum the whole question is
**moot**: whichever column the replay reconstructed from, it got the served floor. C's 5,010
comparable rows carry zero divergence, and C is where the gap `G = 0.021135322`, sections 1c–1g and
all seven spent decisions live.

**The divergence is confined to B**, which is the screening stratum. That is also exactly what the
zero counts already implied — 28 in B against 1 in C — and it is consistent with the era split: B
is June and reads `wu_max_since_7am_c`, C is July and reads `station_max_since_7am_c`, which is the
same source `high_so_far` uses.

(1,353 panel rows have no served floor at all and 2,110 no raw column; both are excluded above
rather than treated as agreement.)

## What this does and does not license saying

**It does not explain the panel's zero rate, and that matters.** If the panel applied this raw
floor uniformly, an excess of ≥2 degrees always zeros the realized band, and pre-fix that is
**12.6%** of snapshots. The panel's observed B rate is **0.604%** — twenty times lower. So either
the panel applies the reconstructed floor on only some rows, or its ~23.5-snapshots-per-market-day
subsample under-weights the pre-dawn hours where the column is stale. **`-09-65a` traced one
instance; uniform use is not established and should not be assumed.**

**`-09-64a`'s null is untouched.** Repaired and control are identical row-for-row, so whatever
floor the replay uses, both surfaces use the same one. This is not a repair defect.

**And a correction to my own correction.** In `SERVED_BAND_FLOOR_DEFECT_2026-08-10.md` I called the
~19–22% figure from `wu_max_since_7am_c` a biased artifact and said not to quote it. That was right
about *serving* — `high_so_far` is the served floor and its true rate is 0.021%. It was wrong to
dismiss the number itself: **that column is what the replay reconstructs from, so ~21.8% is the
error rate of the research surface's floor, not a measurement artifact.** I discarded the answer as
noise because I was asking a different question.

## What must NOT happen next

- **Do not change the floor, the replay, or any scoring code on this document alone.** The size of
  the effect on the gap is not measured. Zeros are the visible tip; a wrong floor shifts mass on
  rows it never zeroes, and the sign of that on the incumbent's Brier is not established.
- **Never weaken the serving floor.** It is the one shipped win (`1.6639 → 1.4980`), and this
  document is evidence it is working: 0.008% post-fix against the raw column's 7.478%.

## Reproduce

`high_so_far` is the served floor (`variant_prediction_runtime.py:369`,
`floor_bucket = round_half_up(high_so_far)`), read from `features_long.csv`. The raw columns are in
`snapshots_long.csv`. Divergence script is in the session scratch.

# Gate 3 retired decision 10 on a row the served floor does not zero

Production host, 2026-08-10. Traced through the production functions themselves, on production's own
recorded band books — not inferred from a report.

> **Read this first.** `-09-63a` fail-closed at Gate 3 and retired decision 10, citing one row:
> denver `2026-06-08`, snapshot `20260608T030552-0400`, realized band `82-83°F`, "incumbent
> probability on winner **`0.0`**".
>
> **Production served `0.5206313021` on that band.** It was the modal band of an eleven-band book
> that sums to exactly `1.0000000000`. The `0.0` belongs to the research replay, which reconstructed
> a floor of `91` from `wu_max_since_7am_c` at 03:05 — a column that before dawn still carries
> yesterday's window. The floor production actually served was `68`, which zeroes nothing.
>
> **The stop still stands** — two other B rows are genuine zeros under the served floor. But the
> reason given for it does not.

## 1. The fatal row, evaluated by the production function

`variant_prediction_runtime.hard_floor_probability` (line 226) zeroes an `eq` band iff
`value_hi < floor_bucket`. Called directly on the real values:

| Floor supplied | `hard_floor_probability('eq', 82, floor, value_hi=83)` | Bands zeroed of 11 |
| --- | --- | ---: |
| Replay's `91` (from `wu_max_since_7am_c`) | **`0.0`** | **8** |
| Served `68` (`round_half_up(high_so_far)`) | **`None`** — no floor applied | **0** |

Denver's served book at that snapshot, from `data/snapshots/.../snapshots_long.csv`:

| Band | Served `model_probability` |
| --- | ---: |
| `75°F or below` | `0.0368731453` |
| `76-77°F` | `0.0433238644` |
| `78-79°F` | `0.1074489401` |
| `80-81°F` | `0.1152281424` |
| **`82-83°F`** ← settled 82 | **`0.5206313021`** |
| `84-85°F` | `0.1737281458` |
| `86-87°F` | `0.0024019418` |
| `88-89°F` | `0.0003094882` |
| `90-91°F` | `0.0000513610` |
| `92-93°F` | `0.0000035881` |
| `94°F or higher` | `0.0000000809` |
| **Sum** | **`1.0000000000`** |

The incumbent was not merely non-zero on the realized winner. **It was right, and confident.**

## 2. Every candidate zero in the panel, under the floor we served

A realized-band zero requires `served_floor_bucket > settlement_high` — necessary, because the floor
can only zero bands lying entirely below it. Across the 10,936 panel snapshots that have a served
floor, exactly **three** rows satisfy it, and all three are confirmed zeros against the real band
geometry:

| Stratum | Market | Date | Snapshot | Local | Served floor | Settled | Realized band | Pre-floor `model_probability` | Material coverage gap |
| --- | --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: |
| **B** | chicago | `2026-06-14` | `20260614T011002-0400` | 01:10 | `70` | `69` | `68-69°F` | `0.0146275224` | **23.190 min** |
| **B** | san-francisco | `2026-06-09` | `20260609T170137-0400` | 17:01 | `68` | `67` | `66-67°F` | `0.0001434313` | **45.699 min** |
| C | seattle | `2026-07-16` | `20260716T030102662487-0400` | 03:01 | `68` | `64` | `64-65°F` | `0.0007190082` | 0.0 min |
| — | denver | `2026-06-08` | `20260608T030552-0400` | 03:05 | `68` | `82` | `82-83°F` | `0.5206313021` | 0.0 min |

The denver row is listed to be explicit that it is **not** a candidate: its served floor sits 14 °F
*below* the settled high.

**Both surviving B rows are over by exactly one degree, and both sit on market-days with a material
coverage gap** — 23.190 and 45.699 minutes. `2026-06-09` is the fleet-wide stall day on which
chicago, atlanta and san-francisco all settled with ~45.7-minute gaps simultaneously. `-09-67a`
established that label coverage does not move the gap *in aggregate*; that is a statement about a
population and it does not exonerate two specific rows.

That was my first reading. **It is not the best one** — §5 traces both rows to their observation
series and finds a mechanism on our side of the boundary.

## 3. Only the hard floor can produce an exact zero — so the third survivor is a fallback row

`apply_band_postprocessing` (line 866) returns the hard floor's `0.0` **before any clipping**
(lines 872–874). Every other path runs through `clip_probability`, and

```
clip_probability(value) = max(1e-6, min(1.0 - 1e-6, float(value)))
```

so it cannot return less than `1e-6`. **An exact `0.0` in a served band book has exactly one
possible origin: the hard floor fired.** This independently explains `-09-64a`'s otherwise curious
observation that the panel contains **zero probabilities in the open interval `(0, 1e-6)`** — that
interval is unreachable by construction.

The deduction is then tight:

1. Exact `0.0` on a realized band ⟺ the hard floor fired on it.
2. The hard floor fires ⟺ `served_floor_bucket > settlement_high` (§2's necessary condition).
3. Exactly **two** B rows in the panel satisfy that.
4. `-09-66a` reports **three** surviving B zeros.

⟹ **The third survivor is a row where no served floor existed and
`rescore_served_floor_09_66a.py` lines 726–730 retained the replay's baseline floor** — a correct
diagnostic choice, but it scores a row against a floor production never applied (§4). On that row
production applied no floor at all and therefore *could not* have served a zero.

> **Under the floor production actually served, B has exactly two realized-band zeros** — chicago
> `2026-06-14` and san-francisco `2026-06-09`, both over by one degree, both on materially gapped
> market-days.

### The raw model does emit exact zeros — and post-processing rescues all of them

`model_probability` in `snapshots_long.csv` is the **raw** model output, before floor, support floor
and late lock-in. (Confirmed: san-francisco's `66-67°F` reads `0.0001434313` where the served floor
`68` zeroes it.) The raw model is far more brittle than the served book:

| Raw-model statistic, panel snapshots | B | C |
| --- | ---: | ---: |
| Snapshots with **any** band at exactly `0.0` | **2,969 / 4,636 = 64.042%** | 2,045 / 7,653 = 26.722% |
| Snapshots where the **realized** band is exactly `0.0` | **146** | 0 |

None of those 146 reaches the served book as a zero: `clip_probability` lifts them to `1e-6`, and
they are disjoint from the two rows where the hard floor fires. Where the day's high is already in
(atlanta `2026-06-12` from 16:08, floor `91`, realized band `90-91°F`), `late_lockin_target` returns
`1.0` and blends the probability *upward*.

**This is direct evidence that the post-processing layer is doing real work** — consistent with the
serving floor being the campaign's one shipped win, and a caution against treating raw model output
as if it were what we serve.

## 4. `high_so_far` was absent fleet-wide for four days

**1,353 of the panel's 12,289 snapshots (11.01%) have no served floor at all** — B 751, C 602. Every
one is `high_so_far` empty in production's `features_long.csv`; none is a join failure. Fill rate by
date, five markets:

| Date | denver | chicago | toronto | nyc | miami |
| --- | ---: | ---: | ---: | ---: | ---: |
| `2026-06-26` | 186/186 | 137/137 | 146/147 | 157/157 | 178/178 |
| `2026-06-27` | 27/121 | 32/112 | 38/112 | 38/107 | 39/107 |
| **`2026-06-28`** | **0/122** | **0/128** | **0/142** | **0/133** | **0/132** |
| **`2026-06-29`** | **0/95** | **0/88** | **0/78** | **0/79** | **0/79** |
| **`2026-06-30`** | **0/168** | **0/161** | **0/171** | **0/159** | **0/160** |
| **`2026-07-01`** | **0/165** | **0/163** | **0/176** | **0/163** | **0/164** |
| `2026-07-02` | 45/150 | 41/153 | 38/156 | 38/156 | 38/156 |
| `2026-07-03` | 137/138 | 140/140 | 141/141 | 127/128 | 129/129 |

Identical shape across every market: a systemic fleet-wide failure, not a station fault. **Closed** —
healthy from `2026-07-03` through today.

`round_half_up(None)` returns `None`, so on those days `floor_bucket` was `None` and
`hard_floor_probability` returned early: **the serving floor was not applied at all.** `late_lockin_target`
is `None`-guarded the same way (line 265), and `support_bucket` defaults to `floor_bucket` when no
`observed_support_bucket` is recorded (line 371). The serving floor is the campaign's one shipped win
— it moved the served ratio 1.6639 → 1.4980 — and it was absent fleet-wide for four full days.

The outage straddles the regime boundary: B ends `2026-06-30`, C begins `2026-07-01`. Both strata
have an edge inside it.

## 5. `high_so_far` is not a running maximum — and that is what blocks Gate 3

Both surviving B rows were traced to their observation series, and neither is a label problem.

| | chicago `2026-06-14` | san-francisco `2026-06-09` |
| --- | --- | --- |
| Blocking snapshot | 01:10 | 17:01 |
| `high_so_far` / `current_temp` there | `70.0` / `70.0` | `68.0` / `68.0` |
| Next snapshot | 01:18 → `68.0` / `68.0` | 17:11 → `67.0` / `67.0` |
| Day's settled high | `69.0` | `67.0` |
| Coverage | `peak_heating_window:17m; settlement_window:23m` | `settlement_window:46m; settlement_window:16m` |

**In both, `high_so_far` went up and then came back down.** Measured across the whole panel:

| | B | C |
| --- | ---: | ---: |
| Snapshots scanned | 28,376 | 49,033 |
| `high_so_far` **below** `current_temp` | **0** | **0** |
| `high_so_far` **below the running max of `current_temp` already seen that day** | **5,283 = 18.62%** | **14,995 = 30.58%** |
| Market-days with ≥1 decrease in `high_so_far` | **125 / 204 = 61.3%** | **292 / 320 = 91.2%** |
| Total decreases | 906 | 1,284 |

Largest single decreases: denver `2026-06-26` `89.0 → 70.0` in ten minutes; seattle `2026-07-30`
`75.0 → 60.1`; toronto `2026-06-15` `24.0 → 13.0`.

`feature_store.py:1232` computes `high_so_far = max(temps_before)` over observations at or before the
cutoff, and `variant_prediction_runtime.py:369` rounds it straight into the serving floor. A maximum
cannot decrease, yet this one does, on the majority of market-days.

### The mechanisms, traced through `replay_inputs.jsonl`

Both blocking rows were traced to their captured source payloads. **They are not the same defect.**

**san-francisco `2026-06-09` — the upstream series is mutable.** Three consecutive snapshots, all
carrying the same 18 `wu_history` rows, the same `max_times` `['11:56','12:56']` and the same
`latest.datetime` of `12:56`:

| Snapshot (ET) | last five row temps | `max(rows)` | `wu_history.max_c` | `wu_current.max_since_7am_c` | `high_so_far` |
| --- | --- | ---: | ---: | ---: | ---: |
| 16:51 | `66, 66, 67, 67, `**`68`** | 68.0 | **67.0** | 68.0 | 68.0 |
| 17:01 | `66, 66, 67, 67, `**`68`** | 68.0 | **67.0** | 68.0 | **68.0** ← blocks |
| 17:11 | `66, 66, 67, 67, `**`67`** | 67.0 | **67.0** | 67.0 | 67.0 |

**Weather Underground restated an already-published observation, 68 → 67**, without changing the row
count or the timestamp. And **`wu_history.max_c` said `67.0` in all three** — including while the
rows still contained a 68. The vendor's own summary field was right, the row was the transient, and
settlement agreed at 67.

**chicago `2026-06-14` — no history at all, so the floor fell back to the instantaneous reading.**

| Snapshot (ET) | `wu_history` | `wu_current.temp_c` | `wu_current.max_since_7am_c` | `high_so_far` |
| --- | --- | ---: | ---: | ---: |
| 01:10 | **`rows=0`, `max_c=None`** | 70.0 | 83.0 | **70.0** ← blocks |
| 01:18 | **`rows=0`, `max_c=None`** | 68.0 | 83.0 | 68.0 |

With no history rows, `high_so_far` tracked `current_temp` — **not a maximum of anything** — and the
70 was a transient. Note `max_since_7am_c = 83.0` is chicago's **previous day's settled high**
(`2026-06-13` settled `83.0`): the pre-dawn carryover, correctly *not* used for the served floor,
with the fallback landing on the instantaneous reading instead.

> **What is established:** two distinct mechanisms — a mutable upstream series, and an empty-history
> fallback to the current reading. **What was not, when this was written:** how the 18.62% / 30.58%
> divides between them, or whether other mechanisms exist. I traced two rows; I did not measure a
> population. **`-09-70a` and `-09-71a` have since measured it — see §5a.**

### 5a. The population, censused — and the one upstream cause (`-09-70a`, `-09-71a`)

`-09-70a` censused **all 2,190** decrease events into a mechanism set whose precedence was **frozen
in the seed** before the run; `-09-71a` added the signed direction the first census omitted. Both
artifacts were reproduced byte-for-byte on production, and `-09-71a` reconciles cell-for-cell with
`-09-70a`.

| Mechanism | B (906) | C (1,284) |
| --- | ---: | ---: |
| `M5_cutoff_change` | **658 = 72.63%** | 2 |
| `M2_empty_history` | 144 | **1,278 = 99.53%** |
| `M3_rows_dropped` | 78 | 0 |
| `M6_unexplained` | **20 = 2.21%** | 4 |
| `M4_source_switch` / `M1_restatement` | 4 / 2 | 0 / 0 |

**C behaves as this document assumed:** 99.53% empty-history fallback, 81.70% of it pre-dawn — the
chicago mechanism above and nothing else of size. **B does not.** 40.62% of B's decreases land in
the peak-heating or settlement window — the model's main decision path, not a pre-dawn corner.

**`cutoff_hour` is not the capture hour.** The producer that wrote the captured `features_long.csv`
is `815d7594:src/model_distribution.py:1010-1023` `effective_intraday_cutoff_hour()` — identified
through the SHA-256 model identity recorded in the replay records themselves, not inferred from
today's tree. It caps the wall clock by the **latest retained WU observation minute**:

```python
eligible = [c for c in INTRADAY_CUTOFF_HOURS if c <= wall_cutoff and c * 60 <= latest_minute]
```

So when the vendor drops its newest rows, the model's own input window slides **backward**. All
**658 / 658** B `M5` events narrowed — 655 by one hour, 2 by two, 1 by four. **None widened.**

> atlanta `2026-06-13`: capture advanced `11:21 → 11:32` while the latest WU row regressed
> `10:52 → 09:52`. Cutoff `10 → 9`, served high `84 → 81`. The capture clock never went backward;
> the observation series did.

**`M5`, `M3` and `M1` are one defect, not three.** Holding each payload fixed, raw-series loss alone
lowers the maximum in **610 / 658**, narrowing alone in 22, both in 26. The upstream property is
that **the captured WU observation series is not append-only**: rows are removed and values restated
after publication. Removal severe enough to drag the derived cutoff backward is `M5`; removal that
leaves it alone is `M3`; restatement in place is `M1`. `M5` is directionally correct but is usually
a *symptom*, not the root.

**This is a model-input finding, and nothing more.** It is not evidence that changing the producer
improves Brier, and it does not license a serving change — `-09-44a` was a precise null on exactly
that move. The 20 B residuals are not scatter either: 19 share a first-history-print signature and
**one** is genuinely unnamed.

Canon: `docs/roadmap/agent-report-2026-08-25-workstation-high-so-far-population.md`,
`docs/roadmap/agent-report-2026-08-26-workstation-cutoff-direction.md`.

What *is* established is the consequence. The floor commits to an exact `0.0` — an irreversible
statement that the day cannot end in that band — from a quantity that is not monotone. Usually this
is harmless, because the transient does not exceed the day's eventual high: fleet-wide the served
floor exceeds the settled high in only **0.008%** of post-fix snapshots, and in **2 of 10,936**
panel rows. **Those two rows are the entire remaining basis of the Gate 3 stop.**

This is not an argument for weakening the floor. The floor is the one shipped win, and
`-09-63a` was right to refuse epsilon mass.

## 6. What this licenses, and what it does not

**It licenses:**

- Retiring the claim that `-09-63a`'s cited row shows the incumbent assigning zero to a realized
  winner. It does not.
- Recording that the panel's floor is wrong in 81.132% of B rows and that Gate 3 — unlike every
  Brier statistic — is sensitive to that in the worst case rather than on average.

**It does not license:**

- **Un-retiring decision 10.** The ledger forbids reassignment, and the stop still fires on two
  genuine rows. Re-registration would need a new slot, and that is an operator call.
- **Amending the frozen protocol.** Changing a pre-registered rule after seeing which row failed it
  is precisely the fishing the pre-registration exists to prevent.
- **Weakening the serving floor**, or adding epsilon mass. `-09-63a` was right to refuse.
- Any claim that the two surviving labels are wrong. Both rows are better explained by §5 — a
  `high_so_far` that rose and fell back — than by a mis-settled outcome, and `-09-67a` found label
  coverage flat in aggregate. **The remaining defect is on our side, not the venue's.**
- Any change to `high_so_far`, the floor, or collection **on the strength of this document alone**.
  §5 measures a phenomenon and explicitly does not establish its cause.

## 7. The general lesson

`-09-66a` measured the wrong floor's effect on B's Brier and found it **cosmetic — 0.5654% of B's
gap**. That conclusion is correct and stands. But Gate 3 is not an average; it is a **minimum**, and
it fail-closes on the existence of a single row.

> **A defect that is cosmetic in the mean can be decisive in the extreme. The statistic you
> validated is not always the statistic you gated on.**

Four missions cleared the instrument by measuring averages, and that clearance is real. It never
covered the one place where a single row could stop the campaign — and that is exactly where the
wrong floor did its damage.

## 8. `-09-68a`: Gate 3 is a size limit, not a quality bar

Verified on production 2026-08-10, branch `dbd0ebd1`, ROLL-FREE.

**The prediction in §3 was correct.** The third survivor is **nyc `2026-06-22`
`20260622T000103-0400`** — 00:01, one minute past midnight — and its `served_floor_bucket` is
**blank**. Production applied no floor there. Denver's realized band reproduces at
`0.5206313021403224`.

That leaves **two** genuine B zeros, and it makes the timing pattern hard to miss: of the five
zero-carrying rows found anywhere in this investigation, **four fall between 00:01 and 03:05.**

| Row | Local time | Status |
| --- | --- | --- |
| nyc `2026-06-22` | 00:01 | no floor served |
| chicago `2026-06-14` | 01:10 | **genuine** |
| seattle `2026-07-16` (C) | 03:01 | genuine, C |
| denver `2026-06-08` | 03:05 | **invalid — served `0.5206`** |
| san-francisco `2026-06-09` | 17:01 | **genuine** |

### The satisfiability result

B floor crossings: **2 / 204 market-days**, crossed 95% `[0%, 4.035874%]`. Under that rate:

| B market-days | P(Gate 3 fires) |
| ---: | ---: |
| 71 | **50.317282%** (70 → 49.825374%) |
| **204 — this panel's own size** | **86.5994%** |
| 305 | **95.045879%** (304 → 94.996828%) |
| 500 | **99.274561%** |

**Gate 3 was ~87% likely to fire on this panel before anyone looked at a candidate.** Whatever it
measured, it was not the candidate.

> **The structural point needs no rate estimate at all.** A fail-closed *"any row"* gate has
> `P(fire) = 1 − (1 − q)^n → 1` for **every** `q > 0`. The measured rate only sets the scale.
> **Only `q = 0` exactly escapes** — and `q` is the serving floor's error rate, which §5 shows is
> not zero and is not even monotone.

**Honest caveat on the rate.** The interval's lower bound is `0%` because the estimate rests on two
events across 23 date × 12 market clusters — many crossed resamples contain neither. Do not quote
`0.980392%` as if it were well determined. **The conclusion does not depend on it:** the structural
argument above holds for any non-zero rate, and two crossings were observed.

Sensitivity only, licensing no exclusion rule: dropping the two genuine rows moves B's incumbent
Brier `0.053290041 → 0.053247700`, a change of `-0.000042341`.

## 9. Reproduction

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
.\venv\Scripts\python.exe -c @"
import sys; sys.path.insert(0,'src')
from weather.model.variant_prediction_runtime import round_half_up, hard_floor_probability
print(round_half_up(None))                                    # None
print(hard_floor_probability('eq', 82, 91, value_hi=83))      # 0.0   replay floor
print(hard_floor_probability('eq', 82, 68, value_hi=83))      # None  served floor
print(hard_floor_probability('eq', 69, 70, value_hi=69))      # 0.0   chicago
"@
```

Band books: `data/snapshots/highest-temperature-in-<market>-on-<month>-<day>-2026/snapshots_long.csv`.
Served floors: `docs/roadmap/served-floor-for-panel-2026-09-66a.csv`.
Label provenance: `docs/roadmap/settlement-provenance-for-panel-2026-09-67a.csv`.

Related: `REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md`, `SERVED_BAND_FLOOR_DEFECT_2026-08-10.md`.

# We serve probability 0.0 on the band that settles, 1.02% of the time

**Found 2026-08-10 by the production agent, tracing `-09-63a`'s Gate 3 stop. Live serving defect.**
Filed separately from `ESTABLISHED_FINDINGS.md` only because the `-09-63a` branch edits that file
and had not merged yet; fold this in as a numbered section once it lands.

## How it surfaced

`-09-63a` refused to fit decision 10's candidate because the **repaired** surface gave probability
`0.0` to Denver `2026-06-08`'s realized band. That was the right call. **But the interesting
question was whether the same thing happens in what we actually serve — and it does, far more
often, and for a different reason than anyone would guess.**

Denver `2026-06-08` itself is *not* an example: settled `82.0°F`, band 4 is `82-83°F`, and we
served it **`0.5206`**. Production was fine there; only the research surface was not.

## The measurement

Sealed window `2026-06-03 → 2026-07-30`, every served snapshot, scored against the settled high:

| | |
| --- | ---: |
| Snapshots scored | **100,040** |
| **Served probability EXACTLY `0.0` on the band that settled** | **1,017 — 1.017%** |
| Distinct market-days affected | **20 of 663** |
| Distinct markets affected | **11 of 12** |
| Between `1e-12` and `1e-6` | **0** |
| Between `1e-6` and `1e-3` | 363 |
| Events with no band covering the settled high | **0** |

**The gap between "exactly zero" and "≥1e-3" is empty.** That is the signature of a hard rule, not
a model tail.

## The mechanism, traced end to end

Atlanta `2026-06-12`, settled **`91.0°F`** → band 4 = `90-91°F`. At snapshot `20260612T152750-0400`:

| | |
| --- | ---: |
| `observed_floor_bucket` | `91` |
| Served mass on bucket `90` | `0.0` |
| Served mass on bucket **`91`** | **`0.4622701`** |
| **Served probability for band 4 (`90-91°F`)** | **`0.0`** |
| Sum of all 11 served band probabilities | **`0.5377`** |
| Market on band 4 at 18:02 | **`0.85`** — and the market was right |

**The per-bucket distribution is correct.** The floor zeroed bucket 90 (the observed max is already
above it — right) and left `0.462` on bucket 91. **The band-level number then throws that mass
away.** Band 5 (`92-93°F`) reproduces exactly as `p(92)+p(93)`, so the summation itself works. Only
the band straddling the floor collapses, and **46% of the distribution is silently discarded** —
the served band vector does not sum to 1.

### The guard is correct. Its input is missing.

`probability_calibration.hard_bin_probability` (`src/weather/calibration/probability_calibration.py:107`)
already documents the exact case:

> *"Exact/range bins containing the floor are not hard: the final high can still rise later, and a
> range like 92-93F is still live when the printed floor is 93F."*

Executed against the real values:

```
hard_bin_probability('eq', 90, 91, bin_value_hi=91)  -> None   # correct: band stays live
hard_bin_probability('eq', 90, 91, bin_value_hi=None) -> 0.0   # what we served
```

`upper = int(bin_value_hi) if bin_value_hi is not None else bin_value`, then `if upper < floor_bucket:
return 0.0`. **With the upper edge present the band survives; without it, `90 < 91` and the whole
band is hard-zeroed.**

Nothing else can produce an exact `0.0`. The live artifact has
`preserve_distribution_coherence = True` — so a non-hard band returns its raw summed probability
untouched — and `min_probability = 1e-06`, so the calibration path **cannot** return exactly zero.
**The `hard` branch is the only route to `0.0`, and it only fires here when `bin_value_hi` is
absent.**

`model_presentation.market_bins` *does* set `value_hi` (`:171`, `digits[-1]`). The serialized band
records carry `bin_kind`, `bin_value_c` and `range_label` but **no `bin_value_hi`**, so any consumer
reconstructing `bin_data` from a stored band loses the upper edge. **The exact loss point is not yet
identified and must be traced before anything is changed.**

### The natural control confirms it

**Toronto is the only Celsius market and it uses single-degree bands** (`16 C`, `17 C`), where
`value_hi == value` and dropping it is harmless. Every Fahrenheit market uses two-degree bands
(`78-79°F`).

| | Occurrences |
| --- | ---: |
| Toronto (1°C bands) | **1** |
| 11 Fahrenheit markets (2°F bands) | **1,016** |

That is exactly what the mechanism predicts, and it is not a pattern anyone chose. Toronto's single
case is a different and rarer thing — a genuine below-floor band that still settled, i.e. the floor
input disagreeing with the settlement source — and is worth its own trace.

## Why it matters, stated without inflation

- **A zero on a realized outcome is the worst possible Brier contribution** and is unbounded under
  log loss. It is also a **trading** hazard: at 18:02 we published `0.0` where the market published
  `0.85`, on the outcome that occurred.
- **Timing works against us.** Occurrences by hour rise through the afternoon and peak at 20:00–21:00
  (115, 114) as the floor climbs. **The `09:00–14:00` primary window carries only ~59 of the 1,017**,
  so this is *not* a large share of the primary objective slice — do not oversell it there.
- **It is a bug fix, not a candidate.** It does not need to clear the ~3.2% campaign floor and it
  spends no ledger decision. Restoring discarded mass is a correctness repair.

## What must NOT happen next

- **Do not "fix" it by weakening the floor.** The floor is the one shipped win (`1.6639 → 1.4980`).
  The floor is not wrong here; the upper edge is missing.
- **Do not patch it during the graded window, and do not patch it without a replay measurement.**
  Adoption of a serving change is measured first (§1e). `model_features.py:1775` feeds served
  outputs into the analog path.
- **Do not assume the research surface has the same defect.** Denver `2026-06-08` proves the two
  surfaces disagree: served `0.5206`, repaired `0.0`. **The repaired surface may be worse.** Every
  campaign conclusion — §1c, §1d, §1f, §1g — was computed on the repaired surface, so **how often
  the repair zeroes a realized band is an open and important question.**

## Reproduce

`scripts` for the census and the trace are in the session scratch; the census streams
`snapshots_long.csv` per event so peak memory stays flat on the 16 GB host. The decisive one-liner:

```powershell
.\venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); from weather.calibration.probability_calibration import hard_bin_probability as h; print(h('eq',90,91,bin_value_hi=91), h('eq',90,91,bin_value_hi=None))"
# -> None 0.0
```

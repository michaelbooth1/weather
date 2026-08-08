# Workstation handoff 2026-09-42a — exclude two Denver station-days, then fit the candidate

Written 2026-08-07 by the production agent. Read on `origin/master` and execute.
**`-09-41a` did everything right and stopped 14 cells short. This clears those 14 cells and then
runs the fit it could not reach. The diagnosis below is already done — do not redo it.**

## 1. What `-09-41a` established (accept these)

P0, P1, P2 all **PASS**. The PIT surface is real and narrow: of **441** cells (21 fields × 7 leads
× 3 markets) only **21** are complete — `temperature_2m`, all 7 leads, all 3 markets. **12,180 /
12,180** PIT rows collected. The trainer now selects honest / rich / hybrid inputs.

P3 stopped at the code-owned gate with **12,586 / 12,600** cells, because Denver **2025-07-28** has
17 WU hourly rows against a floor of 18. **That stop was correct** — fitting on 12,586 would have
let the candidate size its own population, which is the self-sizing defect.

## 2. What production established since (accept these too — measured, not argued)

**The gap is unfillable. Do not try to re-fetch it.** WU, METAR **and** NOAA GHCN-hourly each
return the *identical* 17 timestamps for Denver 2025-07-28, with identical holes:

```
00:58 -> 14:58 hourly, then 18:58, then 23:58   (missing 15:58,16:58,17:58 and 19:58-22:58)
```

Three independent archives agreeing exactly means KBKF (Buckley SFB, a military field) did not
report those hours. `backfill_errors.jsonl` has no entry — the fetch succeeded.

**The whole window has only TWO such market-days, both Denver.** Across all 1,740 market-days in
July 17 – Aug 14, 2021–2025 × 12 markets:

| market | date | WU rows |
| --- | --- | ---: |
| `kbkf` | 2022-07-20 | **1** |
| `kbkf` | 2025-07-28 | **17** |

**`-09-41a` only reported the second. Establish whether `kbkf 2022-07-20` is also inside the
900-market-day retrain population; if it is, it must be handled by the same mechanism.**

**Excluding it is CORRECT, not a workaround.** 2025-07-28's recorded max is **37.2 °C at 14:00 —
the hottest value in Denver's month** — during a spell where 07-26 and 07-27 both peaked at 15:00,
and **9 of 31 Denver July days peak in the 15:00–17:00 window that this day is missing.** The label
is very likely biased low. This is the day you least want in a training set.

## 3. The floor of 18 is NOT a knob — verified on production

`COMPLETE_DAY_MIN_ROWS = 18` (`backtesting/settlement_io.py:32`, `settlement_ledger.py:34`) is not
a retrain threshold that happens to be reused. It is:

- `settlement_ledger.py:489` — the test for whether the **WU daily summary is trusted as the label
  source at all**; below it, settlement falls back to `snapshot wu_history_high`.
- `settled_day_freshness.py:217` — day completeness, which feeds **the streak**.

**Lowering it to 17 would change how days settle fleet-wide and what counts as a complete day for
objective #1.** Do not touch it, and do not touch `MIN_HOURLY_OBS` in `data_auditor.py:26` either.

## 4. P0 — the fix: a code-owned exclusion, not a resize

Add an **explicit, named, version-controlled exclusion list** of station-days that fail the
observation floor, containing exactly the market-days in §2 that fall inside the population, with
the reason recorded. Then declare the expected cell count to match.

**Why this is not the self-sizing defect:** self-sizing is *the candidate's manifest choosing its
own population*. This is *the code naming two specific station-days, once, on evidence, before any
candidate exists*. The distinguishing test, and it is binding:

> **The expected cell count must be derivable from the exclusion list and the window ALONE, with no
> candidate loaded.** If you cannot compute it without a candidate, you have rebuilt the defect.

Make the gate **fail loudly if a market-day fails the floor and is not on the list.** A silent drop
is the defect wearing a different hat.

## 5. P1–P2 — then do what `-09-41a` could not

Everything from `-09-41a` §7–§8 stands, unchanged:

- **Declare the acceptance bar BEFORE fitting**, in the report.
- Fit **A** (thin honest), **B** (rich contaminated), **C** (hybrid: PIT `forecast_high` + settled
  for the rest). **C is the realistic production answer** — do not skip it.
- Evaluate all three **identically**, walk-forward on captured inputs. Nothing in the evaluation
  may come from the settled archive for any candidate.
- Report centre, width, Brier, market gap, **crossed date × market clustering and power**, plus
  **B − A** and **B − C** as the measured price of contamination.
- If a candidate qualifies: **parity must stay at 0 unexpected**, and **candidate-bound replay is
  mandatory** if it selects `wind_gust_kmh` or `wind_shift_3h_degrees` — `-09-39a`'s zero served
  delta does not cover those.
- `-09-41a`'s honest/rich/hybrid selector is on its branch; **reuse it, do not rebuild it.**

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full, plus the `-09-41a` exception: free Open-Meteo on **both
hosts** is permitted. **No paid API, ever.**

- **Never weaken or bypass the serving floor**, and per §3 never the 18-row floor either.
- Do not write production `data/`. Produce a candidate; **promote nothing**. Release #1 stays
  DEFERRED.
- **Do not declare the confirmation window** — it arms at candidate freeze and the declaration is
  the operator's. Check `reserved-confirmation-window.md` at run time.
- Do not run the chain, settle a date, or restart anything.
- Never pool across `2026-07-31` (anchor `b77cfbed`). Ledger rows are not market-days.
- `pytest -q` is red on master — 4 unowned failures in `STATE_OF_PLAY.md`. Diff against those.

## 7. What would falsify this mission

- **`kbkf 2022-07-20` turns out to be inside the population and the exclusion changes the panel
  materially.** Report the balance cost before fitting.
- **Excluding the two days still does not clear the gate** — then the gate is counting something
  other than what §2 measured, and that discrepancy is the finding.
- **No candidate beats the incumbent, or the comparison is not powered.** Say so. Do not ship a
  candidate to have shipped one.
- **B beats A and C.** Legitimate — report it plainly.

## 8. Branch and report

- Branch: `codex/workstation-exclude-denver-station-days-and-fit-2026-09-42a`
- Report: `docs/roadmap/agent-report-2026-08-08-workstation-exclude-denver-station-days-and-fit.md`

Base on **`origin/codex/workstation-honest-corpus-versus-rich-corpus-2026-09-41a`** (head
`50d0a3e9`) — it carries the PIT corpus, the honest/rich/hybrid selector, the parity repair and the
retrain lane. State your base commit explicitly.

Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and a per-file roll verdict
from **`scripts\ops\roll_verdict.ps1 -Branch <branch>`** — do not derive it by hand.
**Commit and push whenever you finish, at whatever hour.**

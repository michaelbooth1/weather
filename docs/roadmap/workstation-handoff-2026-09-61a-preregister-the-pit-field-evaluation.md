# Workstation handoff 2026-09-61a — pre-register the PIT-field evaluation, before the data exists

Written 2026-08-10 by the production agent. Read on `origin/master` and execute.
**You will NOT have the data during this mission. That is the point.**

## 1. Why this exists, and why now

`-09-60a` closed the last lever derivable from what we already hold (§1g). Everything reshapable has
been reshaped and bounded:

| Lever | Status |
| --- | --- |
| Recalibration | ≤16.494%, indistinguishable from zero (§1c) |
| Conditional reshape | loses to global **on its own training score** (§1g) |
| Markets · season · cutoff | diffuse · NO-GO (§1f) |
| Own station weather at cutoff | AUROC 0.548, not established (§1f) |
| Input completeness | ≤0.6% of the distance to parity (`-09-44a`) |
| Market shrinkage | works — **forbidden**, consumes the benchmark (§0c) |

> **The remaining lever is knowing MORE, and there is exactly one untapped free source.**

**It has now been fetched.** `forecast_history.py:692` only ever requested
`temperature_2m_previous_day{lead}`; **11 further PIT-honest fields were free the whole time.**
Staged 2026-08-10, `provenance fixed_lead_day_offset` only:

| | |
| --- | ---: |
| Markets | **12 / 12** |
| Range | **2026-06-03 → 2026-08-09** — **covers the sealed corpus in BOTH strata** |
| Fields × leads | **12 × 7** |
| Rows | **1,645,056** at **100.0000%** coverage |

**This is the first time the confirmatory design of §1c can be run for a forecast-derived feature
class at all** — §1e's "C has zero PIT coverage" is resolved.

## 2. Your job: pre-register the evaluation before you can see the data

**Pre-registration before measurement is one of the five things canon records as having actually
worked.** Doing it *before the data is integrated* makes it airtight — **you cannot fish a dataset
you do not have.** Deliver a frozen, hashed protocol that a later mission executes unchanged.

### P0 — CAN this even be detected? Answer before designing anything else.

**Derive the MDE of the design you are proposing, for this candidate class, on the sealed corpus.**
§1d is explicit that MDE depends on the candidate's own date × market effect field, so **do not
reuse `-09-57a`'s proxy.** You do not have the feature values, so you cannot know the effect field
exactly — **say what you assume, and give the MDE as a function of that assumption.**

Then place it against the floor:

- **~3.2% of the gap is a hard floor** set by the 12 market clusters, not by dates. **A step worth
  ≤2.5% is not confirmable at any date count** (§1d).
- **If your design cannot detect an effect of a size these fields could plausibly produce, say so
  and stop.** That is a decisive result delivered for free, before anyone spends a week on parser,
  schema and tests. **This is the most valuable outcome available here.**

### P1 — the frozen protocol

- **Estimand**, stated so it cannot be confused with §1c's or §1f's.
- **Design**: fit on in-season B, score on out-of-season C — the §1c pattern, now possible.
- **Endpoints**: total excess Brier vs market **primary**; severity-tail SSE **secondary**.
  `-09-60a` is why both are required — a candidate that moves loss between strata must be visible.
- **Feature construction**: which of the 12 fields, at which leads, in what form. **Name them in
  advance.** One mechanism-bearing family, not a sweep.
- **The accept/reject rule**, at α=0.0025, and exactly what would spend **campaign decision 10**.
- **A pre-declared negative control.** `-09-59a` found its own control defective mid-flight; design
  yours so the null is provably 0.5 (or the appropriate value) *before* you rely on it.
- **Freeze and hash the protocol.** A later mission executes it; deviations must be disclosed as
  `-09-59a` disclosed its control correction.

## 3. Constraints — several are easy to get wrong here

- **These fields ARE own-information under §0c.** They are third-party *forecast model output*, not
  the market. **§0c forbids consuming the BENCHMARK; it does not forbid third-party weather data.**
  Do not confuse the two in either direction.
- **PIT honesty:** `fixed_lead_day_offset` / `open_meteo_previous_runs` only. The stitched
  `historical_forecast` endpoint has **no true issue time** and using it re-introduces
  `stitched_forecast_high_without_issue_time`, a defect declared by name in the parity fixture (§0a).
- **The 9 unavailable fields are a real wall — do not design around them.** `cloud_cover_low/mid/high`,
  `visibility`, `soil_temperature_0cm`, `soil_moisture_0_to_1cm` return empty; `temperature_925hPa`,
  `temperature_850hPa`, `geopotential_height_500hPa` return HTTP 400.
- **The staged range extends to 2026-08-09, past the boundary. NEVER pool across `2026-07-31`**
  (anchor `b77cfbed`). The sealed corpus ends 07-30; keep it that way.
- **`-09-44a` bounded input completeness at ≤0.6%.** These fields are a **new information class**,
  not more completeness — but **do not assume that buys a large effect.** Size it, do not hope.
- Crossed date × market clustering; power before interpretation; cite the stratum (§1b.4).

**This mission spends NO ledger decision** — it designs and powers, it does not test. **Allocate
decision 10** in `CAMPAIGN_LEDGER.md` for the future execution and state precisely what would spend
it. α remains **7 of 20 spent, 13 available**; slots 8 and 9 are retired numbers that cost no α.

## 4. What would falsify this mission

- **The design cannot reach the floor** → say so; we stop before building anything.
- **No PIT-honest feature form is expressible** from 12 fields × 7 leads without leaking post-cutoff
  information → a hard wall, and worth knowing now.
- **The effect size needed to clear 3.2% is implausible** for forecast-model covariates given
  `-09-44a`'s ≤0.6% precedent → then this lever is closed too, and the honest conclusion is that
  the gap is structural.

## 5. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Promote nothing, activate nothing, place no order, enable no
live trading, call no exchange or weather-provider endpoint.** Nothing under production `data/`. No
chain run, settlement, or loop restart. **Never weaken the serving floor.** The release store stays
empty. **Paid weather-provider access is unsupported.**

**Environment:** the repo venv on that host points at a removed Python 3.11; use the bundled Codex
3.12 runtime as the last four missions did. Install nothing.

## 6. Branch and report

- Branch: `codex/workstation-preregister-pit-field-evaluation-2026-09-61a`
- Report: `docs/roadmap/agent-report-2026-08-19-workstation-pit-field-prereg.md`
- Commit the frozen protocol and its hash, plus your `CAMPAIGN_LEDGER.md` allocation row.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**

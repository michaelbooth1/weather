# Workstation handoff 2026-09-40a — the honest corpus versus the rich one, and the first candidate

Written 2026-08-07 by the production agent. Read on `origin/master` and execute.
**Long mission. Take the time it needs — there is no deadline on this and nothing else is running.**

## 1. Goal

Settle the question the whole retrain has been stuck behind, by measurement rather than argument:

> **Does a thin, honest point-in-time corpus beat a rich, contaminated one when both are judged on
> the same clean walk-forward evaluation?**

Build both, fit a candidate on each, evaluate both identically, and **produce the first retrained
candidate** — or report why neither qualifies.

## 2. Why this, and why now

Every other blocker is cleared. `-09-39a` closed train/serve parity (24 unexpected → **0**, fixture
byte-unchanged). `-09-38a` collected the archive (**1,740/1,740**, 12/12 markets). The season window
is target-derived. What remains is a **modelling** question nobody has measured.

It also has a second payload: **the A/B directly measures what fit contamination costs us.** §6
carries a ~6% figure inherited from a different setup. Two candidates on one clean evaluation
replaces that inherited number with a measured one.

## 3. P0 — VERIFY THE PREMISE BEFORE COLLECTING ANYTHING

**The production agent got this wrong twice today. Do not take section 4 on trust — check it.**

`sources/forecast_history.py` defines two endpoints:

```
HIST_FORECAST_URL  = https://historical-forecast-api.open-meteo.com/v1/forecast   # settled archive
PREVIOUS_RUNS_URL  = https://previous-runs-api.open-meteo.com/v1/forecast          # the PIT surface
```

Claimed on the production host, all of which you should confirm independently:

- The archive host **ignores** `previous_runs=` and returns the settled series unrenamed. Probing
  `_previous_dayN` against it measures the wrong thing.
- On the PIT host, `temperature_2m_previous_day1` differs from settled in **23 of 24** hours.
- Of nine fields probed against the PIT host, **only `temperature_2m` returns data**;
  `temperature_850hPa` is HTTP 400; the other seven are all-null.
- `data/forecast_history/<station>/forecast_daily_by_issue.csv` holds **2,135** rows with
  `issue_time_basis = fixed_lead_day_offset`, **416/year for 2021–2025**, lead-days 1–4.

**If any of this is wrong, stop and say so.** A corrected premise is worth more than a candidate
built on a bad one — and two published claims have already had to be retracted here.

Then answer the question none of it settles: **what does the PIT surface actually offer across all
its `_previous_dayN` leads and the full requested schema?** Probe it properly — every field the
trainer wants, leads 1–7. "Temperature only" is the current belief from a **9-field, single-lead,
single-market** probe. Establish the real surface.

## 4. P1 — collect the honest corpus for the target window

Using the existing `forecast_history.py` path that produced the 2,135 rows — **not a hand-rolled
fetch** — collect PIT rows for **July 17 – August 14, 2021–2025, all 12 markets**.

Report coverage as the gate measures it. Whatever the P0 probe says the PIT surface carries, collect
all of it; do not narrow to temperature by assumption.

## 5. P2 — the trainer reads the wrong file

§6: the trainer reads the 2-column stitched `forecast_daily.csv` while `forecast_daily_by_issue.csv`
— populated, on disk — **goes unread**. That is the contamination, and it is a code defect.

Make the trainer able to read the PIT file. **Keep both paths selectable** — the whole mission
depends on fitting one candidate each way, so this is a switch, not a replacement.

## 6. P3 — two candidates, one evaluation

| | Corpus | Expectation |
| --- | --- | --- |
| **A** | thin, honest: PIT rows only | fewer features, no lookahead |
| **B** | rich, contaminated: the 21-field settled archive | more features, lookahead at fit |

Fit both. **Evaluate both identically**, on point-in-time walk-forward evaluation over captured
inputs. Nothing in the evaluation may come from the settled archive for either candidate — if the
evaluation is contaminated the comparison is void.

**Declare the acceptance bar BEFORE fitting**, and record it in the report. The slice gate was
already a lottery once — 99.885–99.9905% false rejection of a better candidate — and every
rejection that month was uninformative. A bar chosen after seeing results is not a bar.

Report, for each candidate: centre, width, Brier and the market gap, **with crossed date × market
clustering and power**. Report **B − A** explicitly: that difference *is* the measured cost or
benefit of fit contamination, and it replaces the inherited ~6%.

## 7. P4 — if a candidate qualifies

Run, and report:

- **train/serve parity** — it must stay at **0 unexpected**. `-09-39a` earned that; do not lose it.
- **candidate-bound replay.** `-09-39a`'s zero served delta holds only because the bound June
  artifacts do not select `wind_gust_kmh` or `wind_shift_3h_degrees`. **A candidate that selects
  them invalidates that control** — its own replay is mandatory, in its own words.
- the first-retrain preflight, with **every remaining blocker enumerated individually**.

## 8. Method — binding

- **Crossed date × market clustering** on every comparison. Report power before interpreting any
  point. **"Not powered" is a valid verdict** and is preferred to a directional story.
- **Never pool across `2026-07-31`** (artifact provenance, anchor `b77cfbed`).
- Ledger rows are **not** market-days — deduplicate to `(market, target_date)`, then apply
  `promotion_countable`. A prior handoff quoted 15,174 "market-days" that were 729.
- **The 12,600-cell gate is code-owned.** If it takes its size from the candidate's own manifest,
  that is the self-sizing defect returning — stop and report.
- **Never weaken or bypass the serving floor** to move a number. §3 records it as the one shipped
  win; centre displacement was traced to mass below it.
- `pytest -q` is **red on master** — 4 unowned failures named in `STATE_OF_PLAY.md`. Diff against
  those; classify anything else you see rather than lumping it in.

## 9. Boundaries

`DELEGATION_CONTRACT.md` §2 in full, with one **explicit exception**: you **may call the free
Open-Meteo endpoints, both hosts**, because the collection and the P0 probe are the task.
**No paid API, ever** — that is a standing operator decision, and it has halted two prior missions
that stopped to ask. Do not stop to ask.

- **Do not write production `data/`.** Collect and fit on the workstation.
- **Produce a candidate; promote nothing.** Release #1 is **DEFERRED** by decision and this does
  not change it. No registration, no activation, no release binding.
- **Do not declare the confirmation window.** It arms at candidate freeze and the declaration is
  the operator's. Check `reserved-confirmation-window.md` at run time — it wins over this handoff.
- Do not run the chain, settle a date, or restart anything.
- Expect `roll_verdict.ps1` **exit 3** if you touch the trainer or `forecast_history.py`; both sit
  in live capture closures. That does not block you — production merges in the quiet window, and
  **pushing a branch never rolls anything.**

## 10. What would falsify this mission

- **P0 shows the two-host premise is wrong.** Report it and stop; the premise is load-bearing for
  everything downstream.
- **The PIT surface cannot support a model at all.** Then "the honest corpus is not viable, and
  here is exactly what it carries" is the result, and the contamination question becomes an
  operator decision with a measured price attached.
- **B beats A on clean evaluation.** That is a legitimate and interesting outcome — it would mean
  the extra features earn more than the lookahead costs. Report it plainly; do not suppress it
  because contamination sounds wrong.
- **Neither candidate beats the incumbent**, or the comparison is **not powered**. Say so. Do not
  ship a candidate to have shipped one.

## 11. Branch and report

- Branch: `codex/workstation-honest-corpus-versus-rich-corpus-2026-09-40a`
- Report: `docs/roadmap/agent-report-2026-08-07-workstation-honest-corpus-versus-rich-corpus.md`

Base on **`origin/codex/workstation-close-the-train-serve-parity-gap-2026-09-39a`** — it carries the
parity repair, the archive window and the retrain lane, and is not yet on master. State your base
commit explicitly.

Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and a per-file roll verdict
from **`scripts\ops\roll_verdict.ps1 -Branch <branch>`** — do not derive it by hand.
**Commit and push whenever you finish, at whatever hour.**

# Workstation handoff 2026-09-41a — the honest corpus versus the rich one, and the first candidate

Written 2026-08-07 by the production agent. Read on `origin/master` and execute.
**Re-dispatch of `-09-40a`, whose P0 stop was correct. Long mission — take the time it needs.**

## 1. Why this is a re-dispatch, and what that tells you

`-09-40a` stopped at P0 because my corpus-inventory claim was wrong. **It was right to stop, its
measurement was correct, and production verification confirms it in full:**

| | I claimed | `-09-40a` measured | Production, verified 2026-08-07 |
| --- | --- | --- | --- |
| Rows/station, `fixed_lead_day_offset` | 2,135 | 2,135 | **2,135** ✓ |
| Rows/year, 2021–2025 | 416 | 364 | **364** |
| 2026 rows | *(not mentioned)* | 315 | **315** |
| Lead days | 1–4 | 1–7 | **1–7** |

364 × 5 + 315 = 2,135 exactly. The matching total was a coincidence of different populations, as
that report said.

**The defect was mine and it was in the handoff, not the work.** I put a bookkeeping detail in the
same bullet list as the load-bearing premise and wrote *"if any of this is wrong, stop"*. So the
mission spent its cycle on the claim that did not matter and never reached the two-host premise —
the one where I have actually erred twice. §3 below fixes that: **stop conditions are now ranked.**

## 2. Goal

> **Does a thin, honest point-in-time corpus beat a rich, contaminated one when both are judged on
> the same clean walk-forward evaluation?**

Build them, fit a candidate on each, evaluate identically, and **produce the first retrained
candidate** — or report why none qualifies. Second payload: the A/B **measures what fit
contamination costs**, replacing the ~6% figure §6 inherited from a different setup.

## 3. Stop conditions, RANKED — read before P0

**Load-bearing. If wrong, stop and report:**

- the two-host distinction (§4),
- that the PIT surface is materially narrower than the settled archive,
- anything in §8 Method.

**Not load-bearing. If wrong: record the correction in your report and KEEP GOING.** Row counts,
per-year splits, lead ranges, file sizes, my arithmetic. A corrected number is a finding, not a
blocker. **Do not stop a second time on my bookkeeping.**

## 4. Established on production 2026-08-07 — verify, but these are measured

Two endpoints in `sources/forecast_history.py`:

```
HIST_FORECAST_URL  = https://historical-forecast-api.open-meteo.com/v1/forecast   # settled archive
PREVIOUS_RUNS_URL  = https://previous-runs-api.open-meteo.com/v1/forecast          # the PIT surface
```

The archive host **ignores** `previous_runs=` and returns the settled series unrenamed; probing
`_previous_dayN` against it measures the wrong thing. **Calling `previous_runs=` a leakage trap in
general is RETRACTED** — it is host-specific. On the PIT host, `temperature_2m_previous_day1`
differs from settled in **23 of 24** hours.

**Four facts from disk that need no API call, all verified on production:**

1. Every one of the 2,135 fixed-lead rows carries `source = open_meteo_previous_runs`. **The PIT
   host is already in use** — the two-host distinction is corroborated from the data side.
2. The file's only forecast variable is `forecast_high_native` / `forecast_high_c`. **The
   materialized honest corpus is already single-variable**, independent of what the API could serve.
3. Target range is **2021-05-10 → 2026-06-23, months 05 and 06 only, zero July/August rows.** The
   honest corpus on disk sits in the **stale** May 10 – Jun 30 window — the very window `-09-31a`
   blamed for the cool bias. **It cannot train the season we serve, so P1 is genuinely un-started.**
4. `daily_by_issue_path()` in `sources/forecast_history.py` has **zero readers in `src/`**. The PIT
   file is written and never consumed. `forecast_error_model.py:42` hardcodes
   `DEFAULT_FORECAST_DAILY` to the stitched `forecast_daily.csv` for **`cyyz` alone** — on a
   12-market platform. Check whether callers override that; if they do not, say so.

**The open question P0 must settle:** §4f measured **1 of 21** fields PIT-expressible — but that
was a **single-lead, single-market, `_previous_day1`** probe. Establish the real surface: every
field the trainer wants, **leads 1–7**, more than one market. "Temperature only" is a belief.

## 5. P1 — collect the honest corpus for the window we actually serve

Using the existing `forecast_history.py` path that produced the 2,135 rows — **not a hand-rolled
fetch** — collect PIT rows for **July 17 – August 14, 2021–2025, all 12 markets**. Per §4.3 none of
this window exists yet. Collect whatever the P0 probe says the surface carries; do not narrow to
temperature by assumption.

## 6. P2 — make the trainer able to read the PIT file

Per §4.4 this is a code defect, not a data gap: the honest file exists and nothing reads it.
**Keep both paths selectable** — the mission depends on fitting one candidate each way, so this is
a switch, not a replacement.

## 7. P3 — three candidates, one evaluation

| | Corpus | Expectation |
| --- | --- | --- |
| **A** | thin, honest: PIT only | fewest features, no lookahead |
| **B** | rich, contaminated: the 21-field settled archive | most features, lookahead at fit |
| **C** | **hybrid: PIT `forecast_high` + settled for the rest** | the realistic production answer |

**C is likely the highest-value candidate and it is nearly free once P2 exists.** `forecast_high`
is the forecast of the quantity we predict — plausibly the strongest single feature — and it is
both the most damaging thing to contaminate *and* the one field with a real PIT surface. If A is
one feature and not a model, **C is still a genuine improvement over B.** Do not skip it because
the handoff table lists it third. If P0 shows the PIT surface is wider than one field, C widens
with it.

**Evaluate all identically**, walk-forward on captured inputs. **Nothing in the evaluation may come
from the settled archive for any candidate** — a contaminated evaluation voids the comparison.

**Declare the acceptance bar BEFORE fitting** and record it. The slice gate was a lottery once —
99.885–99.9905% false rejection of a *better* candidate — and every rejection that month was
uninformative. A bar chosen after seeing results is not a bar.

Report per candidate: centre, width, Brier, market gap, **crossed date × market clustering and
power**. Report **B − A** and **B − C** explicitly: those differences *are* the measured price of
contamination and of the part of it we can actually fix.

## 8. P4 — if a candidate qualifies

- **train/serve parity must stay at 0 unexpected.** `-09-39a` earned that; do not lose it.
- **candidate-bound replay.** `-09-39a`'s zero served delta holds only because the bound June
  artifacts do not select `wind_gust_kmh` or `wind_shift_3h_degrees`. **A candidate selecting them
  invalidates that control** — its own replay is mandatory, in that report's own words.
- the first-retrain preflight, **every remaining blocker enumerated individually**.

## 9. Method — binding

- **Crossed date × market clustering** on every comparison; report power before interpreting a
  point. **"Not powered" is a valid verdict** and beats a directional story.
- **Never pool across `2026-07-31`** (artifact provenance, anchor `b77cfbed`).
- Ledger rows are **not** market-days — deduplicate to `(market, target_date)`, then apply
  `promotion_countable`. A prior handoff quoted 15,174 "market-days" that were 729.
- **The 12,600-cell gate is code-owned.** If it sizes itself from the candidate's own manifest,
  that is the self-sizing defect returning — stop and report.
- **Never weaken or bypass the serving floor** to move a number. §3 records it as the one shipped
  win; centre displacement was traced to mass below it.
- `pytest -q` is **red on master** — 4 unowned failures named in `STATE_OF_PLAY.md`. Diff against
  those; classify anything else rather than lumping it in.

## 10. Boundaries

`DELEGATION_CONTRACT.md` §2 in full, with one **explicit exception**: you **may call the free
Open-Meteo endpoints, both hosts** — the collection and the P0 probe are the task. **No paid API,
ever.** That is a standing operator decision and it has halted two prior missions that stopped to
ask. Do not stop to ask.

- **Do not write production `data/`.** Collect and fit on the workstation.
- **Produce a candidate; promote nothing.** Release #1 is **DEFERRED** by decision and this does
  not change it. No registration, activation, or release binding.
- **Do not declare the confirmation window.** It arms at candidate freeze and the declaration is
  the operator's. Check `reserved-confirmation-window.md` at run time — it wins over this handoff.
- Do not run the chain, settle a date, or restart anything.
- Expect `roll_verdict.ps1` **exit 3** if you touch the trainer or `forecast_history.py` — both sit
  in live capture closures. It does not block you: production merges in the quiet window, and
  **pushing a branch never rolls anything.**

## 11. What would falsify this mission

- **The two-host premise is wrong.** Report and stop — it is load-bearing for everything downstream.
- **The PIT surface cannot support a model even as the hybrid C.** Then "the honest corpus is not
  viable, and here is exactly what it carries" is the result, and contamination becomes an operator
  decision with a measured price attached.
- **B beats A and C on clean evaluation.** Legitimate and interesting — it would mean the extra
  features earn more than the lookahead costs. Report it plainly; do not suppress it because
  contamination sounds wrong.
- **No candidate beats the incumbent**, or the comparison is **not powered**. Say so. Do not ship a
  candidate to have shipped one.

## 12. Branch and report

- Branch: `codex/workstation-honest-corpus-versus-rich-corpus-2026-09-41a`
- Report: `docs/roadmap/agent-report-2026-08-07-workstation-honest-corpus-versus-rich-corpus-41a.md`

Base on **`origin/codex/workstation-honest-corpus-versus-rich-corpus-2026-09-40a`** (head
`7517a631`) — it stacks on `-09-39a` and carries the parity repair, archive window, retrain lane
and the `-09-40a` report. State your base commit explicitly.

Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and a per-file roll
verdict from **`scripts\ops\roll_verdict.ps1 -Branch <branch>`** — do not derive it by hand.
**Commit and push whenever you finish, at whatever hour.**

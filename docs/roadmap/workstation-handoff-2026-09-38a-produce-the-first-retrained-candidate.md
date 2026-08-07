# Workstation handoff 2026-09-38a — produce the first retrained candidate

Written 2026-08-07 by the production agent. Read on `origin/master` and execute.
**This is the critical path. Nothing else is running.**

## 1. Goal

**Collect the target-derived forecast archive and drive the first retrain to an actual candidate**
— or enumerate precisely what still blocks it. Not another measurement: a candidate, or a
blocker list.

## 2. Why this is the highest-leverage work available

The centre is **74.97% of oracle excess loss** and the retrain is the only identified fix for it.
`-09-33a` finished the *code* to derive the archive window from the training target, and passed:

| `-09-33a` measured | Value |
| --- | ---: |
| Archive radius (selection 7d + `HISTORY_WINDOW_DAYS` 7d) | **14 days** → **July 17 – Aug 14** per analog year |
| Policy years | **2021–2025** |
| Dates per market | **145** (29/year) |
| **Fleet market-dates required** | **1,740** |
| Free-endpoint probe, 12 markets × 5 years | **60/60 HTTP 200**, 360 hourly rows each, complete core fields, **0** contract failures |

And it says, explicitly: **"No production collection was performed."** Nothing since has done it.

**So the only un-started step on the critical path is fetching data that is already proven
available.** That is ~60 requests (one per market/year, each covering the 29-date window), not
1,740. It is small, bounded, and nobody has run it.

## 3. Base — do not branch from `master`

Base on **`origin/codex/workstation-make-the-season-window-target-derived-2026-09-33a`**
(head `492bfbb7`). It **contains `-09-20a`** (`981b1d3a`) as an ancestor — verified on the
production host — so it carries both the rescued retrain lane and the target-derived window.
It is **not yet merged to master**: it is roll-sensitive and queued behind the settlement fix.

## 4. Start from this — established, do not re-derive

- **Free-tier Open-Meteo only. Never a paid API.** Training population **2021–2025**. Closed.
- **Never pool across `2026-07-31`** (artifact provenance, anchor `b77cfbed`).
- **Both retrain lanes carried a self-sizing defect** — the candidate's own manifest sized its own
  gate (20,160 cells or 2,520, its choice). It is rescued at a **code-owned 12,600-cell gate**.
  If you see the gate take its size from the candidate, that is the defect returning.
- **Train/serve parity is the dominant defect class here.** `wind_gust_kmh` and
  `wind_shift_3h_degrees` were dropped at serve in all 12 markets and would have contaminated the
  first retrain. Run the parity gate before believing any candidate.
- The cool bias is **seasonal coverage**, which is exactly what this archive fixes — but the gap
  **does not vanish in-season** (`-09-34a`). The retrain is **necessary, not sufficient**.

## 5. Prioritised work

### P0 — collect the archive for the target-derived window

Use the module's own target-derived path, not a hand-rolled fetch: the whole point of `-09-33a`
is that the caller's training target plus the climatology halo selects the window. Collect
**July 17 – August 14, 2021–2025, all 12 markets**.

Verify coverage the way the gate does: it must report **healthy 12/12** for the first-retrain
target afterwards. Today it reports **BLOCK, 0/12**.

### P1 — stage the PIT corpus and run the preflight

Corpus staging is **0/60 units** today. Stage it, then run the first-retrain preflight and
**enumerate every blocker it raises, individually**. The last count was 97 across 6 gates, of
which the forecast-source decision cleared ~60. **Nobody has enumerated what remains.** That list
is a deliverable in its own right even if the retrain never runs.

### P2 — produce the candidate

Fit it. Report its metrics against the incumbent **with crossed date × market clustering and
power**, and run the **train/serve parity gate** on it before reporting anything else.

## 6. Method — binding

- **Crossed date × market clustering** on every comparison. Report power. **"Not powered" is a
  valid verdict** and is preferred to a directional story.
- Ledger rows are **not** market-days — deduplicate to `(market, target_date)`, then apply
  `promotion_countable`. A handoff once quoted 15,174 "market-days" that were 729.
- `pytest -q` is **red on master** before you start — 4 unowned failures named in
  `STATE_OF_PLAY.md`. Diff against those; do not claim you broke or fixed them.

## 7. Boundaries

`DELEGATION_CONTRACT.md` §2 in full, with **one explicit exception**: this mission **may call the
free Open-Meteo historical-forecast endpoint** to collect the archive, because that collection is
the task. No paid endpoint, no market endpoint, no other provider.

- **Do not write production `data/`.** Collect and fit on the workstation. Production will repeat
  the collection itself — it is ~60 requests, so the valuable output is *whether the retrain runs
  and what blocks it*, not the bytes.
- **Do not promote, register, or activate anything.** Release #1 is **DEFERRED** by decision;
  producing a candidate does not change that.
- **Do not declare the confirmation window.** It arms at candidate freeze and declaring it is the
  operator's call. Check `reserved-confirmation-window.md` at run time — it wins over this handoff.
- Do not run the chain, settle a date, or restart anything.

## 8. What would falsify this mission

- **The preflight blocks and cannot be cleared from the workstation** — e.g. a gate needing
  production settlement state. Then the enumerated blocker list *is* the result. Report it and stop.
- **Rate limits make the 60-request collection infeasible.** Report the observed limit; that
  changes the collection design.
- **The candidate fails train/serve parity.** Report the dropped features; do not tune around it.
- **The 12,600-cell gate takes its size from the candidate manifest.** That is the self-sizing
  defect returning — stop and report, do not proceed to a candidate.

## 9. Branch and report

- Branch: `codex/workstation-produce-the-first-retrained-candidate-2026-09-38a`
- Report: `docs/roadmap/agent-report-2026-08-07-workstation-produce-the-first-retrained-candidate.md`

Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and a per-file roll
verdict from **`scripts\ops\roll_verdict.ps1 -Branch <branch>`** — do not derive it by hand.
State your base commit explicitly, since you are branching from `-09-33a` and not from `master`.
**Commit and push whenever you finish**; pushing cannot roll production capture.

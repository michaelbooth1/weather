# Workstation handoff 2026-09-60a — the first actual candidate

Written 2026-08-10 by the production agent. Read on `origin/master` and execute.
**This is the first mission in this project's history to test a forecast candidate with a
mechanism, a trigger, a certified endpoint and a budget all in place at once.**

## 1. Why this, and why now

Everything since `-09-44a` has been elimination. Four missions closed routes:

| | |
| --- | --- |
| `-09-56a` | recalibration is closed — bounded at **16.494%**, not distinguishable from zero (§1c) |
| `-09-57a` | the tail **is** refereeable at **3.53%** of its gap; hard **3.2% floor** set by 12 markets (§1d) |
| `-09-58a` | dispersion screen NO-GO — but **blind**, and the PIT source stops `2026-06-23` (§1e) |
| `-09-59a` | **GO** — the tail is centre+shoulder **overconfidence**, ex-ante predictable at AUROC **0.90260** (§1f) |

`-09-59a` also killed the two cheap escapes: **markets are diffuse** (11.44 effective of 12) and
**season/cutoff gating is NO-GO**. What survives is a single direction, and every precondition for
testing it is now satisfied:

- **A mechanism** — we are overconfident at our own mode; the mode wins ~24% (§1).
- **An own-information trigger** — band-state-only AUROC **0.85207**, no market input required.
- **A measurable endpoint** — tail MDE 3.53% of its gap, 4.87% under the ledger (§1d).
- **A budget** — `CAMPAIGN_LEDGER.md`, decision **9**, α=0.0025.

## 2. P0 — the cheap pre-check, on B only, which spends NO slot

**Do not spend decision 9 yet.** `-09-58a` saved a slot by screening on B first; do the same.

**The question: does CONDITIONAL reshaping beat GLOBAL reshaping on in-season B?**

This is the whole bet. §1c already measured the global version — `q ∝ p^β`, β=0.55, recovering
**8.829% [−2.467%, +16.494%]** of the gap, **not distinguishable from zero**. Two live readings,
and you must **declare which you expect before you look**:

- **Conditioning concentrates a benefit that global smoothing diluted** across the 95% of rows that
  were already fine → conditional materially beats 8.829%.
- **§1c's upper bound already caps this shape of fix** → conditional lands inside it and the
  direction is closed.

*(Production agent's prior, stated so it is falsifiable: I expect conditional to beat global,
because global applies the correction where it is not needed. I hold it weakly — the §1c interval
is the only measurement either of us has.)*

**If conditional does not beat global on B, stop and report.** That is a clean, valuable NO-GO and
it costs no slot.

## 3. P1 — if P0 clears, build ONE candidate and spend decision 9

**Append the ledger row before you score anything on C.** Decision 9, α=0.0025 two-sided.

**Design constraints, all binding:**

- **The trigger must be OWN-INFORMATION ONLY (§0c).** Band state, distribution shape, schedule,
  own weather. **The market may not enter the trigger, the reshape, or anything servable.** This
  also disposes of §1f's open caveat — the `|p_model − p_market| ≥ 0.30` gate is definitional and
  partly drives the centre story, but a band-state trigger never touches it, and the candidate is
  scored on real loss rather than on tail membership.
- **Conditional, never global.** Global sharpening stays retired; §1c's β came back **below 1**,
  i.e. smoothing. Whatever you fire must fire on a subset.
- **Preserve total probability mass** and **never weaken the serving floor.** The floor's
  interaction with redistributed mass is exactly where §2's centre-displacement mechanism lives —
  if your reshape moves mass below the floor, say so explicitly.
- **Score the fit on its own training set first** (§5). Free, and it caught `-09-56a`'s broken
  objective instantly.

**Two endpoints, both required:**

1. **Primary — tail SSE.** Where the loss is and where the instrument is sharpest.
2. **Secondary — overall excess Brier vs market.** **A candidate that improves the tail by hurting
   the bulk is worthless.** Report both or the result is uninterpretable.

Place the effect against §1d's floor and say which case holds: ≥5% (confirmable, give the
post-boundary date), 3.2–5% (confirmable late), **≤3.2% (NOT individually confirmable at any date
count — must be batched, do not ship alone)**.

**Re-derive the MDE for the candidate you actually build.** §1d's curve is a proxy from `-09-44a`'s
effect field and does not transfer.

## 4. What would falsify this mission

- **Conditional does not beat global on B** → the direction is closed, cheaply, with no slot spent.
  Given §1c, this is a live possibility and not a failure of the work.
- **The tail improves but total Brier does not** → we have moved loss, not removed it. Say so
  plainly; it would mean the tail is a *symptom* rather than a lever.
- **The effect is below 3.2%** → real but permanently unconfirmable alone; report and batch.
- **The reshape needs the floor weakened to work** → stop. The floor is not negotiable, and its
  own fix was the one shipped win of the month (§3).

## 5. Context you should not re-derive

- **Recalibration is closed** (§1c) — but **this is not that.** §1c closed *global,
  information-free monotone mappings*; an own-information **trigger** decides *where* to act, which
  makes it a model change. Do not let the two be conflated in either direction.
- **Do not anchor expectations to §1f's 27.42%** addressability ceiling — that is what a *perfect*
  intervention on the top 5% could reach, not a booked gain. Anchor to §1c's 8.829%.
- Input completeness is not the lever (`-09-44a`). Market-shrinkage is a diagnostic, never a
  candidate (§1c, §0c). `74.97%` is unciteable. Model-skewed quoting is retired (`-09-46a`).
- Nothing is reserved; `docs/operations/reserved-confirmation-window.md` wins over every other
  document.

**Environment:** the repo venv on that host points at a removed Python 3.11. Use the bundled Codex
3.12 runtime as the last three missions did. Install nothing.

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Promote nothing, activate nothing, place no order, enable no
live trading, call no exchange or weather-provider endpoint.** Nothing under production `data/`. No
chain run, settlement, or loop restart. **Never weaken the serving floor.** The production release
store must stay empty. Anything fitted lives in a scratch root and is a **diagnostic candidate** —
an accepted result is labelled `SELECTED_ON_PREBOUNDARY_PANEL`, **not confirmed**, and stays
provisional until post-boundary evidence can decide it.

**Paid weather-provider access is unsupported.** Do not add credentials, required environment
variables, or any plan that depends on a paid weather source.

## 7. Branch and report

- Branch: `codex/workstation-conditional-tail-reshape-2026-09-60a`
- Report: `docs/roadmap/agent-report-2026-08-19-workstation-conditional-tail-reshape.md`
- **Commit your `CAMPAIGN_LEDGER.md` row if you spend decision 9** — it is part of the deliverable.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**

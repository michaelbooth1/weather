# Workstation handoff 2026-09-56a — decompose the gap on the current surface

Written 2026-08-09 by the production agent. Read on `origin/master` and execute.
**This supersedes the retrain blocker chain as the top item on objective #2.**

## 1. The decision that changed the question

The operator decided on 2026-08-09: **the goal is a better model, not a production-qualified
candidate**, with small improvements accepted incrementally (`ESTABLISHED_FINDINGS.md` §0b).

The release and qualification machinery is therefore **no longer the critical path**. What matters
now is **measurable served improvement per unit of effort** — and we cannot rank that, because:

> **`ESTABLISHED_FINDINGS.md` §5: the gap has never been decomposed on the current surface.** Of our
> excess Brier over the market, how much is **calibration** and how much is **information**? That
> question is *"currently unsupported in both directions."*

**Without that answer, "make small improvements" is guessing.** With it, it becomes a ranked
worklist. That is this mission.

## 2. P0 — decompose the excess Brier over the market, on today's model

**The estimand, stated exactly so it is not confused with the ones already in canon:** of the model's
**excess Brier relative to the market**, what share is removable by **recalibration alone** (a
monotone/probability-mapping correction that reorders nothing), and what share requires **new
information** (resolution the model does not have)?

**Two adjacent numbers in canon are NOT this and must not be reused as if they were:**

- §1's **84.772% / 15.228%** is a served-**loss** decomposition, not a decomposition of the **gap**.
- The retired **98.88% / 1.12%** decomposed the gap on a **different panel** and is retired.

Report the split with **crossed date × market clustering**, the interval, and **power/MDE stated
before interpretation**. If the split cannot be estimated with usable precision, **say so** — an
honest "unidentified" beats a number nobody should act on, and `-09-47a` set that precedent.

## 3. P1 — turn it into a ranked worklist

For whichever component dominates, name **concrete, addressable** candidates and size each:

- If **calibration** dominates: what mapping, fitted on what, evaluated walk-forward, and what is the
  expected served delta? Note §1's caution — **the reliability share moved 1.12% → 15.228% on panel
  change, not on a repair, and whether any of it is recoverable is NOT established.**
- If **information** dominates: which inputs plausibly carry it, and what is the cheapest test?
  Remember `-09-44a` — completing the input population moved the gap by **≤0.6% of the distance to
  parity** — so **do not propose more input completeness without a mechanism.**

**Rank by expected served delta per unit of effort, and state your uncertainty on both axes.** A
ranked list with honest error bars is the deliverable; a single recommendation is not.

## 4. Constraints on method — the bar for believing a result has NOT moved

Dropping *qualification* is not dropping *honesty*. **item-224's "win" over the market was leakage**
and was retracted; do not repeat it.

- **No design that can see its own target.** Walk-forward or replay only.
- **Crossed date × market clustering; power before interpretation.**
- **Never pool across `2026-07-31`** (artifact provenance boundary, anchor `b77cfbed`).
- **Cite the stratum** — 1.4233x is *in-season*; we serve *out-of-season* at 1.526x–1.542x (§1b.4).
- Use the **existing replay harness**. You need **none** of the release machinery for this.

## 5. What would falsify this mission

- **The split is unidentified at usable precision.** Report it plainly; that would mean incremental
  improvement cannot be *directed* by this decomposition and we must pick differently.
- **Recalibration's recoverable share is ~zero.** Then "the model is honest but uninformed" is
  established rather than assumed, and every calibration idea is closed at once — **highly valuable.**
- **The dominant component is not addressable by anything we can build.** Say so. Knowing the gap is
  structural is worth more than a year of small attempts.

## 6. Context you should not re-derive

- **Do not commission or assume model-skewed quoting** — retired, 114 cells, zero positive
  (`-09-46a`).
- **`74.97%` is retired with no replacement.** Do not cite a retrain payoff figure.
- The one shipped improvement of the month was a **serving-path** fix (§3, 1.6639 → 1.4980), of which
  only ~2.2% landed in the 09:00–14:00 primary window.
- Nothing is reserved; `reserved-confirmation-window.md` wins over every other document.

## 7. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Promote nothing, activate nothing, place no order, enable no
live trading, call no exchange or weather-provider endpoint.** Nothing under production `data/`. No
chain run, settlement, or loop restart. **Never weaken the serving floor.** The production release
store must stay empty.

Fitting is authorized **only** where the decomposition genuinely requires it, to a scratch root,
stated explicitly — and any fitted mapping is **diagnostic, not a candidate**.

## 8. Branch and report

- Branch: `codex/workstation-decompose-the-gap-2026-09-56a`
- Report: `docs/roadmap/agent-report-2026-08-19-workstation-gap-decomposition.md`

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never hand-derived.**
**Commit and push whenever you finish, at whatever hour.**

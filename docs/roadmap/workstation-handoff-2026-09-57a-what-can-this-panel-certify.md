# Workstation handoff 2026-09-57a — what can this panel actually certify?

Written 2026-08-09 by the production agent. Read on `origin/master` and execute.
**Runs in PARALLEL with `-09-56a`. It needs none of `-09-56a`'s output and must not duplicate it.**

## 1. Why this exists

The operator decided on 2026-08-09: **the goal is a better model, accepted as small improvements
over time** (`ESTABLISHED_FINDINGS.md` §0b). `-09-56a` is deciding **what to improve**.

Nobody has asked **whether we can tell that we did.** That is this mission.

An incremental path is a **sequence of accept/reject decisions against one instrument**. Its
validity is a property of the instrument and of the sequence, not of any single measurement. We
have never characterised either. Two facts make this urgent rather than academic:

- **Our only sensitive panel is fixed and sealed.** D=50, M=12, 524 promotion-countable
  market-days, 06-03 → 07-30, pre-boundary. Every improvement will be selected *and* confirmed on
  **the same 50 dates**.
- **There is no confirmation panel today.** Post-boundary settlements cover **5 dates only**
  (`2026-07-31` → `2026-08-04`, 12 markets, 60 market-days), and they stop there because
  `08-05` → `08-08` are not yet backfilled. **`-09-43a` was measured on 5 date clusters at power
  0.131 and could conclude nothing** — that is exactly what a 5-date confirmation panel is worth.

**This is the successor risk to item-224.** That was leakage into the *fit*. The risk now is
leakage into the **selection**: a panel consulted k times is no longer a holdout, and the winner of
k honest tests is a biased estimate even when every individual test was clean.

## 2. What we already know about the instrument — do not re-derive

| | |
| --- | ---: |
| In-season pooled ratio, 80%-power MDE (`-09-44a`, paired) | **0.003055 ratio points** |
| Distance from current in-season ratio to parity | **0.4233** |
| **So a detectable step is** | **≥0.72% of the distance to parity** |

**Read that as good news and state it in your report.** The paired design is a *fine* instrument;
`-09-44a` returned a **precise null**, not a blind one. The reflex "we are underpowered" is wrong
for the pooled in-season endpoint.

**But it is the only endpoint whose MDE we know**, and it is not the endpoint that matters.

## 3. P0 — per-stratum operating characteristics

Compute the **80%-power MDE of a paired improvement**, on the existing sealed corpus, with crossed
date × market clustering, for each stratum separately:

1. **In-season** (known: 0.003055 — reproduce it as a positive control that your harness agrees
   with `-09-44a`; if it does not reproduce, that is itself the finding and you should stop).
2. **Out-of-season** — the stratum we actually serve in August (§1b.4, 1.526x–1.542x).
3. **The severity tail** — **4.387% of band rows carrying 64.140% of positive excess loss.**
4. **The 09:00–14:00 primary objective window.**

**Stratum 3 is the one that matters most and is most likely to be blind.** Canon already says work
that improves the pooled average while leaving the tail alone is close to worthless — and §4d's
seasonal contrast on the severe tail came back **underpowered at 47.65%, MDE 1.3489**. If the tail's
improvement-MDE is larger than any improvement we could plausibly ship, then **the incremental path
cannot verify progress where the loss actually is**, and that is a decisive, path-changing result.

For stratum 4, note §5 already records the primary-slice endpoint needs **~504 dates and we have
50**. Do not re-litigate that; state the consequence for the decision rule.

Report each MDE **in the units the improvement would be proposed in**, and next to it the fraction
of the remaining distance to parity it represents. An MDE with no denominator is not usable.

## 4. P1 — the multiplicity budget

**How many accept/reject decisions can this panel support before the selection process is the
defect?**

- Quantify the **selection inflation**: if k candidate improvements are each tested at α=0.05 on
  these 50 date clusters and we ship the best, how biased is the shipped estimate as a function of
  k? Simulate it on the real cluster structure — do not cite a textbook formula, the crossed
  clustering makes the effective N the whole question.
- Then **specify a protocol** we will actually follow. Options to price, not to advocate:
  fold-splitting the 50 date clusters into selection and confirmation halves; an α budget spent
  down across the campaign; pre-registration per improvement; or requiring post-boundary
  confirmation before anything is believed.
- State the **cost of each option in MDE** — splitting the panel makes every individual test
  blunter, and the tail may not survive a split at all. That trade is the deliverable.

## 5. P2 — when does a real confirmation panel exist?

Post-boundary data is the only thing that can ever be a true holdout, because **we must never pool
across `2026-07-31`** (artifact provenance, anchor `b77cfbed`).

Given: D=5 today, accruing ~1 date/day, 12 markets, with `08-05` → `08-08` backfills armed for
`08-10` → `08-13` on the production host — **at what D does the post-boundary panel reach the MDE
needed to confirm a step of the size §1b.5's decomposition implies, and what calendar date is
that?** A dated answer, with its assumptions stated.

If the answer is "not before October," say so plainly. That is a scheduling fact the operator needs
in order to judge how much to believe in the interim.

## 6. What would falsify this mission

- **The tail's MDE is small.** Then the panel can referee the work that matters and the incremental
  path is well-founded — a clean green light, and worth having explicitly.
- **The panel supports many decisions with negligible inflation.** Then multiplicity discipline is
  overhead we can skip; say so and save the campaign the cost.
- **`-09-44a`'s 0.003055 does not reproduce.** Stop and report. Everything downstream of that number
  is then in question, including `-09-56a`.

## 7. Constraints on method

- **Crossed date × market clustering; power before interpretation.** No design that sees its target.
- **Never pool across `2026-07-31`.**
- **Cite the stratum, always** (§1b.4).
- Use the **existing replay harness and the sealed corpus.** You need none of the release machinery.
- Do **not** re-derive the calibration/information split — that is `-09-56a`'s estimand, it is
  running concurrently, and two answers to one question is worse than one.

## 8. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Promote nothing, activate nothing, place no order, enable no
live trading, call no exchange or weather-provider endpoint.** Nothing under production `data/`. No
chain run, settlement, or loop restart. **Never weaken the serving floor.** The production release
store must stay empty. Fitting is authorized only where the operating-characteristic estimate
requires it, to a scratch root, stated explicitly — and anything fitted is **diagnostic, never a
candidate**.

## 9. Branch and report

- Branch: `codex/workstation-what-can-this-panel-certify-2026-09-57a`
- Report: `docs/roadmap/agent-report-2026-08-19-workstation-panel-operating-characteristics.md`

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**

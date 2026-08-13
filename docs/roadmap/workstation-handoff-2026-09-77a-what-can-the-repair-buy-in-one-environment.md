# Workstation handoff 2026-09-77a — what can the repair buy, in one environment

Written 2026-08-11 by the production agent. Read on `origin/master` and execute.
**No α allocation, no realized outcome, no settlement, no market comparison, no C endpoint.**
Canon: `docs/operations/REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md` (`-09-75a`, `-09-76a`)
and `docs/operations/GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md` §5c (the candidate).

## 1. I am retiring my own gate

`-09-74a` stopped before computing the repair ceiling because a reproduction control failed. I set
that control. `-09-75a` and `-09-76a` have since established **why it can never pass**: what we
served was not committed, so it cannot be rebuilt. Only **0 of 368** decision rows and **111 of
28,254** whole-B rows are exactly reconstructable.

**A gate that no work can ever pass is not a gate, it is a stop.** I am retiring it. The ceiling
question does not need historical reproduction, and it never did — it needs *one* environment
holding both arms.

What changes is the claim we are allowed to make. We are not asking "what would we have served
differently." We are asking **"does this repair improve the forecast, under a single stated
environment, on captured inputs."** Canon §4 already licenses exactly that comparison and requires
you to say which question you answered. **Say it in the report title line.**

## 2. The mission

> **Fix one environment. Run the incumbent and the candidate inside it on the same captured inputs.
> Compute the outcome-free ceiling. Then answer whether an α look has any power at all.**

### 2a. Fix and record the environment — and prove `-09-76a`'s recommendation works

Use **current `origin/master`**, one environment for both arms, and record it the way `-09-76a` says
capture should have: an immutable content-addressed bundle of the **loaded** source and artifact
bytes, hashed **after import** from `sys.modules`, not from disk and not from `HEAD`.

- **Print the resolved `__file__` of every model, calibration, feature and market module** and prove
  they resolve inside your tree, not production. `-09-76a` did this correctly with 2,534 module
  paths and zero escapes; match that standard.
- Emit the bundle as an artifact. **This run must be reproducible even though history is not** —
  that is the point, and it is a working demonstration of the forward fix without touching
  `model_identity.py`.

### 2b. Both arms, same inputs, no outcome

The captured raw payloads are **not** affected by the binding defect — they are recorded inputs, not
recorded outputs. Use them.

- Incumbent `q`: current pipeline on the captured payload as-is.
- Candidate `p`: current pipeline on the payload after
  `point_in_time_wu_observable_tail_recovery_v2` (`-09-73a` §5c, which repairs **366 / 368**
  decision-window and **744 / 906** B events).
- Population: the **368-event decision stratum** first; whole B only if it is cheap.
- Report how many rows each arm actually produces, and **why any row is undefined under either arm**.
  A row where the candidate is undefined is not a row where the candidate is neutral.

### 2c. The ceiling, and then the power

The Brier ceiling is **outcome-free** — the realized band enters only through the index `b`:

```
Δ_i       = (‖p‖² − ‖q‖²) − 2(p_b − q_b)
ceiling_i = (‖p‖² − ‖q‖²) + 2·max_k(q_k − p_k)
```

**Do not read a realized band, and do not compute `Δ_i`.** Emit `realized_band_read: false`.

Aggregate with the repository's **crossed `target_date × market_id`** bootstrap and the repository's
`mean ± q·SE` convention at `q = 3.1098893` — **not** a percentile interval, and note that pointwise
domination therefore does **not** transfer to the interval bound.

Then the question `-09-74a` was built to answer and never reached:

| Compare | Against |
| --- | --- |
| the ceiling's upper bound | the **smallest effect detectable** at α = 0.0025 with **12 market clusters** |

The panel floor is **~3.2%, set by 12 markets, not by dates** — adding dates does not buy power here.
**State the detectable-effect floor explicitly and show the arithmetic.**

### 2d. Verdict, and stop

- **Ceiling below the detectable floor** → the look is unpowered. **Recommend closing the thread
  without spending α.** That is a clean result and it protects 13 remaining allocations. Say so
  plainly; do not hedge it into a "further work needed."
- **Ceiling above the floor** → the frozen `-09-73a` pre-registration is answering the wrong
  question and must be **rewritten to the single-environment question and re-frozen** before any
  look. Draft the rewrite; **do not execute it, and do not allocate α.**
- **Ceiling straddles the floor** → report the straddle. Do not round it in either direction.

**Whichever it is, stop at the recommendation. The allocation decision is the operator's.**

## 3. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **CLOSED UNUSED** and must not be reassigned.
- **No realized outcome, no settlement, no market comparison, no `Δ_i`.** Ceiling only.
- **B only. No C endpoint.** Never pool across `2026-07-31` (anchor `b77cfbed`).
- **Do not reproduce history.** No commit binding, no identity binding, no synthetic historical
  trees. That thread is closed; `-09-76a` is its last word.
- **Change nothing** in the working tree: not model, calibration, floor, producer, collection,
  scoring, serving or `model_identity.py`. **Never weaken the serving floor** (`1.6639 → 1.4980`).
- **DO NOT DELETE OR MODIFY ANY BRANCH.** Refs are read-only, full stop.
- Nothing under production `data/`. Disposable work under `scratch/`.
- `DELEGATION_CONTRACT.md` §2 in full. No provider or exchange calls, no promotion, activation,
  release or trading.

## 4. What would close this

The honest outcomes are symmetric and both are wins:

- **The repair cannot buy enough to be detectable** → we close a thread that has run four missions,
  keep the α, and go back to the central goal: a better forecast from our own information.
- **It can** → we know the size, we restate the question correctly, and the look becomes worth its
  allocation.

**What would not close it** is another mission that measures eligibility instead of effect. We have
31 retractions against one shipped win, and the recurring shape is exactly that substitution.

## 5. Environment, branch and report

Use the repository's existing Python 3.11 as `-09-75a` and `-09-76a` did. **Install nothing.**

- Branch: `codex/workstation-what-can-the-repair-buy-2026-09-77a`
- Report: `docs/roadmap/agent-report-2026-09-01-workstation-repair-ceiling-single-environment.md`
- Commit the harness and a versioned seed alongside the artifacts, with a `.sha256` receipt.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**

# Workstation handoff 2026-09-78a — does the look have power, and which way does it point

Written 2026-08-11 by the production agent. Read on `origin/master` and execute.
**No α allocation, no realized outcome, no settlement, no market comparison, no C endpoint.**
Canon: `docs/operations/GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md` **§5c and §5d**, and
`docs/operations/REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md` §5b.

## 1. What I got wrong in `-09-77a`, and why this mission exists

I commissioned a bound and did not state its sign. `ceiling_i = (‖p‖²−‖q‖²) + 2·max_k(q_k−p_k)` is
`max_b [B(p) − B(q))]`, and Brier is a loss, so the `0.4720` that came back is **the most the repair
could cost us**, not the most it could buy. Worse, the verdict rule I wrote reduces to
`mean/SE > 0.8416` applied to a quantity that is **non-negative by construction** — it could not
have returned NO-GO. `-09-77a` executed my specification correctly and flagged the orientation; the
defect is mine.

So the commissioned question is still open: **is an outcome look on this candidate worth an α
allocation?** Canon §5d supplies the missing piece — under a calibrated incumbent
`E_b[B(p)−B(q)] = +‖p−q‖²`, under a calibrated candidate it is `−‖p−q‖²`, mean **0.1385161075**,
crossed SE **0.0237649077**. But that SE is the dispersion of the *displacement*, not of the
estimand: the realized band adds variance the displacement does not carry. **The power claim in the
draft pre-registration is therefore unjustified, in the optimistic direction.**

**This mission must be able to say NO.** Build it so that it can.

## 2. The mission

> **Put an honest standard error on the primary estimand without reading an outcome, decide whether
> the look is powered, and say which way it points if the premise is wrong.**

### 2a. Reuse the evidence; do not re-run the 4.9 GB pass

Everything needed is already committed on `master`:
`docs/roadmap/repair-ceiling-single-environment-2026-09-77a.csv` — 368 rows carrying
`band_keys`, `incumbent_probs_q`, `candidate_probs_p`, `target_date`, `market_id`. Verify it against
`docs/roadmap/repair-ceiling-single-environment-2026-09-77a.sha256`
(`3d782223e5b882d2bbda233f6abaed42b1a30442126979835720aa7e610611a8`) before use, and **stop if it
differs**. No replay, no snapshot scan, no payload re-read. This should be minutes, not hours.

Note the merged `.sha256` also lists a runtime-bundle ZIP that is **intentionally not on `master`**
(canon §5d) — it lives on `origin/codex/workstation-what-can-the-repair-buy-2026-09-77a`. Its absence
from `master` is expected and is not a receipt failure.

### 2b. The estimand's standard error, under both calibrated-arm nulls

The primary estimand is the paired improvement `Δ_i = B(q, b) − B(p, b) = (‖q‖²−‖p‖²) + 2(p_b−q_b)`,
positive = candidate better. It is a function of the realized band `b`, which you may not read. So
**simulate `b` instead of observing it**, under each arm's own claim:

- **Null I — incumbent calibrated:** draw `b_i ~ Categorical(q_i)` independently per row.
- **Null C — candidate calibrated:** draw `b_i ~ Categorical(p_i)`.

For each null, over ≥ 10,000 draws: compute the row vector `Δ`, aggregate with the repository's
crossed `target_date × market_id` pigeonhole bootstrap, and report the mean and the **standard
error of the mean estimand**, not of the displacement. Confirm the simulated means land on the
analytic values `∓0.1385161075` — that is your correctness control, and **report it as a receipt.**

Use a fresh committed seed. State the RNG and the draw count.

### 2c. The power question, with a real NO-GO

Using the repository convention `mean ± q·SE` at `q = 3.1098893`, α = 0.0025, 80% power:

```
MDE = (3.1098893 + 0.8416212336) · SE(Δ)
```

| Compare | Against | Read as |
| --- | --- | --- |
| `|mean Δ|` under **Null C** (the *most favourable* premise) | that null's MDE | if it fails here it fails everywhere |
| the same, under **Null I** | that null's MDE | the symmetric harm case |

Also state the α-corrected 12-market canonical floor `0.0451345675` and whether `SE(Δ)` is large
enough that the floor, not the field, binds.

**If `|mean Δ|` under Null C does not clear its own MDE, the look is unpowered under the premise
most generous to the candidate. Recommend closing the thread and keeping the α, plainly.** That
outcome is a win and must be reachable — check before you start that your design can produce it.

### 2d. Which way does it point, and how much has to go right

The sign of the effect is set entirely by which arm is closer to the truth, and **neither premise is
established**. Quantify the exposure, outcome-free:

- The share of rows on which the candidate would have to be the closer arm for the crossed mean `Δ`
  to be positive at all. Report it as a fraction, and per market.
- `-09-77a` measured that the repair **changes the modal band on 196 of 368 rows** and is
  **sharper on 254 of 368**. Report `‖p‖² − ‖q‖²` per market and per window, and flag any market
  where the repair sharpens on a large majority of rows. Canon retired global sharpening once
  (`centre-not-width`), and `-09-59a` found the tail is centre overconfidence, so **a sharpening
  concentration is a reason to add a guard, not a reason to celebrate.**

### 2e. Repair the draft pre-registration — still a draft

Rewrite `docs/roadmap/observation-recovery-single-environment-preregistration-draft-2026-09-77a.json`
in place (or emit a `-2026-09-78a` successor and mark the predecessor superseded):

- Replace the `outcome_free_power_screen` block with the simulated-SE power calculation from §2c.
  **Remove `candidate_field_mde_at_80_percent_power` as computed from the ceiling's SE** — it is the
  dispersion of the wrong quantity.
- Add a **sharpening guard** to the accept rule alongside the mean improvement, so a win driven by
  narrowing cannot pass on the mean alone. Specify it concretely.
- Keep `status: DRAFT_NOT_FROZEN_ALPHA_UNALLOCATED_NOT_EXECUTABLE`. **Do not freeze it, do not
  execute it, do not allocate α.** The primary row formula `sum(q_k^2)-sum(p_k^2)+2*(p_b-q_b)` is
  already correctly oriented — keep it.

## 3. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **CLOSED UNUSED** and must not be reassigned.
- **Do not read a realized band, settlement, label or outcome.** Simulated bands are draws from the
  arms' own vectors and must never be joined to a real one. Emit `realized_band_read: false`.
- **No market comparison. B only, no C endpoint.** Never pool across `2026-07-31` (anchor
  `b77cfbed`).
- **Do not reproduce history.** No commit binding, no identity binding, no synthetic historical
  trees. That thread is closed.
- **Do not add Git LFS content.** No new bundles, no large binaries; the account exhausted its LFS
  quota once already. Artifacts here are small CSV/JSON.
- **Change nothing** in the working tree: not model, calibration, floor, producer, collection,
  scoring, serving or `model_identity.py`. **Never weaken the serving floor** (`1.6639 → 1.4980`).
- **DO NOT DELETE OR MODIFY ANY BRANCH.** Refs are read-only, full stop.
- Nothing under production `data/`. Disposable work under `scratch/`.
- `DELEGATION_CONTRACT.md` §2 in full. No provider or exchange calls, no promotion, activation,
  release or trading.

## 4. What would close this

- **Unpowered under the candidate's own premise** → we close a five-mission thread, keep 13
  allocations, and go back to the central goal: a better forecast from our own information.
- **Powered** → the operator gets a real number to allocate against, a guard against the failure
  mode canon already knows, and an honest statement that the sign rests on an unverified premise.

**What would not close it** is a third bound without a sign, or a screen whose NO-GO branch is
unreachable. Check your own design against that before you run it.

## 5. Environment, branch and report

Use the repository's existing Python 3.11. **Install nothing.**

- Branch: `codex/workstation-does-the-look-have-power-2026-09-78a`
- Report: `docs/roadmap/agent-report-2026-09-02-workstation-estimand-power-and-sign.md`
- Commit the harness and a versioned seed alongside the artifacts, with a `.sha256` receipt.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**

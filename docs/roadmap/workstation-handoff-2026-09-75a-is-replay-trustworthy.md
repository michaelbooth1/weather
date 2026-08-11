# Workstation handoff 2026-09-75a — is replay trustworthy, and on what?

Written 2026-08-11 by the production agent. Read on `origin/master` and execute.
**No α, no realized outcome, no market comparison, no C endpoint.** Direct continuation of
`-09-74a` (merged `8f7a408a`).

## 1. What `-09-74a` found, and the part of it that was my fault

`-09-74a` stopped where I told it to. On exact captured runtime `1dd68a4395bb`, 7 of 8 rows
reproduced at machine precision (max L1 `1.76e-16`) and **toronto `2026-06-17`
`20260617T000830-0400` missed by L1 `7.02e-3`** — seven billion times the `1e-12` tolerance, so not
a float boundary miss. The stop and the recommendation were both right, and I agree with them:
**do not allocate α while replay is blocked.**

Two things it surfaced that the verdict line does not carry.

**The corpus is not uniformly replayable.** Of the 163 control rows, **99 (60.74%)** carry a
captured runtime commit, **41 (25.15%)** have a model identity but no runtime, and **23 (14.11%)**
have neither — across **six** model versions. If the primary stratum binds at that rate, roughly
**40% of the pre-registered decision cannot be exactly replayed at all.**

**And the control tested nearly none of what the decision would score. That is my specification
error, not the agent's.** I defined the control as rows "the candidate does not change", which by
construction selects the *unrepaired* tail: **157 of 163 pre-dawn**, 135 `M2_empty_history`, 20
`M6`, 4 `M4`, and exactly **one** `M5` row. The decision's primary stratum is **366 `M5`
decision-window events**. An incumbent replay needs only captured inputs — **it does not require the
candidate to leave the row alone.**

So the honest state is: replay failed one row, on a population that was the wrong one to ask.

## 2. What to do

### 2a. Re-run the incumbent control on the stratum that matters

Population: the **366 `M5` decision-window events** of the `-09-73a` artifact (`peak_heating_window`
or `settlement_window`), replayed with **captured, unmodified inputs**. Add the 2 `M1` decision-window
events so the stratum is the full 368. **Do not touch the candidate anywhere in this mission.**

For every row report: runtime binding class, replayed-vs-recorded L1, max per-band error, and the
recorded and replayed active model kind. Report the match rate **per runtime commit, per model
version, per market and per window** — the aggregate rate alone is what hid this for two weeks.

**Do not stop on the first failure this time.** The point of the mission is the shape of the
divergence, so run the whole stratum and characterise it. Cap the work if you must, but say exactly
what you capped and why.

### 2b. Test the source-switch hypothesis directly — four rows

All four B `M4_source_switch` events are **toronto pre-dawn at ~00:08** on `2026-06-15`,
`2026-06-17`, `2026-06-19` and `2026-06-20` — one recurring nightly event, and the `-09-74a` failure
is one of them.

**My hypothesis, which I want tested and not assumed:** a source switch is exactly where a replay
could bind a different observation source than the live run did, so the divergence is a
*source-selection* difference rather than a model defect.

Replay all four. If all four fail and comparable toronto pre-dawn rows *without* a source switch
pass, that is strong. If they do not all fail, say so and abandon the hypothesis. **Then trace one
failing row end to end**: which source did the recorded run use, which did the replay bind, and at
what step do the two feature vectors first differ. **A grep is not a trace** — walk it.

Also separate the two candidate explanations that this row confounds: **toronto** (the only Celsius
market, with its own `toronto_model` path) versus **`M4`** (source switch). Replay non-`M4` toronto
rows and non-toronto rows in the same runtime to break the tie.

### 2c. Census the runtime binding across the whole population

Extend `-09-74a`'s binding census from 163 rows to **all 28,254 replay-supported B feature
snapshots** and to the 368-event stratum specifically:

| Report | For B overall and for the 368 |
| --- | --- |
| runtime-commit bound | count and share |
| model identity only | count and share |
| neither | count and share |
| distinct runtime commits and model versions | list with counts |

**This number sets the ceiling on any replay-based decision we could ever run**, so state it plainly
and put it where the pre-registration can cite it. If the 368 bind materially worse than 60.74%,
that is a finding in its own right and should lead the report.

### 2d. Verdict — a recommendation about replay, not about α

Close with one of:

- **`REPLAY_SOUND_ON_THE_DECISION_STRATUM`** — the 368 reproduce within `1e-12` at a rate you state,
  and the divergence is confined to a characterised class outside the stratum. `-09-74a`'s ceiling
  mission can then resume on the bound subset. **Say what share of the 368 is actually bound**, since
  that, not 368, is the real N.
- **`REPLAY_DIVERGES_ON_THE_DECISION_STRATUM`** — it fails inside the stratum too. Then replay-based
  scoring is not available to us at present, the frozen pre-registration is unexecutable for a
  reason that has nothing to do with the candidate, and **that is the finding.** Write it plainly.
- **`REPLAY_COVERAGE_TOO_THIN`** — reproduction is fine where it binds, but too little of the
  stratum binds for a decision to be worth α. Give the bound N.

**None of these authorises an α allocation, and none of them is about the recovery candidate.**

## 3. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **CLOSED UNUSED** and must not be reassigned.
- **No candidate anywhere.** No candidate probabilities, no displacement, no ceiling, no repaired
  inputs. This mission replays the **incumbent** on captured inputs only.
- **No realized outcome.** No Brier, CRPS, log loss, hit rate, calibration curve, settlement score
  or market price. Comparing replayed probabilities to *recorded* probabilities is not an outcome
  look; comparing either to settlement is. Emit `realized_band_read: false`.
- **B only. No C endpoint.** Never pool across `2026-07-31` (anchor `b77cfbed`).
- **Historical runtimes go in disposable worktrees**, as `-09-74a` did. **Print the resolved
  `__file__` of every model, calibration and feature module** and confirm the tree — a worktree that
  silently imports production modules has bitten us before.
- **Change nothing** in the working tree: not the model, calibration, floor, producer, collection,
  scoring or replay code. Nothing under production `data/`.
- **Never weaken the serving floor** (`1.6639 → 1.4980`).
- Native units per market; toronto is Celsius and does not pool with the F markets.
- `DELEGATION_CONTRACT.md` §2 in full. No provider or exchange calls, no promotion, activation,
  release or trading.

## 4. Why this is worth a mission

Every model-vs-market number this campaign has quoted rests on replay. If replay does not reproduce
what we served, the problem is far larger than one recovery candidate — and if it reproduces cleanly
on the decision stratum and broke only on a characterised nightly toronto source switch, we get the
ceiling mission back and lose nothing. **Both answers are worth having, and one of them is worth
much more than the α it protects.**

## 5. Environment, branch and report

The repo venv on that host points at a removed Python 3.11 — use the bundled Codex 3.12 runtime.
**Install nothing.**

- Branch: `codex/workstation-is-replay-trustworthy-2026-09-75a`
- Report: `docs/roadmap/agent-report-2026-08-30-workstation-replay-trust.md`
- Extend `-09-74a`'s harness; commit it and a versioned seed alongside the artifacts.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**

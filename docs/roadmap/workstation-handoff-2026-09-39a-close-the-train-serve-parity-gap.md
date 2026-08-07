# Workstation handoff 2026-09-39a — close the train/serve parity gap

Written 2026-08-07 by the production agent. Read on `origin/master` and execute.
**This blocks every candidate regardless of how the corpus question resolves. Nothing else is running.**

## 1. Goal

**Close the 24 unexpected train/serve parity blockers** — `wind_gust_kmh` and
`wind_shift_3h_degrees`, dropped at serve in **all 12 markets** — so the first retrained candidate
is not contaminated by features the trainer sees and the server does not.

## 2. Why this, and why now

Train/serve skew is **this project's dominant defect class**, and the parity gate is its standing
control. `-09-38a` re-ran it: **BLOCK, 220 blocking findings, 24 unexpected blockers.**

**Do not try to fix 220.** The decomposition matters:

- **196** are already-classified known defects, carried in
  `tests/fixtures/train_serve_feature_parity_known_defects_v0.1.json`.
- **24 are unexpected** — and 24 = **12 markets × 2 features**. Those two features are the mission.

A candidate fitted while these are dropped at serve learns on inputs it will never receive.
That is exactly the skew that has cost this project repeatedly, and it is cheaper to fix before a
candidate exists than to explain a candidate's behaviour afterwards.

## 3. Start from this — established, do not re-derive

- Both features appear in `model/model_features.py`, `model/feature_store.py`,
  `model/model_sources.py` and several `sources/*_history.py` adapters.
- **§4 already records that 8 of 29 trained inputs are dead at serve**, leaving ~28% of inputs
  permanently imputed, and that 10 of 19 base features read 0% at every hour in all markets.
  **P0 below asks whether these two are inside that 8 or additional to it** — the answer changes
  how bad §4 actually is.
- The corpus question is **closed and is not your problem**: the free tier can express a
  point-in-time corpus for `temperature_2m` and nothing else (§4f, 1 of 21 measured).
  **`previous_runs=` is a leakage trap** — it returns the settled analysis unchanged.

## 4. Prioritised work

### P0 — classify before repairing

For each of the two features, in each market, establish **why** it is absent at serve:

1. never produced by the adapter at serve time,
2. produced but dropped in the feature-contract/routing layer, or
3. produced under a different name or unit.

**These have opposite correct fixes**, and (3) is the dangerous one: it will look like absence and
"fixing" it by recomputing would create two subtly different values for one feature.

Report whether these two are among §4's 8 dead-at-serve trained inputs or additional to them.

### P1 — repair in the direction the evidence supports

**If a feature genuinely cannot be known at serve time, the correct fix is to remove it from
training — not to synthesise it at serve.** That is a legitimate and complete outcome; say so
plainly rather than manufacturing a value to make a gate green.

If it is a routing or naming defect, repair it so **serve produces the value the trainer saw**.
Parity is about *equality*, not *presence*: a differently-computed value passes a presence check
and fails parity in substance.

### P2 — size the serving change

Any repair here **changes what we serve**. Re-run the model over the replay corpus and report the
served-output delta — distribution centre, width, and Brier — with crossed date × market
clustering and power.

**Never weaken or bypass the serving floor** to make a number move. §3 records the floor as the
one shipped win, and centre displacement was traced to mass below it.

## 5. Method — binding

- **Crossed date × market clustering** on every comparison; report power. **"Not powered" is a
  valid verdict.**
- **Never pool across `2026-07-31`** (artifact provenance, anchor `b77cfbed`).
- Ledger rows are **not** market-days — deduplicate to `(market, target_date)`, then apply
  `promotion_countable`.
- `pytest -q` is **red on master** before you start — 4 unowned failures named in
  `STATE_OF_PLAY.md`. Diff against those.

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. Mission-specific:

- **Expect `roll_verdict.ps1` exit 3 (ROLL-SENSITIVE).** `model_features.py`, `feature_store.py`,
  `model_sources.py` and `sources/forecast_history.py` are all in the snapshot and
  observation-trigger closures — verified on the production host. The gate itself
  (`reporting/scorecards/train_serve_feature_parity.py`) is roll-free. This does not block you:
  production merges it in the 01:00–04:00 quiet window. **Pushing a branch never rolls anything.**
- **Do not edit the known-defects fixture to make the gate pass.** Reclassifying a finding is a
  claim about the world and needs its own evidence. If one of the 196 is genuinely misclassified,
  report it; do not silently move it.
- **Fit no candidate, promote nothing, collect nothing, make no provider call.** This runs on data
  already on disk.
- Do not write production `data/`, run the chain, or restart anything.
- Check `reserved-confirmation-window.md` at run time; it wins over this handoff.

## 7. What would falsify this mission

- **The features are genuinely unknowable at serve.** Then the fix is to drop them from training,
  and saying so is the result.
- **The 24 are not 12 × 2** — if they decompose differently, the premise above is wrong and the
  decomposition is the finding.
- **Repair changes served output materially**, or is not powered to show it doesn't. Report it and
  stop before anything ships; that becomes a serving decision, not a parity fix.
- **Some of the 196 "known" defects are not actually classified.** Then the gate's baseline is
  wrong and that is a bigger problem than the 24.

## 8. Branch and report

- Branch: `codex/workstation-close-the-train-serve-parity-gap-2026-09-39a`
- Report: `docs/roadmap/agent-report-2026-08-07-workstation-close-the-train-serve-parity-gap.md`

Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and a per-file roll
verdict from **`scripts\ops\roll_verdict.ps1 -Branch <branch>`** — do not derive it by hand.
**Commit and push whenever you finish.**

# MG-2 binding plan (DRAFT for master; lane L8, 2026-10-25)

**Superseded 2026-10-25** by the composite design and its plan: [binding-plan.md](../mg2-composite-binding-2026-10-25/binding-plan.md). Kept as history.

Status: a plan only. Nothing is bound. It follows master's ruling of 2026-10-24:
- MG-2 = lane L3's OLS + floor model (**arm A**), fed by the L8 serve-time `high_so_far`;
- **arm B**, kept for attribution, is the current HGB + the L8 `high_so_far`;
- both arms take MG-1's floor and calibration;
- MG-2 is bound with D0 = its first forward day;
- there is one Fable review of the serving/parity diff before landing.

L8's own locked rule did not bind anything: no arm beat MG-1 on the dev window (see the [README](README.md)).
The binding below rests on master's ruling, not on an L8 dev win. Arm B's dev result vs MG-1 was
+0.2232 [+0.1489, +0.2927] (worse).

## 1. Shared input (both arms)

- The `high_so_far` input is `weather.model.observed_running_max.running_max_since_midnight` (tip
  `f3b49fabb`, pinned by `tests/model/test_high_so_far_parity_shadow.py`).
- Arm A calls it on the captured `sources.station_observations.data` / `sources.metar.data` of each snapshot.
- Arm B gets it through `high_so_far_shadow_variant = "metar_running_max_since_midnight_v1"`.
- There is no second implementation.
- **Freeze:** the binding commit records the function file's sha256. Any change to the function re-opens the
  binding.

## 2. Arms

| | Arm A (MG-2) | Arm B (attribution) |
| --- | --- | --- |
| Centre / distribution | L3 OLS + floor (`weather.calibration.r0_ols_floor_challenger`, fit frozen on the Aug-Sep 2021-25 PIT corpus `b455bd53…`; coefficient file sha256 recorded) | current serving HGB pipeline (`artifacts/models/hgb/*` sha256 recorded) with the shadow switch on |
| high_so_far | shared function at the snapshot's effective cutoff | the same, via the switch |
| Floor | MG-1's: B = floor(max(rule-4 floor, running max) + 0.5); the dev result shows the running max never raises the rule-4 floor (0 of 83,801) | the same |
| Calibration | MG-1's (none beyond the floor mask) | the same; the HGB pipeline's own stages stay as served |
| Fallback | served vector when the forecast input or an observed row is missing (counted, never filled) | the same |

## 3. Forward capture and scoring

- **Captured-input replay at a frozen hash** (the MG-1 pattern): both arms are computed from each forward
  snapshot's `replay_inputs.jsonl` on the workstation. This needs no capture-host serving change. The scorer
  is `weather.calibration.high_so_far_parity_shadow` (`emit`; arm A needs an `emit` arm that calls L3's
  predictor), at the bound commit.
- **D0** = the first local target date after the binding commit lands. A reserved window for MG-2 at narrow
  scope (MG-2-family candidates only) is dated in `docs/operations/reserved-confirmation-window.md`, in the
  same commit as the D0 / last constants and their test (the MG-1 / OD32 mechanics).
- **Needs a ruling:** MG-1's window (10-15..11-28) is held only against NBM-guidance-to-band candidates.
  Arm A must read no NBM band guidance. MG-1's rule-4 floor contains `guidance_physical_floor`, which reads
  guidance sources; confirm that this does not put MG-2 inside MG-1's reservation.
- **Primary:** R over 00-16 against MG-1 and served, with date-clustered intervals; 07-12 and every hour are
  reported. The pre-registration is written and signed before D0, using `prereg_check` sections (a)-(e).
- **Positive control first:** the first forward week must reproduce arm B's base-replay L1 = 0 on
  unchanged-input rows, and the served-vector control.

## 4. Landing and roll class

- **Diff for the Fable review:** `git diff 87af8ed8b..<tip> -- src/weather/model/` (`model_base.py`,
  `model_features.py`, `model_distribution.py`, `observed_running_max.py`). It is shadow-only; with the switch
  off, production stays byte-identical (`test_production_path_is_unchanged_and_never_reads_the_shadow`).
- **ROLL-SENSITIVE.** The three model files are in the capture closure (`snapshot_tracker` →
  `toronto_model`). Master runs `scripts\ops\roll_verdict.ps1 -Branch claude/high-so-far-parity-shadow-20261024`,
  and landing is in the 01:00-04:00 quiet window via `quiet_window_merge.ps1`.
- The research module, allowlist entries, docs and the `.ps1` / `.codex` changes are roll-free.
- **Arm A's L3 module:** the import must stay outside the capture closure, and arm A is only ever run
  offline. Land it as its own roll-free head after a closure check.
- **Release binding:** the binding row records the code sha, function sha256, HGB artifact hashes, L3
  coefficient hash, rule sha256, D0 and the provisional last date.

## 5. Open items for master

1. MG-2's reservation scope vs MG-1's (section 3).
2. Arm B shows afternoon harm at 15-17 h (training-exact parity drops the h:52 report after the cutoff).
   Should arm B stay strictly training-exact (as pre-registered), or should a separate "union" variant be
   pre-registered? It would be a new candidate and a new ledger row.
3. Ledger row 19 (`DEV_WINDOW_LEDGER.md` on `claude/loss-atlas-prereg-20261024`) needs filling: K, L8, rule
   `55cf6989…`, 00-16 fix − base −0.0088 [−0.0171, −0.0008] (date) / [−0.0232, +0.0058] (crossed); vs MG-1
   +0.2232; KEEP vs base, NOT BOUND by L8's rule.

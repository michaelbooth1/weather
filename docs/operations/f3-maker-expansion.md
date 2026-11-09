# F3 maker expansion engine runbook

Status: draft runbook. Read when implementing or preparing F3-SIM-1 on the workstation.
Owns module routing, inputs and reproducibility. [Protocol](F3_SIM_TRIAL.md) owns the trial;
[rollout](F3_ROLLOUT.md) owns gates; [prereg](../research/f3-sim-trial-2026-11/PREREG.md) will bind values.
Engine packages and configuration described below are planned WP interfaces until phase B verifies their merged code.
This phase ships a thin router; missing packages return 4. Do not run a trial from a development worktree.

## Architecture and module owners

Verified packs → `f3_inputs` → `f3_sim(f3_policy, envelope, cost table, prereg)` →
`sim_band_day_v1` / `sim_portfolio_day_v1` → governed sealed accrual → scoring / looks.

| Module / surface | Producing WP | Responsibility |
|---|---|---|
| market.f3_policy / f3_types | WP-01 | pure policy and F2-parity capital gates |
| backtesting.f3 | WP-02/WP-12 | prereg, scope reader, claimants, read log, freeze, looks, scoring |
| backtesting.f3_cli | WP-05 | lazy routing and candidate policy export |
| backtesting.f3_inputs | WP-06 | pack adapter and adapter-parity receipt |
| scoring.response_envelope | WP-07 | fit and US validation, cell transfer |
| evidence replay / capture | WP-08/WP-09/WP-13 | discovery, terms, books, heartbeats and trades |
| backtesting.f3_sim / f3_rewards | WP-11 | portfolio simulation and economic accounting |
| evidence packs / workstation wrapper admission | WP-14 | sealed manifests, verification, pinned reader |
| backtesting.f3_accuracy / bridge | WP-15 | gate and allowlisted aggregate bridge exports |

## Configuration

WP-01 owns `config/f3/f3_policy.example.json`, `config/f3/strata.json` and
`config/f3/nwp_release_schedule.json`. The example is never the frozen policy.
The candidate policy reads F2's frozen `policy` block, including its offset and sleeve-loss basis.
The strata map pins city-family keys, geographic clusters and the transfer grid. Freeze pins every file hash.
Phase B must reconcile the policy wire serializer and canonical hash with WP-01's merged F3Params.

## Inputs and replay rule

WP-14 verifies `trial_input_pack_v1` manifests and day seals before the WP-06 adapter opens an admitted family.
The manifest supplies reader version, tzdata, config hashes, clock offsets, exclusions and coverage.
VR-11 Tier A books supply executable YES depth; NO mirrors YES subject to the hourly mirror guard.
VR-5 pagination must be complete; missing trade coverage excludes and counts the affected CFD.
VR-3 closed rows supply venue resolution. Reconstructed weather labels are not payouts.
The adapter appends one read-log row per opened family/day; coverage-only opens only coverage-class inputs.

The sole replay implementation is `weather.evidence.replay` (WP-09), or its exported minute_state rows.
At t, use the latest successful token heartbeat attest h ≤ t; missing attest/row or a stale attest means unknown.
Read the latest book row received by h. Tier A staleness is 90 s, Tier B 330 s; sample minutes at +30 s.
No unknown minute is carried forward. Terms require first_seen ≤ t. Input latency adds its own frozen bound.

## Envelope

WP-07 detects public analog entries on admitted calibration inputs, fits per cell, validates held-out entries and
checks US session transfer inside the LFC lane. Unvalidated cells earn zero. Fit/dose/validation outputs are
create-only. Freeze pins shape, counts, held-out ratios, file hash and US validation; every look reports cell rewards.

## Simulator

WP-11 runs an as-of, multi-condition portfolio over T1 primitives, with no network or clock reads.
Mode `trial` is not exposed on the simulate CLI; trial-date runs occur only under governance look admission.
Command replay is exposed only through accuracy. Decision-time selection, capital gates and event order
must reproduce across two runs of three pack days. Rewards are per account-day primary; unresolved sensitivity,
per-condition threshold and strict queue remain diagnostics. Excluded CFDs keep their capital effects.

## Accuracy gate and LFC bridge

WP-15 replays the same adapter pipeline as the trial; older sessions require adapter parity.
Only allowlisted aggregate bridge/gate receipts leave the LFC lane. The bridge supplies k, m, cost reserve,
latency p95 and payout-unit evidence. Binding confirmation reads begin only inside the final look window.
No raw session records are needed by this runbook or this docs mission.

## Commands

The following router commands exist on this branch; their delegates may be absent.
Help for a delegated command also returns 4 when that package is absent. These calls do not authorize a data read.

```powershell
python -m weather.backtesting.f3_cli --help
python -m weather.backtesting.f3_cli policy-from-f2 --f2-freeze <explicit-freeze-receipt> --f2-git-sha <40-hex> --out <new-candidate-path>
python -m weather.backtesting.f3_cli adapter-parity --help
python -m weather.backtesting.f3_cli envelope --help
python -m weather.backtesting.f3_cli simulate --help
python -m weather.backtesting.f3_cli accuracy --help
python -m weather.backtesting.f3_cli bridge --help
```

Use the project interpreter from the repository root. Candidate export creates a new file only;
it never freezes or promotes a policy. Its `policy_sha256` is SHA-256 of canonical sorted compact UTF-8 JSON
before the output's final LF; decimal values are strings. The F2 policy-block hash includes the final LF,
preserving F2's `Campaign.sha256` contract; a supplied receipt policy hash must agree. The F2 freeze-receipt
hash binds the original bytes. Phase B reconciles the candidate serializer/hash interface with WP-01.
On an isolated workstation scratch directory an explicit new output path is required; no ignored data path is presumed.

Planned governance sequence (command shorthand until WP-02's package entry point lands):

1. `f3 claimants --prereg <PREREG.md> --scopes calibration` before calibration.
2. Validate admitted calibration packs; adapter parity → envelope → simulator determinism → accuracy/bridge → killtest/power.
3. `f3 claimants --prereg <PREREG.md> --scopes trial`, then the freeze checks on the integrated run branch.
4. `f3 freeze --trial F3-SIM-1 --prereg-md <PREREG.md> --landing-commit <40-hex> --check-only` before the master landing.
5. After landing and actual freeze receipt: `f3 accrue --trial F3-SIM-1 --date <YYYY-MM-DD> --coverage-only --pack-root <dir>`.
6. `f3 status --trial F3-SIM-1` and `f3 read-log --trial F3-SIM-1 --verify` for counts/integrity.
7. At an admitted window: `f3 look --trial F3-SIM-1 --look <look-id> --pack-root <dir>`, then replay check and verdict.

Phase B replaces this plan with the merged delegates' verified flags and WP DOC TEXT.

## Reproducibility and retained artifacts

The master maintains `codex/f3-run-20261113` by merge commits from production, T1sim, engine, governance and WP-14b.
Its tip and append-only log are pinned by the prereg. Verify the three-way universe-tag agreement on that run tree.
All runtime receipts and sealed outputs are create-only under the explicit WS trial root; retain pack seals,
input hashes, engine digest, read chain, accrual manifests, look receipts and replay-check hashes. Never clean evidence.

## Load rules and invariants

Follow [host load policy](HOST_LOAD_POLICY.md) and the session handoff before running anything.
Heavy work requires `scripts/ops/workstation_heavy.ps1 -Kind weather_heavy` and WP-14's module admission;
never during a live stage, nor after 08:30 until the session ends (about 15:30) on F2 entry dates.
The WP-05 phase-A mission is light only: at most two test files per call, serially, with explicit basetemp;
no full suite, compileall or heavy-wrapper job. Pause at commit charge ≥90%, resume below 85%.
Agents never place, cancel or sign orders. This package changes no F2 bytes and imports no `lfc_*` module.

## Update this file when

Update alongside merged module signatures, configuration/wire contracts, replay semantics or wrapper admission.
Phase B must verify actual help and schemas before claiming an executable end-to-end procedure.

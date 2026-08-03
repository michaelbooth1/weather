# Workstation handoff 2026-08-30a — prove, then repair, exact WU parity

Run this now. **Proof first, implementation only if the proof holds: no fit, no retrain, no
candidate, no fresh dates, no merge.** `-08-16a` remains queued for 2026-08-05 04:30.

## Why this one, now

Your own `-08-28a` sequencing put it first: *"Implement and gate exact WU regression restoration
first. It repairs an active serving defect and establishes the observation feature contract the
retrain must reproduce."* I agree, and `-08-29a` did not change that — it made the forecast corpus a
prerequisite too, but a slower one.

This is also the older wound. WU availability broke at commit `5735b573` on **2026-06-30 12:16:08
EDT**, and `-08-20a` confirmed on the direct serving path that **28,680 / 28,680** affected feature
cells are train/serve skew: the artifacts were fitted with those fields populated and serve with them
absent, median-imputed into plausible-looking values the model cannot tell are fake.

## 1. Prove the condition before building anything

`-08-21a` said Phase R *may* be no-refit, but **only** if it proves identity with the artifact-era
path. That condition has never been tested. Test it first, and be willing to come back with "it does
not hold."

Prove or disprove, field by field, that a **public** WU-history path reproduces the artifact-era
contract on: payload shape, station identity, units, row normalization, and point-in-time
availability at the row's cutoff.

Three traps `-08-21a` already found, which I want explicitly re-verified rather than assumed:

- **The feature names lie.** `dewpoint_c` is native C *or* F depending on market. `wind_speed_kmh` is
  km/h in metric markets and **mph** in English ones. `pressure` follows the WU response unit — hPa
  metric, inHg English. **Preserve artifact-era units regardless of what the column is called.**
- The **July 2 free-station fallback** retained only temperature and current max, so it is not
  evidence of a working contract for the other fields.
- **No paid-provider change.** `fetch_wu_history()` and `fetch_wu_current()` fail before the network
  with `paid_provider_disabled` and that stays true. If exact parity is only reachable through the
  paid endpoint, then Phase R is blocked and the answer is the explicit METAR/ECCC retrain-contract
  decision instead — say so plainly and stop.

**If the condition fails, stop and report.** A proven "no-refit is not available" is a good outcome
and I would much rather have it than a repair that silently needs a retrain we cannot yet run.

## 2. If it holds, implement it

Restore the fields so that **serving matches what the artifacts were fitted on**. This is a serving
change, so it is built here and gated later — do not treat it as shippable on merge.

Requirements:

1. A parity receipt that compares **values, units, categories and missingness** for every restored
   field, from the same captured payload, at train and serve. A boolean replay receipt is not
   sufficient — that is exactly what failed to catch this for two months.
2. Explicit point-in-time behaviour: no field may become available to a row earlier than it would
   have been in production.
3. Fail closed. If a field cannot be reconstructed to the artifact-era contract, it stays missing
   and is reported — it does **not** fall back to a plausible-looking substitute. Median imputation
   of an unavailable field is how this defect stayed invisible.

## 3. Say what it is worth, honestly

`-08-22a` measured blinding these fields as costing **+0.009899 overall / +0.008210 excluded, both
intervals crossing zero**, and moving the excluded-lane centre *warmer* — the opposite direction from
our defect. So do not sell this as a model-quality win.

What survives is narrower and worth restating in your report: restoring cuts blind-defined
severe-tail error **12.77% overall / 15.23% excluded**, concentrated in **pressure, rise_from_7am,
dewpoint**. And it is a correctness defect worth fixing on principle regardless of the score.

Tell me which of those two framings your evidence actually supports.

## What I want back

1. Does exact public-WU parity hold? Field by field, with the three traps re-verified.
2. If yes: the implementation, the parity receipt, and the tests — on a branch.
3. If no: exactly which fields fail and why, and whether that forces the METAR/ECCC retrain contract.
4. An honest statement of what the repair is worth, per the framing above.
5. Which files you touched are roll-sensitive under `SOURCE_PATTERNS`.

## Sequencing

Build only. This does not merge until after release #1 is built and the lock window closes, and it
needs the full serving gate when it does. Do not touch the release path or the parity gate itself —
the build window opens tomorrow and I want that code still.

## Constraints — unchanged

- Base on `master` @ `b804513e`.
- **Do not read, enumerate, evaluate, or substitute 2026-07-27 → 07-31, 2026-08-01 → 08-03, or
  2026-08-06 → 08-19.**
- **No paid-provider change, and no paid endpoint call.**
- **Do not fetch, backfill, refresh, or write any archive, artifact, sidecar, prior, or cache.**
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, scheduler change, capture restart, PR, merge, or master push.
  **No** mirror topology change, **no** ACL change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. The answer I need first is question 1 — if
no-refit parity is not available, everything downstream of it changes shape and I would rather know
before the build window closes than after.

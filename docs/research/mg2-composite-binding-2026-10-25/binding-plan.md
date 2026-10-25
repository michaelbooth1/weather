# MG-2 composite binding plan

- **Status:** DRAFT. Master APPROVED the design on 2026-10-25. The binding commit and D0 wait for the
  single Fable review, which the coordinator relays.
- **Rule:** [rule.md](rule.md) (draft sha256 in the record line of the coordinator report). The rule
  owns every definition.
- **Purpose of this plan:** how the binding is executed, what it reads, and what is pending.
- **Supersedes:** [the L8 draft plan](../high-so-far-parity-shadow-2026-10-24/mg2-binding-plan.md).
- **Dev numbers are selection evidence only.**

## 1. Design (fixed by the coordinator)

The composite switches on local hour, fixed at 13.

- **Before 13:00 local:** MG-1 plus lane L6's own-obs stack.
- **From 13:00 local:** arm A, L3's OLS + floor, fed by L8's
  `weather.model.observed_running_max.running_max_since_midnight`.

**Inherited from MG-1:**
- **Floor:** the rule-4 mask.
- **Calibration:** none.
- **Fallback:** MG-1 falls back to served.

**Scoring:** forward scoring is by captured-input replay at frozen hashes. No capture-host serving
change is made.

**Sources merged into this branch:**
- `claude/stack-l5-20261025` @ `505f35ffd` (G, B2, L6, L1, L7, L5);
- L8 `f6ee3351e`;
- L3 `eaed66d6a`.

All three were full merges; the allowlists, shard lists and findings were resolved as unions.

## 2. The MG-1 reservation: option 3 now, option 2 adds only the read clause

**Quoted clauses (rule §4.1 carries the same text).**

The reservation scope row, in `docs/operations/reserved-confirmation-window.md` and the MG-1
pre-registration §7:

> Reserved **only** against reading or modifying the morning guidance-read (forecast-scoring) family: do not score, enumerate outcomes for, or join to an outcome the MG-1 vector or any other candidate that reads NBM station guidance into band probabilities (including the held RV-1 and HG-1), do not substitute reserved dates for such a candidate, and do not modify MG-1, without a new explicit owner decision.

The MG-1 pre-registration §6:

> **Window leakage:** before the look, any MG-1 vector or any morning guidance-read-family candidate was joined to an outcome (winner, settlement or Brier) on a reserved date, or MG-1 was modified (§7 scope). Uses §7 leaves untouched do not void the look.

The MG-1 pre-registration §5:

> **One look**, after the 45th counted date has settled. No interim outcome look.

**MG-2 is in the reserved family.** It reads NBM in three places:
- before 13:00, MG-1's centre and spread;
- every hour, `guidance_physical_floor` in the rule-4 floor;
- after 13:00, the MG-1 fallback.

Every gate is also against the MG-1 vector.

**Option 3 (now).** Accrue outcome-blind from D0. The four checks below are the ones the scope row's
exemption names: "outcome-blind operational checks (coverage, PIT, replay reproduction, parser version)
are permitted".

| Step | What it does |
| --- | --- |
| `emit` | Captured-input replay at the frozen coefficients. Reads `inputs_snapshots.parquet` and `inputs_bands.parquet` only, and refuses label or market columns. |
| `check` | Coverage ≥ 90% of 00-16; PIT; replay reproduction to 1e-12; parser version 2. |

`score` refuses any date on or before `MG1_LAST` unless the rule carries a dated owner decision id
(test-pinned).

**Option 2 (pending the owner).**
- **Trigger:** a dated Clarification sets `owner_decision_id: OD-YYYY-MM-DD-<slug>`.
- **Effect:** one look, strictly after MG-1's.
- **Scorer guard:** it also needs an MG-1 look receipt and a closed recorded window.
- **Nothing else changes.**
- **Not this lane's edits:** the reservation file and DECISION_LOG are the owner's.

## 3. N, MDE and read dates for both branches

- **Gate:**
  - G1: Δ(00-16) upper bound < +0.0010 (non-inferiority);
  - G2: Δ(13-16) upper bound < 0.
- **Interval:** fixed-market, date-clustered 95%, one-sided α 0.025 each.
- **N:** 45 countable dates in either branch.
- **Variance:** taken from the dev window (43 dates × 11 markets).

| | Branch 2: owner exemption | Branch 1: post-window fallback |
| --- | --- | --- |
| Start | D0 = first target date after the binding commit | first target date after `MG1_LAST` (today 2026-11-29; moves later with it) |
| 45th date (all countable) | D0 + 44, e.g. 2026-12-11 for D0 = 2026-10-28 | 2027-01-12 today |
| Earliest read | the later of the 45th date's settlement and MG-1's completed look; e.g. 2026-12-12 | the 45th date's settlement; 2027-01-13 today |

Both branches have the same MDE and power:

| Gate | MDE80 | Power at the dev point | Power at half the dev point |
| --- | ---: | ---: | ---: |
| G2 (13-16) | 0.0060 | 0.998 | 0.683 |
| G1 (00-16) | 0.0022 | > 0.999 | 0.951 |

G1's power at zero effect is 0.247. N = 60 would give G2 0.80 at half the dev effect, 15 dates later.

The branch is fixed before any read: Branch 2 holds only if the owner decision is recorded before
MG-1's look completes. Exactly one look in either case.

## 4. Measures beside the gate

Each half is reported separately against MG-1:
- **Pre-13:** Δ(00-12) and Δ(07-12).
- **Post-13:** Δ(13-16) and Δ(17-23).

Also reported: per hour, per-market signs, dR and the crossed interval.

## 5. Clarification clause

A′ may replace arm A in the post-13 slot through a dated Clarification before D0, with its coefficients
re-frozen and hashed. A′ is the historical fit on L9's pending PIT NBM corpus. After D0 nothing changes,
except the §2 owner-decision Clarification, which changes permission only.

## 6. Input overlap with MG-1

Rule §9 has the table. In summary:

- **Before 13:00:** MG-2 reads MG-1's NBM v2 centre and spread.
- **Every hour:** both use the identical rule-4 floor, including `guidance_physical_floor`.
- **After 13:00:** MG-2 reads NBM only through the fallback. Its own inputs there are the METAR /
  L8 running max and Open-Meteo `gfs_seamless` `previous_day1`.
- **Free fetches, not captured:** two inputs are later free fetches:
  - IEM own-station observations, for the L6 nowcast;
  - Open-Meteo Previous Runs, for arm A's forecast_high.

  Their PIT safety rests on gating, and this is disclosed.

## 7. Release binding

At the binding commit, `release-binding.json` records:
- the commit sha;
- the sha256 of each file in `mg2_composite.RELEASE_FILES`;
- the function sha256 `bd05d6d601b9c588…`;
- the coefficients sha256 `e29a1b28aec50e97…`;
- the rule's raw sha256.

`emit` (forward) and `score` refuse on any mismatch.

The coefficients file is runtime state, kept local at `C:\t\mg2\freeze\mg2_coefficients.json`. Its hash
is in the rule. It is not committed, under the repository's data and artifacts rule; it is regenerated
byte-identically by `freeze`.

## 8. Operations from D0 (option 3)

Daily or weekly, all through `scripts\ops\workstation_heavy.ps1`:

1. **Build the forward inputs-only layout.** The layout is snapshots and bands from the captured
   replay inputs. It needs the same harness as `C:\swarm\v3layout`, without labels or market files, and
   must expose the parser version.
2. **Fetch free forward inputs.** These are the IEM own-station observations and the Open-Meteo
   Previous Runs `gfs_seamless` `previous_day1`. Each is published content-addressed.
3. **Run the steps in order:**
   - `mg2_composite nowcast` (frozen refit; the dev-window control must reproduce `d2453d0d…`);
   - `emit`;
   - `check`.

   Results go under `C:\t\mg2\forward\<date>`.

No outcome, label, price or market file is opened before the look.

## 9. Roll class

The branch is **ROLL-SENSITIVE**. It carries L8's `src/weather/model/model_base.py`,
`model_features.py` and `model_distribution.py` edits. Those files are in the capture closure through
`snapshot_tracker` → `toronto_model`. The edits are shadow-switch only and production is
byte-identical, but the files change.

This lane's own additions are roll-free:
- `src/weather/calibration/mg2_composite.py`, imported by nothing in `src/` or `app/` (test-pinned);
- the tests;
- the allowlists (`.ps1`, `.codex`);
- the docs.

Run `scripts\ops\roll_verdict.ps1 -Branch claude/mg2-composite-binding-20261025` on the capture host for
the mechanical verdict. On this workstation it cannot read the supervisors' closure evidence.

**Binding needs no merge.** The forward accrual runs from this branch on the workstation. A landing
can wait for a quiet window.

## 10. Open items

- **Fable review, before the binding commit and D0.** Scope: the diff of the base `505f35ffd` against
  this branch's head, for these files:
  - `src/weather/calibration/mg2_composite.py`
  - `tests/calibration/test_mg2_composite.py`
  - `tests/operations/test_mg2_composite_admission.py`
  - `docs/research/mg2-composite-binding-2026-10-25/`
  - the allowlist lines

  Reading the merged L8 and L3 code is optional context.
- **Owner:** the option 2 exemption, or Branch 1 by default.
- **Retrain-window overlap.** The retrain window is armed, not dated. If it is declared and arm A is
  ruled a retrain-family candidate, MG-2's post-13 slot overlaps it. This needs an owner ruling.
- **Forward layout builder.** It must expose the v2 parser version. Without it the parser check fails
  closed (`UNVERIFIED`) and the look is void.

# Workstation handoff 2026-09-68a — is Gate 3 satisfiable on any panel we can build?

Written 2026-08-10 by the production agent. Read on `origin/master` and execute.
**No α, no candidate, no fitting, no protocol change.**

## 1. What I found on production after `-09-67a` landed

`-09-67a` is **verified and correct**, and it closes the instrument audit: the labels are flat, the
gap is real. Every population figure reproduced here, and two structural identities confirm you
scored the verified `-09-66a` surface — C's bucket Briers weight-average to exactly
`G = 0.021135322`, B's to exactly `0.015784384`.

Then I traced the Gate 3 stop through the production functions themselves.

> **`-09-63a` retired decision 10 citing denver `2026-06-08`, snapshot `20260608T030552-0400`,
> realized band `82-83°F`, "incumbent probability on winner `0.0`".**
>
> **Production served `0.5206313021` on that band** — the modal band of an eleven-band book summing
> to exactly `1.0000000000`. The `0.0` came from the replay's reconstructed floor of `91`.
>
> ```
> hard_floor_probability('eq', 82, 91, value_hi=83) = 0.0     # replay floor
> hard_floor_probability('eq', 82, 68, value_hi=83) = None    # the floor we served
> ```

And the survivor count does not reconcile. `apply_band_postprocessing` returns the hard floor's
`0.0` **before** `clip_probability`, and `clip_probability = max(1e-6, …)`. **An exact `0.0` has
exactly one possible origin: the hard floor fired.** (That is also why `-09-64a` found nothing in
`(0, 1e-6)`.) A zero therefore requires `served_floor_bucket > settlement_high`, and **only two B
rows in the panel satisfy that**:

| Market | Date | Snapshot | Local | Served floor | Settled |
| --- | --- | --- | --- | ---: | ---: |
| chicago | `2026-06-14` | `20260614T011002-0400` | 01:10 | `70` | `69` |
| san-francisco | `2026-06-09` | `20260609T170137-0400` | 17:01 | `68` | `67` |

You report **three**. Full detail in
`docs/operations/GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md`.

## 2. What to measure

### (a) Reconcile the third survivor — I predict it is a fallback row

`rescore_served_floor_09_66a.py` lines 726–730 retain the replay's baseline floor wherever
`served_floor_bucket` is absent. **1,353 of the 12,289 panel snapshots (11.01%) have no served
floor** — `high_so_far` was empty in production, including a fleet-wide outage `2026-06-28 → 07-01`.
On those rows production applied **no floor at all**.

From your retained `rescored-snapshot-rows.csv`, name all three B snapshots with
`served_floor_realized_zero = true`, with their `served_floor_bucket`. **State plainly whether the
third has a blank bucket.** If it does not, my deduction is wrong and I want to know that first —
report it and stop.

Also confirm from your own retained surface that denver `20260608T030552-0400` carries
`0.5206313021` (or its binary64 neighbour) on the realized band under the served floor.

### (b) The question that actually matters: is Gate 3 satisfiable?

Gate 3 fail-closes if the incumbent assigns zero to **any** realized B winning band. Given (a), a B
zero occurs iff the served floor exceeds the settled high on some snapshot. That is a property of
**the floor's error rate, not of any candidate**. So:

| Readout | Detail |
| --- | --- |
| **Per-snapshot rate** | share of B snapshots with `served_floor_bucket > settlement_high` — I get `2 / 10,936`. Reproduce it |
| **Per-market-day rate** | the same at market-day granularity, with a crossed interval |
| **Expected zeros vs panel size** | under that rate, the expected number of B realized-band zeros for panels of 100 / 500 / 1,000 / 5,000 market-days, and **the probability Gate 3 fires** at each |
| **The break-even** | at what panel size does `P(Gate 3 fires) > 0.5`? Above `0.95`? |
| **C for contrast** | the same rate in C (I get 1 row: seattle `2026-07-16`) |

**If Gate 3 fires with high probability on any panel large enough to power the test, then the gate
as frozen is not a quality bar — it is a size limit, and no future re-registration should reuse it
unchanged.** That is the finding I am after, and it is decidable without a candidate.

### (c) Bound the damage, so nobody over-reads this

For the two real rows, report the incumbent's **pre-floor** probability on the realized band (I get
`0.0146275224` and `0.0001434313`) and what B's Brier would be if those two snapshots were dropped.
**Label it a sensitivity check, not a result** — it licenses no exclusion rule.

## 3. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  **Decision 10 stays RETIRED and must not be reassigned** — re-registration needs a new slot and is
  an operator call, not yours and not mine.
- **Do not amend, reinterpret, or re-run the frozen protocol beyond its integrity pass.** Changing a
  pre-registered rule after seeing which row failed it is exactly the fishing pre-registration
  exists to prevent. If you think the gate should change, **say so in prose and change nothing.**
- **No fitting.** No β vector, no Gate-1/Gate-2 computation, no C endpoint, no candidate.
- **Never weaken the serving floor and never add epsilon mass.** `-09-63a` was right to refuse.
- **Do not propose changes to `high_so_far`, collection, or settlement.** I have an open production
  question there (`high_so_far` is not monotone; the mechanism is *not* established) and the data
  lives here.
- **You may read C** for the contrast rate only, on the same grounds as the last four: no candidate,
  no fitted parameter, no accept rule. **Say so explicitly.**
- **Never pool across `2026-07-31`** (anchor `b77cfbed`). `DELEGATION_CONTRACT.md` §2 in full.

## 4. Both answers are worth having

- **Gate 3 fires on essentially any usable panel** → the gate is a size limit, the PIT test cannot
  run in this form, and the operator needs that stated plainly with the numbers before deciding
  anything about a new slot. **This is what I expect.**
- **Gate 3's firing rate is low enough that a powered panel usually passes** → then the `-09-63a`
  stop was bad luck on a small panel rather than a structural block, which is equally worth knowing
  and points somewhere quite different.

Either way: **do not conclude that decision 10 should be reopened.** That is not this mission's call.

## 5. Environment, branch and report

Repo venv points at a removed Python 3.11; use the bundled Codex 3.12 runtime. Install nothing.

- Branch: `codex/workstation-is-gate-3-satisfiable-2026-09-68a`
- Report: `docs/roadmap/agent-report-2026-08-23-workstation-gate-3-satisfiability.md`
- Commit the harness and seed.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**

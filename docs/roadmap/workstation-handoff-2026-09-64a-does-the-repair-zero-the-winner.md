# Workstation handoff 2026-09-64a — how often does the REPAIRED surface zero the realized band?

Written 2026-08-10 by the production agent. Read on `origin/master` and execute.
**No α, no candidate, no C model. This audits the panel every campaign number was computed on.**

## 1. Why this outranks everything else queued

`-09-63a` stopped because the repaired surface gave probability `0.0` to Denver `2026-06-08`'s
realized band. **Production served that same band `0.5206`.** Traced directly on the host — the two
surfaces disagree, on the winner, by half the distribution.

I then measured the served side across the sealed window: **1,017 of 100,040 snapshots (1.017%),
20 of 663 market-days, 11 of 12 markets** publish exactly `0.0` on the band that settles. Mechanism
and natural control are in `docs/operations/SERVED_BAND_FLOOR_DEFECT_2026-08-10.md`.

**The repaired surface has never been checked the same way. It is the surface that produced §1c,
§1d, §1f, §1g and all seven spent decisions.**

> **A zero on the realized band is the maximum possible Brier contribution.** If the repair injects
> them at a materially higher rate than serving does, then the incumbent's measured Brier is
> inflated by an artifact, and **part of "we lose to the market" is something we did to ourselves in
> post-processing.** That would not be a small correction — it is the denominator of the whole
> campaign.

**I am not asserting that. It is the hypothesis, and it is cheap to settle.**

## 2. What to measure

You hold `paired-band-rows.csv`, SHA-256 `4352e776…`, D=50, M=12, 135,179 band rows. For every
snapshot, take the band with `outcome == 1` and read `repair_probability`.

| Readout | Detail |
| --- | --- |
| **Exact-zero rate on the realized band** | count, share, and the spread across markets and dates |
| **The empty-interval check** | how many land in `(0, 1e-6)` — served had **zero** there, which is what made it a hard rule rather than a tail |
| **Same for the control probability**, if the file carries one | tells you whether the repair or its input introduced it |
| **Fahrenheit vs Celsius split** | Toronto is 1-degree bands and was the natural control on the served side: 1 occurrence against 1,016 |
| **Brier attribution** | total incumbent B and C Brier, and **how much of it comes from realized-band zeros alone.** State it as a share of the C gap `G = 0.021135322` |

Then the question that matters:

- **Does the repair produce MORE exact zeros than serving's 1.017%?** If yes, by how much, and is
  the excess concentrated on the same market-days.
- **What happens to the incumbent's gap if those rows are excluded?** Report it as a *diagnostic*,
  clearly labelled — **not** as a corrected result and **not** as a candidate. Excluding rows changes
  the estimand; you are sizing an artifact, not fixing one.

## 3. Constraints

- **This spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **closed unused** — `-09-63a` retired it, and it must not be reassigned.
- **You may read C here.** This is not a candidate evaluation: there is no candidate, no fitted
  parameter, no endpoint comparison and no accept rule. It is an audit of the panel's own integrity.
  **Say so explicitly in the report** so nobody later mistakes it for a spent look.
- **Never pool across `2026-07-31`** (anchor `b77cfbed`). Report B and C separately.
- **Do not propose a repair fix.** Identifying the loss point is production work — the data lives
  here. Measure the size and the shape; leave the code alone.
- `DELEGATION_CONTRACT.md` §2 in full. No provider or exchange calls, nothing under production
  `data/`, no promotion, activation, release, or trading. **Never weaken the serving floor.**

## 4. What would falsify the hypothesis

- **The repaired rate is at or below 1.017% and the zeros sit on the same market-days as serving's**
  → the repair inherited the defect rather than adding one, the campaign's numbers stand, and this
  closes as a precise null. **Write that down; it is as valuable as the alternative.**
- **The zeros carry a negligible share of the gap** → then the artifact is real but immaterial, and
  §1c–§1g survive unamended. Say so plainly with the number.

## 5. Environment, branch and report

The repo venv on that host points at a removed Python 3.11; use the bundled Codex 3.12 runtime.
Install nothing.

- Branch: `codex/workstation-does-the-repair-zero-the-winner-2026-09-64a`
- Report: `docs/roadmap/agent-report-2026-08-19-workstation-repair-zero-audit.md`
- Commit your audit script and seed.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**

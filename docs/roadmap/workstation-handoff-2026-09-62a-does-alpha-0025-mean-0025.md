# Workstation handoff 2026-09-62a — does α=0.0025 actually mean 0.0025 on this panel?

Written 2026-08-10 by the production agent. Read on `origin/master` and execute.
**This spends no α, opens no C outcome, and needs no candidate.**

## 1. The assumption the whole campaign rests on, never once measured

Every interval this campaign has published is built the same way:

```
point ± z(1 − α/2) × crossed-bootstrap SD
```

At the ledger's α=0.0025 that quantile is **z = 3.0233 — a three-sigma normal quantile taken off a
bootstrap whose market dimension has 12 clusters.**

`-09-57a` measured **multiplicity**, not **coverage**. Its 50,000-campaign simulation null-centres
the *real* crossed-bootstrap distribution to price best-of-k selection, so **if that distribution's
dispersion is wrong at M=12, the multiplicity result inherits the error instead of detecting it.**
Nothing in `-09-44a`, `-09-56a`, `-09-57a`, `-09-59a`, `-09-60a` or `-09-61a` ever checked whether
these intervals cover at their nominal rate.

The cluster-robust literature says the error has a known direction — few-cluster normal intervals
**under-cover**, and the error grows in the far tail, which is exactly where α=0.0025 lives. For
scale, `t₁₁(1−0.00125) = 4.02` against `z = 3.02`: **a 33% wider interval.**

> **If the interval under-covers, α=0.0025 is nominal rather than real, every MDE in §1d is
> optimistic, and the ~3.2% floor is a floor on the wrong quantity.** That would not invalidate a
> single NO-GO — it makes an *accept* the dangerous direction, and decision 10 is an accept rule.

**Nothing is being asserted here. The direction is a prior; your job is the measurement.**

## 2. P0 — the empirical rejection rate under a known null

**Simulate. Do not derive.** Take the sealed panel's *actual* cluster structure — D and M, the real
date × market cell occupancy, the real per-cell row counts — and generate paired deltas under a
**true zero effect**. For each replication run the **exact crossed date × market pigeonhole
bootstrap the campaign uses**, form the interval, and record whether it excludes zero.

Report, two-sided, for **α = 0.05 and α = 0.0025**:

| Readout | Why |
| --- | --- |
| Empirical rejection rate vs nominal | the answer |
| **Implied actual α** of today's z-interval | the number to quote in §1d |
| Multiplier on the SD (or t-df) restoring nominal coverage | the fix, if one is needed |
| Monte-Carlo SE of your rate | so a null result is a *precise* null, not a blind one |

Do this for the structures that actually matter, because they differ:

1. **Out-of-season C** — D=27, M=12, 84,183 rows. Decision 10's primary endpoint.
2. **Severity tail** — D=49, M=12, **5,930 rows**. Thinnest, and §1d's headline 3.53%.
3. **In-season B** — D=23, M=12. For the fit stratum.

**The variance components are the one thing you must not invent.** Set the date / market / residual
dispersion from a *real observed* paired field — `-09-44a`'s repair-minus-control field is the one
`-09-57a` used and is the defensible choice. **Say which field you used and report the components**;
if coverage turns out to depend strongly on them, that dependence is itself the finding.

**Budget honestly.** 10,000 bootstrap draws × many replications may not fit. Reducing draws is
allowed **if you show the interval width has stabilised** at the number you use. Reducing
*replications* is what costs you resolution at α=0.0025 — you cannot measure a 0.25% rejection rate
with 200 replications. **State the smallest effect on coverage you could have detected.**

## 3. The control that makes the harness believable

**Pre-declare a positive control with a provable answer: at a large cluster count the procedure must
return nominal coverage.** Run the identical harness at M=200 (or the largest you can afford) and
show it recovers 0.05 and 0.0025 within Monte-Carlo error. **If it does not, the harness is wrong
and every other number in your report is uninterpretable — say so and stop.**

`-09-61a`'s clone control is the model to copy: prefer a control whose correct answer is an
identity, not an assumption. `-09-59a` had to repair its control mid-flight; design yours so it
cannot happen.

## 4. What to do with the answer — both branches are useful

- **Coverage is nominal** → §1d stands as written, decision 10's accept rule is sound, and this
  question is closed permanently. **Write that down; a precise null here is worth as much as a
  correction.**
- **Coverage is short** → give the corrected quantile, then **restate §1d's four MDEs, the ledger's
  ×1.3796 multiplier, and the ~3.2% market floor under it.** Say plainly whether the ≥5% step size
  and the 2026-10-16 confirmation date survive, and whether decision 10's 10%-of-gap power gate
  still admits a plausible effect.

Do **not** edit `-09-61a`'s frozen protocol. If the quantile must change, that is an operator
decision recorded as a disclosed amendment with a new hash — **propose it, do not apply it.**

## 5. What would falsify this mission

- The positive control fails to recover nominal coverage at large M → harness defect, stop.
- Achievable replications cannot resolve a rejection rate at the 0.0025 scale → **say so and report
  the α=0.05 result alone**, clearly labelled as not answering the ledger's α. That is an honest
  partial answer and far better than a confident number built on 200 draws.
- Coverage depends so strongly on the assumed variance components that no single correction applies
  → then the honest output is a *conditional* table, not a single multiplier.

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **This mission needs no C outcome, no market probability, and
no candidate** — it is a property of the cluster structure. **Read no post-boundary row; never pool
across `2026-07-31`** (anchor `b77cfbed`). Promote nothing, activate nothing, place no order, enable
no live trading, call no exchange or weather-provider endpoint. Nothing under production `data/`.
No chain run, settlement, or loop restart. **Never weaken the serving floor.** Paid weather-provider
access is unsupported.

**Spends NO ledger decision and allocates none.** α remains **7 of 20 spent, 13 available**;
decision 10 stays allocated and unspent.

**Environment:** the repo venv on that host points at a removed Python 3.11; use the bundled Codex
3.12 runtime as the last five missions did. Install nothing.

## 7. Branch and report

- Branch: `codex/workstation-interval-coverage-at-alpha-0025-2026-09-62a`
- Report: `docs/roadmap/agent-report-2026-08-19-workstation-interval-coverage.md`
- Commit your simulation script and its seed so the numbers reproduce.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**

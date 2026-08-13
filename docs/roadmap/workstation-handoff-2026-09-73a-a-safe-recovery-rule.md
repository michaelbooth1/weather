# Workstation handoff 2026-09-73a — a safe recovery rule, or none

Written 2026-08-11 by the production agent. Read on `origin/master` and execute.
**No α, no outcome scoring, no C endpoint.** Direct continuation of `-09-72a` (merged `b681e8b1`).

## 1. Where we are

`-09-72a` established that the rows WU drops are **still in our own corpus**: a point-in-time
envelope repairs **748 / 906** B decrease events and **368 / 368** on the model's main decision path.
C is **0 / 1,284** and is closed — nothing to union pre-dawn. Verified on production, receipts
audited independently, zero point-in-time violations.

It also established the blocker: **a monotone envelope cannot retract a transient print.** 55 new
above-settlement feature rows of 28,254, all san-francisco `2026-06-09`, `+1 F`.

**The open problem, and it is now narrow:** recover the lost rows **without** carrying forward a
value the vendor was right to withdraw.

## 2. The lead — and I want you to attack it, not confirm it

I sliced `-09-72a`'s artifact by mechanism after the fact:

| Mechanism | repaired | of |
| --- | ---: | ---: |
| `M5_cutoff_change` | 658 | 658 |
| `M3_rows_dropped` | 78 | 78 |
| `M1_restatement` | 2 | 2 |
| `M2` / `M4` / `M6` | 9 / 0 / 1 | 144 / 4 / 20 |

**The single event that breaks the floor is classified `M1_restatement`.** Restricting recovery to
`M5 ∪ M3` retains **736 of 748** repairs and **366 of 368** decision-window events, with no retained
event above settlement.

**Treat that with suspicion. It is a rule I derived post-hoc from the very row it has to clear, and
B contains exactly TWO `M1` events.** A gate fitted to `n = 2` is not a finding. Worse, there is a
direct contradiction in the evidence you must resolve first (§2a).

### 2a. Resolve the contradiction before anything else

`-09-70a` classifies san-francisco `2026-06-09` `20260609T171152-0400` as `M1_restatement` — "same
row count, same `latest`, a row's temp changed". But `-09-72a`'s payload trace of the same pair says
the `13:00 / 68 F` row **vanished** and a **new** `14:00 / 67 F` row appeared, and states plainly
"this is not a same-timestamp restatement."

**Both cannot be true.** And `-09-71a` already proved these discriminants read the vendor's
**summary** fields rather than the rows — that is exactly how toronto `2026-06-08` got
`latest_datetime_changed = false` while its rows regressed underneath.

**Go to the raw payloads and say which it is.** If the `M1` label is wrong, then "exclude `M1`" is
fitted to a label error and must be abandoned no matter how well it scores.

### 2b. Prefer a rule stated over observables, not over our own labels

Mechanism labels are our classification and they have already been shown to misread the vendor.
**A servable rule should be expressible in what the payloads show at time `t`.** The candidate I
think is principled — again, test it, do not assume it:

> **Recover a row only if the vendor has published nothing at or after that row's timestamp.**

- atlanta `2026-06-13`: latest regressed `10:52 → 09:52`, nothing published at or after `10:52`
  → the vendor **lost** data → recover.
- san-francisco `2026-06-09`: `14:00` published while `13:00` vanished → the vendor **revised**
  → do not recover, trust the newer payload.

This is point-in-time computable from two consecutive payloads and needs no mechanism label. Compare
it head to head against the `M5 ∪ M3` gate and against `-09-72a`'s two envelope rules, and report
all four in one table. **If a simpler or better rule exists, propose it and measure it.**

### 2c. The gate that decides this — run it on the full population

`-09-72a`'s repair counts are over the **906** decrease events. **The 55 above-settlement rows are
over the 28,254 feature snapshots**, because the envelope is monotone and one bad print persists
through snapshots that are not themselves decrease events.

**So any candidate must be re-scored on the full snapshot population.** A rule that removes the
offending *event* has not been shown to remove the 55 *rows*. Measure it; do not infer it.

Accept a candidate as **servable** only if, on all 28,254 B feature snapshots:

1. **`new_above_settlement == 0`.** Hard gate. The floor is the one shipped win and it is never
   weakened.
2. It repairs a material share of the **366** decision-window events — report the number, do not
   trade it away silently.
3. Point-in-time receipts are clean: **zero** future snapshots consumed, **zero** blank receipts.
4. It does not widen train/serve skew versus `-09-70a`'s 9.74% B baseline.

### 2d. If a candidate clears, re-freeze the pre-registration

Update `observation-envelope-preregistration-2026-09-72a.json` into a `-09-73a` successor bound to
the new candidate: same protocol, `status` lifted from `SAFETY_BLOCKED` only if §2c passes, and
**still `outcome_scoring_authorized: false` with `allocated_now: false`.** The α allocation is the
operator's to declare, not yours, and it happens after this mission — not inside it.

**Do not compute Brier, CRPS, log loss, or any market comparison.** That remains the next mission's
job, and only against a candidate that has already cleared the floor.

### 2e. My predeclared expectation

I expect the observable rule in §2b to clear the gate and land near the `M5 ∪ M3` numbers — and I
expect the `M1` label on the san-francisco row to turn out **wrong**, which would mean my tidy
mechanism story is the wrong frame even though the arithmetic works.

**I would rather be wrong about the rule than right about the label.** Report what you measure.

## 3. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **CLOSED UNUSED** and must not be reassigned.
- **You may read C** on input-integrity grounds, as `-09-70a`–`-09-72a` did: no candidate, no fitted
  parameter, no endpoint comparison, no accept rule. **Say so explicitly.** C's repair question is
  closed at 0 / 1,284 — do not re-open it.
- **Never pool across `2026-07-31`** (anchor `b77cfbed`). B and C separate throughout.
- **Point-in-time is absolute.** At snapshot `t`, only snapshots with `captured_at_utc <= t`. Emit
  the receipts and assert them, as `-09-72a` did. **Never clamp to realized settlement** — settlement
  is the thing we are trying to predict, and using it to pick a rule is leakage.
- **The corpus lives in two roots**; one yields **7 B dates, not 23**. Reconcile against `-09-72a`
  and state which root you used.
- **Change nothing** — not `high_so_far`, not `cutoff_hour`, not the producer, not the floor, not
  collection, not scoring. This measures counterfactuals.
- **Never weaken the serving floor** (`1.6639 → 1.4980`).
- Native units per market; toronto is Celsius and does not pool with the F markets.
- **A grep is not a trace.** Walk the san-francisco pair and the atlanta pair end to end from raw
  payloads.
- `DELEGATION_CONTRACT.md` §2 in full. No provider or exchange calls, nothing under production
  `data/`, no promotion, activation, release or trading.

## 4. What would close this — and this thread terminates either way

- **A rule clears §2c** → we have a servable candidate and a re-frozen protocol. The next mission
  allocates α and scores it. **That is the first outcome measurement this thread has earned**, and
  it is the whole reason for the three measurement missions behind it.
- **No rule clears §2c** → recovering the dropped rows cannot be made floor-safe on captured
  evidence. **Write that down plainly and the thread closes.** It is a precise null, it retires the
  strongest input lead we hold, and it frees the workstation. That outcome is worth as much to me as
  the other, and I do not want it dressed up as "promising but needs more work."

**Neither outcome licenses a serving change on its own**, and a repaired feature is still not
evidence of a better forecast — `-09-44a` was a precise null on exactly that move.

## 5. Environment, branch and report

The repo venv on that host points at a removed Python 3.11 — use the bundled Codex 3.12 runtime.
**Install nothing.**

- Branch: `codex/workstation-a-safe-recovery-rule-2026-09-73a`
- Report: `docs/roadmap/agent-report-2026-08-28-workstation-safe-recovery-rule.md`
- Commit the harness and seed alongside the artifacts; extend `-09-72a`'s harness rather than
  rewriting it, and version the seed schema.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**

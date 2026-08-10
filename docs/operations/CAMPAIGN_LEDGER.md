# Campaign ledger — the sealed pre-boundary panel

**Opened 2026-08-09** on the recommendation of `-09-57a`. **Canonical and binding.**

This file exists because **filing a risk is not mitigating it** (`HOW_WE_GET_THINGS_WRONG.md`
pattern 5). `-09-57a` recommended a 20-decision α ledger; a recommendation living only in a report
is a document, not a control. **This is the control.**

## The panel this governs

The sealed **pre-boundary** paired band surface: `2026-06-03` → `2026-07-30`, **D=50, M=12, 524
promotion-countable market-days, 135,179 band rows**, input SHA-256 `4352e776…`. Post-boundary
confirmation is a **separate** instrument and is not spent from this budget.

## The rule

| | |
| --- | --- |
| Family α | **0.05** |
| Budget | **20 decisions** |
| Per-decision α | **0.0025**, two-sided |
| MDE multiplier vs unadjusted | **×1.3796** |
| After decision 20 | **STOP.** Freeze a new panel or wait for post-boundary evidence |

**Why this and not a 25/25 date split:** the split's confirmation half is consumed by a single
winner, and its fold MDEs are asymmetric (in-season `0.003831` vs `0.006688`), so `√2` does not
price this cluster structure. The ledger preserves the full panel and keeps the tail usable.

**Post-ledger MDEs** — in-season `0.004215` (0.9958% of gap) · out-of-season `0.052052` (9.5993%)
· **tail `0.020937` (4.8734%)** · primary window `0.002314` (12.9265%).

## Why unadjusted reuse is not an option

Under the global null, best-of-k on this panel at one-sided α=0.05 (`-09-57a`, 50,000 campaigns):

| Looks | Any false accept, ρ=0 | ρ=0.5 |
| ---: | ---: | ---: |
| 5 | 23.1% | 15.5% |
| **10** | **39.0%** | 25.7% |
| 20 | 64.2% | 40.8% |
| 50 | **92.2%** | 65.7% |

At k=50 the mean best *null* "improvement" is `0.003008` — **essentially the entire `-09-44a` MDE,
manufactured by selection alone.** Cross-candidate correlation is **not identified** by this panel,
so ρ=0 is the honest planning assumption.

## Spend to date

**7 of 20 spent. 13 remain.**

| # | Decision | Mission | Outcome | Counts? |
| ---: | --- | --- | --- | --- |
| 1 | Scalar isotonic PAVA, predeclared primary | `-09-56a` | NO-GO, worsened C **and its own training score** | yes |
| 2 | Per-market isotonic | `-09-56a` | worsened C materially | **contestable** |
| 3 | Daily-expanding isotonic | `-09-56a` | worsened C materially | **contestable** |
| 4 | Simplex-native `q ∝ p^β`, β selected on B | `-09-56a` | +8.829% gap, CI includes zero | yes |
| 5 | 50% shrink toward market, disagreement set | `-09-56a` | 65.111% gap closed — *consumes the benchmark* | yes |
| 6 | 25% shrink toward market, global | `-09-56a` | 44.652% gap closed — *consumes the benchmark* | yes |
| 7 | Season-matched refit, B↔C proxy | `-09-56a` | 24.893%, CI [−20.5%, +55.2%] | yes |

### Allocated, not yet spent

| # | Decision | Mission | State |
| ---: | --- | --- | --- |
| 8 | One own-information feature for the disagreement set — **mechanism to be named by the mission** | `-09-58a` | **ALLOCATED 2026-08-09.** The mission must fill in the mechanism and endpoint **before** scoring on C. Do not assign #8 to anything else |

**The accounting choice is stated rather than hidden.** Entries 2 and 3 are arguably sensitivity
analyses of entry 1, not independent decisions — a defensible reading would spend 5, not 7. **I
charged all 7**, because the multiplicity arithmetic counts *looks*, not intentions, and because a
budget that starts by arguing itself down is not a budget. If the operator prefers 5, change it
here and say so — **do not re-derive a friendlier number inside a future mission.**

`-09-56a`'s own β selection is **not** charged separately: it was priced inside its bootstrap,
reselected in all 10,000 draws.

## Rules for spending a decision

1. **Pre-register** mechanism and endpoint here, with the row appended, **before** scoring.
2. Test at **α=0.0025** two-sided. Report the selection-adjusted evidence, never the raw best.
3. Retain all existing determinism and non-regression gates — this budget replaces none of them.
4. An accepted step is labelled **`SELECTED_ON_PREBOUNDARY_PANEL`**, *not confirmed*. It stays
   provisional until post-boundary evidence can decide it (see §1d).
5. **Steps below the floor must be batched**, not tested individually.

## Update this file when

A decision is pre-registered (append the row *first*), an outcome is known (fill it in), or the
operator changes the budget. **Never renumber, never delete a row** — a spent look stays spent
even if its result was discarded.

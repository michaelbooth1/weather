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

**α SPENT: 7 of 20. → 13 decisions remain available.**

**Accounting correction, 2026-08-10.** An earlier line read *"slot 8 closed without a look; 12
unallocated slots remain"*, which silently charged a retired slot against the budget. **It does
not.** The budget is **20 α-spends of 0.0025**; a slot closed without scoring on C **consumes no
α**. Slot *numbers* 8 and 9 are retired for audit clarity — **never reassign a number** — but
**13 decisions of budget remain.** Do not let conservative bookkeeping end the campaign early;
that would be a self-inflicted version of the very thing this ledger exists to prevent.

| # | Decision | Mission | Outcome | Counts? |
| ---: | --- | --- | --- | --- |
| 1 | Scalar isotonic PAVA, predeclared primary | `-09-56a` | NO-GO, worsened C **and its own training score** | yes |
| 2 | Per-market isotonic | `-09-56a` | worsened C materially | **contestable** |
| 3 | Daily-expanding isotonic | `-09-56a` | worsened C materially | **contestable** |
| 4 | Simplex-native `q ∝ p^β`, β selected on B | `-09-56a` | +8.829% gap, CI includes zero | yes |
| 5 | 50% shrink toward market, disagreement set | `-09-56a` | 65.111% gap closed — *consumes the benchmark* | yes |
| 6 | 25% shrink toward market, global | `-09-56a` | 44.652% gap closed — *consumes the benchmark* | yes |
| 7 | Season-matched refit, B↔C proxy | `-09-56a` | 24.893%, CI [−20.5%, +55.2%] | yes |

### Allocated or closed without a look

| # | Decision | Mission | State |
| ---: | --- | --- | --- |
| 10 | Lead-1 PIT surface-heating and convective-budget exponential tilt using the 12 predeclared Open-Meteo previous-run fields; total excess Brier vs market primary, incumbent-frozen severity-tail SSE secondary | `-09-61a`, executed by `-09-63a` | **CLOSED UNUSED 2026-08-10 — GATE 3 NO-GO.** The B-only integrity pass found a realized winning band with incumbent repaired probability exactly zero (Denver, `2026-06-08`, snapshot `20260608T030552-0400`, band 4). The frozen multiplicative map cannot create support and the protocol forbids epsilon repair, so no beta was fitted, no OOF curve was built, and no C state was opened. Decision 10 spent no alpha and must never be reassigned. |
| 9 | Conditional own-distribution reshape behind a peak-probability band-state trigger (β=0.52, threshold 0.65) | `-09-60a` | **CLOSED UNUSED 2026-08-10 — P0 NO-GO.** Conditional lost to global on **its own B training score** (0.051512 vs 0.050613) and forward (0.054804 vs 0.053567). No C score, **no α spent. Never reassign #9.** |


| # | Decision | Mission | State |
| ---: | --- | --- | --- |
| 8 | Forecast run-to-run instability (`fixed_lead_day_offset` seven-run high SD) and strictly lagged five-day station forecast-error dispersion screened on B; **no feature selected and no C endpoint scored** | `-09-58a` | **CLOSED UNUSED 2026-08-09 — P0 NO-GO.** Both forward OOF point estimates worsened prediction of excess loss and both crossed intervals included zero. C outcomes stayed unscored, so α=0.0025 was not spent. **Never reassign #8.** |

Closing a slot unused is intentionally conservative. The P0 screen used only in-season B to decide
whether a mechanism existed; it never used or scored the out-of-season C outcomes, never built a feature,
and therefore never performed the pre-registered decision that would have spent this slot.

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

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
| 10 | Lead-1 PIT surface-heating and convective-budget exponential tilt using the 12 predeclared Open-Meteo previous-run fields; total excess Brier vs market primary, incumbent-frozen severity-tail SSE secondary | `-09-61a` → `-09-63a` | **CLOSED UNUSED 2026-08-11 — NO-GO at Gate 3 on the B-only screen.** Allocated 2026-08-10 under frozen protocol `docs/roadmap/pit-field-evaluation-protocol-2026-09-61a.json` (+ amendment A1), then closed without ever reaching C. **The B-only screen does not spend alpha** by this row's own trigger, so **α spent = 0**. No C settlement outcome, market probability, candidate probability, or bootstrap draw was ever computed. **Never reassign #10.** |
| 9 | Conditional own-distribution reshape behind a peak-probability band-state trigger (β=0.52, threshold 0.65) | `-09-60a` | **CLOSED UNUSED 2026-08-10 — P0 NO-GO.** Conditional lost to global on **its own B training score** (0.051512 vs 0.050613) and forward (0.054804 vs 0.053567). No C score, **no α spent. Never reassign #9.** |

### Coverage calibration — `-09-62a`, no spend and no allocation

The predeclared true-zero simulation found decision 10's C primary calibrated at ledger alpha
(`0.00240`) but its required 5,930-row severity tail short (`0.00340 [0.002927, 0.003950]`). The
restoring tail quantile is `3.1098893` rather than `3.0233414`. This result is component-conditional:
in-season B was conservative, so it is not a generic M=12 `t` rule.

**ADOPTED 2026-08-10 as amendment A1 — the conservative UNIFORM quantile.** The operator took the
uniform option: `q=3.1098893` replaces `z=3.0233414` for **both** required decision-10 endpoints,
not just the tail. Nominal α does not move — it stays `0.0025`; the quantile is corrected to
*deliver* the α the ledger already declares.

| | |
| --- | --- |
| Amendment | `docs/roadmap/pit-field-evaluation-protocol-2026-09-61a-amendment-A1.json` |
| A1 SHA-256 | `549e26a3a55494e0da2d406809ad67c43dba60c6fbb3604aec62488ea4e8f2bb` |
| Base protocol | **byte-identical, edited nowhere** — `336150be1a62e88c2fe40ccd7b77916576d08981617ebbff1e01195007cfc146` |
| MDE multiplier | `1.3795628` → **`1.4104552`** (×`1.0223929` on every existing MDE) |
| Campaign-adjusted market floor | `4.414601%` → **`4.513457%`** — the practical ≥5% step still clears it |

**Uniform was chosen over the statistically exact endpoint-specific rule on purpose.** C measured
calibrated (`0.00240`) and only the tail short, so a per-endpoint quantile would have cost no power
on C. It was rejected because it makes *"which quantile applies here"* a live choice at analysis
time, and this campaign's recorded failure mode is researcher degrees of freedom, not lost power.

**Decision 10 KEEPS ITS NUMBER and its allocation.** The base protocol's `deviation_policy` voids a
decision whose verdict rule changes, but that clause exists to stop a rule being tuned once results
are visible. **Nothing has been executed** — no C outcome, market probability, candidate
probability, or bootstrap draw exists, and A1 was decided from a **true-zero** simulation that never
touched the candidate. **Every effect of A1 is strictly conservative:** a wider quantile makes the
primary interval *harder* to exclude zero, and a larger MDE makes the `actual_power_gate` *harder*
to pass. There is no path by which it raises the false-accept rate or helps a candidate. Renumbering
would imply a fresh look was taken; none was.

`-09-62a` spent and allocated nothing and A1 spends nothing, so accounting is **unchanged: 7 of 20
spent, 13 available**. See `ESTABLISHED_FINDINGS.md` section 1i and
`docs/roadmap/agent-report-2026-08-19-workstation-interval-coverage.md`.

**A1 was adopted, and then decision 10 closed unused anyway** (`-09-63a`, NO-GO at Gate 3 on the
B-only screen — see the row above). A1 is retained as the standing quantile rule for **any future**
decision on this panel, not as a dead letter: the coverage defect it corrects is a property of the
panel's component mix, not of decision 10. **Recorded 2026-08-11 from the `-09-63a` result while
that branch is still queued and unmerged** — its report is not yet in-repo, so cite the branch, not
a repo path, until it lands.


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

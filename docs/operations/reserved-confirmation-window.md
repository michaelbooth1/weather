# Reserved confirmation window

**Single source of truth for which dates are held out and what they are held out *for*.** Every
research handoff must carry this range. If this file and a handoff disagree, this file wins.

## The reservation

| | |
| :--- | :--- |
| **Reserved dates** | **NONE ARE CURRENTLY RESERVED.** The window is *armed but not dated*. |
| **Trigger** | The reservation begins on the **first target date after the first retrain candidate is fitted and frozen**, and runs forward from there. |
| **Size** | Computed at freeze time against endpoints that still stand — see *Sizing at freeze* below. Not fixed in advance. |
| Status | No date is held out today. Nothing is off-limits to research or MM scoring right now. |
| Declared | 2026-08-04 by the operator (re-base). Previously 2026-08-03. |
| Supersedes | 2026-08-06 → 2026-11-03 (90 dates); before that, 2026-08-06 → 08-19 (14 dates) |

### OPERATOR DECISION 2026-08-04 — re-base the reservation to the retrain

**Decided by the operator on 2026-08-04, with reasons recorded here as this file requires.**

The 90-date block was replaced by a **forward reservation triggered at candidate freeze.** Three
reasons:

1. **It was reserving against something that does not exist.** Release #1 *freezes* the June
   per-market HGBs — it does not retrain. The first retrain has **no candidate and no schedule**.
   Dates held out *before* a candidate exists add no protection: the candidate cannot have seen them
   either way. What actually protects a confirmation is that its dates are unseen **at the moment the
   candidate is fitted and selected** — which a forward reservation guarantees exactly.
2. **Its sizing basis had been superseded on every row** (see the table below, retained for history).
3. **It blocked the operator's stated end goal by about four months.** `-09-10a` established that no
   reserved date can contribute a countable market-making day, because scoring a maker day reads that
   date's settlement. Under the 90-date block the first possible MM decision was **2026-12-16**.

**This is a re-base, not a retroactive shortening.** It was decided on **2026-08-04**, before the
window's own start date of 2026-08-06. **Not one reserved date had elapsed, so no holdout was
consumed and nothing was un-reserved after the fact** — the specific hazard the *Changing this file*
section below warns about does not apply.

### Why this does not collide with market making

The two tracks become **sequential instead of overlapping**. MM consumes *current* dates for its
paper clock now; the confirmation window consumes *future* dates once a candidate is frozen. On the
`-09-10a` design at `$25/tier-20`, the MM clock is ~22 countable dates — it should complete well
before any retrain candidate is frozen. Once MM is live it no longer needs countable paper days.

### Binding rules under the re-base

1. **Until a candidate is frozen, nothing is reserved.** MM scoring, diagnostics, and research may
   use any settled date.
2. **At candidate freeze, the window is declared here immediately** — dated, sized, and with its
   endpoints named — *before* any confirmation scoring begins. An undeclared window reserves nothing.
3. **Once declared, the window is absolute again** and every rule below applies unchanged: not read,
   not enumerated, not evaluated, not substituted. Reading one destroys it permanently.
4. **MM paper scoring must stop on declared confirmation dates**, or be granted a fresh explicit
   exemption recorded here. It does **not** inherit an exemption from this decision.
5. **The freeze must not be timed to dodge the reservation.** Declaring a candidate frozen only after
   convenient dates have been consumed would defeat the protection this file exists to provide.

### Sizing at freeze

Do **not** reuse the superseded table below. At freeze, compute N against endpoints that still stand,
under **crossed date × market** clustering, and record the derivation here. Known constraints:

- **Severe-tail SSE remains the only plausibly powered primary**, but `N=4` is **not** established:
  measured power at N=4 is **72.94%**, and the candidate-native N is **UNKNOWN**.
- **Pooled all-hour Brier is a guardrail, not a primary.** Its `N=53` was a weak 3-date variance
  proxy and cannot be described as crossed-bootstrap power.
- **09:00–14:00 remains unconfirmable** — 75.76% power at N=34, MDE 19.44% of baseline.
- **Toronto-only is not viable at any endpoint. Fleet or nothing.**

If no endpoint is powered at achievable N, **say so and do not declare a confirmation** rather than
reserving dates against a test that cannot decide.

## Historical sizing basis — SUPERSEDED, retained for audit

Everything in the next two sections was the justification for the 90-date block. **Every row of its N
table has since been retracted or downgraded.** It is kept because the reasoning trail matters, not
because it is still load-bearing.

- severe-tail `N=4` → measured **72.94%** power; candidate-native N unknown (`-09-06a`)
- pooled all-hour `N=53` → "weak 3-date variance proxy" by its own admission; `-09-07a` ruled it
  cannot be called crossed-bootstrap power at all
- the `5.39%` anchor → `-09-05a` found it a **separately fitted transform, not a propagated one**
  (real propagated served effect **18.32%**), and the `24.69%` figure was retracted outright

The previous 14-date window was chosen by calendar convenience. It was never a powered
confirmation and must not be described as one retrospectively: its 09:00–14:00 minimum detectable
effect was **32.30% of the served gap**, giving **10.96% power** at the optimistic effect.

## What changed, and why

`-08-04a` derived the honest served-level effect range for the first retrain as **0 to 5.39% of the
served incumbent-versus-market Brier gap**. The 24.69% raw-HGB closure does not survive the
downstream floor, blend, cap and calibration stages.

Fleet N required at 80% power, alpha 0.05 one-sided, two-way clustered by target date and market:

| Endpoint | N at 5.39% | N at 2.5% midpoint |
| --- | ---: | ---: |
| **Frozen severe-tail SSE** | **4** | **9** |
| Pooled all-hour Brier | 53 (weak 3-date variance proxy) | 246 |
| 09:00–14:00 Brier | 504 | 2,337 |
| Toronto-only, any endpoint | 3,350 | 15,550 |

**90 dates covers the two endpoints that are actually powered, with buffer for the weak pooled
variance estimate.** It does not cover the 09:00–14:00 slice, and nothing practical does.

## Endpoints for the first retrain's confirmation

- **Primary: frozen severe-tail SSE, fleet, paired, clustered by date and market.** It is powered at
  achievable N, and it is where the conditional correction improved *all five* held-out dates.
- **Guardrail: pooled all-hour Brier non-regression, fleet.** The primary endpoint alone is
  narrow — a candidate could improve the incumbent's worst rows while degrading elsewhere. This
  catches that.
- **Harm gate: one-sided two-way-cluster max-T, familywise error 5%.** Replaces the frozen
  53–54-slice bar, which falsely rejects a uniformly better candidate 99.885%–99.9905% of the time.
- **Reported but not confirmatory: the 09:00–14:00 slice.** Report it, label it directional, and do
  not call it a confirmation.

**Toronto-only evaluation is not viable at any endpoint.** Fleet or nothing.

## Standing consequence for the primary objective

The 09:00–14:00 slice remains the thing we are trying to *fix*. It is no longer the thing we can
*confirm* in a single shot. Those are different claims and conflating them is how this project
previously called an underpowered Toronto result a win.

## Changing this file

Extending the reservation is cheap; shortening it after the fact is not, and reading a reserved date
destroys it permanently. Any change needs an explicit operator decision recorded here with its date
and reason.

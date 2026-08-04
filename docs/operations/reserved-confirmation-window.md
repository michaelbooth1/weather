# Reserved confirmation window

**Single source of truth for which dates are held out and what they are held out *for*.** Every
research handoff must carry this range. If this file and a handoff disagree, this file wins.

## The reservation

| | |
| :--- | :--- |
| **Reserved dates** | **2026-08-06 → 2026-11-03 inclusive (90 dates)** |
| Status | Not read, not enumerated, not evaluated, not substituted |
| Declared | 2026-08-03 |
| Supersedes | 2026-08-06 → 08-19 (14 dates) |

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

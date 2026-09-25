# Break-even reward per filled share `R` — frozen as a rule (2026-09-23)

Status: **FROZEN by the owner on 2026-09-23, before any new read of the public execution-tape markouts.** This closes the
open item left by the 2026-09-19 markout pre-registration (`codex/execution-tape-markout-20260919`,
`docs/research/execution-tape-markout-preregistration-2026-09-19.md` on that branch), whose `R` was left blank and whose
2026-09-20 run printed `R_NOT_SUPPLIED` (item 330). Owner of the plan: [forward plan](../operations/forward-plan-2026-09-23.md)
item 5.

## Definition

`R` is the liquidity reward earned per filled share by the study's simulated maker quote. It is **a rule, computed later on
the study panel**, not a number chosen now:

    R = (sum over quoted minutes of modelled reward per minute) / (sum of simulated filled shares)

- **Simulated quote:** the fill-toxicity desk study's slow quote — 20 shares per leg at 1.5 c either side of the
  size-adjusted midpoint, repriced only at each minute's book sample; a leg counts as filled when a public trade prints
  through or at its price.
- **Modelled reward per minute:** `rate(t) / 1440 × share_many(t)` from the canonical estimator (the one RE-1 session 1
  validated against the venue within about 10%: `mm_stage2_selection` / `reward_share_estimate`), with our own size removed
  from competition as that estimator does. A minute in which the quote is not reward-eligible (size below the band's reward
  minimum, distance beyond the maximum spread, one side missing where two-sided scoring is required) contributes **zero**.
- **Sensitivity only:** the same rule with `share_single`, reported beside the primary value; it cannot replace it.
- Computed once on the study's pre-registered panel and reported with a date-clustered interval. Every intermediate figure
  is recorded; none may be used to change the rule.

## What it decides

Net maker value per filled share = `R` + markout (horizon as pre-registered in the desk study). The study's KILL /
SUPPORTIVE thresholds are written in its own pre-registration before the tape is read; this document fixes only `R`.
Changing this rule after any markout read requires a new dated pre-registration that names this one and states that the
data had been seen.

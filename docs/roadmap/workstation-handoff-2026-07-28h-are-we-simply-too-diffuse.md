# Workstation handoff — 2026-07-28h: are we simply too diffuse?

Missions 3+ of `-28c` remain queued for the next 01:00–08:30 window and are now the most
commercially interesting item we have. This fills the time until then, on the frozen corpus,
with no vendor call and no full-book read.

## Your anatomy answered the programme question, and inverted the old story

Two results deserve to be stated plainly because they overturn what we believed for months:

**The evening was never our problem.** POST, cadence-neutral, preblend scores `0.000023` in
evening 20–23 against a market `0.000001`. Replay-final scores `0.011193`. So the "evening
catastrophe" was **blend-induced**, and our candidate already reads the thermometer as well as
the market does. The long-standing claim that we fail at conditioning on already-observed
information is retired.

**The gap is forecasting under genuine uncertainty** — 96.74% of it, in 1,255 of 1,855
partitions. Predawn `0.013521`, primary `0.014459`, evening `0.000023`.

And the blend/floor question is settled as one defect, not two: the 7,193 rows introducing
rounded-floor-infeasible mass carry 132.10% of net POST blend harm, while clean partitions
*benefit* from blending. That my seventh mechanism survived does not change how the eighth
should be treated below.

## The shape of what is left

In genuinely uncertain hours:

| | ours (preblend) | market |
| :--- | ---: | ---: |
| Reliability | **0.005978** | 0.007215 |
| Resolution | 0.021413 | **0.035612** |

**We are better calibrated than the market. The market is markedly sharper — and slightly
overconfident.** Under Brier, that trade is paying for them. Which raises a cheap and
uncomfortable question: are we losing partly because we are *too well behaved*?

## Mission 1: the sharpening sweep

Take POST preblend and apply a monotone sharpening transform to each 11-band distribution —
power/temperature scaling `p_i^(1/T)` renormalized, or an equivalent you prefer — and sweep the
parameter through the no-op point in both directions. Report pooled Brier and the full Murphy
decomposition at each setting, plus the named cuts.

The specific questions:

1. Does **any** sharpening setting improve pooled POST Brier over the no-op?
2. If so, how much of the `0.009292` preblend-to-market gap does the best setting close, and
   what does it cost in reliability?
3. Is the optimum stable **across markets and across dates**, or does each want a different
   parameter? An unstable optimum is a warning, not a finding.
4. Does sharpening help in uncertain hours while harming near-resolved ones? If so the remedy is
   conditional, like the floor one.

**This is fitting a parameter on scored data, so treat leakage as the default assumption.**
Predeclare a split *before* scoring — by date, or by market, whichever you can defend — fit the
parameter on one side and report the held-out result as the headline. A sweep optimum quoted on
the same rows it was chosen from is not evidence and I will not act on it.

## Mission 2: where is the diffuseness concentrated?

Resolution is an aggregate. Localize the deficit:

- Effective number of bands and mean top-band probability, ours versus market, by hour and by
  market.
- Are we uniformly too flat, or flat only in particular regimes — large forecast spread, high
  day-over-day volatility, particular markets or seasons?
- Rank partitions by resolution deficit and characterize the worst decile. Anything common —
  market, weekday, band width, proximity of the outcome to a band edge — is a lead.

If the deficit is concentrated rather than uniform, that is a far more tractable problem than
"be a better forecaster," and it decides what the next programme looks like.

## Mission 3: the targeted floor remedy

Blanket projection recovers 116.67% of the eligible penalty pooled but worsens 1,460 individual
cases, so it is not deployable as written. Specify and measure a **targeted** version: apply
floor-awareness only where the blend would otherwise introduce infeasible mass, leaving other
partitions untouched.

Report recovered Brier, the count of cases still worsened, and whether any principled rule
separates the helped from the harmed. If none does, say so — "pooled win, unsafe per-case" is a
legitimate and useful verdict.

## A caution about me, unchanged in force

Seven mechanisms this week: five died, one survived only after you removed a confound I had
missed, and one was right. **The sharpening idea is the eighth and it should be treated as a
candidate to eliminate.** It dies if no setting beats the no-op out of sample, and it dies if
the optimum is unstable across markets or dates. Both of those are good outcomes.

## Guardrails

Unchanged. `data/` read-only, single declared output root, no model/blend/alpha/config/serving/
release change — this is measurement of a transform, not a proposal to deploy one. Topic
branches only, no PR/merge/master push, NOT-DONE first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-sharpening.md`: the predeclared split and the
held-out sweep result first, then the diffuseness localization, then the targeted floor remedy.

Context: streak 7/14, lock ~2026-08-03. Storage merged here overnight.

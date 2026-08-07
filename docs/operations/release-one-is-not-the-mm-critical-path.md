# Release #1 and the MM clock — what is and is not established

Status: **corrected 2026-08-06, same day, before anyone acted on it.** The first version of
this file claimed release #1 was *not* on the critical path to a countable MM day. That claim
was under-evidenced and is retracted. What replaces it is narrower and, for sequencing,
points the same way for a different reason.

## What the first version got wrong

It checked for the string `release` in three gate modules, found none, and generalised that
into a causal claim about the critical path. That is a search, not a trace — the same mistake
this project has already recorded once, when a literal search over `-09-01a` was mistaken for
a safety property (`ESTABLISHED_FINDINGS.md` §7).

The path that actually produces a countable day was never traced. Tracing it falsifies the
headline:

**Today's maker run, `data/mm_runs/2026-08-06/.../quote_intents_long.csv`, 924 intents:**

| Field | Value |
| --- | --- |
| `promotion_state` | **BLOCK on all 924** |
| `known_edge_reason = promotion_block` | **847 (91.7%)** |
| `known_edge_reason = source_freshness_model_gap` | 77 (8.3%) |

So MM quoting **is** gated on promotion today. Promotion BLOCK denies known-edge permission,
no permission means no quotes, no quotes means no fills, and
`fill_evidence_completeness=BLOCK` is one of the six countability blockers. The countability
*modules* do not mention a release; the *causal chain* to a countable day runs straight
through promotion.

## What is established

1. **The MM countability gate modules contain no release reference.**
   `live_forward_gate.py`, `market_making_preflight.py`, `market_making_readiness.py`: zero
   occurrences of "release", case-insensitive. `build_live_forward_gate` passes on per-market
   paper-trading evidence and run-level `useful_work_liveness`. This is true and reproducible;
   it just does not support the conclusion that was drawn from it.

2. **MM quoting is gated on promotion**, by the 847/924 measurement above.

3. **Release #1 is not sufficient for promotion.** `hourly_model_performance` is `BLOCK` on
   `early_hour_brier_regression` — early-hour Brier trails the market by **0.0205 against a
   0.0030 tolerance, in all 12 markets** — and that gate's own remediation line reads
   `keep promotion blocked`. This is a model-skill refusal. **No release pointer touches it.**

4. **Release #1 does turn on `production_readiness_gate`**, which currently reports `SKIPPED`
   because `release_identity` is `RESEARCH_UNBOUND` / `production_capable: false`.

## What is NOT established

- **Whether release #1 is necessary for promotion.** A 2026-07-31 note records the chain as
  no release → `captured_input_replay_parity` BLOCK → `f_family_promotion_refresh` `not_run` →
  every market `promotion_state: BLOCK`. That is consistent with today's data but was **not
  re-verified here**, and today is a poor test: the chain died at the settled-day barrier
  before Stage B, so promotion refresh never ran at all and its summary is all-null. Today's
  BLOCK is the `not_run` default, which cannot distinguish "blocked by missing release" from
  "never reached".
- **Therefore the ordering of release #1 against the maker stack is open.** Do not treat
  either as settled by this file.

## What survives for sequencing

Only one conclusion, and it is strengthened rather than weakened by the correction:

**The blindness repair belongs before the candidate freeze.** Release #1 *freezes* the June
per-market HGBs, and the confirmation window arms at candidate freeze. Those HGBs are fed
constant imputed medians for 8 of 29 trained inputs, at every hour, in every market. Two
reasons, the second of which is new:

1. Freezing first bakes a knowingly blind incumbent into the baseline that every future
   comparison is measured against, making the first retrain's apparent gain partly an artifact
   of repaired plumbing rather than a better model.
2. **Model skill is an independent promotion blocker that no release clears** (point 3 above).
   Whatever release #1 unblocks, `early_hour_brier_regression` still refuses afterwards. Work
   that improves the model is therefore on the promotion path in a way that building the
   release is not.

## How to settle the open question

Run promotion refresh to completion once, with the settlement chain healthy, and read whether
`captured_input_replay_parity` blocks for want of a release pointer. That requires the chain to
get past the settled-day barrier — which needs 2026-08-05 backfilled first
(`WeatherChainRecovery20260807`). **Do not re-answer this from the roadmap or from module
greps.**

## Reproduction

```powershell
# claim 1 — true, and insufficient on its own
Select-String -Path src\weather\market\live_forward_gate.py,`
  src\weather\market\market_making_preflight.py,`
  src\weather\market\market_making_readiness.py -Pattern "release" -CaseSensitive:$false

# claim 2 — the trace that falsified the headline
python -c "import csv,collections;r=list(csv.DictReader(open(r'data/mm_runs/2026-08-06/20260806T174937785434Z/quote_intents_long.csv',encoding='utf-8')));print(collections.Counter(x['known_edge_reason'] for x in r))"
```

## Update this file when

The open question above is settled by a completed promotion refresh, or the MM gate chain
gains or loses a release dependency.

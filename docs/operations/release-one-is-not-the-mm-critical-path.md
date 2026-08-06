# Release #1 is not on the critical path to a countable MM day

Status: canonical finding, measured 2026-08-06 on production state. Supersedes the
"remaining blocker is promotion, downstream of release #1" framing of the MM track.

## The question

The MM bot is the stated end goal, and release #1 has been priority 1 for several days. The
sequencing question is whether that ordering is right: **is release #1 actually on the
critical path to a countable market-making day, or is something else the binding constraint
either way?**

## The answer

**Release #1 is not on that path.** The market-making countability gate chain contains **zero
references to release binding**:

| Module | Occurrences of "release" (case-insensitive) |
| --- | ---: |
| `src/weather/market/live_forward_gate.py` | **0** |
| `src/weather/market/market_making_preflight.py` | **0** |
| `src/weather/market/market_making_readiness.py` | **0** |

`build_live_forward_gate` (`live_forward_gate.py:194-218`) passes on exactly two conditions:

```python
counts_toward_live_forward_gate = (
    evidence["paper_trading_evidence"]["all_selected_markets_count"]
    and run_level_ok
)
```

Per-market paper-trading evidence, and run-level `useful_work_liveness`. Neither consults an
active release pointer, a release manifest, or a served binding.

## What is actually blocking, 2026-08-06

From the chain payload (`daily_refresh_status.json`, `summary.trading_evidence`):

| Blocker | Cleared by a release pointer? |
| --- | --- |
| `live_forward_gate=BLOCK` | **No** — depends on per-market paper evidence |
| `useful_work_liveness=BLOCK` | **No** — the maker is not doing useful work |
| `quote_starvation=quote_starved_infra` | **No** — infrastructure |
| `fill_evidence_completeness=BLOCK` | **No** — `mm_paper_conservative_fills = 0` |
| `preflight=WARN` | No |
| `model_variant_bakeoff_skipped_variants=66` | No |

`mm_paper_gate_status` is **OPEN** and `mm_paper_score_freshness_status` is **PASS**. The
paper scorer is running fine and covering today. **What is missing is execution evidence —
zero fills — not a release.**

## What release #1 does and does not do

- **Does:** create the active release pointer. `release_identity` is currently
  `RESEARCH_UNBOUND` / `production_capable: false`, which makes `production_readiness_gate`
  report `SKIPPED` rather than evaluating. A pointer turns that gate on.
- **Does not:** unblock promotion. `hourly_model_performance` is `BLOCK` on
  `early_hour_brier_regression` — early-hour model Brier trails the market by **0.0205
  against a 0.0030 tolerance**, in **all 12 markets** — with the gate's own remediation
  reading `keep promotion blocked`. That is a model-skill refusal and a release pointer does
  not touch it.
- **Does not:** advance the MM clock, per the table above.

**So release #1 unblocks the pointer, not promotion, and not market making.**

## Consequences for sequencing

1. **The maker branch stack is the real MM critical path.** `-09-11a` → `-09-18a` → `-09-25a`
   → `-09-27a` is a four-deep chain, each merging its predecessor, and **none of it is on
   master**. It is the work that addresses execution evidence, which is what actually blocks
   the clock. Landing it beats building the release.
2. **The blindness repair should land before the candidate freeze, not after.** Release #1
   *freezes* the June per-market HGBs, and the confirmation window arms at candidate freeze.
   Those HGBs are fed constant imputed medians for 8 of 29 trained inputs at every hour in
   every market. Freezing first bakes a knowingly blind incumbent into the baseline that
   every future comparison is measured against, and makes the first retrain's apparent gain
   partly an artifact of repaired plumbing rather than a better model.
3. **Release #1 is not urgent, and it is not useless.** Its value is turning on
   `production_readiness_gate` and establishing release identity. That value does not expire,
   and it does not compete with the two items above.

## What this corrects

The prior framing — recorded as "MM Phase 1 fixed; remaining blocker is promotion,
downstream of release #1" — is **wrong on this host as of 2026-08-06**. Promotion is blocked,
but MM countability does not depend on promotion, and neither depends on the release pointer
for the reasons above. The three were treated as one chain and they are not.

## Method note

This was settled by reading the gate implementations and today's chain payload, not by
argument from the roadmap. `ESTABLISHED_FINDINGS.md` §5 requires power and interval treatment
for *measurements*; this is a structural claim about code paths, and the appropriate evidence
is the code path plus the live payload. Both are cited above and both are reproducible:

```powershell
Select-String -Path src\weather\market\live_forward_gate.py,`
  src\weather\market\market_making_preflight.py,`
  src\weather\market\market_making_readiness.py -Pattern "release" -CaseSensitive:$false
```

## Update this file when

The MM gate chain gains a release dependency, or the set of countability blockers changes.

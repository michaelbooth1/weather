# Closed Roadmap Model Progress Audit - 2026-06-22

Scope: review all roadmap items currently marked `COMPLETE` and assess what
they say about the direction, progress, current state, and remaining work for
the weather model.

Method:

- Regenerated the active roadmap scan with
  `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint`.
- Used `docs/roadmap/ROADMAP.md`, `docs/roadmap/active-backlog.md`, numbered
  item files under `docs/roadmap/items/`, current backtest reports, and the
  latest model/taker audits as evidence.
- Treated `COMPLETE` as "closed"; `PARTIAL` and `OPEN` are active.

## Roadmap Coverage

Current roadmap state:

| Metric | Count |
| :--- | ---: |
| Total items | 241 |
| Complete / closed | 200 |
| Partial | 31 |
| Open | 10 |
| Roadmap lint errors | 0 |

Closed-item coverage by roadmap section:

| Section | Closed | Closed item IDs reviewed |
| :--- | ---: | :--- |
| Near-Term Priorities | 5 | 1-5 |
| Model Improvements | 4 | 6-9 |
| Dashboard Improvements | 4 | 10-13 |
| Data Quality And Operations | 4 | 14-17 |
| Market Expansion | 2 | 18-19 |
| Long-Run Accuracy Roadmap | 8 | 20-27 |
| Track A: data layer | 32 | 28-31, 39, 61-62, 64-65, 76-81, 85, 100, 102, 109, 111, 113-114, 120, 124, 154, 158-159, 193, 197, 201, 203, 208 |
| Track B: production model | 109 | 33-34, 36-38, 40-47, 49-60, 63, 66, 68-75, 82-84, 86, 101, 103-106, 108, 110, 115-118, 121, 123, 125, 139-143, 145, 148-153, 155, 162-170, 179-184, 192, 194-196, 198-200, 202, 207, 209-218, 220-223, 225-227, 231, 234 |
| Architecture And Maintainability | 32 | 87-99, 107, 112, 119, 122, 126-133, 171-175, 204-205 |

The closed set is broad enough to be meaningful. It is not just early dashboard
work. It includes the settlement ledger, source provenance, train/serve parity,
blocked validation, promotion gates, shadow variants, stage attribution, runtime
identity gates, taker evidence gates, and architecture cleanup.

## Honest Assessment

The project has moved in the right direction. The closed roadmap items show a
clear shift from "produce probabilities" to "prove probabilities under
settlement-scored, slice-aware, fail-closed evidence." That is the correct
direction for a model whose real benchmark is Polymarket, not generic weather
forecast accuracy.

The main accomplishment is not that the model now beats the market. It does
not, broadly. The accomplishment is that the system now catches that fact. The
closed items have built an evidence machine that blocks weak promotion claims,
separates no-market model skill from market-informed overlays, quarantines bad
inputs, records explanation/stage tapes, and prevents MTM-only trading evidence
from masquerading as settled profitability.

That is real progress, but it is not yet product success.

## What We Have Actually Built

### 1. An auditable evaluation foundation

Closed items 20-26, 28, 36, 83, 85, 106, 113, 117, 163, 179, 182, 198, 217,
and related reporting work make the evaluation target explicit:

- settlement-scored Brier/log-loss versus market prices,
- daily-first and blocked validation,
- promotion-grade market-day thresholds,
- frozen baseline trend separation,
- stage attribution over served distributions,
- explicit broad-claim gates.

This is the strongest part of the project. It prevents the most dangerous
failure mode: deciding a model is good because an aggregate or stale artifact
looked good once.

Current evidence from `data/backtest/daily_progress_ledger_report.md` still
blocks broad improvement claims: rolling daily-first skill is negative
(`-0.2212`), only one positive skill day is present, promotion-grade market-days
are below threshold, live-forward SLO is blocked, and runtime identity is not
clean enough for a broad claim.

### 2. A much better data layer

Closed Track A work added settlement ground truth, source redundancy, nearby
station provenance, ECCC/ASOS/MRMS/marine/official guidance sidecars, raw
payload sidecars, source-status recovery, data-retention policy, replay status
repair, feature-quality quarantine, and current-day expected-degradation
handling.

This is good directionally because weather-model failures are often data
failures wearing a model costume. We now have enough provenance to distinguish
source absence, source degradation, feature missingness, replay eligibility,
and live-only evidence.

But several data-layer parents remain active: reanalysis/synoptic features,
source-family expansion, probabilistic guidance, SST/marine, ECMWF/ML-NWP, NBM,
and smoke/soil/radiation features are still partial/open. The data layer is
vastly better, not complete.

### 3. A governed multi-variant model lane

Closed items 33-38, 69-73, 82-86, 139-143, 145, 148-151, 218, 220-223, 225-227,
and 231 establish model-family governance:

- pooled F-family artifacts,
- per-market calibration and allowlists,
- active variant registry,
- paired shadow scoring,
- no-market versus market-informed lane separation,
- early-hour and ten-minute gates,
- source/missingness location gates,
- blocked-market no-go guards,
- bottom-location winner-mass attribution.

This is a major improvement over broad, ad hoc candidate promotion. The system
now says "promote only where the candidate passes" instead of treating a few
wins as proof for the fleet.

Current evidence from `data/backtest/f_family_promotion_refresh_report.md`
keeps the broad candidate blocked: cutover is `DO_NOT_CUT_OVER`, readiness is
`OPEN`, aggregate candidate skill trails market, hourly/ten-minute weak-slot
gates are blocked, source/missingness location gates are blocked, and eight F
markets remain blocked.

### 4. Important model bug fixes and calibration repairs

Closed model-focused items fixed or gated several real issues:

- item 179 removes validation leakage from feature-model tuning;
- item 180 routes missing features through the imputer instead of unit-unsafe
  literals;
- item 181 removes forecast double-counting from the ML path and gates fallback
  behavior;
- item 183 clusters correlated fallback forecasts;
- item 184 adds per-market fallback priors;
- items 193-197 quarantine bad current highs and improve warm-tail/lock-in
  controls;
- item 200 makes model explanations first-class.

These are directionally right and reduce several known sources of skew. The
important caveat: code-level fixes are not the same thing as production skill.
The current active pooled artifact and served distribution still need to clear
the same market-relative gates.

### 5. Better trading evidence discipline

Closed trading and taker items, especially 162, 164-167, 192, 209, 214, and
234, moved the bot away from promotional MTM fantasy and toward settlement-only
quality.

Item 234 is particularly important. The June 21 run showed positive MTM but
settlement-scored negative PnL, and June 19 had the same sign-flip shape. The
closed fix now keeps MTM visible as provisional telemetry while blocking it from
quality, promotion, default selection, and profitability claims.

This is progress in honesty, not proof of profitable trading. Items 235-241 are
still open because bad low-price/warm-tail fills, strategy-family loopholes,
canary requalification, full daily bakeoffs, settlement liveness, fee/slippage,
and no-trade market benchmarks are not finished.

## Where The Model Is Now

The active no-market weather model has useful signal, but not broad market
edge.

The main failure is early local-day winner under-centering. Current hourly
evidence shows the `00:00-08:00` window has model Brier `0.0670` versus market
`0.0511`, winner probability `29.4%` versus market `43.5%`, and the hourly gate
blocks because early-hour Brier trails market by `0.0159`. The worst hours are
`03:00`, `04:00`, and `05:00`.

The ten-minute gate shows the same shape: weak slots cluster from `03:00` to
`05:50`, model Brier is `0.0721` versus market `0.0592`, and model winner
probability is `24.2%` versus market `34.6%`.

Location performance is uneven. The latest location audit finds top locations
near market, but Miami, NYC, and Seattle remain weak. Those bottom locations
are still bad even when sources are fresh, so source freshness alone is not the
fix. The CLOB raw overlay helps the bottom cohort, but it is market-informed
and partial coverage, so it belongs in quote-risk logic, not in the no-market
weather-model promotion lane.

The current best posture is therefore:

- keep broad F-family cutover blocked;
- allow only location-specific promotion where gates pass;
- keep market-informed overlays separate from weather-model skill claims;
- treat early-hour and bottom-location centering as the main model repair;
- require active served-artifact evidence before any broad improvement claim.

## What The Closed Items Tell Us About Direction

The direction is mature and empirically honest:

1. The roadmap is now gate-driven instead of narrative-driven.
2. Market-relative skill is the benchmark.
3. No-market weather skill and market-informed trading overlays are separated.
4. Runtime identity, live-forward SLO, data freshness, and evidence provenance
   are first-class.
5. Model changes are increasingly judged by hard slices: hour, ten-minute slot,
   market, source state, missingness, exact band, settlement distance, and
   bottom-location winner mass.

The weak spot in direction is volume and complexity. The roadmap has many
closed gates and many active gates. That is correct for safety, but it creates a
risk that we keep adding diagnostic structure instead of forcing the model to
win a small number of decisive battles.

## What Still Needs To Happen

### P0: prove or reject the active weather model on hard slices

Do not broaden serving until the same active artifact clears:

- hourly early gate,
- ten-minute weak-slot gate,
- exact-band and settlement-distance-zero gates,
- bottom-location gates for Miami, NYC, Seattle,
- source/missingness gates,
- aggregate and daily-first market-relative promotion gates.

### P0: finish active-schema retrain and validate what is served

Items 178, 224, and 233 show the right target: the distribution validated in
replay must be the distribution served in production. The remaining work is a
current-schema active artifact plus active replay-contract evidence, not a row
export surrogate.

### P0: convert early-hour repairs into candidate artifacts

The predawn/item147 direction is promising, but it needs to be a real candidate
lane with market, hour, ten-minute, ramp, late-day, and bottom-location
guardrails. A broad sharpening pass is not enough; the failure is centering on
the eventual winner.

### P1: repair live-forward proof

Current closed work added SLOs, preflights, supervisors, and recovery reports,
but the live-forward proof is still blocked by operational evidence: CLOB
freshness, current-code soak, runtime identity segmentation, and daily learning
blockers. Production proof requires a clean active day.

### P1: finish trading/taker fail-closed work

Items 235-241 should remain ahead of any live-profit claim. The bot needs
settlement-only quality, bad-tail no-go gates, universal current-high/warm-tail
guards, canary demotion/requalification, full champion/challenger bakeoff,
settlement finalization liveness, fee/slippage/depth modeling, and market
no-trade benchmarking.

### P2: continue source expansion only behind isolated gates

More data can help, but the current bottleneck is not "add every source." It is
proving which source family improves a known slice without averaging away bad
markets. Soil, radiation, SST, ECMWF/ML-NWP, NBM, smoke, and reanalysis work
should stay behind isolated replay gates.

## Final Evaluation

The closed roadmap items show strong engineering progress and a healthier
model-development culture. We now have an auditable, fail-closed system that is
much harder to fool.

The model itself is not yet where it needs to be. It is useful, measured, and
partially promotable by location, but broad weather-only edge remains unproven.
The hardest failures are early-hour winner under-centering, bottom-location
performance, exact-band calibration, and live-forward evidence reliability.

The right next move is not another broad roadmap expansion. It is to force the
active weather model through the current gate stack on the hard slices, promote
only the markets that pass, and keep trading claims settlement-only until
after-fee, after-slippage, benchmarked evidence exists.

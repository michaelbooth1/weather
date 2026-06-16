# Multi-Variant Shadow Test Design

Date: 2026-06-15

Roadmap conversion: this research design is now split into roadmap items
69-73:

- Item 69: multi-variant shadow harness and experiment governance.
- Item 70: exact-winner catch-up candidate.
- Item 71: dynamic source-freshness model variant.
- Item 72: market-aware CLOB overlay variant.
- Item 73: conservative per-market candidate bridge.

## Decision

Testing multiple model variants per location is useful, but only as a
pre-registered shadow experiment. It does not create more independent labels:
one location-day still settles once, and the band rows inside that day are
highly correlated. The value is paired counterfactual data: every variant sees
the same snapshots, source state, market prices, and eventual settlement, so
variant deltas are cleaner than comparing different days or ad hoc reruns.

The current F-family evidence supports a small multi-variant test. The pooled
candidate is better than current serving on pinned rows, but not better than the
market:

- Candidate Brier: 0.0436.
- Current replay Brier: 0.0454.
- Market Brier: 0.0379.
- Delta versus current: -0.0017.
- Delta versus market: +0.0057.
- Promote-ready markets: Atlanta, Denver, Houston.
- Shadow markets: Austin, Chicago, Dallas, Los Angeles, Miami, NYC, San
  Francisco, Seattle.

This means broad random model search would add noise. Targeted variants against
the known gap cells should improve learning speed.

## Where Extra Variants Become Noise

Avoid treating 67k band rows as 67k independent experiments. The useful sample
unit is closer to market-day, cutoff block, and disagreement case, not raw rows.
At present most F markets have only four settled days in the current promotion
corpus, so too many simultaneous variants will overfit day composition.

The largest false-discovery risks are:

- Many minor hyperparameter variants with no distinct hypothesis.
- Letting market-informed variants compete directly with no-market variants
  for "model edge" claims.
- Choosing winners from row-weighted aggregate Brier while ignoring per-market
  and per-day behavior.
- Re-tuning after every settled day without a frozen evaluation window.
- Promoting a variant that only wins one high-leverage market-day or one
  correlated taxonomy cell.

## Experiment Rules

Run at most four non-control shadow variants per family for the next evaluation
window. Freeze variant definitions before collection starts, then score by
paired replay on the same pinned corpus.

Use these primary gates:

- Primary metric: daily-first equal-day Brier delta versus current serving.
- Secondary metric: Brier delta versus market, reported separately.
- Calibration: ECE and winner-band catch-up, especially exact bands.
- Robustness: per-market action table, cutoff-hour slices, settlement-distance
  slices, source-freshness slices, and CLOB taxonomy slices.
- Minimum evidence: do not promote from fewer than two additional settled days
  beyond the frozen start date for a market; prefer at least 8-10 market-days
  before changing broad family behavior.

Keep no-market and market-informed tracks separate. A CLOB/market-informed
variant can be useful for quoting, but it should not be used as evidence that
the weather model independently beats the market.

## Recommended Variant Set

### V0: Current Serving Control

Purpose: immutable baseline.

This is the replayed current model already captured by the promotion gauntlet.
It must stay in every comparison so candidate deltas are paired and auditable.

### V1: Pooled F v0.3 Base Candidate

Purpose: current champion no-market candidate.

Use the existing `feature_model_hgb_f_pooled_v0_3.pkl` path as the main shadow
candidate. This is the model already proving aggregate improvement over current
serving while still trailing market prices.

Success condition: continue to beat current replay globally and avoid any
market-level `BLOCK`. Promotion remains per-market only.

### V2: Exact-Winner Catch-Up Variant

Purpose: attack the largest model-vs-market gap directly.

The biggest current gap is settlement distance 0: candidate Brier 0.3587 versus
market Brier 0.2827. That says the model is still under-allocating probability
to the eventual winning exact/range band when compared with market prices.

Design:

- Start from V1.
- Add a post-model exact-band calibration layer or train-time sample weighting
  that focuses on the true winning exact/range band and near-floor adjacent
  bands.
- Condition the adjustment on source agreement, high-so-far/floor distance,
  remaining forecast ceiling, source-freshness state, and cutoff hour.
- Do not use live market price as an input in this variant.

Target slices:

- settlement_distance = 0.
- band_type = eq.
- cutoff hours 7-15.
- Seattle, NYC, Miami, and Chicago, where market-relative gaps are meaningful.

Failure mode to watch: stealing too much probability from the one-above band.
The variant must not worsen settlement_distance = 1, where V1 currently beats
the market.

### V3: Dynamic Source-Freshness Variant

Purpose: make stale/missing live source state trainable instead of just
diagnostic.

Current reports show gaps in source-freshness and CLOB taxonomy cells,
especially `failed:wu_history`, stale METAR states, and `wu_lag_catchup_miss`.
The base pooled artifact includes static source-reliability priors, but the
candidate replay source-freshness table is still mostly diagnostic.

Design:

- Start from V1.
- Add live dynamic source-state features: WU history freshness, latest WU print
  minute/age, METAR age, forecast payload age, failed-source flags, and
  cross-source max disagreement.
- Train and score these as no-market weather/source features.
- Keep the Miami WU print-lag alias and high-has-stood lock-in behavior as
  fixed baseline logic, not as the only treatment.

Target slices:

- `failed:wu_history`.
- `failed:wu_history;stale:metar`.
- `stale:metar`.
- `wu_lag_catchup_miss`.
- 9-14 cutoff-hour windows where the current candidate regresses current.

Success condition: improve stale/failed-source slices without worsening
`all_fresh`, which is most of the sample.

### V4: Market-Aware CLOB Overlay Variant

Purpose: test whether order-book state adds useful quote-time signal.

This must be treated as market-informed and not compared as a no-market edge
claim. The current raw CLOB overlay is promising on eligible rows: micro Brier
0.0303 versus base candidate 0.0376 and market 0.0299. The taxonomy-gated
overlay currently affects only 437 rows and has nearly zero aggregate effect.

Design:

- Start from V1.
- Keep the CLOB overlay out-of-fold and taxonomy gated.
- Expand only predeclared taxonomies if they pass replay gates, with separate
  thresholds for delta versus base and delta versus market.
- Track both raw overlay and gated overlay, but only the gated version is
  eligible for operational use.

Target slices:

- `market_lead`.
- `book_liquidity_artifact`.
- Future candidates for `boundary_rounding_error` and `stale_source`, only if
  they meet minimum rows and paired replay gates.

Failure mode to watch: better Brier but worse log loss from overconfident book
signals. Keep log loss and calibration in the gate.

### V5: Conservative Bridge Variant

Purpose: distinguish architecture weakness from per-market overpromotion.

Some shadow markets are not failing in the same way. Dallas and San Francisco
are effectively tied with current. Miami is worse than current. Seattle and NYC
beat current but trail the market badly. A bridge variant can test whether a
more conservative candidate/current blend improves reliability while the richer
variants mature.

Design:

- Start from V1.
- Use predeclared per-market candidate alpha values.
- Keep Atlanta, Denver, and Houston near full candidate weight.
- Keep Miami, Dallas, and San Francisco near current-serving fallback.
- Use partial candidate weight for Austin, Chicago, Los Angeles, NYC, and
  Seattle.

This is not the most scientifically interesting variant, but it is operationally
useful. It can show whether shadow-market pain is from the pooled artifact
itself or from aggressive cutover policy.

## Priority

Use V0 and V1 always. Add V2 and V3 first because they are no-market variants
that attack the largest current accuracy gaps. Add V4 as a separate
market-informed track for quoting decisions. Add V5 only if operational
stability matters more than isolating new weather signal.

Do not run a broad grid of HGB depths, temperatures, bridge alphas, and overlay
taxonomies live. Run those offline on the promotion corpus, then graduate one
or two clearly different variants into shadow collection.

## Implementation Shape

The current `pooled_candidate_replay` path accepts one candidate artifact at a
time. The clean extension is a multi-variant shadow runner that writes one
long-form table:

- `variant_id`
- `variant_family`
- `market_id`
- `snapshot_id`
- `band_key`
- `probability`
- `uses_market_features`
- `artifact_hash`
- `postprocess_config_hash`

Reports should pivot this table into paired deltas. The promotion refresh can
continue to promote only one candidate per market, while the multi-variant
report decides which variant graduates to the single-candidate promotion slot.

The key design constraint is that variants are logged, not served, until replay
and promotion gates prove them on future settled days.

# 70. Exact-Winner Catch-Up Candidate [COMPLETE 2026-06-16 - WHITELIST ALPHA GUARDRAIL PASSED]

Goal: close the largest current model-vs-market gap by improving probability on
the eventual winning exact/range settlement band without using live market price
as a model input.

Source: `docs/research/MULTI_VARIANT_SHADOW_TEST_DESIGN_2026-06-15.md`.
The 2026-06-15 promotion refresh shows the F-family pooled candidate beats
current serving overall but badly trails market prices on settlement-distance-0
rows: candidate Brier `0.3587` versus market Brier `0.2827`.

Why this is missing: the pooled F v0.3 candidate improved aggregate replay, but
the market is still much better at concentrating probability on the eventual
winning exact/range band. The current gap drivers point to exact bands,
settlement-distance-0 rows, and early-to-midday cutoff hours rather than a
generic model-capacity problem.

Design:

Build this as an opt-in no-market postprocess layer for the pooled direct
market-band model. It should reuse the existing band-row feature context rather
than looking at market prices or settled outcomes at inference time. The first
artifact-level switch is `exact_winner_catchup_enabled`; if absent or false,
existing v0.3 artifacts keep identical behavior.

The calibration layer fits multiplicative factors on held-out band rows using
only contexts available at inference:

- exact/range bands only (`band_kind = eq`),
- high-so-far/floor distance via `band_mid_minus_high_so_far`,
- forecast distance via `band_mid_minus_forecast`,
- cutoff-hour bucket,
- band width,
- market id and static source-trust bucket.

Dynamic source-freshness state is intentionally deferred to item 71; this item
should expose a context slot for source state when present, but it must not
pretend historical source-freshness parity exists before item 71 ships.

The layer must be evaluated as a separate item-69 variant, not silently blended
into current promotion. It can graduate to the single promotion slot only after
paired shadow replay proves it improves settlement-distance-0 and exact-band
rows without worsening the one-above/adjacent slice.

- [x] Build a no-market variant from the pooled F v0.3 baseline with either a
  post-model exact-band calibration layer or train-time weighting focused on
  winner exact/range bands and near-floor adjacent bands.
- [x] Condition the adjustment on source agreement, high-so-far/floor distance,
  remaining forecast ceiling, source-freshness state, cutoff hour, and market
  climate/source-trust context.
- [x] Target the failure slices explicitly: `settlement_distance = 0`,
  `band_type = eq`, cutoff hours 7-15, and the Seattle/NYC/Miami/Chicago
  shadow-market gap cells.
- [x] Add guardrails proving the variant does not steal too much mass from the
  one-above band, where the current candidate is already better than the
  market.
- [x] Score the variant through item 69's multi-variant shadow table before it
  can become the single promotion candidate for any market.
- [x] Report ECE, winner-band catch-up probability, and per-day paired Brier so
  a win cannot be driven by one high-leverage market-day.

Acceptance: a no-market exact-winner catch-up variant improves
settlement-distance-0 and exact-band replay versus the pooled F baseline,
does not regress adjacent/one-above bands or per-market promotion gates, and
has enough future paired shadow evidence to justify per-market promotion.

Implementation update 2026-06-15:

- Added an opt-in `exact_winner_catchup_enabled` postprocess layer to
  `weather.calibration.pooled_feature_model`.
- Added `pooled_feature_band_hgb_v0.4` for the exact-winner candidate artifact;
  v0.3 behavior remains unchanged when the switch is absent or false.
- Fitted catch-up factors use inference-available exact-band contexts:
  market id, cutoff-hour bucket, high-so-far/floor gap, forecast gap, band
  width, static source-trust bucket, and an optional source-state slot.
- Dynamic source-freshness parity is still owned by item 71, so item 70 does not
  claim historical freshness-aware scoring yet.

Verification 2026-06-15:

- `.\venv\Scripts\python.exe -m pytest tests\calibration\test_pooled_feature_model.py -q`
  passed.
- `.\venv\Scripts\python.exe -m pytest tests\reporting\test_multi_variant_shadow.py tests\operations\test_schema_registry.py tests\operations\test_import_architecture.py -q`
  passed.
- `.\venv\Scripts\python.exe -m src.schema_registry audit --strict --paths src\weather\calibration\pooled_feature_model.py src\weather\reporting\multi_variant_shadow.py src\weather\schema_registry.py`
  passed.

Smoke evidence 2026-06-15:

- Bounded pipeline artifact:
  `artifacts\models\hgb\feature_model_hgb_f_pooled_exact_winner_smoke.pkl`,
  trained with `--exact-winner-catchup --holdout-year 2024
  --max-days-per-market 30`.
- Smoke replay corpus:
  `data\backtest\item70_71_smoke_corpus.json` with Atlanta and Austin
  2026-06-07 settled market-days.
- Candidate item-69 CSV:
  `data\backtest\item70_exact_winner_shadow_variants_smoke.csv`.
- Joint item-69 smoke report:
  `data\backtest\item70_71_smoke_multi_variant_shadow_report.md` returned
  `OK` with 6,160 scored rows and zero governance warnings.
- Smoke result: exact-winner Brier `0.0399` versus current `0.0318` and market
  `0.0445`; it beat market on this subset but regressed current, so it remains
  a shadow-only research lane.

Full replay evidence 2026-06-16:

- Full artifact:
  `artifacts\models\hgb\feature_model_hgb_f_pooled_exact_winner_v0_1.pkl`
  (`pooled_feature_band_hgb_v0.4`, artifact hash prefix `cf1a385b2f92`).
- The artifact applies the exact-winner catch-up at `strength = 1.0`, then
  uses a conservative no-market incumbent blend: default `alpha = 0.0`, with
  `alpha = 0.10` only for Chicago, Houston, NYC, and Seattle. The fitted
  guardrail stores a one-above tolerance of `0.0002`.
- Replay report:
  `data\backtest\item70_exact_winner_full_replay_report.md`; JSON:
  `data\backtest\item70_exact_winner_full_replay.json`.
- Item-69 shadow CSV:
  `data\backtest\item70_exact_winner_shadow_variants_full.csv`.
- Item-69 report:
  `data\backtest\item70_exact_winner_multi_variant_shadow_report.md` returned
  `OK` with 67,430 scored rows, 44 market-days, 11 markets, and zero
  governance warnings.
- Replay verdict: `PASS_WITH_SHADOWS` / `PER_MARKET_ONLY`.
- Aggregate result: candidate Brier `0.043001` versus current `0.043554`
  (`-0.000553`) and market `0.037869` (`+0.005132`).
- Item-69 daily-first result: candidate Brier `0.042944` versus current
  `0.043496` (`-0.000552`) and market `0.037830` (`+0.005114`).
- Target slices improved: settlement-distance-0 `0.344160` versus current
  `0.348648`, exact-band rows `0.052056` versus `0.052717`, cutoff hours 7-15
  `0.061296` versus `0.062060`, and combined target failure slice `0.474686`
  versus `0.489979`. Winner exact-band mean probability rose above current
  (`0.532622` versus `0.529733`).
- Guardrail slices cleared within the predeclared tolerance:
  one-above/adjacent improves by `-0.000052` Brier versus current
  (`0.071353` versus `0.071406`) while beating market by `-0.015523`;
  distance-2 improves (`0.021187` versus `0.021587`); and there are no
  per-market `BLOCK` verdicts. Seattle, NYC, and Chicago target-market cells
  improve, while Miami is unchanged versus current (`0.025046` versus
  `0.025046`).
- The completion claim is limited to the no-market shadow candidate and its
  conservative alpha guardrail. It is not a global serving promotion; widening
  alpha still requires fresh paired evidence through item 69.

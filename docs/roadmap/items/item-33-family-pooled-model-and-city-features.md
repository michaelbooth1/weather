# 33. Family-Pooled Model + City Features [COMPLETE 2026-06-15 - PIPELINE LIVE, READINESS SPLIT TO ITEM 48]

Goal: train on all cities in a unit family, not one (audit Option A).

- [x] Add city features to the pooled training path (market one-hot,
  climate-normal, latitude/longitude, coastal flag, high-so-far anomaly, and
  forecast anomaly).
- [x] Add a pooled training mode (`src.pooled_feature_model`) that iterates a
  unit family's specs, concatenates records, and trains one HGB bundle per
  cutoff hour.
- [x] Train the F family on all 11 US cities; keep Toronto/C as its own family.
- [x] Validate per-market on replay + trust before cutover; per-market
  HGB-vs-empirical gate.
- [x] Train a v0.2 pooled/F candidate with direct market-band objective,
  hard/support floor calibration, late-day lock-in, and snapshot partition
  normalization.
- [x] Clear `src.pooled_candidate_replay` per market before any serving hook.

Acceptance: the pooled F model beats the NYC-only HGB on per-market replay/trust
without regressing NYC.

Status update (2026-06-15 UTC): item 33 is complete as the family-pooled
pipeline work item. The remaining proof that F-family markets are ready for
broader promotion is explicitly tracked by item 48, so this item no longer
owns those readiness blockers.

Pooled F starter (2026-06-11): built `src.feature_model_hgb_f_pooled.pkl` as a
non-serving research artifact plus
`data/backtest/f_family_pooled_model_report.md`. Dataset: 66,669 rows across
the 11 F markets using `toronto_feature_store_v0.3` and 14 cutoff models.
Holdout-year 2025 validation is intentionally not promotion-grade yet: some
hours remain weak even after support-wide smoothing, so this artifact should
feed the next model iteration and gauntlet comparison, not live serving.

Pooled candidate replay (2026-06-11): added `src.pooled_candidate_replay`
plus `tests/test_pooled_candidate_replay.py`, then ran the pinned promotion
corpus against `src.feature_model_hgb_f_pooled.pkl`. Coverage was complete:
16,940 F-family band rows, 1,540 F snapshots, and zero missing candidate rows.
The verdict was **BLOCK / DO_NOT_CUT_OVER** in
`data/backtest/pooled_candidate_replay_report.md`: aggregate candidate Brier
`0.1370` versus current replay `0.0429` and market `0.0384`; all 11 F markets
blocked by candidate-vs-current regression. The gate worked and the artifact
is confirmed as research-only. The next Item 33 work is a v0.2 candidate whose
training objective/calibration is aligned to replayed market-band probability,
especially exact settlement-distance-0 buckets and late-day lock-in.

Pooled band v0.2 (2026-06-11): trained
`src.feature_model_hgb_f_pooled_v0_2.pkl` with schema
`pooled_feature_band_hgb_v0.2`, prediction mode `band_binary`, and objective
`binary_market_band_brier`. Unlike v0.1, this model trains directly on
synthetic market-band outcomes (`eq`/ranges, `lte`, `gte`) from historical WU
feature rows, then applies deterministic WU hard floors, soft live-support
floors from replay inputs, late-day lock-in, and per-snapshot partition
normalization. Holdout exact-winner mean probability now reaches `0.56-1.00`
by hour and late-hour holdout Brier collapses near zero in
`data/backtest/f_family_pooled_band_model_report.md`.

Adjacent calibration + bridge result (2026-06-11): v0.2 now carries a
holdout-trained above-floor adjacent/range calibration table with `262`
market/hour/floor-gap contexts, and `src.pooled_candidate_replay` applies the
artifact's configured incumbent bridge after partition normalization. The five
markets that previously blocked on adjacent/range leakage (Denver, Houston, Los
Angeles, NYC, Seattle) run at `0.20` pooled alpha until more settled days prove
the raw pooled probabilities; other F markets remain at full pooled alpha.

Pinned replay result: `data/backtest/pooled_candidate_replay_v0_2_report.md`
now scores the v0.2 artifact at aggregate Brier `0.0413` versus current replay
`0.0429`, recorded `0.0499`, and market `0.0384`. The verdict improved from
**BLOCK / DO_NOT_CUT_OVER** to **SHADOW_ONLY / DO_NOT_CUT_OVER**: all 11 F
markets clear the per-market regression gate, with no blocked markets and zero
missing candidate rows. No market is cutover-ready yet because every F market
still has only one pinned settled day and `15/100` trust, and several markets
remain behind the market-price Brier. The next Item 33/34 work is to collect
more F-family settled days, relax the incumbent bridge only when per-market
replay proves it, and move the secondary calibration/forecast/lag artifacts
from Toronto-only to F-family.

Pooled band v0.3 (2026-06-12): trained
`src.feature_model_hgb_f_pooled_v0_3.pkl` with schema
`pooled_feature_band_hgb_v0.3` and feature schema
`toronto_feature_store_v0.4`. v0.3 keeps the direct market-band objective and
adds static per-market source-reliability priors learned from WU-vs-METAR/ASOS,
GHCNh, and ERA5-style reanalysis overlaps. These are source trust features, not
same-day final redundant highs, so they do not leak the settlement into
intraday training rows. Fresh replay also showed that the old v0.2 artifact now
blocks Dallas under the current code path (`0.0703` candidate Brier versus
`0.0483` current replay), so v0.3 adds a Dallas incumbent bridge at alpha `0.0`
until more settled days justify relaxing it.

v0.3 pinned replay result:
`data/backtest/pooled_candidate_replay_v0_3_report.md` scores the new artifact
at aggregate Brier `0.0515` versus current replay `0.0686`, recorded `0.0499`,
and market `0.0384`, improving the refreshed v0.2 replay (`0.0538`) while
clearing all per-market regression gates. Verdict remains
**SHADOW_ONLY / DO_NOT_CUT_OVER** on the 2026-06-12 corpus: all 11 F markets
were shadow, none were blocked, every F market still had one settled pinned day
and `15/100` trust, and several markets remained behind market-price Brier.
This result is superseded for current decisions by the 2026-06-14
ledger/promotion refresh below.

Promotion-refresh automation (2026-06-12): added `src.promotion_refresh`, the
Item 33/37 path that turns newly finalized settled days into a fresh pinned
promotion corpus, refreshed `location_trust.json`, pooled-F candidate replay,
current-serving gauntlet, and machine-readable per-market actions. The pooled
candidate replay now also carries a global replay gate over corpus-pin warnings
and exact replay-identity fidelity, so candidate promotion fails closed when
the input pin or replay canary is bad.

Real refresh run:
`.\venv\Scripts\python.exe -m src.promotion_refresh` wrote
`data/backtest/f_family_promotion_refresh.json` and
`data/backtest/f_family_promotion_refresh_report.md` using corpus hash
`b69ba9f3ccf9b2cba46c278d5a63b6a1f8b2de11df419b354ceec7d4b8b9937e`
(`12` market-days, `1,680` snapshots, `18,480` band rows). The pooled v0.3
candidate stayed **SHADOW_ONLY / DO_NOT_CUT_OVER** with aggregate Brier
`0.0515` versus current replay `0.0686` and market `0.0384`; per-market
actions were `0` promote, `11` shadow, `0` blocked. Corpus pin passed, but
`identity_record_count` is still `0`, so the strict exact-identity canary
cannot be required until future settled captures include replay identities.

Ledger/promotion refresh (2026-06-14 UTC): `src.market_day_labels finalize`
eventually reconciled 105 total labels (`complete=54`, `partial=51`) with
Polymarket reconciliation `match=105`. `src.promotion_refresh` then rebuilt the
F-family corpus at hash
`0c3f02ca56c83a5099b156985fdb93e83209addae8bf02c2dffe07b185112339`
(`51` market-days, `6,989` snapshots, `76,879` band rows,
`3,363` identity records). Candidate verdict is
**PASS_WITH_SHADOWS / PER_MARKET_ONLY**: Atlanta, Denver, and Houston are
`PROMOTE_CANDIDATE`; Austin, Chicago, Dallas, Los Angeles, Miami, NYC, and
San Francisco, and Seattle remain `KEEP_SHADOW`; no candidate markets are
blocked. Aggregate candidate Brier is `0.0436`
versus current replay `0.0458` and market `0.0379`; this is a process/model
improvement but not a north-star edge claim. The remaining promotion-readiness
gaps are split into item 48, and the one-market Miami serving replay regression
is split into item 52.

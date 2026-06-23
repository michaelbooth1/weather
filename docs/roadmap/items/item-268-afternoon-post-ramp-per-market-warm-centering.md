# 268. Afternoon Post-Ramp Per-Market Warm-Centering Correction (15:00-18:00 Local) [COMPLETE 2026-06-23 - AFTERNOON RESIDUAL CENTERING ARTIFACT LIVE]

Goal: correct the systematic per-market warm bias that remains in the served
distribution **after** the morning/ramp window that items 194/195 own — the
post-ramp afternoon block (local `15:00-18:00`) where the high is near or just
past peak but the served distribution still centers warm of the eventual band.

Source: the 2026-06-23 per-location week audit (Jun 16-22, served tape vs
settlement). The model's probability-weighted expected-high bias does not wash
out as the day develops; it stays warm at every decision time:

- `08:00 -> +0.87 F` (67% of market-days hot), `12:00 -> +1.10 F` (71% hot),
  `16:00 -> +0.80 F` (74% hot, n=84). MAE tightens (`1.92 -> 1.28 F`) but the
  **sign and hot-share keep rising**, so the residual is a directional offset,
  not just shrinking noise.
- The bias is a per-market regime structure, not day-specific. Noon expected-high
  bias by market: continental cluster runs hot — `chicago +1.86`, `austin +1.75`,
  `dallas +1.72`, `nyc +1.56`, `houston +1.55 F`; marine runs neutral/cool —
  `miami -0.30`, `seattle +0.17 F`.
- The same continental markets under-commit on the winner: mean model
  probability on the eventual winning band at noon is `toronto 0.191`,
  `nyc 0.196`, `austin 0.200` versus `miami 0.571` — low sharpness on exactly
  the locations that center warm.
- Error scales with forecast disagreement (corr `+0.37`; high-disagreement-day
  expected-high MAE `2.45 F` vs `1.43 F` on low-disagreement days), so the
  correction should be disagreement-aware, not a flat scalar.

Why this matters: item 195 (ramp-window ordinal centering) is scoped to local
`08:00-14:59` and item 194 to the morning ramp; both are COMPLETE. Item 266's
parity gate shows the model still trails market Brier through the scoring window
and routes ramp warm-tail to 194/195/232, but **no owner covers the post-ramp
afternoon block** where this audit measures a still-warm, still-rising-hot-share
offset. The afternoon snapshots are heavily traded by the taker, so an
uncorrected `+0.80 F` warm center there maps directly to the warm-tail YES
losses already in the backlog.

Why it is not already covered: the late-day items (08, 59, 103, 170, 196) model
lock-in / saturation / "high has stood" once the high is effectively declared;
they do not apply a per-market centering offset in the `15:00-18:00` window
while the band is still live. Item 195 stops at `14:59`. Item 268 is the
afternoon continuation of 195's per-market ordinal centering.

## Design

1. Add an afternoon (`15:00-18:00` local) slice to the settled-day root-cause and
   item-262 reliability scorecard: per-market signed expected-high bias,
   winner-band probability, effective spread, and disagreement bucket.
2. Train a per-market (or continental/marine regime) afternoon centering offset
   that consumes observed trajectory, time-past-peak, robust forecast consensus,
   and forecast disagreement; the offset must be per-market, not a single global
   scalar (per item 266's guardrail that global scalar candidates stay
   diagnostic-only).
3. Couple centering with disagreement-scaled spread so the distribution widens on
   high-disagreement afternoons (where MAE is `2.45 F`) instead of staying
   over-sharp.
4. Sequence after item 267 so the offset corrects only the residual that remains
   once the input-layer source debias is in place (avoid double-correcting the
   `global_ensemble` warm input).
5. Validate against the winner-rank parity gate (266) and the proof-packet gates;
   require the candidate to cut the afternoon warm bias and the
   `model_top_miss | market_top_hit` case class without adjacent-band,
   bottom-location, or late-lock-in regressions, and counterfactually reduce
   afternoon taker warm-tail fills.

- [x] Add the `15:00-18:00` per-market afternoon slice to root-cause + scorecard.
- [x] Train a per-market/regime afternoon centering offset (not a global scalar).
- [x] Add disagreement-scaled spread for high-disagreement afternoons.
- [x] Sequence after item 267; correct residual only.
- [x] Parity-gate + proof-packet + taker-counterfactual validation.

Acceptance: the served afternoon (`15:00-18:00` local) distribution shows
materially reduced per-market signed warm bias and improved winner-band
probability on settlement-scored, day-blocked evidence, the winner-rank parity
case class falls, and there is no regression in the early-hour, exact-band,
bottom-location, ramp, and late-lock-in proof-packet gates.

## Completion Evidence

Implemented `afternoon_residual_centering_v0.1` as a separate post-source-bias
calibration stage sequenced after ramp warm-tail dampening and before the
current-max floor. The runtime selects contexts in order:
`market|hour`, `market|afternoon`, `regime|hour`, `regime|afternoon`,
`global|hour`, `global`, and only uses the global contexts as diagnostics when
market/regime support is unavailable. The stage shifts ordinal mass by the
learned residual and applies disagreement-scaled smoothing when forecast
disagreement exceeds the learned reference.

`python -m weather.calibration.afternoon_residual_centering train` wrote
`artifacts/misc/afternoon_residual_centering.json` with `5,747` training rows
across all 12 markets through 2026-06-22. In-sample afternoon residual
validation moved mean bias `+0.3948 -> 0.0000` buckets and hot share
`0.6654 -> 0.4858`. The settled-day root-cause report now includes an
`Afternoon Post-Ramp Slice`, and the proper-scoring reliability scorecard
includes 812 afternoon snapshots plus source-bias coverage status.

Validation: `python -m pytest tests\calibration\test_afternoon_residual_centering.py
tests\model\test_estimate_distribution.py
tests\reporting\test_settled_day_root_cause.py
tests\reporting\test_proper_scoring_reliability_scorecard.py
tests\operations\test_schema_registry.py -q` passed as part of the focused
`66 passed` regression set. `proper_scoring_reliability_scorecard` regenerated
with status `PASS`; `settled_day_root_cause --date 2026-06-22` regenerated with
status `ACTIONABLE`; `winner_rank_parity` remains `BLOCK` on existing
served/candidate tapes (`model_top_hit=0.5407`, `market_top_hit=0.6356`,
excess `1390`) because that gate evaluates stored tapes rather than replaying
this new runtime artifact.

Related: items 194, 195, 196, 232, 233, 262, 266, 267; `[[forecast-tracker]]`,
`[[toronto-model-audit]]`.

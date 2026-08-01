# Workstation repair-replay handback — 2026-08-01

## Verdict

Both named experiments were run once, replay-only, from `de559d5a` on topic
branch `codex/workstation-repair-replays-2026-08-02c`. Neither candidate earns
another run:

| Lane | First-run result | Recommendation |
| :--- | :--- | :--- |
| `audit_exact_band_winner_centering_replay` | The audited snapshot improves slightly, but the 64–65 F band regresses the incumbent across the pinned day and winner top-hit remains 93/99. | **RETIRE** |
| `audit_warm_tail_dampening_replay` | The audited snapshot improves slightly, but the 66–67 F band and whole pinned day both regress the incumbent; the whole day also trails the market. | **RETIRE** |

This is a null repair result, not a request to tune. No serving, promotion,
pointer, release, scheduler, capture, mirror, ACL, or production artifact was
changed. `automatic_model_or_trading_change_allowed=false` remains binding for
both review rows.

## Declared input range and freshness assertion

Both replays read exactly one target date: **2026-06-07 through 2026-06-07**,
Seattle only. They read no July or August date.

Freshness gate: **PASS**.

- Mirror folder:
  `data/snapshots/highest-temperature-in-seattle-on-june-7-2026`.
- Settlement: `65 F`, `quality_grade=complete`,
  `settlement_source=daily_summary`,
  `resolution_source_type=wunderground_history`, and
  `promotion_countable=true`.
- Pinned corpus:
  `promotion_corpus_v0.1`, semantic hash
  `4c5b60d2c9b42c33829249fa7938c6acc4a42bc6e6dcfac0d382fc8703fe10ff`,
  one market-day, 99 snapshots, and 1,089 band rows.
- The review case snapshot `20260608T025542-0400` is present in both the tape
  and captured replay inputs. Its pinned replay-record hash is
  `4cfc31edf9121524e052aed8778be0e74c4b344b8b2ec34427e1b5a76d76003d`;
  its pinned tape-row hash is
  `5bbb97f94cd58aa5b855b86a07ac2234ee95d222516ba0f4a759e3ce9721a7ed`.
- Whole-file SHA-256 identities were recorded before handback:
  `snapshots_long.csv` =
  `6c1c1dd7798a68635cc06b5913c8f40f047c59e7abca1ee1d2efbeba70c265f2`,
  `replay_inputs.jsonl` =
  `d682b730831006091755527f0cf1ce0a95bff427cf477889d1972dab23587eea`,
  and `settlement.json` =
  `6c091beb5b17bca78f94e5143d0d90b3f5c29bac0c2eeda84b801d068283a372`.
- Both replay reports say all pinned tape/replay hashes matched, with zero
  corpus warnings, 1,089/1,089 candidate rows, zero missing candidate rows,
  zero feature errors, and zero missing hour models.

The mirror's global horizon was deliberately ignored, as instructed. Nothing
was refreshed or written in the mirror.

## Leakage and boundary audit

Feature/outcome leakage: **PASS**. Evaluation independence: **development-only,
not promotion evidence**.

- Each candidate can see only the captured sources available in its replay
  record at that checkpoint, its frozen no-market model/postprocess state, and
  static historical priors. Both exported variants declare
  `uses_market_features=false`. Market probability and the settlement outcome
  are scoring fields, not model features.
- Pooled model fitting uses `historical_target_cache()`'s serving-safe
  prior-year target-season cache. Current-year rows are excluded by default;
  both training reports use a 2025 holdout. The 2026-06-07 settlement was not a
  training row.
- The candidate files and all policy constants were frozen before this run.
  There was no parameter search, outcome-conditioned branch, or rerun after
  seeing a score.
- The historical Item 147 and Item 232 development reports already include
  Seattle 2026-06-07 in their broad replay corpus. Therefore this replay is an
  honest test of the two already-declared audit cases, but it is not an
  independent unseen-day or promotion claim. The result is intentionally
  classified as replay-only development evidence.
- `rows[-1]` boundary: **PASS**. Both candidate and incumbent probabilities
  were regenerated together after the 2026-07-31 boundary from the same
  pinned corpus and the same `de559d5a` code. No pre-boundary result rows were
  spliced into either comparison. The old reports were read only for frozen
  variant provenance.
- Replay fidelity reports correctly warn that these are changed-model-version
  snapshots, not exact-identity canaries. Corpus integrity still passes, and
  the recorded 2026-06 probability is reported below only as context—not as
  the regenerated incumbent.

## Lane 1 — exact-band / winner-centering

Review row: `audit-review-seattle-92631cf037`; band `64-65 F`; direction
`market_higher_than_model`.

Exact frozen variant:

- Artifact: `item147_hour7_no_austin_exact_winner_candidate.pkl`.
- SHA-256:
  `5054d4b49bae7a7dd4042c239289907ac5acbea9ddc8fada0fce7123affe09ac`.
- Model schema `pooled_feature_band_hgb_v0.4`; training feature schema
  `toronto_feature_store_v1.3`; trained at
  `2026-06-16T02:41:47.631674`.
- Fixed policy:
  `hour7_forecast_centering_no_austin_with_item70_exact_winner_catchup`;
  hour-7 forecast-centering alpha `0.4`, sigma `1.25`, 784 exact-winner
  contexts at strength `1.0`, and Seattle current-blend alpha `0.2`.

Measured result:

| Scope | Candidate Brier | Incumbent Brier | Market Brier | Δ vs incumbent | Δ vs market |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Full pinned Seattle day, 1,089 band rows | 0.012021 | 0.010566 | 0.016325 | **+0.001455** | -0.004304 |
| 64–65 F winner band, all 99 checkpoints | 0.084901 | 0.072551 | 0.119977 | **+0.012350** | -0.035076 |
| Audited 02:55 snapshot only | 0.000005283 | 0.000008186 | 0.000000250 | -0.000002903 | +0.000005033 |

On the 99-checkpoint winner-band slice, mean candidate probability is
`0.781358` versus incumbent `0.806934` and market `0.730056`. Winner top-hit is
`93/99` for both candidate and incumbent versus `99/99` for the market. At the
single audited snapshot, the regenerated candidate is `0.997702`, incumbent
`0.997139`, and market `0.999500`; the historical recorded model was
`0.274247`.

Recommendation: **RETIRE**. The tiny audited-snapshot gain does not survive the
declared replay day. The candidate reduces winner mass, does not improve
top-hit, and materially regresses the current incumbent on the target band.

## Lane 2 — warm-tail dampening

Review row: `audit-review-seattle-ad4416de86`; band `66-67 F`; direction
`model_higher_than_market`.

Exact frozen variant:

- Artifact: `current_max_trust_retrain_merged_candidate.pkl`.
- SHA-256:
  `95a1298ec744299a5dfab7aa0ab861816bf6f877a50555dfe5cd616942683934`.
- Model schema `pooled_feature_band_hgb_v0.3`; feature schema
  `toronto_feature_store_v1.15`; trained at
  `2026-06-23T11:43:46.506393`.
- Fixed policy `item232_current_max_trust_warm_tail_backoff_v0_1`: candidate
  alpha `0.35` for warm-side pressure, alpha `0.35` when the band midpoint is
  at least 2 F above the printed floor, and alpha `0.5` for support-only,
  quarantined, or pre-reset current-max disposition. Seattle current-blend
  alpha is `0.2` outside those context overrides.

Measured result:

| Scope | Candidate Brier | Incumbent Brier | Market Brier | Δ vs incumbent | Δ vs market |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Full pinned Seattle day, 1,089 band rows | 0.020099 | 0.010566 | 0.016325 | **+0.009533** | **+0.003774** |
| 66–67 F rejected band, all 99 checkpoints | 0.007792 | 0.005537 | 0.005557 | **+0.002255** | **+0.002235** |
| Audited 02:55 snapshot only | 0.000005248 | 0.000008179 | 0.000000250 | -0.000002930 | +0.000004998 |

On the 99-checkpoint target-band slice, mean candidate probability is
`0.066961` versus incumbent `0.043444` and market `0.059045`: the supposed
dampener allocates more, not less, to the losing warm band. At the single
audited snapshot, candidate probability is `0.002291`, incumbent `0.002860`,
and market `0.000500`; the historical recorded model was `0.724665`.

Recommendation: **RETIRE**. The isolated audited-snapshot movement is real but
does not generalize even across the same pinned day. The candidate worsens the
target band versus both references and fails the full-day incumbent and market
guardrails.

## Outputs and execution controls

All generated outputs are under the single declared run root:
`scratch/runs/repair-replays-2026-08-02c`.

The primary JSON artifacts are:

- `audit_exact_band_winner_centering_replay.json`
- `audit_warm_tail_dampening_replay.json`

Each has a matching Markdown report, current-replay report, and variant-row
CSV in that run root. Replay cache was `off`; candidate-side overlays were
disabled; the run did not write `data/`. There was one successful scoring run
per candidate. An earlier CLI invocation stopped in argument parsing before
reading or scoring a case and produced no model result.

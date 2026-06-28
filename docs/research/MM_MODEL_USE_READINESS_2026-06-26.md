# Market-Making Model-Use Readiness

Date: 2026-06-26 local / 2026-06-27 UTC

Scope: repo-grounded readiness check for how the weather model should affect the market-making bot while the near-term goal is liquidity-reward farming. This is a paper/shadow evidence document only. It does not authorize live orders, `live-pilot`, credentials, wallet funding, or model-skewed live quoting.

## Verdict

Current model evidence supports only conservative harvest research:

- In harvest mode, use the model as a veto, risk overlay, band selector, stale-input detector, and post-run diagnostic signal. Do not use it as the quote center.
- In edge mode, keep model-skewed quotes in research only. They require per-slice known-edge permission, countable active-day paper evidence, positive execution markouts, independent days, locked policy parameters, complete fill evidence, and positive P&L after costs.
- For live capital, the current answer is `NO LIVE CAPITAL` and `NO MODEL-SKEWED LIVE QUOTING`.

The latest available evidence is not promotion grade:

- Accepted known-edge map: `data/backtest/mm_known_edge_map.json`
  - 17 records: 7 `harvest_only`, 3 `edge_research`, 7 `no_quote`.
  - 0 paper fills in the generated map report.
  - Promotion markets: 11.
- Latest post-snapshot-recovery all-market shadow one-shot: `data/mm_runs/2026-06-27/20260627T150554104648Z/run_summary.json`
  - mode `shadow`
  - evidence mode `operator_drill`
  - preflight `BLOCK`
  - first failing gate `source_status_degradation`
  - 132 quote rows, 132 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows.
  - `preflight_remediation.root_cause_counts = {source_status_degradation_blocked: 12}`
  - known-edge map provenance is accepted, non-diagnostic `mm_known_edge_map_v0.2` with 17 records and permission counts `{harvest_only: 7, edge_research: 3, no_quote: 7}`.
  - matching score: `data/backtest/mm_paper_shadow_20260627T150554_post_snapshot_recovery_source_status_block.json`, with 0 quoted legs, fill evidence `BLOCK` via `no_quote_legs`, reward score 0, exchange economics `PASS`, paper freshness `NO_ACTIVE_DAY`, and no actual payout evidence.
  - matching readiness: `data/backtest/mm_live_readiness_20260627T150554_post_snapshot_recovery_source_status_block.json`, status `BLOCK`, blocker count 11, `live_capital_permission = false`, and `snapshot_model_source_failing_gate_counts = {source_status_degradation: 12}`.
- Latest active-window all-market paper-live-forward one-shot: `data/mm_runs/2026-06-27/20260627T135932865534Z/run_summary.json`
  - mode `paper-live-forward`
  - evidence mode `active_day_live_forward`
  - preflight `BLOCK`
  - first failing gate `source_status_degradation`
  - 132 quote-intent rows, 0 quote-permission rows, 0 live-trade-permission rows.
  - `preflight_remediation.root_cause_counts = {source_status_degradation_blocked: 12}`
  - it is current active-window paper-forward evidence, but it does not count toward live-forward promotion and all 12 markets remain blocked by source-status degradation before policy/model output can be interpreted.
  - matching readiness: `data/backtest/mm_live_readiness_20260627T135932_after_clob_recovery_source_status_block.json`, status `BLOCK`, blocker count 11, `live_capital_permission = false`.
- Latest model-variant bakeoff: `data/mm_runs/2026-06-27/20260627T150554104648Z/model_variant_bakeoff.json`
  - schema `mm_model_variant_bakeoff_v0.1`
  - `status = EMPTY`
  - `score_status = NO_ROWS`
  - `base_input_rows = 0`
  - emitted variants: none.
  - skipped variants: none.
  - pre-registered variants remain `served_current`, `current_high_trust_retrain`, `dynamic_source_freshness`, `conservative_no_market_baseline`, and `clob_overlay_risk_only`.
  - interpretation: source-status preflight blocked before policy counterfactual rows, so this artifact is not model-promotion evidence.
- Latest non-empty moving model-variant bakeoff for historical comparison: `data/mm_runs/2026-06-26/20260627T031938117215Z/model_variant_bakeoff.json`
  - schema `mm_model_variant_bakeoff_v0.1`
  - `status = PASS`
  - `score_status = SAMPLE_PENDING`
  - 132 base rows, 396 materialized rows.
  - Emitted variants: `served_current`, `conservative_no_market_baseline`, `clob_overlay_risk_only`.
  - Skipped variants: `current_high_trust_retrain` and `dynamic_source_freshness`, both because probability columns were missing.
  - All emitted variants had `quote_permission_rows = 0` and `quote_permission_rate = 0.0`.
  - All emitted variants had reason counts: 44 `NO_QUOTE_INFORMATION_EVENT`, 88 `NO_QUOTE_KNOWN_EDGE_PERMISSION`.
- Prior moving run summary: `data/mm_runs/2026-06-26/20260627T031938117215Z/run_summary.json`
  - mode `paper-live-forward`
  - evidence mode `post_settlement_evaluation`
  - preflight `PASS`
  - live-forward gate `BLOCK`
  - 132 rows, 0 quote-permission rows, 0 live-trade-permission rows.
  - first failing gate `policy`; root cause `policy_no_edge`.
  - does not count toward live-forward evidence.
- Latest fixed recovered paper score: `data/backtest/mm_paper_postsettlement_recovered_20260627T0233_competitor_source.json`
  - 1,320 quote rows.
  - 17 quote-permission rows.
  - 0 live-trade-permission rows.
  - 34 quote legs.
  - 0 conservative fills.
  - 2 queue-estimated fill legs / 2.29885 queue-estimated filled shares.
  - fill evidence status `BLOCK`.
  - 4,148 missing-size trade rows.
  - 1 missing-book queue leg.
  - 34 unresolved resting quotes.
  - counterfactual rewards only; no actual payout evidence.

## How The Model Should Be Used Now

Use the current model in three roles.

1. Veto and safety overlay.

   The model may suppress quoting when model freshness, source freshness, event timing, source-state replay, or market-model disagreement indicates elevated adverse-selection risk. This is already consistent with fail-closed behavior in `market_making_run.py`, `mm_policy.py`, `info_event_calendar.py`, and paper diagnostics.

2. Harvest-only selector.

   The model can help select bands that remain within `harvest_only` cells, but quote prices should remain market/reward anchored. The model should not move quote centers toward directional fair value until edge evidence clears promotion gates.

3. Research signal.

   The model can be compared against market mid, CLOB overlay, source freshness state, and settlement outcomes in paper/shadow mode. These comparisons should feed known-edge map proposals and model-variant reports, not live quoting.

Do not use the current model for:

- directional live quoting,
- wider sizing because the model likes a band,
- model-skewed bid/ask placement around decisive WU/METAR/SWOB observation windows,
- replacing known-edge permission,
- overriding promotion blocks,
- treating CLOB-overlay variants as clean predictive edge without leakage controls.

## Current Variant Interpretation

The latest active-window bakeoff is `EMPTY` because source-status preflight blocked before policy counterfactual rows. It provides no evidence for model-skewed quoting or for changing known-edge permissions.

`served_current` is the only served model variant in the latest non-empty historical bakeoff, but it did not produce quote permission and did not beat the control on live-forward eligible metrics.

`conservative_no_market_baseline` is useful as a no-model control. It had 0 quote-permission rows, the same as the served model in the latest non-empty historical bakeoff. That means the available run evidence provides no support for letting model probabilities steer quote placement.

`clob_overlay_risk_only` uses market features and should remain risk-only unless leakage and overfitting controls are explicit. In the latest non-empty historical bakeoff it had mean edge `-0.000278`, mean absolute edge `0.001303`, and 0 quote-permission rows.

`current_high_trust_retrain` and `dynamic_source_freshness` were not evaluated in the latest non-empty historical run because their probability columns were missing. Missing model columns are not neutral evidence; they are a promotion blocker. In the latest active-window run, no variants were evaluated at all because source-status preflight blocked before model/policy rows.

## Promotion Gates For Model-Skewed Quoting

Model-skewed quoting remains blocked until all of these are true for the target platform, target date family, and selected markets:

- Active-day `paper-live-forward` evidence counts toward the live-forward gate.
- Known-edge map grants `edge_research` or stronger permission for the exact cell being considered.
- Model-variant bakeoff is not `SAMPLE_PENDING`.
- Intended model variants are emitted, not skipped for missing probability columns.
- Quote permissions are nonzero in countable active-day evidence.
- Paper/shadow live-trade-permission rows remain 0.
- Conservative fills and markouts are available, not only queue-estimated fills.
- Fill evidence completeness is `PASS` and promotion grade.
- Resting quotes resolve before decisive observation events; unresolved resting quote count is 0.
- Policy hash is locked across enough independent paper days.
- Per-slice markouts are positive after fees, rebates, rewards, flattening, and adverse-selection costs.
- Model delta versus market-mid/control remains positive after multiple-testing correction.
- Reward estimates are separated from realized P&L unless actual payout evidence exists.
- CLOB overlay features are used only with explicit leakage controls and held-out validation.

Until these pass, `edge_research` means collect evidence only. It does not mean live quote permission.

## Prompt Grounding For Future Codex Goals

Future goal prompts should require Codex to:

- Read this document after `MM_MODEL_READINESS_GAP_PLAN.md` and before recommending model-driven quoting.
- Recompute the latest known-edge counts from `data/backtest/mm_known_edge_map.json`; do not rely on historical 238-cell or 217-cell diagnostic maps.
- Inspect the latest run folder's `model_variant_bakeoff.json` and treat missing probability columns as blockers.
- Inspect both fixed paper-score artifacts and moving run summaries; moving tick state is not promotion-grade evidence by itself.
- Classify every quote/no-quote row into harvest-only, edge-research, no-quote, stale-data, event-gate, reward/economics, book-quality, or risk/budget suppression.
- Keep harvest quote prices market/reward anchored and use model output only as a veto until promotion gates pass.
- Reject model-skewed live quoting if the evidence is post-settlement, noncountable, sample-pending, missing model variants, fill-incomplete, or reward-only.

## Next Safe Actions

1. Collect active-window `paper-live-forward` evidence where the run counts toward the live-forward gate.
2. Re-run bounded paper scoring with model variants enabled after source-status preflight clears and nonzero countable quote permissions appear.
3. Restore or explain missing probability columns for `current_high_trust_retrain` and `dynamic_source_freshness` before using them in any promotion argument.
4. Compare `served_current`, no-model baseline, and risk-only CLOB overlay on conservative fills, markouts, avoided toxicity, quote uptime, and net P&L after costs.
5. Promote no known-edge cell from `edge_research` to live-capable behavior without independent active-day evidence and a passing readiness artifact.

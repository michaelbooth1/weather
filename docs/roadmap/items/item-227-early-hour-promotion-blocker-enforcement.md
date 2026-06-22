# 227. Early-Hour Promotion Blocker Enforcement [COMPLETE 2026-06-22 - CONSOLIDATED FAIL-CLOSED BLOCKER LIVE]

Goal: keep early-hour model and promotion gates fail-closed until current
serving or a matching candidate proves the 00:00-08:00 and weak-slot windows
are safe.

Source: `docs/roadmap/audits/early-hour-model-performance-audit-2026-06-22.md`.
The audit says current-serving hourly and 10-minute weak-slot gates are unsafe,
candidate broad replay still trails market, and live-forward SLO/current-code
soak blockers remain independent production blockers.

Why this matters: a broad aggregate improvement can still be a bad promotion if
the early hours are worse than market or if the mitigating candidate evidence
belongs to a stale variant. Promotion readiness must prove the exact candidate,
exact corpus, and exact gate that clear each blocker.

## Design

1. Add a consolidated early-hour blocker manifest to promotion refresh that
   records current hourly gate, current 10-minute gate, candidate hourly gate,
   candidate 10-minute gate, broad replay disposition, live-forward SLO, and
   current-code soak.
2. Require candidate mitigations to match replay variant id, candidate-hourly
   variant id, candidate-10-minute variant id, corpus hash, and generated-at
   freshness window before they can clear current-serving blockers.
3. Treat row-export surrogate evidence as diagnostic unless it is backed by the
   active replay/export contract.
4. Keep operations blockers visible as production-readiness blockers without
   relabeling them as model-skill evidence.
5. Add tests for stale report, mismatched variant, missing 10-minute evidence,
   and unsafe override cases.

- [x] Emit a promotion-refresh early-hour blocker manifest with current and
  candidate gate evidence side by side.
- [x] Fail closed when candidate hourly, 10-minute, and replay evidence do not
  share the same variant id and corpus lineage.
- [x] Add stale-artifact and surrogate-only blocker tests.
- [x] Regenerate promotion refresh, daily learning, and progress audit with
  the consolidated blocker state surfaced.

## Completion Notes

Promotion refresh now emits `early_hour_promotion_blocker` with current hourly,
current 10-minute, candidate hourly, candidate 10-minute, broad replay,
live-forward SLO, and current-code soak evidence side by side. The blocker is
fail-closed when candidate-specific gates are missing, stale, mismatched by
variant/corpus lineage, or backed only by surrogate row-export evidence.

The regenerated promotion refresh blocks early-hour promotion with six
categories: `candidate_hourly_mitigation`, `candidate_ten_minute_mitigation`,
`active_replay_export_contract`, `broad_replay_market_tolerance`,
`live_forward_slo`, and `current_code_soak`. Daily learning and progress audit
now surface the same consolidated blocker state in their JSON and Markdown
reports.

Verification:

- `python -m pytest tests\calibration\test_promotion_refresh.py tests\reporting\test_daily_learning.py tests\reporting\test_progress_audit.py tests\operations\test_schema_registry.py -q`
- `python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\pooled_candidate_replay_latest.json --precomputed-candidate-report data\backtest\pooled_candidate_replay_latest_report.md --candidate-hourly-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_ten_minute_performance.json --skip-serving-gauntlet`
- `python -m weather.reporting.daily_learning --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\daily_learning.json --report-out data\backtest\daily_learning_report.md`
- `python -m weather.reporting.progress_audit --backtest-root data\backtest --snapshots-root data\snapshots --roadmap docs\roadmap\ROADMAP.md --json-out data\backtest\progress_audit.json --report-out data\backtest\progress_audit_report.md`

Acceptance: promotion refresh cannot cut over an early-hour candidate while the
current-serving hourly or weak-slot gate is `BLOCK` unless matching
candidate-specific hourly and 10-minute gates pass, broad replay is within
market tolerance, and production-readiness blockers are explicitly cleared or
left as blocking non-model evidence.

Related: items 145, 160, 168, 178, 179, 212, 217, 228, 229.

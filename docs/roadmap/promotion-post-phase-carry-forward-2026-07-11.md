# Promotion Post-Phase Carry-Forward + Taker Permission Deadlock (2026-07-11)

## Problem, measured (2026-07-10 Stage B, corpus 297)

The replay cache fixed the candidate replay (2.5h+ → ~1h flat), but promotion
still took **10.1h** because its post-phase recomputes O(corpus) work daily on
inputs that only change when the model changes:

| Phase | Cost | Inputs actually change when… |
| --- | --- | --- |
| Candidate replay | ~1h (cached) | corpus grows / artifact changes (handled) |
| Post-replay diagnostics (microstructure OOF training, source-state ablation, conservative bridge) | **5.5h** | candidate artifact changes |
| Serving gauntlet (full recorded replay) | **3.4h** | model lineage changes (retrain/cutover) |

Knock-on effects: Stage B ran 16h → task-killed 04:44 mid-shadow → held the
long-job lock at 03:30 → 6th consecutive blocked retrain night; MM starved on
`model_freshness` 5 days.

## Fix: one carry-forward pattern, two applications (shipped 2026-07-11)

Reuse the previous result when the artifact hash is unchanged, the result is
recent, and (for the gauntlet) the verdict is healthy. Recompute otherwise.

- **Serving gauntlet** (`orchestration.py`): after each full run, write
  `serving_gauntlet_manifest.json` (artifact hash + the summary fields
  `_serving_gauntlet_summary` consumes — never the full replay rows). Carry
  when: hash matches, verdict ∈ {PASS, PASS_WITH_SHADOWS} (never carry a
  failing verdict — recovery must be re-proven), age ≤
  `--heavy-analysis-max-age-days` (default 7), and `--force-heavy-analysis`
  not set. Carried results are marked `carried_forward` +
  `carried_from_utc` + `carry_age_days` in the f_family summary.
- **Heavy diagnostics** (`pooled_candidate_replay.py`): same pattern via
  `promotion_heavy_diagnostics.json` for the microstructure / ablation /
  bridge sections. Export files from the last full run stay on disk; any
  downstream freshness gate that dislikes their age surfaces a visible
  blocker (fail-closed, diagnosable). The flag defaults to **0 (disabled)**
  inside `run_pooled_candidate_replay` so shadow contract runs — which share
  this code path with per-contract artifacts — can never touch the shared
  manifest; only the promotion CLI (parser default 7 days) enables it.

Retrain nights produce a new artifact hash → full recompute that night, by
construction. Stable nights: promotion ≈ **1.5–2h** (from 10.1h).

Both manifests were seeded from the 2026-07-10 completed run (same artifact,
<24h old), so the carry engages from the first post-fix Stage B. Verified live:
gauntlet ENGAGED (PASS_WITH_SHADOWS, age 0.48d), diagnostics ENGAGED,
wrong-hash refused. Tests: 192 across promotion/replay/cache/daily-refresh.

### Expected steady-state Stage B

Promotion ~2h + shadow ~5h + tail ~2.5h ≈ **9.5h** (12:45 → ~22:15), lock free
hours before the retrain (moved to 06:30 on 2026-07-11 until this bedded in)
and before MM's 19:30 preflight. Next tightening after a clean cycle: restore
canonical task budgets via `scripts/ops/register_daily_refresh.ps1` + revisit
the 06:30 retrain slot.

## Sentinel: two mismatch classes (context for the tolerance shipped 2026-07-11)

- Real input drift (2026-07-09, SF July-2): reanalysis 10-day sidecar refresh
  moved `candidate_p` ~1.6e-3 → handled by the 14-day cache fresh window.
- Float noise (2026-07-11, Chicago June-26): thread-level nondeterminism,
  `candidate_p` wobble ~2.4e-6 → handled by
  `SENTINEL_NUMERIC_ABS_TOLERANCE = 1e-4` in `rows_match_tolerant` (sits
  between the regimes; forensics still dump on real mismatches).

## Taker zero-fill diagnosis (decision needed — not auto-applied)

Why the taker has zero fills since June 24, fully traced:

1. `taker_edge_permission_map`: **4,840 of 4,847 slices are observe-only**
   (`insufficient_settlement_scored_skill`; gates: ≥5 settled orders, ≥3
   independent days, after-fee skill > 0). Bootstrap deadlock: permission
   requires settled orders; settled orders require permission.
2. The only 7 `edge_allowed` slices are **Seattle NO-side** (late hours,
   distance_1; after-fee skill 0.90, mean after-fee EV +$0.014/share).
3. The NO-side arm exists (item 253, `taker_bot_two_sided.py`, registered
   strategy `fade_overpriced`, status shadow) but `two_sided_enabled`
   defaults false and the live worker basket runs only
   `low_price_tail_capped` — registered shadow strategies are NOT
   auto-included (`shared_inputs_full_shadow` is a scoring rule, not a
   selection rule). The bot is in **paper-taker mode** (paper fills,
   $100 paper budget).

**Recommended unblock** (operator decision, one change): add
`fade_overpriced` to the daily-roll worker strategy list (e.g.
`--strategies low_price_tail_capped,fade_overpriced`). In paper mode this
risks no money, exercises the only slices the permission map already vets,
and starts accumulating the settlement-scored evidence that un-deadlocks the
bootstrap. The alternative path is the item-238 bakeoff replay to promote the
strategy on corpus evidence first.

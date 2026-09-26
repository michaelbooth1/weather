# Workstation handoff 2026-09-110b — weather maker plugin, Phase 1

Written 2026-09-25 by the production agent. Spec: [informed maker design](../operations/informed-maker-design-2026-09-25.md)
("Weather fair value (Phase 1)", "Plugin contract", "When to adjust"). Builds on Phase 0 (110a,
`codex/maker-core-phase0-20260925` @ `0b2224d37`, verified by the production agent; landing tonight). **All live trading is
paused.** No production data is available on the workstation: build against fixtures in the exact captured shapes; the
production agent exports bounded real samples afterwards.

## 1. Build (branch `codex/weather-maker-plugin-20260925` from `codex/maker-core-phase0-20260925`)

`src/weather/market/maker_plugin/` importing only `maker_core.contracts` from the core (the Phase 0 ratchet enforces this):

1. **`universe.py`** — `MarketUniverse` for local T+0..T+2 events of the 12 registered markets, from `market_registry` and the
   event-slug rules (mirror 88a's `build_universe` in `src/weather/market/maker_evidence_capture.py:100-150`; do not import
   the capture module if that would pull network code). `neg_risk_group` = the event; `native_unit` informational.
2. **`fair_value.py`** — `FairValueProvider`:
   - **T+1/T+2**: newest retained NBP bulletin at or before `as_of` whose TXN row holds the target date's maximum, using the
     **parser v2 slot rule** (the single 00Z-valid token whose window falls on the target local date). Vendor that rule
     from `origin/codex/integrate-2-parser-20260921` (@ `abd648c7c`) into the plugin with a test that it matches v2's
     output on fixtures; do not depend on the unmerged branch. Read p10/p25/p50/p75/p90 in native units; piecewise-linear
     CDF with linear tails; integrate over each band (open-ended `lte`/`gte` as `bin_probability`,
     `src/weather/model/model_presentation.py:733-741`); renormalise the event; declared zero-parameter stdev
     `sqrt(p(1-p)) * (bulletin_age_h/24 + 0.25)`; `valid_until` = next cycle's expected availability, ≤ 24 h after issue;
     `calibration_grade = "none"`. Fallback: PIT lead-1 `forecast_high` with a fixed climatological spread (state the value
     and its source in the pre-registration). Market prices never enter (the conformance kit's contamination probe must pass).
   - **T+0**: read the latest captured served band probability from snapshot rows (identify the exact field by reading the
     snapshot writer; do not recompute), `valid_until` = +15 min, expose the afternoon-centering stage id.
   - `Unavailable` whenever inputs are missing, stale or ambiguous; never a guess.
3. **`clock.py`** — `InformationClock`: station routine METAR minutes (from `origin/codex/observation-clock-20260923`
   `observation_clock.py`, vendored with attribution), NBM cycles 01/07/13/19Z with observed fetch time when available, NWP
   00/06/12/18Z + 210 min, detected `new_high` / `decided` from observation triggers; replayable from captured inputs.
4. **`settlement.py`** — `SettlementResolver` over settlement ledgers with `reconciliation_status`; `Pending` until
   reconciled; never a silent proxy (WRH caveat EF §10c).
5. **`exposure.py`** — `ExposureModel` from `mm_risk` region groups.
6. **Pre-registration**: `docs/research/t1-fair-value-preregistration-2026-09-25.md` — the T+1/T+2 fair value scored only on
   88a T+1/T+2 mids and settlements over panel-B-aligned dates (2026-09-25..2026-10-08), reliability table, Brier vs mid
   (expected worse), date×market crossed intervals, `UNDERPOWERED` below 10 clusters; states it is not a model-panel
   candidate or edge claim. Freeze before any real data is read.

## 2. Tests

Conformance kit on every provider; fixtures in the captured NBP/snapshot/ledger shapes (read the writers to get them
right); v2 slot-rule parity; band integration sums to 1 per event; `Unavailable` paths; point-in-time repeatability;
contamination probe; ratchet green.

## 3. Boundaries and deliverables

No venue calls, credentials, `.env`, production data or writes, scheduled tasks. Report:
`docs/roadmap/agent-report-2026-09-110b-weather-maker-plugin.md` (verdict first, module map, input shapes used, the
pre-registration link, what needs real data, the tip). Push is authorized. The production agent then exports a bounded,
hashed real-input sample for a dry run.

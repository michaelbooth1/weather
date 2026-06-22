# 225. Location Audit Evidence Freshness Repair [COMPLETE 2026-06-22 - FRESHNESS BLOCKER LIVE]

Goal: repair replay status, fleet freshness, and disk/headroom blockers before
using new live or microstructure evidence to validate a location-performance
fix.

Source: `docs/roadmap/audits/location-performance-model-audit-2026-06-22.md`.
`settled_day_freshness.json` is FAIL for 2026-06-20 with missing replay status
for all 12 markets. `fleet_observability.json` is CRITICAL with loop restarts,
CLOB staleness, missing tape files, and MM evidence starvation. MM and taker
daily roll logs show `OSError: [Errno 28] No space left on device`.

Why this matters: the historical location split is valid evidence, but a
production repair cannot be validated on stale replay status, stale CLOB books,
or disk-full runs. Evidence freshness must be green before new live-forward
claims count.

## Design

1. Run replay status backfill and settled-day freshness repair for the affected
   date.
2. Verify data-layer audit, ingest quality gate, fleet observability, and
   daily-learning status after cleanup.
3. Rerun the location audit after replay status and quarantine exclusions are
   present.
4. Add a location-promotion blocker when freshness or fleet status is not green.

- [x] Repair replay status and settled-day freshness for the affected evidence
  set.
- [x] Resolve disk/headroom blockers or document retained artifact cleanup.
- [x] Regenerate data-layer, ingest, fleet, daily-learning, and location audit
  reports.
- [x] Add freshness status to location promotion/readiness output.

## Completion Notes

Replay-status backfill regenerated the missing replay status for the affected
folders. The repaired freshness reports now show `0` missing replay-status and
`0` missing replay-input markets for both the original 2026-06-20 audit date
and the current 2026-06-21 settled-day target. Settled-day freshness remains
`WARN`, not `PASS`, because all 12 markets still carry source-lag/fallback
settlement warnings.

Regenerated operational artifacts:

- `data/backtest/settled_day_freshness.json`
- `data/backtest/settled_day_freshness_2026-06-20.json`
- `data/backtest/data_layer_audit.json`
- `data/backtest/ingest_quality_gate.json`
- `data/backtest/fleet_observability.json`
- `data/backtest/daily_learning.json`
- `data/backtest/location_trust.json`
- `data/backtest/f_family_promotion_refresh.json`

`f_family_promotion_refresh.json` and its Markdown report now include an
`evidence_freshness` gate and a `location_evidence_freshness` readiness
blocker. Location promotion/repair validation is non-countable until
settled-day freshness, data-layer audit, ingest quality, fleet/live-forward,
CLOB book freshness, daily learning, and artifact headroom all pass. Current
disk headroom passes with more than the configured 1 GB reserve, while the
regenerated evidence still blocks on settled-day `WARN`, data-layer `WARN`,
ingest `WARN`, fleet `CRITICAL`, CLOB freshness `BLOCK`, and daily learning
`BLOCKED`.

Verification:

- `python -m pytest tests\calibration\test_promotion_refresh.py -q`
- `python -m pytest tests\reporting\test_runtime_identity_evidence.py tests\operations\test_daily_refresh.py -q`

Acceptance: location promotion and repair validation can count only when replay
status is present, fleet/live-forward gates are green, CLOB evidence is fresh
for market-informed lanes, and the location split has been regenerated after
quarantine exclusions.

Related: items 120, 146, 154, 157, 159, 161, 218.

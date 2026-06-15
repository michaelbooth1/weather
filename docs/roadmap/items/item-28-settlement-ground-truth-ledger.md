# 28. Settlement Ground-Truth Ledger [COMPLETE - LEDGER LIVE]

Goal: encode and archive EXACTLY how each market resolves, and the realized
outcome, as the supervised label.

- [x] Per market, pin the resolution spec: source (Wunderground station id),
  daily-max window, rounding, unit, timezone.
- [x] After each market day, freeze the realized settlement high + winning band +
  evidence (generalize `market_day_labels finalize` to all 12 markets).
- [x] Reconcile the live WU-history settlement against the actual Polymarket
  resolution; alert on mismatch.
- [x] Maintain a per-market settlement ledger = the supervised labels and the
  calibration target.

Acceptance: every settled market day has a frozen, source-verified label, and
backtests/trust read from the ledger.

Detailed design (implemented 2026-06-06):

- Add `src/settlement_ledger.py` as the authoritative settlement-label layer.
  It writes pinned market-resolution specs to
  `data/settlements/resolution_specs.json` and per-market ledgers to
  `data/settlements/{market_id}/ledger.jsonl`.
- Keep folder-local `settlement.json` files as evidence copies, but make the
  per-market ledger the first source read by scoring tools.
- Resolve each folder's market from the registered Polymarket slug, then use
  that market's WU station, unit, timezone, daily-summary path, and local
  midnight-to-midnight daily-max window.
- Freeze native-unit settlement high, rounded settlement bucket, winning market
  band, quality grade, collection coverage, source evidence, Polymarket URL,
  Gamma API URL, and reconciliation status.
- Reconcile closed Polymarket events by reading the resolved Yes band from Gamma
  final outcome prices. Matches are recorded as `reconciliation_status=match`;
  mismatches append an alert row to `data/settlements/reconciliation_alerts.jsonl`.
- Make `src.backtest` and `src.location_trust` ledger-first. Backtest falls back
  only for unfinalized legacy tapes; trust now counts clean/manual ledger labels
  rather than every historical folder.

Codex implementation status (2026-06-06): complete for the current 12-market
platform foundation. The registry now has pinned resolution specs for Toronto
plus the 11 US Fahrenheit markets. The finalizer wrote 9 settled Toronto ledger
rows; all 9 matched Polymarket's resolved winning band. Current clean scoring
uses 3 complete ledger days, while 6 partial rows remain preserved in the ledger
but excluded from headline quality-filtered backtests/trust.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_market_day_labels.py tests\test_settlement_ledger.py tests\test_backtest.py tests\test_location_trust.py -q`: 37 passed.
- `.\venv\Scripts\python.exe -m compileall src tests`: passed.
- `.\venv\Scripts\python.exe -m src.market_day_labels finalize`: wrote 9 labels,
  per-market ledgers under `data/settlements`, and `complete=3, partial=6`;
  Polymarket reconciliation `match=9`.
- `.\venv\Scripts\python.exe -m src.backtest --quality-grades complete,manual_override`:
  scored 3 complete Toronto ledger days, with settlements reported as
  `settlement_ledger:snapshot_high`; all-snapshot model Brier 0.0550 versus
  market Brier 0.0337, daily-first model Brier 0.0539 versus market 0.0347.
- `.\venv\Scripts\python.exe -m src.location_trust`: Toronto trust now uses 3
  clean ledger days and reports 38/100 Low; US markets remain Unproven until
  their first post-ledger days settle.

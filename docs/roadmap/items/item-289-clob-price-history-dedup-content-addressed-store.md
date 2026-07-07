# 289. CLOB Price-History Deduplication And Content-Addressed Raw Response Store [COMPLETE 2026-06-23 - DEDUPED POINT TABLE AND HASHED RAW STORE LIVE]

Goal: stop repeated CLOB price-history captures from appending duplicate
overlapping windows, and store raw price-history responses once by content hash
while preserving replayable point-level price history for later analysis.

Source: the 2026-06-23 storage audit found CLOB price-history tapes among the
largest and fastest-growing snapshot artifacts. The CLOB loop includes price
history by default and each capture fetches a rolling history window for every
token, then appends all returned points to `price_history.csv` and the raw
response to `price_history.jsonl`. This preserves useful information, but a
240-minute rolling window collected repeatedly means most points can be written
many times across the day.

Why this matters: CLOB price history is valuable for microstructure features,
markouts, taker/maker replay, adverse-selection analysis, and market movement
diagnostics. It should be kept. The waste is not the data itself; it is storing
the same exchange time series points and raw responses repeatedly. A deduped
point table plus content-addressed raw response blobs keeps the useful evidence

## Design

1. Define a stable uniqueness key for price-history points, at minimum
   `market_id`, `event_slug`, `clob_token_id`, `fidelity_minutes`,
   `interval`, and `point_timestamp`/`point_time_utc`.
2. Replace append-all `price_history.csv` writes with an upsert/dedupe writer
   that appends only new points and records duplicate-suppression counts in
   `clob_capture_status.jsonl`.
3. Store raw price-history API responses in a content-addressed raw payload
   directory keyed by SHA-256, and have JSONL/status rows reference the hash and
   path instead of duplicating identical response bodies.
4. Preserve backward-compatible readers for legacy `price_history.csv` and
   `price_history.jsonl`, while new reports prefer the deduped point table and
   raw-response manifest.
5. Add a historical repair command that scans existing price-history tapes,
   writes a deduped table, validates point counts by key, and reports reclaimed
   pass.

- [x] Add a deduped CLOB price-history point writer with an explicit uniqueness
  key and duplicate suppression accounting.
- [x] Add a content-addressed raw price-history response store and manifest.
- [x] Update CLOB capture status and diagnostics to report new points,
  duplicate points, raw response hash, and raw response byte counts.
- [x] Add legacy-reader compatibility and a repair/backfill command for
  existing price-history tapes.
- [x] Add tests covering overlapping windows, changed/corrected price points,
  raw response hash reuse, and parity with legacy readers.

## Completion Notes

- `MarketMicrostructureStore.write_price_history` now upserts `price_history.csv`
  by `(market_id, event_slug, clob_token_id, fidelity_minutes, interval,
  point_timestamp/point_time_utc)` and reports new, duplicate, corrected, and
  total point counts.
- Raw `/prices-history` responses are stored once under
  `price_history_raw/<sha256>.json`; `price_history.jsonl`,
  `price_history_raw_manifest.jsonl`, capture status rows, and loop
  diagnostics reference the hash/path/byte counts instead of duplicating the
  response body.
- `python -m weather.market.market_microstructure repair-price-history
  --folder <snapshot-folder>` writes `price_history_deduped.csv`; `--apply`
  rewrites `price_history.csv` after the key-parity validation passes.
  policy now classify the raw response blobs as canonical CLOB evidence.

Verification:

- `python -m pytest tests/market/test_market_microstructure.py -q`

Acceptance: repeated CLOB captures over overlapping price-history windows write
each unique point once per token/fidelity/interval timestamp, raw API responses
are stored once by content hash and referenced from manifests/status rows, and
historical repair proves a deduped point table can reproduce legacy reader
results before any legacy file cleanup is allowed.

Related: items 66, 124, 156, 202, 240, 241, 246, 282, 286, 287.

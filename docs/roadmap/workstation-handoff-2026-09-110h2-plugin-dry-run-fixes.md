# Workstation handoff 2026-09-110h2 — weather plugin: fixes from the first real-data dry run

Written 2026-09-28 by the production agent. The first production run of the 110h dry-run CLI (branch
`codex/weather-maker-plugin-20260925` at `3b8c7b92d`, run from a detached worktree with `python -P`, module path verified)
on 88a date 2026-09-26 ended **PARTIAL** after 24.8 s: `stop_reason=input_byte_cap` (1 GiB read after 2 segment-minutes),
7 records, **every band `not evaluated`**, zero policy decisions. Full reports (no local paths or secrets) are in
[`evidence-110h-dry-run-20260926/`](evidence-110h-dry-run-20260926/report.md).

## Defects to fix (base `origin/codex/weather-maker-plugin-20260925`, then merge `origin/master`)

1. **NBP bulletin path is wrong (1,269 `nbp:FileNotFoundError`).** `maker_plugin_sources.py:63` looks for
   `data/forecast_payloads/sha256/<xx>/<key>.json`; production's content-addressed store is
   `data/forecast_payload_cas/sha256/<xx>/<key>.blob` (verified on production 2026-09-28). Resolve through the store's own
   reader or path helper rather than a hand-built path; keep the hash verification (confirm what the hash covers for `.blob`).
2. **`descriptor:missing_captured_band_metadata` for every T+1/T+2 band (44).** Production hypothesis to confirm: band
   metadata comes from per-event CLOB token files that exceed the 64 MiB per-file cap (Atlanta 2026-09-26
   `clob_tokens.jsonl` is 93.5 MB, `clob_tokens.csv` 49.6 MB). Read band metadata with a bounded streaming reader (first
   complete token batch at or before the minute), not a whole-file load; never raise the cap silently.
3. **`descriptor:missing_point_in_time_input` for every T+0 band (33).** Explain from code which input is missing at
   minute 00:01Z for a same-UTC-day event and fix or report it as a genuine coverage limit.
4. **`settlements:file_byte_limit` (7).** The settlement ledger file exceeds the per-file cap; stream it (only the target
   events' rows).
5. **Input budget:** 1 GiB was consumed after 2 of ~1,440 minutes (381 files, 314 sealed files verified). Load each event's
   supporting files once per run (bounded cache keyed by path+size+mtime+hash), not per minute; report bytes per source.
   Target: a full day for all markets within the documented caps, or a clearly reported per-source budget.

## Deliverables

Fixture tests for each defect (store layout `forecast_payload_cas/sha256/<xx>/<key>.blob`, an over-cap token file, an
over-cap ledger, the T+0 case) plus the repo-wide audits and maker-core boundary tests. Push, update draft PR #96, and
report `docs/roadmap/agent-report-2026-09-110h2-plugin-dry-run-fixes.md` with the exact production re-run command (same
safeguards: detached worktree, `python -P`, module-path probe, lease, new output directory). The plugin does not land until
a production re-run evaluates bands end to end. The replay exam is unaffected in timing: hazard calibration uses 88a
public trades, and panel bundles can be exported after the fix from sealed 88a data.

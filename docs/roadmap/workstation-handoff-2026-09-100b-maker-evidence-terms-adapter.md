# Workstation handoff 2026-09-100b — 88a reward terms into the 89a desk study

Written 2026-09-25 by the production agent. Serves Q-04/Q-05 and the fill-toxicity study (89a). Finding: the
[post-night audit](audits/post-night-audit-2026-09-25.md) row 1. The 89a run on `2ac227d08` admitted 0 of 480 events, all
`no_panel_bands_with_captured_reward_terms`: 89a reads terms only from the snapshot folder (`reward_records.jsonl`,
`rewards.jsonl`, `snapshots.jsonl`), which never carried them. 88a (on master since 2026-09-25, capturing since 06:34Z)
records the right terms in a different place and shape.

## 1. Build (branch `codex/fill-toxicity-desk-study-20260923`, on top of `2ac227d08`)

- An adapter in `src/weather/market/fill_toxicity_inputs.py` (or a sibling module) that reads 88a's sealed segments
  `data/maker_evidence/<UTC-day>/<hh>-<seg>/reward-<hash>.jsonl.gz`: unwrap `body_utf8` → JSON `data[]`, resolve `payload_ref`
  rows to the payload they point at, take `captured_at_utc` per minute, and emit the rows `term_rows` already understands
  (`rewards_min_size`, `rewards_max_spread`, `rewards_config[].rate_per_day` already match). Read the store's own reader or
  schema first (`src/weather/market/maker_evidence_store.py` around lines 248-276); do not guess the layout.
- Plan the adapter's files as an additional reward input per event (by `event_slug`/condition), bounded and streamed (gzip,
  no full-day loads), and never read an unsealed segment.
- Record **Clarification 11** in the frozen 89a pre-registration: a data-inclusion change (new source of captured terms, same
  60-minute freshness rule, same analysis). Update `FROZEN_REF` to the commit that records it.

### Observed record shape (production, `2026-09-25/08-f8bb30b5690c/reward-009d67b432ce7f3236517653.jsonl.gz`)

Outer keys: `body_stored, body_utf8, captured_at_utc, change_key, content_sha256, http_status, kind ("rewards"),
latency_seconds, offset, request_sha256, response_bytes, response_sha256, sequence, url`
(`url` = `https://clob.polymarket.com/rewards/markets/<condition_id>`). `body_utf8` decodes to
`{"count", "data": [...], "limit", "next_cursor"}`; each `data[]` item has `condition_id, market_slug, event_slug, tokens[]
{token_id, outcome, price}, rewards_config[] {asset_address, start_date, end_date, id, rate_per_day, total_rewards, total_days},
rewards_max_spread (4.5), rewards_min_size (100)`. A dedup row has `body_stored: false` and
`payload_ref: {"file": "reward-….jsonl", "offset": 8893}`; the offset is into the **uncompressed** stream of the named file
(stored gzipped as `….jsonl.gz`), which is the stored row whose `body_utf8` to reuse.

## 2. Tests

Unit tests on a small synthetic segment in 88a's exact format (a real record's shape, redacted): `body_utf8` unwrap,
`payload_ref` resolution, a minute with no change, an unsealed segment ignored, a freshness violation excluded.

## 3. Boundaries and deliverables

No production run: the rerun waits for about ten UTC dates of 88a data (earliest ~2026-10-05) and is launched by the
production agent under the lease. No `.env`, no production writes. Report: `docs/roadmap/agent-report-2026-09-100b-maker-evidence-terms-adapter.md`
(verdict first, tests, the Clarification 11 text, the tip). Push is authorized.

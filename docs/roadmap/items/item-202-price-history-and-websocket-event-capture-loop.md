# 202. Price-History And WebSocket Event Capture Loop [COMPLETE 2026-06-21]

Goal: add lightweight, durable price-history and WebSocket event capture for
active market days so model-market disagreement cases can distinguish market
lead, liquidity artifacts, and book-state sampling effects.

Source: the June 21 log audit found order books, tokens, and derived CLOB
features are captured for current locations, but the supervised CLOB loop does
not collect price history or WebSocket events by default. The constants keep
manual capture enabled but loop capture disabled for `price_history.csv` and
`market_ws_events.csv`.

Why this matters: order-book snapshots explain the current state, but not always
the path into that state. The disagreement casebook already flags market-lead,
book-liquidity artifact, large midpoint moves, and price-collapse episodes. A
thin event/history stream would make those cases more actionable for both model
improvement and market-aware risk controls.

## Design

1. Add loop-safe capture modes for short-window price history and bounded
   WebSocket event summaries.
2. Persist per-token price history points, event type, asset, side, price,
   receive time, raw hash, and capture status.
3. Add storage tiers so raw event streams can be retained briefly while
   downsampled summaries remain long-term.
4. Join event/history summaries into disagreement casebook and settled-day
   root-cause reports.
5. Add fleet observability gates for event-stream freshness without blocking
   core weather-model review when only optional market event streams are stale.

- [x] Enable a bounded active-day price-history capture path in the loop.
- [x] Enable bounded WebSocket event summary capture with heartbeat diagnostics.
- [x] Add storage tiering and backup accounting for event/history artifacts.
- [x] Join event/history evidence into market-lead and liquidity-artifact cases.
- [x] Add tests for optional-stream failure isolation from core snapshot capture.

Acceptance: future market-lead or liquidity-artifact cases include recent price
path and event-stream context, while failures in optional streams do not block
the core weather-model snapshot tape.

Completion notes (2026-06-21): the supervised CLOB loop now enables bounded
price-history and WebSocket event capture by default while retaining explicit
opt-out flags. Disagreement casebook and settled-day root-cause reports join
recent price path and WebSocket event summaries into reviewed cases, and fleet
observability surfaces optional stream WARNs without blocking the broad
live-forward SLO. Existing tape-backup policy coverage for `price_history` and
`market_ws` artifacts was verified.

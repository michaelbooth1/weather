# Workstation handoff 2026-09-110f — wallet reader: incomplete P&L while a settled lot is unredeemed

Written 2026-09-25 by the production agent; owner-approved (wide audit WAL-1, DECISION_LOG 2026-09-25). Branch
`codex/wallet-public-reader-20260925` (tip ec44b657 or newer).

## Problem

A campaign lot that has resolved but is not yet redeemed drops out of live equity: the reader classifies it `resolved`
and excludes it from live marks, so campaign P&L reads the lot at zero. Chicago 68-69°F Sep 25 (75 YES @0.43) would read
−32.25 whether it won or lost; a win is really +42.75.

## Build

- A resolved position with `redeemable == true` (or a known terminal price of 1) and non-zero size is **unredeemed**.
  Value it at its terminal price (`size × 1` for a winning outcome, `0` for a losing one) using the data-api / gamma
  resolution fields; if the outcome price is not definitively 0 or 1, it is `terminal_value_unknown`.
- `campaign_pnl_pusd` includes unredeemed terminal values. If any unredeemed lot has `terminal_value_unknown`, set
  `status = "INCOMPLETE"` and `campaign_pnl_pusd = null` with reason `unredeemed_terminal_value_unknown`, never a silent zero.
- Add `unredeemed_positions` (title, outcome, size, terminal value) to `/summary`.
- Only lots acquired after the campaign baseline count toward campaign P&L; historical dust stays in
  `resolved_pnl_vs_cost_pusd` (unchanged). If the reader cannot tell acquisition time, mark `INCOMPLETE` rather than guess.

## Tests and deliverables

Fixtures: winning unredeemed lot counts +size; losing counts 0; ambiguous price → INCOMPLETE; redeemed lot (cash already
moved) not double-counted; historical dust excluded. All 100a safety properties unchanged; no `.env`, no real account.
Append the result to `docs/roadmap/agent-report-2026-09-100d-wallet-reader-fixes.md` as "110f". Push; the owner restarts
`serve`.

# Venue shape provenance

The trade fixtures are redacted **shape reconstructions**, not original wire
captures. Their source is the confirmed-shape section of the 84g report at commit
`c771cbb427cd2ab3cac1cbee52c84721bb3ac935`,
`docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md`,
and its `tests/market/test_re1_addendum.py` alias fixture.

The confirmed REST trade uses `token_id`: taker YES at 0.52, two maker NO
rows at 0.48 for 20 and 5.57 shares; the latter is our terminal NO order.
IDs, addresses and token numbers are replacements. No credential fields were
copied. The `asset_id` variant preserves that confirmed relationship using
the documented WS alias. The failing session-1 WS payload was never retained;
its exact bytes and event-specific fields cannot be recovered.

The order fixture is a **retained normalized real order event**, not raw wire
JSON: a YES BUY placement at 0.49 for 20 shares, with LIVE status and zero
matched size. It comes from the `user_event` row in the workstation campaign's
`.weather-re1m-20260921/session-1/user-stream.jsonl`, examined with a bounded,
read-only field allowlist on 2026-09-23. That journal is outside the session
worktree. Event fields and exchange timestamp are preserved; order, condition,
token and maker identifiers are replacements. No credential-named field or
authentication payload was copied. Its normalizer-added keys are intentionally
retained, so do not feed this normalized record back as an original WS message.

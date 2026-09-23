# Venue shape provenance

These are redacted **shape reconstructions**, not original wire captures.
The source is the confirmed-shape section of the 84g report at commit
`c771cbb427cd2ab3cac1cbee52c84721bb3ac935`,
`docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md`,
and its `tests/market/test_re1_addendum.py` alias fixture.

The confirmed REST trade uses `token_id`: taker YES at 0.52, two maker NO
rows at 0.48 for 20 and 5.57 shares; the latter is our terminal NO order.
IDs, addresses and token numbers are replacements. No credential fields were
copied. The `asset_id` variant preserves that confirmed relationship using
the documented WS alias. The failing session-1 WS payload was never retained;
its exact bytes and event-specific fields cannot be recovered.

The order event combines the reported cancelled, partially filled NO order
with the existing order-event envelope. Its cancellation envelope is inferred,
not an observed WS event. It must not be described as a captured real event.
A future attended session's credential-stripped retained message should replace
that inferred envelope after separate owner authorization to read the evidence.

# WS-1(b) computation review packet

Historical T002 method and validation record; no market-day or power result.
Read with the [earlier preflight](ws1b-maker-feasibility-preflight-2026-11-06.md)
and the [edge trial charter](../operations/EDGE_TRIAL_CHARTER.md).

The task's updated COMMON.md research-script protocol authorizes staging an
exact allowlist entry on the task branch and requires master review and GO
before a heavy run. The entry does not authorize execution by itself. B002
also requires HOLD_HEAVY checks, default resource admission and publication by
verified bundle. No further push or authentication attempt was made.

The prepared standalone script streams sealed journals into a bounded SQLite
index, admits token identities from explicitly dev-dated event heads, and
scores historical as-of reward terms. It avoids mixed-date universe scores.
Each invocation handles one UTC day, one event, or generated-output statistics.
The script and its exact hash are in the staged allowlist entry; the external
`C:\t\codex\T002\REVIEW_REQUEST.md` binds inputs, outputs and resource estimates.

The small synthetic checks cover cumulative-size midpoint selection, reward
minimums and capital, queue depletion, partial fills, complementary aggressors,
cancel delay, streaming indexing, journal-hash rejection, date aggregation and
the competition-response sensitivity. A bounded captured-sample trace resolves
one paired Atlanta book and its preceding reward record, scores all three
sizes and finds the venue settlement. These are validation checks, not a daily
reward, fill-rate or profitability estimate.

During the hold, bounded free official fetches obtained the historical venue
resolution inputs for the supplied September 30–October 14 event names.
The raw replies and projections are archived. The validation checks raw hashes,
exact event identity, closed markets, UMA resolved status, binary payouts and
one winning condition per event. It is not a model-label reconstruction.

Two corrections were made before any bulk computation: a daily reward upper
bound uses the entire captured pool rather than a prorated partial-day pool,
and the adverse stress preserves guaranteed payouts in hedged inventory. The
full-active-epoch reward scenario, unknown competing-maker ownership and
endogenous competition remain explicit assumptions or identification limits.
The [official methodology](https://docs.polymarket.com/programs/liquidity-rewards)
defines the normalization and scoring used for this review.

The script separates actual-venue-settlement counterfactual P&L from assumed-f
stress means. It reports fee-funded rebate accrual but credits no unverified
rebate payment. The fixed f cases are 0.10, 0.25 and 0.50. An additional 0.10
reward multiplier at f=0.25 is a competition-response sensitivity, not an
estimated response. Conditional planning variance retains date aggregation and
categorical inventory support rather than treating bands or shares independently.

This is not a validated fair-trial simulator. Decision and cancellation lags
are assumed; paid-reward normalization and response need own-pilot validation.
Normal planning N omits sequential, Holm and serial-date penalties. The
three-cohort capital reserve is a sizing sensitivity, not a simulated bankroll
path. The method cannot establish a T1 PASS or a universal G1 kill.

Receipts and source versions are under `C:\t\codex\T002\out\`, including
`light_checks_v2.txt`, `tiny_trace_v2.json`, `resolution_validation.json`,
`pin_validation.json`, and `COMPUTATION_ADDENDUM_V2.md`. SHA256SUMS identifies
the archive. No bulk computation ran before this review request.

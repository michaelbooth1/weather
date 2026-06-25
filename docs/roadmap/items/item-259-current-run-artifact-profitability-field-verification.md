# 259. Current-Run Artifact Profitability Field Verification [COMPLETE 2026-06-23 - CURRENT-RUN PROFITABILITY VERIFIER GATES PROMOTION]

Goal: extend item 240 and item 241 verification from code/tests to current run
artifacts, so taker orders and strategy reports must actually contain
executable-depth, slippage, market-benchmark, and no-trade fields before they
can support live-profitability claims.

Source:
`docs/roadmap/audits/trading-stack-performance-strategy-audit-2026-06-23.md`.
The June 19-22 taker order tapes contain `fee_usdc`, but the run artifacts do
not carry executable-depth, slippage, market-benchmark, avoided-loss,
missed-gain, or no-trade scoreboard columns. Settled June 19-21 finalization
payloads mark `live_profitability_evidence_basis` as `paper_no_fee`, with
`after_fee_pnl_scored=false` and `after_slippage_pnl_scored=false`.

Why this matters: items 240 and 241 are complete at the implementation level,
but stale or legacy run artifacts can still look like usable evidence unless
the current-run artifacts are checked. Profitability evidence must prove that
the fields exist in the tapes being used for the claim.

## Design

1. Add an artifact verifier that scans the latest taker run folders and report
   outputs for fee, slippage, executable-depth, benchmark, and no-trade fields.
2. Fail the verifier when required fields are absent, null-only, or marked
   false in finalization payloads.
3. Wire the verifier into daily refresh, strategy bakeoff, and promotion gates.
4. Mark June 19-22 style artifacts as legacy/non-promotable even when code and
   unit tests support the newer fields.
5. Make item 240/241 evidence require a current run artifact pass, not only
   implementation proof.

- [x] Add a current-run artifact verifier for taker order tapes, strategy
  summaries, and finalization payloads.
- [x] Include after-fee, after-slippage, executable-depth, avoided-loss,
  missed-gain, and market-smarter/no-trade fields in the verifier contract.
- [x] Add fixtures showing June 19-22 legacy artifacts fail the verifier.
- [x] Block live-profitability evidence and promotion when the verifier fails.

Acceptance: current taker artifacts used for any live-profitability claim
include after-fee, after-slippage, executable-depth, avoided-loss, missed-gain,
and market-smarter/no-trade fields. The verifier fails June 19-22 legacy-style
artifacts and passes a fresh post-fix run whose finalization payloads mark
after-fee and after-slippage scoring true.

Completion note 2026-06-23: added
`taker_profitability_artifact_verification_v0.1` with fail-closed checks for
order-tape fee/slippage/executable-depth fields, strategy benchmark/no-trade
fields, and finalization after-fee/after-slippage booleans. Strategy bakeoff
payloads now record the verifier result and block promotion gates on verifier
failure; daily trading evidence reports the verifier status and returns BLOCK
for legacy current-run profitability artifacts. Verification:
`python -m pytest tests\market\test_taker_bot.py -q`;
`python -m pytest tests\reporting\test_trading_evidence.py tests\operations\test_schema_registry.py -q`.

Related: items 240, 241, 256.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - CURRENT-RUN PROFITABILITY VERIFIER GATES PROMOTION`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.


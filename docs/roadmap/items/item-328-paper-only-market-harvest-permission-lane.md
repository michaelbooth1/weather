# 328. Paper-Only Market-Harvest Permission Lane [PARTIAL 2026-08-15 - CUMULATIVE PARENT FOCUSED-GREEN; EXACT SUITE AND ACTIVE-DAY PROOF OPEN]

Goal: make the approved market-centered rebate experiment reachable without
misrepresenting model promotion or manufacturing model edge.

Owner/package: `weather.market.market_making_run`,
`weather.market.market_making_run_support`, and `weather.market.mm_policy`.

Source: `docs/operations/ESTABLISHED_FINDINGS.md` section 8c. The existing
policy's harvest fallback still iterates model snapshot rows and evaluates
model freshness and promotion before it can quote. Production can therefore
produce countable paper artifacts but no quote-permission row even though the
approved experiment uses the market midpoint rather than a model fair value.

Why this matters: Stage 1 requires a simultaneous paper row with quote
permission. Without a separate lane, the real-money lifecycle remains blocked
by a model-promotion condition that the approved market-centered experiment is
not intended to satisfy. Relabelling promotion or deleting the known-edge map
would weaken unrelated model protections instead of implementing the missing
route.

Claim boundary: this item proves only route reachability and auditable paper
mechanics. It does not prove maker fills, reward eligibility, adverse-selection
economics, profitability, model edge, or live readiness. Those require the
public execution tape plus authoritative own-account lifecycle, fee, rebate,
position, and settlement evidence.

Scope:

- [x] Add a named `market_harvest` permission profile separate from model
  promotion and known-edge permission. Leave the default `model` profile and
  all model BLOCK behavior unchanged.
- [x] Assemble harvest rows from current event/token metadata, CLOB books, and
  CLOB features without reading model snapshot probabilities.
- [x] Keep active-event validation, source and watcher health, information-event
  pulls/widening, CLOB discovery/continuity/freshness/depth, exchange economics,
  current minimum size/tick, cadence, current-high, and budget/risk gates.
- [x] Enter the harvest decision before fair-value, model-age, overlay,
  disagreement, and promotion logic; record empty model probability fields and
  `market_mid_no_model` provenance.
- [x] Force paper-only behavior, `live_trade_permission=false`, zero assumed
  reward/rebate, the declared midpoint spread settings, and non-raisable
  quote/event/band/daily ceilings even after dynamic reconciliation.
- [x] Fail closed when risk haircuts leave a quote below the current exchange
  minimum order size or when prices cannot remain on the current tick grid.
- [x] Pass focused policy and orchestrator tests with model rows absent,
  promotion BLOCK, a known-edge `no_quote` record, and attempted ceiling raises.
- [ ] Pass the immutable exact-tip full suite on the refreshed parent.
- [ ] Integrate through the guarded roll-sensitive path and adopt the new code
  without disrupting capture.
- [ ] Run one active-day, one-market `paper-live-forward` tick and prove nonzero
  quote permission, two-sided post-only intent, zero live permission, exact
  risk ceilings, and public-tape counterfactual markout fields.
- [x] Bind the successful paper row into the eligible-host Stage 1 candidate
  selection without allowing it to authorize mutation by itself.

Acceptance: a current one-market paper run can emit an exchange-valid,
two-sided midpoint quote intent when model probabilities are absent and model
promotion is BLOCK, while every retained non-model safety/economics gate passes,
all live permission remains false, and no caller or dynamic artifact can raise
the existing ceilings. Live orders remain exclusively owned by item 67's
eligible-host staged lifecycle.

## 2026-08-15 cumulative-parent disposition

The refreshed harvest lane, unified official client, and pUSD payout-asset
contract now share one current-master parent. Focused tests and the real
`polymarket-client==0.6.0` wheel contract pass. Candidate-plan v0.2 streams and
hashes the complete paper quote tape, requires a still-current successful
`market_harvest` row with two-sided intent and zero live permission, binds the
exact condition/token, and is revalidated by `run_stage1` before credentials or
a mutation-capable adapter are constructed. The plan explicitly remains
non-authorizing.

The first real one-market paper attempt was useful but not successful: the new
v0.3 economics gate rejected the production v0.2 snapshot, so it emitted zero
quote permissions and no live permission. No baseline was accepted. After the
protected capture window, collect a fresh external v0.3 snapshot, rerun the
one-market tick, and require nonzero quote permission before closing the active-
day proof. Immutable exact-tip full-suite proof and guarded integration remain
open.

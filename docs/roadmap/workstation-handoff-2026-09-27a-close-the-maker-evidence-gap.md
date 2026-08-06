# Workstation handoff 2026-09-27a — close the maker evidence gap by backfilling it

## Goal

Maker execution evidence that survives a reconnect, so the settlement-coverage gate can be satisfied
on merit rather than by a lucky gap-free night — and the market-making decision clock can finally
start.

## Why this mission exists

The MM decision clock is at **zero and structurally cannot advance**. Measured on the production host
2026-08-06 from a fresh `mm_paper_report.json`: `quote_rows = 116,556` but `quote_legs = 0`,
`fill_rows = 0`, `clob_recon_book_rows = 0`, `vacuous = true`, `fill_evidence_completeness = BLOCK`
on `no_quote_legs`, against `min_edge_allowed_live_days = 14` and `min_edge_allowed_fills = 10`. The
day counter can tick while the evidence stays vacuous, so **the gate can never decide** however long
we wait. It is not blocked by `clob_freshness`, the reservation, or promotion.

`-09-18a` built the producer that would supply that evidence. It passed every resource limit with
wide margin and returned **NO-GO** on one thing: a 2.165-second reconnect gap broke continuous
settlement coverage.

`-09-25a` then tried to re-specify that gate to materiality and **correctly falsified the attempt**:

- the cadence-derived threshold came out at **0.000 s** — two distinct San Francisco trades share one
  exchange millisecond, so no positive gap duration is provably safe;
- the 60 bound receipts (`mm_execution_capture_bound_session_v0.1`, 42-field union) contain **zero**
  quote, decision, fill, resting-state, gap or overlap fields, so emptiness cannot be proven at any
  threshold.

**The gate is correct.** A market maker that cannot account for its own blind spots is not safe to
run live with real money. Read
[`RETRACTED_AND_FALSE_LEADS.md`](../operations/RETRACTED_AND_FALSE_LEADS.md) — the master agent's
"the gate is over-specified" thesis was wrong on this instance and is recorded as such.

## The idea this mission tests

Both prior attempts asked *"can we prove nothing happened during the gap?"* That is hard because
during a disconnect we receive nothing.

**Ask instead: can we simply fill the gap?** After reconnecting, fetch the public market data for the
gap window over REST and splice it in. If that works, continuity stops being a question of proof and
becomes a question of retrieval — and the existing gate passes on merit, unchanged.

This is plausible because we already speak to these endpoints: `market_microstructure.py` captures
`/prices-history`, and `https://clob.polymarket.com` is already in use.

**Note the asymmetry that makes this tractable: the maker runs in paper mode.** There are no resting
orders of ours to reconcile. Fill attribution is counterfactual against the *public* tape, so what a
gap costs us is public trade and book data — which is retrievable — not private order state, which
is not.

## Start from this, do not re-derive it

Read [`DELEGATION_CONTRACT.md`](../operations/DELEGATION_CONTRACT.md) and
[`RETRACTED_AND_FALSE_LEADS.md`](../operations/RETRACTED_AND_FALSE_LEADS.md) first. Take as given:

- `-09-25a`'s two findings above. **Do not re-derive the cadence threshold and do not re-litigate the
  gate.** No new soak was run there, deliberately, and that was correct.
- `-09-18a`'s producer on `codex/workstation-respecify-the-maker-settlement-gate-2026-09-25a`
  (tip `75882434`, which already contains `-09-18a` and `-09-11a`). **Reuse it. Do not rewrite it.**
- Reconnects are normal: 4 remote losses in 6 h 52 m, about one per 1.7 hours. Any design that
  assumes a clean settlement half-hour is a lottery ticket.

## P0 — can a gap be backfilled at all? (cheapest falsifier, do this first)

Take the **known** `-09-18a` gap: coverage ended `00:08:24.636461` ET and full readiness returned
`00:08:26.801465` ET on 2026-08-06.

Determine, read-only, whether the public API can reconstruct that window: which endpoints, what
granularity, what retention horizon, and whether the result is **exact** (every trade and book change)
or merely **indicative** (sampled prices). Report the precise endpoint and response shape.

**If the API cannot reconstruct a two-second window exactly, stop and say so.** That is the whole
premise. A partial or sampled reconstruction is *not* a pass — say plainly which it is, because an
indicative backfill presented as exact would corrupt every maker P&L number downstream.

Also state the **retention horizon**: a backfill that only works for recent windows implies the
producer must reconcile promptly, which is a design constraint, not a detail.

## P1 — implement gap backfill, only if P0 passes exactly

On reconnect, retrieve the gap window, splice it into the tape in the same canonical form as streamed
data, and **mark every backfilled row as backfilled** with its retrieval provenance. Streamed and
backfilled rows must remain distinguishable forever; a downstream consumer that wants to exclude
backfilled evidence must be able to.

Extend the session receipt so it binds, per gap: the gap bounds, the retrieval endpoint and time, row
counts recovered, and whether the window is now **exactly covered**. Bump the receipt schema version;
do not mutate `mm_execution_capture_bound_session_v0.1` in place.

## P2 — soak under the unchanged gate

Re-soak with its own isolated evidence root. **The settlement-continuity gate stays exactly as it
is** — the point is to satisfy it, not to move it. Report GO or NO-GO plus the gap/backfill
inventory.

**Do not register or start `WeatherMakerExecutionCapture`, and do not schedule anything.**
Registration is a separate operator decision.

## Boundaries

[`DELEGATION_CONTRACT.md`](../operations/DELEGATION_CONTRACT.md) §2 binds in full. In addition:

- **Public market data only, read-only.** No order placement, no cancellation, no authenticated
  trading endpoint, no credential of any kind. Nothing in this mission may touch live trading.
- **Do not relax the settlement-continuity gate, or any other gate.** If backfill does not close the
  gap, the answer is NO-GO, not a softer bar.
- **Do not relax the promotion gate for `harvest_only` rows** — operator decision, not delegated.
- Respect the exchange's rate limits and the existing `source_family_rate_limit` machinery. A
  backfill storm that degrades live capture is a failure of this mission.
- No production, mirror, or `D:\weather-mirror` writes. Never read `C:\Users\micha\.weathersync.cred`.
- Concurrent owners — do not edit: `model_features.py` (`-09-26a`, `-09-20a`),
  `schema_registry_data.py` (`-09-19a`, `-09-20a`), `forecast_history.py`, `base_retrain.py`,
  `nightly_retrain.py`, `daily_refresh.py`.
- Roll verdict from the retained `runtime_identity.source_scope_files` arrays, not `SOURCE_PATTERNS`.
  Do not merge.

## What would falsify this mission

1. **The API cannot reconstruct a gap window exactly.** The premise dies at P0 and the honest result
   is to say so — that redirects the work to accepting bounded uncertainty in maker scoring, which is
   a much larger and more interesting question.
2. **Backfill is only indicative, not exact.** Sampled prices cannot support counterfactual fill
   attribution. Do not dress this up as a pass.
3. **The retention horizon is too short** for a producer that reconciles on its own schedule.
4. **Backfill closes the gap but the soak still fails** on something else — then continuity was never
   the binding constraint, and `-09-18a`'s NO-GO had a second cause we have not found.
5. **Rate limits make prompt reconciliation incompatible with live capture.** If closing the evidence
   gap costs capture continuity, that is a direct conflict with the project's first objective and the
   trade-off is the operator's to make, not yours.

## Deliverables

- Branch: `codex/workstation-close-the-maker-evidence-gap-2026-09-27a`, based on `75882434` merged
  with current `origin/master`.
- Report: `docs/roadmap/agent-report-2026-08-06-workstation-close-the-maker-evidence-gap.md`
- Report structure per [`DELEGATION_CONTRACT.md`](../operations/DELEGATION_CONTRACT.md) §5.
- Push the branch only. No PR, no merge, no force-push, no branch deletion.

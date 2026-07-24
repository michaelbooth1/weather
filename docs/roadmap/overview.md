# Roadmap Deep Dive (2026-05-31)

> **Historical context, not current instructions.** This document preserves a
> dated roadmap analysis and later incremental notes. Use
> [active-backlog.md](active-backlog.md) for current work and the owning
> numbered item file for authoritative status and acceptance criteria.

### North Star

The project goal is to project the daily high-temperature settlement bucket
better than Polymarket. The durable accuracy target is therefore not "does the
weather forecast look right?" but:

- model Brier/log loss better than Polymarket yes prices on settlement-scored
  snapshot tapes,
- positive Brier skill score versus the market,
- calibrated probability buckets across market bands and cutoff hours,
- realized edge/P&L that survives thresholding, first-entry scoring, and
  out-of-sample market days.

The latest settlement-scored report (`data/backtest/backtest_report.md`,
regenerated 2026-05-31) is the most important evidence. After adding
coverage-aware market-day labels, only May 28 currently passes the
`complete,manual_override` quality filter; May 27 starts too late and May 30
has a 74-minute collection gap. The strict headline report therefore scores 1
clean market day and 704 band rows. The uncalibrated model Brier was 0.0583
versus market Brier 0.0394, and model log loss was 0.1850 versus market log
loss 0.1230, for a Brier skill score of -0.478. The older 3-day calibration
sample remains useful as provisional research, but two of those tapes are now
partial. The correct roadmap posture is clear: we need more clean settled
market days before claiming the model beats Polymarket.

Audit refresh (2026-06-14 UTC): the settlement ledger had fallen behind the
available snapshot folders. A later refresh reconciled 105 settled folders with
Polymarket (`match=105`) and raised the label ledger to `complete=54`,
`partial=51`. The missed days were not absent from capture; they were recent
fleet tapes that had not yet been finalized into the ledger/promotion corpus.
Promotion evidence improved after refresh, but the current
`data/backtest/f_family_promotion_refresh_report.md` still does not prove broad
edge versus Polymarket: the F-family corpus has 51 market-days, aggregate
candidate Brier is `0.0436` versus market Brier `0.0379`, Atlanta, Denver, and
Houston are `PROMOTE_CANDIDATE`, eight F markets remain shadow, and no
candidate markets are blocked.

### Roadmap Triage (2026-06-15 UTC)

Can be done now, in implementation order:

1. [COMPLETE] Item 47: wire `mm_known_edge_map.json` into `mm_policy` and
   `market_making_run` so every quote-intent row carries generated evidence
   fields. Security clarification (2026-07-23): the detached
   `mm_known_edge_map_v0.2` and `promotion_allowlist_v0.1` schemas are
   recommendation/diagnostic artifacts, not runtime authorization envelopes;
   an `edge_allowed` claim is capped at research until a future independently
   verified authorization schema exists.
2. [COMPLETE] Item 52: validate Miami `wu_max_since_7am`, scope the hard-floor
   change to Miami only, and clear the current-serving Miami `BLOCK`.
3. [COMPLETE] Item 49: add `forecast_high` and `forecast_gap` to late-day
   continuation training, regenerate all tracked late-day artifacts, and prove
   the refresh on settlement-scored replay.
4. [COMPLETE] Item 37: define/enforce the live-forward SLO and gap-free active-day
   tape gates in software; final clearance still requires a clean future active
   day, and the current strict report blocks on snapshot and CLOB tape gaps.
5. [PARTIAL] Item 39 cleanup: source/truth/storage/gate hygiene is reconciled;
   remaining work is infrastructure-heavy, especially schema migration tooling
   and the Parquet/freshness dashboard.
6. [COMPLETE] Item 55: reconcile quote lifecycle and budget reservation state before
   treating the running market-making test's budget numbers as live-gate
   evidence.
7. [COMPLETE] Item 57: turn the current `paper-live-forward` preflight blockers
   into source-status/model/CLOB remediation incidents so a future active day
   can count.
8. [COMPLETE] Item 56: upgrade the MM dashboard into an operator cockpit that
   separates latest tick, cumulative run, paper corpus, and live-forward gate
   state.
9. [COMPLETE] Items 58-60: turn the 2026-06-15 Miami 92-93 F audit into
   concrete follow-up work. Item 58 is complete: the intra-hour WU print-lag
   feature parity bug is fixed and gauntlet-proven. Item 59 is complete: the
   afternoon high-has-stood lock-in component is live, explained, and
   gauntlet-proven with per-market activation caveats documented. Item 60 is
   complete: range-band endpoints, replay compatibility, latest-row
   diagnostics, and stale-code collector guards are live.
10. [COMPLETE] Items 61-64: turn the 2026-06-15 historical/nearby-station audit
    into provenance-safe follow-up work. Item 61 is complete: registered
    supplemental station roots now carry source id, station provenance,
    distance, adopted windows, and canonical-plus-supplemental audit coverage.
    Item 62 is complete: supplemental station validation artifacts, promotion
    states, and fail-closed audit gates are live. Item 63 is complete:
    validated nearby rows now feed historical-only source-trust/redundancy
    features without changing settlement labels or live-serving columns. Item
    64 is complete: canonical history provenance guardrails and explicit
    composite GHCNh views are live.
11. [COMPLETE] Items 69-73: turn the multi-variant shadow-testing research note into
    concrete model work. Item 69 is complete: the paired shadow harness and
    experiment governance are live. Item 70 is complete: the exact-winner
    candidate now uses a no-market per-market alpha whitelist, clears the broad
    replay and item-69 harness gates, improves settlement-distance-0,
    exact-band, and 7-15 target slices, and no longer regresses one-above or
    Miami.
    Item 71 is complete as a guarded no-market shadow variant: dynamic
    source-state features are replay/live model inputs, the full artifact now
    improves the combined failed/stale source bucket and all-fresh rows, and
    sparse unproven failed-source states fall back to current instead of
    becoming noisy evidence. Item 72 is complete: raw and
    gated CLOB overlay lanes now score through item 69 as market-informed shadow
    variants with log-loss/ECE/overconfidence gates; the refreshed known-edge
    map emits only a `market_lead` `edge_research` quote-time record and keeps
    `book_liquidity_artifact` blocked on log-loss regression, so it remains
    separate from no-market promotion evidence. Item 73 is complete: the
    conservative bridge alpha schedule
    and no-market item-69 policy-shadow export are live; paired scoring improves
    both current serving and the pooled candidate control, while still trailing
    market and leaving future alpha changes behind deliberate readiness updates.

Blocked or gated:

- Item 45's software gates are complete. Live MM-2 orders remain blocked until
  the platform-verification artifact, live-readiness file, data-layer live gate,
  and 14 locked live-forward paper-day gate all pass for a real pilot.
- Item 48 promotion readiness is blocked as a readiness claim until aggregate
  candidate Brier is market-or-better and remaining shadow markets have
  generated, resolved blockers; decomposition work remains actionable.
- Item 37 live-forward gate credit is still gated by future evidence: the
  software gate now fails closed, but the current strict report is `CRITICAL`
  for both snapshot collection gaps and CLOB book-capture gaps, so a paper/live
  day counts only when a future active day clears both in real time.
- Item 35 continuous density is gated behind stronger settlement-scored proof
  from the current F-family and failure-slice work.
- Item 27, item 32, and the infrastructure families in item 50 are blocked from
  promotion until their historical/archive coverage exists and they pass
  replay-safe validation.
- Any feature or quote mode that relies on live-only data remains blocked from
  promotion until matching historical or live-forward evidence exists.
- The Miami 2026-06-15 92-93 F audit package is complete via items 58-60:
  print-lag parity, afternoon high-has-stood lock-in, and range-band/version
  artifact guards are now implemented.
- Multi-variant testing is gated by item 69. Variants from items 70-73 should
  not be promoted from ad hoc reruns or raw row-count wins; they need paired
  shadow evidence, no-market versus market-informed separation, and per-market
  promotion checks.

### Current Work That Needed Roadmap Reconciliation

- `docs/operations/AGENT_CONTEXT.md` captures the current
  mission, architecture, settlement hierarchy, commands, risks, and best next
  work.
- The test suite is much larger than the 2026-05-28 audit stated. Current
  verification on 2026-06-01: `pytest -q` passed with 141 tests, and
  `python -m compileall src tests` passed.
- The feature model now includes Open-Meteo forecast daily-max features
  (`forecast_high`, `forecast_gap`) in training and live extraction, and
  `src/feature_model.py` has `RUN_LOO = True`.
- The feature-model report now includes log loss, Brier, accuracy, ECE,
  per-hour HGB climatology-blend weights, and feature-family ablations. This
  updates old item-6/item-24 audit notes that said forecast max, Brier/ECE, and
  ablation visibility were absent.
- Market-day labels are now coverage-aware: settlement labels include capture
  ratio, max gap, and coverage reason, and the headline backtest excludes
  partial tapes by quality grade.
- The snapshot loop now has a managed runner, PID/start/heartbeat/error status,
  `--status`, pause flag handling, and diagnostics logging. Item 16 is now
  partial rather than not-started; clean stop/restart remains open.
- Live fetches now have retry/backoff and last-good source caching with a
  90-minute age cap. Item 17 is now partial; separate per-source TTLs and
  structured source-level diagnostics remain open.
- Several "COMPLETE" roadmap items were really implemented prototypes with
  accuracy-grade follow-up work. This roadmap now distinguishes "visible in the
  app" from "calibrated enough to improve edge versus Polymarket."

### Best Path To A More Accurate Model

1. Make the evaluation target unambiguous. Every model improvement should be
   scored against Polymarket prices, by target day and cutoff hour, with
   correlated intraday snapshots handled conservatively. This is item 20.
2. Increase clean market-day capture. Better models need more settled market
   tapes, not just more historical weather rows. This depends on items 16, 17,
   20, and 25.
2a. Capture market microstructure now, not later. The 2026-06-12 data-layer
   audit found that the weather/model loop is healthy, but the market data tape
   was shallow: Gamma best bid was only 48.0% filled and no CLOB token ids,
   order-book depth, or trade stream were persisted. `src.market_microstructure`
   now provides the fast capture path, but historical order-book depth from
   before this ship cannot be recreated, so keeping the new loop running is a
   data-retention priority before final trading-model work.
3. Calibrate before adding complexity. The HGB model has useful signal, but
   the live model can be overconfident versus market prices. Add a market-bin
   calibration layer and shrink high-confidence exact buckets unless history
   and live settlement-source evidence justify them. This is item 21 and is now
   complete; it reduced overconfidence but did not close the gap to Polymarket.
4. Replace heuristic forecast caps/floors with learned forecast-error
   distributions by source, horizon, and regime. This is item 22 and is now
   complete for the first artifact-backed forecast component.
5. Explicitly model WU settlement lag and revisions. Non-resolution sources
   should update probability through a learned catch-up process, not through
   ad-hoc confidence. This is item 23.
6. Use one feature-generation path for training, backtesting, live inference,
   and explanations. This prevents train/serve skew and makes model changes
   auditable. This is item 24 and is now complete.
7. Build the ensemble/ablation framework on top of those shared features, with
   fast sampled validation and separate no-market versus market-informed
   scores. This is item 26 and is now complete as a framework; the strict
   sample is still too small to promote an ensemble.
8. Add physically meaningful weather-regime and microclimate features only when
   item-20/item-26 reports can prove their value. This is item 27.
9. Only then expand model classes, other markets, or trading automation.
   Sophistication without a stronger evaluation harness will create attractive
   but unproven probabilities.

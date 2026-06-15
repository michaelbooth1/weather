# Sequencing The Two Tracks

0. **Item 39 P0 (the `_c`-column unit lie)** first — it silently corrupts any
   canonical-Celsius pooling, so it gates item 33/35. Plus the item 39 cleanup
   tasks (orphan artifacts, forecast_history gaps, ERA5 normalize lag, and the
   GHCNh/ERA5 use-or-drop decision) are quick and unblock clean validation.
1. **Item 28 (settlement ledger)** and **item 33 (pooled F + city features)** in
   parallel — the foundation labels and the immediate model win, both unblocked
   now.
2. Then **31 (observability)** and **34 (F calibration + gating)** as F days
   settle.
   Item 48 now owns the proof that the pooled F pipeline is promotion-ready,
   rather than merely implemented and refreshed; item 53 closed the missing
   source-freshness attribution slice, and item 54 owns downstream
   permission-map consumption of those cells.
3. Then **29-30 (deeper, redundant data)** feeding **35 (unified model)**.
4. **36-37 (gating + MLOps)** harden whatever 33/35 produce.
5. **32 (reanalysis features)** and **38 (cross-market / microstructure)** are
   the long-tail accuracy and edge plays.
   Item 49 was the scoped late-day forecast-gap cleanup split out of items 8 and
   22; it is now complete, with forecast-gap-aware late-day artifacts and a
   non-regressing settlement-scored replay.
6. **41 (disagreement casebook)** now runs as the durable audit layer alongside
   model work: it converts every large live edge into supervised evidence
   instead of another one-off chat audit. **42 (fast observation-triggered
   recompute)** follows item 40's live-reading feature work, item 38's
   fast-book capture, and item 41's large-disagreement slices; it is the next
   latency fix before any quote engine trusts sub-10-minute edges.
7. **43-57 are the market-making bridge and live-forward test loop.** After
   book capture, casebook, and observation-trigger plumbing are stable, build
   the keyless quote policy first, then paper-trade it with conservative and
   queue-aware fills, then add the date/budget run orchestrator, define the
   known-edge permission map, wire source-freshness permissions, and harden the
   running live-forward test with order lifecycle reconciliation, a usable
   operator cockpit, and actionable preflight recovery. Live MM-2 orders wait
   until the policy, paper, orchestration, readiness-map, test-reliability, and
   live-risk gates pass; reward/rebate yield is not treated as alpha until
   adverse-selection markout is deducted.
8. **58-60 are the Miami 2026-06-15 audit follow-ups.** Fix the WU intra-hour
   feature parity bug first (58), add the afternoon high-has-stood lock-in
   component only with pinned-corpus replay proof (59), and make range-band
   artifacts/version identity auditable before trusting future one-off
   disagreement investigations (60).

Current best next actions after the 2026-06-15 MM test review:

1. **Done 2026-06-14: automate the daily settlement-to-promotion refresh.** The biggest audit
   miss was not a model bug; it was a stale ledger/promotion corpus. Schedule
   `src.daily_refresh run --continue-on-error` via
   `scripts/register_daily_refresh.ps1` so clean days enter trust/gates without
   a manual chat-driven nudge.
2. **Done as implementation 2026-06-14: ship item 42's watcher and scoring
   slice.** WU lag/catch-up accounts for 745 settled model-loss cases; the new
   low-cost observation watcher creates tagged urgent recomputes, and
   `src.observation_trigger replay` scores them directly on those case IDs once
   live triggered rows settle. Keep the watcher supervised so the acceptance
   report gains evidence.
3. **Mostly done 2026-06-14: clear false fleet observability criticals.** Miami's
   impossible 2005-06-11 WU value is quarantined and the rebuilt normalized
   daily high is `86 F`; `data_auditor.py --fleet --json --strict` reports zero
   impossible values. The CLOB audit now records startup gaps separately from
   post-start recorder failures; `src.market_microstructure audit --strict`
   passes all 12 active markets. Main snapshot health now separates scheduled
   and triggered cadence and checks strict gaps inside the settlement-decisive
   window. The remaining `src.fleet_observability report --strict` criticals are
   true 2026-06-14 active-day collection gaps, so they stay visible until item
   37's live-forward SLO hardening prevents recurrence.
4. **Done as shadow scoring 2026-06-14: score item 38's CLOB features behind
   the promotion gauntlet.** Market lead is now a measured losing family, and
   market overreaction is a measured winning family. The book-depth, stickiness,
   and liquidity feature plumbing is in place; the CLOB overlay is taxonomy-gated
   and remains non-serving until held-out/live-forward evidence clears.
5. **Delay item 35 until the promotion gauntlet has more days.** Continuous
   density is still the endgame, but today's highest value is using the new
   24-day F corpus and casebook slices to fix concrete, settlement-scored
   failure modes first.
6. **Done 2026-06-15: implement item 46's date/budget run orchestrator.** The
   operator layer now provides date selection, budget ledgers, run folders,
   preflight gates, fail-closed quote/no-quote rows, and a durable report for
   shadow and live-forward paper runs.
7. **Done 2026-06-15: implement items 44, 47, and 54.** The paper scorer now
   provides strict conservative fills, queue companion analysis, markouts, and
   incentive accounting. The known-edge map is policy-consumed, and
   source-freshness permission cells are live.
8. **Done 2026-06-15: complete items 55-57 around the live-forward test.** The
   run budget now reconciles against an order lifecycle ledger, preflight
   blockers emit remediation incidents, and the `?market=mm` page shows
   latest-tick versus cumulative state, blockers, lifecycle budget, and
   live-forward gate progress.
9. **Next: work items 58-60, then accumulate locked live-forward paper days and
   work item 45.** MM-2
   remains blocked until the live-forward paper gate has enough clean evidence,
   lifecycle/remediation/cockpit artifacts stay green, and platform/account/
   wallet/cancel-all readiness is verified.

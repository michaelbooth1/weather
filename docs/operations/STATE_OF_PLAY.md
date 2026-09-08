# State of play

**Last updated: 2026-09-08 America/Toronto (storage and host health).** Read this first; read
`ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` before research.

> **REWRITTEN, never appended. Capped at about 90 lines.** This file owns the
> current decision; numbered items and retained receipts own detailed evidence.

**Objectives:** protect capture and settlement evidence, recover disk headroom
through verified off-site storage, and execute the non-live maker-economics
refocus in [item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md).
**No market edge or profitable maker opportunity is proved.**

## Current authority

On September 7 the owner approved the revised disk-reclaim plan and its
implementation. Bounded cache compression preserves files and requires fresh
overnight admission; this does not waive capture, memory or deletion gates.

The owner authorized the plan's implementation, source-control integration,
and takeover of unfinished cold-storage work on September 4. Ordinary authorized
work proceeds without repeated permission prompts. **The explicit exception is
no live trading.** W5-W7 exchange lifecycle and economic sessions therefore remain
blocked; offline implementation, fixtures, public-evidence analysis and paper
work may continue. Existing host admission, guarded runtime adoption, evidence
retention and restore requirements still govern their exact actions.

## Current truth

| Area | Verified state / remaining limit |
| --- | --- |
| Production source | W0's guarded plan/reporting-pause adoption completed at September 5 01:31:49 as `4603a56138406a66d7f52ee8266572d4b3f80abf`, with three-worker recovery and fresh HEAD/local/cached/live equality. W1 and W2 were previously adopted at `f570f0286194a5abe516e0e73f971038074ceb0a` and `dfcafc5bc175952597e1fd2cc08b9ad50db02937`; their master CI passed. Baseline restoration is complete; generated configs were preserved byte-for-byte in separate commit `19c25ad33de968e4b2c376346b192fee7eb8c9bc`. Consult Git and guarded receipts for later integrations. |
| Portable source versus readiness | Phase repair `3f2b077b95f5dcabbeba8995ac24fb2e4ca85659` and portable topic tip `1acf9ebbc4a9576810b99126ea5ab8764f35aa9b` are ancestors of production master. This establishes integrated source only; the portable clone, current qualification and fresh live receipts have not been re-proved. No live attempt is permitted by this task. |
| Capture | September 8 hourly checks through 08:03 report all three capture families active with zero consecutive errors and advancing snapshot clean iterations. The latest snapshot clean iteration is 77 seconds old; the watchdog is fresh. These are host-health observations, not a new graded streak or fleet-countability proof. |
| Public execution tape | The same receipt reports `CONNECTED` and integrity `PASS`, with `price_path_usable=false`. Do not count a healthy producer as complete price-path evidence. |
| Off-site qualification | The September 5 `v3-r1` independent restore passed 17 checks for one 513,522,801-byte provisional mirror log on source `54da9076c10e6d109062c635211fcd273022f94e` ([PR 23](https://github.com/michaelbooth1/weather/pull/23)). The one-file restore is proved; production source identity, whole-mirror recovery and production deletion eligibility remain unproved. Preserve spent attempts and the frozen mirror. |
| Settlement / recurring work | The September 8 08:03 chain receipt is terminal and deferred at `ingest_quality_gate` by physical-memory/capture admission, with `rollup_freshness` blocked. The bounded 14-day settlement check flags August 28-31 and September 1, 4-6, affecting up to twelve markets on the worst date. The next chain run does not repair those dates automatically. Full-ledger reconciliation and resource-admitted per-date repair remain open. |
| Storage | September 8 helper/app cleanup restored memory headroom. Qualified retained-file compression completed the eligible July 1-3 immediate files: 830 files and 6,308,986,880 newly reclaimed bytes. July 4's pilot adds 42,745,856 bytes. A subsequent memory-gated stop left six completed journals and one compressed file awaiting independent hash verification; further compression is paused while the read-only verification mode is qualified. The 120 GiB newly reclaimed / 100 GiB free target remains open. [Item 325](../roadmap/items/item-325-tiered-data-retention-and-verified-archive-offload.md#production-pilot-and-resource-limited-expansion-september-8) owns exact receipts and resume requirements. |
| Maker changes | W1 governance at `dc580b330f91a8f098752f23f6058a6c016e3d62`, [PR 16](https://github.com/michaelbooth1/weather/pull/16), passed full Linux CI and guarded adoption; all three capture workers passed before/after checks. W2 identity/config at `5ad48d69c4825bce56b0985f222513d3c7fab3a1`, [PR 17](https://github.com/michaelbooth1/weather/pull/17), passed workstation checks, topic-head Linux CI and guarded production adoption; all three capture workers and the public execution-tape producer passed recovery. Atomic paired configuration publication remains open. Both underwent independent review. |
| Feasibility | W3's [pure diagnostic calculator](maker-incentive-feasibility.md) is implemented at `85d086992bab8c77ce976a5d255f90902aae03c3`. Independent review, 91 workstation checks and compilation of both changed Python paths passed. W3/G1 remain open: no current campaign/economics collection, evidence qualification, paid or reconciled profit, or consumer/CLI/executor integration. Git, CI and guarded receipts own source-integration status. |
| Accounting | W4's static source trace is complete. Next is a pure offline accrual-to-wallet-credit matcher within the existing reports family, preserving the cash identity. No account failure or paid incentive is observed; item 330 records the design receipt. |
| Documentation debt | The status receipt still reports a pending integration-documentation transaction. A draft state rewrite or passing source suite does not close it; reconcile actual pending tips and publish the required documentation before claiming a completed transaction. |
| First recurring-job reduction | At September 5 00:30, only `WeatherModelMarketDisagreementAnalysis` was disabled after exact task/action and python/pythonw process checks. Before/after XML differs only by task Enabled=false. Stage A rehydration and all report/audit evidence remain; daily-learning freshness still matters. The exact receipt is `scratch/handoffs/model-disagreement-on-demand-20260905.md`. No runtime savings are yet measured. |

September 8 observations use the production-local ignored receipt
`scratch/handoffs/overnight-status-20260908-0803.json`, timestamp 08:03 local,
SHA-256 `219f6c89faa0f03bee8652ba43875f8572488fa110d493e43d163a5178d3ac4b`.
Older entries retain their own dated evidence. These files need not exist in a
clean checkout; historical exit codes and copied burn rates are not fresh proof.

## Ordered non-live critical path

1. Recover at least 120 GiB of additional capacity and finish above 100 GiB
   free under the owner's September 8 approval. Qualify the exact cold snapshot
   compression selection and measure retained-file savings under today's dated
   storage exception. Continue archive qualification under item 325; neither
   workstation fixture savings nor the earlier 16.04 GiB meet this new target.
2. Complete exact-head CI and the documentation closeout,
   then recheck the canonical roll verdict for each published tip and use the
   integration/recovery path. Preserve generated config and capture evidence.
3. Review W0's proposed recurring-job dispositions and mixed daily-chain steps,
   and scope the remaining fleet/ledger gaps before choosing a resource-admitted
   repair for the confirmed Toronto omissions. Do not infer ledger rows from a flag.
4. Qualify exact current campaign, terms, books and adjusted-midpoint provenance,
   then use the existing W3 calculator with competitor-score scenarios; aggregate
   depth does not identify a nonlinear per-maker denominator. Continue W4 accounting
   gaps; no assumed campaign or profit.
5. Continue offline W5 readiness and accounting fixtures. Real W5-W7 sessions
   stay blocked by the owner's no-live instruction; a green suite cannot remove it.

## Standing decisions that still bind

- International Polymarket only; no paid weather providers or new statistical
  alpha allocation. Models serve risk/settlement interpretation until a specific
  measured failure justifies research. No new predictor is on the critical path.
- Spent reconciliation, live and archive attempts remain immutable evidence;
  never retry, rewrite or reconstruct a spent namespace as a fresh attempt.
- Capture-host heavy work remains time-gated, admitted and serial. The separate
  workstation uses its exact host/principal admission wrapper and shared mutex.
- Source integration, runtime adoption, release qualification and live authority
  are distinct. Follow the owning canonical contracts, not superseded dated prose.
- Native units, WU effective-print cutoffs, probability mass, train/serve parity,
  captured-input replay, release binding and evidence retention remain mandatory.

## Update this file when

Rewrite after source publication/adoption, a storage/restore result or reclaim,
validated settlement/job dispositions, an economic-feasibility result, or a
changed owner instruction. Move superseded operational detail to its evidence owner.

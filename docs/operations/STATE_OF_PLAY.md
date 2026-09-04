# State of play

**Last rewritten: 2026-09-04 America/Toronto.** Read this first; read
`ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` before research.

> **REWRITTEN, never appended. Capped at about 90 lines.** Put quantitative
> evidence, false claims, and durable mechanics in their owning canonical file.

**Objectives:** protect capture and settlement; convert the existing weather
archive into statistically defensible model evidence; obtain a complete,
point-in-time-compatible outcome cohort; then measure International maker
economics after costs. **No market edge is proved and no live trade is
authorized.**

## Current truth

| Area | State / next action |
| --- | --- |
| Production Git | Baseline reconciliation completed successfully in the 2026-09-04 quiet window. Local `master`, cached `origin/master`, and the live remote all equal merge `7480172a1315868727af18af04895475cbd5d048`; its ordered parents are preserved-config commit `ca4313a7652666969720d711e468d1ec6f43d154` and reviewed repair tip `296f8d2dfb7c90beb74767b4e56f695cbc502e0b`. The worktree is clean, the exact two production-generated location configs were preserved, all three capture workers recovered, and the single authorized `WeatherOneShotPush` invocation succeeded. The authoritative report is `data/alerts/quiet_window_merge_last.json`. |
| Capture | The 2026-09-04 02:46 host status is `TODAY: ON_TRACK` with 21 captured intervals and zero reported maximum gap. Snapshot, market-microstructure, and observation-trigger supervisors are running at AboveNormal priority, apart from one snapshot child temporarily Normal under the five-minute priority guard. The public execution tape is connected but its complete price path is not currently usable. |
| Settlement | Canonical bounded repair restored all 12 markets for 2026-08-25 and 2026-08-27 with zero reported errors or retries. Five explicit holes remain for 2026-08-28 through 2026-09-01. Do not continue bulk repair while disk headroom is below the host policy threshold; each date remains an independent bounded repair and must prove all-market ledger content, not merely a zero process exit. |
| Storage | The production disk is the immediate operational constraint: 46.9 GiB was free at 02:46 and the recent trend was about 8.9 GiB/day. The off-host mirror remains operator-paused and its frozen copy is not verified restorable, so it must not be treated as a recovery copy or silently re-enabled. Six already-published validation roots under `C:\tmp\weather-ws9*` are known redundant, but automated removal was policy-blocked; retain them until an attended, exact-target cleanup. |
| Documentation | This rewrite closes production truth after three accumulated integrations. The ignored pending transaction remains authoritative until a published documentation commit, synchronized `master`, and a passing `documentation_transaction complete` receipt bind all three integration tips. |
| Scheduler/status | `WeatherMaintenancePostBoot0823` is disabled after a successful self-disarming run and has a valid PASS receipt; the current status warning appears to misclassify that one-shot contract. Treat this as a monitor-repair candidate, not authority to re-enable the task. Historical failed and spent one-shots remain evidence, not a retry queue. |
| Workstation | The separate 32 GiB workstation is the ordinary implementation, full-test, collection, training, replay, and measurement host. Its unattended runner now provides heartbeat, absolute deadline, child-tree teardown, generic handback validation, complete-history bundle verification, strict fsck, and external final-tip/tree/blob binding. Mission 100b repaired only the malformed 100a handback metadata and reached `COMPLETE_VALIDATED`; no scientific result changed. |
| Forecast inputs | The exact 2026 12-field, leads 1-7 corpus is complete at 1,645,056 rows. The 2021-2025 research collection retains every requested cell and explicit gap: temperature-only for 2021-2023, eleven fields for 2024, and all twelve for 2025. The separate calendar extension is complete for 2025 and has explicit January-2024 gaps. These archives increase training support but do not by themselves establish point-in-time availability or model edge. |
| Model evidence | The sealed seasonal challenger, multiyear NWP residual challenger, and calendar residual replication were all `INCONCLUSIVE_UNDERPOWERED`; confidence intervals crossed zero and no distribution challenger, promotion, or retrain was authorized. This is evidence about power and signal size, not evidence that improvement is impossible. The next efficient step is completing the predetermined outcome cohort, then running a newly frozen replication rather than another unrestricted feature sweep. |
| WU outcome gap | The outcome-blind 100a contract inventories 816 requested market-days: 720 locally admissible, 94 missing, and 2 below the 18-row threshold; 59 of 68 dates are fully complete. Its exact production request contains 96 market/date keys and can raise the cohort to at most 68 complete dates and 816 market-days. A safe read-only, create-only production exporter is being implemented and tested on the workstation; no outcome value has been opened by that mission. |
| Maker economics | Existing workstation quote-intent evidence has 2,916,117 rows but no authenticated fills, canonical execution tape, exchange reconciliation, or realized economics export, so admissible maker-economics support remains zero. The default-off International market-harvest companion is implemented on a stacked workstation branch and must remain paper-only until reviewed integration and fresh evidence. |
| GitHub queue | The experiment-executor MAX_PATH repair passed its complete workstation suite and has a draft PR targeting `master`. The International market-harvest companion is stacked on that repair and has a separate draft PR. The unattended-runner portable-binding repair has exact-head Linux and Windows CI PASS on its draft PR. A green branch or PR is review evidence only; it is not production adoption or live authority. |
| Portable live lane | The tracked 32 GiB PC remains the sole `portable_execution_v1` host for a future attended International Stage 0/1 attempt. The repaired receipts now distinguish authenticated stream subscription from REST mutations and require exact heartbeat/cancel evidence. No new attempt may inherit an old candidate, receipt, credential comparison, or action-time geography decision. |
| Live money | Prior pilot attempts are spent. No unattended session may place an order or perform a mutation-capable live stage. Any future Stage 0/1 action remains attended, International-only, exact-tip and credential-bound, geoblock-checked, capped at the reviewed 10 pUSD request / 100 pUSD wallet limits, and subject to terminal cleanup reconciliation. |

## Closed decisions -- do not relitigate without new evidence

- The production baseline incident is closed at exact merge `7480172a...`; do not replay either historical reconciliation attempt or reconstruct its one-use publication authority.
- A remote branch push never rolls production. Roll-free branches can be
  reviewed and integrated during the day; only a canonical
  `roll_verdict.ps1` result of roll-sensitive requires the 01:00-04:00 guarded merge path.
- Heavy work on the production capture host remains limited to 00:30-09:00
  under the shared workload lease, regardless of roll sensitivity. The
  repository Stage-A chain is the sole scheduled daytime exception.
- Full tests, training, broad replay, and collection belong on the workstation. Production verification is bounded and serial; do not bypass the host hook, S4U guard, disk threshold, or workload lease.
- Configured Weather Underground history is the settlement proxy. Supporting sources cannot silently replace it, and pre/post 2026-07-31 provenance may not be pooled.
- Do not reopen outcome values until the next evaluation design, cohort, exclusion policy, models, metrics, bootstrap, and terminal attempt semantics are frozen. An integrity-failed create-only attempt is never rerun.
- More than 500 GiB captured is not equivalent to more independent settled
  dates. Improve power by adding independent dates and complete labels, not by
  treating correlated hourly rows as new samples.
- International Polymarket only. No Polymarket US probe, credential, readiness
  decision, order mutation, or new production path is permitted.
- No alpha or paid weather provider. Candidate selection, paper intent, a
  no-fill lifecycle, or a successful export does not prove profitability.
- The paused mirror, generated runtime data, and retained attempt evidence must
  not be rewritten or deleted casually.

## Ordered critical path

1. Publish this roll-free documentation transaction and bind its completion
   receipt to integration tips `4feef39a...`, `788ff8e4...`, and
   `7480172a...`.
2. Finish the workstation's synthetic-only production-exporter implementation,
   independently validate its exact handback, and review the complete stacked
   diff before any production execution.
3. If the exporter is accepted, run one bounded read-only production export of
   the exact 96 WU keys into a new protected external directory. Fail closed on
   any missing key, source drift, threshold failure, or identity mismatch.
4. Transfer and revalidate the two-file export on the workstation. Before
   opening its outcomes, freeze a wholly new replication design using the
   already-fitted baseline/challenger identities and explicit pre/post
   boundary reporting.
5. Use that replication to decide whether residual/distribution work is worth
   another fit. If uncertainty still crosses zero, collect new independent
   dates and improve missing historical fields; do not spend the corpus on
   repeated adaptive searches.
6. Review and integrate the draft engineering PR stack by dependency. Use
   daytime integration for canonical roll-free results and the guarded quiet
   path only when the canonical verdict says a live import closure can roll.
7. Restore storage headroom and then repair the five remaining settlement
   dates one at a time, preserving capture and all retained evidence.

## Verification boundary

A finite audit cannot predict every unknown defect. The durable standard is
fail-closed identity/path binding, immutable claims and receipts, exact
train/serve and source parity, independent-date evaluation, complete child-tree
containment, bounded execution, and truthful uncertainty. No branch, export,
paper row, or statistical point estimate is live or capital authority.

## Update this file when

Rewrite after documentation-transaction completion, any production integration
or capture/streak change, workstation exporter or replication result, storage
recovery, portable qualification, or any Stage 0/1 action.

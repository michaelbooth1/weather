# 326. Supervised Continuous Public Execution Tape [PARTIAL 2026-08-14 - SUPERVISOR PREPARED; INTEGRATION, ADOPTION, AND SOAK OPEN]

Goal: continuously retain the International public execution stream needed for
counterfactual price paths without creating an unmanaged fourth process on the
production capture host.

Owner/package: weather.market, weather.operations

Source: the bounded production pilot in `docs/operations/ESTABLISHED_FINDINGS.md`
§8c proved the execution-only stream's subscription, routing, identity
preservation, resource coexistence, and teardown. The audit then found that the
producer had no scheduler supervision, PID/runtime identity, stale-code
readoption, or roll-verdict participation, so directly registering its
`capture` command would make a live source closure invisible to operations.

Why this matters: public market paths cannot be reconstructed exactly after a
websocket gap, and paper counterfactual markouts are the only use this tape may
support. A cheap producer is still unsafe if it can die silently, survive on
stale code, or disappear from merge-impact analysis.

Evidence boundary: public `last_trade_price` rows support received-time market
paths and counterfactual markouts only. They do not prove our fills, queue
position, fees, rebates, inventory, or P&L. Those require authoritative
own-account evidence under item 67.

Scope:

- [x] Add a dedicated lifecycle supervisor around the read-only producer with
  exact process provenance, single-writer lock agreement, heartbeat health,
  stale-code readoption, restart backoff/circuit breaking, and fail-closed stop.
- [x] Add a current-user S4U/Limited registrar whose worker has no credential,
  wallet, signing, order, cancellation, or exchange-mutation argument path.
- [x] Make the armed/active producer's loaded import closure participate in
  roll verdicts and staleness checks without making the never-armed state a
  false critical alert.
- [x] Surface armed process/lock/identity failures and public evidence-integrity
  loss in the host status while preserving the separate three-worker streak
  definition.
- [x] Preserve execution-only persistence: discard book and price-change bursts,
  retain explicit gaps and exact seed bindings, and keep public identities
  blocked from unique-execution/intensity claims.
- [ ] Pass an immutable exact-tip full suite for the prepared branch.
- [ ] Integrate through the quiet-window path because the producer and central
  runtime/schema closure are roll-sensitive.
- [ ] Explicitly register and start the task off-window; prove exact action,
  S4U/Limited principal, low priority, one worker/lock owner, current runtime
  identity, and healthy coexistence with all three core capture workers.
- [ ] Complete a forward soak long enough to observe rollover, reconnect/gap
  accounting, storage growth, non-deleting log rotation, and alert behavior;
  record measurements only in `ESTABLISHED_FINDINGS.md`.

Acceptance: while armed, exactly one read-only producer survives reboot and
stale-code adoption, every stop/restart is bound to the recorded process
instance, its closure cannot disappear from roll decisions, and evidence loss
is visible. Continuous public data must remain clearly separated from
authoritative own-account lifecycle and economics evidence.

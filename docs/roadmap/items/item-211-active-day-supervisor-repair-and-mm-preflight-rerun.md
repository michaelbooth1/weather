# 211. Active-Day Supervisor Repair And MM Preflight Rerun [OPEN 2026-06-22 - JUNE 21 PREFLIGHT BLOCK NEEDS OPERATOR CLOSEOUT]

Goal: close the active-day supervisor repair loop when snapshot or CLOB
freshness blocks market-maker preflight, and prove the repair by rerunning MM
preflight before the active day is treated as lost evidence.

Source: the 2026-06-21 log review. The market-maker run
`data/mm_runs/2026-06-21/20260621T153607128252Z` ended with
`preflight_status=WARN`, `live_forward_gate_status=BLOCK`,
`counts_toward_live_forward_gate=false`, `quote_permission_rows=0`, and
`live_trade_permission_rows=0`. The remediation table named Toronto
`model_freshness` with `python -m weather.collection.snapshot_tracker --status`
and Atlanta `clob_freshness` with
`python -m weather.market.market_microstructure ensure`.

Why this matters: items 157, 161, and 210 detect cadence loss and route stale
MM evidence, but the active-day operator workflow still needs an explicit
closeout: run the surfaced recovery command, rerun preflight, and record
whether the day became countable. Without that step, a recoverable freshness
incident can still strand the MM bot at zero quotes for the day.

## Design

1. Add an operator command or daily-refresh step that consumes MM preflight
   remediation incidents and executes or prints the exact recovery command for
   each stale supervisor gate.
2. After repair, rerun MM preflight against the same target date and selected
   markets, writing a post-repair status artifact beside the original run.
3. Preserve the original failing preflight, the recovery command output, and
   the post-repair preflight result so audits can distinguish recovered days
   from unrecovered lost days.
4. Wire the post-repair result into daily progress and fleet observability so
   `counts_toward_live_forward_gate=false` cannot remain the last state without
   a recovery attempt.

- [ ] Add a recovery closeout command for MM preflight remediation incidents.
- [ ] Capture the output of `snapshot_tracker --status` / restart and
  `market_microstructure ensure` when those commands are surfaced by preflight.
- [ ] Rerun MM preflight after recovery and write a post-repair artifact.
- [ ] Teach daily progress/fleet observability to show unrecovered vs recovered
  active-day MM preflight failures.
- [ ] Add a regression fixture from the 2026-06-21 Toronto/Atlanta block.

Acceptance: a stale active-day MM preflight run produces a recovery artifact,
the surfaced supervisor commands are executed or explicitly skipped with a
reason, MM preflight is rerun, and daily progress reports whether the day was
recovered or remains lost evidence.

Related: items 57, 110, 157, 161, 210.

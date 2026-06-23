# 277. Maker All-Market Liveness And Fresh Data SLA [OPEN 2026-06-23 - SELECTED PROOF PASSED BUT ALL-MARKET ROLL STILL STALE]

Goal: make the full all-market maker roll prove useful fresh data activity, not
just process heartbeats, before it can count as active-day evidence.

Source: the June 21-23 maker log audit found a selected three-market proof on
June 23, but no countable all-market maker run. June 21 had `10/12` stale
markets, June 22 had `9/12` stale markets, and the June 23 all-market run was
still blocked by stale model and CLOB inputs. Current supervisor status also
showed live heartbeats with weak work evidence: observation triggers reporting
`stale_code` for several markets, snapshot loop with no
`last_snapshot_written_at`, and a CLOB loop freshly started at `iterations: 0`.

Why this matters: selected-market recovery proves the manual path can work, but
strategy evaluation needs durable all-market active-day collection. A heartbeat
without fresh snapshot/model rows, fresh CLOB captures, and current runtime
identity still starves maker evidence.

## Design

1. Extend maker preflight and daily-roll liveness checks to require recent
   write activity for snapshot/model rows, CLOB book rows, and observation
   trigger outputs, not only process PID/heartbeat.
2. Treat runtime-identity mismatch between supervisor processes and current
   source as a first-class all-market blocker with a restart command and owner.
3. Add per-loop activity fields to maker reports: last useful write, useful
   iteration count, stale-code market count, and markets blocked by stale model
   or stale CLOB tape.
4. Require all-market active-day evidence to prove every selected market either
   passes freshness gates or has an explicit fail-closed exclusion.
5. Preserve prior hard-failure evidence in the report: UTF-8 CLOB CSV decode
   failures and disk-full write failures should be visible as data-starvation
   causes when they recur.

- [ ] Add useful-write liveness checks for snapshot, CLOB, and observation
  trigger loops.
- [ ] Fail all-market maker countability on stale runtime identity, no useful
  writes, or `iterations: 0` after startup grace.
- [ ] Surface stale-code, stale-model, stale-CLOB, UTF-8 decode, and disk-full
  root causes in the maker report and trading evidence summary.
- [ ] Run at least two consecutive all-market active-day maker rolls with
  current runtime identity and fresh data across all selected markets.

Acceptance: two consecutive all-market paper-live-forward maker sessions pass
freshness gates across all selected markets, show recent useful writes for the
snapshot, CLOB, and observation-trigger loops, count toward the live-forward
gate, and report zero stale-code, stale-model, stale-CLOB, encoding, or disk
write blockers.

Related: items 57, 121, 152, 157, 159, 210, 211, 258.

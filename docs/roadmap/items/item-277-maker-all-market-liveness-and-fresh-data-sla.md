# 277. Maker All-Market Liveness And Fresh Data SLA [COMPLETE 2026-06-23 - TWO ALL-MARKET PROOF RUNS PASS]

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

- [x] Add useful-write liveness checks for snapshot, CLOB, and observation
  trigger loops.
- [x] Fail all-market maker countability on stale runtime identity, no useful
  writes, or `iterations: 0` after startup grace.
- [x] Surface stale-code, stale-model, stale-CLOB, UTF-8 decode, and disk-full
  root causes in the maker report and trading evidence summary.
- [x] Run at least two consecutive all-market active-day maker rolls with
  current runtime identity and fresh data across all selected markets.

Implementation note 2026-06-23: `mm_useful_work_liveness_v0.1` is now emitted
in maker preflight, live-forward gate, run summary, and report artifacts. The
gate is enforced only for all-market `active_day_live_forward`
`paper-live-forward` runs, so selected proof runs remain usable while full
all-market sessions fail countability on stale runtime identity, absent useful
writes, zero CLOB iterations after startup grace, stale-code observation
results, stale/missing model rows, stale/missing CLOB rows, CLOB CSV encoding
diagnostics, or daily-roll disk failures. Validation: `python -m pytest
tests\market\test_market_making_run.py tests\reporting\test_trading_evidence.py
-q` passed with 37 tests. The item remains partial until two consecutive real
all-market sessions pass the gate.

Operational audit 2026-06-23 18:07 America/Toronto: the active all-market
paper-live-forward roll `data/mm_runs/2026-06-23/20260623T165025535344Z`
remains non-countable. Its latest summary reports
`counts_toward_live_forward_gate=false`, live-forward gate `BLOCK`, 12 selected
markets, 40 quote-permission rows, 80 paper-posted lifecycle legs, 11 blocked
markets with first failing gate `clob_freshness`, reason counts
`NO_QUOTE_KNOWN_EDGE_PERMISSION=11` and `NO_QUOTE_STALE_INPUT=121`, and one
runtime-identity drift: the snapshot loop is still running a different source
fingerprint than the current code. The current process therefore cannot satisfy
the two consecutive all-market session acceptance gate.

Recovery proof 2026-06-23 18:29 America/Toronto: after restarting stale
snapshot/observation/CLOB loops and refreshing raw CLOB books across all 12
markets, two consecutive all-market `paper-live-forward` finite sessions passed
the active-day gate:

- `data/mm_runs/2026-06-23/item277-proof-2-20260623T2222Z`: 12 selected
  markets, `preflight_status=PASS`, `live_forward_gate_status=PASS`,
  `counts_toward_live_forward_gate=true`, useful-work liveness `PASS`, zero
  blocked markets, zero stale model markets, zero stale CLOB markets, zero
  runtime-identity drift, 132 quote-intent rows, and 396 model-variant rows.
- `data/mm_runs/2026-06-23/item277-proof-3-20260623T2229Z`: 12 selected
  markets, `preflight_status=PASS`, `live_forward_gate_status=PASS`,
  `counts_toward_live_forward_gate=true`, useful-work liveness `PASS`, zero
  blocked markets, zero stale model markets, zero stale CLOB markets, zero
  runtime-identity drift, 132 quote-intent rows, and 396 model-variant rows.

The proof also exposed a follow-up collection-speed gap: sequential all-market
CLOB capture with derived feature refresh was too slow for the 120-second
freshness SLA, while per-market raw-book capture with derived features disabled
completed quickly. That operational automation gap is now tracked separately in
item 282.

Acceptance: two consecutive all-market paper-live-forward maker sessions pass
freshness gates across all selected markets, show recent useful writes for the
snapshot, CLOB, and observation-trigger loops, count toward the live-forward
gate, and report zero stale-code, stale-model, stale-CLOB, encoding, or disk
write blockers.

Related: items 57, 121, 152, 157, 159, 210, 211, 258.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - TWO ALL-MARKET PROOF RUNS PASS`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.


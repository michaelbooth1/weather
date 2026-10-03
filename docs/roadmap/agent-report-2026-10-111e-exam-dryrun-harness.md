# Agent report 2026-10 — 111e: exam dry-run harness (W2 runbook end to end)

## Verdict

1. **The W2 runbook runs end to end on fixture data.** Every step runs as its own `python -P -B -m …` process with the
   runbook's flags and `PYTHONPATH=<worktree>\src`. It ends with the look writing
   `attempts/maker-replay-2026-10-15-v3.completed.json`.
   - The fast test takes 71 s on the workstation and is green in GitHub CI (Linux full suite).
   - It uses one city, 4 segments a day and dense calibration-date prints.
2. **Three refusals before passing; one is a defect in the pinned set (not fixed, scope).**
   `engine_preflight: pull_opportunity_cap` compares the panel's pull candidates with `max_events`. The rule derives
   `max_events` from rehearsed engine events, and the rehearsal never measures candidates. PR #166 found the same
   independently.
3. **The production-scale run** (12 cities, 12 segments, 150k reward rows a day): see
   [Production-scale run](#production-scale-run). Its per-day numbers feed the v2 registration design.
   maker-replay-2026-10-15 was closed by the owner as NOT EXECUTED.

Base: `37092926` (`codex/exam-w2-20261003`, #164). `codex/integration-exam-20261002` was still at `d6086f3c` without the
W2 fixes, so this branch is stacked on #164 and nothing was merged into the exam branch. No file in
`execution_manifest.source_hashes()` changed.

## What was built

- `tools/research/exam_dryrun_fixture.py` writes the exam's 18 UTC days (09-27..10-14) through the production writers:
  - `EvidenceStore` hourly segments, gzipped by `compress_closed_segments`;
  - snapshot CSV, forecast-payload manifests and NBP payloads, and explanations;
  - an immutable release root, so the night kind projects `release_calibration_method`.

  Every day records a power loss after a third of its segments. The restarted store's `_recover` seals the orphaned
  segment, and its `run_summary` gives the receipt exactly one restart event. One trailing segment is left unsealed in
  the open day 10-15. Parameters: cities, segments, minutes, reward rows a day, prints per minute (separately for
  calibration dates) and venue-clock lead, bounded by `MAX_TRADE_CLOCK_SKEW`. The fixture uses +1.2 s and −0.8 s.
- `tests/market/test_exam_dryrun_sequence.py` runs the sequence of the 111e follow-up "Production runbook":
  - module-path probe and `module-hash`;
  - calibration ×3 and night ×3, with `--expected-module-sha256` and `$ExportLim`;
  - receipt asserts: `SEALED`, `module_sha256`, `events_trimmed`, `trade_clock_skew` inside its bound;
  - `quote_markets` and `calibrate_hazard`, with limits sized from the receipts (`global_fallback` null, no
    `binding_status`);
  - `rehearse` ×3, one process each, then `derive_ceilings` (`calibration_sha256` equals the sealed
    `calibration.json`);
  - 15 panel exports, `universe`, `manifest build` and `manifest verify` (both print `VERIFIED_PREFLIGHT_ONLY`), using
    the five signed documents from the worktree and a fixture DECISION_LOG with REVOKE v1 and APPROVE
    `maker-replay-2026-10-15-v3`;
  - `run --compare`, asserting `.completed.json` with `status: COMPLETED`, the manifest hash and `registered_decision`.
- **Test-only shim.** A `sitecustomize.py` written into the test's temp dir follows `src` on `PYTHONPATH`. It patches
  module attributes after import and changes no source byte, so the module hash and `source_hashes()` are the tree's.
  It does three things:
  1. Fixes the clock at 2026-10-15T05:00Z (01:00 Toronto), because the panel dates, the closed-day check and the
     scoring-date gate are hard-coded.
  2. Pins `commit_percent` at 10%; see refusal 2.
  3. Enrols the manifest hash for the look's process only. Runbook C4 does this with a reviewed commit in production.

## Refusals the harness produced before passing

| # | Step | Refusal | Cause | Disposition |
| --- | --- | --- | --- | --- |
| 1 | fixture build | `FileNotFoundError` (Windows `MAX_PATH`) | pytest's default temp path plus `snapshots/<slug>/forecast_payloads/sha256/xx/<64>.json` is over 260 characters | Environment, not code. Run with a short `--basetemp` (documented in `maker-replay-bundle.md`). Production paths are short. |
| 2 | look, `host_preflight` | `host_commit_charge_not_below_70_percent` | Workstation commit charge 96.5% with parallel sessions | Real host reading. Recorded as `NOT_CONSUMED_OPERATIONAL_REFUSAL`, so look protection works. The shim pins 10% because Linux CI can exceed 100% under overcommit. |
| 3 | look, `engine_preflight` | `pull_opportunity_cap` | 4 segments × 1 minute a day gave ~80 engine events per rehearsal date, so `max_events` was a small power of two against tens of thousands of candidates | **Defect in the pinned set** (below). The fixture passes only with dense calibration-date prints. |

### `pull_opportunity_cap` (pinned set, not fixed)

- **Candidates.** `opportunity_candidates` counts minute starts in each condition's active windows. Windows are full UTC
  days minus 05:00–08:00, so each quote day contributes about 1,260 per condition, whatever the capture density.
- **The bound.** `max_events` is `next_pow2(15 × max rehearsed engine events)`. Engine events are distinct capture
  timestamps across all conditions, so they do not grow with the condition count. The look therefore needs
  `Σ_panel conditions × 1,260 ≤ next_pow2(15 × E)`, roughly E ≥ 588–1,176 × conditions per rehearsal date.
- **Why the rule cannot help.** The rehearsal records engine events, not candidates, so `derive_ceilings` cannot size for
  them. The refusal happens before reservation and does not consume the look, but the exam is then not executable.
- **Coupling with memory.** The rehearsal's spans grow as events × conditions, so raising events to clear the cap raises
  the memory and runtime ceilings. In the fast run, one city (3 conditions) and 2,607 events per date gave 12,365
  decisions+spans, 2.4 MB input, 44 MB peak above baseline and 5.5 s per rehearsal.
- **Production check from a built manifest.** Count `opportunity_candidates` over `manifest.active_intervals` and compare
  it with `manifest.replay_config.max_events`. The test does exactly this (`summary["pull"]`).

## Fast run (CI test)

Workstation, 2026-10-02:

- 71 s in total, of which the fixture build is 11 s.
- Rehearsal: 2,607 engine events per date; 52,920 candidates against `max_events` 65,536. Derived ceilings:
  `runtime_seconds` 128 and `memory_bytes` 2,661,187,584. The baseline is 1.59 GB on this 32 GB machine: private
  commit after the numpy/scipy import, before any input.
- Look decision `UNDERPOWERED`, as expected on fixture data.

## Production-scale run

**Shape.** `Shape(reward_rows=150_000, calibration_trades_per_minute=125)`, run under `workstation_heavy.ps1 -Kind
pytest` on the 32 GB workstation from 2026-10-03 16:37:
- 12 cities, 36 conditions a day;
- 12 sealed segments × 2 capture minutes a day;
- 150,000 reward rows a day;
- calibration dates carry 125 prints a minute per city, so the rehearsed events could cover the panel's
  ~635,040 pull candidates.

The fixture build took about 30 minutes, and the three calibration exports, three rehearsal-panel exports, quote
markets and hazard calibration all finished.

**Per-day export receipts.** All six are `SEALED` under one module hash, with one restart event each, `max_us`
1,200,000 inside the 5 s bound, and no `events_trimmed`:

| Kind | Day | `runtime_seconds` | `peak_memory_bytes` | `bundle.bytes` | `bundle.records` | `input_bytes` |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| calibration | 09-27 | 144.0 | 5,056,577,536 | 597,553,844 | 1,334,124 | 94,547,766 |
| calibration | 09-28 | 127.4 | 5,057,601,536 | 597,561,167 | 1,334,124 | 94,569,994 |
| calibration | 09-29 | 117.5 | 5,058,142,208 | 597,565,664 | 1,334,124 | 94,586,546 |
| night (rehearsal panel) | 09-27 | 130.6 | 5,489,938,432 | 670,016,049 | 1,486,245 | 94,580,970 |
| night (rehearsal panel) | 09-28 | 137.5 | 5,493,825,536 | 670,092,564 | 1,486,317 | 94,603,198 |
| night (rehearsal panel) | 09-29 | 159.5 | 5,492,727,808 | 670,131,657 | 1,486,353 | 94,619,750 |

`peak_memory_bytes` includes the workstation's ~1.59 GB import baseline. The export peak is about 8.2× `bundle.bytes`
here. That is above the ~6× output bytes in `maker-replay-bundle.md`, because these bundles are dominated by coverage
rows from dense prints. `calibration.json` reports hazard `1.000000000000` with `global_fallback` null and every city
`sparse_pool_one`: two capture minutes a segment leave n below 1,440, a fixture artifact.

**Rehearsal (09-27): stopped on resources, not completed.** One fresh `rehearse` process on the 670 MB night bundle
(36 conditions, ~36k distinct capture times) was read at 2026-10-03 18:09:
- still running after 61.6 min;
- 35.5 GB private commit, 17.5 GB peak working set, 3,549 CPU-s;
- 1.6 GB of physical memory free on the 31.2 GB machine.

The rule's per-date limits are about 546 s and 546 MiB above baseline (8,192 s and 8 GiB powers of two ÷ 15). This date
exceeds both by more than an order of magnitude. Raising capture density to clear `pull_opportunity_cap` at 12 cities
therefore makes the rehearsal itself infeasible on any 16 GB host, consistent with PR #166's 2.57 GB at its density.
For v2 design, rehearsal memory scales with decisions+spans ≈ events × conditions, not with bundle bytes.

**Not reached.** The remaining rehearsals, `derive_ceilings`, the 15 panel exports, manifest build/verify and the look
were not reached at handback; see the handback note.

## Not done

- No source change to the pinned exam set; no merge into the exam branch; no production data, credential, Scheduler or
  venue call.
- **The local full suite did not run.** The workstation heavy lease was held or stale from 2026-10-02 19:20 until the
  owner stopped WeatherWalletReader on 10-03, and the runner's 12 h window for that stage expired at 10:32. The full
  suite ran green in GitHub CI on `5ca92e5b`: Linux `test`, including the audits and the fast dry run, and Windows
  `native-launch`.
- **Research inventory.** `tools/research/research_harness.py` registers the generator as `fixture-only`; CI's
  inventory ratchet caught the omission.

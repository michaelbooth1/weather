# Agent report 2026-10-03 — streaming scored pipeline for Clarification 4 (STOP at ~120 bands)

**Verdict: STOP (NO-GO at ~120 bands), as the mission's stop rule instructs. No streaming code was written and no hashed
file changed.** At ~120 simultaneously selected bands, the fixture density PR #166 derived from the 88a exporter puts
one calibration date far beyond Clarification 2's per-date budgets. Runtime is about **7.5 h per date** against
~546 s (49 ×). The report is about **31.5 GiB per date** against ~546 MiB (59 ×). Input is about **596 MiB per date**
against ~546 MiB (1.09 ×). A 15-date run would need **≥ 112 h** against the 4 h limit and **~472 GiB of report** against
the 70%-of-16-GiB report limit. A byte-identical streaming pipeline cannot reduce runtime, report bytes or input bytes:
it must do the same work and write the same bytes. It changes memory only. So no Clarification 4 memory rule makes a
~120-band panel executable on this host, and the whole 15-date ~120-band streamed run could not be measured here: it is
≥ 112 h of compute. Memory alone could fit: one loaded ~120-band day holds about 2.7 GiB. But that is moot while three
other ceilings bind.

**Safety finding for production (act on it before the ceiling rehearsal).** `pack_cli.rehearse` has a deadline but **no
memory guard**. At this density the current code retains about **224 GiB** for one ~120-band date (6,374 MiB above
baseline for 40 minutes, linear in minutes). If real calibration bundles resemble the fixture, the planned production
rehearsal would drive the 16 GB capture host into the pagefile long before its 4 h deadline. Measure the real density
first, from `bundle.json` (`tools/exam_pull_cap_precheck.py` on PR #166 prints conditions and pops per date) or with a
short-window probe, before any full-day rehearsal runs on the capture host.

Branch `codex/replay-streaming-20261003` from `origin/codex/integration-exam-20261002` at `664c8943` (W2 + Amendment 3),
with PR #168 (`codex/replay-memory-20261003`, `dd4da634`) merged first. Reserved confirmation window: NONE RESERVED
(checked at run time). No production data, panel data, credentials or venue calls were used: every input is
the synthetic #166 fixture. Owner approval of Option A (2026-10-02) was the premise; this report answers it with a
measured stop.

## 1. Measurements (exam source unchanged; one date, 8 passes, `prof.py --mode multi`)

All runs use PR #166's fixture: churn 1, one capture cycle a minute, a reward clock per band per minute, and trade rows
scaled to the window. Each was a fresh process, started one at a time, and every process exited. Figures are in
[`agent-report-2026-10-03-replay-streaming.json`](agent-report-2026-10-03-replay-streaming.json).

| D (bands at once) | Window | Records | Engine events | Decisions + spans (max pass) | Runtime (s) | Peak above baseline (MiB) | Report bytes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12 | 20 min | 1,119 | 588 | 14,064 | 2.8 | 50 | 5,556,991 |
| 40 | 20 min | 3,667 | 1,680 | 134,240 | 31.9 | 369 | 54,999,536 |
| 60 | 20 min | 7,867 | 2,522 | 302,400 | 90.9 | 824 | 122,897,856 |
| 120 | 20 min | 20,367 | 4,923 | 1,181,040 | 332.2 | 3,181 | 486,500,871 |
| 120 | 40 min | 40,795 | 9,963 | 2,390,640 | 745.8 | 6,374 | 938,309,080 |
| 120, load only | 40 min | 40,795 | — | — | 1.2 | 76 retained (115 peak) | — |

**Scaling.** Heap pops grow with D, because each band has its own reward clock. Spans and decisions grow with pops × D,
so with D². Runtime, memory and report bytes grow with them: D = 12 → 120 multiplies runtime by 119 and report bytes
by 88. Doubling the window at D = 120 multiplies runtime by 2.25 and memory by 2.0. A full day is therefore at least
36 × the 40-minute run.

## 2. One ~120-band date against Clarification 2's per-date budgets

Each budget is the largest power of two within the host limit, divided by 15. Full-day figures are the 40-minute run
× 36, which is a lower bound because runtime is superlinear.

| Quantity | One full ~120-band date | Per-date budget | Over by | Can byte-identical streaming change it? |
| --- | ---: | ---: | ---: | --- |
| Runtime | ≥ 26,849 s (7.5 h) | ~546 s (8,192 s / 15) | 49 × | No: same ticks, decisions and spans |
| Report bytes | ~33.8 GB (31.5 GiB) | ~546 MiB (8 GiB / 15) | 59 × | No: same bytes; `excluded_intervals` dominate |
| Input bytes | ~625 MB (596 MiB) | ~546 MiB | 1.09 × | No: same bundles |
| Memory, current code | ~224 GiB | ~546 MiB | ~420 × | Yes, the only one |
| Memory, streamed floor (one loaded day) | ~2.7 GiB retained, ~4 GiB while loading | — | — | — |
| Engine events | ~359,000 (#166: 351,524–355,574) | 2^31 / 15 | fits | — |
| Decisions + spans | ~86 M | 2^31 / 15 ≈ 143 M | fits | — |

A whole 15-date streamed run at ~120 bands would take ≥ 112 h and write ~472 GiB of report. The rule's verdict is
"not executable on this host", with runtime, report bytes and input bytes binding. **Streaming moves memory from
binding to non-binding and leaves the verdict unchanged.**

## 3. Why the mission stopped before implementing

The mission's step 1 required byte-identical output, so the streamed pipeline would run exactly the computation
measured above. The stop rule names fitting 70% of 16 GiB for 15 dates at ~120 bands. The report-bytes host limit is
that same 70% of 16 GiB, and it binds about 42 × over the whole run. The runtime limit binds ≥ 28 ×. Re-implementing
the hashed engine and scoring path during the exam period would re-pin both the replay tree and the exporter. That
forces re-exports of the calibration days and cannot make the panel executable. So it was not started. The streaming
design is still sound if the owner shrinks the universe, or if real density proves far lower than the fixture. The
design is the incremental-consumer plan in the Clarification 4 option draft §A, plus three things this mission found:
per-pass, per-day bundle reloading, because 15 retained ~120-band days would hold ~40 GiB; spooled excluded intervals;
and a two-pass `write_report`.

At D = 12 none of this binds except memory (#168: 2,514–2,616 MiB per date). Streaming would very likely make a
D = 12 panel fit. But D = 12 is not the 88a universe (10 bands per city, 12 cities).

## 4. What decides it on production

The fixture's density is #166's reading of the exporter, not a measurement of real bundles. The density drivers are
per-band reward clocks, `TRADE_CAPTURE_GAP` spans from 30 s coverage expiries, and `excluded_intervals` per uncovered
span. Real calibration days may differ. The cheapest real measurement, in order:

1. `tools/exam_pull_cap_precheck.py` (PR #166) reads only `bundle.json`. It gives the real conditions per date and
   the candidates per heap pop.
2. If D_inst is near 120, a time-boxed rehearsal of one calibration date is unsafe on the capture host as built,
   because it has no memory guard. Run it on the workstation instead, against bundles handed over for that purpose,
   or add a memory guard first (a hashed change).

## 5. Hashed files and module hashes

**None changed.** `execution_manifest.source_hashes()` and the exporter module closure are byte-identical to `664c8943`.
The exporter module hash is unchanged, so production needs no re-pin and no calibration re-export. The ctypes leak fix in
`ceilings._windows_process_memory` (step 2) was **not** landed alone. `ceilings.py` is in both `source_hashes()` and the
exporter closure, so the fix alone would change the exporter hash and force re-pins and re-exports for no executability
gain. It belongs in whatever hashed change the owner next authorizes: hoist `Counters` and the `argtypes`/`restype`
setup to module level.

## 6. Per-file roll verdict

| File | Closures entered |
| --- | --- |
| `docs/roadmap/agent-report-2026-10-03-replay-streaming.{md,json}`, `docs/research/maker-replay-clarification-4-memory-option-draft.md`, `docs/roadmap/correspondence-index.md` | none (docs) |
| `tools/research/replay_memory/{gen_d,loadmem}.py` | none (research scripts, not under `src/`) |

Roll-free. Confirm with `scripts\ops\roll_verdict.ps1 -Branch codex/replay-streaming-20261003`.

## 7. Not done

- Steps 1, 2, 4 (as an authorizing rewrite) and the v4 binding in `authorization.py`. The option draft gains a
  measured ~120-band section instead and stays unsigned.
- No production data, credentials, `.env`, Scheduler change, merge or order.
- The 15-date ~120-band run was not measured. It is ≥ 112 h of compute and is non-executable on three other ceilings.

## 8. Reproduce

```powershell
$env:PYTHONPATH = "<this worktree>\src"
.\venv\Scripts\python.exe tools\research\replay_memory\gen_d.py <scratch>\q120 120 40 2026-09-27
'{"format":"maker_core.replay.calibration.v1","hazard_per_minute":0.01}' | Set-Content -Encoding ascii <scratch>\cal.json
.\venv\Scripts\python.exe tools\research\replay_memory\prof.py --mode multi --bundle <scratch>\q120\2026-09-27\bundle --calibration <scratch>\cal.json --out <scratch>\q120.json
.\venv\Scripts\python.exe tools\research\replay_memory\loadmem.py <scratch>\q120\2026-09-27\bundle
```

The 40-minute D = 120 run needs about 8 GB of free RAM and 13 minutes on the 32 GB workstation. Never run it on the
capture host.

Commit: see the PR head on `codex/replay-streaming-20261003`.

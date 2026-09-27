# Efficiency audit — 2026-09-27

- **Owns:** the four-dimension efficiency audit of the production host (runtime inventory, capture-loop code, storage I/O,
  language strategy), its verified findings, ranked actions and the language decision rule.
- **Read when:** changing a capture loop, Stage-A, storage formats, or proposing a language/runtime change.
- **Do not use for:** current free space (`Get-Volume`) or current state (STATE_OF_PLAY).

Method: four Fable read-only subagents on the production host during the protected window (process counters, a few
performance-counter samples, code reading; no data walks). Production verified the headline finding with its own
measurement.

## Verdict

**Do not migrate languages.** Nothing here is CPU-bound in Python; the binding resources are disk, then memory, then the
venue's cadence and rate limits. The waste is algorithmic and I/O: we recompute immutable history daily, re-read growing
files every cycle, rewrite static data every poll, and flush status on every websocket frame. Fix that in Python, adopt
native libraries where a profile says so, and keep Rust/Go only for a future latency-sensitive quoting runtime.

**Language decision rule:** move a component off Python only when (1) a saved profile shows > 30 % of that lane's wall
time or peak private bytes in pure-Python compute, (2) no native library (orjson, zstandard, pyarrow, Polars, DuckDB, numpy)
removes it, and (3) its outputs are hash-bound so byte-for-byte parity with the Python reference can be proven.

## Verified headline

- **Execution-tape worker writes ~3.7 MB/s (≈ 314 GB/day, production measurement 2026-09-27 ~14:45) for ~0.5 MB/day of tape
  per market**: `execution_tape_store.heartbeat()` persists the ~25 KB root status via atomic write on every websocket frame,
  and `append()` fsyncs per row. ~0.3-0.5 core continuously, and pointless SSD wear.

## Findings by dimension

**Runtime** (fleet ≈ 0.7 core, commit 46 %, disk the constraint at −7.6 GiB/day net): the exec-tape rewrite above;
snapshot tracker reads ≈ 470 GB/day re-parsing `replay_inputs.jsonl` and rewriting derived files each cycle; four idle
workers hold 2.9 GB private commit against 0.53 GB working set; 14 spent one-shot tasks and `WeatherMmCountabilityReport`
(paper maker retired) still registered, adding watchdog noise; `WeatherMakerEvidenceCapture` trigger refused ~1,440×/day
(IgnoreNew, PT1M); `WeatherBootRecovery` runs from a stale foreign checkout and last exited 0x3; Defender ≈ 0.8 core;
`explorer.exe` 3.6 GB working set.

**Capture-loop and Stage-A code**: ~75 of Stage-A's ~100 minutes recompute immutable settled history — hourly and
ten-minute model performance re-score every labeled folder daily (~34 min), `replay_status_backfill` parses every folder's
JSONL before its "already exists" early return (~26 min), `market_day_labels_finalize` re-finalizes all settled folders with a
Gamma request each (~22 min, ~1,000 requests/day). Snapshot capture spawns one interpreter per market per cycle; ≥ 5 full
parses of `snapshots_long.csv` per capture and one `forecasts_long.csv` read per forecast row; CLOB enrichment rewrites whole
files every 15 min; the CLOB raw loop fetches Gamma per market per minute (~17k/day); four `--ensure` tasks import the full
model stack every 1-2 minutes (~3 CPU-hours/day); 88a runs a PowerShell subprocess per cycle and fsyncs per journal row.

**Storage**: we retain ~4 GiB/day and write ~10-12 GiB/day against ~0.4-0.6 GiB/day of compressed information (~8× retained,
~20× written). Largest items: the static CLOB token map re-appended for every token on every 60 s poll (~1 GiB/day, gzips
20×); plaintext raw books tiered only at 06:00 (a 10-13 GiB daily sawtooth); duplicate `_long.csv` projections (~0.8
GiB/day); `snapshots.jsonl` embedding sidecars written elsewhere; default JSON separators (~10-15 %); Stage-A exports rewritten
whole daily. The 88a store (compact JSON, hourly gzip, hash-verified) is the pattern to copy. Target: ≤ 1 GiB/day retained,
≤ 3 GiB/day written.

**Language**: see verdict. Stage-A has never been profiled (no cProfile/pyinstrument/tracemalloc anywhere); profile first.

## Actions (owner-approved direction pending; implementation handoff 110v)

1. Exec-tape: persist status on change or every 10 s; batch fsync to once per second (durability decision: ≤ 1 s of tape at
   risk on a crash). Roll-sensitive; small.
2. Stage-A incremental: per-folder score cache (immutable settled folders), early return in `replay_status_backfill`, finalize
   and reconcile labels only for recent or unlabeled folders. Roll-free; ~75 minutes a day.
3. CLOB token map written on change, not per poll; Gamma event cache (~10 min TTL). Roll-sensitive; ~1 GiB/day.
4. Snapshot capture: tail reads instead of full parses, a hash sidecar for forecast archive checks, one child per cycle for
   all due markets. Roll-sensitive.
5. Thin `--ensure` entry module (lazy imports). Roll-free as a new module.
6. Raw book tape gzip-streamed at write (hourly parts like 88a); compact JSON separators at a UTC day boundary; de-embed
   `snapshots.jsonl`. Roll-sensitive; prospective only.
7. Ops (production, owner-approved): unregister spent one-shot tasks and `WeatherMmCountabilityReport`; repoint
   `WeatherBootRecovery`; `WeatherMakerEvidenceCapture` to an ensure pattern or PT5M; restart `explorer.exe` at night;
   Defender exclusions for `venv\` and worktree roots.
8. Profile Stage-A once (pyinstrument + tracemalloc per step) and record per-step wall time and peak private bytes.

Evidence rules unchanged: nothing canonical is deleted; format changes are prospective; roll-sensitive changes land in quiet
windows, and during the replay exam (panel 2026-09-30..10-13) only by exception.

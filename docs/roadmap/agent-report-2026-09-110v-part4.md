# Agent report 2026-09-110v Part 4 — snapshot read efficiency

**Verdict: PASS on fixtures; adoption after 2026-10-13 only.** Tail reads
and persistent hash/first-seen indexes preserve the original output. The
requested single-child design was evaluated and rejected for adoption because
it conflicts with required per-market fault isolation; memory limits remain.

Branch `codex/snapshot-incremental-reads-20260927`, authorized integration
base `e3bc4dc88a785e989258ac9e24b286879568d8d1`.
Mission: [110v handoff](workstation-handoff-2026-09-110v-efficiency-fixes.md).

## Change and measurement

- Latest snapshot time: 64 KiB suffix first; full-reader fallback retains
  scheduled-cadence and legacy multiline/malformed/triggered-only semantics.
- Forecast last-hash and manifest first-seen: small stat-bound, checksummed,
  atomic JSON indexes. Cold/stale/corrupt cache rebuilds; normal appends update
  indexes after evidence writes. Candidate first-seen values never become
  authoritative before their manifest row exists.
- Forecast schema migration checks the header before materializing rows.
  Forecast and snapshot derived files already append in the selected base;
  their append behavior is retained. Schema upgrades remain explicit rewrites.
- No reader schema, captured-input hash, feature parity, release binding or
  WU cutoff change. No production evidence was read.

Synthetic fixture: 10,000 rows each of snapshot CSV, forecast CSV and manifest,
five repeated checks per measurement, same result under full and warm paths.
Measurements include logical bytes returned to parsers (including the cache),
not Windows physical disk I/O or production performance.

| Per cycle | Full reference | Warm indexes/tail |
| --- | ---: | ---: |
| Logical bytes read | 4,790,516 | 66,239 |
| Wall seconds | 0.05162 | 0.00261 |
| CPU seconds | 0.053125 | Below Windows process-time timer resolution (reported 0) |

Logical reads fell **98.6%** on this fixture. Cold recovery still scans
evidence; the cache is bounded to 16 MiB and is always disposable.

## One child per fleet cycle evaluation

Under the unchanged 1,792 MiB child cap, import-only subprocess fixtures:
three children took 2.324 seconds wall / 1.953 CPU; one took 0.767 wall /
0.563 CPU. These measure imports only, not market capture throughput.

A single child can catch ordinary Python exceptions, but cannot preserve
per-market containment after a hung native call or process memory kill.
`test_snapshot_capture_batch.py` retains the slow-market isolation, explicit
deadline results and resource-limit contracts. The scoped collection
`AGENTS.md` requires bounded isolated children and per-market failure
isolation. Therefore the current two-worker bounded fleet stays intact;
no unproved process reuse was enabled merely to save imports.

## Verification and rollout

Wrapper-admitted owner suite plus all seven repo-wide audits: **185 passed**.
After adding the isolated import evaluation: focused fixture plus every
repo-wide audit **83 passed**. Repo-wide compileall passed.
Owner coverage includes forecast archive/payload persistence, collection
robustness, captured-input hash, latest market inputs and capture batch.

Authoritative local roll verdict: **UNDECIDABLE**, all four live closure
files absent. Per-file prospective classification:

| Files | Classification |
| --- | --- |
| `src/weather/collection/snapshot_read_index.py` | Roll-sensitive capture dependency |
| `src/weather/collection/snapshot_store.py` | Roll-sensitive capture code |
| `src/weather/collection/forecast_archive.py` | Roll-sensitive capture dependency |
| `tests/collection/test_snapshot_incremental_reads.py` | Test-only |
| Operations design, this report, correspondence index | Roll-free documentation |

Production must rerun `roll_verdict.ps1`, integrate against landed master,
and adopt after October 13 under the exam policy. No scheduling, exchange,
credentials, production-data operations, or deployment were performed.

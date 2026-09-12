# 332. Bounded Settlement-Source Audit [PARTIAL 2026-09-12 - WORKSTATION QUALIFIED; PRODUCTION QUALIFICATION OPEN]

Goal: complete settlement-source auditing within the existing daily-chain
resource gates while preserving selected revisions, summaries, lineage meaning,
and truth-label decisions. This implements the approved R3 reliability increment.

Owner/package: `weather.reporting.source_gates`, with existing daily and trading
consumer entrypoints. The durable contract is
[settlement-source audit](../../operations/settlement-source-audit.md).

Source: the operator's September 12 approval of the R3 reliability increment;
canonical master `f3814173775335adb546b7201a2e73ecec7703bf` and retained baseline
plus workstation qualification evidence.

Why this matters: retained revision histories must not exceed the daily audit's
memory budget or prevent later settled-day analysis steps from running.

Acceptance: preserve legacy semantics, qualify the complete bounded path against
its memory target, and obtain separate current-production execution proof.

## Implementation

- [x] Stream histories into a fresh disk-backed revision index; preserve
  encounter-order whole-row selection and nonempty label overlay.
- [x] Stream complete canonical output and provide bounded requested-date readers.
- [x] Release the first index before a daily reconciliation retry rebuilds it.
- [x] Preserve previous authoritative output on failed or interrupted writes.
- [x] Reuse hashes only for explicitly sealed, content-verified offline inputs.
- [x] Prove frozen semantics, growth bounds and historical-corpus memory.
- [ ] Qualify current production inputs and actual lineage hashing workload.
- [ ] Complete publication/review and guarded adoption, then verify an admitted
  daily-chain execution and resource receipt.

The implementation is isolated on `codex/bounded-settlement-audit-20260912`.
The first implementation is `663a7af13eb23ea24fe3c3ed1d03bc204c599ea9`; subsequent
qualification changes extend tests and documentation. No production source
adoption, Scheduler change, historical ledger repair, capture restart,
promotion, or live trading has been performed by this increment.

## September 12 workstation qualification

All verification used the assigned non-capture workstation and its unchanged
`workstation_heavy.ps1` admission, shared mutex and Job containment. Runtime
source/test hashes matched the local implementation before execution.

The 18-event frozen fixture was produced by the old implementation before the
builder changed. It covers revisions, label overlay, status families, both
native units, lineage, summaries and target-date gates.

- 51 focused Windows tests passed, including process termination during a
  partial JSON write, sealed same-size/same-mtime mutation and daily retry.
- The broader owner suite had 211 passes and one Git-tracking setup failure:
  newly copied files were untracked in the workstation replica. Registering
  those exact files in its index made the failed check pass. No production
  code or gate was changed to resolve it. The 212 owner checks include 17 subtests.
- Both scaling regressions passed. With 256 events and 2,048 versus 16,384
  historical rows, traced Python peaks were 402,600 and 354,023 bytes. The
  legacy peaks were 5,353,373 and 42,368,683 bytes with the same semantic digest.
- Increasing selected events from 2,048 to 16,384 grew JSON from 6,487,321 to
  51,895,824 bytes while traced peaks stayed at 510,500 and 561,443 bytes.
  The complete build, gate, write and file-reader path was included.

## Historical corpus and limits

A fresh sealed copy of the workstation's August 12 frozen history contained
251,456,622 input bytes, 18,844 input rows and 813 selected events across
12 markets and 76 target dates, May 27 through August 11. Each profile ran in
a fresh process with the daily-child imports loaded. The legacy module's bytes
matched Git blob `c2d0a0a3e7e2e65b0d41bb317bf87410618ba8d1` exactly.

| Path | Native process lifetime peak commit | Elapsed seconds | Index bytes |
| --- | ---: | ---: | ---: |
| Legacy | 2,477,072,384 | 1.857 | 0 |
| Bounded, ordinary uncached lineage | 1,724,649,472 | 2.483 | 18,415,616 |
| Bounded, explicit sealed identities | 1,726,722,048 | 2.827 | 18,415,616 |

Both bounded paths passed the 2 GiB limit. All JSON values, Markdown text and
date gates matched the legacy result. The existing global BLOCK remained BLOCK.
Semantic digest:
`7f798926087d947b531683fc3089a5a4706415aca1992428395c1d21c2306f6d`.

This is historical qualification, not a current-production corpus result or a
throughput claim. SQLite increased writes and elapsed time in this sample.
All 4,065 lineage entries in this frozen-path layout retained missing-with-reason
status, so it does not qualify production raw-lineage I/O or demonstrate hash
cache speedup. Separate deterministic tests verify sealed reuse and invalidation.
No missing source, label or capture gap was upgraded.

Retained controller evidence is under ignored
`scratch/handoffs/audit-qualified-20260912/`: full compared outputs, source-bound
metrics, qualification receipts, input seal inventory, synthetic measurements
and eight JUnit files including the initial setup failure. A separate bounded
verification of the downloaded artifacts reproduced parity, content hashes and
memory acceptance in `verified.json`. The corpus remains on the workstation;
only reports and its small inventory were returned.

The seal inventory digest is
`3d7027c4cc3dae80a0f2d10e9aeb7d8e9f8439bbdb83c85d480848b4d1e99d07`.
Reproduction sources are retained in controller
`scratch/handoffs/audit-corpus-qualification-20260912/` and workstation
`C:/Users/Michael/Documents/github/weather-audit-20260912/scratch/qualification/`.
Use a fresh attempt namespace; existing inputs, outputs and receipts are frozen.
The hosted qualification workflow runs the full Linux suite and native Windows
affected-owner suite and retains exact tested-commit/environment/JUnit evidence.

## Adoption boundary

The repository-owned verdict for `663a7af13` is ROLL-SENSITIVE:
`src/weather/io.py` enters snapshot, CLOB, observation-trigger and public
execution-tape closures. The other six changed importable files are roll-free.
Receipt: `scratch/handoffs/audit-roll-663a7af13-20260912.json`.
Refresh that verdict for the final reviewed tip and use guarded quiet-window
adoption. Source tests and historical memory acceptance do not prove a successful
scheduled daily chain on current production data.

# Counterfactual fill-tape export: draft night job

This is for master-agent to slot into a night. The folder is a placeholder; move it to `night-plans/<date>/` once
a night is chosen.

## What it does

`cftape_host_run.ps1` runs `weather.market.maker_counterfactual_tape export` on the capture host.

- **Input:** the 88a store (`data\maker_evidence`).
- **Output:** a zstd Parquet tape with receipts. Build 2 (item 330, `toxicity.read_records`) fits from this tape
  once the `to-jsonl` adapter has converted it on the workstation.

The wrapper is cloned from the FC-11 r3 wrapper (`night-plans/2026-10-19/fc11_host_run.ps1`). It keeps the same
lease, kill-on-close child tree, hard stop, tree-memory sampler, StrictMode handling and exit codes.

**Prerequisite:** branch `claude/cf-tape-export-20261016` (tip `f1ff9f139`) must be merged on the host.

- The new module, tests and docs are roll-free: nothing in a capture loop imports them.
- One edit touches a `.ps1` file and the Codex hook allowlist (`scripts/ops/workload_admission.ps1`).
- Run `roll_verdict.ps1 -Branch claude/cf-tape-export-20261016` as usual.
- The wrapper exits 5 if the module is missing.

## Slot

- **Slot:** host load policy 4f, 03:50–04:45, the same slot as FC-11.
- **Start:** between 03:50 and 04:00. If the lease is busy, the wrapper retries every 15 s until 04:00:59.
- **Stops:** no new day starts after 04:30. The child tree is hard-killed at 04:45.
- **Do not schedule it on an FC-11 night (2026-10-19).** Both wrappers want the slot, and the second one would
  exit 4.

## Expected runtime and IO (estimates, not measured on the host)

- **Input:** 88a UTC days dated on or before 2026-09-29. Per EF §10r, that is roughly 5 days (09-25..09-29) at
  about 62 MB gz per day, about 311 MB in total. Whether capture actually starts on 09-25 or 09-27 is an open
  question; the dry run answers it.
- **Speed:** each day is read once, streaming, with gzip decode. Estimate 1–3 min per day, so `-MaxDays 5` should
  finish in one night, or two at worst. The exporter is resumable, so a short night only defers days.
- **Output:** small. Estimate about 10% of the input bytes as Parquet, but this coefficient is unmeasured. The
  first night's `output_bytes` measures it.
- **Memory:** one day's in-scope book bodies are held in memory. The working set is expected to stay well below the
  1 GiB tree cap; the cap kills the run with exit 7.

## Commands (on the host, from the night-plan copy)

Dry run (stat only; safe at any hour). It lists day folders by name, then segments and file sizes, reports
done/mismatch per day, and opens no file:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File cftape_host_run.ps1 -RepoRoot C:\Users\Michael\Documents\github\weather -DryRun
```

First night: run one day to measure. Then raise `-MaxDays` (for example to 5) on later nights.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File cftape_host_run.ps1 -RepoRoot C:\Users\Michael\Documents\github\weather -MaxDays 1
```

Optional parameters:

- `-OutRoot` (default `C:\cftape-out`);
- `-EvidenceRoot` (default `<RepoRoot>\data\maker_evidence`);
- `-MinDate`;
- `-FillRule at_price|strictly_through` (default `at_price`);
- `-TreeCapBytes`.

`--max-date 2026-09-29` is fixed in the wrapper. Folders dated 2026-09-30..2026-10-15 are never listed or opened.

## Receipts

All output is under `C:\cftape-out` (outside `data\`). Every file is create-only.

| Path | Contents |
| --- | --- |
| `backlog\tape\utc_day=<D>\cf_minutes.parquet`, `cf_fills.parquet` | The tape (zstd). |
| `backlog\receipts\<D>.json` | Sealed day: row counts, input segments and journals, a sha256 for each output, the code commit, the match checks. |
| `backlog\receipts\<D>.mismatch-<stamp>.json` | A day that did not match its manifests. It is not sealed and is retried later. |
| `backlog\run_receipt_<stamp>.json` | Exporter run: input day list, days extracted and remaining, all_match, stopped_reason. |
| `runs\cftape-<stamp>-<hex>\wrapper_receipt.json` | Wrapper: exit code, lease, teardown proof, peak tree working set, summed minutes and fills, each day receipt's sha256, child log sha256s. |

Exit codes: 0 ok, 1 mismatch, 2 refused, 3 hard stop, 4 not admitted, 5 preflight, 6 teardown or fault,
7 memory stop.

## Rollback

Delete `C:\cftape-out`. The 88a store is only read, through share-read/write/delete opens with no locks, so there
is nothing else to undo.

## After the host run

Copy `C:\cftape-out\backlog` to the workstation. Then convert one maker side per file:

```powershell
python -m weather.market.maker_counterfactual_tape to-jsonl --tape-dir <backlog> --output <file>.jsonl --maker-side YES|NO [--settlement-json <file>]
```

The adapter verifies every table's sha256 against its receipt before it writes anything.

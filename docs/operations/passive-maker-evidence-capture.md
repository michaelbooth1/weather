# Passive maker evidence capture

Status: implementation contract; registration is a separate production action.
Owns: the independent public maker-evidence collector, its status, selection,
storage and scheduled task. Read when operating or interpreting this evidence.
For disk thresholds read [the storage plan](storage-plan-2026-09-23.md); for
live sessions use the [live pilot](INTERNATIONAL_MM_LIVE_PILOT.md).

`weather.market.maker_evidence_capture` uses public International Gamma events,
CLOB books and per-condition rewards, and the public market WebSocket. It has
no authenticated route, credential reader, dotenv, SDK or order-module import.
The sole HTTP POST is the public batch book read. Redirects, ambient proxies,
netrc authentication and response bodies over the byte limit are refused.
HTTP calls are sequential with per-request and per-cycle deadlines and at most
one retry for a transient connection/timeout failure; book and
event reads are batched. A failed cycle is explicit and is retried next minute.

## Universe and timing

Each minute, discover each configured city's local dates T+0, T+1, T+2 from
the canonical registry. Gamma's current `clobRewards` and reward terms establish
eligibility; rank captured YES books with the canonical
`reward_share_estimate.evaluate_sample`: 20 shares per side, one cent outward,
size-cutoff midpoint, `share_many` times the active daily rate. This is modelled
selection, never evidence of earned income. A 100-share minimum gives a 20-share
score of zero but remains a reward-eligible candidate.

Select ten per city, reserving its best three per day-ahead first and filling
the remaining slot by score (condition ID breaks ties). If fewer than three
exist in a day, record the shortage; never fabricate coverage. Capture both
tokens together and the full `/rewards/markets/<condition>` record for every
selected condition. The full CLOB record is retained separately from Gamma's
ranking terms so discrepancies are visible. Exact repeated pagination rows
are dropped and logged; conflicting rows or repeated cursors refuse the cycle.

`--extra-conditions` names an optional, bounded JSON file:

```json
{"extra_conditions": ["0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"], "update_windows_utc": [{"start": "2026-09-24T00:00:00Z", "end": "2026-09-24T00:30:00Z"}]}
```

The production agent publishes that file atomically with the session band and
two controls and explicit UTC windows for the 30 minutes before and after the
session. Up to two non-overlapping windows are allowed, each at most 1,800 seconds.
Raw updates are off without a currently active window and subscribe only to these
conditions. The socket enforces the end time even during an HTTP cycle;
configuration is reconciled between cycles. Extra conditions are
added regardless of rank or reward eligibility. This worker does not inspect
session worktrees or campaign roots.

The existing pinned `websocket-client` transport uses at most 100 tokens per
connection and bounded message
sizes. The hard daily cap defaults to 300,000,000 uncompressed response bytes,
shared by all connections and surviving restart. A frame that would exceed it
is rejected whole, a cap event is journaled, and update sockets close until the
next UTC day. Separate public trade connections continue at the existing
execution tape's event-driven cadence, with ten-second application heartbeats.
They retain only explicit `last_trade_price` replies and record disconnects and
gaps. They cover the entire selected universe because this worker does not
assume another tape's current subscriptions. Overlapping public trades must be
deduplicated by an analysis consumer; no own-account fill or backfill is claimed.

## Storage and brakes

Default root: `data/maker_evidence`. Schema `maker_evidence_v2` stores journals
inside `<UTC-day>/<UTC-hour>-<segment-id>/`. Each sealed segment has one
`manifest.json` with one entry per file: SHA-256, byte count, record count and
last offset. Each response record carries its own time, raw SHA-256/byte count,
logical offset and payload reference. Exact UTF-8 bodies are stored as strings;
non-UTF-8 replies fall back to base64. Status is an atomic operator cache.

Subscription lists and discovery projections are stored only on content change.
Unchanged rewards/projections reference the prior equal canonical body; key order
or whitespace may differ from the received bytes, whose original hash is retained.
Every new segment writes a fresh body baseline so its references are self-contained.
Lifecycle records reference subscription lists instead of repeating them.
Changed lists share one journal so compression can reuse their common token IDs;
references retain the exact list hash and record offset.

Book replies are split losslessly into per-token journals, with a batch record
retaining the original delimiters and offsets. Reassembly reproduces the exact
wire SHA-256; token grouping lets hourly gzip reuse prior snapshots rather
than repeatedly compress unrelated books. Ranking and selected books share
these token journals without dropping either capture.
Updates and reward bodies are grouped by condition, and universe selections
by city, for the same reason. The daily byte cap remains global across every
update journal. Universe rows reference full reward-record content hashes and
retain the scalar ranking terms instead of duplicating whole reward replies.

Gamma discovery stores a change-only **selection projection**: event ID/slug,
condition/token/outcome identities, active/closed/order-book flags and all
published reward configurations/limits. Unrelated descriptions, volumes and
analytics are omitted. Every received reply still has its original response
SHA-256/byte count inline, alongside the projection's independent
stored/content hashes and an explicit representation tag. The original full
Gamma response cannot be reconstructed; every input actually used for universe
selection is retained. This distinction is reported by the inspector.

The writer holds a kernel lock. A torn journal refuses restart without rewriting
evidence. Journals rotate at UTC hour boundaries, or earlier at 100 MB per segment.
A bounded background worker compresses sealed segments while leaving the writer
lock free, verifies the complete decompressed SHA-256, then removes its own plain
representation. Compression is also attempted after failed HTTP cycles and during
clean shutdown. Logical offsets refer to the decompressed file. Nothing expires.

Writes stop before the total uncompressed journal/manifest working set reaches
500,000,000 bytes, reserving space for sealing metadata. Status reports current
and measured peak raw bytes; reaching the bound fails visibly rather than
silently reducing capture. Verified compression runs in Green, Amber and Red;
Critical stops capture. Compression delay cannot bypass the raw limit.

The v2 writer refuses a legacy v1 root. Preserve legacy evidence and inspect it
using its original bound reader; start v2 in a new root. There is no implicit
migration or deletion.

These journals are `canonical_evidence` in
[the storage-class contract](data-storage-class-contract.md), with the same
reviewed archive/reclaim gate as other original public evidence.

Before each cycle the worker checks actual free space on its output volume.
Red (< 60 GiB) stops the raw update channel; Critical (< 40 GiB, owner 2026-09-25: below the bounded suite's 50 GiB
floor so capture outlives nights when a suite cannot run) stops all capture and writes status.
Windows process priority is IDLE (Scheduler
priority 10); buffers, reply sizes and universe size are bounded. The worker is
independent of snapshot/CLOB supervisors and never calls them.

## Commands and registration

From an integrated checkout with the pinned dependencies installed:

```powershell
.\venv\Scripts\python.exe -m weather.market.maker_evidence_capture --help
.\venv\Scripts\python.exe -m weather.market.maker_evidence_capture --dry-run --duration-seconds 1800 --root C:\scratch\maker-evidence-new-run
.\scripts\ops\register_maker_evidence_capture.ps1 -WhatIf
```

The dry run requires a new scratch root, rejects an active RE-1 preflight/live
process without opening its files, and reserves one minute for teardown before
19:45 America/Toronto. The process guard is checked each cycle. It writes the
same evidence as production, using public reads only.

After it stops, the bounded offline inspector verifies every manifest payload
reference/hash and reports per-minute bytes, request latency aggregates, exact
gzip-6 encoding size and explicitly labelled daily extrapolations. Set `--day`
to the captured UTC day. It reads at most 20,000 journals / 1 GiB of decompressed
data and changes no evidence (at most 16 open readers). It reports gzip bytes and
daily projections by family, a stream-off projection against the 150 MB/day target,
and incremental update bytes per 30-minute active window. These are observed-window
extrapolations, not a full-day guarantee. Perform this scratch verification on the workstation; broader
production-day inspection remains subject to the host load policy.

Run the offline compression/integrity inspection through the workstation heavy
wrapper, which keeps the existing host/principal and shared-lease checks:

```powershell
$inspectArgs = @('-m', 'weather.market.maker_evidence_inspect', '--root', 'C:\scratch\maker-evidence-new-run', '--day', '2026-09-23')
$inspectEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -Compress -InputObject $inspectArgs)))
.\scripts\ops\workstation_heavy.ps1 -Kind weather_heavy -PythonPath "$PWD\venv\Scripts\python.exe" -ArgumentsBase64 $inspectEncoded -RepoRoot $PWD.Path
```

Only the offline inspector is added to that module allowlist; the network
capture command is not admitted as an offline workload.

Only the production operator runs the registrar without `-WhatIf`, after
integration qualification and dependency verification. `WeatherMakerEvidenceCapture`
uses current-user S4U/Limited, IgnoreNew and a retry trigger; one
long-running Python worker owns the lock. The **intended** retry interval is
five minutes (`PT5M`, owner-approved efficiency audit 2026-09-27 in the
[decision log](DECISION_LOG.md)): with the worker holding the lock, a one-minute
trigger only produced about 1,440 refused starts a day. The host runs PT5M. The
registrar still writes `PT1M`, so re-running it unchanged would revert the
interval; aligning the registrar is an open owner question held behind the 88a
freeze (Swarm P audit F2, 2026-10-07).

> **DO NOT RUN `register_maker_evidence_capture.ps1` until the owner answers the PT5M question.**
> It writes **PT1M** and would silently undo the live, intended **PT5M**. This applies to the DST
> re-registration pass too: the task's repeating trigger needs no DST action.
 A Critical disk stop remains visible
and subsequent triggers keep refusing capture until disk recovers. The worker
never stops another process. `scripts/ops/status.ps1` reads `status.json`, flags
missing/stale/non-capturing state when armed and displays band count/disk/cap.
After changing this worker, the production operator must explicitly re-adopt
its task; it has no effect on the existing supervisors' adoption behavior.

The central schema registration is additive. Its shared-registry placement
means deployment must use the repository roll-verdict tool; independence of
the worker does not itself prove the entire branch roll-free.

## Counterfactual fill tape (item 330 build 2 input)

`weather.market.maker_counterfactual_tape` is an offline, read-only reader of
sealed 88a days. It writes the COUNTERFACTUAL quote-minute and fill tape that
the item 330 build 2 toxicity fit (`maker_core.replay.toxicity`) consumes. It
is not imported by the capture worker, so it is roll-free. It is on the
workstation-heavy offline allowlist. On the capture host it runs only as the
night job `cftape_host_run.ps1` (claude/night-plans), under the shared lease,
with the same slot, caps and exit codes as FC-11.

```powershell
python -m weather.market.maker_counterfactual_tape export --root <88a root> --out-dir C:\cftape-out\backlog-strictly_through --fill-rule strictly_through --dry-run
python -m weather.market.maker_counterfactual_tape export --root <88a root> --out-dir C:\cftape-out\backlog-strictly_through --fill-rule strictly_through --max-days 1 --deadline <iso> --code-commit <head>
python -m weather.market.maker_counterfactual_tape to-jsonl --tape-dir C:\cftape-out\backlog-strictly_through --maker-side YES --output <new file>.jsonl [--settlement-json <file>]
```

**Fill rule per run.** Each run uses one `--fill-rule` (default `at_price`),
recorded in every receipt. A backlog holds one rule: `export` refuses (exit 2)
an `--out-dir` that already holds day receipts of the other rule. The host
wrapper writes `backlog-<rule>`, so the two rules are two runs. Build 2's
default fit uses `strictly_through` (print < bid); `at_price` (print ≤ bid) is
its declared sensitivity. `print_side` is the print's recorded aggressor (taker)
side, kept as is; a resting BUY is hit by an aggressor SELL.

**Embargo and reads**
- Only dates on or before 2026-09-29 are read. A day folder's date comes from
  its name. Folders dated 2026-09-30..2026-10-15, or after `--max-date`, are
  never listed, stat'ed or opened. A `--max-date` after 09-29 is refused
  (exit 2).
- Inside an allowed day, a universe band whose event date (from its slug) is
  after 09-29 is dropped before any of its `book-<asset>` journals is opened.
  Its prints are parsed and discarded. Both are counted in the day receipt.
- Inputs are opened read-only with share read/write/delete.
  `.writer.lock` and `status.json` are never opened, and no lock is taken.
- An unsealed segment is listed and counted, never read.
- Every journal is checked against its manifest: decompressed bytes and SHA-256.
- A damaged segment (unreadable file, bad or truncated gzip, manifest
  mismatch) fails only its own day: that day gets a mismatch receipt and stays
  unsealed, and the run continues.

**Output**
- Output goes under an `--out-dir` outside `data\` and outside the 88a root:
  - `tape/utc_day=<D>/cf_minutes.parquet` and `cf_fills.parquet`, zstd;
  - `receipts/<D>.json`, which records input segments with manifest SHA-256,
    dispositions, row counts, the SHA-256 and bytes of each output, module
    SHA-256 and commit;
  - `run_receipt_<stamp>.json`.
- Files are create-only. A day without a receipt is an interrupted attempt; its
  leftover tables are renamed `*.orphan-<stamp>`.
- Only a day whose checks all match is sealed. A mismatch writes
  `receipts/<D>.mismatch-<stamp>.json` and is redone after the
  never-attempted days.
- `--dry-run` lists folders and reads directory-entry sizes only. Its output
  estimate is an unmeasured placeholder.
- Rollback: delete the output folder. Nothing else is written.

**Record semantics.** The tape is per UTC day. It never reads a neighbouring
day, so a minute that would start after midnight, and a mark due after
midnight, are omitted and counted. A token's 88a book snapshot captured at `c`
opens the exposure minute `ceil_minute(c)`.

| Field | Semantics |
| --- | --- |
| `cf_minutes` row | One per token and minute. It is a hypothetical resting BUY of 20 shares at that token's best bid. The first snapshot in a minute wins. A row needs `0 < bid < 1`. Its context is taken at `c`. |
| `cf_fills` row | The first `last_trade_price` print on the token in `[minute, minute + 60 s)` that crosses the bid under the run's rule (`maker_core.shadow.paper.crosses`): `at_price` print ≤ bid, `strictly_through` print < bid. `size = min(print size, 20)`, and `crossing_prints_in_minute` counts every crossing print. Prints repeated by overlapping connections count once. |
| Context | Trailing only, as in build 2's `toxicity_features.weather_fill_context`. Imbalance and depth come from the latest YES book no more than 120 s old, summing all levels. `last_print_size`, `burst_prints` (1 s) and `sweep_bands` (60 s, distinct conditions of the event in the 88a universe) come from prints strictly before the instant, as build 2's `FillContext` requires (4ae3602fa): the fill's own print, and any print at or after the fill instant, are excluded. A fill's book is also strictly before the fill; a minute's book is its quote snapshot at the context instant. `horizon_days` is the event date minus the market-local date. Close is the end of the local event day. |
| Weather fields | Scheduled print, model cycle and decided probability are null. `station` lets a workstation step add the scheduled-print clock. |
| Marks | Marks `1m`, `5m` and `30m` are the first two-sided YES snapshot in `[fill + h, fill + h + 120 s]`, at mid. |
| `settlement_p_yes` | Null in the tape. `to-jsonl --settlement-json` supplies `{condition_id: {"p_yes", "observed_at_utc"}}`; build 2 requires the observation time, dates it against the embargo, and refuses one before the fill, so a settlement read on 09-30 or later cannot enter the fit. The adapter withholds the settlement label (the fill is kept with `settlement_p_yes` null, so the exposure-minute hazard is unbiased) when none is given, when it was observed before the fill, or when it was observed on or after 09-30, and counts each reason in the create-only `<output>.receipt.json` (`fills_settlement_withheld`, `fills_with_settlement`). |

**Build 2 mapping.** `to-jsonl` writes build 2's neutral records:

- columns `ctx_*` map to `context.*`, and `ctx_ft_*` map to
  `context.feature_times`;
- `mark_<h>_*` map to `marks`;
- `quote_price` maps to fill `price`, on the maker token's axis.

Build 2 keys exposure minutes by `(condition_id, minute_utc)`, so one JSONL
file holds one `--maker-side`. The tape keeps both sides. Before a table is
read, the adapter checks its SHA-256 against the day receipt. Any record date
after 09-29 is refused.

## Update when

Update with selection, endpoints, timing, CLI, byte/disk brakes, storage,
registration or status changes. Verify with the focused maker-evidence tests,
import architecture, storage/schema tests and the required timed scratch run.

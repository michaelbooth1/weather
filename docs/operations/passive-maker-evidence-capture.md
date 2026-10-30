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
tokens together. The full `/rewards/markets/<condition>` record of a selected
condition is read every cycle for built-ins through the 88a hold and on change otherwise
(data layer v2 S9, below), separately from Gamma's
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
assume another tape's current subscriptions. Trades that overlap another tape's
capture must be deduplicated by an analysis consumer; no own-account fill or
backfill is claimed.

A trade-channel token-set swap (about once a minute) is make-before-break. The new
sockets connect and subscribe while the old ones stay open. The old ones close once
every new socket has received its first data frame (the venue's book snapshot), and
never more than 5 s (`SWAP_OVERLAP_SECONDS`) after the swap began; they then stop
within the existing 8 s stop bound. At most two generations of sockets are open at
once. A trade seen on both sockets is journaled once. The venue's `last_trade_price`
has no trade id, so the identity is the execution tape's trade fingerprint fields
(asset, market, price, side, size, fee rate, timestamp, transaction hash). A socket's
n-th sighting of an identity is journaled only when no other socket has already seen
it n times, so genuine identical trades on one socket are kept. A frame that is
entirely repeats is not journaled; a mixed frame keeps its exact bytes with
`duplicate_trades: <n>` on its row. Dedupe memory holds at most 16,384 identities
for at most 120 s (about 4 MB). The raw update channel stays break-before-make,
since its frames have no identity to dedupe. Every token-set change and every stop
journals a `stream_tokens` row (`channel`, token count, and references to the
wanted subscriptions; an empty list means nothing is wanted). The inspector checks
those references like the lifecycle ones.

Each socket thread only reads, sends `PING` and stamps receipt time; a per-session
writer thread journals the session's rows in arrival order from a queue bounded at
4,096 frames and 64 MiB (the reader blocks only that far behind and never drops a frame), so an
fsync or the store lock cannot stop the socket being drained and pinged. Stream,
trade and lifecycle rows carry the reader's receipt time in `captured_at_utc`; the
segment still rolls on the write clock. Frames received before a drop are journaled
before the `disconnected` lifecycle row and the `stream_gap` row, both stamped when
reading stopped. The 30-second inbound-silence deadline is judged only after a
receive has just timed out. A venue close frame raises `VenueCloseError` and its
gap text carries `code=<n> reason=<text>`; an empty data frame is liveness, not a
close. Reconnects wait a jittered delay in [d/2, d], doubling from 2 s to 30 s after
failures; a session that stayed connected for 60 s resets it to the base.

## Reward records by change trigger (S9)

Selection never used the per-condition CLOB reward reply (ranking uses Gamma's
terms), yet reading it for every selected band each minute was about 83% of the
recorder's public REST. `weather.market.maker_evidence_rewards` replaces that read for
pilot bands now and for built-in bands only after the 88a panel hold:

- **Built-ins stay legacy through the hold.** Built-in bands keep the pre-S9
  every-minute read of every selected band's record (`read_every_cycle`; same request
  order, change keys and universe row shape) unless `built_in_reward_cadence` is
  `event_driven` **and** the time is at or after UTC 2026-10-31T00:00Z
  (`BUILT_IN_LEGACY_UNTIL`). Before that the setting is ignored, except in a scratch dry
  run. `status.json` `rewards.built_in_cadence` says which cadence ran.

- **Sweep (VR-4).** One paged pass over `/rewards/markets/current` (GET, allowlisted,
  `next_cursor` until `LTE=`, `-1` or empty) at most every 15 minutes, a few pages per
  cycle. Each page is journaled as a bounded projection (cursor, row count, hash of its
  canonical rows); the documented sweep fields of selected bands are journaled
  change-only (`rewards_current`, a full baseline each segment); a `rewards_sweep`
  event closes each pass with the changed and removed ids. A sweep error is journaled
  and counted, never fails a cycle, and retries after 15 minutes.
- **Trigger.** A selected band's full record is read when it is first selected, when
  its Gamma terms change, when its sweep row changes, every 15 minutes while the sweep
  is stale (30 min) or off, and at the latest hourly. Reads are capped at 20 per cycle,
  ordered by lane (built-ins first), reason, then age. Universe rows carry
  `clob_reward_content_sha256`, `clob_reward_age_seconds` and `clob_reward_reason`.
- **Kill switch.** `core_recorder_only.rewards_sweep` in `config/capture_families.json`
  is `on` or `off` (lands `off`), reloaded each cycle; off falls back to the
  stale-recheck cadence.

`REQUEST_BUDGET_PER_HOUR` (0.4 req/s) is the plan's acceptance bound for the
event-driven cadence. The registry's `request_budget` stays `not_declared` while built-ins
run the legacy cadence (about 2 req/s, mostly reward reads); declare it when
`built_in_reward_cadence` flips.

## Recorder-only pilot (S2 P1)

`config/capture_families.json` block `core_recorder_only` lists at most ten
**recorder-only** markets the core process records alongside the built-ins: a
non-built-in id and location, a `highest` series slug prefix, an IANA zone,
day-aheads 0-2 and band policy `top10_reward_ranked`. The loader refuses built-in ids,
locations or slug prefixes, family prefixes, duplicates and unknown fields; a bad block
is journaled once (`recorder_only_config_error`) and the pilot stays off
(`CONFIG_ERROR`) while the built-in cycle is unchanged. The shipped rows are R1 (the P1
cities London, Shanghai, Paris, Seoul and Tokyo) and R2 (Munich, Madrid, Beijing,
Wellington and Hong Kong, id `hong_kong`).

**It lands disabled** (`pilot: "off"`, `rewards_sweep: "off"`,
`built_in_reward_cadence: "legacy"`): the rows are validated every cycle but nothing is
captured, so landing changes no built-in record. Switching on after the post-landing
verification is a config-only change landed through the roll-free path: set `pilot` and
`rewards_sweep` to `on`; the running recorder re-reads the block on its next cycle (no
restart). Flip `built_in_reward_cadence` to `event_driven` only after UTC 10-30; it has
no effect before 2026-10-31T00:00Z.

**R1+R2 on.** Per the owner's 2026-10-23 phase-2 plan (`DECISION_LOG.md` lines 258/259,
day-1 receipt allowance at line 265) the shipped block sets `pilot: "on"` for all ten
rows; `rewards_sweep` stays `off` and `built_in_reward_cadence` stays `legacy`. Ten rows
mean 100 pilot bands and 200 trade tokens, so the `pilot_trades` channel runs two sockets
of at most 100 tokens. The S2+S9 receipts are measured after the flip.

The pilot shares the core process (owner Q1 via master, 10-15). A failed pilot cycle or
a failed or closed pilot trade socket is the pilot's own `DEGRADED`; the built-in cycle,
its reads and its journals continue (tested in `capture()` itself).

Owner Q16 (2026-10-15): these bands are **outside** the 10-01 maker-P&L
pre-registration's 12-market stratum. Every pilot universe row carries
`stratum: outside_10_01_maker_pnl_prereg_12_market_stratum`, `lane` and the config's
`config_sha256`, and every pilot read lands in a pilot partition: `discovery-pilot`,
`book-<token>` for pilot tokens only, `universe-pilot-<id>`, rewards `-pilot`, and a
separate trade socket journaling `trades-pilot.jsonl` (channel `pilot_trades`). No
pilot token joins the raw update stream, `books.jsonl`, `ranking_books.jsonl`,
`trades.jsonl` or the core discovery journal, so the panel inputs and the update cap
are unchanged. The pilot runs after the core cycle, is skipped in the Red disk band,
and any failure is journaled (`recorder_only_cycle_error`) as `DEGRADED` without
failing the cycle. A test ratchet holds the built-in selection identical with the
pilot on, sweep off, malformed or absent.

## Capture families

`--family <id>` records one family from
[`config/capture_families.json`](../../config/capture_families.json) instead of the
core universe, as a **separate process with its own root**,
`data/maker_evidence_families/<id>` (the core root and `--extra-conditions` are
refused). The core 88a root, its discovery captures and every reader of them stay
unchanged: a lowest-temperature slug inside them would make the pinned exam
exporter refuse with `unregistered_event`, and the family's reads would share the
core 55-second cycle.

A family names, per registry city, an event-slug prefix (dates are formed as for
the core family, in the city's own time zone), its excluded cities with the reason,
its day-aheads and its bounds. The first family, `lowest_temperature`, covers the 11
cities the lowest-temperature desk study (2026-10-02) admitted for passive capture;
Chicago is excluded because its own F1 was falsified.

Each minute a family discovers its events in batches of 12 slugs, keeps **every**
active condition (no ranking, no reward filter; bound `max_conditions`), and reads
both tokens' books. Gamma's reward terms arrive with discovery every minute and are
stored change-only in the selection projection. The full CLOB
`/rewards/markets/<condition>` record is read when a condition's Gamma terms change,
when it is new, or after `reward_sweep_minutes`, at most
`max_reward_reads_per_cycle` per minute (changed first, then oldest). Reward records
share one journal per family and universe rows one change-only journal per city.
Universe rows carry the family, Gamma's scalar terms and the latest CLOB record hash
and rate.

A family opens **no websocket**: trades and raw updates stay with the core recorder
(at 100 tokens per connection, the lowest-temperature universe alone would need eight
more sockets). It stops at its own `stop_below_free_gib` floor (70 GiB for
`lowest_temperature`), above the core Critical brake, so it yields disk before the
core recorder does. Below the floor it opens no journal; each one-minute retry only
rewrites `status.json` with `STOPPED_FAMILY_DISK_FLOOR`. Its journals are
`canonical_evidence` (`passive_capture_family_evidence`).

`scripts/ops/register_maker_evidence_family_capture.ps1 -Family lowest_temperature`
registers `WeatherMakerEvidenceLowestTemperature` with the same S4U/IgnoreNew/one-minute
contract. Only the production operator registers it, after integration. The task name
must be `WeatherMakerEvidence<PascalCaseId>` (the registrar refuses any other): the
monitor finds each family's task by that name. A new family passes its own `-TaskName`
and adds its `config/scheduled_tasks.json` row.

**Monitoring.** `weather.reporting.market.capture_family_status` reads every family in
the config from its bounded `status.json` (never the journals). `status.ps1` prints one
`FAMILY` line per family (state, status age, conditions against `max_conditions`, free
space against the family floor, mean request rate, task state) and the cockpit's Health
column shows the same rows. The alarms are the core recorder's: while the family's task
is registered and enabled, a missing or unreadable status, a status older than 180 s, or
any state other than `CAPTURING` is a `CAPTURE_FAMILY` FLAG. **A family stopped at its
own floor (`STOPPED_FAMILY_DISK_FLOOR`) is a WARN with its reason, not a capture failure**:
it is yielding disk to the core recorder as designed, and the disk itself is alarmed by
the disk lines. That floor status is rewritten every one-minute retry, so a stale one
is still a FLAG (the retries have died). An unregistered or disabled family is
informational only. The cockpit cannot see the Scheduler, so it holds any family that
has written a status to the alarms.

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
`raw_working_fraction` is the peak against that limit; `status.ps1` warns
(`MAKER_EVIDENCE_LATCH`) at one half.

The core recorder fsyncs journals in groups (the execution-tape precedent): appends
mark a file dirty and a flusher syncs dirty files at least every second, and before
any seal. Three consecutive fsync failures latch the writer and stop capture as
`STOPPED_STORAGE_FAILURE`. `status.json` `storage` reports appends, fsync calls and
failures. Family recorders keep per-append fsync.

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
.\venv\Scripts\python.exe -m weather.market.maker_evidence_capture --dry-run --duration-seconds 5400 --root C:\scratch\s2s9-run --recorder-only-config C:\scratch\capture_families-pilot-on.json
.\scripts\ops\register_maker_evidence_capture.ps1 -WhatIf
```

The dry run (1,800-5,400 s) requires a new root with a path part named `scratch`, rejects
an active RE-1 preflight/live process without opening its files, and reserves one minute for teardown before
19:45 America/Toronto. The process guard is checked each cycle.
`--recorder-only-config` (dry run only; production reads the default path) points the
dry run at a copy of `capture_families.json`, e.g. with the pilot, the sweep and
`event_driven` on to measure S9 before the switch-on; a dry run honours `event_driven`
before the hold ends because its root is scratch. It writes the
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

`python -m weather.market.maker_evidence_disconnects --date <local date>` replays
only the `stream_lifecycle`, `stream_gap`, `stream_tokens` and `subscription`
journals (plain or gzip). It reports socket drops by cause, channel and local hour,
venue close codes, connect failures, orderly stops and session lifetimes, listing
each input with its SHA-256. It is read-only and opens no connection.

Dark time is judged per token, never per subscription key. A swap rekeys every socket,
so the earlier per-key figure kept an old key "dark" until that exact token set came
back: 53,760 s on 2026-09-29, against 283 s with no trade socket connected at all.
That field (`dark_seconds_by_cause`) had no downstream reader and is removed.
`coverage_by_channel.<channel>` reports:

- `token_dark_seconds_total`, `per_token_dark_seconds`, `darkest_tokens`: time a token
  was wanted while no connected session's subscription included it, taking the union
  across every subscription that contains it. The total is in token-seconds.
- `token_dark_seconds_by_cause`: that time by the end cause of the session whose end
  opened the gap. `awaiting_connect` is time a token was wanted before its first
  covering connect.
- `all_sockets_down_seconds` and `all_sockets_down_gap_seconds`: time the channel
  wanted any token while none of its sockets was connected.
- `wanted_basis`. `stream_tokens_rows` uses the journaled wanted sets.
  `inferred_from_session_rows` covers journals written before those rows existed: a
  token stays wanted after its coverage ends only if the channel's next connect round
  (connects within 10 s of the first) covers it again, or until that round began
  after a failure. For those journals, all-sockets-down spans the channel's first to
  last row.

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
A reader holding `status.json` makes the replace fail on Windows; the recorder retries it
(5 tries within 2 s) and, if still blocked, journals a WARN `status_write_failed` event, counts
`status_write_misses` in the next status, and keeps capturing.
After changing this worker, the production operator must explicitly re-adopt
its task; it has no effect on the existing supervisors' adoption behavior.

### Explicit restart (88a-R)

Owner Q11 (2026-10-15): new capture families adopt code by explicit restart, with
running-vs-disk code identity shown in status. The recorder stamps `source_sha256`
for each `weather.*` module it imported; `status.ps1` compares those with the files
on disk and reports `maker_evidence_code` (`CURRENT`, `STALE` with the modules, or
`UNKNOWN`) on the `MAKER` line and in JSON, warning `MAKER_EVIDENCE_CODE` when stale.
It also prints a `PILOT` line and warns `MAKER_EVIDENCE_PILOT` on `DEGRADED` or
`CONFIG_ERROR`.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\opsestart_maker_evidence_capture.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\opsestart_maker_evidence_capture.ps1 -Apply
```

Report-only without `-Apply`. It refuses outside 00:30-01:00 local, without a
readable status, when the status pid is not the running core recorder (`--family` or
`--dry-run` refuse), or while a raw update window is active. `-Apply` stops that
process only; the task's existing PT5M trigger starts the new one (it never touches
the Scheduler). It waits up to `-WaitSeconds` (default 420) for a new pid in
`CAPTURING` and prints a JSON receipt with `gap_seconds` and the identity after.
Exit 0 only for `RESTARTED_CURRENT`; 2 refused, 3 not restarted, 4 not current.
Record the gap in the panel notes.

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
registration, status, restart, reward-trigger, recorder-only or capture-family changes. Verify with the focused maker-evidence tests,
import architecture, storage/schema tests and the required timed scratch run.

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
uses current-user S4U/Limited, IgnoreNew and a one-minute retry trigger; one
long-running Python worker owns the lock. A Critical disk stop remains visible
and subsequent triggers keep refusing capture until disk recovers. The worker
never stops another process. `scripts/ops/status.ps1` reads `status.json`, flags
missing/stale/non-capturing state when armed and displays band count/disk/cap.
After changing this worker, the production operator must explicitly re-adopt
its task; it has no effect on the existing supervisors' adoption behavior.

The central schema registration is additive. Its shared-registry placement
means deployment must use the repository roll-verdict tool; independence of
the worker does not itself prove the entire branch roll-free.

## Update when

Update with selection, endpoints, timing, CLI, byte/disk brakes, storage,
registration or status changes. Verify with the focused maker-evidence tests,
import architecture, storage/schema tests and the required timed scratch run.

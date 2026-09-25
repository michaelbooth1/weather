# Mission 88a — passive maker-evidence capture

**Verdict: PARTIAL — the 30-minute capture and integrity checks pass, but the
tens-of-MB/day storage target is missed (298.02 MB/day projected with the default
cap). Production discard-counter baseline and host roll qualification also remain
outstanding.** No production registration or adoption was performed. This is a
handback for the owner-authorized mission, not deployment or live authority.

## Binding and scope

- Handoff: `origin/codex/reward-test-attended-handoff-20260921`,
  fetched tip `cc028cda9f5b540eab42982a5a1a7a7657a48b24`,
  `workstation-handoff-2026-09-88a-passive-maker-evidence-capture.md`.
- Branch: `codex/maker-evidence-capture-20260923`, based on fresh `origin/master`
  `198f7ccbcd8e80271693462425582097d22b298b`.
- Implementation tip: `bc53822a2289114b6c2f94b4624514fbf23a304f`.
  The report commit follows that tip. Every recorded runtime import hash was
  checked against the committed source; all matched.
- Worktree: `scratch/w/maker-evidence-capture-20260923` on the non-capture workstation.
- Only public International Gamma/CLOB reads and public market WebSockets were used.
  No `.env`, venue credentials, authenticated endpoint, order module, RE-1 session
  worktree or campaign root was accessed. No task was registered or production
  supervisor called. Runtime import hashes are retained with the scratch status.

The [owning contract](../operations/passive-maker-evidence-capture.md) documents the
CLI, selection, storage representation, brakes, operator extras, registrar and status
integration. New journals are classified as canonical evidence, with no age deletion.

## Implementation

Every minute the independent Idle-priority worker discovers local T+0/T+1/T+2 for
every configured city, reserves three eligible bands per day when available, and
fills ten per city by the canonical modelled 20-share reward score. Operator extras
are additive. Both-token book reads are batched; per-condition reward bodies are
change-only, with every response hashed. Public trades remain event-driven after
the separately capped raw-update sockets close. The default cap is 300,000,000 raw
bytes per UTC day, persisted across restart. Red drops updates; Critical stops all
capture and writes terminal status.

Books are retained losslessly in per-token journals and batch delimiter/offset
records. Rewards and raw updates are grouped by condition; selections by city.
Gamma discovery retains all selection inputs as an explicit change-only projection,
plus the original response hash/byte count. The full Gamma wire response is **not**
reconstructable; the independent stored/content hashes prove the retained projection.
Raw books, stored reward changes, updates and public trades remain reconstructable.
Unchanged canonical reward replies reference the prior body even if wire whitespace
changes. The inspector reports these distinctions rather than claiming every raw
response can be recreated.

Day-close gzip runs outside the active writer lock, verifies decompressed SHA-256,
and changes only the representation of closed journals. Request/reply sizes,
pagination, sockets, queues, deadlines and retries are bounded. Torn journals refuse
restart without truncation. Malformed HTTP book bodies are retained before parsing
fails. There is no gap backfill claim.

## Workstation verification and measured capture

Verification: **115 tests passed, 40 subtests passed** in 14.25 seconds through
the workstation admission wrapper: maker-evidence and canonical estimator tests,
import architecture, storage classes, schema registry, dependency pins and roadmap
backlog. `compileall -q app src tests` passed through the same wrapper, without
importing those modules. Agent docs audit passed (18 agent files, 921 Markdown
files); generated backlog check passed. All three changed PowerShell scripts
parsed cleanly; this is syntax verification, not production Scheduler execution.
Whitespace checks passed. Owned pytest temporary directories were removed after
verification, while every capture namespace was preserved.

The acceptance run used the committed implementation from **12:38:25 to
13:08:27 ET on 2026-09-23** (1,802.05 seconds including teardown), completing
before the 19:45 ET cutoff. Exit 0, **30 successful cycles, zero failed cycles**,
120 selected conditions / 240 tokens across all 12 cities. Eligibility shortages
were explicit: Toronto T+0 had two bands early; Chicago T+0 had two at the end.
No event was missing. Public stream gaps/errors: zero. All six sockets and the
process exited. Three transient HTTP attempts failed and recovered within their
cycles through the bounded retry.

| Measurement | Observed acceptance run |
| --- | ---: |
| HTTP attempts | 3,843 (127.95/minute) |
| HTTP response bytes | 88,117,614 |
| Request latency, mean / maximum | 0.1618 / 5.031 seconds |
| Histogram upper bounds for p95 / p99 | 0.5 / 1.0 seconds |
| Both-token book batches / ranking batches | 90 / 60 |
| Per-condition reward replies / changed bodies | 3,600 / 1,613 |
| Discovery replies / changed projections | 90 / 17 |
| Raw update events / bytes | 279,984 / 186,606,627 |
| Raw update rate | 9,322.19 events/minute; 6.213 MB/minute |
| Public trade events retained | 386 |
| Journal bytes, including manifests | 473,648,468 (15.770 MB/minute) |
| Exact gzip-level-6 encoding size | 46,392,957 bytes |
| Verified manifest records / journal files | 284,922 / 612 |
| Last sampled process peak working set | 67,227,648 bytes (64.11 MiB), Idle |

Decimal MB are used for storage rates. These are **30-minute measurements**, not
a measured full day. Stationary uncapped extrapolations are 8.947 GB/day of raw
updates, 22.709 GB/day of total journals and 2.224 GB/day compressed. Applying the
300,000,000-byte daily raw-update cap to the measured per-family compression rates
projects **298.02 MB/day compressed**. The cap was not reached in the half-hour;
cap, restart and UTC reset behavior passed deterministic tests. Normal live disk
state stayed Green; disk-threshold behavior was verified by tests.

The cap-adjusted storage projection is 69.1% below the initial implementation, but
still does **not** meet the requested target. In the measured half-hour, token-book
journals alone compressed to 1.710 MB; repeated connection subscription lists to
1.159 MB; reward manifest records to 0.574 MB. These continuing families dominate
the full-day overhead after updates are capped. Further lossless storage work and
a new measured qualification are required before calling storage accepted. No
reduced cadence, narrower universe or lower default cap was substituted to pass.

The adjacent [machine-readable evidence](agent-report-2026-09-88a-passive-maker-evidence-capture.json)
contains rates, request histograms, per-minute counts, per-family sizes, source
hashes and resource samples. Its SHA-256 is
`e77d7988f97104bbed278f8b908dfc194f374d31ec344efdead163e2cd9cbb58`.
The final manifest SHA-256 is
`62cab9bfa7c44ea6c90b7d44e69d1f181189dd23b9c0d23232ccbde76af1c724`.
Full journal and inspection files remain in the named ignored scratch namespaces;
only the compact report evidence is checked in.

Reproduction uses the commands in the owning contract. The live command was
`python -m weather.market.maker_evidence_capture --dry-run --duration-seconds 1800
--root <repository>/scratch/maker-evidence-88a-acceptance-20260923`; the terminal
journals are inspected with `python -m weather.market.maker_evidence_inspect
--root <same-root> --day 2026-09-23` through `workstation_heavy.ps1 -Kind weather_heavy`.
The inspector performs no venue calls and does not rewrite evidence.

The initial 30-minute run completed at 12:19 ET with 29 successful cycles and one
failed cycle after a transient public connection reset. It exposed the need for
bounded retries and socket reconnection coverage. Initial Gamma storage alone
projected about 510 MB/day compressed, so that format did not meet the storage
target. Offline inspection of that completed run verified 288,177 manifest rows:
504.91 MB of journals encoded to 68.63 MB at gzip level 6; the 300 MB update-cap
projection was 965.07 MB/day, confirming that the original format was unsuitable.
These are measurements of this mission's initial collector, not the production
tape discard counter. Two intermediate runs were stopped by exact owned PID/command/start-time
identity checks after further storage/error-path review; each has an explicit
`operator-interruption.json`, and all evidence was preserved. They are not passed
30-minute runs. The final acceptance namespace is
`scratch/maker-evidence-88a-acceptance-20260923`.

Heavy verification and offline compression inspection use the repository's
`workstation_heavy.ps1` host/principal/mutex admission path. An unrelated test job
held the shared lease during development; refusals were respected, without stopping
that job or bypassing admission. Only the offline inspector was added to the module
allowlist; the network collector was not added. Lightweight docs and parser checks
did not mutate Scheduler or production state.

## Production qualification still owed

1. **Storage acceptance is not met.** The measured default-cap projection remains
   about 298 MB/day compressed. Do not register on the assumption that the requested
   tens-of-MB/day target passed.
2. **Existing tape discard volume is unavailable locally.** Before the first live
   run, the expected `data/snapshots/execution_tape_status.json` was absent in both
   the main checkout and this new worktree. No frozen mirror or historical receipt
   was substituted. `non_trade_messages_discarded` counts messages, not bytes:
   the production operator must measure its delta between two current status
   snapshots from the same worker/start time, with the elapsed time. The new
   collector's measured raw byte rate is reported separately and is not a baseline
   measurement of the existing tape's different subscriptions.
3. **Roll verdict: UNDECIDABLE (exit 1).** The required tool was attempted again
   against committed implementation `bc53822a` with
   `-Branch codex/maker-evidence-capture-20260923 -Base origin/master`; it refused
   because the workstation has no current snapshot/CLOB/observation/enrichment
   closure status. Its early refusal did not emit the requested JSON receipt.
   The worker itself is independent, but the mandatory additive central schema
   registration changes a shared imported module. Do not infer ROLL-FREE from the
   standalone Scheduler entry point. Run the tool against current production
   closures and use its prescribed integration path before adoption.
4. After qualification, verify pinned dependencies, register with the owning
   registrar, publish the separate extras file as needed, and verify the worker's
   atomic status. This handback does not register, merge, restart or trade.

No empirical maker edge, own-account fill probability or earned reward is inferred
from this data collection exercise.

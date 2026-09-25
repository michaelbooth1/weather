# Mission 88a Amendment 1 — passive maker evidence

**PASS for workstation Amendment 1 verification.** The final stream-off run projects
**113.8 MB/day compressed** on the stricter 30-cycle basis,
below the 150 MB/day target. Both final public dry runs completed 30 cycles with
zero failed cycles, ending at **14:44:44 ET** and **14:45:23 ET** on 2026-09-23,
before 19:45 ET. **PR 87 remains draft; production adoption is not qualified here.**

This answers section 5 of the user-designated handoff and supplements the immutable
[original report](agent-report-2026-09-88a-passive-maker-evidence-capture.md) and its
[hash correction](agent-report-2026-09-88a-passive-maker-evidence-capture-correction.md).
Implementation tip: **bd4e4b0a9215fb1033b19c5b994f807b36886432** on
`codex/maker-evidence-capture-20260923`.

## Implementation and lossless storage

Raw updates default off. The operator's extra-condition file supplies at most two
explicit, non-overlapping UTC windows of at most 30 minutes each, for the intervals
before and after a session. Only those conditions receive raw-update subscriptions.
Minute books/rewards keep the target of ten eligible conditions per city plus extras. The
measurement window used three public next-day Los Angeles conditions selected
from this collector's own output; it did not inspect or represent an RE-1 session.

Journals rotate hourly, with an earlier 100 MB segment threshold. A background
worker verifies decompressed SHA-256 before replacing each closed plain file with
gzip, including after failed HTTP cycles. The writer refuses before 500 MB of
plain journals/manifests, reserving sealing space. Each sealed manifest has one
entry per file; response hashes and logical offsets remain inside the journals.
Subscription lists and discovery projections use content-change storage. Changed
subscription lists share a journal so gzip can reuse their common token IDs.
Book batches still reconstruct to their exact wire SHA-256. The previously
documented Gamma selection projection remains explicit; omitted analytics are
not claimed reconstructible. Existing pinned websocket-client replaces the added
websockets dependency, with frame and fragmented-message bounds before allocation.
The [owning contract](../operations/passive-maker-evidence-capture.md) describes v2.

## Final measurements

| Measure | Stream off | Three-condition window |
| --- | ---: | ---: |
| Completed / failed cycles | 30 / 0 | 30 / 0 |
| Elapsed seconds, including final compression | 1804.452 | 1804.909 |
| Raw journal bytes per minute | 1357744 | 1783451 |
| Measured peak plain journal/manifest bytes | 40833071 | 53649456 |
| Final plain journal/manifest bytes | 0 | 0 |
| HTTP requests / recovered request errors | 3817 / 0 | 3848 / 1 |
| HTTP mean / max latency, seconds | 0.1442 / 4.047 | 0.1413 / 5.016 |
| Update messages / bytes received | 0 / 0 | 13500 / 8243448 |
| Update / trade socket gaps | 0 / 0 | 0 / 0 |
| Response records verified | 4640 | 18168 |
| Journal files / file manifests verified | 444 / 1 | 451 / 1 |
| Total gzip-6 bytes | 2370813 | 4119758 |

Incremental raw-update retention in the active window is
**1.722 MB compressed per 30 minutes**,
or **3.445 MB for two such windows**
at the observed rate. The measured active interval was
1780.598 seconds. This is update-file
cost above the ordinary books/rewards/trades record; lifecycle/manifest overhead
is separately visible in the evidence. Public subscription transitions are
retained; zero reported gaps does not claim venue completeness or backfill.

| Stream-off family | Observed gzip bytes | Projected MB/day, 30-cycle basis |
| --- | ---: | ---: |
| books | 234,750 | 11.268 |
| discovery | 394,447 | 18.933 |
| manifests | 38,324 | 1.840 |
| ranking_books | 46,733 | 2.243 |
| rewards | 366,909 | 17.612 |
| run_summary | 1,803 | 0.087 |
| stream_lifecycle | 11,139 | 0.535 |
| subscriptions | 29,409 | 1.412 |
| token_books | 1,059,737 | 50.867 |
| trades | 37,575 | 1.804 |
| universe | 149,987 | 7.199 |

The table multiplies each family's 30-cycle compressed bytes by 48; it does not
gain from cleanup time. All 30 baseline cycles contain all 12 cities; the
actual ranked count was 119-120. Shortfalls were in austin;
each retained every eligible candidate, as audited per cycle. Records are matched
by each city's capture order: variable HTTP latency can place successive cycle
completions in the same wall-clock minute. Conservatively scaling
the strict daily estimate to 120 from the minimum observed count gives
114.76 MB/day. The inspector's elapsed-time projection is separately
113.52 MB/day. Both are
short-window extrapolations, not full-day guarantees. There was no reduced cadence
or narrower ranked universe. Extra bands were additive; naturally insufficient
T+0 eligibility remains explicitly recorded as shortages. Both final runs overlap
on the workstation, in separate roots; this is not production-host load qualification.

## Verification, earlier measurements and production handback

**127 tests and 40 subtests passed** in 13.79 seconds through the workstation
admission wrapper: collector, estimator, storage classes, schema registry, import
architecture, dependency pins and roadmap backlog. Compilation, agent-doc audit,
generated-backlog and whitespace checks passed. All 18 runtime source hashes match
the committed checkout/Git blobs, and both final runs have identical source hashes.

The first completed amendment baseline on `0cd20b5d` verified cleanly but projected
151.36 MB/day (elapsed basis), above target. Its subscription lists were individually
compressed files. Grouping changed lists in one journal produced the final build;
the earlier result and both earlier runs remain in the evidence. Those earlier
30-minute runs crossed the UTC hour boundary during capture: closed files were
verified/gzipped and plain working sets fell while cycles continued. The hourly
rotation code is unchanged in the final subscription-only fix and has focused tests.
Venue activity and partial-hour segment counts also differed; the measurements
do not isolate the size of the subscription change's effect.
An even earlier short preliminary run was interrupted to move compression maintenance
outside the successful-HTTP-cycle path; its evidence and interruption note remain.

The repository roll-verdict tool returned **UNDECIDABLE**, exit 1: this workstation
lacks all four live closure status files. It emitted no JSON receipt; the transcript
is embedded in the evidence. No roll-free verdict is inferred. Production must
measure the existing tape's discard counter, rerun its roll verdict and qualification,
and register only after its disk sweep brings the daily low out of Critical.
No Scheduler registration, runtime adoption, production merge, credential access,
.env read, order import, RE-1 worktree access or campaign-root access occurred.

Final raw roots are the two `maker-evidence-88a-a1-qualified-*` directories under
the task's workstation scratch directory, as recorded in status. All capture roots
are retained. [Evidence JSON](agent-report-2026-09-88a-passive-maker-evidence-capture-amendment-1.json) SHA-256 over published LF bytes:
`7bd9fedb2b53a9e63388ce9f1a77af2cfb4c7e84db52619dcd85365dabf21577`.

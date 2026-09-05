# 325. Tiered Data Retention And Verified Archive Offload [OPEN 2026-07-21 - DESIGN RECORDED; NO DELETION AUTHORIZED YET]

Goal: keep the production capture host permanently inside its disk budget by
holding only the operating window locally, offloading everything older to a
verified append-only archive on the workstation host, and never deleting a byte
that has not been proven durable elsewhere.

Owner/package: weather.operations, weather.collection

Source: 2026-07-21 measurement on the production host (931 GB volume, 223 GB
free, 24%). Repository footprint 503 GB, of which `data/` is 466 GB:

| Subtree | Size | Files |
| --- | --- | --- |
| `data/snapshots` | 345.6 GB | 3,527,668 |
| `data/taker_runs` | 47.8 GB | 4,733 |
| `data/backtest` | 43.6 GB | 3,622 |
| all others combined | ~29 GB | ~164,000 |

`data/snapshots` is 74% of bytes and 95% of files, and is already organized as
one directory per market-day (`highest-temperature-in-<city>-on-<month>-<day>-<year>`,
562 present), so the market-day is a natural atomic retention unit with its date
in the name.

Measured per-day totals across all 12 markets: Jul 15 9.3 GB, Jul 16 13.0 GB,
Jul 17 9.0 GB, Jul 18 9.6 GB, Jul 19 26.0 GB, Jul 20 25.3 GB, Jul 21 16.2 GB
(partial). At the recent ~20 GB/day rate the free-space runway is roughly 11
days, so this item is time-critical even though no deletion is authorized yet.

Why this matters: the host cannot be grown, and capture cleanliness is the
critical path to the first release (Item 321 and the streak window). A full
disk stops capture, which is strictly worse than any storage cost. Retention
alone cannot solve it: a 45-day raw window at the current rate is ~900 GB,
larger than the whole volume, so per-day size reduction is mandatory alongside
retention.

Blocking prerequisite: the nightly `WeatherDataMirror` task currently runs
`robocopy /MIR`, whose delete-propagation makes the workstation copy a replica,
not an archive. Pruning locally under the present configuration would delete the
offloaded copy on the next run. Sync semantics must be split before any
retention policy is enabled.

## Design

Three tiers, with the market-day as the unit of movement:

- **Hot (production, raw).** The rolling window read directly by capture, the
  daily settlement chain, open barriers, and the point-in-time window. Sized by
  real consumers, not by convenience.
- **Warm (production, compressed).** Closed market-days retained locally as one
  compressed archive per market-day. Restores in seconds when a barrier resumes
  an older date. This also collapses the 3.5M-file count, which is itself a cost
  (enumeration, backup time, NTFS metadata).
- **Archive (workstation, append-only, compressed).** Every market-day ever
  produced, never deleted by a sync. Replay, backtest, and corpus work run
  against this tier on the workstation, which is where the memory and disk
  headroom already are.

Hot-window sizing must be derived from the longest real lookback, not guessed.
Known consumers: the point-in-time window needs 14 contiguous complete days
ending within 7 days (≈21 days), the maker-paper evidence window is 14 runs, and
observed barrier resumes have reached back several days (Jul 12 and Jul 14).
Minimum safe hot window is therefore ~30 days; the warm tier absorbs the rest.

Classification governs whether an artifact may ever be deleted without an
archive copy:

- **Irreplaceable:** market snapshots and observations. A market price at a past
  instant can never be recaptured. Archive forever; never delete unverified.
- **Evidence:** taker/maker run summaries, settlement tapes, ledgers, labels.
  Archive forever; prune locally only after settlement is final.
- **Regenerable:** replay caches, permission maps, feature stores, backtest
  outputs. May be deleted locally without archiving, and rebuilt on demand.

Deletion is gated on four conditions, all fail-closed:

1. the market-day is older than the configured hot window;
2. it is closed - settled, labeled, and referenced by no open barrier, queue
   entry, or active point-in-time window;
3. an archive copy is verified by manifest (file count, total bytes, and content
   hashes), not merely present; and
4. the deletion is recorded in a prune ledger carrying the restore pointer.

A restore drill must pass before any automated prune is enabled. An archive that
has never been restored is an assumption, not a backup.

## Scope

- [ ] Split sync semantics: keep the disaster-recovery replica separate from an
  append-only archive push (`/E`, never `/MIR`) into a distinct archive root.
  This must land before any retention policy is enabled.
- [ ] Investigate the 2.5x per-day growth step change (Jul 15-18 ~9-13 GB/day
  versus Jul 19-21 ~16-26 GB/day). Both spike days were operator outage days, so
  retry or duplicate-capture amplification is a plausible defect; if so, fixing
  it is the cheapest reclaim available and reduces every downstream tier.
- [ ] Derive the hot window from code rather than assumption: enumerate every
  production reader of `data/snapshots`, `data/taker_runs`, and `data/backtest`
  with its maximum lookback, and record the binding constraint.
- [ ] Build the market-day manifest and verification tool (file count, bytes,
  content hashes) plus a restore path, and prove both with a restore drill on a
  closed day before any deletion is authorized.
- [ ] Add per-market-day compression for closed days (warm tier), preserving the
  existing read paths through a restore-on-demand shim.
- [ ] Implement the four-gate prune with its ledger, defaulting to dry-run and
  requiring explicit authorization to delete.
- [ ] Never prune a market-day inside the point-in-time streak window or
  referenced by an open barrier; assert this in tests, not only in documentation.
- [ ] Dispatch the conservative cleanup already written in
  `docs/roadmap/agent-work-order-2026-07-20b.md` (duplicate and regenerable
  artifacts) as the immediate, no-new-mechanism reclaim.

## 2026-07-27 workstation storage-pressure build

The build-only slice in
[the workstation storage-pressure report](../agent-report-2026-07-27-workstation-storage-pressure-build.md)
adds three guarded mechanisms without authorizing production mutation:

- future full-book long-CSV capture is controlled by a checked-in policy whose
  default remains `true`; malformed or missing policy preserves current
  capture;
- replay-cache cleanup is full-key reachability based, retains ambiguity, and
  requires frozen candidate static context, an exact retained serving-release
  graph, two cache-off rebuild parity checks, and a durable write-ahead receipt
  before an exact-file unlink; and
- closed-day projection tiering has a complete family registry but permits only
  `order_books_long.csv`, whose canonical source and gzip/JSONL reader fallback
  are fixture-proven.

All production dry-runs, approvals, compression, deletion, deployment, mirror
topology changes, and restore drills remain operator-owned and not done. This
does not close the broader archive-offload item or change any scope checkbox
below.

## 2026-07-29 measurement: do the warm tier first

Host at 146 GB free, falling 15.7 GB/day (~9 days). Retained `data/snapshots` is
**8.88 GB/day** (Jul 27) and 8.99 GB/day (Jul 20) across 12 markets — steady, and
almost entirely canonical evidence, so no cleanup can touch it.

Gzip level 6 over the uncompressed files >5 MB of one closed market-day
(`atlanta-on-july-20`): **0.65 GB -> 0.05 GB, 14.3x.** `order_books.jsonl`
292->28 MB (10.5x), `clob_tokens.jsonl` 81->1 MB (74x), `replay_inputs.jsonl`
54->4 MB, `variant_predictions.jsonl` 51->4 MB, `order_books_summary.csv`
46->4 MB. Ordered by reclaim across 12 markets, `order_books.jsonl` alone is
3.2 GB/day and the top two families are 55% of the win.

This reorders the scope above. **The warm tier is not gated on the sync split**:
compressing closed market-days in place is not a deletion, so it needs no archive
verification, no prune ledger, and no `/MIR` topology change, and it is reversible.
It should take retained snapshots to roughly 1.3 GB/day and is a large one-time
retroactive reclaim. The sync split still gates every *deletion* and remains the
prerequisite for the archive tier.

The real blocker for the warm tier is reader coverage: the projection-family
registry marks 16 of 17 families ineligible with *"Direct gzip readers not all
proven"*. The compression mechanism already exists in
`closed_day_projection_tiering`; the work is proving the gzip read path per family
and flipping eligibility, which makes it incremental and safely interruptible.

Two corrections to earlier assumptions, both from measurement:

- `capture.write_order_books_long_csv=false` is **not** a disk fix. Tiering already
  compresses that projection 25x (1.44 GB -> 57 MB per market-day), so the flag is
  worth ~0.7 GB/day retained, not ~17 GB/day.
- `data/backtest/replay_cache` (32.3 GB, untouched since 2026-07-11) is **not**
  reclaimable: `storage_classes.py` gates it on
  `reviewed_exact_path_reachability_manifest` and states *"age and LRU are never
  deletion evidence"*. That manifest needs the active release pointer, and
  `artifacts/releases` does not exist on this host.

## 2026-07-29: a fourth tier (2 TB Google Drive), and what it can and cannot be

Exact figures from the 04:30 mirror log, which reports the whole replicated tree
without needing a scan: **531.805 GB, 3,785,460 files, 53,469 dirs.** That run
copied **39.476 GB** and purged **15.927 GB** of extras.

Two numbers govern every offload decision, and both rule out the obvious plan:

- **File count.** 3.79M files. A per-file cloud sync of that tree costs days of
  pure metadata round-trips on every pass, forever. The market-day archive
  (562 objects) is the only viable unit — so the warm tier is a **prerequisite**
  for any cloud tier, not an alternative to it.
- **Churn amplification, 4.4x.** 39.476 GB copied for ~8.9 GB of genuinely new
  retained data, because `order_books_long.csv` and its siblings grow all day and
  re-copy whole. A cloud target suffers the same amplification with no delta
  transfer. Therefore **only sealed (closed *and* tiered) market-days are ever
  pushed**, which makes the cold tier append-only by construction and sets upload
  volume to the retained rate rather than the churn rate.

Capacity arithmetic on 2 TB:

| what we push | initial | daily | 2 TB lasts |
| --- | ---: | ---: | ---: |
| raw tree as-is | 532 GB | ~10 GB | **~5 months** |
| sealed compressed market-days | ~70-120 GB | ~1.5-2 GB | **~3 years** |

So 2 TB is either barely a stopgap or multi-year headroom, decided entirely by
whether we compress first. Compressed is also the only version that fits a home
uplink: ~2 GB/night is minutes, whereas 39.5 GB/night never converges.

Tier 4 (cold, off-site) therefore reads: **one verified compressed object per
sealed market-day, pushed by `rclone` through a `crypt` remote, verified with
`rclone cryptcheck`.** Encryption is not gold-plating here — raw capture payloads
can embed provider API keys in request URLs and headers, and an upload to a
third-party service cannot be recalled, only rotated. A `crypt` remote closes
that question structurally instead of relying on a scan being exhaustive, and
`cryptcheck` satisfies gate 3's "verified by manifest, not merely present".
Cost acknowledged: no server-side dedup or preview, and the crypt passphrase
becomes load-bearing for a *copy* (never for the original).

Drive must **not** be a mirror target, a working tier for replay/backtest, a git
remote, or a `.git` host. It **should** carry the ~382 MB model artifacts that
exhausted the metered Git LFS quota, which is a clean, small, immediate use.

This does not reopen the durability agenda, which is deliberately deprioritized
until the model is profitable. The cold tier is being specified as **capacity
relief**, and it stays behind the sync split like every other deletion.

### Mirror scope is a separate lever from retention, and it was free

`WeatherDataMirror` ran a bare `/MIR` of all of `data/`, including
`data/backtest/replay_cache` — **32.28 GB / 770 files** of cache that
`storage_classes.py` classifies as rebuildable. Nothing requires a rebuildable
cache to be *replicated*; it is not archive payload. Excluded it via `/XD`
(2026-07-29), which is 3x the workstation's then-current 9.7 GiB admission
shortfall, recovered with no compression, no network, and no deletion of
canonical evidence. `/XD` skips the directory rather than purging it, so the copy
already on the workstation needs one explicit deletion there.

Next-cheapest compression family found while measuring: **10.67 GB of loose
analysis output at `data/backtest` root** (2,417 files; 4.86 GB `.csv`, 2.47 GB
`.pkl`, 1.94 GB `.jsonl`), untouched since 2026-07-11 — entirely cold and highly
compressible, but outside the closed-market-day family registry, so it needs its
own eligibility proof rather than an improvised one-off.

## 2026-08-02 first real dry run: the warm tier is blocked on the event-day manifest, not on reader coverage

First production dry run of `closed_day_projection_tiering plan` (`--as-of-date 2026-08-02`).
Read-only; wrote only to a review root outside `data/`. Result:

| Metric | Value |
| --- | ---: |
| Folders evaluated | 706 |
| **Eligible actions** | **0** |
| Blocked folders | 706 |
| Planned source bytes | 0 |

Blocker frequency across all 706 folders:

| Count | Blocker |
| ---: | --- |
| 661 | `order_books_long_csv_missing` (already tiered — benign) |
| 657 | `event_day_manifest_missing_or_invalid_json` |
| 93 | `canonical_order_books_jsonl_missing` |
| 48 | `event_day_manifest_current_validation_blocked` |
| 48 | `event_day_manifest_not_finalized_pass` |
| 12 | `event_day_is_not_closed_before_as_of_date` (today — correct) |
| 12 | `order_books_long_recently_written` (today — correct) |
| 1 | `event_slug_has_no_target_date` |

Isolating the 45 folders that actually hold a plain `order_books_long.csv`:

- **32 closed days whose *only* blocker is `event_day_manifest_missing_or_invalid_json`;**
- 12 open days from today, correctly refused as not-closed;
- 1 is `observation_source_cache`, a non-event directory under `data/snapshots` that the planner
  reports as a blocked folder rather than skipping as out-of-scope.

**Root cause.** `event_day_manifest.json` exists in **48 of 706** folders. Every one was written
`2026-07-11` and covers only June 6-9 (12 markets x 4 days) — and all 48 fail
`event_day_manifest_not_finalized_pass` *and* `event_day_manifest_current_validation_blocked`.
**No folder anywhere in the tree carries a finalized-PASS event-day manifest.** No manifest has been
generated since 2026-07-11.

**This corrects the 2026-07-29 entry above.** That entry named the real blocker as reader coverage —
"the projection-family registry marks 16 of 17 families ineligible" — and framed the work as proving
the gzip read path per family and flipping eligibility. That is a real constraint but it is **not the
binding one**. `order_books_long` is already eligible and already fixture-proven, and it still plans
zero actions. Proving the other sixteen families changes nothing while the manifest gate is
unsatisfied for all 706 folders. **The binding constraint is the event-day manifest pipeline.**

What is actually sitting there, measured the same day:

- **44 plain `order_books_long.csv`, 25.44 GB untiered**, against 588 already-tiered `.csv.gz`
  totalling 21.78 GB.
- **~17 GB of that backlog is 2026-08-01 alone** — twelve markets at ~1.4 GB each. At the measured
  ~23x this is ~16 GB reclaimable from one day of one family.
- **20 of the 44 have both a plain and a gz half.** These are the split-projection days: disjoint
  halves where a gz-first reader silently gets a partial day. They are not ordinary tiering
  candidates and the plain half must not be deleted. Any automation must exclude them explicitly.

The provenance of the existing 588 `.gz` files is **not** established by this dry run. Something
tiered them, but it was not this gated path, which has never been able to emit an action. Do not
assume the two are the same mechanism without checking.

Revised ordering for the warm tier, replacing the 07-29 framing:

1. Fix the event-day manifest pipeline: find why generation stopped after 2026-07-11 and why the 48
   that exist are not finalized-PASS. Nothing else in the warm tier can move until this does.
2. Re-run this dry run. Expect ~32 closed days to become eligible, worth ~25 GB.
3. Only then consider cadence (a scheduled plan/apply for the already-eligible family), with split
   days excluded.
4. Reader coverage for the other sixteen families remains genuinely open, but it is step four, not
   step one.

Automating an apply path is deliberately gated behind operator review by the design above, and it
would touch `src/**` or `scripts/**`, making it roll-sensitive. **Not before the release-#1 lock.**

Acceptance:

- Free space on the production volume trends flat or upward across a full week
  of normal capture, with no manual intervention.
- Every deletion is traceable to a verified archive copy and a ledger entry, and
  a restore drill has been executed and recorded.
- Capture, the daily chain, and barrier resumes complete unchanged for every
  date inside the hot window, and any older date can be restored on demand.

## 2026-09-05: signed-in native fixtures pass; real archive stage remains unproved

The owner authorized takeover of unfinished cold-storage work on September 4.
This entry records bounded qualification progress; the historical measurements,
commands and decisions above remain evidence of their own dates. Item 325 and
[item 330 W11](item-330-maker-economics-refocus-master-plan.md#w11--bound-storage-and-retire-noncontributing-model-work)
remain open. No new upload, restore proof, deletion or reclaimed bytes is
established by these checks.

At September 5 09:21:48 America/Toronto, the user ran the unchanged native
fixtures from an ordinary signed-in PowerShell session on `DESKTOP-RFCD2GH`:
**53 passed, zero failures, errors or skips**. The retained production-local
JUnit is `scratch/handoffs/archive-preflight-interactive-20260905.xml`, SHA-256
`0EFA430989BBA4E7E0ABA6F04685B1F067F173CF2C25AF4DE8E298D06A3637E6`.
The exact source and frozen test fixture file hashes match published repair
`aea427fb7faf0b5fd67b8893b62b11fe649e71ea`:

| File | SHA-256 |
| --- | --- |
| `src/weather/operations/workstation_cold_archive_stage.py` | `7795308527D65FDB1260E1807DAE0E48A48CA38DFB27F93CFED240CCD19C2D27` |
| `tests/operations/test_workstation_cold_archive_stage.py` | `DC44C46C013DA2CDE43410BDA0792E770FFC0EC7F5A515908799CB5DDD3A729C` |

The earlier exact-source SSH run remains **51 passed, two failed**: both
failures occurred in genuine PowerShell protection fixtures before the loader.
The signed-in result clears that native fixture boundary without changing the
source or weakening the fixtures. It does not prove loading the actual
provisioned credential or a real stage, transfer, restore or reclaim.
The separate 48-test archive/ratchet verification and
[exact-source Linux CI](https://github.com/michaelbooth1/weather/actions/runs/33944568088)
also passed. [PR 18](https://github.com/michaelbooth1/weather/pull/18) records the
source repair and qualification scope. The repair is stacked on adapter
`2d586da6dcfe2e0955154fd0dd0a2e5b1076af40`: encryption preflight runs before
source staging and rechecks its binding after compression.

A new clean workstation checkout is prepared at
`C:/Users/Michael/Documents/github/weather-archive-stage-signedin-20260905`,
at the same published repair commit and Git tree
`97adb242ee1af173ff26938a1eafe377d408aedd`. Source remains unchanged.
The signed-in v2 runner is prepared at
`C:/Users/Michael/Documents/Codex/handoffs/run-archive-real-stage-v2-20260905.ps1`,
SHA-256 `C781E1151BB986F23992B5ACD82327CE65DD5A0683132D0E5110E7DACBAE5A80`.
Independent review passed with no remaining findings. Three bounded smoke
checks covering parser behavior, actual metadata/ACL handling and the import
path passed in 0.79 seconds through the canonical workstation admission wrapper.
Their retained production-local JUnit is
`scratch/handoffs/archive-signedin-runner-smoke-bounded-20260905.xml`, SHA-256
`2AEB3084107455CA3DB40374D4D7F091333DDB6E66EF6EC2CCB7187AD71156D0`.
These exact local paths identify retained evidence and prepared workstation
files; they are not assumed to exist in a clean checkout.

The user has received the runner; no actual v2 result has yet been recorded.
Keep spent attempt `real-pilot-clob-console-20260713-v1` unchanged: it failed
at DPAPI before ciphertext creation and must not be reused or reconstructed.
The v2 preparation does not establish actual credential loading, ciphertext,
upload, restore verification or local reclaim. The next evidence is the
signed-in real-stage result, followed by exact encrypted-transfer and restore
proof before any manifest-bound reclaim. The paused, unverified workstation
mirror cannot substitute for that proof.

Fresh production disk metadata from `Get-PSDrive -Name C` at September 5
09:49:34 reports **40,978,989,056 free bytes (38.16 GiB)**. The retained receipt
is `scratch/handoffs/archive-native-qualification-disk-20260905.json`, SHA-256
`E8BB8A7095745E829CDDE5F5CE48F9DF43D3195DA7D2A4A9519411556A40E6A9`.
The earlier 01:38 status snapshot reported 34 GiB; it remains a dated fact,
not current capacity. No reclaim by this task or cause of the increase is
established. Current capacity still falls below the ordinary 50 GiB reserve.

Production admission remains separately binding. At this September 5
qualification, the capture host was outside its 00:30-09:00 ad-hoc heavy-work
window. The old 36 GiB hashing proposal has expired and binds spent v1; it is
not executable authority for v2 even though the later capacity reading exceeds
36 GiB. Any production hashing or subsequent heavy step needs fresh admission
under the owning host policy; workstation fixture success changes neither the
time nor reserve gate.

## 2026-09-05 10:09: signed-in v2 fails at rclone copy

The user's actual `real-pilot-clob-console-20260713-v2` attempt failed at
`2026-09-05T14:09:51.448222Z` (10:09 Toronto) with
`rclone_create_only_copy_failed`. This supersedes the pending-v2 status in the
earlier qualification entry without changing its successful 53-test result.
The raw 1,753-byte receipt is retained production-locally at
`scratch/handoffs/real-pilot-clob-console-20260713-v2.receipt.json`, file SHA-256
`570989B37B84E5EB65EA889500D8EAA97E9C7903594221160A20260E9B19A0F9`;
the workstation copy matches. Its validated receipt self-hash is
`6f6c28b97ea02a6c66f507435cad0e90681ff3b257eeb476027f56d8b2a45434`,
verified together with its exact source binding in the admitted workstation
suite below. Retain the raw evidence unchanged.

The tool checkout remained clean at repair
`aea427fb7faf0b5fd67b8893b62b11fe649e71ea`, tree
`97adb242ee1af173ff26938a1eafe377d408aedd`, with the source SHA-256 recorded
above unchanged. The receipt reports PASS for encrypted configuration and
local crypt-root checks, supporting the inference that the real provisioned
credential loaded through DPAPI in this signed-in session. Initial source hash,
compression and destination-absence checks also passed. These checks do not
qualify the failed copy, cryptcheck or restore.

The retained encrypted-object state is `creation_state_ambiguous_retained`.
A bounded metadata read found the exact target ciphertext absent and only the
prior smoke directory in the ciphertext root. That observation neither clears
the spent namespace nor replaces copy/cryptcheck/restore evidence. Preserve
both v1 and v2 and all their outputs. No uploaded archive, restore proof,
deletion or reclaimed bytes is established.

Code review found `RCLONE_PARTIAL_SUFFIX = ".partial.cold-stage"` in the exact
published source. The literal is **19 ASCII bytes**, independently counted,
and exceeds [rclone's 16-byte suffix limit](https://rclone.org/docs/#partial-suffix-string).
The independent stacked repair `codex/archive-rclone-suffix-20260905` is
published at `5e9b60e9d9f346346c0d8ef7de751fc43130d402`, tree
`763479ae1cc43680e85686d5261e7ea47805a21d`, in
[PR 22](https://github.com/michaelbooth1/weather/pull/22). It uses the 13-byte
`.partial.cold`, retains refusal of both raw partial suffixes and preserves all
copy safety flags. Five real-rclone synthetic cases prove the legacy rejection,
fresh copy plus cryptcheck success, unchanged ciphertext for identical and
changed destination collisions, and empty-source refusal. The combined admitted
workstation run passed 58 checks in 3.57 seconds; only the two signed-in DPAPI
positive cases were deselected in SSH. Their implementation is unchanged from
the earlier 53-pass signed-in qualification. All three changed Python files
compiled, the documentation audit passed, and independent source review found
no actionable issues.

The retained `scratch/handoffs/archive-suffix-native-verification-20260905.xml`
has SHA-256 `6DA775E9ECD039A8DB659ECFA1CB3EA93FFD4770CA510880EF8BA1C7D11B5085`.
Source SHA-256 is `3813C67C5897982BA7FDC590859826236BFDAB77EF626503133825BA54B188BE`;
unit-test SHA-256 is `64B6BF9ADDAA3E264E2EC8AB0450E08E6FA97E7488C842070DE7818602BD9118`;
native-rclone-test SHA-256 is `4CAF21B798EF62786454C62548C0683E5F41FD95FCE75563E9FA48B5E7B03EF2`.
The suite also validates v2's receipt self-hash and old source identity, plus the
newly loaded module path and repository root. These proofs do not rehabilitate
the spent real attempt or establish real ciphertext.

A separate clean workstation checkout at
`C:/Users/Michael/Documents/github/weather-archive-stage-v3-20260905` binds
that exact published repair. The new signed-in runner
`C:/Users/Michael/Documents/Codex/handoffs/run-archive-real-stage-v3-20260905.ps1`
requires the full 59-case native suite with zero failures/errors/skips before
claiming `real-pilot-clob-console-20260713-v3`, and rechecks source/Git identity
after the fixtures. Four admitted smoke checks passed: PowerShell parsing,
actual metadata/ACL preflight, fresh-process import binding and exact 59-case
collection. The real v3 result is pending. This runner has no upload, restore,
production hashing or deletion path. The next step is the signed-in result,
followed by exact receipt/manifest review before any encrypted cloud transfer.
Independent runner review found no actionable issues. Runner SHA-256 is
`BF9344E59A5073B9F97281980F51D2B28C517FD153F5453FC7CB4213227BD3B9`,
confirmed equal locally and on the workstation. The retained smoke report
`scratch/handoffs/archive-v3-runner-smoke-20260905.xml` has SHA-256
`568F2E73F804417F57A3937FD2D2B5160909E023646C486B107A84735DA4010C`.

The prior qualification documentation's
[PR 21 CI](https://github.com/michaelbooth1/weather/actions/runs/33970328290)
passed. It has not been adopted on production, whose master remains
`6714b77d8bb57fa36b4d2dd33675cab971ef2432`; the two generated-config changes
remain preserved. Source publication and passing CI do not close storage
qualification, admission, restore or whole-W11 acceptance.

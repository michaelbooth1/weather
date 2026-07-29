# 325. Tiered Data Retention And Verified Archive Offload [OPEN 2026-07-21 - FIRST WARM FAMILY BUILT; NO APPLY OR DELETION AUTHORIZED]

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
replacing a reviewed plain peer with byte-identical compressed evidence does
not discard decompressed evidence, so it needs no archive verification, prune
ledger, or `/MIR` topology change. It does physically unlink that exact plain
representation, however, so apply still requires explicit operator approval
and durable checkpoints. It should take retained snapshots to roughly
1.3 GB/day and is a large one-time retroactive reclaim. The sync split still
gates deletion of the retained canonical representation and remains the
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

## 2026-07-29 workstation build: first warm family only

The build-only result in
[the workstation Item 325 report](../agent-report-2026-07-29-workstation-item-325-warm-tier.md)
confirms the six-family payoff order on 84 market-days and inventories 130
role-tagged content, delegated, discovery, manifest, and writer surfaces.
Canonical `order_books.jsonl` is the only newly eligible warm-compression
family. Its 23 surfaces are covered by a transparent plain/gzip boundary;
gzip-only reads work, identical transitional pairs are verified, and a
malformed or divergent pair fails before rows are returned.

The other five families remain explicitly blocked:

| Family | Inventoried surfaces | Blocking plain-file consumers |
| --- | ---: | --- |
| `clob_tokens.jsonl` | 11 | CLOB coverage and data-layer audits |
| `replay_inputs.jsonl` | 40 | Replay/snapshot tracking and pooled-candidate replay |
| `variant_predictions.jsonl` | 13 | Density parity, residual corpus, and captured-input parity |
| `order_books_summary.csv` | 28 | Latest inputs, microstructure features, and MM scoring |
| `clob_tokens.csv` | 15 | Latest inputs, MM support, and taker-strategy evaluation |

The hot-window requirement is now code-derived. A valid production
point-in-time selection uses 14 contiguous dates whose latest target may be at
most 7 days old, so its oldest possible target is 20 days old and the first
safe warm age is 21 days. The default 30-day hot window adds 9 recovery days.

The planner/apply build is manual, fail-closed, deterministic (`gzip mtime=0`),
exact-manifest bound, and receipt/checksum protected. Apply would physically
remove only the verified plain peer after a durable retained-gzip checkpoint
and immediate parity recheck. No real-data plan was applied; no real file was
compressed, removed, moved, or rewritten. No archive, mirror, scheduler, or
capture setting changed, and no broader scope checkbox is complete.

Acceptance:

- Free space on the production volume trends flat or upward across a full week
  of normal capture, with no manual intervention.
- Every deletion is traceable to a verified archive copy and a ledger entry, and
  a restore drill has been executed and recorded.
- Capture, the daily chain, and barrier resumes complete unchanged for every
  date inside the hot window, and any older date can be restored on demand.

# Verified Cold-Archive Foundation

`weather.operations.verified_cold_archive` defines the create-only archive,
verification, restore-drill, and cleanup-plan contracts for one sealed market-day
folder. The current command surface is deliberately restricted to marked
synthetic fixture roots. It does not authorize a production plan, transfer, or
cleanup, and it contains no source-delete executor.

This contract complements the existing event-day manifest and storage-class
contracts. It preserves every selected source byte in one deterministic
`tar.gz` object, rather than replacing canonical evidence with the Parquet
analysis projection produced by `closed_market_day_archive`.

## Fixture-only boundary

Every command requires all of these conditions:

- the root directory name starts with `vca-`;
- the root contains `.verified-cold-archive-fixture-root.json` with exactly
  `{"allow_real_data": false, "purpose": "synthetic_tmp_path_fixture_only"}`;
- the root, source, destination, restore tree, and receipts contain no symlink,
  junction, mount-point reparse, or path escape; and
- the root and all writable paths are outside, and do not contain, the
  repository `data/` tree.

The supported source shape is exactly
`snapshots/<recognized-market-day-event-slug>`. Tests construct it only under
pytest `tmp_path`. Operators must not add the fixture marker to production or a
real corpus to bypass this boundary.

## Selection contract

`plan` handles one market-day folder at a time. It reads without changing the
source and emits `verified_cold_archive_plan_v0.1` through a create-only output.
The plan has no generated timestamp, and its file inventory uses sorted relative
paths, byte sizes, and SHA-256 identities so repeated plans over unchanged input
are byte-for-byte deterministic.

The minimum and default hot window are both 30 days. A day is eligible only when
its target date is strictly older than the selected window. The planner also
requires:

- a current, self-hash-valid, fully validating `event_day_manifest_v0.1`;
- no external shared-payload dependencies in that manifest;
- a source-bound `verified_cold_archive_selection_proof_v0.1` outside the
  market-day folder;
- exact PASS evidence for market-day closure and final settlement;
- exact PASS evidence that barriers, queues, and point-in-time windows have no
  open reference to the day;
- a non-link regular-file inventory that remains stable across stat, hash, and
  re-enumeration checks;
- no writer-lock file; and
- exact uncompressed byte parity whenever both a plain file and its `.gz`
  representation exist.

Every selection-proof check must name at least one evidence file by fixture-root
relative path, size, and SHA-256. Missing, unreadable, stale, duplicated, or
re-hashed but semantically unsafe plans and proofs fail closed. A split day whose
representations contain disjoint material is not eligible.

## Archive and manifest contract

`build` accepts only a valid PASS plan made by the same clean Git commit and
tree. It revalidates the event-day manifest, selection evidence, file inventory,
split representations, and filesystem identities before and during reads. Any
source drift leaves the source untouched and blocks publication.

The archive format identifier is `deterministic_tar_gzip_v0.1`. Members are
sorted relative paths with normalized mode, owner, and modification metadata;
gzip metadata is also normalized. The result is one object per market day, plus
one JSON sidecar, so later cloud transport does not create millions of remote
objects.

Publication is create-only. An existing archive object, manifest, receipt, plan,
or cleanup-plan path is a collision and is never overwritten. The archive is
published before its sidecar; if sidecar creation fails, the immutable archive
remains an unverified orphan that requires operator disposition. It is never
silently adopted or replaced.

`verified_cold_archive_manifest_v0.1` contains:

- the relative source folder, event slug, market id, target date, event-day
  manifest identity, and source-plan hash;
- every archived relative path with SHA-256 and size, plus total file count and
  bytes;
- the complete selection contract and evidence identities;
- archive format, object key, SHA-256, and size;
- the clean Git commit, tree, branch, tool, and format identity; and
- a canonical manifest self-hash and `append_only: true` assertion.

## Destination verification and transport boundary

`verify` reads an existing object and sidecar. It validates their schemas and
self-hashes, requires exact archive size and SHA-256, streams every archive
member, and proves exact sorted path/size/SHA-256 parity with the manifest. It
rejects duplicate or unexpected members, links, special members, traversal,
missing members, truncation, and destination drift. A requested
`verified_cold_archive_verification_receipt_v0.1` is written create-only.

Cloud transport is a separate, still-unimplemented adapter and preflight. The
eventual off-site adapter is `rclone` to Google Drive through an `rclone crypt`
remote, followed by `rclone cryptcheck` or an equivalently verified encrypted
transport. It must preserve append-only copy semantics equivalent to
`robocopy /E`, and must never expose `/MIR`, `rclone sync`, remote deletion, or
overwrite behavior. Archive-format code must not import or configure Drive or
`rclone`.

Credentials, crypt passphrases, OAuth setup, remote creation, and recovery-key
custody are operator-owned and absent from this repository and command surface.
Raw capture may contain sensitive request material, including request URLs,
headers, or provider secrets. It must never be uploaded to a third-party target
without encryption, even when a content scan appears clean.

## Restore drill

`restore` first runs the complete destination verifier. Only then does it create
one new scratch directory below the marked fixture root. It never writes restored
bytes under `data/`, an existing directory, the archive destination, or the
receipt location.

Extraction accepts regular files only. Each normalized relative path is opened
create-only, each stream is hashed as it is written and fsynced, and the complete
restored tree is inventoried again. Success requires exact ordered manifest
parity. The durable `verified_cold_archive_restore_receipt_v0.1` binds the
manifest and archive identities, complete restored inventory, totals, scratch
root, internal verification receipt hash, timestamp, and tool/code identity.

## Cleanup-plan boundary

`cleanup-plan` re-verifies the archive, validates the restore receipt self-hash
and exact archive/manifest/file parity, re-inventories the restored tree, and
proves the source is still byte-identical. Only then does it extend the existing
`cleanup_manifest_v0.1` contract with each candidate's exact absolute
`source_path`, archive identity, restore identity, selection proofs, clean tool
identity, and a `cleanup_plan_hash`.

The generated review block starts unapproved and `executor_present` is false.
There is no apply, unlink, prune, directory removal, or retention-period change
in this foundation. A cleanup plan is review evidence only.

## Fixture command sequence

Run only against a synthetic, marked fixture whose output directories already
exist. Every JSON output path is create-only.

```powershell
python -m weather.operations.verified_cold_archive plan --fixture-root <vca-fixture> --source-folder <vca-fixture\snapshots\event-slug> --selection-proof <vca-fixture\review\selection-proof.json> --as-of-date <YYYY-MM-DD> --output <vca-fixture\review\plan.json>
python -m weather.operations.verified_cold_archive build --fixture-root <vca-fixture> --plan <vca-fixture\review\plan.json> --destination-root <vca-fixture\archive>
python -m weather.operations.verified_cold_archive verify --fixture-root <vca-fixture> --destination-root <vca-fixture\archive> --manifest <vca-fixture\archive\object.tar.gz.manifest.json> --receipt <vca-fixture\review\verification-receipt.json>
python -m weather.operations.verified_cold_archive restore --fixture-root <vca-fixture> --destination-root <vca-fixture\archive> --manifest <vca-fixture\archive\object.tar.gz.manifest.json> --scratch-root <vca-fixture\restore-drill> --receipt <vca-fixture\review\restore-receipt.json>
python -m weather.operations.verified_cold_archive cleanup-plan --fixture-root <vca-fixture> --destination-root <vca-fixture\archive> --manifest <vca-fixture\archive\object.tar.gz.manifest.json> --restore-receipt <vca-fixture\review\restore-receipt.json> --output <vca-fixture\review\cleanup-manifest.json>
```

Production enablement remains a separate reviewed mission. It must supply a
production selection-proof adapter, prove all current shared dependencies are
self-contained or included, implement and fixture-test the encrypted transport
preflight, perform an operator-owned restore drill, split existing mirror
semantics, and add an independently reviewed deletion/ledger mechanism before
any local source byte can be reclaimed.

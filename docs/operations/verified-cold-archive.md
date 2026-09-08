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

Off-site cloud transport remains unimplemented. The eventual off-site adapter
is `rclone` to Google Drive through an `rclone crypt` remote, followed by
`rclone cryptcheck` or an equivalently verified encrypted transport. It must
preserve append-only copy semantics equivalent to `robocopy /E`, and must never
expose `/MIR`, `rclone sync`, remote deletion, or overwrite behavior.
Archive-format code must not import or configure Drive or `rclone`.

Credentials, crypt passphrases, OAuth setup, remote creation, and recovery-key
custody are operator-owned and absent from this repository and command surface.
Raw capture may contain sensitive request material, including request URLs,
headers, or provider secrets. It must never be uploaded to a third-party target
without encryption, even when a content scan appears clean.

## Provisional workstation encrypted staging

`weather.operations.workstation_cold_archive_stage` is a separate default-off
adapter for one already-rotated provisional mirror file. It does not change the
fixture-only boundary of `verified_cold_archive`, establish production source
identity, upload to Drive, restore an object, or authorize cleanup. It must run
as the exact module admitted under `-Kind weather_heavy` by
`scripts/ops/workstation_heavy.ps1`; the wrapper supplies the host-global mutex,
tracked workstation identity, and kill-on-close child-tree containment.

The CLI requires `--provisional-mirror-copy` plus explicit absolute
`--source-root`, `--source-file`, `--staging-root`, `--ciphertext-root`,
`--receipt-root`, `--rclone-config`, `--dpapi-secret`, and
`--rclone-executable` paths. It also requires the immutable `--archive-id`, the
local `--crypt-remote-name`, and operator-pinned `--source-size` and
`--source-mtime-utc`. The source is limited to 1 GiB, must be a regular
non-reparse file below the source root and outside the repository, and is read
without requesting an exclusive writer lock. All output roots must already
exist, be disjoint and non-reparse, and remain outside repository `data/`.

The named rclone remote must pass `rclone config encryption check`. A bounded
`rclone config redacted <remote>` inspection must then prove it is a `crypt`
remote whose wrapped `remote` is the exact absolute local ciphertext root;
named or cloud backing remotes fail before any destination probe or copy. The
DPAPI CurrentUser-protected config password is recovered only in process,
placed only in a private child `RCLONE_CONFIG_PASS`, never placed in argv or
output, and removed and zeroed as far as the runtime permits. Every other
ambient `RCLONE_*` override is excluded from the private child environment.

After the existing path/pin/tool checks and create-only receipt claim, DPAPI
recovery, encrypted-config validation, and local crypt-root binding run before
the source is opened or a plaintext staging directory is created. An encryption
preflight refusal records `source_initial_hash_stable=NOT_RUN`,
`deterministic_compression=NOT_RUN`, and `copy_not_attempted`. The failure still
spends its receipt namespace and retains the source; it cannot authorize a
retry. Successful preflight does not replace any later source, ciphertext, or
supporting-input integrity check.
After compression, the adapter compares config, DPAPI-file, and executable
identities to their admission pins before invoking the client again. It repeats
encrypted-config and local-root validation, brackets those checks with the same
identity comparison, and retains the final post-staging comparison. This closes
the long compression gap under the existing size/mtime/file-identity contract;
it does not claim immutable config handles across every child invocation.

The password file format is ASCII hexadecimal containing a native DPAPI blob
over UTF-16LE text, protected for the same Windows user with no optional
entropy. This is the Windows `ConvertFrom-SecureString` format when no `-Key`
or `-SecureKey` is supplied; keyed/AES exports and other encodings are not
accepted formats. The loader retains `CRYPTPROTECT_UI_FORBIDDEN` and never
falls back to a different user, encryption scope, key, or plaintext. See the
[PowerShell protection implementation](https://github.com/PowerShell/PowerShell/blob/master/src/System.Management.Automation/security/SecureStringHelper.cs).

When native recovery fails, the sanitized error and optional integer
`dpapi_winerror` field in a `FAIL_CLOSED` receipt retain the Windows last-error
code captured immediately after `CryptUnprotectData`. The existing receipt
version, error code, self-hash, and retention fields remain unchanged. Blob
bytes, plaintext, raw exception messages, and OS error descriptions are not
retained. A numeric error is a diagnostic, not proof of a wrong password,
corrupt blob, or changed principal; distinguish format compatibility from
current logon/profile access before deciding a repair. The
[Windows API contract](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata)
requires matching protection inputs. Failed attempts remain spent and retained;
diagnosis does not authorize secret reprovisioning or retry. Windows fixture
tests produce new synthetic DPAPI secrets with PowerShell and exercise actual
native recovery and refusal without reading provisioned archive credentials.

If a positive fixture fails in PowerShell `ConvertFrom-SecureString` before
the Python loader runs, that proves only that the session could not protect
a fresh synthetic fixture. It does not diagnose a retained real blob.
Keep the positive Windows fixtures required. Run the same unchanged fixtures
through the wrapper from the attending user's normal interactive workstation
session to distinguish a session limitation from a loader problem. Microsoft
[documents that key-authenticated SSH sessions lack associated user credentials](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement).
That makes logon context a diagnostic hypothesis, not a proven cause. The
ordinary Job helper inherits the launching token and supplies containment; it
does not create a credentialed logon. Do not change authentication, credential
scope, profile or key material, or skip/mock the positive tests to obtain PASS.

For each archive ID the adapter creates one normalized single-member
`archive.tar.gz`, with zero timestamps and owner IDs, empty owner names, mode
`0600`, and stable member name `payload`. Local paths are create-only. The
adapter proves the logical crypt destination and mapped ciphertext path absent,
rejects recognized retained staging partials, and invokes only bounded argument-array
`copy --immutable` and one-checker `cryptcheck` operations. An exact bounded
before/after local ciphertext inventory must contain one new regular file and
no removed or changed pre-existing file. Source size, timestamp, file identity,
and SHA-256 are checked before and after staging.

The temporary-copy suffix must fit rclone's
[16-byte limit](https://rclone.org/docs/#partial-suffix-string). The adapter uses
`.partial.cold` and retains refusal of physical filenames ending in the older
`.partial.cold-stage` suffix. Crypt can encrypt the entire temporary filename,
so a raw suffix scan is not a complete encrypted-partial detector. An occupied
logical archive namespace is always refused, and the inventory check preserves
all pre-existing ciphertext. Never reuse a failed attempt to test a repair.

The optional `tests/operations/test_workstation_cold_archive_rclone_native.py`
suite exercises the actual copy client against tiny temporary local crypt
fixtures. Set `WEATHER_TEST_RCLONE_EXECUTABLE` to an explicit installed rclone
binary and run it through the appropriate host admission wrapper. It uses no
provisioned credentials or cloud remote and checks successful copy/cryptcheck,
collision refusal, and the legacy invalid-suffix failure. The ordinary mock
suite alone cannot qualify installed-rclone compatibility.

Success writes create-only, self-hashed
`workstation_cold_archive_stage_manifest_v0.1` and
`workstation_cold_archive_stage_receipt_v0.1` evidence, with exact stable byte readback and self-hash validation before PASS.
An already-written receipt that fails readback is retained and never rewritten.
If staging fails after copy has been attempted, it retains every object and
writes a create-only `FAIL_CLOSED` receipt
whose encrypted-object state is verified, unverified, or explicitly ambiguous.
Every outcome permanently states `source_retained=true`,
`Drive_upload_performed=false`, `restore_performed=false`,
`production_identity_not_proved=true`, `cleanup_eligible=false`, and
`deletion_authorized=false`. No cleanup or delete executor exists.

Build the canonical UTF-8/base64 JSON argument array separately, then pass that
literal value to the wrapper in its fixed parameter order:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File <repo>\scripts\ops\workstation_heavy.ps1 -Kind weather_heavy -PythonPath <absolute-cpython.exe> -ArgumentsBase64 <canonical-base64-json-array> -RepoRoot <repo>
```

The decoded array begins with
`["-m","weather.operations.workstation_cold_archive_stage", ...]`. A real run
requires separate operator authorization and provisioned local paths and keys;
the build-and-test mission used only temporary fixtures and substituted child
behavior.

## Independent provisional workstation restore

`weather.operations.workstation_cold_archive_restore` verifies one independently
downloaded ciphertext object against the retained workstation staging manifest
and PASS receipt. It is admitted only as the explicit `weather_heavy` module
through `scripts/ops/workstation_heavy.ps1` under the existing workstation
identity, host mutex, and kill-on-close Job. It has no cloud client, production
mode, credential provisioner, or deletion executor.
The Codex host-load hook carries the same exact offline-module entry; direct
invocation remains subject to the capture-window and workstation-wrapper rules.

The controller separately supplies a create-only, self-hashed
`workstation_cold_archive_download_receipt_v0.1`. Required fields are `status`
(`PASS`), `archive_id`, `stage_manifest_hash`, `stage_receipt_hash`,
`controller_evidence`, `independent_download_performed`, and
`private_permissions_verified` (all three `true`), `drive` containing distinct
`root_folder_id`, `folder_id`, and `file_id`, `ciphertext` with `bytes` and
`sha256`, `downloaded_input` with an absolute `path` and the workstation regular
file identity (`device`, `inode`, `mode`, `bytes`, `mtime_ns`), and an aware UTC
`completed_at_utc`. `receipt_hash` uses the stage receipt's canonical JSON hash,
excluding the hash field itself. The controller must establish the exact Drive
object/private-parent evidence, perform a fresh independent cloud download,
and transfer it into the restricted workstation inbox before recording that
input identity. A local copy of the original staged ciphertext cannot establish
independent cloud recovery.

The verifier binds the two stage receipts, their tool identity and verification
checks, the explicit expected stage manifest/download receipt hashes, and the
downloaded file's identity and actual SHA-256. Drive provenance stays labeled
`controller_evidence_only`; local success does not claim that this module
queried Google Drive or independently audited those permissions.

All root directories must already exist and be disjoint, regular local paths
outside repository `data/`. The downloaded input must be outside original
source/staging/ciphertext roots and must not share the original ciphertext's
file identity. Config, DPAPI recovery, and the explicitly named local restore
crypt remote are checked before large file reads or plaintext outputs. The
config/executable/secret and other supporting file identities are rechecked
before each child; encryption and root binding are also repeated across long
local verification steps. This preserves the existing stat-identity scope and
does not claim immutable configuration handles.

Use a short fresh `--restore-id`, such as `v3-r1`. The mapped logical path is
`<restore-id>/<stage-archive-id>/archive.tar.gz`; its final two encrypted path
segments must equal the original manifest mapping. The new encrypted prefix
and plaintext attempt directory must both be absent. Windows ciphertext paths
are limited to fewer than 240 UTF-16 code units. The copied ciphertext remains
create-only and is checked byte-for-byte, then `cryptcheck` compares it with the
retained compressed archive. Bounded `copy --immutable --ignore-times
--error-on-no-transfer` decrypts the single file into the fresh output directory.
The client also requires that directory to be empty immediately before launching
the child; the native flags alone can accept an identical existing local output.
The normalized USTAR parser accepts one regular `payload`, with exact header,
size, hash and bounded zero footer. It does not process PAX/GNU extensions or
extract supplied archive paths. Compressed reads, decompression, hashes and
children share a one-hour deadline; byte bounds derive from the stage evidence.
Source and retained archive hashes are re-proved before and after restoration.

The wrapper's canonical argument array starts with
`["-m","weather.operations.workstation_cold_archive_restore", ...]` and requires
`--provisional-mirror-copy`, `--stage-manifest`, `--stage-manifest-hash`,
`--stage-receipt`, `--download-receipt`, `--download-receipt-hash`,
`--downloaded-ciphertext`, `--source-root`, `--source-file`, `--staging-root`,
`--staging-ciphertext-root`, `--retained-archive`, `--restore-ciphertext-root`,
`--restore-output-root`, `--receipt-root`, `--rclone-config`, `--dpapi-secret`,
`--rclone-executable`, `--crypt-remote-name`, and `--restore-id`. Paths and hashes
come from the reviewed handoff, never a directory-wide selection or guessed ID.

The create-only `workstation_cold_archive_restore_receipt_v0.1` records local
checks and upstream identities. A claimed receipt namespace remains spent on
failure, and every created object is retained. PASS sets `restore_performed`
true while permanently retaining `source_retained=true`,
`production_identity_not_proved=true`, `cleanup_eligible=false`, and
`deletion_authorized=false`. Production source identity and an exact deletion
proposal remain separate work with separate authority. The restore tests use
tiny synthetic fixtures; the optional native case shares the explicit
`WEATHER_TEST_RCLONE_EXECUTABLE` opt-in and verifies the installed rclone's
decrypt-copy behavior and payload parity.

## Fixture restore drill

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
self-contained or included, connect reviewed production selection to encrypted
off-site transport, perform an operator-owned restore drill, split existing
mirror semantics, and add an independently reviewed deletion/ledger mechanism
before any local source byte can be reclaimed. The provisional staging adapter
cannot be upgraded into authoritative production mode by a runtime flag.

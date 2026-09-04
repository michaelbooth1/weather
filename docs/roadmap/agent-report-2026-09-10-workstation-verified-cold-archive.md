# Workstation verified cold-archive handback

Mission branch:
`codex/workstation-verified-cold-archive-2026-09-101a`

Status: **COMPLETE FOR THE AUTHORIZED BUILD-AND-TEST SCOPE.** The branch adds a
fixture-only, fail-closed foundation. It does not authorize or perform a
production plan, transfer, restore, cleanup, or deletion.

## Git identity

| Role | Commit | Tree |
| --- | --- | --- |
| Pinned source (`origin/master` when the isolated branch was created) | `e31720cc92bafe4c8ebf6d1cb16ae1f26194ea32` | `731c66ea52d322c79e8e87899cbb78406d7415f5` |
| Implementation and tests | `c14b50ec2a93ad9c08624383e9b212156a2956c6` | `314c4a0a6c645aab7f9d0552a0f22c6a2d75526c` |
| Final report-only successor | See the final handback accompanying this commit | See the final handback accompanying this commit |

Git hashes cannot be embedded in the content that determines those same
hashes. This report-only commit therefore records its exact parent and its sole
intended delta; the final handback reports the resulting commit and tree IDs
after Git creates them. The report-only commit changes only this file.

The branch was based directly on the pinned source: before implementation,
`HEAD`, `HEAD^{tree}`, and the merge base with the recorded source were exactly
the source identities above.

## Delivered foundation

`weather.operations.verified_cold_archive` exposes five commands through the
canonical module surface:

1. `plan` selects exactly one recognized market-day folder and writes a
   create-only deterministic plan.
2. `build` revalidates that plan and creates one deterministic `tar.gz` object
   plus one machine-readable sidecar without overwriting either path.
3. `verify` proves exact object and member parity and can write a create-only
   verification receipt.
4. `restore` verifies first, extracts regular files into a new scratch tree,
   rehashes the result, and writes a durable restore receipt.
5. `cleanup-plan` re-verifies the archive, receipt, restored tree, and source
   before naming exact source paths in an unapproved review manifest.

The current surface accepts only a marked `vca-*` synthetic fixture root and
rejects any overlap with repository `data/`. No production-root adapter,
transport adapter, or delete executor exists.

## Registered schemas and format

| Registry name | Version or format identity | Purpose |
| --- | --- | --- |
| `verified_cold_archive_format` | `deterministic_tar_gzip_v0.1` | Normalized tar/gzip object bytes |
| `verified_cold_archive_selection_proof` | `verified_cold_archive_selection_proof_v0.1` | Source-bound closure, settlement, and open-reference evidence |
| `verified_cold_archive_plan` | `verified_cold_archive_plan_v0.1` | Deterministic one-day selection and source inventory |
| `verified_cold_archive_manifest` | `verified_cold_archive_manifest_v0.1` | Archive, source, selection, file, total, and tool identities |
| `verified_cold_archive_verification_receipt` | `verified_cold_archive_verification_receipt_v0.1` | Destination object/member parity proof |
| `verified_cold_archive_restore_receipt` | `verified_cold_archive_restore_receipt_v0.1` | Exact restored-tree parity proof |

The cleanup-plan output deliberately reuses and extends the established
`cleanup_manifest_v0.1` helper contract instead of adding a parallel cleanup
schema.

## Safety invariants

- The minimum and default hot windows are 30 days, and the target date must be
  strictly older than the selected window.
- Selection requires a current self-hash-valid event-day manifest with complete
  validation and no external shared-payload dependency.
- A separately hashed proof must bind the exact folder, slug, date, and
  event-day manifest. Its exact required checks prove closure, final
  settlement, and empty barrier, queue, and point-in-time reference sets. Every
  check carries at least one current path/size/SHA-256 evidence identity.
- Source enumeration accepts only stable regular non-link files. It rejects
  symlinks, junctions/reparse points, special members, writer locks, path
  escape, manifest drift, inventory drift, and files that change during hash or
  archive reads.
- Plain/`.gz` split representations are eligible only when decompression proves
  exact byte identity. Disjoint halves fail closed.
- Plans contain sorted stable relative path/size/SHA-256 identities. The
  builder retains volatile filesystem identities only in memory for race
  detection, so repeated unchanged plans and archive objects are deterministic.
- Archive publication uses create-only destination semantics. A pre-existing
  object, sidecar, plan, or receipt is a collision. Publication never silently
  adopts, overwrites, or mirrors an object.
- Tar and gzip metadata are normalized. The sidecar records every source file,
  total count/bytes, archive SHA-256/size, selection proofs, and clean Git
  commit/tree/tool identity.
- Verification rejects sidecar/object-name mismatch, outer-object drift,
  traversal, links, special or duplicate members, unexpected or missing
  members, truncation, order drift, size drift, and content drift.
- Restore verifies the object before creating scratch space, opens each member
  create-only, fsyncs and rehashes it, and re-inventories the complete tree.
  Restored bytes cannot enter `data/`, an existing root, the archive
  destination, or the source tree.
- Cleanup-plan generation requires exact archive identity, a self-hash-valid
  successful restore receipt, current restored-tree parity, and unchanged
  source bytes. Its operator review starts unapproved and
  `executor_present` is false.
- Cloud transport remains outside the archive-format module. The operating
  contract requires eventual `rclone` Drive transport through a `crypt` remote
  with `cryptcheck` or an equivalent verified encrypted adapter,
  append-only `/E`-equivalent copy semantics, and never `/MIR` or destructive
  `rclone sync`.
- Raw capture may include sensitive request URLs, headers, or provider secrets
  and must never be uploaded unencrypted. Credentials, OAuth, remote setup, and
  recovery keys remain operator-owned and absent.

## Changed paths

Implementation commit:

- `docs/operations/README.md`
- `docs/operations/data-retention-policy.md`
- `docs/operations/verified-cold-archive.md`
- `docs/roadmap/ROADMAP.md`
- `docs/roadmap/active-backlog.md`
- `docs/roadmap/items/item-325-tiered-data-retention-and-verified-archive-offload.md`
- `src/weather/operations/verified_cold_archive.py`
- `src/weather/schema_registry_data.py`
- `tests/operations/test_verified_cold_archive.py`

Final report-only successor:

- `docs/roadmap/agent-report-2026-09-10-workstation-verified-cold-archive.md`

No live-loop module, `config/storage_pressure.json`, scheduling surface,
capture default, retention period, current reader, transport configuration, or
PowerShell file changed.

## Verification

| Gate | Literal result |
| --- | --- |
| Focused cold-archive adversarial suite | `26 passed in 3.30s` |
| Combined archive, schema, agent-doc, and roadmap focused suite | `52 passed in 6.38s` |
| Strict schema audit | `registered=627 discovered=1050 unregistered_versions=0 excluded_versions=16` |
| `compileall -q app src tests` through `workstation_heavy.ps1` | PASS, exit 0 |
| Changed PowerShell AST parsing | `changed_ps1_count=0`; `PowerShell AST: NOT_APPLICABLE` |
| Agent-document audit after adding this report | `Agent docs audit: PASS (18 agent files, 832 Markdown files)` |
| Roadmap generation | `Roadmap backlog: OK` |
| Roadmap generated-view check | `Roadmap backlog: OK (generated report matches sources)` |
| Implementation staged `git diff --check` | PASS, exit 0 |
| Canonical workstation full suite on implementation commit | `61 failed, 4382 passed, 18 skipped, 13 warnings in 1873.70s (0:31:13)` |
| Pinned-source control on the exact six failing files | `61 failed, 109 passed in 639.69s (0:10:39)` |

Every full-suite failure reproduced at the unchanged pinned source with the
same test list:

- 1 live-SDK overlay path-key case mismatch;
- 13 experiment-executor Windows `MAX_PATH` failures;
- 44 production-baseline reconciler execution failures in nested synthetic
  worktrees;
- 1 replay-cache fixture path-case mismatch;
- 1 point-in-time preselection fixture path-case mismatch; and
- 1 registration rendering fixture path-case mismatch.

All 26 new archive tests passed inside the canonical full run. The source
control used the same Python executable and the source worktree's own
`scripts/ops/workstation_heavy.ps1`; it contained none of this mission's code.
Its detached worktree was removed after the comparison.

The focused tests cover deterministic plans and objects, stable manifest
content, create-only collisions, source drift before and during reads, absent
proof, incomplete finalization, unsafe hot windows, active/unsettled state,
open barriers/queues/windows, path escape, reparse points, split mismatch,
manifest tampering including re-hashed unsafe semantics, destination drift,
truncated archives, traversal, links, duplicate members, restore mismatch,
successful exact restore, cleanup receipt/archive/source/restore drift, fixture
markers, `data/` overlap, and schema registration. All fixtures use only
pytest `tmp_path`.

## Roll verdict

The required script was run against the exact branch. Its Scheduler lookup was
shadowed to return no task because this mission expressly prohibits Scheduler
access; no manual roll classification replaced the script. Literal output and
exit code:

```text
UNDECIDABLE: no live closure evidence
  missing closure evidence: data\snapshots\loop_supervisor_status.json
  missing closure evidence: data\snapshots\clob_loop_supervisor_status.json
  missing closure evidence: data\snapshots\observation_trigger_supervisor_status.json
  missing closure evidence: data\snapshots\clob_enrichment_status.json
```

Exit code: `1`.

## Remaining production work

1. Build and independently review a production selection-proof adapter against
   the authoritative finalization, settlement, barrier, queue, and
   point-in-time sources. Do not weaken a missing proof into eligibility.
2. Make each selected event-day manifest current and self-contained. A shared
   payload dependency remains a blocker until exact included bytes and restore
   evidence prove completeness.
3. Add a separately reviewed production-root boundary and encrypted transport
   adapter. Operators must configure Drive, `rclone crypt`, OAuth, and key
   custody outside Git; transport must be create-only and must run
   `cryptcheck` or an equivalent byte-verification gate.
4. Separate the disaster-recovery mirror from the append-only archive. Preserve
   `/E`-equivalent copy semantics for archive publication and never use `/MIR`
   or `rclone sync` on the archive target.
5. Run a reviewed production dry run and capacity/admission plan, publish one
   sealed day, verify the encrypted destination, and complete an operator-owned
   restore drill into an approved scratch location outside `data/`.
6. Review the resulting cleanup manifest. Design and authorize a separate
   prune ledger and delete executor in a later mission; none exists here.

No production source byte may be reclaimed until all six steps are complete.

## Prohibited-actions audit

- Production host or production share accessed: **no**.
- Scheduler accessed: **no**; the roll script's lookup was locally shadowed.
- Credentials, OAuth, device code, browser flow, or GitHub authentication
  inspected or requested: **no**.
- Provider, exchange, outcome, or Google Drive surface accessed: **no**.
- Real corpus, mirror, archive, or production file uploaded, moved, compressed,
  mutated, restored, or deleted: **no**.
- Bytes restored into repository `data/`: **no**.
- Real cleanup, unlink, prune, directory-removal, or delete executor added or
  run: **no**.
- Synthetic archive and restore operations: **pytest `tmp_path` only**.
- Networked cloud transport or upload attempted: **no**.

The roadmap generator wrote its ordinary ignored JSON report under this
isolated worktree's `data/backtest`; it was generated repository metadata, not
corpus input and was never read as evidence, archived, restored, or committed.

## Publication handoff

The initial branch push failed before implementation because interactive
GitHub authorization was unavailable. Work continued under the owner's
transfer instruction. The one permitted final noninteractive push attempt must
occur after the report-only commit; its literal result and the exact final
commit/tree are recorded in the accompanying final handback. If credentials
remain absent, publication status is `PUSH_DEFERRED_TO_PRODUCTION`, and the
production owner can transfer this local branch through the already-authorized
host-to-host Git-bundle path and publish it with production's existing GitHub
authorization.

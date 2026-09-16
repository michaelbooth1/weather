# Dated capacity recovery exception

This is an isolated successor to the unadopted archive source `021cd6d387ce2c76e240b00cff8f2da73fd5231e` (PR 67). It grants no production merge or live authority.

The September 15 owner approval permits the exact 1,066-file selection already bound by the archive plan, unencrypted upload to the existing private Drive folder, and removal only through the existing independent-download, member verification and pinned exact-source reclaim gates. The historical upload refusal remains evidence; its precise scope is superseded by the new hash-bound approval.

## Disk admission

`production_cold_archive_run.ps1` accepts paired `-DiskExceptionPath` and `-DiskExceptionSha256` arguments. The bounded record must bind the clean source tip, current capture installation, production root, exact plan and selection, and the post-denial owner approval. It expires at 09:00 Toronto on September 16, 2026.

The lower reserve is 25 GiB, plus 2 GiB of bounded job output and 300 MiB for five minutes of capture growth at 1 MiB/s. Existing archive chunks remain at most 1 GiB; the writer independently reserves and caps its worst-case output. Ordinary 50 GiB admission resumes when its full output reservation fits. All capture, memory, shared-lease, time-window, process-tree and teardown checks remain mandatory.

## Scheduled continuation

The fresh `plain-20260916-cap150b` campaign begins at 00:30 and ends absolutely at 04:42 Toronto. It preserves 04:45–06:45 for recurring tiering. It accepts all 56 exact chunks under new attempt identities, requires the new approval, and stops at actual free volume of 150,000,000,000 bytes or the window boundary. Queue completion alone is not the capacity target.

A metadata-only S4U preflight must pass before registration of the payload task. A failed or interrupted attempt is retained and must be reconciled before another attempt. Do not reuse an old progress ledger or spent staging identity. No late campaign is armed by this registrar. Further compress-and-retain work uses its existing independently qualified lane and must not overlap this campaign.

Update this document when the exception arguments, date, exact selection, reserve calculation or scheduled continuation contract changes.

## Compression prerequisite and continuation

If early free space is below 30 GiB, the archive campaign first runs the bounded retained-file night controller. Its dated plan reads the hash-bound local selection and uses only groups 7 onward: 8,754 untouched paths, with every held archive path excluded. A fresh complete inventory must still match each selected file's native identity, size and modification time. Already-compressed paths supply no new authority or credit. The first seven groups, including earlier interrupted attempts, remain excluded.

The early compression segment stops at the same 30 GiB of actual free volume required to start archiving; its overall target remains 150 GB. The late segment resumes the same verified ledger and targets 150 GB, with its existing 08:55 absolute stop. `register_storage_recovery_night.ps1 -OnlySegment late` arms only that continuation, avoiding a duplicate early trigger while the archive campaign owns the early conditional dispatch. Preflight registration still uses the full plan. Late qualification and audit must remain unarmed while the storage continuation owns the late window.

The metadata-only `prepare_capacity_recovery_20260916.ps1` producer creates fresh immutable baseline, compression-plan, disk-exception and archive-config records beneath the production handoff directory. It reads only the pinned existing selection and approval metadata, validates the capture installation and clean source tip, and does not register a task or touch any payload. Complete exact-source native checks before invoking it, then register and prove both metadata-only S4U preflights before arming the archive task and late-only compression continuation.

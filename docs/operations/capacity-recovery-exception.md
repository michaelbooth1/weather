# Dated capacity recovery exception

This is an isolated successor to the unadopted archive source `021cd6d387ce2c76e240b00cff8f2da73fd5231e` (PR 67). It grants no production merge or live authority.

The September 15 owner approval permits the exact 1,066-file selection already bound by the archive plan, unencrypted upload to the existing private Drive folder, and removal only through the existing independent-download, member verification and pinned exact-source reclaim gates. The historical upload refusal remains evidence; its precise scope is superseded by the new hash-bound approval.

## Disk admission

`production_cold_archive_run.ps1` accepts paired `-DiskExceptionPath` and `-DiskExceptionSha256` arguments. The bounded record must bind the clean source tip, current capture installation, production root, exact plan and selection, and the post-denial owner approval. It expires at 09:00 Toronto on September 16, 2026.

The lower reserve is 25 GiB, plus 2 GiB of bounded job output and 300 MiB for five minutes of capture growth at 1 MiB/s. Existing archive chunks remain at most 1 GiB; the writer independently reserves and caps its worst-case output. Ordinary 50 GiB admission resumes when its full output reservation fits. All capture, memory, shared-lease, time-window, process-tree and teardown checks remain mandatory.

## Scheduled continuation

The fresh `plain-20260916-cap150` campaign begins at 00:30 and ends absolutely at 04:42 Toronto. It preserves 04:45–06:45 for recurring tiering. It accepts all 56 exact chunks under new attempt identities, requires the new approval, and stops at actual free volume of 150,000,000,000 bytes or the window boundary. Queue completion alone is not the capacity target.

A metadata-only S4U preflight must pass before registration of the payload task. A failed or interrupted attempt is retained and must be reconciled before another attempt. Do not reuse an old progress ledger or spent staging identity. No late campaign is armed by this registrar. Further compress-and-retain work uses its existing independently qualified lane and must not overlap this campaign.

Update this document when the exception arguments, date, exact selection, reserve calculation or scheduled continuation contract changes.

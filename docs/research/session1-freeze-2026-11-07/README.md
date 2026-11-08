# Session 1 evidence-validation freeze — design lock (2026-11-07)

> **SUCCESSOR LOCK, 2026-11-08: [`FREEZE-FINAL-v2.md`](FREEZE-FINAL-v2.md) supersedes `FREEZE-FINAL.md` in full
> from its publication on `origin/master`. It was published before any session-1 observation.**
>
> - **New Monday version (F0):** `57fe4ce1eeb14e7c0800d5eaecf65fc7eef638e1`. The LFC economic selection filters
>   are relaxed under the owner's 2026-11-07 directives;
>   [clarification F](../live-fill-calibration-clarification-F-2026-11-07.md) gives the details.
> - **New simulator/validator:** `728d60e396c574d5a363d2d680f48a71166a3077`, which changes recorder-pin identity
>   only.
> - The v1 bytes below are unchanged as the record. The v2 change list is at the top of v2, and the pin table in
>   "Bound builds" below is the v1 record.

**Published by the master (production capture host) on 2026-11-07 before any
Monday 2026-11-09 result exists.** Committing this directory to `master` is the
design lock that Rule 01 of the freeze requires. The SHA-256 values below
identify the locked text; the two files in this directory are byte-identical
copies of the workstation originals.

| File | SHA-256 |
| --- | --- |
| `FREEZE-FINAL.md` (full rules, decisions, closure table) | `c7dacf026997f5a6a2b984e3930ce837d941b3fd42514e29afc1df1f4fa92640` |
| `FREEZE-SHORT.md` (one-page owner summary) | `22f0c2b4d176f42684731c041b8009651ad0d3c3292bf85a5abdc40feb8b0f67` |
| `FREEZE-FINAL-v2.md` (successor lock, 2026-11-08; supersedes `FREEZE-FINAL.md` from its publication) | `5ecd79dac33195ed8f9b93711e41f4226d5082368ea961f036c36c074263ed69` |

## What this governs

Session 1 is the owner-started F0 maker session on Monday 2026-11-09. It is
**simulator-calibration evidence only**. It cannot qualify an edge or a
general simulator. The fixed NOT QUALIFIED categories are in Rule 28 of
`FREEZE-FINAL.md`.

The freeze governs validation only. It grants no launch permission, capital
approval, readiness, or order authority. No agent places, cancels, or signs
orders.

## Decisions recorded at lock

Under the owner's 2026-11-06 directive, technical defaults belong to the master:
"don't make it too rigid", and block only for:

- a budget overrun;
- an ambiguous restart or overlapping sessions;
- evidence loss.

The master recorded D3–D8 at 2026-11-07 08:02 America/Toronto:

- **D3:** the recommended tolerance schedule. Cash and net endpoints within 0.00001 pUSD; prediction within 0.01 pUSD.
- **D4:** raw conditional receipt economics. Cost reserves are diagnostics only; no charter change.
- **D5:** the existing approved F0 limits, unchanged. This is not a new approval.
- **D6:** evidenced wallet-paid costs only. Owner time is reported separately and unmonetized. The owner may override in plain chat before the lock.
- **D7:** named roles.
  - Custodian: the workstation Claude session.
  - Validation lead: the master Claude.
  - Independent reviewer: a fresh Codex gpt-6-astra task.
  - Recipient: the owner, who is also the only Monday operational viewer.
- **D8:** coverage floors only.

D1 and D2 were fixed earlier by the owner: the account is exclusive to session 1
for UTC 2026-11-09, with no manual trades.

## Bound builds

| Role | Commit |
| --- | --- |
| F0 executor (frozen pin) | `f531395522d0b0a37495185b2750164008fe586a` |
| Optional public-evidence sidecar | `55e2a0ff12ced1d128e962c09bf42b9e03008e6c` |
| Simulator / validator | `206664b6e91066e219c0e072f00c2d97ed3fb909` |

The sidecar is configured as follows:

- fees and metadata every 180 s;
- at most 2 public request starts per second;
- a hard end at 2026-11-10T00:45Z;
- a terminal stop, with no restart, on the first 429 or Retry-After.

A sidecar failure is a recorded evidence gap and never an F0 blocker.

## Provenance

- **Drafts:** T015 package P6, reviewed by Codex Astra (T021, FREEZE-WITH-EDITS), then revised as v2 (T019r1r1) and finalized (T019r1r1r1).
- **Workstation originals:** `C:\t\codex\T019\` (custodian copy).
- **Master's verification:** both hashes match, and the pins match the reviewed tips (sidecar: Astra T036r1 GO; simulator: Astra T035 RECHECK3 STAGE2-READY). The superseded 60-second fee setting no longer appears as a target.

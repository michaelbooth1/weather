# Mission 2026-09-83b — Part B: national bulletin reuse

**PARTIAL — design recorded before implementation; verification pending.**

Branch `codex/nbp-bulletin-reuse-20260921`, independent base `origin/master`
`e28530af67c7371fc7b2c08bbd0e26cfe72a28f9`. Part A is not an ancestor.
Section 3 decisions are accepted without reopening them. Production download
counts in the handoff are supplied facts, not workstation observations.

## B1 design, recorded before code (2026-09-21)

Choose a cross-pass request/cycle index, not scheduled prefetch. Capture already
knows both immutable identities; it can discover an earlier successful fetch
without a new scheduler, scope change, or required warm-up. The index copies the
existing successful fan-out receipt only after verifying the bulletin cycle and
all configured US station blocks, required TXN rows and terminal pressure rows.
Its key includes the completeness policy and station set. Reuse validates the
receipt identity and original timing, then hashes the CAS bytes and checks their
cycle. A new cycle has a new key. Missing/incomplete/error responses never enter
the index. Atomic create-only publication needs no additional claim or wait.
Index read/write/verification errors fall back to the existing pass fetch;
coordination errors fall back to the direct provider callback. A successful
download is not repeated just because publishing its index failed.

Existing columns suffice: `captured_at_utc` is this use, `fetched_at` and
request/response times remain the original network timestamps,
`single_fetch_reused=true`, `single_fetch_fetched=false`, and current
`single_fetch_scope` describe reuse. The reused result has no new coordinator
network event (zero count, `not_applicable`), rather than copying the old
coordinator's one download into a new scope. The index retains the original
receipt. The original capture owns its network attribution. Cycle age is use
time minus issue, never fetch time disguised as use time. No manifest schema or
writer change is required.

Memory remains bounded by the existing two-entry local fan-out. Completeness
scans one line at a time without making a national `splitlines()` list; the index
retains only a small receipt, never another decoded national response. Reuse
reads/verifies the same CAS bytes already used by existing cross-process
followers. It adds no background process or long-held lock.

## Verification and handback

Pending implementation, fixture probe, unchanged replay/migration/parity tests,
roll-verdict output and publication. No forecast candidate, fit, retirement,
re-score, outcome read, floor change, paid provider, credential, exchange call,
production write, Scheduler registration, capture restart or master merge.

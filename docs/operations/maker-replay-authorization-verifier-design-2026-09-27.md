# Maker replay owner-authorization verifier — 2026-09-27

**Status: decision-log signature check implemented and fixture-verified; full one-look admission still proposed.**
Owns the owner attestation format and the remaining scored-admission design. Read before enrolling a replay.
The [registration](../research/maker-replay-hurdles-preregistration-2026-09-27.md) owns the hurdles;
the [execution addendum](../research/maker-replay-execution-addendum-2026-09-27.md) freezes remaining configuration;
the [bundle contract](maker-replay-bundle.md) owns replay IO. No real-data approval is enrolled.

This revision follows the owner's instruction to use a DECISION_LOG row as the signature. It supersedes this note's
earlier detached-Ed25519 proposal. No signing key, crypto dependency or key enrollment is required. October 12 was
proposed by the agent and still awaits owner confirmation; neither publication nor fixtures supply that confirmation.

## Trust and signature row

The owner approves a row in the existing five-column table in [DECISION_LOG](DECISION_LOG.md). Append only after an
explicit owner decision on the final file bytes. Do not write a placeholder approval into the real log. The row is:

| Column | Required content |
| --- | --- |
| Date | UTC date of `signed_at`, canonical YYYY-MM-DD |
| Decision | Literal `APPROVE_MAKER_REPLAY` |
| Scope / expiry | Literal `offline replay only`; expiry is recorded in Source |
| Source | One inline-code JSON object with exactly the seven keys below; no pipe characters |
| Supersedes | Literal em dash `—`; a new authorization uses a new ID |

The Source object has `authorization_id` (1-80 ASCII letters/digits/underscore/hyphen), `owner`, `protocol_sha256`,
`addendum_sha256`, `signed_at` (UTC), `scoring_date` (YYYY-MM-DD America/Toronto), and `expires_at` (UTC, exclusive).
Both hashes are lowercase raw-byte SHA-256 of the final frozen Markdown files, including newlines. `owner` is the
exact independently reviewed owner identity. Pending names, dates or hashes are not an owner decision.

The execution JSON manifest retains the CLI's `--pre-registration` name for compatibility. Its `owner_decision`
object must equal the row's Source object exactly, and its top-level `owner` and `signed_at` must agree. The manifest
also carries the existing hurdles, policies, clusters, dates, market inventory, complete ReplayConfig and bootstrap
bindings. Its own raw-byte SHA-256 and owner must be independently enrolled through an owner-approved code review in
`replay.authorization.APPROVED_REGISTRATIONS`, which remains **empty**. A caller-supplied row, hash, Git author,
nonempty signature string or synthetic provenance cannot enroll authority. Hashes establish byte binding; authorship
comes from the owner decision/review process, not from a claim of cryptographic authentication.

To revoke, append a `REVOKE_MAKER_REPLAY` row whose Source object names the `authorization_id`; never remove the old
approval. The checker requires exactly one row for that ID and requires it to be APPROVE. A duplicate, revocation or
superseding row for the same ID therefore refuses. A successor gets a new ID and a newly reviewed manifest. Operators
must use the current reviewed log from the executing checkout, not an archived pre-revocation copy. This offline CLI
does not authenticate Git history or defend against an operator deliberately substituting stale trusted files.

## Implemented CLI check, before bundle IO

Comparison now additionally requires the explicit paths `--decision-log`, `--frozen-protocol`, and
`--execution-addendum`. Diagnostic mode rejects authorization flags and remains score-free. The CLI:

1. Rejects an unenrolled execution-manifest hash before any file IO.
2. Reads the bounded manifest using the existing redirected-path, changed-file and strict-JSON protections and
   verifies its raw hash, enrolled owner, required policy/cluster declarations and owner-decision object.
3. Requires `signed_at <= now < expires_at` and the confirmed America/Toronto scoring date to equal today's date.
   No early look is admitted; expiry equality refuses. Manifest and row signing timestamps must agree.
4. Reads the explicit DECISION_LOG, locates the unique row in its canonical five-column table, and checks its date,
   decision, offline purpose, Source object and supersession state. Duplicate JSON keys and ambiguous IDs refuse.
5. Reads and hashes both frozen files without newline normalization. Both must match the owner row. Each Markdown
   file and the manifest are capped at 64 KiB, the log at 256 KiB, the total at 448 KiB and five seconds. Failure
   returns nonzero before bundle loading or policy/scorer invocation.
6. Continues through the existing bounded bundle reader and exact scope/config/metric/bootstrap binding. The
   comparison report retains the execution-manifest hash and verified owner-decision object alongside all input hashes.

The tests use a fictional log and monkeypatched approval table, never a real log row or production enrollment.
Old free-form `signature` strings no longer satisfy the gate. There is no runtime enrollment command or bypass flag.

## Remaining one-look execution gates — must precede real enrollment

The row check is necessary but does not implement every gate in this prospective design. In particular, it is not a
durable consumed-attempt registry or a combined economic/pull-hurdle evaluator. **Keep real enrollment empty until
all of the following land and receive owner review**, even if a row has been signed:

- Strictly validate the complete execution-manifest schema, including exact executable source identities, every
  input/stream/plugin/settlement hash, sorted market/condition inventory and declared intervals. Require the fixed
  14 closed quote dates and typed settlement-only date; the latter has no active minutes or quote/date clusters.
  Enforce the addendum's complete field values and independently recomputed calibration recipe before scoring.
- Atomically reserve a create-only, authorization-ID attempt receipt before the first policy/scorer call. Mark it
  consumed before exposing scores. Partial/failing scored attempts remain consumed across output directories.
  Recovery needs a new reviewed authorization disclosing every previous read; an ordinary rerun is not allowed.
- Evaluate the registration's full conjunction: conservative k=1 date and crossed lower bounds strictly above zero
  against both baselines; >=14 dates admitted and >=10 dates/markets effectively retained; mandatory 100 valid
  replicates; matched, identified pull point ratio >=2; both fill bounds and k sensitivities/report fields present.
  The implemented pull endpoint reports its own result only. Missing gates cannot produce REPLAY_HURDLES_MET.
- Write an immutable verification/attempt receipt with protocol/addendum/manifest/input/config/source digests,
  authorization ID, verification time and gate verdicts. Keep time-bearing receipts separate from deterministic
  comparison reports; preserve partial output as incomplete. Revalidate trusted files at the execution boundary.

Libraries remain pure tools rather than a security sandbox. Host admission is independent; the heavy-module
allowlist still does not permit this real-data CLI. This change authorizes no guard changes, data reads or live work.

## Focused acceptance

Fixtures cover a valid reviewed log path, unknown hash/old signature, absent and duplicate rows, revocation,
owner/purpose/hash changes, raw-byte newline changes, duplicate JSON keys, wrong local scoring date and expiry.
CLI spies prove hash refusal precedes bundle IO and scoring; default diagnostics still emit no economics.
The pull suite covers threshold and endpoint tolerances, missing/one-sided/crossed books, coverage gaps, post-decision
state, one-minute matching, zero denominators, crossed counts, omitted draws, cluster/replicate minima and both bounds.
Full-manifest/input/source and consumed-attempt acceptance remains required with the gates above before enrollment.

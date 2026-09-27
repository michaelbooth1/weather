# Maker replay signed-authorization verifier — design note, 2026-09-27

**Status: proposed implementation contract; docs only, no scoring authority.**
Owns the signature/admission gap for the harness CLI. Read when implementing that verifier.
The [frozen registration](../research/maker-replay-hurdles-preregistration-2026-09-27.md) owns the hurdles;
the [bundle contract](maker-replay-bundle.md) owns existing IO and replay semantics.

At basis `8ee7b8ad34c3d6ab8c073e93f90fc717586505ca`, `replay.authorization` has an empty
`APPROVED_REGISTRATIONS` table. It pins a raw artifact hash and owner through code review, accepts a nonempty
signature-reference string, then binds dates, markets, policies, clustering, metrics and configuration. It does
**not** cryptographically verify that string or enforce numeric hurdles/scoring dates. Keep the default diagnostic
path and empty production approval table until the complete scored path has separate owner approval.

## Proposed trust and signed object

Use a detached Ed25519 signature over an exact, bounded UTF-8 execution-manifest byte sequence, prefixed by a fixed
domain-separation literal for maker replay authorization. This is a design choice for implementation review, not
a claim that a crypto dependency, key or new flag exists. The signer retains the private key outside the repository;
the CLI receives only a signature and a key ID resolved from an independently owner-approved public-key trust store.
A key supplied inside the artifact, a Git author name, a caller SHA-256 or a review URL cannot establish that trust.
The owner must approve enrollment, rotation and revocation; never generate or enroll an owner identity on their behalf.

The manifest must bind the frozen Markdown path, introducing commit and raw-byte SHA-256, plus:

- a unique authorization ID, owner/key ID, purpose restricted to offline replay, review reference, signed_at,
  not-before and expiry in UTC, and the October 12 scoring date in America/Toronto;
- the exact quote-date list and separately typed settlement-only date, sorted market/condition inventory and active
  intervals, and every bundle/stream/plugin/settlement hash (future inputs are sealed before signing, not wildcards);
- exact executable source/tree identities and policy/plugin/scorer identities, all four policy names (map prose
  informed_v0 to runtime informed-v0 explicitly), every ReplayConfig value, both fill bounds, both k metrics,
  clustering methods, interval quantiles, bootstrap count/seed, and the pull endpoint/matching definitions;
- typed numeric hurdles and strictness: 14 closed quote dates; 10 effective dates and markets; all required
  conservative k=1 lower bounds > 0; matched pull-efficiency point ratio >= 2; mandatory sensitivities and disclosures.

Reject missing/unknown fields, duplicate keys, nonfinite values, ambiguous dates, duplicate identities and unsupported
versions. Verify the signature over the bytes actually read: no newline normalization or parse/re-serialization before
verification. SHA-256 is a byte binding, not proof of authorship. Preserve the existing review-attested enrollment
as an additional independent approval if retained; it must not bypass cryptographic verification in the new mode.
Do not silently reinterpret a previously accepted review-reference string as a cryptographic signature.

## Verification order and result

1. Parse bounded invocation metadata; require explicit comparison mode and an independently enrolled, unrevoked
   key/authorization. Reject unknown approval before bundle IO. Read only the bounded explicit authorization files,
   using the existing redirected-path, changed-file and strict-JSON protections.
2. Verify purpose/domain, signature, protocol hash, owner identity, approval, time window and exact source identities.
   Reject pending signature fields, future signed_at, expired/not-yet-valid authorization and a scoring-date mismatch.
3. Read the admitted bundles with the existing bounded reader, verify all signed hashes and exact scope/config
   equality, then enforce closed-day and settlement-only restrictions. No omitted/extra date, market or condition,
   configuration override or widened input cap may silently alter the approved experiment.
4. Atomically reserve a create-only attempt receipt for the authorization ID before the first policy/scorer call.
   Record the verification evidence and consumed status before releasing any scores. A partial or failed scored run
   stays consumed; retries need an explicit reviewed recovery authorization bound to the same frozen experiment,
   with any output already exposed disclosed. A new output directory alone must not reset the one-look rule.
5. Compute all policies, both fill bounds/k values and both inference schemes. Evaluate typed hurdles on effective
   paired cells and the matched move panel. Missing endpoint implementation, insufficient clusters/replicates,
   undefined efficiency, unmatched controls or missing required reports must never produce a combined PASS.
6. Write deterministic comparison artifacts and a separate immutable verification/attempt receipt containing
   authorization/protocol/input/config/source digests, key ID, verification time and each gate verdict. Time-bearing
   receipts are separate from deterministic scores. Refusals are bounded, nonzero and contain reasons, not scores
   or private material; a partial output is retained as incomplete and never reused.

Local receipts assume operator-controlled storage; they cannot stop a hostile caller deleting state or invoking the
pure library directly. The CLI is the authorized operational entry point, not a sandbox. Keep verifier tests and
synthetic library tests separate; no synthetic provenance, diagnostic flag, environment variable or test key may
enroll real scoring authority. Host workload admission remains an independent requirement.

## Focused implementation acceptance

Fixtures must prove one valid offline signature path and refusals for an unknown/revoked key, wrong owner/purpose,
tampered protocol/manifest/signature, newline changes, duplicate JSON keys, invalid time window, unclosed date,
extra settlement-day quote minutes, changed config/source/input hash and reused/partially consumed authorization.
Use spies to prove early refusals do not open bundles or invoke the scorer. Test exact zero lower bounds, a ratio of
exactly two, 13 dates, nine markets, undefined clock efficiency and UNMATCHED controls; none may silently weaken
the frozen inequalities. Verify both bounds/sensitivities always appear and diagnostic runs still emit no economics.
The pull-efficiency endpoint and typed hurdle evaluator must land with the verifier before this registration is
enrolled. This note adds no code, keys, approval-table entry, live permission or production admission change.

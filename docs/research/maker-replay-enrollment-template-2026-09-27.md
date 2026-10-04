# Maker replay final-manifest enrollment — commit template, 2026-09-27

**Status: TEMPLATE ONLY; no hash enrolled.** Owns the production procedure approved by the owner in the 110r task.
Read after the September 30 calibration and final panel inventory are sealed. The [execution-pack contract](../operations/maker-replay-bundle.md#clarified-execution-pack)
owns CLI inputs; the [110r report](../roadmap/agent-report-2026-09-110r-replay-execution-pack.md) supplies complete commands.
The original frozen registration/addendum remain untouched. The clarification still requires the owner's signature.

1. Production records the owner's approval of all three final document hashes in `DECISION_LOG.md`, revokes
   `maker-replay-2026-10-12-v1`, and approves the new ID `maker-replay-2026-10-15-v1`. Copy the new row's exact Source
   JSON to the owner-decision input. Do not infer a signature from this implementation task or template.
2. Complete the September 30 calibration with the prospective city inventory. After all fourteen quote dates and
   October 14 settlement-only bundle close, seal the full sorted condition inventory and run `manifest build`.
   Preserve one canonical manifest directory and its `attempts/` receipts; never make relocated copies to retry.
3. Compute the manifest's **raw-byte** hash with `Get-FileHash -Algorithm SHA256`, convert it to lowercase, and run
   `manifest verify --manifest <canonical-path> --manifest-sha256 <that-hash>` with every binding path from the report.
   Require exit zero and `VERIFIED_PREFLIGHT_ONLY`. This verifies the current APPROVE row and revocations before
   enrollment; it neither executes a policy nor spends the look. Do not normalize or rewrite manifest bytes.
4. In a new isolated topic branch, replace the empty mapping in
   `src/maker_core/replay/approved_registrations.py` with exactly the verified hash mapped to `michaelbooth1`.
   The following is a **diff template**, not an applicable patch or an executable enrollment command:

   ```diff
   -APPROVED_REGISTRATIONS: dict[str, str] = {}
   +APPROVED_REGISTRATIONS: dict[str, str] = {
   +    "REPLACE_WITH_THE_VERIFIED_64_LOWERCASE_HEX_RAW_SHA256": "michaelbooth1",
   +}
   ```

5. Run `tests/maker_core/test_replay_enrollment.py`, the authorization tests and maker-core boundary tests through
   the host's required admitted path. These exercise an empty registry, an enrolled exact hash, changed bytes and
   old-ID revocation without modifying real evidence. Run `manifest verify` again after the change. Enrollment is
   deliberately the only source file excluded from the executable hash set, preventing a self-referential manifest.
6. Review and commit **only the enrollment change** (plus its factual production receipt if required) as
   `replay: enroll maker-replay-2026-10-15-v1 execution manifest`. Include the verified hash, canonical manifest path,
   three document hashes, verifier receipt, source commit and owner identity in the review. Do not tune configuration.
   Push and obtain independent review. Production confirms the per-file roll verdict with `roll_verdict.ps1` before
   landing; maker core is not capture-imported, but the production verdict remains authoritative.
7. On October 15 America/Toronto, after the current authorization and host gates pass, execute the one scored run
   using that same canonical manifest and current DECISION_LOG. The CLI consumes its attempt before the first policy
   invocation. Partial/failing output remains spent; a second output directory cannot authorize a retry.

The supplied registry stays empty. No placeholder, document hash, protocol ID, fixture hash or caller-supplied
signature may be enrolled instead of the final execution-manifest hash. If any binding changes, stop and follow the
prospective authorization contract; a successful verifier run is not permission to revise the frozen method.

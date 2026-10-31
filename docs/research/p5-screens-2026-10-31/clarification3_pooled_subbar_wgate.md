# Master Clarification 3: rule_pooled_subbar_wgate (row 94)

Date: 2026-10-31. Lane L17. Master's ruling, relayed by the coordinator. Master approved both row 94 flags from
the L17 POOL-0006 build report. It was written before any C4 replay, C3 run or pooled read. No outcome, price or
label was read to write it.

Scope: this clarification amends `rule_pooled_subbar_wgate.md` (A3, sha256
`bd081e402c2c91fe16b560fab530c7d66f1bade9bc98b767a139231ae464b74d`) as already amended by Clarification 1
(`clarification1_pooled_subbar_wgate.md`, sha256
`f48c6fd8c6d7de5533e9a4ec9ebec16a5599f9872ec22ae4987737920b841c51`). It changes only which blocks C5 gates and
records the C4 run-env disclosure. Every other A1, A2, A3 and Clarification 1 term stands.

## (i) C5 gates only the testable block(s)

- **C5 gates only the TESTABLE block(s).** Under the option (a) scope that is POOL-0006 alone. A C5 failure in a
  testable block VOIDs the read as before.
- **C5 is still computed on the UNTESTABLE blocks.** POOL-0712 and F2-1316 get the same planted SYN+ / SYN-
  control, and its result is recorded in the receipt as a diagnostic.
- **A diagnostic failure is flagged prominently.** If C5 fails in any recorded diagnostic block, the receipt
  says so in a top-level field, and the run prints a banner naming the failing block(s).
- **Master reviews a flagged diagnostic before the verdict is labelled.** The POOL-0006 verdict is not labelled
  until master has reviewed the flagged diagnostic.
- **A diagnostic failure never VOIDs by itself.**

## (ii) C4 replays run in the members' recorded run env

- **The C4 replays run in the members' recorded run env, as Clarification 1 requires.** For R-PD and R-N that
  env is commit `68920c47defcd5e23af16bba7ec1b957baee6a64`. It is the detached merge of `a9f9be5b0` that ran
  their gate 2 on 2026-10-26 03:30.
- **Disclosure.** That env differs from the pool tree only in two places:
  - `r0_ols_floor_challenger`, which adds a default-preserving `metar_only` parameter;
  - `pooled_residual_model`.

  The scorecard code (sha256 prefix `f69071ac`) is identical in both. The pooled receipt carries this
  disclosure and this clarification's sha256.

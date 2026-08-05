# Deleted branch recovery manifest - 2026-08-05

Remote refs deleted from `origin` after `-09-15a` classified them **SUPERSEDED**.
Recorded **before** deletion so every tip commit stays recoverable by SHA.

**To restore any branch:** `git push origin <sha>:refs/heads/codex/<name>`
The workstation also retains local copies.

## Preconditions verified before deletion

- Every `docs/roadmap/agent-report-*.md` reachable from these branches is on `master`
  (45 rescued in `28f882cd`; 108 reports on master, verified branch by branch).
- None is classified MERGE, NEVER, or UNKNOWN by `-09-15a`.
- `live-canary-bot` and `workstation-research-2026-07-22` are NEVER and are **retained**.
- All 7 UNKNOWN branches are **retained**. An honest unknown is not a deletion warrant.

| Branch | Tip SHA | Base | Why superseded |
| --- | --- | --- | --- |
| `workstation-1000-information-gap-audit-2026-08-19a` | `f032bf4eef0ea484b08b56b526d997f2609e82e5` | `b125e2df013c` | exact ancestor of -08-25a |
| `workstation-continuation-candidate-2026-08-12a` | `1e525a02dfce1ba8c0d58a506877d3a778e8fe58` | `b125e2df013c` | exact ancestor of -08-25a |
| `workstation-floor-informativeness-gate-2026-08-13a` | `55f5f5ddda9e1a6ce73aa4075f2996eff5e2c7ef` | `b125e2df013c` | exact ancestor of -08-25a |
| `workstation-floor-informativeness-replication-2026-08-14a` | `703075f7e3a906f7a5e6f723974f97b3930e898f` | `b125e2df013c` | exact ancestor of -08-25a |
| `workstation-forecast-residual-anchor-2026-08-18a` | `ed0f5ffe0ae56caf9602352da9cff60192581d04` | `b125e2df013c` | exact ancestor of -08-25a |
| `workstation-gate-cost-diagnosis-2026-08-17a` | `b5be028a4b1ffc2d731d0cfb06f40773449b6d0a` | `b125e2df013c` | exact ancestor of -08-25a |
| `workstation-gate-harness-2026-08-09a` | `b9c62ead999bfb74175e0e2eb46d2d31e57f225b` | `b125e2df013c` | exact ancestor of -08-25a |
| `workstation-is-the-bias-conditional-2026-08-24a` | `fd1a0bb70c8cc63e17e9f22152804ded474235fc` | `b125e2df013c` | immediate ancestor of -08-25a |
| `workstation-measure-blindness-causally-2026-08-22a` | `ababbfd15153d3752f371e80ee8a5d46ae475b83` | `b125e2df013c` | exact ancestor of -08-25a |
| `workstation-prove-1000-blindness-2026-08-20a` | `6a068783a8ba6abcb1286e408da07d1b0f7e70d6` | `b125e2df013c` | exact ancestor of -08-25a |
| `workstation-repair-d1-anchor-2026-08-15a` | `8377873e44e3f3af41811130a79b7cb4cfcb5066` | `b125e2df013c` | exact ancestor of -08-25a |
| `workstation-spec-contract-repair-2026-08-21a` | `3718324394856ed918f7fb6e3aac63a300c36814` | `b125e2df013c` | ancestor of -08-25a; specifies but does not implement the parity fix |
| `workstation-why-is-the-morning-cool-2026-08-23a` | `b893857ebb7a815bc519ac1022121488e968dc73` | `b125e2df013c` | exact ancestor of -08-25a |
| `workstation-make-the-first-retrain-count-2026-08-25a` | `92bb534779677ca9c010798be2afd3c7186a6989` | `b125e2df013c` | functionally superseded by -09-12a; its 14 unique reports are now on master |
| `workstation-build-base-retrain-step-2026-08-26a` | `71d18318cfcc6f865f034b838654b63f6606b2d6` | `73d53cde722b` | superseded by the -09-12a lane; its PIT seam survives in -09-01a (KEPT) |
| `workstation-build-pit-forecast-corpus-2026-08-31a` | `f2dbc71e26ce674b950bfef67d1653650c938984` | `b7345ab2e6b0` | superseded by commits 2 and 3 of -09-01a (KEPT), which add the missing binding |
| `workstation-train-serve-parity-gate-2026-09-03a` | `af32501b9a6c0a1c241ad581ff805d8780b4a6e9` | `9275a41ea6d7` | implementation, fixture and tests carried forward into -09-12a (KEPT) |
| `workstation-hardening-lock-blocker-fixes-2026-07-24` | `1d9d58d37420c5794c266dfc27c714e2e4bb06b6` | `097562272312` | master owns the lock/release fixes; also embeds the excluded research/release rewrite |
| `workstation-mm-gate-2026-07-28b` | `34fda2a4010d06e1cfbef398a0475e9c26b10b90` | `5c004c4554d8` | superseded by merged -09-10a and held -09-11a |
| `workstation-pit-simplex-2026-07-24` | `8252209ba6ec25eb1199c23789dd0b49297e6dd9` | `097562272312` | superseded by the PIT-simplex fix on master (4041d358) |
| `workstation-release-one-blockers-2026-07-29` | `0beb40b8c7e4dab78e376a32bb7028d5e02db496` | `51d53b69ae44` | superseded by master 447dda75 and later release work |
| `workstation-second-clock-bootstrap-2026-07-30f-keystone` | `eadcd4b1f74c1920aff79a2e57552df0359ead04` | `a29590d62f8f` | superseded by master ea0167a7, d56e87cb and later release code |
| `workstation-skill-gap-2026-07-25b` | `e912557857242b46b3069457aa11a6803934ed26` | `008a0b82a6f7` | superseded by master and later ownership/schema ratchets |
| `workstation-strict-parity-2026-07-29` | `0591e4c228c1209dbb6dcd1b0c61778d662d8726` | `5954da1b2129` | superseded by master release fixes and the -09-03a/-09-12a parity contract |

**24 branches deleted.** Retained: 6 MERGE, 2 NEVER, 7 UNKNOWN.

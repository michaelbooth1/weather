# Workstation WU outcome gap/export contract report

Mission: `workstation-wu-outcome-gap-export-contract-2026-09-100a`

Verdict: `COMPLETE_VALIDATED`

The exact frozen WU blocker was reproduced without reading or emitting a
settlement temperature. The result supplies an outcome-blind 816-key gap
manifest, a 96-key production export specification, and a repository-owned
validator. This source tip has no safe reviewed production exporter, so this
handback deliberately contains no production command. The smallest remaining
production implementation is a read-only entry point that verifies settlement
ledger history, selects the authoritative revision for every requested
market/date, and creates the exact two-file artifact described by the spec.

## Source, workstation, and attempt identity

- Source: commit `30386b5f082abbecda99c6357bccde1308771448`, tree
  `b373970f5912284d6852c9fbb145952727cdc04e`, sole parent
  `663a288dbf04d8fbcabf0501288cfc9af1b8b545`.
- Stack base: `2e20e59aae08e7367dc79e1b8102c0551e7f6904`.
- Result ref:
  `refs/heads/codex/workstation-wu-outcome-gap-export-contract-2026-09-100a`.
- Implementation: commit `1f2b44a990cb9c4203a61c0a7aab881951ab2250`,
  tree `f2c67cbed28aa0a093cde81b82e115e7401a2796`, sole parent the
  exact source commit.
- Assigned workstation/principal: `DESKTOP-RFCD2GH` /
  `DESKTOP-RFCD2GH\Michael`. The assignment IDs matched SHA-256
  `a740ee7dc03165b0c88094f8b313aa6676f0984b30737ec5bcd9f723709fe5dc`
  and `899c8218f19e948baf648733e34ab9e3301c154300a30477816ed749c3c8507b`.
- The repository root and source worktree were clean before creation; the
  required result ref and worktree were absent. The shared mutex admitted the
  wrapper probe and every Python/test invocation, and the poison marker was
  absent.
- The previously sealed external-secondary attempt remains spent. Its
  create-only seal is 1,151 bytes, file SHA-256
  `e8a3e19da0798fef56c74bca98c6fec798d3d3f99dd253f0c600532c8cc217d3`,
  and self-hash
  `55d7dfe0dd9fe45ecd0926931dfcca4376765ccec1751c0036053efcafc9d86b`.
  It was not rerun or reinterpreted.

P0 also reverified the immutable 99c runner bundle and binding. The bundle is
516,981,666 bytes with SHA-256
`0503c0113d132cb2f122999556ebc197bd478b62d43d193e7e3b8f3753c068ab`;
the binding is 12,735 bytes with SHA-256
`d54fcc39d81638b161d3d86556b74b516d0734c3f7d5e6a509e36e28d7dd89a2`.
Bundle verification, complete history, and its retained final tip
`7c58e55e156bbd486fbd0fbf977ff9db9864f657` all matched.

## Frozen inputs

All paths below were read locally. SHA-256 is over exact file bytes.

| Role | Path | Bytes | SHA-256 |
| :--- | :--- | ---: | :--- |
| Mission | `C:\Users\Michael\Documents\Codex\runs\workstation-wu-outcome-gap-export-contract-2026-09-100a\mission.md` | 8,212 | `3c91f416e193cd4b27db49e4dc4a2bd46ad681de2924ca13568c9d1b520a0429` |
| Frozen design | `docs/roadmap/multiyear-nwp-residual-design-2026-09-88a.json` | 80,273 | `0667fdc204360122f44e35f2ef31dad5d6f7f53afd83bfd09ba0f0a50874bc65` |
| Frozen amendment | `docs/roadmap/multiyear-nwp-residual-external-amendment-2026-09-88a.json` | 9,415 | `866d7537440c6d1921128deff04e04ecc03f9bcc6f0b904b0fa1489e302ac152` |
| Source report | `docs/roadmap/agent-report-2026-09-12-workstation-multiyear-nwp-residual.md` | 20,674 | `aefff1ad8f8e7117cf6bbe1e054db45b749fc65e2bbb8d6bc33836f289f7d17e` |
| 2026 transfer | `C:\Users\Michael\Documents\Codex\inputs\pit-12field-20260810\transfer-manifest.json` | 8,585 | `1794455e40f967411d05660ff4ac785e1fab48caccb8fbdfb3df7aa31438712a` |
| 2026 front manifest | `C:\Users\Michael\Documents\Codex\inputs\pit-12field-20260810\front\manifest.json` | 5,481 | `f1366001341ad6bf96242dc42a9ed47310051079a033e035e850f0f486d1d28d` |
| 2026 back manifest | `C:\Users\Michael\Documents\Codex\inputs\pit-12field-20260810\back\manifest.json` | 5,427 | `0f52e100a979e5aeb2949d94734682045b5fa294ca0f0cb0d88c1de078ebc735` |
| 2021-2025 corpus manifest | `C:\Users\Michael\Documents\Codex\inputs\pit-12field-multiyear-2021-2025\final\corpus-manifest.json` | 49,118 | `25b7b50a733b2f714651bdd4fdb0724aa805fe684c0265e396d90f9d45e28c73` |
| 2021-2025 coverage matrix | `C:\Users\Michael\Documents\Codex\inputs\pit-12field-multiyear-2021-2025\final\coverage-matrix.csv` | 1,625,313 | `b7a2d4f0b6a9725122fb96d9953f6d25520552bc75779973ce869486d6344429` |
| 2021-2025 verification | `C:\Users\Michael\Documents\Codex\inputs\pit-12field-multiyear-2021-2025\final\final-verification.json` | 151,312 | `a1cdfc4daa29c3b5ecd750a8dcf28c95538269b17317ccb8b6c9e574ad2b4421` |
| Calendar corpus manifest | `C:\Users\Michael\Documents\Codex\inputs\pit-11field-2024-2025-calendar-extension\final\corpus-manifest.json` | 39,050 | `023c1a3fefa50b241a1a7a7234eb0c258d5e02c630d7468d057c0303e625fbd2` |
| Calendar coverage matrix | `C:\Users\Michael\Documents\Codex\inputs\pit-11field-2024-2025-calendar-extension\final\coverage-matrix.csv` | 1,117,491 | `3284fe12a4dc003cd897fc31dac44df2a0a788e50ac2ccd3889cfe407c807cbd` |
| Calendar verification | `C:\Users\Michael\Documents\Codex\inputs\pit-11field-2024-2025-calendar-extension\final\final-verification.json` | 117,729 | `9aa25a50611d03f5766e290c272fa6f0d6129f539610fa7db6db999d78996589` |

The frozen amendment bound the following WU daily-summary files under
`C:\Users\Michael\Documents\github\weather\data`. The builder rechecked every
byte count and hash before inventorying only date, unit, schema, and row-count
support.

| Market | Relative path | Bytes | SHA-256 |
| :--- | :--- | ---: | :--- |
| `atlanta` | `wunderground/katl/daily/daily_summary.csv` | 888458 | `1f013bb6cbd6b387184e5c3038f7cdf2f08a66f95342e59be887df6de482f060` |
| `austin` | `wunderground/kaus/daily/daily_summary.csv` | 868209 | `05852251187f980771f7b08e52e53983314f43f94797677cb7dfc9eafd74be3e` |
| `chicago` | `wunderground/kord/daily/daily_summary.csv` | 889680 | `1eff2c8aa1e031298686b054e642dbf1518ed8e3f2efd7f3229f45ee5a5d437e` |
| `dallas` | `wunderground/kdal/daily/daily_summary.csv` | 887289 | `db631cf6036ede6a64ea18b98c55a1a88dd9e96751c57bf22bccb103d7b31b8b` |
| `denver` | `wunderground/kbkf/daily/daily_summary.csv` | 874808 | `52ee59385d6ab5f265394e86acc99d22ec88ae7d92cbca0106e4e5f97cb351b1` |
| `houston` | `wunderground/khou/daily/daily_summary.csv` | 888882 | `2ba8271cd8dc05b962309655ee62a8626bfd14f140867d1bd52de06310ef59fd` |
| `los-angeles` | `wunderground/klax/daily/daily_summary.csv` | 876354 | `7e05d5d83e5999b975027fba7c86bfe71ba9a2de2829d4b2b0c074952058703f` |
| `miami` | `wunderground/kmia/daily/daily_summary.csv` | 901582 | `a3d2c6d94462ac73718632def9860bea1ec24884fdc2e27d21681fcd02862440` |
| `nyc` | `wunderground/klga/daily/daily_summary.csv` | 893238 | `90e89fb67c48dceffdea43cc7320b35a6f3d163a5f44abc200ae4fcf4f8f4691` |
| `san-francisco` | `wunderground/ksfo/daily/daily_summary.csv` | 876617 | `5f1560c0a4ac5f236dc9af7e2ed64b6156ebe114bed5e4f5462e9ff0dc472d49` |
| `seattle` | `wunderground/ksea/daily/daily_summary.csv` | 878163 | `c2c5eebc0e8e29f5a4d753d50cd221e57adced8c8bfd5df4ebeb2280086460a7` |
| `toronto` | `wunderground/cyyz/daily/daily_summary.csv` | 2741446 | `1ced925a605b6f4e82fa20cbe238b9c91d841a9390da604bc648b630dac920e1` |

## WU gap result

The machine-readable cohort comes from the frozen amendment: 2026-06-03 through
2026-07-30 on the pre-boundary side and 2026-07-31 through 2026-08-09 on the
post-boundary directional side. The gap builder kept these sides separate and
reproduced the spent attempt exactly.

| Side | Requested dates | Dates with any admissible market | Fully complete dates | Requested market-days | Admissible | Missing | Below threshold |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pre-boundary | 58 | 53 | 50 | 696 | 612 | 82 | 2 |
| Post-boundary directional | 10 | 9 | 9 | 120 | 108 | 12 | 0 |
| Total | 68 | 62 | 59 | 816 | 720 | 94 | 2 |

The current complete support is 59 dates and 720 market-days. The exact export
request is the 96 missing-or-below-threshold keys. If every requested key is
authoritative and admissible, the maximum attainable support is 68 complete
dates and 816 market-days. All 12 markets occur in both the cohort and request
contract.

The terminal gap is
`C:\Users\Michael\Documents\Codex\runs\workstation-wu-outcome-gap-export-contract-2026-09-100a\wu-outcome-gap-manifest.json`:

- 340,369 bytes;
- file SHA-256
  `6ba020575e3ef1eb903ae0010510caea20f31b31bdf3451c0e03f11175c3de94`;
- canonical self-hash
  `64176a727907c8f62c496f6fb1893c1f7462cfef15c1db3f06ef7b3e244f0ce8`.

An independent create-only rebuild at
`wu-outcome-gap-manifest-reproduced.json` produced the same 340,369 bytes, file
hash, and self-hash. A raw byte comparison returned true. It did not access a
settlement-value column. A separate field-name scan found no settlement bucket,
high, or daily temperature field in either gap file.

## NWP coverage kept separate

These are input-cell counts and do not alter the WU request. The 2021-2025
twelve-field corpus requests 13,789,440 cells, of which 5,975,424 are present
and 7,814,016 are missing. Each of 2021, 2022, and 2023 has 229,824 present and
2,528,064 missing cells because only temperature is present. The 2024 portion
has 2,528,064 present and 229,824 missing cells across its eleven-field surface;
2025 is complete at 2,757,888 cells.

The separate calendar extension requests 11,154,528 cells, with 10,682,595
present and 471,933 missing. Its 2025 portion is complete at 5,566,176 cells;
its missing cells are explicitly in January 2024. The 2026 target transfer is
complete at 1,645,056 rows across 12 markets, 12 fields, and leads 1 through 7.
Missing NWP cells and missing WU settlement labels remain distinct artifacts.

## Export contract and implementation

The tracked spec is
`docs/roadmap/wu-outcome-gap-production-export-spec-2026-09-100a.json`:

- 41,288 bytes;
- file SHA-256
  `cf10553a9b041a783bf5caf56b191835e2904474a4bad34dcbc1f6ad934d093f`;
- canonical self-hash
  `5d370c51da7d95e1d3a62a8ff4f9d66cd3312c5eecfebcbdbaab169be505e0f9`.

An independent create-only rebuild produced the same bytes and both hashes.
The spec requests only canonical WU evidence for the exact 96 keys. It requires
append-only ledger deduplication by `(market_id, target_date)`, authoritative
revision ordering, exact pre/post boundary labels, an exact two-file destination
under a 1 MiB bound, create-only and non-reparse paths, per-file hashes,
canonical manifest self-hash, ACL proof, and equal pre/post source identities.
It forbids substitute sources and all credential, provider-request, market-price,
prediction, probability, coefficient, and evaluation content.

`weather.operations.wu_outcome_export_contract` builds the outcome-blind gap and
the spec, selects latest revisions deterministically, and validates a future
export. The validator rejects absent, duplicate, extra, case-colliding,
wrong-boundary, wrong-unit, wrong-station, below-threshold, unbound-source,
tampered, escaping, reparse, oversized, and unexpected-file artifacts. It
returns only identities and counts. Five schemas were registered and the module
was added consistently to the workstation wrapper and mirrored Codex hook
allowlists.

## Verification

All Python and tests ran serially through `scripts/ops/workstation_heavy.ps1`.

- New contract tests: 11 passed in 0.13 seconds.
- Contract plus workstation wrapper/admission tests: 44 passed, 15 skipped in
  6.02 seconds.
- Pre-suite contract, wrapper, import, and schema tests: 74 passed, 15 skipped
  in 10.73 seconds.
- The single authorized complete suite used the fresh short external base temp
  `C:\w100af`: 4,361 passed, 3 failed, 18 skipped, 13 warnings, and 866 subtests
  passed in 419.85 seconds. Its JUnit is 710,856 bytes with SHA-256
  `4e2ad8bc535a8148639964653550cf7697ce613f6504fd4ac4de87b49dba00b7`.
- The three failures were deterministic integration ratchets introduced or
  exposed by this source stack: the wrapper/hook allowlist equality test and two
  module-size ownership tests. No `test_experiment_executor.py` MAX_PATH test
  failed, so the inherited-12 exception was not used. The allowlist mirror and
  the previously undocumented 2,064-line source module were repaired.
- The exact post-repair focused set covering those three tests and all new
  contract, wrapper, import, and schema tests passed: 109 passed, 15 skipped in
  11.75 seconds. The complete suite was not repeated, honoring the one-attempt
  contract.
- Final `compileall -q app src tests`: pass.
- Final agent-doc audit: pass, 18 agent files and 836 Markdown files.
- Final roadmap lint/check: pass, generated report matches sources.
- Cumulative `git diff --check` from the exact source: pass.
- Independent gap/spec generation and raw byte/hash comparison: pass.

## No-value-leak and prohibited-action audit

The gap parser retained only WU schema, local date, native unit, row count, and
revision position. The gap artifacts contain statuses, support counts, source
identities, and reasons. They contain no settlement temperature. The report also
contains no settlement temperature. Focused tests prove an outcome-bearing gap
field is rejected and that the parser discards an unrelated value column.

No production host, Scheduler, credential, provider, exchange, GitHub, remote,
market price, model fit, probability, scoring, forecast metric, campaign,
promotion, live path, corpus mutation, fetch, pull, merge, push, or cleanup
action occurred. The WU data and all corpus, ledger, attempt, and prior handback
evidence remained read-only. No unsafe production command was invented.

The final report/receipt-only commit and its tree are bound by the external
portable binding written after the complete-history bundle and isolated bare
verification, avoiding a self-referential committed receipt.

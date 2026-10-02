# 110m part 5 — repository health ratchets and combined qualification

**Verdict: PASS.** All requested regrowth categories have tracked-file tests,
explicit initial allowances and growth controls. Standalone qualification:
**62 passed in 46.03 s**. Combined 110m parts 1–5 and 110n qualification:
**331 passed, 3 subtests passed in 97.76 s**. Both used
`scripts/ops/workstation_heavy.ps1` and included schema registry, import
architecture/maker-core boundaries, agent docs and path-policy audits.

Branch: `codex/repo-health-ratchets-20260926`. Mission source: 110m at
`2c8b90618` or newer. A final fetch found handoff tip `d52969fa`; 110m and 110n
are unchanged. The new 110o handoff records the approved owner decisions and
separately assigns their implementation. Its seven producer dispositions remain
explicit exceptions here until that work resolves them.

## Implemented contracts

The canonical guide is [repository health ratchets](../operations/repo-health-ratchets.md).
The tests read tracked source and Git object metadata, never runtime evidence.

| Category | Initial reviewed allowance / behavior |
| --- | --- |
| Module size | 2,000-line default across src, maker_core, app, tests and tools; 37 existing larger files have individual ceilings |
| Operational orphans | 127 named module paths; operational docs/scripts and static/lazy/literal dynamic imports establish reachability; tests alone do not |
| Retired tokens | Per-file, per-symbol ceilings across 167 files, rather than a fungible repository total |
| Legacy unit names | Exact identifiers and field-name strings in 198 files; no new name or new path can hide behind a stable total |
| Unsigned band regex | Six existing patterns across five files on the independent integration base; alias and module-level regex scanning; part 1 removes its three defective patterns in the combined tree |
| Tracked size | Three existing Git blobs over 1 MiB have exact byte ceilings; roadmap data over 250,000 bytes must carry a mission id |
| Runtime dependencies | Undeclared import roots fail; eight existing path/root allowances cover joblib, pyarrow and eth_account with explicit reasons |
| Report producers | 94 JSON literal contracts: 71 on the daily-refresh dependency path, 12 explicit producer exceptions, 11 caller-input/output-name cases |

The producer scan deliberately includes output and configuration literals so an
ambiguous new JSON reference cannot silently escape review. The 12 explicit
producers include the seven D1-09 inputs, three research reports, the accepted
exchange-economics snapshot and the frozen-baseline manifest. Every exception
has an owner and disposition. A scheduled producer must exist, be reachable from
the daily-refresh module named by its PowerShell contract, and have a filename
reference in its source closure. This static contract does **not** prove runtime
dispatch, freshness, successful generation or activation. Those gates retain
their existing authority; no producer or task was scheduled here.

The dependency allowances let this branch qualify independently before part 4
lands its direct joblib/pyarrow declarations. The existing two eth_account sites
use the pinned live SDK's transitive dependency. No new implicit dependency is
permitted. After companion adoption, removed debt can be removed from the baseline.

The regex rule prevents regrowth of literal patterns in band/temperature/range
contexts; it does not prove arbitrary computed patterns safe. Historical unsigned
patterns outside part 1 remain named debt, not a claim of a complete parser rewrite.
LFS files are measured by tracked pointer bytes without hydration. Static orphans
are review exceptions and never instructions to delete code.

## Baseline review and controls

The initial reviewed seed is
`2db5220bc12dc231ef1a42ab2f2ebff11ed5cf69`; the helper binds it explicitly.
Each allowance may only shrink against that immutable seed and the preceding
committed baseline revision. A deliberately reviewed replacement seed starts a
new limit; prototype seeds predating it do not override that decision. Positive
and negative controls cover count growth, replacement paths/names, reductions,
signed versus unsigned regexes, regex aliases and module-level patterns,
unreachable graph cycles and literal dynamic imports.

The first combined check found three failing ratchets (55 checks passed): the
new status test exceeded the old ceiling, retirement handling/tests necessarily
introduced retired-token references, and signed-band fixtures used the unchanged
legacy field names. Before first publication, the seed was qualified against
these exact companion changes, rather than adding directory-wide waivers:

- `test_status_script.py`: 2,007 to 2,036 lines, covering the new alarm fixtures.
- Exact token counts in nightly health and five associated/new fixture files,
  including neutral-helper compatibility and retired-registrar controls.
- Only `bin_value_c` and `bin_value_hi_c` in the new signed-band fixture file.

The baseline records the five companion commit identities used for this review.
It retains integration-base ceilings so the ratchet branch can qualify on its
own as well as after the sibling fixes. Future increases require an explicit
reviewed governance change, not regeneration from a failing inventory.

The existing module-size audit also lacked ownership metadata for integration's
already-large `closed_day_projection_tiering`. Its owner and proposed split
boundary are now recorded; its measured cap is frozen. No runtime tiering
behavior changed.

## Combined evidence and landing

Validation-only detached merge: `a4b949538fddc90f8101b71647e6e5b744948562`.
It contains these implementations:

| Part | Qualified tip | Draft PR |
| --- | --- | --- |
| 110m part 1 | `a0f11a8a61613ff2607797b261297c7fb2e9eaa7` | [101](https://github.com/michaelbooth1/weather/pull/101) |
| 110m part 2 | `3306dd95deaa1243a9e9285d4ab36e1abe0f68a0` | [103](https://github.com/michaelbooth1/weather/pull/103) |
| 110m part 3 | `c1391d9704b6c02b90a7ba37cc810b11eb09deac` | [104](https://github.com/michaelbooth1/weather/pull/104) |
| 110m part 4 | `7c23927864d9d195e8f29c739402f65de0ff3398` | [105](https://github.com/michaelbooth1/weather/pull/105) |
| 110m part 5 | `7aaf073e33c0ce8ff749e32578c2aaa214e6392a` | This branch, before this report/index |
| 110n | `ac47f5035517af1e6185840d6811d5d15dbf3f34` | [102](https://github.com/michaelbooth1/weather/pull/102) |

The combined run covers signed capture and observation triggers, shared helpers
including the corrected private clocks, snapshot batches, geographic eligibility,
captured-input parity, the PIT differential fixtures, bounded temp handling,
dependency/ignore declarations, watchdog and alarm fixtures, Stage-A skip/barrier
behavior, retired health handling, all-script AST/host-literal checks, inventory,
operating-reference generation, both size audits and all four repo audits.
The earlier per-part reports retain the broader release/serving and full-market
results. This combined run is additional integration evidence, not production
adoption. The part 3 clock-census correction is in its separate append-only report.

There were no source-code merge conflicts. Retain both the PIT-contract and
neutral-helper sections of `docs/operations/package-boundaries.md` when resolving
its additive documentation conflict. Regenerate `correspondence-index.md` after
merging report commits; do not discard either branch's report entries.

The final fetched master is `965374a0edc6fcb65d66e257be9e404cc9af8d60`;
integration `8180404a0e588f73dab3c83a171538f8a89c9705` is not its ancestor yet.
All six PRs therefore retain the requested integration base. After that production
landing, rebase onto master and requalify any conflict resolutions. A rebase or
squash that rewrites the seed must explicitly rebind its reviewed commit; retain
full Git history for the seed and differential-fixture checks.

## Roll classification by file

| File | Classification |
| --- | --- |
| `tests/operations/repo_health_support.py` | Roll-free; tests only |
| `tests/operations/test_repo_health_ratchets.py` | Roll-free; tests only |
| `tests/fixtures/repo_health_baseline.json` | Roll-free; explicit test allowances |
| `src/weather/operations/module_size_audit.py` | Expected roll-free; audit CLI ownership metadata only, no capture import found |
| `docs/operations/README.md` | Roll-free |
| `docs/operations/module-ownership-map.md` | Roll-free |
| `docs/operations/repo-health-ratchets.md` | Roll-free |
| This report and `docs/roadmap/correspondence-index.md` | Roll-free |

Production must obtain the mechanical `roll_verdict.ps1` verdict for each part
and follow its integration procedure. Part 5 needs source adoption only. The
110n report contains the exact reviewed watchdog/status hashes and production
re-registration command; run it only on production after owner-ops review.

No production data, credentials, `.env`, local exclude/settings files, Scheduler
changes, network collectors or venue calls were used. Heavy work was admitted
through the workstation wrapper. The main checkout was left unchanged.

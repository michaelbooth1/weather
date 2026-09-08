# Post-reclaim implementation sweep - 2026-09-07

Historical review evidence for
[item 331](../items/item-331-post-reclaim-model-economics-and-research-plan.md).
**Draft: combined native full suite and compilation passed; exact-tip CI and publication pending.**
This records the follow-up implementation sweep; the
[initial system audit](post-reclaim-system-audit-2026-09-07.md) owns the earlier
whole-system findings and recent-PR dispositions.

## Source verdict and exact scope

Three introduced defects were found and their repairs independently reviewed.
No further must-fix source finding remained within the reviewed scope after
those repairs. Focused verification of the repaired combined source passed;
the earlier full combined suite was interrupted after critically low workstation
disk space was observed. The later full native suite at `7709236` passed with
18 explicitly documented skips; the result does not establish the skipped cases.

The sweep covered the changes from production baseline
`6714b77d8bb57fa36b4d2dd33675cab971ef2432` through combined preparation source
`55d688982f99b3bdc7615780b058dcb16960fe0d`, then the three repair patches below.
The reviewed local tips were READY
`e24bcd30bb29bff8595cc2d74aed5c8327f7c224` and combined P3
`c11c3287264ea75a3264e243c15932842867b208`.
Both worktrees were clean before the initial draft. Neither tip establishes
production adoption; source publication was authorized separately by the owner.
The owned workstation checkouts were subsequently advanced cleanly to these
READY/P3 tips before the final focused `c11c3287` run recorded below.

At those reviewed tips, full Git blob IDs and modes establish that READY retains
exactly the two-path ledger patch over `e18234613f9e84b76d6d4afb1a785b83a37a9208`.
Combined P3 at `c11c3287` retains the exact nine-path union of the ledger, report and Stage 0
repair patches over `55d6889`, without incidental merge changes. The earlier
`55d6889` merge likewise retained the disjoint reviewed P3 and READY changes.

## Findings and reviewed repairs

| Severity / trigger | Defect and resulting repair | Reviewed repair commit |
| --- | --- | --- |
| P1 - refreshed generation metadata reaches the attended execution lane | Stage 0 required exactly the six legacy metadata root keys; P3 adds two generation fields, blocking Stage 0, shared Stage 1 validation, sealing and copied-input revalidation. The repair validates the canonical generation envelope before accepting its exact root shape, preserves legacy compatibility and full raw-file hashing, and supports a copied metadata file without following the embedded registry path. Partial/corrupt envelopes and unrelated extra fields still fail closed. | `0aab443d21466f802f22ae4b5808227f0a8ebc0e` |
| P2 - settlement CSV has a blank upper endpoint | Pandas represents the blank as floating NaN, so strict native-band parsing rejected an otherwise valid legacy label. The repair normalizes only actual floating NaN in the two upper-endpoint aliases on a copied row before calling the canonical parser. Invalid lower endpoints and other malformed values still fail; input rows remain unchanged. | `c1db06d4c934d6278ebb47ed79d28d1850476b19` |
| P2 - invalid config replaces an earlier PASS receipt | JSON correctly became BLOCK and skipped live fetching, but the Markdown report omitted the human-readable cause. The repair displays the first blocker, with config-pair error fallback, escaping table separators/backslashes and flattening newlines. JSON and gate decisions are unchanged. | `8ce0a1dae539d133ef398ed2de557e733792bde8` |

The ledger and Stage 0 fixes received cross-review by the architecture reviewer
and their owning implementation reviewers; the report repair received an
independent architecture review. The Stage 0 incompatibility was identified
jointly during architecture/economics cross-checking. Native verification found
the report omission. The model reviewer identified the ledger regression.

## Test-infrastructure and probe corrections

A later change limited to synthetic test fixtures advanced READY to
`e7ef9d96234ae7cab8b2c881614982fb54f445d9` and combined P3 to
`77092366f180177f561ac409f40161bd0586bdbe`. This is separate from the three
production-code findings above. The native fixture/import gate passed on
`7709236`; the later full native suite in session `22884` exited 0. These
native-tested source heads remain the runtime evidence anchors; planned
closure commits add documentation only and require their own final-tip CI.

The first READY verification copied the nine-module P3 source probe, which
included `weather.market.location_config`, a module absent from READY.
That probe failed before the owner tests ran. Its failed receipt is preserved;
the corrected v2 probe removes only that absent import. The READY owner checks
and resulting eight-module probe then passed. This was a verification-scope
correction, not an additional production-code defect.

## Review coverage and responsibility

| Reviewer | Source and contract coverage |
| --- | --- |
| Architecture / operations | Generation publication, compare-and-swap and first-migration races; strict pair readers and invalid-receipt replacement; candidate freeze and both release verification paths; package/import ownership; portable host/principal/session and sealed-source authority; executor path/volume admission, exclusive claims and owned cleanup; affected operator UI, configuration and documentation. |
| Economics / execution | Raw exchange-response provenance and bounded reward-page validation; accounting/capital boundaries; Stage 0/1 metadata and copied-input compatibility; credentials and execution authority; unresolved payment attribution and cash coverage. |
| Model / research | Native C/F bands, zero and legacy endpoint consumers, replay/ablation paths, strict numerical incumbent controls and settlement-ledger CSV handling; limits on fidelity, comparison and improvement claims. |
| Integration owner | Serialized merges, independent repair acceptance, admitted native workstation execution, retained receipts and final source/verification/publication accounting. |

Source reviewers did not run tests, compile, scan runtime datasets, query
providers, transfer source or mutate production state during this sweep.
Heavy verification belongs to the integration owner's admitted 32 GB workstation
sessions under the canonical shared live/heavy exclusion and child-tree cleanup.

## Verification evidence available at draft time

Receipts below are retained ignored `scratch/` evidence in the review worktree;
they are not promised files in a clean checkout. Hashes identify exact artifact
bytes. Durations are the terminal stdout summaries supplied by the integration
owner unless explicitly labelled JUnit. The earlier 372/333-test XML results and
old-source negative control were independently checked. The integration owner
supplied the later exact terminal results and verified receipt hashes below.
The final full-suite JUnit aggregate, skipped-test reasons, source/import
properties and SHA-256 were independently checked against the retained file.
Earlier `88bacc6` checks remain in item 331.

| Source / receipt | Terminal evidence or current limitation | SHA-256 |
| --- | --- | --- |
| `55d6889`; `scratch/post-reclaim-native-controls-55d6889.xml` | 5 passed in 32.90 s. One `record_property`/xunit2 compatibility warning from the import probe; no test failure. | `DBE74869273F6FF48E5F11022DC6863A23E7DCABD4646D5A6FE027BE330CD877` |
| `55d6889`; `scratch/post-reclaim-focused-55d6889.xml` | Stopped at the first failure: 1 failed, 68 passed in 3.51 s. The invalid-config Markdown omission above was the failure; JSON BLOCK and no live fetch were correct. | `5C021495F0CDADFDF4A377E5A9C10388F19FBC733D6C223E8BB72C2925EB77AE` |
| `8ce0a1d`; `scratch/post-reclaim-focused-8ce0a1d.xml` | EXIT 0: 372 passed across the 17-file gate in 1750.18 s; JUnit 1750.157 s, zero failures/errors/skips. This source includes the report repair and predates the ledger and Stage 0 repairs. | `821305F36728D817AEFAC2FB931383F0566A4F056282E22C3872F75B11E6CCFB` |
| Old-source `8ce0a1d`; `scratch/post-reclaim-ledger-old-control-8ce0a1d.xml` | Expected EXIT 1: 1 failed, 27 deselected in 0.54 s; JUnit 0.536 s. The blank-upper CSV case returned `{}` instead of the native `90-91 C` winner. This is the intended negative control. | `AD712675A71C6C7CB3943AC82D3C12E0D70A6E3291A91CD17ADC44ECBBE65EBE` |
| Combined `c11c3287`; `scratch/post-reclaim-repairs-focused-c11c328.xml` | EXIT 0: 333 passed in 17.95 s; JUnit 17.934 s, zero failures/errors/skips. Includes ledger, Stage 0/1, generation, imports, roadmap and the nine-module source probe. | `0D03B8A749E23C7465179F3AF709FC3C737B8A784C6154BAB0D5D3D22176EF8C` |
| Combined `c11c3287` full suite; session `44389`, namespace `w331f` | INTERRUPTED / EXIT 1 after workstation `C:` reached 0.14 GiB free. Verified pytest child `7664` was stopped; canonical wrapper teardown completed and the poison marker was absent. No JUnit was produced and no full-suite PASS is claimed. | No JUnit produced |
| Combined `7709236`; `scratch/post-reclaim-fixture-disk-focused-7709236.xml` | EXIT 0: native fixture/import gate, 5 passed in 55.94 s. This checks the later fixture-only source and its import binding. | `E45793B8726630E979CA199AC87D4AD93EA457270D0E899580340E926F8B7A1A` |
| READY `e7ef9d9`; `scratch/post-reclaim-ready-focused-e7ef9d9.xml` | Failed before owner tests: the copied nine-module P3 probe imported `location_config`, which is absent from READY. The failed probe receipt is retained. | `B79978731AF986C8174F98ED9490FA9635D8F9E998893864BC58178E125E200F` |
| READY `e7ef9d9`; `scratch/post-reclaim-ready-focused-e7ef9d9-v2.xml` | EXIT 0: 155 passed in 9.27 s across owner checks and the corrected eight-module source probe. Only the absent P3 import was removed from the probe. | `E77FB863B34FD0DDC944536B0759FA941945F7ED333E286E84340E1101E41B9E` |
| READY `e7ef9d9` and combined `7709236`; `scratch/post-reclaim-native-compilation-20260908.json` in both local worktrees | Both admitted native `compileall -q app src tests` commands exited 0. The retained receipt binds exact wrapper commands, source heads, UTC start/terminal times and raw terminal output. | `BC26B1D6570317978BA9D2038A19178866A540B8CC253792562BE71B5AD6E59F` |
| Combined `7709236` full suite; session `22884`; `scratch/post-reclaim-full-7709236.xml` | EXIT 0: 5,464 passed, 18 skipped, 13 warnings and 991 subtests passed in 1945.42 s. JUnit: 6,473 entries, zero failures/errors, 1945.250 s. Skips are qualified below. | `7F6AEFC55F0DFC272B3164C9EB525C345924CFD1D8AF17A62392AC44FC39CDD6` |

The 17-file gate's JUnit start timestamp is
`2026-09-07T19:37:01.336563-04:00`. The final full-suite timestamp is
`2026-09-07T21:17:38.469018-04:00`; its 6,473 entries comprise 5,464 passing
tests, 991 passing subtests and 18 skips. The stdout warning count is supplied
by the integration owner and is not a JUnit test count.

| Full native suite skip reason | Count / coverage limit |
| --- | --- |
| POSIX credential-cleanup quarantine fallback | 2; these POSIX paths were not exercised by the Windows run. |
| `pwsh` unavailable | 4; the PowerShell Core variants of state helpers, number parsing, absent-state recovery and process classification were not exercised. |
| Outer workstation lease owns the shared mutex | 12; nested lease, wrapper and teardown scenarios requiring that mutex were not exercised by this admitted run. |

The receipt therefore supports the stated native suite PASS with these skips,
not an all-native-controls claim. Final-tip CI remains pending, including POSIX
and `pwsh` cases as enabled by the configured test environment. Its actual
results and skip disposition must be checked; this native receipt cannot
substitute for them.

The native control import probe resolved all seven checked modules under
`C:/Users/Michael/Documents/github/weather-post-reclaim-config-generation-20260907/src/weather/`:
`market/location_config.py`, `operations/experiment_executor.py`,
`operations/replay_cache_retention.py`, `market/exchange_economics_sources.py`,
`backtesting/replay.py`, `release_artifacts.py` and `units.py`.
The later `c11c3287` probe confirms the same seven paths plus
`backtesting/settlement_ledger.py` and `market/mm_live_stage0_scope.py` under
that root, with exact source-head property
`c11c3287264ea75a3264e243c15932842867b208`. The final full-suite receipt confirms
the same nine paths and source-head property
`77092366f180177f561ac409f40161bd0586bdbe`. These probes establish their
checked import roots, not every import. Windows path/PowerShell controls require
native execution; a skipped Unix test does not establish those behaviors.

## Full-suite interruption and completed fixture retirement

The integration owner stopped the full `c11c3287` run after observing only
0.14 GiB free on workstation `C:`. Session `44389` ended with exit 1 after the
verified pytest child `7664` was stopped. Canonical wrapper teardown completed,
the poison marker was absent, and source remained
`c11c3287264ea75a3264e243c15932842867b208`. No JUnit XML was produced.
Individual `F`/`E` progress markers have no retained explanatory traces here;
their causes are unresolved and are not attributed to disk exhaustion.

The integration owner subsequently completed the reviewed fixture-only
retirements of `w331b` and the eligible direct-child fixture directories under
`w331d`. The two terminal receipts report `COMPLETE` with no error: one
namespace root was removed for b and 278 direct-child directories for d.
The `w331d` root and its two linked fixture directories were held; neither
retained symlink was followed or removed. Interrupted namespace `w331f` and
the earlier 372-test and 333-test receipts remain preserved.

The recorded volume free-space deltas sum to **50,979,397,632 bytes
(about 47.5 GiB)**; the final recorded cleanup free-space sample is **53,986,689,024
bytes**. These are observed workstation volume changes around synthetic-fixture
cleanup. No real data, mirror, production archive, live or reclaim attempt was
cleaned. This scoped retirement does not establish production storage reclaim.

All six exact started/progress/final receipts are retained locally in the P3
review worktree, with the following independently checked SHA-256 hashes:

| Retained fixture-retirement receipt | SHA-256 |
| --- | --- |
| `scratch/fixture-temp-retirement-20260908-w331b.started.json` | `F9918911631BCC1DA215A1A00B44AFACB89FFC56BE70C0E832F8A6869DDB7DBA` |
| `scratch/fixture-temp-retirement-20260908-w331b.progress.jsonl` | `0DF3800D656A9D9D7F5667E117F6BDF60F4CD39B12345E4A1D57E5911A0DD20E` |
| `scratch/fixture-temp-retirement-20260908-w331b.final.json` | `F4254E11C54A649A0C678E5DABBBB0D31FA99E119A28217EC04F1465905944CA` |
| `scratch/fixture-temp-retirement-20260908-w331d.started.json` | `7F99E17A43E2A6A5FDC96FC6A16D0E8D467CBBF39D49770C9552B1EF8A5DAB5B` |
| `scratch/fixture-temp-retirement-20260908-w331d.progress.jsonl` | `6D7BB0C0E40CE0190EE045B8F31B48EAA595BA0DD29AC7E55C9591C0150814D5` |
| `scratch/fixture-temp-retirement-20260908-w331d.final.json` | `103CD8F93D178DC331C1619229F270CCA6402FEC2D39B0168285CBA58F00D495` |

Both native-tested source heads passed compilation, and the full `7709236`
suite in session `22884` exited 0 with the qualified result above. The integration
owner reported the remote worktree clean and unchanged at `7709236`, with
40,550,785,024 bytes free after the full suite. Final documentation commits,
exact-tip CI and publication remain pending.

## Remaining limits and closure evidence

- Legacy config remains explicitly unbound. Bound readers use one captured
  envelope; independent metadata-only consumers do not prove a paired read.
  Arbitrary editors outside the publication lock can still race after the last
  source comparison. Crash/power-loss behavior exceeds source review alone.
- Economic source/accounting improvements do not prove campaign payment
  attribution, complete cash, opportunity profitability or exact settlement.
  WU remains the model proxy; each traded event needs its own Rules contract.
- Parser and diagnostic replay fixtures do not establish production impact,
  restored serving fidelity, paired crossed inference, adequate support/power,
  model improvement or permission to spend statistical allocation.
- Storage reclaim and capture continuity remain their owners' evidence work.
  The completed attended Stage 0/1 attempt grants no new Stage 2 exposure,
  longer session, unattended trading, activation or release promotion.
- P3 adds a generation schema, but the full combined change also advances other
  existing schema contracts. Production adoption requires the canonical roll
  verdict and guarded recovery; no roll classification is inferred here.

The integration owner will finalize the documentation-tip verification and
publication record before treating this draft as complete. Native runtime
receipts remain bound to READY `e7ef9d9` and combined P3 `7709236`; later
documentation-only commits do not rewrite those tested source identities.
Continuing work scope and acceptance remain in item 331 and its linked owners.

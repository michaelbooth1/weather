# Agent report 2026-09-110e — maker contract hole

**PASS: MAK-4 and the owner-selected MAK-1 policy are fixed on the current Phase 0
lineage, merged into the weather plugin, and verified offline. The real
WeatherFairValue-to-decide regression now returns two symmetric legs.**

Executed on the workstation, 2026-09-25/26 America/Toronto. Authority is the owner's
explicit task: require an InfoEvent reference timestamp, keep observed-only events
active through expiry or removal, and quote grade `none` symmetrically without skew
or leg omission. This is implementation/test evidence, not live-readiness authority.

## Changes and evidence

**MAK-4.** `InfoEvent.__post_init__` rejects an event whose scheduled, observed and
detected timestamps are all absent, including when only an expiry is supplied.
An observed-only event becomes active at its observed time and remains active
through its inclusive `active_until_utc`, or until the caller removes it when no
expiry exists. Detection still takes precedence if supplied, so an earlier
observation does not admit a future detection. Scheduled-only windows are unchanged.
Tests cover future/at-reference events, exact expiry, post-expiry, indefinite
retention, removal, pull/decided behavior and cancellation before cooldown.

**MAK-1.** Grade `none` now has zero probability skew. Both BUY legs use the same
clipped width and size around the qualified market midpoint. Existing one-sided,
unequal-size or asymmetric quotes cannot pass HOLD: the kernel returns CANCEL
with `UNCALIBRATED_ASYMMETRY` before cooldown. The size cap remains 30; freshness,
fair-value disagreement, information, touch, depth, capital and economic screens
can still refuse the whole quote. Shadow/scored asymmetry is unchanged.
Tests exercise positive/negative/zero model disagreement at market midpoints
0.4, 0.5 and 0.6, plus resting-quote symmetry and unchanged safety gates.

The plugin end-to-end test instantiates the real `WeatherUniverse` and
`WeatherFairValue` with invented 2030 discovery/band/bulletin inputs, then passes
the actual returned `OutcomeView` to `decide()`. It does not substitute a mock
probability. The non-neutral grade-`none` view originally produced only a NO leg;
the regression now requires QUOTE, ordered YES/NO legs, equal distance from their
complementary market centres, and equal 30-share sizes. The test belongs on the
plugin branch because Phase 0 intentionally has no weather implementation.

The canonical [maker core contract](../operations/maker-core-contracts.md) now
describes timestamp validation, observed-event lifetime and the owner's uncalibrated
symmetry decision. No contract arguments, units or version identifier were changed.
The existing expiry test constructs a valid referenced event directly, instead
of first constructing the newly forbidden timestamp-free intermediate object.

## Branch and commit lineage

| Role | Branch / commit |
| --- | --- |
| Fetched Phase 0 base | `codex/maker-core-phase0-20260925` at `c5f245b84e4e991a6ee8ec177e935239b9d3e338` |
| Core fix | `8d6d9ba64e93728ade3f3f35cee36bc79829ec6a` — publish to the same Phase 0 branch |
| Fetched plugin base | `codex/weather-maker-plugin-20260925` at `f723599960a243f921745847f642ec8107639bca` |
| Requested merge | `110a142f4c0d2d33be2380d9a0ddd62a576d7535` — two-parent merge of plugin base and core fix |
| Plugin end-to-end regression | `4f84ab138e3f33222bc5edcdbd05cb1e24a84f90` |

This report and its generated correspondence-index entry follow the plugin test
commit. The final published plugin tip is the docs/index descendant containing
all three commits above; the task handback gives its exact hash.

The existing local branch worktrees were behind their remote tips and belonged to
earlier tasks. They were preserved. Isolated worktrees were created from the exact
fetched topic tips with process-local `GIT_LFS_SKIP_SMUDGE=1`:

- `scratch/w/maker-contract-110e`, local working branch `codex/maker-contract-hole-110e`.
- `scratch/w/maker-plugin-contract-110e`, local working branch `codex/maker-plugin-contract-hole-110e`.

Publication targets only the two owner-named remote branches, using ordinary
fast-forward pushes. No master merge, rebase, squash, force-push or branch deletion.

## Verification

| Check | Result |
| --- | --- |
| New core regressions before implementation | 13 failed / 8 passed, demonstrating the timestamp, lifetime, leg-drop and resting-asymmetry holes |
| Real WeatherFairValue regression before merge | Failed: actual outcomes were `('NO',)` instead of `('YES', 'NO')` |
| Complete core tests plus import-architecture ratchets | **639 passed, 12 skipped** |
| Merged core/plugin tests, architecture ratchets and roadmap/index tests | **1,183 passed, 12 skipped** |
| Bounded core and integrated plugin compileall | PASS |
| Core and integrated plugin documentation audits | PASS |
| Git whitespace and staged-diff checks | PASS |

The 12 skips are the pre-existing RE-1 sanitized-journal replay skeleton; this
task did not access real journals. Focused checks cover the changed contracts,
all maker-core tests and all weather-plugin tests; no full repository suite or
production-host qualification is claimed. Temporary-test setup was corrected
(create the parent directory and stage the new test before the tracked-file
ratchet), then the complete focused suites passed.

All pytest and compileall runs used `scripts/ops/workstation_heavy.ps1`, with
the project CPython and separate explicit `--basetemp` directories under the
task-owned `scratch/maker-110e-tests`. To reproduce on an admitted workstation,
use that wrapper with the following argument arrays (encode JSON as UTF-8 base64
for `-ArgumentsBase64`; `-RepoRoot` must own the selected wrapper):

```json
["-m","pytest","tests/maker_core","tests/operations/test_import_architecture.py","-q"]
["-m","pytest","tests/maker_core","tests/market/test_maker_plugin.py","tests/market/test_maker_plugin_110c.py","tests/market/test_maker_plugin_110e.py","tests/operations/test_import_architecture.py","tests/reporting/test_roadmap_backlog.py","tests/reporting/test_correspondence_index.py","-q"]
["-m","compileall","-q","src/maker_core","src/weather/market/maker_plugin","tests/maker_core","tests/market/test_maker_plugin_110e.py"]
```

Add an owned absolute `--basetemp` to pytest, create its parent first, and remove
the test directory after verification. The plugin array runs from the plugin
checkout; the core array runs from the Phase 0 checkout.

## Per-file operational disposition

| File | Disposition |
| --- | --- |
| `src/maker_core/contracts/__init__.py` | Offline maker contract validation; production closure membership not measured |
| `src/maker_core/quoting/policy.py` | Pure offline proposal behavior; production closure membership not measured |
| `tests/maker_core/test_110c.py` | Existing synthetic expiry fixture corrected; no runtime adoption |
| `tests/maker_core/test_110e.py` | Synthetic core regression coverage; no runtime adoption |
| `tests/market/test_maker_plugin_110e.py` | Synthetic real-provider/core integration coverage; plugin branch only |
| `docs/operations/maker-core-contracts.md` | Canonical behavior documentation; docs-only roll-free classification |
| This report and `docs/roadmap/correspondence-index.md` | Historical handback and generated index; docs-only roll-free classification |

No production data or retained capture closures were read. A production adoption
owner must obtain `scripts/ops/roll_verdict.ps1 -Branch <branch>` under the normal
integration gates before any master/runtime adoption; branch publication itself
does not adopt or restart anything.

**Not done:** no venue calls, credentials, `.env`, production data, live trading,
capture/Scheduler operations, model fitting, release promotion or master mutation.
Network access was limited to the requested source-control publication and its
GitHub verification. All provider inputs used by the new test are synthetic.

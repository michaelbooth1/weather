# Branch retirement manifest - 2026-08-11

Every branch below is an **ancestor of `master`**: `git branch --merged` ancestry, not a
guess. Deleting them removes no commit and no file from the project's history. The tip SHA is
recorded so any branch here can be restored with `git branch <name> <sha>` (or
`git push origin <sha>:refs/heads/<name>`) for as long as the object survives in any clone.

This retirement was unblocked by `4e2b8c27`, which rescued the last 13 agent reports that
existed only on unmerged branches. Orphaned-report count at the time of writing: **0**.
The prohibition that stood since 2026-08-05 was specifically *until those reports are on
master* - it is satisfied, and it still applies to every branch NOT listed here.

## Local branches retired (32)

| branch | tip | in master |
| --- | --- | --- |
| `admission-budget-rightsize-2026-07-21` | `9eee2831` | yes |
| `codex/ci-green-baseline` | `0df90224` | yes |
| `codex/item323-hardening` | `30f647e5` | yes |
| `codex/observation-cache-isolation` | `767a217d` | yes |
| `codex/operator-state-july15` | `13ac5427` | yes |
| `codex/overnight-integration` | `fc2cfbda` | yes |
| `codex/pit-preselection-source` | `11bab9bb` | yes |
| `codex/production-hardening` | `b6841f3e` | yes |
| `codex/production-mm-countability-postmortem-2026-08-08` | `0889f6ae` | yes |
| `codex/production-operating-reference-2026-08-08` | `1e73eb1e` | yes |
| `codex/production-register-mm-countability-schema-2026-08-08` | `3501db40` | yes |
| `codex/production-register-two-schema-literals-2026-08-08` | `50bc894e` | yes |
| `codex/production-tolerate-benign-capture-race-2026-08-08` | `aeed3a65` | yes |
| `codex/release-bootstrap-hardening` | `e72f2f0a` | yes |
| `codex/scheduler-attestation` | `4d132fd2` | yes |
| `codex/snapshot-memory-stabilization` | `0127914f` | yes |
| `codex/snapshot-resource-stability` | `6affca1b` | yes |
| `codex/taker-latest-input-bounds` | `d12cd11b` | yes |
| `codex/windows-venv-process-identity` | `a636fdc5` | yes |
| `daily-attestation-2026-07-19` | `c0eb3e6e` | yes |
| `evidence-plumbing-2026-07-14` | `7c3e3bb5` | yes |
| `fix/stack-reconcile` | `1937d34f` | yes |
| `hourly-bounded-2026-07-16` | `6b6b1442` | yes |
| `item206-shim-removal-2026-07-20` | `b7e427a4` | yes |
| `maker-bounded-2026-07-16` | `d2ce198d` | yes |
| `maker-projection-2026-07-19` | `cf8d456b` | yes |
| `ops/clob-raw-tape-tiering-2026-08-10` | `9812f112` | yes |
| `ops/rescue-orphaned-reports-2026-08-11` | `4e2b8c27` | yes |
| `ops/tiered-raw-tape-readers-2026-08-11` | `4bf56246` | yes |
| `release-bootstrap-2026-07-13` | `c1f60f31` | yes |
| `taker-finalization-bounded-2026-07-17` | `332ea9d1` | yes |
| `taker-tail-casebook-bounded-2026-07-17` | `023706df` | yes |

### Three local branches that are NOT ancestors of master

These were checked separately, because `--merged` excludes them and deleting them on the strength
of their names would have been exactly the mistake this file exists to prevent. Each was tested with
`git rev-list <branch> --not --remotes master` - the commits that exist on **no remote at all**:

| branch | local-only commits | what they are | verdict |
| --- | --- | --- | --- |
| `codex/fix-wu-404-classification-2026-08-06` | 0 | fully preserved on `origin/` | safe to drop locally |
| `fix/wstretch-bom` | 2 | merge commits; one resolved `OPERATIONS_DESIGN.md` | superseded |
| `verify/watcher-stretch-merge` | 1 | trivial merge, no conflict resolution | superseded |

The two `superseded` verdicts are not assumptions. Both branches are local integrations of
`-09-14a` and `-09-37a`, and **both of those are already merged into master**, which resolved the
same overlap its own way. What is lost by deleting them is a dead alternative resolution, not work.
Local deletion is recoverable from the reflog for ~90 days regardless.

## Remote branches eligible for retirement (46)

| branch | tip | in master |
| --- | --- | --- |
| `codex/codex-audit-20260811` | `16049f1e` | yes |
| `codex/production-register-mm-countability-schema-2026-08-08` | `3501db40` | yes |
| `codex/production-register-two-schema-literals-2026-08-08` | `50bc894e` | yes |
| `codex/production-tolerate-benign-capture-race-2026-08-08` | `aeed3a65` | yes |
| `codex/workstation-anatomy-of-the-severity-tail-2026-09-59a` | `fe158a7e` | yes |
| `codex/workstation-are-severe-rows-identifiable-ex-ante-2026-09-32a` | `472337c1` | yes |
| `codex/workstation-audit-the-held-release-branch-2026-09-52a` | `17f5e85c` | yes |
| `codex/workstation-build-the-research-parent-path-2026-09-53a` | `0b17b6f0` | yes |
| `codex/workstation-can-executions-be-reconstructed-2026-09-47a` | `35a05794` | yes |
| `codex/workstation-can-the-maker-quote-at-all-2026-09-48a` | `874cff61` | yes |
| `codex/workstation-close-the-repair-follow-ups-2026-09-49a` | `c46b2160` | yes |
| `codex/workstation-close-the-train-serve-parity-gap-2026-09-39a` | `0da83657` | yes |
| `codex/workstation-conditional-tail-reshape-2026-09-60a` | `459cd02d` | yes |
| `codex/workstation-consolidate-merge-queue-2026-09-01a` | `450f03c5` | yes |
| `codex/workstation-decompose-the-gap-2026-09-56a` | `14db9ead` | yes |
| `codex/workstation-does-a-quotable-edge-exist-2026-09-46a` | `b960d213` | yes |
| `codex/workstation-does-the-repair-zero-the-winner-2026-09-64a` | `fb41bfa5` | yes |
| `codex/workstation-exclude-denver-station-days-and-fit-2026-09-42a` | `1937d34f` | yes |
| `codex/workstation-fix-the-watcher-stretch-2026-09-14a` | `78b05cd7` | yes |
| `codex/workstation-honest-corpus-versus-rich-corpus-2026-09-40a` | `7517a631` | yes |
| `codex/workstation-honest-corpus-versus-rich-corpus-2026-09-41a` | `50d0a3e9` | yes |
| `codex/workstation-interval-coverage-at-alpha-0025-2026-09-62a` | `e821edb3` | yes |
| `codex/workstation-is-gate-3-satisfiable-2026-09-68a` | `dbd0ebd1` | yes |
| `codex/workstation-is-the-market-gap-seasonal-2026-09-34a` | `d8bd0259` | yes |
| `codex/workstation-is-the-outcome-label-sound-2026-09-67a` | `1c694a97` | yes |
| `codex/workstation-is-the-panel-floor-the-served-floor-2026-09-65a` | `847358c0` | yes |
| `codex/workstation-make-the-season-window-target-derived-2026-09-33a` | `492bfbb7` | yes |
| `codex/workstation-map-the-release-bootstrap-2026-09-51a` | `72fb7a11` | yes |
| `codex/workstation-one-own-information-feature-2026-09-58a` | `1cc4b9f1` | yes |
| `codex/workstation-preregister-pit-field-evaluation-2026-09-61a` | `5ea8ce75` | yes |
| `codex/workstation-produce-the-corpus-manifests-2026-09-54a` | `6f973932` | yes |
| `codex/workstation-produce-the-first-retrained-candidate-2026-09-38a` | `701f5ac0` | yes |
| `codex/workstation-rehearse-the-first-retrain-2026-09-50a` | `9c05d14f` | yes |
| `codex/workstation-remeasure-the-gap-on-the-repaired-model-2026-09-44a` | `6c3a5dc0` | yes |
| `codex/workstation-repair-the-blind-feature-block-2026-09-43a` | `96a58774` | yes |
| `codex/workstation-rescore-b-on-the-served-floor-2026-09-66a` | `9a33ecd2` | yes |
| `codex/workstation-rescue-the-pit-retrain-lane-2026-09-20a` | `981b1d3a` | yes |
| `codex/workstation-restart-the-mm-countable-day-clock-2026-09-45a` | `3c6ee243` | yes |
| `codex/workstation-restore-the-settlement-source-2026-09-37a` | `d323ed15` | yes |
| `codex/workstation-run-the-b-only-screen-2026-09-63a` | `995433c4` | yes |
| `codex/workstation-seasonal-distance-two-stratum-2026-09-31a` | `276ac508` | yes |
| `codex/workstation-split-the-chain-2026-09-29a` | `f418e957` | yes |
| `codex/workstation-what-can-this-panel-certify-2026-09-57a` | `937b8031` | yes |
| `codex/workstation-where-is-the-market-information-advantage-2026-09-36a` | `b8b0244b` | yes |
| `codex/workstation-write-the-corpus-producer-2026-09-55a` | `629368e9` | yes |
| `ops/clob-raw-tape-tiering-2026-08-10` | `9812f112` | yes |

## RETAINED - not merged, do not delete (27)

These carry commits that exist nowhere else. Their reports are now on master, but their
**code** is not.

- `codex/fix-wu-404-classification-2026-08-06` (`8e5c140a`)
- `codex/live-canary-bot` (`10ad54f5`)
- `codex/workstation-autopsy-the-learning-loop-2026-09-21a` (`6959796f`)
- `codex/workstation-bootstrap-rehearsal-2026-07-23` (`b6aa1c11`)
- `codex/workstation-build-free-source-parity-dark-2026-09-22a` (`538b5acb`)
- `codex/workstation-build-the-first-retrain-2026-09-12a` (`b7ee084c`)
- `codex/workstation-clear-the-forecast-archive-gate-2026-09-16a` (`ff9cf08b`)
- `codex/workstation-close-the-maker-evidence-gap-2026-09-27a` (`14bfc088`)
- `codex/workstation-detect-win-power-2026-09-04a` (`933de933`)
- `codex/workstation-does-the-cool-bias-track-seasonal-distance-2026-09-30a` (`05beb65c`)
- `codex/workstation-execution-tape-capture-2026-09-69a` (`98edaaa2`)
- `codex/workstation-gate-the-model-input-surface-2026-09-28a` (`06c508f8`)
- `codex/workstation-lock-blocker-fixes-2026-07-24` (`06a38069`)
- `codex/workstation-lock-window-sweep-2026-08-02a` (`b28efa54`)
- `codex/workstation-make-mm-days-countable-2026-09-11a` (`14dd1e84`)
- `codex/workstation-measure-full-free-source-parity-2026-09-26a` (`735cb891`)
- `codex/workstation-narrow-the-maker-producer-2026-09-18a` (`55d500de`)
- `codex/workstation-prove-repair-wu-parity-2026-08-30a` (`6990913a`)
- `codex/workstation-release-one-rehearsal-2026-07-29` (`e13851cc`)
- `codex/workstation-research-2026-07-22` (`423eaa59`)
- `codex/workstation-respecify-the-maker-settlement-gate-2026-09-25a` (`75882434`)
- `codex/workstation-restart-skill-tracking-2026-09-19a` (`ba748b76`)
- `codex/workstation-rotate-the-other-two-loops-logs-2026-09-35a` (`a7de816f`)
- `codex/workstation-scope-forecast-archive-extension-2026-08-28a` (`39ab2047`)
- `codex/workstation-size-forecast-lookahead-2026-08-29a` (`9b8fde66`)
- `codex/workstation-start-the-maker-tape-2026-09-17a` (`13a9f690`)
- `codex/workstation-who-breaks-floor-2026-07-27g` (`58ab0dd3`)


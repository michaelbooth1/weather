# Agent report 2026-09-111b — returned branches CI-green on current master

**All 18 returned PRs are green at the heads below. Two items need production review before integration: #106's new
repo-health seed, and the fact that the exam-line exporter bytes changed after 111a.** Nothing was integrated, promoted,
scheduled or run against production data.

This answers `workstation-handoff-2026-09-111b-returned-branches-ci-green.md` from
`origin/codex/handoff-110h2-20260928`. Workstation session (32 GB, non-capture); heavy runs used
`scripts/ops/workstation_heavy.ps1`. Fixtures only: no production data, credentials, `.env`, Scheduler or venue calls.
Every branch was advanced by merge only (no rebase or force-push). Master was `164f12d0a` at the start and
`b0032a90` (docs-only: the 111b/111c handoffs) by the end.

## Result table

| PR | Branch | Head SHA | CI run (test) | Conclusion |
| --- | --- | --- | --- | --- |
| [#100](https://github.com/michaelbooth1/weather/pull/100) | `codex/maker-replay-harness-20260926` | `98f768c7cc` | [36619198169](https://github.com/michaelbooth1/weather/actions/runs/36619198169) | success (native-launch=pass, test=pass) |
| [#108](https://github.com/michaelbooth1/weather/pull/108) | `codex/shadow-runner-design-20260927` | `06a0bb31f3` | [36621226363](https://github.com/michaelbooth1/weather/actions/runs/36621226363) | success (test=pass, native-launch=pass) |
| [#109](https://github.com/michaelbooth1/weather/pull/109) | `codex/replay-hurdles-prereg-20260927` | `066b0700fa` | [36621207872](https://github.com/michaelbooth1/weather/actions/runs/36621207872) | success (test=pass, native-launch=pass) |
| [#112](https://github.com/michaelbooth1/weather/pull/112) | `codex/replay-execution-pack-20260927` | `96bfef806e` | [36621213058](https://github.com/michaelbooth1/weather/actions/runs/36621213058) | success (native-launch=pass, test=pass) |
| [#113](https://github.com/michaelbooth1/weather/pull/113) | `codex/t1-fair-value-scorer-20260927` | `d937b34ab1` | [36621217815](https://github.com/michaelbooth1/weather/actions/runs/36621217815) | success (test=pass, native-launch=pass) |
| [#114](https://github.com/michaelbooth1/weather/pull/114) | `codex/nightly-bundle-export-20260927` | `481b367798` | [36621223078](https://github.com/michaelbooth1/weather/actions/runs/36621223078) | success (native-launch=pass, test=pass) |
| [#115](https://github.com/michaelbooth1/weather/pull/115) | `codex/shadow-runner-20260927` | `c0a54642bc` | [36621235285](https://github.com/michaelbooth1/weather/actions/runs/36621235285) | success (native-launch=pass, test=pass) |
| [#103](https://github.com/michaelbooth1/weather/pull/103) | `codex/pit-contract-split-20260926` | `d6fce5544e` | [36610095822](https://github.com/michaelbooth1/weather/actions/runs/36610095822) | success (test=pass, native-launch=pass) |
| [#104](https://github.com/michaelbooth1/weather/pull/104) | `codex/paper-maker-decouple-20260926` | `b8c827995a` | [36610101967](https://github.com/michaelbooth1/weather/actions/runs/36610101967) | success (native-launch=pass, test=pass) |
| [#105](https://github.com/michaelbooth1/weather/pull/105) | `codex/repo-health-quick-wins-20260926` | `5c4c3f8df3` | [36610107817](https://github.com/michaelbooth1/weather/actions/runs/36610107817) | success (hook (windows-latest)=pass, hook (ubuntu-latest)=pass, test=pass, hook (ubuntu-latest)=pass, hook (windows-latest)=pass, native-launch=pass) |
| [#106](https://github.com/michaelbooth1/weather/pull/106) | `codex/repo-health-ratchets-20260926` | `0baf930648` | [36614372223](https://github.com/michaelbooth1/weather/actions/runs/36614372223) | success (test=pass, native-launch=pass) |
| [#110](https://github.com/michaelbooth1/weather/pull/110) | `codex/W-tracker-step1-20260927` | `d2f7df4fe9` | [36610120656](https://github.com/michaelbooth1/weather/actions/runs/36610120656) | success (native-launch=pass, test=pass) |
| [#117](https://github.com/michaelbooth1/weather/pull/117) | `codex/stage-a-incremental-20260927` | `9e8bbf5b97` | [36610065285](https://github.com/michaelbooth1/weather/actions/runs/36610065285) | success (qualify (windows-latest)=pass, native-launch=pass, test=pass, qualify (ubuntu-latest)=pass) |
| [#118](https://github.com/michaelbooth1/weather/pull/118) | `codex/clob-write-on-change-20260927` | `df686f4b70` | [36610072523](https://github.com/michaelbooth1/weather/actions/runs/36610072523) | success (test=pass, native-launch=pass) |
| [#119](https://github.com/michaelbooth1/weather/pull/119) | `codex/snapshot-incremental-reads-20260927` | `1877ba36cf` | [36610075563](https://github.com/michaelbooth1/weather/actions/runs/36610075563) | success (native-launch=pass, test=pass) |
| [#120](https://github.com/michaelbooth1/weather/pull/120) | `codex/thin-ensure-entry-20260927` | `3ccbaa8c5e` | [36610080302](https://github.com/michaelbooth1/weather/actions/runs/36610080302) | success (native-launch=pass, test=pass) |
| [#121](https://github.com/michaelbooth1/weather/pull/121) | `codex/stage-a-profile-20260927` | `2c6c7ad51c` | [36610086942](https://github.com/michaelbooth1/weather/actions/runs/36610086942) | success (test=pass, native-launch=pass) |
| [#125](https://github.com/michaelbooth1/weather/pull/125) | `codex/110o-unscheduled-producers-20260928` | `3770ea3fe0` | [36610092092](https://github.com/michaelbooth1/weather/actions/runs/36610092092) | success (test=pass, native-launch=pass) |

Base #96 (`codex/weather-maker-plugin-20260925`, owned by 111a, not pushed by this session) is green at `134be204`.

"Green" means every check on that PR's head finished `success`: `test` (full Linux suite, including the schema
registry, import boundary, agent-docs, path-policy and module-size audits), `native-launch`, and where a PR triggers
them, `hook` or `qualify`.

## What each fix was

### Exam line (#100, #108, #109, #112, #113, #114, #115)

Stack: master ← #96 plugin ← #100 harness ← {#109 prereg ← #112 execution pack; #113 T+1 scorer; #114 nightly export;
#108 shadow design ← #115 shadow runner}. Each branch was merged from its own base downward-first, so each PR's diff stays
its own. #108 is not in the handoff list, but #115 sits on it and it needed the same master merge.

1. **Size-audit ownership (#100, #108, #109, #113, #114, #115).** Fixed on master (`closed_day_projection_tiering`
   ownership). Merging master resolved it. The only textual conflict on every branch was the generated
   `docs/roadmap/correspondence-index.md`, which was regenerated after each merge commit, never hand-merged.
2. **#112 sealer and live-candidate failures: real cause.** #112 carried the original 110q commit `08dd1b61`, which
   added a `market_tick_size_mixes` key to the economics drift report. `mm_live_candidate_cli` gates on
   `set(drift) == DRIFT_REPORT_KEYS`, so every candidate selection failed with `drift_shape`, and the sealers then
   reported `candidate economics acceptance does not match the sealed evidence`. The three "Regex pattern did not
   match" failures were expected refusals preempted by that earlier error. Master's re-landed 110q (`a8713efa`) removed
   the key from the report and kept tick mixes out of material drift. Merging master took master's version with no
   conflict. No test was changed.
3. **#114 task-inventory ratchet.** Master's 110n ratchet requires every registrar's default task name in
   `config/scheduled_tasks.json`. #114 adds `register_replay_bundle_export_nightly.ps1`, so I added the
   `WeatherReplayBundleExportNightly` row (owner `docs/operations/maker-replay-bundle.md`; state `active`; not expected
   disabled; registration unverified and gated on production adoption) and regenerated `OPERATING_REFERENCE.md`. No
   other branch adds an uninventoried registrar.
4. **111a plugin push, carried up the stack.** 111a pushed `134be204` to `codex/weather-maker-plugin-20260925`. I did
   not push to that branch. I merged it into #100 and carried it up. It changed three contracts the #100 exporter
   (`maker_replay_bundle.py`) consumed, so the whole stack went red until they were adapted:
   - `Sources(reader, day, markets)` now bounds rows to the run window; the exporter passes `args.date` and
     `args.markets`.
   - `evaluate_event`, `captured_book` and `reward_terms` take a `CaptureIndex` built once per segment instead of the
     raw capture list.
   - `providers()` now releases an event's raw support rows after building its providers. The exporter read those
     rows after evaluation, so it silently wrote no `plugin_input` or settlement records. It now copies each event's
     rows before evaluation and refuses (`support_rows_released_before_export`) if they were already released.
   - **Provenance gap closed.** `Sources` now streams the trigger journal and settlement ledgers through
     `Reader.lines`, which bypassed `ExportReader.read`. Those inputs were therefore absent from `input_hashes` and from
     the pre-export identity recheck. Hashing moved to `Reader.scan`, which both paths use. A visitor that stops early
     (band-token batches) records `prefix:<bytes>:<sha256>`, never a false whole-file hash, and a later partial read
     never replaces a whole-file hash. A new test pins this.
   - **#114** already rewrote the same `ExportReader` (release-root reads, `remember`, `paths`). The merge keeps both:
     `remember` now takes a digest, and `ReleaseSources` passes the date and markets to the new constructor.

### Group 2

- **#103, #104, #106 base.** These were based on `codex/integration-91a-110f-20260926`, which has landed. After merging
  master I retargeted them (and #105) to `master`, so each diff is only its own commits (#104's 66 files are its own
  clock consolidation).
- **#105 `hook`: real workflow bug on master.** `.github/workflows/host-load-hook.yml` checks out shallowly, then runs
  `agent_docs_audit`, which refuses shallow correspondence history. So any PR touching the hook paths failed. I added
  `fetch-depth: 0`, matching `ci.yml`. This fix would also be correct on master.
- **#125 new size warning.** Scheduling the seven D1-09 reports took `daily_refresh_reporting_steps.py` to 2,142
  lines. Rather than adding an ownership exemption, I moved the seven isolated-child adapters, unchanged, into the new
  module `weather.operations.daily_refresh_gate_report_steps`, returning the reporting family to its master size
  (1,999). The module-ownership map is updated. **This makes #125 roll-sensitive** (it already was, since it changes the
  daily-refresh chain).
- **#106 repo-health ratchets.** These went red only on master growth that landed after its reviewed seed `2db5220b`:
  - `schema_registry_data.py` reached 2,836 lines against its 2,829 ceiling (110k's `wu_orphan_cleanup_receipt`). I
    moved that spec unchanged to `schema_registry_recent_data.py`, the split route the size audit already names. This
    makes #106, previously tests/docs-only, **roll-sensitive**: it now touches a capture-imported schema shard.
  - `tests/market/test_exchange_economics_drift.py` (110q) contains one retired-family token match, `taker_only`, the
    Polymarket fee-schedule field. The ratchet deliberately freezes per-file counts, including fee vocabulary
    (`taker_only` is already frozen in `test_exchange_economics.py` and `exchange_economics.py`). Following the
    ratchet runbook, I added that single named allowance in commit `0dcaa8aa` and bound it as the new seed in
    `0baf9306`. **This seed needs production review before #106 joins an integration branch.** Every other
    allowance is byte-identical to the old seed.
- **#110, #117–#121.** The recorded runs were from 2026-09-27/28, against an older master. Merging master and
  re-running was enough. #110's only non-generated conflict was `docs/documentation-maintenance.md`, where I kept
  master's wallet/portfolio rows and #110's mission-registry rows.
- **#109** had a master-side failure (size audit), so I merged master into it as the handoff allows. Its
  `docs/research/maker-replay-*` bytes are unchanged against `bc9fd5b1` (`git diff --stat` is empty).

## For production

- **Exam enrolment 2026-09-30.** #112's `execution_manifest.source_hashes` binds the live bytes of `maker_core`, the
  plugin package, `maker_plugin_{runner,capture,sources}.py` and `maker_replay_bundle.py` at enrolment. The 111a push
  and the exporter adaptation above change those bytes relative to the heads production reviewed before. Enrol from the
  final heads, not earlier ones.
- **Not yet at `b0032a90`.** Group 2 PRs (and #106/#110) were merged with `164f12d0a`. Master's only later change is
  handoff docs; all are `MERGEABLE`, and integration regenerates the correspondence index anyway.
- **111a: two follow-ups, not fixed here.**
  1. `tests/market/test_maker_plugin_111a.py::test_shared_cas_matches_legacy` and #113's
     `test_actual_110l_export_and_settlement_carry_roundtrip` fail on Windows under pytest's default temp root: the
     `layout` fixture's CAS path reaches exactly 260 characters (MAX_PATH). Both pass with a short `--basetemp`, and
     Linux CI is unaffected.
  2. `ReleaseSources.for_event` (#114) returns a fresh dict each call, so 111a's build-providers-once optimisation
     never applies under the nightly export. This is correct, and it is no worse than before 111a, but providers are
     rebuilt on every call.
- **Local full suite.** The #100 full run through the wrapper passed 7,690 tests with one Windows load flake
  (`test_market_making_daily_roll::test_direct_start_and_supervisor_ensure_serialize_launch_decision`, which passes
  alone). Later iterations ran the full `tests/market` and `tests/maker_core` directories plus the audits per branch,
  with GitHub CI as the full gate.

## Update when

Append-only; correct in a later report.

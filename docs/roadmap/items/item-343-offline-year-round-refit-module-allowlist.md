# 343. Offline Year-Round Refit Module And Workstation Allowlist Line [OPEN 2026-11-03 - 343a SCORER ALLOWLIST LINE; 343b MODULE BUILT, EQUIVALENCE RUN PENDING]

Goal: give the lever-inventory row 28 year-round P3d_N refit (and later year-round history runs) a packaged
offline module under `src/weather/` and one line in the workstation offline-module allowlist, so that they run
through `scripts\ops\workstation_heavy.ps1` instead of a one-off guarded launcher.

Owner/package: `weather.calibration` (the new module), `weather.backtesting.evening_fix_scorer` (allowlist only) and `scripts/ops/workload_admission.ps1` (the allowlist
line), with the Codex hook mirror in `.codex/hooks/pre_tool_use_host_load.py`. Workstation research builds the
module; master owns the combo landing.

Source: master ruling 2026-11-03 on row 28's fits (relayed by the coordinator). Option 2, a one-off run outside
`workstation_heavy.ps1` through a guarded launcher derived from L47's reviewed `run_walk_guarded_v1`, covers the
first run only (DEV_WINDOW_LEDGER rows 114-118 note). Option 1 is this item. Prereg
`docs/research/row28-yearround-history-2026-11-02/prereg_row28.md` (sha256
`cb6d4e8da0ab5a144a185cf8dbaf777881402ea8a95db99f2a0e98f20a5e132b`) on
`claude/row28-yearround-history-20261102`.

Why this matters: the wrapper admits a weather-heavy job only when its module is in the offline list. At
`b7071ccfe`, `scripts/ops/workstation_heavy.ps1:138-147` reads `Get-WeatherWorkstationOfflineModule` and throws
"weather-heavy workload must be an offline training/replay module" (`:146`) for any other module, and for a
`--live`, `execute`, `place`, `cancel` or `promote` argument. The list lives in
`scripts/ops/workload_admission.ps1:611-667`, next to the B-look argument refusal (`:696`) and the command-line
test (`:898`); after item 17 (combo B), the S4U memory-commit guard parses this file every tick; workstation_pregate.ps1:82 and the wrapper dot-source it. The list classifies processes
(`:1176-1177`), so a parse error or a wrong entry there affects every guard tick, not only this lever. Each
one-off launcher is another reviewed script outside the shared admission path.

Precedent: `weather.calibration.r0_full_year` went the same way (allowlist entry
`workload_admission.ps1:649`, Codex mirror `pre_tool_use_host_load.py:84`, admission test
`tests/operations/test_r0_full_year_admission.py`).

Split (master ruling 2026-11-03, relayed by the coordinator): design (B), a pinned-runner entry point that runs a
reviewed runner file by sha, is REJECTED as a file-path loader in disguise. The item splits into 343a (built now)
and 343b (deferred, design (A)). **Until 343b lands, row 28's remaining stages stay on launcher v6 under the one-off
exception.**

The module name `weather.calibration.yearround_refit` is reserved here only. Until 343b no allowlist line and no hook-mirror
entry existed for it, and no test pinned it as admitted: an admitted name with no module behind it is a slot that
anything could fill. Its line lands with its module in 343b.

Checklist:

343a (branch `claude/item343-offline-refit-allowlist-20261103`):

- [ ] One allowlist line for `weather.backtesting.evening_fix_scorer` in `Get-WeatherWorkstationOfflineModule`
  (`scripts/ops/workload_admission.ps1`) and the matching entry in the Codex hook mirror (master 2026-11-03). The
  evening-fix Stage 1 score ran once as a direct run of `stage1_score_v1.py` (`ce70e3e8`) under a master one-off
  ruling, because the wrapper refused the scorer module ([item 337](item-337-no-metar-observed-floor-gap.md)).
- [ ] Admission tests beside `test_r0_full_year_admission.py` (`test_evening_fix_scorer_admission.py`): exact-name
  admission in both mirrors, sibling and live/promote refusals before any lease, and the B-look refusal kept
  (`b_scorer look` refused, `b_look_wrapper look` admitted). The full-list pin in `test_r0_full_year_admission.py`
  gains the entry.
- [ ] `README.md` (operator command catalog) notes the wrapper route for the scorer.
- [ ] Land through a combo with WS exact-tip suite evidence (the bounded suite at the combo's exact tip) and
  guard-parse evidence: the guard script parses the edited `workload_admission.ps1` cleanly and classifies the
  scorer as offline.

343b (BUILD GO, master 2026-11-03; branch `claude/item343b-yearround-module-20261103`, stacked on 343a; design (A),
fit_kind "forward" for row 28 candidate B; runbook [YEARROUND_REFIT.md](../../operations/YEARROUND_REFIT.md)):

- [x] The durable offline year-round refit module `weather.calibration.yearround_refit` under
  `src/weather/calibration/`, research-only and history-only: the stages, the arms and the output guard as a library,
  repo paths through `weather.paths` and config-driven roots, with no live, order or promotion path and no B-bound
  file edited (it may import them read-only).
- [ ] Its own review, and a real-data equivalence re-run against the frozen row-28 run's stages.
- [x] Its allowlist line and hook-mirror entry, landing with the module, with its own admission test; the B-look
  argument refusal stays in force for it.
- [x] `README.md` and the owning runbook for the new command in the same change.
- [ ] The real-data equivalence run on the WS under a new records root (STATE-SHA mode), after review; not
  yet run.
- Trigger (fired 2026-11-03): master's BUILD GO for the row 28 B forward refit.

Evidence (343a):

- Guard parse at `c8e9b611d` (WS, read-only): `Parser::ParseFile` reports 0 errors on `workload_admission.ps1`,
  `workstation_heavy.ps1`, `memory_commit_guard.ps1` and `workstation_pregate.ps1`; 51 modules listed, the scorer
  once, nothing named yearround; the scorer is classified offline and its `_x` sibling and `yearround_refit` are not.
- Master's combo-tip expectation: after B and A', the module count becomes 52 (A' adds
  `weather.calibration.b_drop_list`), with the scorer listed once and nothing named yearround. Master re-runs the
  guard parse at the combo tip on the host with B's `memory_commit_guard.ps1`.
- WS exact-tip suite: recorded in the combo's report (26 chunks of at most 25 files through
  `workstation_heavy.ps1 -Queue`).

Acceptance:

343a:

- `workstation_heavy.ps1 -Kind weather_heavy` admits `weather.backtesting.evening_fix_scorer`, and still refuses an
  unlisted module and the live/execute/place/cancel/promote arguments.
- The guard parses the edited file at the combo tip, with the evidence recorded in the combo's report.
- No allowlist line or hook-mirror entry names `weather.calibration.yearround_refit`.

343b:

- `workstation_heavy.ps1 -Kind weather_heavy` admits `weather.calibration.yearround_refit`, with the same refusals.
- A later year-round run needs no option-2 launcher; the row-28 option-2 exception stays a one-off.
- Train/serve parity, probability mass and release binding are unchanged: the module is offline research and
  serves nothing.

Status 343a (2026-11-05, closeout): **landed, activation checks pending**, in combo C (member `97c2bb824`),
master `984d783e6`, 2026-11-05 01:42.

Status 343b (2026-11-05, WS docs head; status only):

- In progress on the WS at landing tip `84b50a173` (branch `claude/item343b-yearround-module-20261103`: the merge
  of master plus a test-only exemption). (A), the fit, (B) and the suite are pending; it is not on master.
- The 343b fit pin `0e5c4f729e8bacfe8995a1533d96d0b5a71cd410adaa4ca654b737b7a6ea339b` is **SUPERSEDED**: its module
  sha changed. Its archive is kept at `C:\archive\row28b-forward-state\20261105T061242Z`.
- `--hours` dropped: 4b closed (master 11-04). Design Clarification 1 (2026-11-05) records the amended F3(a), the
  pre-imputation NBM date check and the run-procedure lesson:
  [design note](../../research/item343b-yearround-module-design-2026-11-03.md#clarification-1-2026-11-05-master-rulings-of-11-04-and-11-05).

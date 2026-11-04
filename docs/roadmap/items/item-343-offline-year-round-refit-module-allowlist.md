# 343. Offline Year-Round Refit Module And Workstation Allowlist Line [OPEN 2026-11-03 - MASTER OPTION 1; ROW 28'S FIRST RUN USES THE ONE-OFF OPTION-2 LAUNCHER]

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
test (`:898`). The one-minute guard parses that file on every tick and uses the list to classify processes
(`:1176-1177`), so a parse error or a wrong entry there affects every guard tick, not only this lever. Each
one-off launcher is another reviewed script outside the shared admission path.

Precedent: `weather.calibration.r0_full_year` went the same way (allowlist entry
`workload_admission.ps1:649`, Codex mirror `pre_tool_use_host_load.py:84`, admission test
`tests/operations/test_r0_full_year_admission.py`).

Checklist:

- [ ] An offline row-28 / year-round refit module under `src/weather/calibration/`, research-only and
  history-only. It reproduces the frozen row-28 run's arms from the frozen prereg, with no live, order or
  promotion path and no B-bound file edited (it may import them read-only).
- [ ] One allowlist line in `Get-WeatherWorkstationOfflineModule` (`scripts/ops/workload_admission.ps1`) and the
  matching entry in the Codex hook mirror, with an admission test beside `test_r0_full_year_admission.py`. The
  B-look argument refusal stays in force for the new module.
- [ ] Fold `weather.backtesting.evening_fix_scorer` into the same offline-module allowlist work, with the same review
  and combo (master 2026-11-03). The evening-fix Stage 1 score ran once as a direct run of `stage1_score_v1.py`
  (`ce70e3e8`) under a master one-off ruling, because the wrapper refused the scorer module ([item 337](item-337-no-metar-observed-floor-gap.md)).
- [ ] Land through a combo with WS exact-tip suite evidence (the bounded suite at the combo's exact tip) and
  guard-parse evidence: the guard script parses the edited `workload_admission.ps1` cleanly and classifies the new
  module as offline.
- [ ] Update `README.md` (operator command catalog) and the owning runbook for the new command in the same change.

Acceptance:

- `workstation_heavy.ps1 -Kind weather_heavy` admits the new module and `weather.backtesting.evening_fix_scorer`, and still refuses an unlisted module and
  the live/execute/place/cancel/promote arguments.
- The guard parses the edited file at the combo tip, with the evidence recorded in the combo's report.
- A later year-round run needs no option-2 launcher; the row-28 option-2 exception stays a one-off.
- Train/serve parity, probability mass and release binding are unchanged: the module is offline research and
  serves nothing.

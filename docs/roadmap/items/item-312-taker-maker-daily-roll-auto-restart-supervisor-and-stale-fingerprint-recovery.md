# 312. Taker And Maker Daily-Roll Auto-Restart Supervisor And Stale-Fingerprint Recovery [COMPLETE 2026-06-25 - BOT DAILY-ROLL ENSURE SUPERVISORS AND STALE-FINGERPRINT RECOVERY LIVE]

Goal: give the taker and maker daily-roll loops the same auto-restart
supervision the collection loops have, so a dead, hung, or stale-code bot loop
is relaunched on current code within minutes instead of staying dark until the
next daily fire.

Source: 2026-06-24/25 taker incident. The taker daily-roll pid 28700 was a
48 KB hung `pythonw` process that stopped writing useful artifacts at
2026-06-24T22:12Z and sat dead for roughly four hours with nothing restarting
it; a manual `start --force` was required to recover. It had also been launched
on a superseded source fingerprint (`b6bb5eb6c4fb17d5`, commit `7845aa24`) while
current code was commit `925448d2`, so even before it hung its evidence was
non-countable under current-code gates. The taker daily-roll
(`WeatherTakerBotDailyRoll`, 00:05) and maker daily-roll
(`WeatherMarketMakingDailyRoll`, 19:30) are each launched once per day with no
`ensure`-style supervisor, unlike the snapshot, CLOB, and observation-trigger
loops, which run `ensure` every 1-2 minutes and at logon.

2026-06-24 audit update: the Python/log audit found the gap active on both bot
families. `python -m weather.operations.taker_bot_daily_roll status` reported a
previous taker run quarantined as `STALE_HEARTBEAT_METADATA` before the current
forced recovery, while `python -m weather.operations.market_making_daily_roll
status` reported maker pid `34772` as `started` on commit `3242e26399be` with
source fingerprint `dc31a4c70a4f0228` even though the repo HEAD during the audit
was `fb2da2283d88`. The maker daily-roll status also still marked the run as
`counts_toward_live_forward_gate=true`, even though the latest run summary was
preflight-blocked by the current exchange-economics gate. Process-alive status
is therefore not enough to prove current-code, countable bot evidence.

Why this matters: a once-daily launch with no supervisor means a hung or
redeploy-orphaned bot loop burns settlement-scoreable calendar days until the
next scheduled fire, and a loop running superseded code produces evidence that
cannot count. Item 272 already detects taker artifact staleness and sets
`restart_recommended=true`, but nothing consumes that signal to actually
relaunch the loop.

Why it is not already covered: item 272 is taker-only and detection-only - it
recommends restart and quarantines stale folders but never auto-restarts, and
its root-cause classes do not include a stale code fingerprint. Item 311 gates
latest-tick evidence starvation but does not restart the process. Item 152 is an
active-day preflight and disk-liveness check, not a continuous supervisor. Items
161/307/95 supervise and stabilize the collection loops (snapshot/CLOB/
observation) and provide shared supervisor primitives, but none extends auto-
restart or stale-fingerprint recovery to the taker or maker daily-roll loops.

## Design

1. Add an `ensure`-style supervised relaunch for the taker and maker daily-roll
   loops, registered as a scheduled task at minute cadence and at logon,
   mirroring `register_snapshot_supervisor.ps1` / `register_clob_supervisor.ps1`.
2. Make `ensure` consume item 272's `restart_recommended` (taker) and the
   item-311 latest-tick starvation signal, and actually relaunch a dead, hung, or
   idle loop with `--force`, quarantining the stale run folder.
3. Add a stale-code-fingerprint check: when a running bot loop's
   `source_fingerprint`/commit differs from current HEAD, classify it
   `superseded_code` and restart it on current code so a redeploy cannot orphan
   the loop on non-countable stale code.
4. Extend useful-write liveness detection (item 272's taker work) to the maker
   daily-roll so both bots fail on stale tape activity rather than process
   existence.
5. Bound restarts with backoff and a restart budget (reuse item 95 / 307
   supervisor primitives) so a crash-looping bot roll cannot thrash, and surface
   restart cause, fingerprint, and last useful write in the daily-roll status and
   fleet observability.

- [x] Add a minute-cadence `ensure`/supervisor and registration script for the
  taker and maker daily-roll loops.
- [x] Make `ensure` consume `restart_recommended`/latest-tick starvation and
  relaunch dead/hung/idle loops with `--force`.
- [x] Add `superseded_code` stale-fingerprint detection and restart on current
  code.
- [x] Extend useful-write liveness detection to the maker daily-roll.
- [x] Bound restarts with backoff/budget and surface restart cause + fingerprint
  in status and fleet observability, with tests for dead-pid, hung-no-write, and
  stale-fingerprint restart paths.

## Completion Notes

Completed 2026-06-25. Added shared bot daily-roll ensure supervision in
`weather.operations.bot_daily_roll_supervisor`, with bounded restart budget and
backoff via the existing supervisor primitives. Taker and maker daily-roll CLIs
now expose `ensure`, write restart cause/current-code identity/last useful
write into status, and append JSONL diagnostics. Stale-code restarts classify as
`superseded_code`, terminate the previous matching Python process, and launch
with `--force`; stale-code taker runs force-retire the prior run folder even
when artifacts were otherwise fresh.

Maker daily-roll status now has taker-parity useful-write liveness for
`run_summary.json`/`quote_intents_long.csv`, latest useful-write reporting, and
quarantine-on-force for unhealthy latest run folders. Added
`register_taker_bot_daily_roll_supervisor.ps1` and
`register_market_making_daily_roll_supervisor.ps1` minute-cadence/logon Task
Scheduler registration scripts while keeping the existing once-daily launch
tasks intact. Fleet current-code soak now includes both bot daily-roll
supervisors and reports their restart budgets, stale-code restarts, status
paths, diagnostics paths, and repair commands without treating plain bot console
logs as JSONL integrity failures.

Validation:

- `python -m pytest tests/operations/test_taker_bot_daily_roll.py tests/operations/test_market_making_daily_roll.py tests/reporting/test_fleet_observability.py -q`
- `python -m pytest tests/operations/test_nightly_health_checks.py -q`
- `python -m py_compile src/weather/operations/bot_daily_roll_supervisor.py src/weather/operations/taker_bot_daily_roll.py src/weather/operations/market_making_daily_roll.py src/weather/reporting/fleet/fleet_observability_inventory.py src/weather/reporting/fleet/fleet_observability_loops.py`
- CLI help smoke tests for `python -m weather.operations.taker_bot_daily_roll ensure --help` and `python -m weather.operations.market_making_daily_roll ensure --help`.

Known unrelated validation blocker observed while checking nearby operations
tests: `python -m pytest tests/operations/test_schema_registry.py -q` still
reports pre-existing unregistered
`marine_contrast_calibration_v0.1` and
`pooled_feature_band_hgb_marine_contrast_v0.1` schema versions.

Acceptance: a taker or maker daily-roll loop that is dead, hung (no useful
writes), or running a superseded code fingerprint is automatically restarted on
current code within the supervisor cadence rather than left until the next daily
fire; restarts are bounded by backoff/budget; and the restart cause, fingerprint,
and last useful write are visible in the daily-roll status and fleet
observability, proven by tests for the dead-pid, hung-no-write, and
stale-fingerprint paths.

2026-07-13 rollover hardening: the 12-hour runtime monitor found the scheduled
`WeatherTakerBotDailyRoll` direct `start` path had bypassed the supervisor's
prior-date retirement. The July 12 worker therefore continued alongside the
canonical July 13 worker after midnight, consuming about 1.9 GiB of private
memory and continuing to grow non-countable prior-day artifacts. The verified
July 12 process tree was retired without deleting its evidence. The direct
start owner now command/date-verifies the recorded Windows process, terminates
the full launcher tree with `taskkill /T`, blocks the new launch if retirement
fails, and preserves the prior status for operator recovery. Focused regression
coverage exercises successful rollover, fail-closed rollover, exact process
matching, and tree-aware termination; all 29 taker daily-roll tests pass. This
closes the observed gap without changing scheduler registration or trading
permission.

2026-07-13 long-loop retention remediation: the same monitor measured the
current-date taker worker growing from 727.5 MiB to 3,349.1 MiB private memory
in 107 minutes. `run_loop` retained every full, increasingly cumulative tick
payload even though its public contract returns only the latest payload. The
loop now retains only `last_payload`; a weak-reference regression proves prior
tick payloads become collectible during the next iteration, and the complete
taker test file passes 70 tests plus 5 subtests. The existing current-code
supervisor adopted the repair as `superseded_code`, retired the old tree, and
the replacement returned to healthy `POLICY_NO_EDGE` paper evidence on the new
source fingerprint. Item 322 owns the separate incremental-persistence and
bounded-resource soak work; this completed lifecycle item does not claim that
broader performance debt is closed.

2026-07-13 loaded-host liveness hardening: at the monitor boundary, an
unbounded scheduled settlement step drove physical load to 98% and caused the
taker supervisor's PowerShell/CIM command-line lookup to time out. The exact
current-date taker tree remained alive and continued writing fresh, COUNTABLE
`POLICY_NO_EDGE` evidence, but the binary lookup result had conflated probe
failure with a confirmed missing PID and persisted a false terminal
`pid_missing` status. Command-line discovery now retries and returns a
tri-state result. Non-destructive health may preserve liveness from the
independent Python process-image check when command identity is temporarily
unavailable; stop and tree-retirement paths still require an exact module/date
match and remain fail closed. A persisted false-dead status self-recovers only
when the recorded PID is live and artifact activity is fresh. After host
pressure cleared, the scheduled supervisor restored the same tree to
`already_running`, `pid_alive=true`, with its latest useful write current; it
did not restart or delete evidence. The combined taker/maker daily-roll suite
passes 48 tests, with compile and diff checks passing.

Related: items 16, 95, 152, 161, 239, 272, 307, 311, 322.

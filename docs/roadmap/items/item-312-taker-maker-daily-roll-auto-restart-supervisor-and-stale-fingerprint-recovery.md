# 312. Taker And Maker Daily-Roll Auto-Restart Supervisor And Stale-Fingerprint Recovery [OPEN 2026-06-25 - BOT LOOPS HAVE NO ENSURE-SUPERVISOR; A HUNG OR STALE-CODE ROLL GOES DARK FOR HOURS]

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

- [ ] Add a minute-cadence `ensure`/supervisor and registration script for the
  taker and maker daily-roll loops.
- [ ] Make `ensure` consume `restart_recommended`/latest-tick starvation and
  relaunch dead/hung/idle loops with `--force`.
- [ ] Add `superseded_code` stale-fingerprint detection and restart on current
  code.
- [ ] Extend useful-write liveness detection to the maker daily-roll.
- [ ] Bound restarts with backoff/budget and surface restart cause + fingerprint
  in status and fleet observability, with tests for dead-pid, hung-no-write, and
  stale-fingerprint restart paths.

Acceptance: a taker or maker daily-roll loop that is dead, hung (no useful
writes), or running a superseded code fingerprint is automatically restarted on
current code within the supervisor cadence rather than left until the next daily
fire; restarts are bounded by backoff/budget; and the restart cause, fingerprint,
and last useful write are visible in the daily-roll status and fleet
observability, proven by tests for the dead-pid, hung-no-write, and
stale-fingerprint paths.

Related: items 16, 95, 152, 161, 239, 272, 307, 311.

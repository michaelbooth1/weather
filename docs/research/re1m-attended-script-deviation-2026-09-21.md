# RE-1M attended-script deviation — 2026-09-21

**Approved in this task; no live session exercised. Mission 84b implements and qualifies the attended script; the linked report owns its verification verdict.**

The only requested treatment deviation from the
[frozen RE-1 registration](https://github.com/michaelbooth1/weather/blob/a14ce80dc0189ddbcd1de1af11111f27e07bfe99/docs/research/liquidity-reward-epoch-preregistration-2026-09-20.md)
is orders placed and cancelled by an attended script instead of by hand.
The owner replied directly in this task: "approved, look at .env.example".
The [mission 84a handoff](../roadmap/workstation-handoff-2026-09-84a-run-the-reward-test-attended.md)
limits that exception to International Polymarket, at most three sessions in
total, none after September 30, 2026, with its non-widenable financial and
operational limits. The owner must start each live command in their terminal
and type its confirmation. This does not authorize agent-started trading or
change the sealed lane.

The required live-session evidence statement is:
"owner confirmation: recorded in the session journal".
It is a requirement for a future session, **not a claim that such a journal
exists**. No session has occurred in this mission, and no confirmation was
fabricated or copied into a supposed live-session record.

Mission 84a stopped at the handoff's Python/JavaScript parity condition.
See the [84a report](../roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md).
No selection, prediction or treatment change was substituted to avoid that
stop. The RE-1A place-and-hold addendum was not adopted.

## Outcome-blind corrections, September 21, 2026 (84b)

The [84b ruling](../roadmap/workstation-handoff-2026-09-84b-parity-resolved-build-the-script.md)
accepts that stop and corrects the JavaScript reference before any session or
earnings observation. Python's full displayed competing depth applies at
selection, when none of our hypothetical shares exists. Own size is removed
only during observation of a resting quote. The counterexample at YES
0.40 / NO 0.57 with 100 competing shares, reward minimum 20 and rate 45/day
therefore has share 1/6 and predicted reward 1.875, below the frozen 2.0
threshold. The old premature subtraction produced 2.25.

Reward scoring and re-quotes use the midpoint of reward-minimum-sized
levels. With YES bid 0.33 x 100, ask 0.36 x 100, and a one-share bid at
0.34, that midpoint remains 0.345. A held YES 0.33 / NO 0.64 quote has
share 0.20 and reward 0.006250/minute at 45/day. The plain midpoint 0.350
gives share 25/173; it is recorded every minute as `plain_mid`,
`share_many_plain_mid`, and accumulated `P_many_plain_mid` sensitivity.
True best asks still govern immediate pre-submit safety. The corrected
reference and Python agree; the 17:20Z historical selection does not contain
the raw depth needed to repair its overstated shares.

Every order carries GTD expiration at fixed end plus 60 seconds; no
replacement is submitted with fewer than 180 seconds left. The script adds
heartbeat and explicit cancellation, without claiming an unconditional 15.8
dollar loss ceiling against arbitrary bugs or failure. The unconditional
ceiling is the controlled account balance; the owner's run card recommends
a dedicated account with about 50 dollars.

The owner separately answered **"Allow read-only credential loading"** in
this task. `collect-payout` may therefore load `.env` in memory for
authenticated reads, in addition to the already authorized live and panic
modes. It cannot submit, cancel or send a heartbeat. Rehearsal never loads
credentials. No credential was read by the agent.

These corrections change neither the frozen ranking threshold nor the
treatment's distance window, duration, session limit or verdict thresholds.
The script's separate RE-1M path does not change any sealed-lane module,
capability, grant, sealer, host assignment or test.

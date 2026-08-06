# The observed-floor fail-closed flip — deliberately deferred, 2026-08-04

Lock-day checklist item 5 (`RELEASE_ONE_BUILD_RUNBOOK.md` §2) reads: *"Flip the observed-floor
safety monitor from alert-only to fail-closed."*

**It was not done on lock day, on purpose.** This file records why, and exactly what doing it
requires, so the next session does not either skip it silently or attempt it blind.

## It is not a config toggle — it needs code

The monitor's own CLI has the switch:

```python
# src/weather/reporting/source_gates/observed_floor_safety_monitor.py:480
parser.add_argument(
    "--fail-closed",
    action="store_true",
    help="Turn ALERT/BLOCK findings into a nonzero exit and pipeline hard stop. "
         "The temporary pre-lock default is alert-only.",
)
```

and the chain step reads it from its args:

```python
# src/weather/operations/daily_refresh_trading_steps.py:733
fail_closed=getattr(args, "fail_on_observed_floor_safety", False),
```

But the chain's arguments are not editable in place. `scripts\ops\daily_refresh.ps1` receives them
as `ProductionEvidenceArgumentsB64` — a base64 scheduler-argument contract fixed at **task
registration** time. And `scripts\ops\register_daily_refresh.ps1` has **no parameter that can emit
`--fail-on-observed-floor-safety`**: its production evidence arguments are built only from
`CapturedInputParityServed`, `CapturedInputParityReplay`,
`ProductionReadinessServedArtifact` and `ProductionReadinessServedRoute`.

So flipping the flag requires:

1. adding a switch to `register_daily_refresh.ps1` that appends the flag;
2. re-registering `WeatherDailySettlementPromotionRefresh` **and**
   `WeatherEveningEvidenceRefresh` with every mandatory parameter reconstructed correctly;
3. verifying the re-encoded argument contract round-trips.

That is a code change plus a scheduler re-registration of the daily chain — not a lock-day
formality.

## The stronger reason: it arms a new hard-stop while nobody is watching

`hard_stop_pipeline` is `bool(fail_closed and status != "PASS")`. Turning it on converts any future
floor ALERT into a **chain hard stop**.

This project already knows what that costs. A single isolated-step failure on 2026-08-02 —
`maker_paper_score` losing an exact size binding to a live-appending file — stopped stage A at step
9 and skipped stage B entirely, taking out a full day of settlement, tiering and learning. One
transient condition, one dead day.

Today the monitor reads `status=PASS`, `enforcement_mode=alert_only`, `hard_stop_pipeline=False`,
`evidence_blocker_count=0`, over 2,165 snapshots with 2,159 enforced floors. **Flipping it changes
nothing about today; it only changes what happens the next time something goes wrong** — and the
operator was out, with two unattended agent runs already scheduled.

Arming a novel failure mode into an unattended pipeline is the wrong risk to take on the one day
nobody can respond to it.

## What is actually lost by deferring

Very little, and it is bounded. Fail-closed does not make the floor stronger — the floor is
enforced either way, on all 2,159 snapshots. It only changes whether a floor *finding* halts the
chain instead of recording an alert. Alert-only still records; the evidence is still captured; the
monitor still runs as chain step 12.

## When to do it

**After the release build lands and someone is available to watch the next chain run.** Sequence:

1. add the switch to `register_daily_refresh.ps1`;
2. re-register both chain tasks and verify the round-tripped argument contract;
3. run one chain cycle attended, and confirm the floor step still reports `PASS` with
   `enforcement_mode=fail_closed` and `hard_stop_pipeline=False`;
4. only then leave it unattended.

It is roll-free work (`.ps1` plus a scheduler registration), so it does not need a quiet window —
it needs an audience.

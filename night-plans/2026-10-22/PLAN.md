# 10-22 night (2026-10-21 -> 2026-10-22): A9 leftovers, then DLv2 S2+S9

Workstation summary for master. Master lands; nothing here is a merge. Integration branches only.
The order was decided by master-agent on 2026-10-15 at 16:3x EDT, following the workstation's proposal.

## Order

1. **A9 leftovers first.** These are the units the 10-21 H-block did not finish before 03:15. It writes them to its
   10-22 leftovers file (plan `claude/o9-a9-plan-20261015`, r6 `6a27044f5`, §7). They run under the shared lease
   with the same 03:15 outer deadline. Anything still unfinished goes back to master; it is never stretched past 03:15.
2. **DLv2 S2+S9** via `scripts/ops/quiet_window_merge.ps1`, inside 01:00-04:00, and only once the lease is free.
   If there are no A9 leftovers, S2+S9 goes first. Get the verdict from `scripts\ops\roll_verdict.ps1 -Branch <b>`
   first; it is expected to be ROLL-SENSITIVE (88a recorder modules).
3. **Restart step: the following night, 10-23, 00:30-01:00.** First run
   `scripts\ops\restart_maker_evidence_capture.ps1` as a report, then run it with `-Apply`. The existing PT5M trigger
   restarts the recorder. Then `status.ps1 -Json` must show `maker_evidence_code` CURRENT. Never run
   `register_maker_evidence_capture.ps1`: it writes PT1M over the live PT5M.

Prerequisites: stack6 (10-18), then S1 `658592038`, then the roll_verdict fix `d69842131` must have landed first.
S2+S9 is based on S1.

## Head

| Branch | Sha | Notes |
| --- | --- | --- |
| `claude/dlv2-s2-s9-pilot-20261015` | @@S2S9SHA@@ | on S1 `658592038`; pilot ships DISABLED; built-in reward cadence per §Data hold |

## Data hold (until UTC 10-30)

The code freeze lapsed after 10-14. The data hold stays until UTC 10-30:
- add files only;
- never write to held segments;
- the 12 built-ins are enumerated from `all_specs()`;
- config adds recorder-only rows only.

Built-in reward-read cadence: @@CADENCE@@

## Pilot switch-on

This is a separate event from the code roll. It is a config-only change, made only after the 24 h verification:
- req/s ≤ 0.4;
- the latch fraction;
- no pilot token in the panel journals.

## Dry-run measurements (workstation, public endpoints only)

@@DRYRUN@@

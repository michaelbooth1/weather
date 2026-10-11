# N8 landing night 2026-10-12 -> 2026-10-13 (workstation summary)

**Prerequisite:** N7 (`claude/integration-20261012-n7-rf` a36798574) has landed on master. Both N8 heads are stacked on it.

| Order | Head | Sha | Class (static) | Members | Pre-gate (base 8ea5d089b) | Journal pinned touch |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `claude/integration-20261013-n8-rs` | c6977df5f | ROLL-SENSITIVE, 01:00-04:00 quiet window | DST-H1 + DST-M1 (`claude/dst-h1-m1-m2-utc-20261011` 70efaed11) | PASS, 9655 passed / 64 skipped / 0 failed | none |
| 2 (last) | `claude/integration-20261013-n8-rf2` | 1c64f9173 | ROLL-FREE, guarded, 00:30-09:00 | RS + DST-L6/L7/L8/L11/L15 (`claude/dst-lows-ps-20261011` 5b1311169) + DST-M7/L13 (`claude/dst-m7-l13-suite-20261011` e44ebcaa4) | PASS, 9668 passed / 64 skipped / 0 failed | none |
| fallback | `claude/integration-20261013-n8-rf` | 9bf466af1 | ROLL-FREE | N7 + lows + M7/L13 without H1 | PASS, 9624 passed / 63 skipped / 0 failed | none |

Targeted queue runs: rs 921 passed, 2 skipped, 8 xfailed; rf2 500 passed, 16 skipped, 3 xfailed; rf 456 passed, 16 skipped.
Landing preflight (`--tests none`): the only FAIL on either head is the strict correspondence-index check, which also fails on master by design. Landing path: rs ROLL_SENSITIVE, rf2 ROLL_FREE_GUARDED.

## Defender verdicts
- H1/M1: FAIL (the 11-01 early-hour PASS->BLOCK regression) -> fixed -> PASS-WITH-NOTES. Note: if a ledger series ever carries one non-Toronto stamp, the window falls back to that stamp's offset; nothing writes one today.
- PowerShell lows: PASS-WITH-NOTES. quiet_window_merge.ps1:3094 is left unfixed (spent reconciliation mode, fails safe).
- M7/L13: PASS-WITH-NOTES, fix round applied.

## Landing constraints
- **rs:** quiet window; must not land while a live attempt is sealed (`streak_status.py` is on the live-path attestation list); must land before 11-01; if it lands after any 11-01 ledger row is written, regrade those rows.
- **rf2:** land LAST, and only when no frozen integration attempt is still due. The suite and attempt-suite hashes are frozen per attempt. A failed attempt caused by this head needs successor class `manual_reviewed_change`. Any legacy gated-merge task frozen with the old `suite_gated_quiet_merge.ps1` hash must be re-set-up.
- **Registrars:** the L7 and L11 changes take effect only at the owner's next registration; nothing was re-registered.

## Docs light path (any time)
`claude/host-python-upgrade-runbook-20261011` 65387f54d: the PROPOSED host Python 3.11.0 -> 3.11.9 runbook. Defender rounds 1-3 FAIL, round 4 PASS, polish applied. It needs owner sign-off; the report lists host reads H1-H9 for master and 12 owner decisions.

## Owner questions
1. DST-M2 (held): should `cache_age_minutes` be fixed in UTC before 11-01? It feeds the `source_*_age_minutes` features of the shadow variant and the primary model's last-good `wu_history` cache reuse. Recommendation: yes.
2. Retire OD30 once H1 and the L7/C1 re-registrations are settled.
3. Python upgrade runbook sign-off.

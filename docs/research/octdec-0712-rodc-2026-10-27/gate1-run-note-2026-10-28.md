# R-ODC gate 1: launcher fix before the single run (2026-10-28)

Written 2026-10-28 before gate 1 runs, under master's OK relayed by the coordinator. Master's conditions: change
only the `tr` line, re-verify every other pin, then run once and stop on any non-verdict failure.

## The refusal (01:55:11 EDT, 2026-10-28)

- `C:\t\l16odc\run_gate1.sh` (sha256 `28ade0089e152730700a993b5d7e2c004e195ad61823a1dcb9fd00028752dc24`)
  ended with `EXIT=1`.
- The workstation wrapper refused the arguments before admitting the job: "workstation-heavy Python
  argument contract is not canonical base64" (`scripts\ops\workstation_heavy.ps1` line 94).
- **No read, no score.** No Python process started, and no `gate1.json` or rows file was written.
- The refusal files are kept in `C:\t\l16odc\rodc\refused_015511\`.

## Cause and the one-line fix

The launcher's `tr -d` held a literal newline where `\r` was intended. The script was written by a shell
that expanded the escape, so the statement wrapped onto a second physical line. The carriage return printed by
`mkargs_gate1.py` therefore stayed in the arguments, and the wrapper's canonical-base64 check rejected it.

- **The fix:** only that statement changes, to `tr -d '\r\n'`. Because of the bug, the old statement spans
  physical lines 18-19, so `diff` reports `18,19c18`:

  ```text
  < ARGS=$(... mkargs_gate1.py "$SUMS" "$RULESHA" "$COMMIT" | tr -d '
  < ')
  ---
  > ARGS=$(... mkargs_gate1.py "$SUMS" "$RULESHA" "$COMMIT" | tr -d '\r\n')
  ```

- **New sha256:** `b3254adb6ea9a1200ca677cd6cb9f3a5c0054813c2407b3ff88aa3db586a1edc`.

## Pins re-verified before the run (all unchanged)

| Pin | sha256 |
| --- | --- |
| rule `rule_rodc.md` | `40ea3a94d08601dc7c571e59fdf38c893ec9a313bdcbcebde214e1db3f9daf93` |
| env worktree `claude/rodc-run-env-20261027` (clean) | `9403d87bca6156613e7507ffe7fb45fda758e1a4` |
| `mkargs_gate1.py` | `ba9f454c70bfe8f8771dd86ea97c0d67e78ccd693aa927f2391771cd189ac0e5` |
| 2021-23 backfill seal (SHA256SUMS) | `7dad81ce0b12679bc5a1b33a16671936cbccbff1d836be56ff5176545cac8a94` |
| `seal_2123.sh` | `bf343f3580f3995d5971ae9c92b0f38556f1e5159daee955947ef86511431bbe` |

Gate 1 runs once from this state. The verdict is labelled "vs the Aug-Sep-centred frozen blend (item 341)".
Any non-verdict failure stops the run, and there is no second fix without master.

## G2 note (2026-10-28)

G2 must use a comparator fit for the season it scores, or report vs MG-1 as primary (master ruling 10-28); written before any G2 code.

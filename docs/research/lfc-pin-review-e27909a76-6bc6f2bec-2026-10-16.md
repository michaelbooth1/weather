# Review: LFC range `e27909a76..6bc6f2bec` (session-0 pin to session-1 pin candidate)

Reviewed range: `claude/lfc-hardening-r2-20261014`
`e27909a764e96931c9ea38d6fba8202af8fc2b67..6bc6f2bec854468226acfec93c62441c173e348d`. It has 11 commits in a linear
chain, and the base is an ancestor of the tip. Seven files change: `lfc_cli.py`, `lfc_constants.py`, `lfc_fees.py`,
`lfc_pilot.py`, and three test files.

Method: I used `git diff`/`show` to read the code, and read the SDK source in the workstation venv
(`polymarket_client` 0.6.0) for the signing path. The review was read-only. I made no venue or reader call and opened no
`.env*`, `config/local` or `data\` file. Line numbers are `git show 6bc6f2bec:<path>` numbers. The signed texts read on
origin/master are clarification D §D8/§D10 and DECISION_LOG row 2026-10-13 "LFC session 0 moved". The format follows
the delta-3 review (`320ac22a9`, `live-fill-calibration-code-delta3-review-2026-10-09.md`), with the severities
blocker / should-fix / nit asked for in this review.

## Verdict: PASS

- **Code in the range: PASS. There is no blocker.** No commit weakens a start gate, deadline, budget, open-order or
  foreign-order check, heartbeat/dead-man rule or phrase.
  - Every behaviour change is one of two kinds:
    - a new refusal, which applies to session 0 only;
    - a correction that lets an existing end code through instead of relabelling it.
  - The range does not touch L, `BUDGET_PUSD`, sizes, caps, GTD, `cancel_leg`, `cleanup`, the ledger schema or the
    signing path.
- **Session-1 effect of the range:** only two changes run on the counted path:
  - `lfc_fees.py:289-292`: a `HoldEnd` or `LivePathSecurityError` raised inside the fee reads now propagates;
  - `lfc_pilot.py:525-527`: the duplicate `refusal=` keyword is dropped.

  Both make end codes truer. Every scope-date change (S3-S8) and the early 88a load sit behind `profile.session0` or
  `args.session0`. There is no session-0 assumption that breaks session 1. The session-0 evidence written on
  `e27909a76` still satisfies the new code: `session0_passed`/`session0_attestation` are unchanged, are not bound to a
  commit, and no reader of `scope_sources` re-validates old selection tables.
- **Session-1 neg-risk readiness:** none of this code is in the range. I found two should-fix items to carry into the
  session-1 driver and runbook (SF-1, SF-2). They are not code fixes in this range.

---

## 1. Per-commit findings

| Commit | Subject | Finding | Severity |
| --- | --- | --- | --- |
| `8b66a2cb5` | S5: read the session-0 scope once | `_selector` (`lfc_cli.py:480-483`) reads the bytes once and hashes, lists and dates those same bytes (`conditions_from_bytes`, `shadow_scope_date_refusal(raw=)`). Correct. `run_live`'s early M1 check (608) is a separate read, as designed (defence in depth). The hashed and dated bytes are the selector's. | OK |
| `4c6cc1099` | S4: linked or non-regular condition file refuses | `read_condition_file` (354-363) goes through `validate_regular_nonreparse_file`, which checks every path component for reparse points, resolves strictly and requires `is_file()`. `LivePathSecurityError` maps to `condition_file_not_regular`. An absent path refuses too, so it fails closed. A plain `OSError` from `read_bytes()` after validation is not mapped; it is still a refusal, with a different label. See nit N-3 on test coverage. | OK |
| `09ffe8f43` | S5 test matches by basename | Test only. Correct for Windows normcase/resolve differences. | OK |
| `2f5ff5230` | S7: a date-shaped name token that is no date refuses | `lfc_cli.py:441-446`: an invalid 8-digit run now raises `shadow_scope_date_unreadable` instead of being skipped. This is stricter. Side effect: any non-date 8-digit run in the file name refuses (N-4). | OK |
| `971bb097a` | S6: selection records the checked scope date | `sources['shadow_scope_date'] = utc(checked).date()` (489-491). It enters `selection.json` and `digest(table)`, and so the `go` phrase and `attempt.json`. `validate_session0_table` passes `scope_sources` through unchanged (`lfc_pilot.py:285`), so the rebuild still reproduces. Session 0 only. | OK |
| `810f1cf71` | S3: re-check the scope date at the recorded start | `session0_start_date_refusal` (461-467) runs after the confirmation and before `session_identity`, the directory and any ledger row (648-651). On refusal, the client is closed by the `finally` and no ledger close-out runs, because `session_id` is None. The check is needed: `start_allowed` would accept a 00:05Z D+1 start, because the hard stop is per start day. A missing `scope_sources` or date refuses. Residual sub-second window: see N-2. | OK |
| `e9d6156c9` | S8: `shadow-scope-union` writes `"date"` | `{"conditions": [...], "date": D}` (423). `conditions_from_bytes` ignores the extra key. The guard checks the field and the name together, and a renamed file is still refused on the field. | OK |
| `cadcbbd75` | R2-S1/S2 test reflow; deadline before scope | Test only. It pins `session0_deadline_passed` ahead of a stale scope at the deadline instant. | OK |
| `ce56fbb03` | Re-point "clarification E" citations | Comments and docstrings only (`lfc_cli.py:33-35`, `lfc_constants.py:64-65`, one test comment). The cited row exists on origin/master (`DECISION_LOG.md:188`). `SESSION0_DEADLINE_UTC` is unchanged (2026-10-25T00Z). Session 1 is not gated by it (`session0_deadline_refusal` returns early unless `profile.session0`). | OK |
| `03d6448f1` | Delta-3 N-11/N-12 | **N-11:** `except HoldEnd: raise` ahead of `except Exception` in `FeeEvidenceBooks.fee_evidence`. A control-checkpoint end (`fixed_end`, `fill`, `geoblock`, `heartbeat_stale`, `venue_deadman_*`, `foreign_open_order`, …) now keeps its own code. In the minute loop, `transient(HoldEnd)` is false (`re1_resilience.py:9-24`; no status, no cause), so it reaches `except HoldEnd` in `Session.run` and ends with cleanup. **N-12:** the selection-phase `lfc_fee_rule` row filters `'refusal'` out of `opening_fee` (`lfc_pilot.py:525-527`). On the normal path (no code) the row is byte-identical to before, so journal integrity holds. With a code, it now raises `HoldEnd(code)` before the first submit instead of `TypeError`. Tests cover both. Residual: see N-1. | OK |
| `6bc6f2bec` | Should-fixes 1-4 | (1) test reflow; (2) N-11 test through `snapshot` with a checkpoint counter; (3) `LivePathSecurityError` (ambient proxy) inside fee reads propagates (`lfc_fees.py:289`). Mid-session that ends `exception` with cleanup, exactly as the same error does from the base `/book` reads, instead of `fee_fields_unreadable`. Both end the session, so no gate is weakened. At selection it aborts before the confirmation. (4) `load_conditions(args.extra_conditions)` in the early session-0 block (612-613), before `pilot_root`, the mutex and credentials. The new import in `lfc_fees` (`live_path_security`) is already imported by `mm_stage2_selection`, so it adds no dependency. | OK |

## 2. Findings by severity

### Blockers

None.

### Should-fix (session-1 readiness, outside the range; carry to the driver and runbook, not to this pin)

**SF-1. The neg-risk collateral allowance is not checked per spender.** `re1_transport.py:450-452`:
`OwnerVenue.balances` refuses `collateral_allowance` only when the **maximum** of all `allowances` values is below
`reserve_cap`.
- A wallet approved for the standard CTF exchange but not for the neg-risk exchange (`0xe2222d27…`) or adapter passes
  this gate.
- The first neg-risk POST would then be rejected by the venue (`submit_acknowledgment`/`exception`). Nothing rests, so
  no money moves, but a counted session number and a local date are consumed.
- The owner's wallet has traded weather (neg-risk) markets by hand, so this is unlikely.
- Fix: before `go`, the driver prints the allowance for the neg-risk exchange and adapter keys from the preflight
  `available_collateral`/allowance evidence. Alternatively, a later code item could check the spender named by the
  selected row's `neg_risk`.

**SF-2. Neg-risk signing is chosen by the SDK, cannot be bound after signing, and has no in-repo test.**
- `OwnerVenue.submit` (`re1_transport.py:463`) calls `create_limit_order(**request)` with no neg-risk argument.
- SDK 0.6.0 resolves `neg_risk` from its own CLOB market metadata (`_internal/actions/orders/limit.py:117`,
  `resolve_exchange_address`) and picks the exchange.
- `SignedOrder` has no exchange or verifying-contract field, so the existing `signed_order_binding` check cannot
  compare the signing domain with the selected row's `snapshot.rules.<token>.neg_risk`.
- No `tests/market/test_lfc_*` or RE-1 submit test uses a `neg_risk: true` row.
- Failure mode: if the SDK picked the wrong domain, the venue rejects the signature and nothing rests. That is fail
  closed, but it costs a session.
- Fix for session 1 (D8 says session 1 is the first neg-risk signing):
  - the driver prints `neg_risk` for both tokens from the PASS preflight's `selection.json` before `go`, and again from
    the session's `selection.json` after the run;
  - the runbook names a first-post `submit_acknowledgment` or `exception` on a neg-risk band as a signing-domain
    suspect, to report rather than retry.
- The `go` prompt (`confirmation`, `lfc_cli.py:511-531`) still prints neither `neg_risk` nor the fee class. The driver
  must add both.

### Nits

- **N-1 (`lfc_fees.py:289-296`):** only `HoldEnd` and `LivePathSecurityError` pass through. Any other exception raised
  by the control checkpoint inside a fee read is still relabelled `fee_fields_unreadable`. An example is a non-HoldEnd
  `RuntimeError` re-raised by `check_fills` (`lfc_pilot.py:652-655`). The session still ends with cleanup, so only the
  label is wrong. A tighter fix wraps the checkpoint itself, so that any exception from `checkpoint()` propagates.
- **N-2 (`lfc_cli.py:647-651`):** the S3 check uses the CLI's `started`, not `PilotSession.start`, which is taken a
  moment later. A start straddling 00:00:00Z by less than a second could pass both the S3 check and `start_allowed`
  while the session runs on D+1 with the D scope. Session 0 only, and session 0 is done.
- **N-3 (test coverage, `tests/market/test_lfc_cli.py`, S4 test):** this host refuses `os.symlink` (WinError 1314), so
  the real-link branch is skipped silently, without a pytest skip, and only the monkeypatched
  `validate_regular_nonreparse_file` path ran. No test here exercises a real junction through
  `_assert_no_reparse_components`.
- **N-4 (`lfc_cli.py:426,441-446`):** S7 refuses any non-date 8-digit run in the scope file name, for example a
  build-id suffix. This fails closed. The runbook should keep the plain `shadow_scope_YYYYMMDD.json` name.
- **N-5:** the N-11 test pins the exact checkpoint count (`len(calls) == 11`), so it will break if the snapshot reads
  are reordered. This affects test brittleness only.

## 3. Gate and integrity checklist

| Question | Result |
| --- | --- |
| Start gates, deadline, budget, open/foreign-order checks, heartbeat/dead-man, phrases weakened? | No. New refusals only (S3, S4, S7, early 88a). Deadline order is pinned by a test. The phrase still binds `digest(table)`, and for session 0 the table now also carries the scope date. |
| Ledger integrity | No ledger schema or row change. The S3 refusal precedes `session_start`, so it writes no orphan row. |
| Journal integrity | The `lfc_fee_rule` selection row is unchanged on the success path. On refusal it is now written once with a single `refusal` before `HoldEnd`. |
| Session-0 assumptions breaking session 1 | None found. Counted runs refuse every session-0 flag (`check_flags`), take none of the new branches, and read session-0 evidence through unchanged functions. |
| Neg-risk signing for session 1 | Unchanged by the range. SF-1 and SF-2 above. |
| Untested paths | N-3 (real reparse point on this host). The SF-2 neg-risk submit path. N-1 (the remaining checkpoint exception types). |

## 4. Tests

Run on the workstation (DESKTOP-RFCD2GH) through
`scripts/ops/workstation_heavy.ps1 -Kind pytest -Queue` (main checkout wrapper; queue ticket 1, waited 0 s) in a
temporary detached worktree `C:/wt/rv6bc` at `6bc6f2bec` (`GIT_LFS_SKIP_SMUDGE=1`). The run used `--rootdir`/`-c` on
the worktree, `--basetemp C:/wt/bt-rv6bc` and the venv interpreter, over
`tests/market/test_lfc_{analysis,cli,fees,ledger,panel_exclusion,pilot}.py`.

**Result: 306 passed, 0 failed, 0 skipped, 0 errors (34.1 s).** The worktree code was the code under test: the new
tests (for example `test_the_start_date_check_reads_the_recorded_date`) need `session0_start_date_refusal`, which
master does not have. The worktree and the basetemp were removed afterwards, and `git worktree prune` was run.

## 5. Carried forward

- Pin for session 1: `6bc6f2bec` plus the driver commit. The driver review (`6bc6f2bec..<driver tip>`) should check
  SF-1 and SF-2. The driver must print `neg_risk` (both tokens), the fee class and the neg-risk allowance before `go`.
- N-1 and N-2 can land with any later tip. Neither is needed for session 1.

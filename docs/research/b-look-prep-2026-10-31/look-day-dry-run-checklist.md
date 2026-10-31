# B look-day dry run: runbook checklist (synthetic inputs only)

Dated research note by lane L8, 2026-10-31. It is not canonical and not a B edit. It changes no B-bound file, and it
does not edit `B_FORWARD_TEST_DESIGN.md` or `docs/research/mg2-composite-binding-2026-10-25/`.

**Scope.** The look-day order is: MG-1 look, then the label transfer (binding plan §9.6), then the B scorer
(`b_scorer.py` sha256 `f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439`), then the post-look
analysis of master's ruling (b). This checklist walks that order. For each step it lists every refusal or VOID path
and the synthetic test that exercises it.

The dry run is one queued focused-test run. It uses only `tmp_path` synthetic worlds; no repository data, outcome,
label or price is read.

Line and section references are to origin/master `1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de`.

## 0. The dry-run command (workstation, queued)

```powershell
$bt = "C:\t\l8blook\bt-$(Get-Date -Format yyyyMMddTHHmmss)"
$argv = @("-m", "pytest", "-q", "--basetemp", $bt,
  "tests/calibration/test_mg1_look.py", "tests/calibration/test_b_scorer.py",
  "tests/calibration/test_mg2_composite.py", "tests/calibration/test_b_post_look_serial.py")
$b64 = [Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes((ConvertTo-Json -Compress $argv)))
.\scripts\ops\workstation_heavy.ps1 -Kind pytest -Queue -MinAvailableMemoryGB 3 `
  -PythonPath (Resolve-Path .\venv\Scripts\python.exe) -ArgumentsBase64 $b64 -RepoRoot (Get-Location)
Remove-Item -Recurse -Force $bt
```

- The wrapper takes the Python arguments as canonical base64 of a UTF-8 JSON array (`workstation_heavy.ps1` lines
  91-105); the host load policy owns the rest. If the wrapper refuses, stop and report.
- Pass means every listed test passes at the scorer sha above. Record the wrapper receipt and the four test file
  sha256s beside the run.

## 1. MG-1 look (`weather.calibration.mg1_look`)

Before the step:
- [ ] The MG-1 window has closed: `MG1_LAST` = 2026-11-28 in `weather.mg1_reserved_window`.
- [ ] The MG-1 scoring is built into the entry point and re-registered (the registered `1e691c58…` cannot score:
  its `run` refuses).
- [ ] **Expected in any rehearsal before the clarification: VOID 5 fires.**
  - B's `MG1_LOOK_ENTRY_SHA256` is the `UNRECORDED` sentinel BY DESIGN (master ruling (iii), 2026-10-31). It
    equals no sha, so every receipt fails VOID 5 (`b_scorer.py` lines 127-133).
  - Master writes the dated B-1 clarification that sets the constant once MG-1's look receipt exists
    (2026-11-29..12-12).
  - So, until that commit, a full synthetic chain ends in `VOID` with conditions `[5]` (or with 5 among them).
    That VOID is the correct result, not a defect. `test_void_5_fails_a_receipt_whose_entry_sha_is_not_the_recorded_one`
    exercises it.
  - After the clarification, VOID 5 must no longer fire on the real receipt.

Refusals and VOIDs, with the synthetic test that exercises each (`tests/calibration/test_mg1_look.py`):

| Path | Test |
| --- | --- |
| `run` refuses while the scoring is not built | `test_the_run_command_refuses_until_the_scoring_is_built` |
| Rule sha is not the signed `MG1_RULE_SHA256`; a start marker or receipt already exists | `test_refusals_before_anything_is_read` |
| A non-registered `__main__` or a wrong sha cannot stamp | `test_only_the_registered_entry_point_can_stamp` |
| `looked_at_utc` is on disk before the first outcome join | `test_looked_at_is_stamped_and_on_disk_before_the_first_outcome_join` |
| A crash after the first join still spends the look | `test_a_crash_after_the_first_join_still_spends_the_look` |
| One look per rule; a written receipt passes | `test_a_written_receipt_passes_and_one_look_per_rule` |
| Hand-made or hand-edited receipts fail `receipt_problems` | `test_hand_made_or_hand_edited_receipts_fail` |
| The entry point is registered at its current sha | `test_the_entry_point_is_registered_at_its_current_source_sha` |

Output: `data/mg1_look/receipt-<rule sha>.json`, copied into the repository record the same day.

## 2. Label transfer (binding plan §9.6; B-1 §9, step 2)

This is one host export of the venue-rule winner, `promotion_countable` and capture-time `p_market_yes`. It covers
the input-countable dates in order, until 45 countable dates are found. It goes to a separate inbox with
`b_transfer_manifest.json` (schema `b_transfer/1`, files `labels.parquet` and `market.parquet`, plus
`transferred_at_utc` and `mg1_look_receipt_sha256`).

Before the step:
- [ ] The exporter exists. It is master's to build ("Master builds and registers the host exporter", binding plan
  §9.7). No repository writer of `b_transfer/1` exists at `1a78e1ba0`; B only reads it.
- [ ] The transfer happens after the MG-1 receipt's `looked_at_utc`.

B checks the transfer at the look (`tests/calibration/test_b_scorer.py`):

| Path | Condition | Test |
| --- | --- | --- |
| Manifest missing, wrong schema, wrong files or malformed | VOID 6 | `test_missing_manifest_voids_and_fewer_than_40_survivors_void` |
| Dates not increasing, before D0, not 45 countable, dates after the 45th, differing from MG-2's set | VOID 6 | `test_manifest_conditions_cover_missing_order_count_and_other_dates` |
| Manifest does not bind this MG-1 receipt; transfer not after `looked_at_utc` | VOID 5 | `test_void_5_uses_the_bound_receipt_and_the_instant_inside_it` |
| Receipt absent or hand-edited | VOID 5 | `test_void_5_passes_on_a_written_receipt_and_fails_absent_or_hand_edited` |
| Receipt entry sha is not the recorded `MG1_LOOK_ENTRY_SHA256` | VOID 5 | `test_void_5_fails_a_receipt_whose_entry_sha_is_not_the_recorded_one` |
| A file time is never used | VOID 5 | `test_void_5_ignores_the_receipt_file_time` |
| A label or price file is altered against the manifest; extra dates or rows | VOID 6, outcomes opened | `test_hash_control_receipt_time_and_manifest_voids` |

## 3. MG-2 score, then the B look (`b_scorer look`, sha `f941628a…`)

Before the step:
- [ ] The B scorer sha is frozen.
- [ ] The §(a) control has passed and is receipted (ledger row 68).
- [ ] The §3 drop list is final.
- [ ] MG-2's `score` has written `mg2_look.json`. Its own guards are in `tests/calibration/test_mg2_composite.py`:
  `test_scorer_refuses_reserved_dates_without_a_dated_owner_decision`,
  `test_owner_decision_still_needs_mg1_look_receipt_and_a_closed_window`,
  `test_post_window_dates_need_no_decision_but_need_d0_and_n`, `test_the_score_look_also_requires_parity` and
  `test_second_look_is_refused`.

`look_guard` refusals come before anything is read, and they do not consume the look (`test_b_scorer.py`):

| Order | Refusal | Test |
| --- | --- | --- |
| 1 | No MG-1 look receipt (checked first) | `test_the_look_refuses_first_without_mg1_look_receipt` |
| 2 | Rule block not single or complete; unknown keys; values differ from the scorer's; d0 after d0_latest | `test_rule_block_must_be_single_and_complete`, `test_rule_with_an_unknown_key_refuses`, `test_rule_values_must_equal_the_scorer_constants` |
| 3 | A bound field is FILL or malformed | `test_any_bound_field_not_in_its_format_is_unfilled_and_refuses_the_look`, `test_rule_without_the_l6_state_field_refuses` |
| 4 | The MG-1 window has not closed; a second look | `test_unfilled_rule_open_window_and_second_look_refuse` |
| 5 | Consumed markers: a new `--out`, drop list or copied inputs | `test_the_look_is_consumed_so_a_new_out_or_drop_list_cannot_rescore`, `test_copied_inputs_and_a_new_out_are_refused_by_the_fixed_per_rule_marker`, `test_the_fixed_marker_root_is_repository_owned` |
| 6 | Last-in-hour vectors instead of gate vectors (MG-2 C7); the 45th date is under embargo | `test_the_look_refuses_last_in_hour_vectors_and_an_unsettled_45th_date`, `test_embargo_ends_at_the_latest_market_local_midnight` |
| 7 | A refusal does not consume the look | `test_a_refusal_before_anything_is_read_does_not_consume_the_look` |

After the guard, every exit writes `b_look.json` and `b_look_receipt.json`:

| Path | Result | Test |
| --- | --- | --- |
| MG-2 §7 condition failed or unrecorded (VOID 1); pre-look reads (VOID 4). The transfer is never opened | VOID, `outcomes_opened` false | `test_pre_outcome_voids_never_open_the_transfer` |
| Bound hash (VOID 2), control receipt (VOID 3), receipt time (VOID 5), manifest (VOID 6) | VOID | `test_hash_control_receipt_time_and_manifest_voids`, `test_bound_hash_problems_pass_on_a_consistent_binding_and_name_each_break`, `test_control_receipt_must_pass_at_this_scorer` |
| Drop list disagrees with the coverage recomputed from the transfer | VOID 6 | `test_a_drop_list_that_disagrees_with_the_transfer_voids_6` |
| Fewer than 40 surviving dates | VOID 7 | `test_missing_manifest_voids_and_fewer_than_40_survivors_void` |
| Exception before or after the outcomes open | ABORTED; consumed | `test_a_crash_before_outcomes_open_is_aborted_with_outcomes_closed`, `test_a_crash_after_outcomes_open_writes_an_aborted_receipt_and_consumes` |
| Degenerate primary interval | VOID | `test_a_degenerate_primary_interval_is_void` |
| PASS / FAIL / INCONCLUSIVE (NOT-WORSE when U < +0.0027, design line 162) | the verdict | `test_keep_kill_table`, `test_full_look_scores_ten_markets_and_writes_one_receipt` |

Output: `b_look.json` (its `decision` holds `estimate`, `ci95`, `verdict` and `label`), and `b_look_receipt.json`
(`b_decision`).

## 4. Per-date extraction, then the post-look analysis (ruling (b))

Module: `src/weather/calibration/b_post_look_serial.py`, FROZEN at `fa380db09980692f6afe50eb48b949b6c21aa88a`
(sha256 `0c485d6e347dc11c95a7cf756e760e292db12536e663c61c1eda5d9650d80bed`, pinned in `master-ruling-b-post-look.md`).

- [ ] Run it only on a scored verdict. It refuses VOID, ABORTED and any other verdict.
- [ ] Inputs: B's `b_look.json` (or its `decision` object), plus a per-date 07-16 table of S_t (the sum of cell
  differences) and n_t (cell count) for B's surviving dates. Optionally add the 07-12 and 13-16 tables for the
  descriptive VAR(1).
- [ ] **The per-date extractor (master ruling (i), 2026-10-31: PERMITTED).** `b_look.json` carries only
  aggregate `rows`, so the per-date S_t and n_t come from a separate extractor.
  - It runs in the SAME look session, immediately after the B scorer, on the SAME sha-pinned `b_transfer` bytes the
    scorer consumed. It reads no byte B did not.
  - It outputs only the per-date S_t and n_t (07-16, plus the 07-12 and 13-16 splits), receipted with B's look.
  - It must reproduce B's printed Δ.
  - It imports `build_table` and `arm` read-only and edits no B-bound file.
  - It is being built by this lane (its sha goes here once frozen). A look-chain clarification note puts it on the
    closed list.
- [ ] Refusals (`tests/calibration/test_b_post_look_serial.py`):
  - a repeated date, non-ISO date, non-positive or non-integer n_t, or non-finite S_t;
  - fewer than 3 dates, or fewer than 2 consecutive-date pairs;
  - zero residual variance;
  - B's estimate is not sum(S) / sum(n) of the table (to 1e-9);
  - a verdict outside PASS, FAIL and INCONCLUSIVE;
  - an existing `--out`.
- [ ] Output: B's verdict and label copied unchanged; `fragile_label`; rho_hat, rho_used, VIF parts, SD(e), t and
  U_adj; and the module sha256.

# Item 341 January serving: refusal paths and options

Status: note for a ruling (L8, 2026-10-30), on the held branch `claude/jan-wrap-fix-20261029`. It is to be ruled by
master and the owner before 2026-12-14.

- The fix commit `cf33cd71b15effe8315b7c86323589a084ce339a` and this note stay unlanded until 2026-12-14 or later.
  Both files the fix changes are B-bound release files (`mg2_composite.RELEASE_FILES`).
- `SERVE_COVERAGE` stays `("08-01", "12-31")`.
- Everything here is read-only code analysis plus synthetic tests. No date after 2026-09-29 was read.

What the fix does:

- Both serve copies of `nearest_centre` now measure the month-day distance on a 365-day circle:
  - `mg_serve_core.nearest_centre`, used by `mg_serve_core.state_features`;
  - `mg2_p3d_n.nearest_centre`, used by `mg2_p3d_n.serve_distribution`.
- A date outside coverage is refused rather than snapped to a far centre:
  - `mg_serve_core` raises `ServeCoreError` outside 08-01..12-31;
  - `mg2_p3d_n` raises `P3dNRefused` outside its training coverage 08-01..12-16.

## 1. Callers, propagation, and why nothing crashes

**Production code cannot load the P3d_N path.**

- `mg2_p3d_n` and `pooled_residual_model` refuse to import from these packages: `weather.operations`, `.market`,
  `.model`, `.serving`, `.trading`, `.capture`, `.sources`, `.execution`, `maker_core` and `app`. They also refuse
  on the capture host, through the `r0_ols_floor_challenger` guard (`_refuse_production_import`).
- `mg_serve_core` may be imported on the host. Its only importers are two research modules, `l6_own_state` and
  `mg2_composite`; it has no other importer in `src/`, `app/`, `scripts/` or `tools/`.
- No capture loop, collector, supervisor, live executor or maker module imports any of these modules. So no
  refusal in this note can reach capture or a live loop.

**Every caller, on the fix tip:**

| Callee | Caller | Reached in January? | What happens |
| --- | --- | --- | --- |
| `mg2_p3d_n.nearest_centre` | `mg2_p3d_n.serve_distribution` | **No.** Its only caller, `emit_rows`, first checks `in_training_coverage(target_date)`, the same test that `nearest_centre` refuses on. | The row is counted under `outside_training_coverage`, listed in `coverage_fallback`, and skipped. |
| `mg2_p3d_n.serve_distribution` | `mg2_p3d_n.emit_rows`, from `mg2_composite.post_records`, from `mg2_composite.emit` (CLI `emit` / `check`) | Only inside coverage | `emit` writes `mg2_post_coverage_fallback.jsonl` (`reason: outside_training_coverage, slot: mg1`). `compose` gives the row to MG-1, because no `post` row exists for it. |
| `prm.nearest_centre` (research; no wrap, unchanged) | `prm` dev scorers (Aug-Sep centres, dev keys ≤ 09-29); `mg2_p3d_n.golden` on the fixture centres | No; research and dev only | Not served. Any research reuse on January dates must not use it, because it still snaps to a far centre. |
| `mg_serve_core.nearest_centre` | `mg_serve_core.state_features`, from `mg_serve_core.state_distribution` | **No serve caller exists.** `mg_serve_core` is Stage A (it is not rewired yet), so these run only in tests. | `ServeCoreError` would go to the caller. There is none today. |
| `prm.state_features` / `prm.state_distribution` (research) | `prm.forward_fit`'s self-check on training rows | No; training rows are in coverage | Not served. |

**If a refusal were reached anyway** (defence in depth):

- `emit` turns `P3dNRefused` into `Mg2Refused`. `mg2_composite.main` then prints `{"refused": ...}` and exits 2.
  `b_scorer` also catches `Mg2Refused`.
- That would be a clean refusal of the whole emission, not a crash. It is still worse than the per-row MG-1
  fallback, which is why the coverage pre-check matters.

**Requirement for MG-3 or any future wiring of `mg_serve_core.state_distribution`:**

- The caller must check `in_serve_coverage` first, or catch `ServeCoreError` per row, and send the row to MG-1.
  It must never let one January row abort the run.
- The ratchet test below fails when a new caller appears, so this requirement is seen at the time of wiring.

**One January gap that does not refuse: the pre-13 L6 arm.**

- `l6_stack.predict` serves `v2 + a + b·(n − v2)` with no date check. The L6 nowcast `n` comes from the frozen L6
  own-model HGB, which was trained without January rows and takes `doy` as a raw feature.
- January's `doy` (1-31) lies below every trained value. So HGB treats January as the earliest fitted day of year:
  there is no wrap, and it is a silent extrapolation.
- The effect is bounded by `b` in [0, 1], and nothing crashes. But this arm is not covered by any refusal; see
  option 1.

**Proof (focused tests, this branch):** `tests/calibration/test_jan_serve_fallback.py`.

- `test_january_rows_fall_back_to_mg1_without_raising`: rows dated 2026-12-31, 2027-01-05 and 2027-01-31 go
  through `emit_rows` with `nearest_centre` patched to fail if called.
  - Nothing is emitted, and nothing raises.
  - All three rows are counted and listed as coverage fallback.
  - `compose` gives every one to `mg1`.
- `test_no_serve_caller_of_the_core_state_functions`: only `mg_serve_core.py` and `pooled_residual_model.py`
  contain `state_features(` or `state_distribution(`.
- The run: with `tests/model/test_jan_wrap_fix.py` and `tests/calibration/test_mg2_p3d_n.py`, 42 passed via
  `workstation_heavy.ps1 -Queue` on 2026-10-30, exit 0.
- Existing coverage: `test_a_date_past_12_16_falls_back_to_mg1_and_is_logged_per_row` already covers 12-17.

**Not affected:** B's 45 countable dates run from D0 2026-10-29 and end by 12-12, so all of them are inside
coverage. The MG-1 forward shadow has no month dependence: it uses the layout's `v2_mean`, `v2_stddev` and floor
only.

## 2. January serving options (for the 12-14 ruling)

Today, without the fix, the P3d_N afternoon slot already falls back to MG-1 from 12-17. With the fix, both serve
copies refuse January cleanly. The open question is what should serve January from 2027-01-01.

| Option | What it is | Cost | Risk | Earliest serve |
| --- | --- | --- | --- | --- |
| **1. MG-1 for January** | Land the fix as is. P3d_N's slot goes to MG-1 from 12-17, as today. Add a January refusal to the pre-13 L6 arm, so that every hour serves MG-1. | No fit and no new data. One small release-file change after 12-14 (the L6-arm coverage check, plus a test) and a release re-binding. | Lowest. It gives up whatever gain P3d_N/L6 has over MG-1 (forward-unmeasured until B's 12-13 look) for about 6-7 weeks. | 2027-01-01 |
| **2. Extend coverage via the wrap fix** | Widen `SERVE_COVERAGE` and `TRAINING_COVERAGE` across the year end (say to 01-31). The frozen Aug-Dec state then serves January from its nearest centre, which is 12-09: the forward state has no 12-24 centre. | No fit. It needs a rule amendment to C5, because coverage is the training range by rule, plus a new binding. Before serving, run a cheap dev check: the frozen state on January 2022-26 history, which it never trained on, against MG-1. The records for centres 01-08 and 01-23 already exist (`C:\t\l2\records`, 11 markets each). | High without that check. Serving 2027-01-31 would use the 12-09 centre's bias and normal (53 days away), and HGB would extrapolate in `doy_sin` beyond 12-16. The check makes the risk visible. | After the check and the amendment; mid-December is possible |
| **3. Winter retrain** | Refit P3d_N (`prm.forward_fit`) with centres through the winter: add 12-24, 01-08, 01-23 and 02-07. Or adopt a full-year state like the P3F arm. | Data: the full-year PIT corpus union `621bcd8e…` (EF §10z) and the records. 01-08, 01-23 and 02-07 exist; **12-24 does not** (11 market files to build, heavy, under `workstation_heavy`). The fit is short. Gates: pre-registration and a ledger row (a new candidate, so +1 multiplicity); history LOYO on 12-17..02-07 for 2021-25 against MG-1 and against option 2; the C1/C2 parity and golden tests; a new state sha and binding. | Medium. The history evidence is favourable: P3F (full year, with Jan-Jul centres) − P3 = −0.004 [−0.014, +0.006] in-season (EF §10aa), so a full-year fit does not hurt. But no forward evidence on winter dates can exist before January itself, so any January serve is unvalidated forward. | History gates are possible before 12-14. Forward-validated only after a forward window, effectively February. |

**Recommendation: option 1 for January 2027.**

- Its cost is near zero, and January cannot get a forward-validated alternative in time.
- The L6-arm refusal belongs in the 12-14 landing, together with the wrap fix, so that January is MG-1 for every
  hour and not a silent `doy` extrapolation.
- If master wants a winter lever, run option 2's dev check first, as the one lever. It needs no fit and no new data.
  - If the frozen state does not beat MG-1 on January history, close it, and record it in the exhaustion register
    with a "Reopen if" line.
  - Only if it is close but biased should option 3 be registered, and that is the larger job: it needs the 12-24
    records and a new candidate.
- Neither option 2 nor option 3 should serve before its gates. MG-1 stays the January default until one passes.

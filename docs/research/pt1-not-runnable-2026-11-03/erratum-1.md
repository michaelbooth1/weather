# PT-1 NOT RUNNABLE receipt: erratum 1 (master ruling R21, part (1))

- **Create-only.** Written by WS lane L59 on 2026-11-03 on master's order ("A grep is not a trace", applied by master
  to its own R21). It amends the attribution in R21 (1) and in `receipt.md` beside it. **The receipt is not edited**
  (raw sha256 `8c45c8d99dabf1e38b21ad3ebd6e1b015a723b54054dd73d72e2373686cf7c35`). Ruling source:
  `C:\t\rulings-20261101\rulings.md` sha256 `2499b5afec7a258378da9235689b594ae72a7c9f627d79c3b8c64ad489e2b44d`, :179.
- **Code only.** Citations are to `claude/mg1-b-rulings-docs-20261103` @ `e2369a4a60a51dd874aa6d5bef609efabf80409f`.
  No data was read and nothing was fitted.

## What was wrong

R21 (1) and the receipt say that C-PT's pre-13 L6 arm "has training coverage only to 12-16". **That attribution is
wrong.** In code, 08-01..12-16 is the **post-13 P3d_N** slot's training-coverage gate. Rows outside it fall back to MG-1
(`src/weather/calibration/mg2_p3d_n.py`:318, :321-323, :469-472).

The receipt also cites `l6_own_state.py`:53-55 for the served L6 state. That file fits the Aug-Sep primary-month state
(`upstream_obs_screen.py`:66).

## What is right

- **The served pre-13 arm.** It is the season-matched L6 own-model state: the HGB fitted on Oct-Dec 2021-25
  (`src/weather/calibration/mg2_composite.py`:14, :786; DEV_WINDOW_LEDGER row 46).
- **No date gate on the pre-13 arm.** Every snapshot before `SWITCH_HOUR` = 13 goes to the pre arm
  (`mg2_composite.py`:53, :433-441).
- **Rule 6 still fails.** The rule asks for "training coverage that reaches the last forward date"
  (MODEL_IMPROVEMENT_METHOD.md:163-164).
  - The served state's training months are Oct-Dec, so January forward dates are not covered.
  - The widest covered reading is PT_D0 12-13..12-31: **19 dates**. That is below rule 6's 20 and below the draft's 30.
  - PT-1's window runs to about 01-25/26, so coverage never reaches its last forward date.

## Verdict

**UNCHANGED: PT-1 with C-PT is NOT RUNNABLE.**

- Rule 6 fails on the corrected attribution, as above.
- Rule 4, R21 (2), holds independently: MG-1 cannot fill January. On dev its blend R is 1.0017 against floor-only
  1.0010, with w 0.008 (`docs/research/market-blend-l11-2026-10-25/README.md`:21, :24).
- The reopen rule and register row X106 are unchanged.

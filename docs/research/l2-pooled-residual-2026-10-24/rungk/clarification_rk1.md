# R-K Clarification RK-1: gate 1 in two halves, and the LOYO incumbent control

Written 2026-10-25, before any HRRR row has been joined to an outcome. It applies to `rule_rk.md`
(sha256 `21b5dfe1870c03bcab143903b8fccc37a446c49de97b3889377039c7c8327221`) and changes no gate, threshold,
feature, arm or kill.

1. **Gate 1 runs in two halves.** The coordinator directed that gate 2 (LOYO, 2021-25 rows only) run before L13's
   2026 dev corpus exists.
   - **Gate 1a (before gate 2):** on the 2021-25 corpus and the h13-16 training rows:
     - training coverage ≥ 0.95;
     - zero used messages failing their identity check;
     - zero TMP values outside [−60, 130] °F;
     - zero selections failing the point-in-time check (availability + 10 min ≤ h:00) or the window
       [h:00, 17:00 local], and zero with a snapshot other than h:00 local.
   - **Gate 1b (before gate 3):** the same checks on the 2026 dev corpus, plus dev coverage ≥ 0.95 on the h13-16
     layout rows.
   - Both halves are inputs only. Neither can be influenced by a LOYO result. Failing either stops R-K without a
     kill.
2. **LOYO incumbent control (a refusal, not a gate).** R-K's B_N and P3d_N_fix LOYO rows must reproduce R-J's
   `C:\t\l2\rungj\emit\loyo_rows.jsonl` exactly: identical (hour, year, market, date) keys and every Brier and
   log-loss within 1e-12. If not, gate 2 is not read.
3. **Outputs.** Gate 1a and gate 2 write `C:\t\l2\rungk\loyo\` (`rk_loyo_audit.json`, `loyo_rows.jsonl`). The dev
   emit writes `C:\t\l2\rungk\emit\` as in the rule.
4. **Code.** The joiner is `rk_hrrr_columns`, `rk_columns` and `rk_training_columns`. The LOYO run is
   `rung_k_loyo` (CLI `rung-k-loyo`). The inputs-only schema audit is `rk_hrrr_audit` (CLI `rk-hrrr-audit`). All
   are in `src/weather/calibration/pooled_residual_model.py`, with `RK_RULE_SHA256` recorded.

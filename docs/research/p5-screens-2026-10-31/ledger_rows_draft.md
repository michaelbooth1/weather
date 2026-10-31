# P5 screens: dev-window ledger row text (draft, written before any rule or computation)

Status: draft for the coordinator (lane L17, 2026-10-31). Nothing here is a result. The row numbers were
provisional (final per Amendment A2): 92 is the highest row on any remote ledger branch at the time of writing
(`origin/claude/successor-batch-20261030`), so 93, 94 and 95 are the next free numbers. The coordinator
renumbers at merge-forward if another lane claims them first. Each row is inserted into
`docs/operations/DEV_WINDOW_LEDGER.md` as `pending` before its first scored row, then filled.

**Amendment A1 (2026-10-31, pre-run).** The coordinator's rulings were applied (F2 KEEP; W1 stays
under R15; A4 synthetic controls confirmed as CONTROLs; run bases recorded), and so was the MIM §5 rule 6 /
checklist (f) power instruction.

- **All three rows: verdict NOT RUN, UNDERPOWERED.**
- No arm reaches power 0.5 at half its dev effect on its own scale. Each rule's section (d) gives the
  compliance line.
- Each row's Headline and Verdict cells read `not run (UNDERPOWERED, MIM §5 rule 6)` instead of `pending`.
- The numbers 93-95 are PROVISIONAL. L15 assigns the final numbers in the assembled ledger and records a
  renumber note.

**Amendment A2 (2026-10-31, pre-run; master's edge-size power ruling).** A kill-only read runs only if
its power AT EDGE SIZE is ≥ 0.5; the verdict is "KILL at edge size" or "SCREEN" only. A2 supersedes A1's
"all three rows NOT RUN" line. Final row numbers (coordinator): **93 = (c), 94 = (a), 95 = (b)**; they are
no longer provisional.

- **Row 93 (c):** ρ scale, edge ρ 0.2236, power 1.00 (0.9998 at the most conservative SE). RUN after
  admission. Cells read `pending`.
- **Row 94 (a):** Brier against the market (the w-gate legs bind), edge 5% of the market's Brier, power
  0.305 (00-06), 0.28 (07-12), 0.18 (13-16). NOT RUN. Cells read
  `not run (edge-size power 0.305 / 0.28 / 0.18 < 0.5)`.
- **Row 95 (b):** bucket Brier against the incumbent, relative scaling through dev R_L6 1.1528 (disclosed),
  edge δ 0.00562 at the SYN bar (0.149 B-style), power 1.00. RUN after admission. Cells read `pending`.
- The arithmetic is in each rule's Amendment A2.

Evidence class of all three rows: SCREEN. A pass earns a forward pre-registration only. It is never a
promotion, a release input or an edge claim.

Shared conventions used below:

- dev means 2026-07-31..09-29. Burn-in is 08-01..08-14 and the scored dates are 08-15..09-29.
- Rule files are under `docs/research/p5-screens-2026-10-31/`.
- The branch is `claude/p5-screens-20261031` off `origin/master` @ `1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de`.
- The code is pending: a new research module per row, on a run branch, admitted by the coordinator before any run.

## Row 93 (task P5 (c)): ECMWF ENS member spread against the market

| # | Date | Lane | Branch @ tip | Rule (sha256 or commit) | Type | Candidate | Headline delta [95%] | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 93 | 2026-10-31 | L17 | `claude/p5-screens-20261031` (dev-window kill-only P0; this row is written before the rule and before any computation; 93 is the next free number across remote ledger branches, row 92 being X36 Oct-Dec). Code is pending: a new module through the cleared `loyo_screen` entry point; the module diff, its sha256 and the test plan go to the coordinator before any run | `docs/research/p5-screens-2026-10-31/rule_ens_spread_p0.md` (sha256 pinned at commit). Machinery: rule_mr_sweep `85f8192c`, sections 1-5. Input: local G2 cache `data/research/free_sources/ecmwf_ens/points.parquet`, sha256 `bd761fa52869d244addda7fb3746276e1eb6aad2416ac2fdc3291750d7320a7e` (171 runs, 0 errors; not rebuilt or re-downloaded) | dev 2026-08-15..09-29 market residuals, local 07-12 (ENS-SD-0712, 00Z run of D) and 00-06 (ENS-SD-0006, 00Z run of D-1). **Prior reads disclosed:** G2-a and G2-b (row 13, X5) already read the dev ENS member MEAN with outcomes against MG-1 and t3-r3, never against the market. `points.parquet` already holds `ens_sd_f`, which G2 built but never scored. **Availability is modelled** (run + 9 h, from the open-data release time), not a capture receipt. **The daily-max proxy under-reads the maximum** (it is the maximum over three 3-hourly steps) | ENS member spread against the market (X5's reopen line "ENS spread as spread information", the R9 family): type S, sign +, K = 2 (its own arm, not pooled with rows 78, 81 or 85-92). Calibration-matched disagreement placebo, BH q 0.10, survivor needs a Delta lower bound > 0; w = 0 identity and the w gate only for a survivor, in its own block. A4 synthetic sign control: SYN+ must SURVIVE and SYN- must read Delta < 0, or the run is VOID. **Kill line:** a KILL closes the ECMWF open-data ENS member SD of the 00Z daily-max proxy against the market at 00-06 and 07-12 on dev. It reopens only with a captured ENS feed and a new rule on dates disjoint from dev | pending | pending |

## Row 94 (task P5 (a)): pooled sub-bar w-gate read

| # | Date | Lane | Branch @ tip | Rule (sha256 or commit) | Type | Candidate | Headline delta [95%] | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 94 | 2026-10-31 | L17 | `claude/p5-screens-20261031` (dev-window SCREEN; this row is written before the rule and before any computation; 94 follows row 93). Code is pending: a new research module that imports the members' frozen emitters read-only and does no network I/O; the module diff, its sha256 and the test plan go to the coordinator before any run | `docs/research/p5-screens-2026-10-31/rule_pooled_subbar_wgate.md` (sha256 pinned at commit). Machinery: rule_mr `37cb46be` (w gate, `market_blend.pool`) and rule_mr_sweep `85f8192c` (P0, Delta, placebo, BH). Power gate: PREREGISTRATION_CHECKLIST (f) draft (`claude/s5-power-futility-gate-20261030`) | dev 2026-08-15..09-29, capture-time market. **SELECTION DISCLOSED: the eight members were chosen because their dev point estimates were helpful** (review `acaf441b`, takeaway 4). A pass therefore cannot be read as evidence that any member carries information. Every member has already read these dates with outcomes, against MG-1, served, L6, t3-r3 or its own twin (rows 7, 61, 62 and 71; X8, X11, X17 and X19); F2's construct has also read them against the market (row 91, KILL) | POOLED: per block, one candidate = the equal-weight log pool of that block's members' band vectors. 07-12: R-Q A, R-I, X17 blend, A2, upstream ASOS. 13-16: F2 (subject to the row 91 conflict, rule section 3). 00-06: R-PD, R-N. Type: model distribution against the market, K = 3 blocks (K = 2 if the coordinator drops F2 before the run), BH q 0.10. PASS = BH rejection AND Delta lower bound > 0 AND the w gate (all four rule_mr legs). Controls: w = 0 identity, reproduction of every member's recorded headline, A4 synthetic positive and its negation. **Kill line:** a KILL closes pooling of these members on dev; it never reopens any member | not run (edge-size power 0.305 / 0.28 / 0.18 < 0.5) | not run (edge-size power 0.305 / 0.28 / 0.18 < 0.5) |

## Row 95 (task P5 (b)): Oct-Dec history LOYO batch

| # | Date | Lane | Branch @ tip | Rule (sha256 or commit) | Type | Candidate | Headline delta [95%] | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 95 | 2026-10-31 | L17 | `claude/p5-screens-20261031` (history-only LOYO; this row is written before the rule and before any computation; 95 follows row 94). Code is pending: a new research module on a run branch off `9ee8a243f55efe314ad5a1b1b33dd0cf0816508e` (row 92's tip, which carries `season_matched_l6`, `cool_season_audit`, `successor_odc_low` and `upstream_obs_screen`); the module diff, its sha256 and the test plan go to the coordinator before any run | `docs/research/p5-screens-2026-10-31/rule_octdec_loyo_batch.md` (sha256 pinned at commit). Machinery: row 92 (`rule_rm_octdec.md` `9e494ff9`, nested LOYO, readers and pins). Statistic: date-cluster bootstrap, B = 10,000, seed 20261024, BH q 0.10, placebo-matched | history LOYO (Oct-Dec 2021-25, local 07-12, plus a conditional 13-14 block), not a dev-window read. Same readers and pinned inputs as row 92 (obs `37d97195…`, NBM corpus `1ae4bf52…`, selection `a23f4cba…`, MG-2 coefficients `4bc51e03…`). Nothing dated 2026 is read | Oct-Dec batch on the SM-L6 incumbent, K = 4. W1: day-specific width from the HGB-vs-NBM disagreement anomaly (R9 spread information; not a fitted global temperature or scale map). X13: overnight-low anomaly centre term. X18: R-G trajectory columns at 07-12. X20: R-G columns at 13-14, conditional on outcome-free 13-14 coverage. The batch reopens X13, X18 and X20 under R10, which row 92's batch note had closed by family. PASS needs BH rejection, a Delta upper bound < 0, a placebo-net upper bound < 0 and no CI-worse year or month, and earns only a forward prereg to master. Controls (any fail → VOID): the row 92 C-a reproduction, identity, a planted signal and its negation, training score | pending | pending |

# Pooled sub-bar w-gate read on dev (ledger row 94, draft)

Status: DRAFT, pre-declared before any computation (2026-10-31, lane L17, task P5 (a)).

- Evidence class: dev-window SCREEN. A pass earns a forward pre-registration to master, and nothing else.
- This is not a release, a promotion or an edge claim.
- The ledger row text (row 94) was committed before this file, in `ledger_rows_draft.md`.

## 0. Selection disclosure (read this first)

**The member set was chosen because each member's dev point estimate was helpful.** The review
(`origin/claude/research-review-2026-10-31` @ `acaf441b44e6e2c730f15062f4f14f7091347ed3`, takeaway 4)
observed that "the helpful sub-threshold set was never pooled on the window where it was measured".

Consequences:

- **The read is post-selection on these 43 dates.** Each member's helpful sign was observed on exactly
  these dates. Pooling members selected for sign can pass by selection alone, even when no member
  carries information. A pass is therefore a SCREEN that earns only a forward test on new dates. It
  cannot be cited as evidence that any member, or the pool, beats the market.
- **The members' comparators were not the market.** Members were measured against MG-1, served, L6,
  t3-r3 or their own twin. The estimand here, information beyond the capture-time market, was never read
  for seven of the eight. F2's construct was read against the market in row 91 and KILLED (section 3).

## 1. Machinery

**The P0** is that of `docs/research/mr-sweep-2026-10-30/rule_mr_sweep.md` (sha256
`85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`), sections 1, 2 and 5. A model
distribution replaces the tilted market as the candidate c:

- e = y − m, with ρ_c = ρ(c − m, y − m) over (snapshot, band) cells;
- the calibration-matched disagreement placebo: c_pl(d) = m(d) + (c(d′) − m(d′)), with d′ a derangement
  within (market, local hour), via `market_blend.placebo_vector`;
- J = 20 placebo seeds 20260921 + j; clip to [EPS, 1] and renormalise;
- Δ = ρ_c − mean_j ρ_pl,j;
- B = 10,000 date-cluster draws with seed 20261024, where draw b uses j = b mod 20;
- one-sided p = (1 + #{Δ* ≤ 0})/(B + 1);
- BH at q = 0.10 over K;
- UNTESTABLE below 20 covered dates or 1,000 snapshots (p = 1, still counted in K).

**The w gate** is that of `docs/research/mr-gate-2026-10-30/rule_mr.md` (sha256
`37cb46be8d8ddb272ac69638d71de8d023eddff2384e0a6824e00a18417f34ac`), `mr_gate.gate_candidate`:

- walk-forward log pool g = m^(1−w)·c^w, with w on 0..1 fitted on dates ≤ d−2;
- the placebo c_pl,0;
- the floor-only control (market plus the hard floor);
- PASS needs all four legs:
  - mean w ≥ 0.05;
  - the blend R date-clustered upper bound < 1;
  - blend − placebo Brier upper bound < 0;
  - blend − floor-only Brier upper bound < 0.

**Data:**

- layout `C:/swarm/v3layout`, with the 11 US markets (Toronto excluded: not every member exists there);
- burn-in 2026-08-01..08-14, scored dates 2026-08-15..09-29;
- **the capture-time arm is PRIMARY** (MIM §3, master ruling 2026-10-25): every member input comes from the
  latest snapshot captured at or before the row's capture time, and from no METAR received after it.

## 2. Members and blocks (fixed; no member is added or dropped after this file is pinned)

| block (local hours) | member | ledger / register | rule sha256 | code @ commit | recorded dev headline (own comparator) |
| --- | --- | --- | --- | --- | --- |
| 07-12 | R-Q A: GEFS member SD scale modulator on P3d_N_fix | row 71 / X43 | `5703f06542b6f369bd32eaa2b84214bf4064b98490be3791b223c439d5e010c4` | `claude/spread-info-20261026` @ `19d8223895c4ae3d16faa7ec0b27403fca5547ee`; run env `c471b32b97c1cf68ba03df3b812cb5912827d8f4`; emit `C:/t/l15/rq/emit0712/dev_P3d_N_fix_Q.jsonl` | dR −0.00260 [−0.00650, +0.00094] vs P3d_N_fix (`rq_score_0712.json` `a2e0dcdb04086130…`) |
| 07-12 | R-I: per-hour temperature on P3d_N_fix (walk-forward τ) | X19, EF §10af | `b8a3d79ca13111db2bd667dc16e7a8418ddfe27bfaecbfaea23b099037341730` | `pooled_residual_model` on `claude/rung0712-20261025` @ `6488c7a31623c859631099a882ffee2fd065a925`; score `C:/t/l2/rungi/score/ri_score.json` | −0.0022 [−0.0156, +0.0104] vs P3d_N_fix |
| 07-12 | X17 R-F: blend(L6, P3d_N_fix) | X17, EF §10af | `cca30734771933f2028a9c46f7edbebd887af9ac9b9ece968b73325cf85ce7f6` | same commit; L6 frozen part `07a67425…`; `C:/t/l2/rung0712/blend/rung_blend.json` | −0.0096 [−0.0187, +0.0003] vs L6 |
| 07-12 | A2: L5 linear + overnight-low anomaly | X8, EF §10ah | `53fd0bc5…` (full sha recorded in S1 from the L5 record) | `free_source_candidates/l5_centre.py` on `claude/stack-l5-20261025` @ `533ffcb3c8dc6ce2a831e62b41fc080c21e0e2ae`; scores `C:/t/l5/scores/` | −0.0016 [−0.0059, +0.0033] vs MG-1 (crossed) |
| 07-12 | Upstream ASOS ring (L6 UP arm) | X11, EF §10ab | `6687c8dfb49b0650d27bbf23164ba102de5d838ada79917df50075c61653921a` | `upstream_obs_screen` on `claude/upstream-obs-screen-20261024` @ `e6c3f30cfdd8ecea56a31b06134ed723dbec2e3e`; `C:/t/l6/jobs/up_vs_own.json` | −0.0005 [−0.0012, +0.0003] vs the own-obs twin |
| 13-16 | F2: MRMS echo flag ≥ 35 dBZ within 25 km on t3-r3 | row 7 / X7, EF §10y | commit `308ce88ed` | `claude/free-source-screens-20261023`; score `511bd35de76e…` | −0.0005 [−0.0010, −0.0001] vs t3-r3 |
| 00-06 | R-PD: L6 own-obs nowcast stacked on NBM | row 61 / X31, EF §10ak | `e010d166…` + PD-1 `fa874b10…` | `claude/predawn-0006-20261026` @ `a9f9be5b0`; `C:/t/l3/pd/step2/gate2.json` (`86268ec6…`) | −0.0232 [−0.0520, +0.0047] vs NBM/MG-1 analogue |
| 00-06 | R-N: HRRR 2 m max stacked on NBM | row 62 / X32, EF §10ak | `c1694f75…` + RN-1 `e4869491…` | same branch; `C:/t/l3/pd/rn/gate2.json` (`d299bbf5…`) | −0.0105 [−0.0482, +0.0239] vs NBM/MG-1 analogue |

Rules for the table:

- **Abbreviated shas.** S1 replaces every abbreviated sha with its full value from the member's record
  before any outcome is read.
- **A member whose record cannot be pinned is UNTESTABLE.** It drops from its block's pool, and the block
  keeps its K slot.

**The pooled candidate per block** is the equal-weight log pool of the members covered at that snapshot:

- c_pool,b ∝ Π_k c_k,b^(1/K_b), renormalised and clipped to [EPS, 1];
- a snapshot enters the block only when **every** member of the block is covered there (the intersection);
- the per-member coverage and the intersection coverage are reported.

**K = 3 blocks:** POOL-0712 (five members), F2-1316 (one member) and POOL-0006 (two members). Members are
reported one by one, descriptively. Those per-member numbers are not in K and carry no verdict.

## 3. The F2 conflict (decision needed from the coordinator before the run)

Row 91's kill line closes "MRMS against the market for 13-16 echo max and flag at 25 km". F2's construct
is MRMS-ECHO35, which row 91 tested and killed. Task P5 lists F2 as a member. This rule therefore
pre-declares both readings:

- **(i) As ordered.** F2-1316 stays in K (K = 3). Its reading is reported as a re-read of a killed
  estimand, and an F2-1316 pass cannot reopen row 91. The block exists only so the pooled family is
  complete.
- **(ii) Dropped.** F2-1316 is removed before the run (K = 2).

The coordinator's choice goes into a dated Clarification with its own sha256 before S1 runs. Without one,
(i) applies.

## 4. Steps

1. **S1, outcome-free (no label, price or settlement read).**
   - Pin every member's code, rule and output shas.
   - Emit each member's band vectors on the dev snapshots at capture time, from its pinned code. Members
     whose stored emission is `last_in_hour`, such as the P3d_N family dev emitter (MIM §3), are
     re-emitted at capture time.
   - Report coverage per member and per block intersection.
2. **Controls (section (a)).** Any failure → VOID, and no candidate Δ is reported.
3. **P0** on the three pooled candidates, then BH over K.
4. **The w gate on every testable block.** It is the read the task asks for. A block that is not a P0
   survivor is reported as w-gate context only, and it carries no verdict.
5. **Per-member descriptive Δ and w**, not in K.

## 5. Decision

- **P0 survivor:** the block is testable AND BH (q 0.10, K as fixed in section 3) rejects AND the Δ 95%
  lower bound is > 0.
- **SCREEN-PASS:** a P0 survivor AND all four w-gate legs PASS. It earns only a forward pre-registration
  to master, on dates disjoint from dev, for the pool, never for a single member.
- **Otherwise:** KILL (pooling closed for that block), or UNTESTABLE.
- **A P0 survivor with mean w < 0.05** is labelled "P0-PASS, w ≈ 0: no information beyond the market"
  and is a KILL.

## (a) Positive control

These run before any candidate is scored. Any failure → VOID.

- **C1, served against the market:** R 1.774 (all hours) and 1.526 (00-16), to 3 digits.
- **C2, MG-1's 07-12 excess over the market:** 0.0120, to 3 decimals (observed 0.011957, row 78).
- **C3, the w = 0 identity:** for each pooled candidate, w = 0 gives R = 1.0 and max |diff| 0.0.
- **C4, reproduction.** Each member's recorded headline (section 2, last column) is reproduced from its
  pinned as-run emission and scorer, on the member's own comparator and rows, to the 4 printed decimals:
  −0.00260, −0.0022, −0.0096, −0.0016, −0.0005, −0.0005, −0.0232 and −0.0105.
  - A member that does not reproduce is UNTESTABLE and drops from its pool. Its block stays in K.
  - This is the only place outcomes are re-read for the members' own comparators. It reads nothing beyond
    what was already read.
- **C5, A4 synthetic sign control (row 91 amendment), per block.**
  - Construction:
    - planted distribution: Gaussian bands, centred at μ_m + 0.5·(y_mid − μ_m) + ε, width σ_m;
    - ε ~ N(0, sd(y_mid − μ_m)), seed 20261031;
    - it is pooled at the block's member count, by replacing every member with the planted vector.
  - Pass conditions:
    - SYN+ must be a P0 survivor and must PASS the w gate with mean w ≥ 0.05;
    - SYN− (centre μ_m − 0.5·(y_mid − μ_m) + ε) must read Δ < 0.
  - Handling: built in memory, reported only as Δ, CI and w. It is never a candidate and never in K. It
    reads the outcome deliberately as a planted control, and is not an oracle candidate.

## (b) Comparator fairness

- The comparator is the capture-time market, on identical snapshots.
- **Calibration.** The placebo is the same pooled candidate deranged across dates, so it has the same
  calibration and the same flexibility as the candidate. The w gate fits the same walk-forward weight for
  the candidate and for the placebo.
- **Floor.** The floor-only control gives the market the same hard floor on the observed running max that
  the members carry. The L11 lesson (EF §10ad) is that a 13-16 "gain" can be the floor alone.
- Every member keeps its own frozen floor and calibration, unchanged.

## (c) Targeted loss slice

- **07-12.** MG-1's capture-time excess over the market is 0.0120. About two thirds of the 07-12 excess is
  sharpness (R-H atlas `ff7ee23179be2bec…`, X27). The members target centre (A2, X17, ASOS) and width
  (R-Q A, R-I).
- **00-06.** Atlas `046aa7a924af7063…`.
- **13-16.** The served atlas is `4d094a63eb25…`.
- **Expected pooled size against the market:** below the 5% bar (about 0.0012 in Brier). The largest
  member headline against its own comparator is 0.0096.

## (d) MDE and clusters

These are the checklist (f) power-gate fields. N = 43 date clusters per block (2026-08-15..09-29).

| block | sigma_d (Brier) | rho | VIF = max(1, (1+ρ)/(1−ρ), block3²), floor 1.78 | MDE80 (Brier, w-gate legs) | planning delta | power at delta | N80 at delta | class |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 07-12 | 0.00946 (row 82, MG-1 − market) | +0.080 | 1.78 (1.174 < floor) | 0.0054 | 0.0026 (median 07-12 member) | about 0.27 | about 185 dates | SCREEN |
| 13-16 | 0.01263 (row 82) | +0.279 | 1.78 (1.774 < floor) | 0.0072 | 0.0005 (F2) | about 0.04 | about 8,900 dates | SCREEN |
| 00-06 | 0.00946 (proxy: no row 82 figure at 00-06; disclosed) | +0.080 (proxy) | 1.78 | 0.0054 | 0.0105 (R-N) | about 1.00 | about 12 dates (below the N ≥ 20 minimum; N = 43 used) | SCREEN (delta is against the NBM analogue, not the market) |

- **MDE80 formula:** MDE80 = 2.802·σ_d·√VIF/√N.
- **The P0 on the Δ scale:** σ_d proxy 0.00754 (row 78 type S), MDE80 0.0043.
- **Intervals:** date-clustered, with a block-3 interval beside it (MIM §5 rule 7).
- **Batching.** MIM §5 rule 5 batches levers smaller than about half the dev MDE80 (0.0027 at 07-12).
  Four of the five 07-12 members qualify, and X17 does not; it is in the pool because the task lists it.
- **Rule 6.** Power ≥ 0.5 is not met at 07-12 or 13-16. Every block is therefore labelled SCREEN, and a
  KILL is "KILL at edge size", never a statement that the members carry no information.
- The post-run sigma_d, rho and block-3 ratio are reported, and they cannot change the verdict.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER: this is row 94. Every member has read these 43 scored dates with outcomes at least
once (rows 7, 61, 62 and 71; X8, X11, X17 and X19), and F2's construct read them against the market in
row 91. This read adds one more reuse to each of those eight, and to the dev window as a whole, which has
been read in at least 90 rows. MIM §5 rule 11: the workstation records its own kills.

## 6. Kill and reopen line (written now)

**KILL scope.** A block KILL closes pooling of that block's members against the market on dev.

**What reopens it.** Only a forward test of the pool, on dates disjoint from dev, under a new rule.

**What it does not do.**

- It reopens no member.
- It changes no member's register row, except a note that the member was pooled under row 94.

No other weighting (inverse-variance, fitted or stacked), subset, block split, hour window or member swap
runs under any name. That would be a selection garden on a post-selected set.

## 7. Outputs and test plan (before any run; the coordinator admits the module)

**Outputs.**

- They are written once, under `C:/t/l17/pool/` only:
  - the receipt JSON;
  - per-date rows with sufficient sums;
  - per-member coverage;
  - the S1 pin table.
- Every ruled-out block keeps its prereg, script sha, outputs, receipts and logs under
  `C:\archive\ruled-out\<row-94 folder>`.

**The module.**

- A new research module, `weather.calibration.pooled_subbar_wgate`.
- It does no network I/O and writes only under its out dir.
- It imports the members' frozen emitters and scorers read-only. B-bound files (the mg2_composite
  RELEASE_FILES, `b_scorer.py`, `pooled_residual_model.py`) are imported, never edited.
- It runs from a run branch that merges the member commits read-only. That merge is listed in the module
  diff sent to the coordinator.

**Unit tests (synthetic frames only).**

- The log pool, including renormalisation and the intersection rule.
- The C3 identity.
- The C5 planted signs on a toy market.
- Refusal on an unpinned member or a post-2026-09-29 date.
- Pytest runs with `--basetemp` under `C:\t\l17\pytest-pool`, which is deleted afterwards.

**The run.** One run, after admission, through `scripts\ops\workstation_heavy.ps1 -Queue -Kind
weather_heavy`.

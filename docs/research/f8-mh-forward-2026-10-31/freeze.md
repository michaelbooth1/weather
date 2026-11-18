# F8-MH forward screen: the Oct-Dec "midnight-high" regime at 01-06 (FREEZE, L16, 2026-10-31)

Status: **frozen** by this commit on `claude/f8-mh-freeze-20261031`, under master's F8-MH rulings of 2026-10-31
(i)-(v). Dev-window ledger row 104 was committed first, on this branch, before this file, the code or any count.
The sha256 of this file is pinned in the code (`FREEZE_DOC_SHA256`) and in `SHA_PINS.md` beside it.

What was done before the freeze:
- Nothing was counted, run or fetched for this arm. No snapshot, METAR, `high_so_far`, label, price or receipt was
  opened for any date. The only code run was the synthetic test file below.
- No B-bound file was edited. The B-bound modules the code needs are imported read-only (§8).

Sources: the design draft `forward-arm-f8-20261031.md` (L16, same day) and the documents it cites (EXHAUSTION_REGISTER
X24, X31, X32, X72, X75, X85; EF §1k, §10ad, §10qq; ledger rows 59-62, 86, 93-95, 101; MODEL_IMPROVEMENT_METHOD §5;
the B, MG-1, PT-1, L6_G and row 72 designs). This file replaces the draft wherever they differ.

## 0. Kill check (method §5 rules 2, 14, 15)

| Row | What it closed | Bearing on F8-MH |
| --- | --- | --- |
| X31 R-PD, X32 R-N | Model-vs-model 00-06 arms on Aug-Sep: NULL, underpowered | Not a regime-gated market residual. Not this member. |
| X72 (row 86) | R-PD on Oct-Dec history: harm; only h00 improves | F8-MH is not R-PD. Its hours are 01-06; h00 cannot be regime (§2). |
| X75 (row 88), row 93 | Spread family vs the market, 00-06: KILL | Not this member. Row 93 supplies the reference SE (§6). |
| X85 (row 94) | POOL-0006: UNTESTABLE at edge on 43 dates | A pooled model arm. Its population lesson binds F8-MH (§5, §6). |
| X46-X62 (row 78) | mr_sweep at every hour: null | No regime gate. None measured this member (rule 15). |
| X24 / EF §10ad | Dead-bucket mechanism closed fleet-wide | **Family-adjacent.** F8-MH's mass *below* H is that closed mechanism. Its open claim is mass *above* H (§1). |
| EF §1k | Observation-recovery thread closed | A historical-replay candidate. F8-MH uses none. |

**New member:** a regime-gated, centre-type market-residual P0 on the observed midnight max, at 01-06.

## 1. The arm and its mechanism (rule 14: ACCEPTED as a hypothesis, master ruling (i))

**Mechanism (verbatim):** "after a pre-dawn cooling (midnight high, ≥ 3°F drop by the cutoff), the thin 01-06 book
keeps mass above H for a daytime recovery that does not come".

**Falsifier:** the market already prices pre-dawn fronts.

**Prior, disclosed and non-deciding:** EF §10ad (the market reprices a bucket the running max has killed before our
capture holds the killing observation) is the strongest prior against the arm. The look reports Δ split by tilt
direction: market mean above H (the open claim) and market mean at or below H (the closed dead-bucket family). The
split never decides the verdict.

**Arm F8-MH:**
- K = 1, its own arm, BH trivial. One ledger row (104).
- Statistic: the frozen `mr_sweep.p0_candidate` (pin `8bb0f9563`, vendored unchanged), signal type `"C"`, value
  **H** (§2), on the regime-only table (§5).
- A positive Δ means the tilt toward H predicts the market's error on regime snapshots.

## 2. Regime (master rulings (ii) and (iv); thresholds fixed now)

**The NBM gate G of the draft was dropped before any count**, for scope (it would place the arm inside MG-1's
reserved "NBM-guidance-to-band" family) and for computability (the forward store's NBM field is not needed by the
arm). No regime count of any kind existed when G was dropped.

Scope: B's 10 US markets (Denver out), native °F; local hours h ∈ {01, …, 06}; every snapshot captured in those
hours on a window date (§4).

Inputs, from the snapshot's own captured `sources.metar.data` only (rows and `raw_payload`), at its capture instant t:
- **Rows:** observed on the local target date D at or before t. **Routine METAR only:** a row is SPECI, and is
  dropped, when its raw text begins with `SPECI` or its `raw_payload` entry declares `metarType` SPECI. One value per
  observation instant (a later row at the same instant replaces it).
- **Observation instant:** `observed_running_max.metar_observation_local_time` (the AWC `obsTime`, else the raw
  DDHHMMZ group), the serve definition.
- **Temperature:** `feature_store.row_temp_native` as `observed_running_max` reads it; finite and within
  −80..140 °F only. The serve 30..125 °F plausibility filter is **not** applied (it would blind cold markets).
- **H** = the max of those rows on WU's whole scale, `mg_serve_core.wu_whole_f(v, "half_up")`.
- **t_H** = the earliest observation instant whose whole value is H.
- **C** = the whole value of the latest row.

**Regime iff** t_H ≤ 01:59 local **and** H − C ≥ 3 °F, with every input present. A snapshot with no routine row by t
(or no METAR data, or no capture time) is not regime and is counted as missing.

The flag uses no label, no price and nothing after t. It is outcome-bearing (H is the floor of the day's label), so
it is computed **only at the look** (§4) and by S0 on history (§6).

## 3. Inputs it records: nothing new

No emitter, recorder or daily task. At the look, everything comes from the capture host's existing snapshot store
(`<event slug>/replay_inputs.jsonl`), exported after the last claiming look, and a layout built from it with the
venue-rule labels (from 10-23, the highest routine METAR, WU fallback). **No daily check reads anything**: even a
regime count would leak the outcome. Dependency: the store keeps these dates until the look (as row 72).

## 4. Dates, D0 and the single look

- **D0 = the later of (freeze + 1, 2026-11-02) = 2026-11-02.** 11-01 is excluded (DST ends; local 01 occurs twice).
  D0 is never backdated; no date before it counts.
- **Window: 2026-11-02 .. 2027-01-25** (85 local dates).
- **One look, in the 01-26 window:** on or after PT-1's look (on or after 2027-01-27) and after every other claiming
  look (B/MG-2, MG-1, L6_G, row 72; rule 9). **No interim look and no futility look.**
- The code refuses any forward read before its gate opens: the date must be ≥ 2027-01-27, master's approval must
  name F8-MH, and a receipt sha256 must be given for each claiming look (B, MG1, L6G, R72, PT1). Every date read must
  be a window date. One look per guard root (`C:\t\l16\f8-look`), with an exclusive `look_started.json`.

## 5. Population (method rule 16)

- The table is built from **regime snapshots only**, so every row is covered and the derangement draws donors among
  regime dates of the same (market, hour).
- **Frozen cell pre-filter:** a (market, hour) cell with fewer than 2 distinct regime dates is dropped before the
  table is built (a one-date cell cannot be deranged and would bias Δ toward 0).
- **Population** = the regime snapshots in the kept cells, as `p0_candidate` counts it (covered and donor-covered
  under all 20 placebo seeds).
- **Testable** iff population dates ≥ 20 and snapshots ≥ 1000 (`mr_sweep` floors; rule 6).
- The look prints and records the realised population and its projected power (deff 2) before any Δ.

## 6. Power, and the S0 launch gate

Reference: row 93 ENS-SD-0006 (00-06, same statistic family), wider interval [−0.0219, +0.0349], so
SE_ref = 0.0568 / (2 × 1.96) on 43 × 11 market-days × 7 hours. SE scales with √(market-day-hours); "deff 2" inflates it
by √2 for regional clustering. Edge ρ = 0.2236. Power = Φ(0.2236 / SE − 1.96). About 7.1 snapshots per market-hour
(X75: 23,668 over 43 × 11 × 7).

**S0** (admitted by master; spec `s0_spec.md`, run only after this freeze commit is pushed) is an outcome-free count of
the §2 flag on Oct-Dec 2021-25 history, the X72 frame. It projects population dates, snapshots and deff-2 power for
the window under rule 16 with the ≥ 2-regime-date cell filter. **If it projects < 20 dates, < 1,000 snapshots or
power < 0.5, the arm closes UNTESTABLE without reading any forward date**, and everything is archived to
`C:\archive\ruled-out\f8-mh-midnight-high\` with SHA256SUMS.

The draft's bracket table (f = 0.03..0.10) is superseded by S0 and is not reproduced here.

## 7. Outcomes, controls and rule (e) (rule 8: a screen, never an edge claim)

Interval: the wider of the date-clustered (`mr_sweep.boot_counts`, 10,000 draws) and the circular block-3 (2,000 draws,
seed 20261024) intervals of Δ through the unchanged `mr_sweep.paired_delta`. In-run power from the larger SD.

Labels, in order:
1. **UNTESTABLE:** not testable (§5), or in-run power < 0.5, or a control fails.
2. **KILL at edge size:** the wider upper bound < 0.2236. Archived under rule 13, with a register row.
3. **SCREEN-POSITIVE (descriptive only):** the wider lower bound > 0 and the upper bound ≥ 0.2236. The next step
   would be a separate frozen test on dates no test claims. No promotion, no edge claim; nothing feeds B, MG-2,
   MG-1, PT-1, L6_G or row 72.
4. **NOT KILLED, NOT SCREEN-POSITIVE:** otherwise.

Controls before the verdict: every table cell has ≥ 2 dates after the pre-filter; the w = 0 identity (value = the
market mean gives c = m on every band, max |c − m| < 1e-12); the D3 rows reproduce `p0_candidate`'s Δ. The synthetic
planted / null checks are the test file's (§9).

Disclosure, non-deciding: Δ with zero tilt outside each subset (same population) for market mean above H, at or below
H, each hour 01-06 and each market; plus `p0_candidate`'s own block and market subgroups.

**Rule (e):** any refusal or error at the look for any other reason stops the look, and master rules.

## 8. Claims and the B-bound imports

| Claim | Dates and hours | F8-MH interaction |
| --- | --- | --- |
| B / MG-2 | D0 10-29, 45th 12-12; primary 07-16; look 12-13 | F8-MH dates to 12-12 are B's dates: a screen there, read only after B's look. Never alters B. |
| MG-1 reservation | 10-15..11-28 | G dropped (§2): the arm uses no NBM input. Read only after MG-1's look. |
| PT-1 | PT_D0 12-12 .. 01-25, look on or after 01-27 | Read only after PT-1's look. Never alters PT-1. |
| L6_G | D0 10-31, N = 45, 07-12, after B | Disjoint hours; read after its look. |
| Row 72 | D0 10-31, look ≥ 12-15; 07-12 | Same store; read after its look. The odc blob `1cc4d565` is untouched. |

**B-bound imports (master ruling (iii)).** The code imports `mg_serve_core` and `observed_running_max` directly, and
`dev_scorecard`, `dev_scorecard_data` and `loss_atlas` through the frozen statistic, all READ-ONLY. Before importing,
it checks each file's sha256 against B's release-binding manifest
`docs/research/mg2-composite-binding-2026-10-25/release-binding.json` (`files` map), whose own sha256
`4e4dd97d0b2aa0eae920d6ee5406160ca8f0c16a001ba1615446702554a812fa` is pinned in `B_FORWARD_TEST_DESIGN.md` (line 73),
and after import it checks that every loaded module on that manifest is the checked file. Any mismatch refuses. No
rule bars these imports; none of these files is edited. `mr_sweep`, `mr_gate` and `loyo_screen` are vendored unchanged
from pin `8bb0f9563` (git blobs pinned in the code); `block_counts` and `power_at` are copied from
`c3_kill_tier` @ `b1d8e65fd`.

## 9. Code, tests and pins

- Code: `tools/research/forward_f8/f8_mh.py` (stages `preflight`, `look`). It must run only through
  `scripts\ops\workstation_heavy.ps1 -Queue` after main admits the module (not admitted by this commit).
- Tests: `tests/reporting/test_forward_f8_mh.py`, synthetic only.
- S0 spec: `s0_spec.md`. Pins: `SHA_PINS.md` (sha256 of this file, the S0 spec, the code and the tests, and the
  vendored blobs).
- Any change to this file, the code or the S0 spec after this commit is a dated clarification ruled by master, never
  an edit in place.

# B at 07-12: costed program plan (DESIGN NOTE, outcome-blind; waits for master's GO / NO-GO)

- **Status:** DRAFT design note by WS lane L59, written 2026-11-03 15:12 -05:00 (Get-Date). It freezes, runs and
  fetches nothing. No price, label, outcome or loss value was read for it, and no data dated 2026-09-30 or later.
  Bound inputs are named by manifest sha only; no data file was opened.
- **Base:** `origin/master` `621d67f0f`. Other tips are cited where used:
  - docs head `claude/mg1-b-rulings-docs-20261103` @ `22f3631f0`;
  - feasibility `claude/row28b-wstep-feasibility-20261103` @ `4e8b23675`;
  - forward draft `claude/row28b-forward-prereg-draft-20261103` @ `acab59345`;
  - row 28 `claude/row28-yearround-history-20261102`.
- **Framing (master, 11-03).** 07-12 is the only hour range where a market test can be powered. R21's reopen shape is
  "a pre-13 candidate whose coverage reaches its last forward date" (`rulings.md`:193; register X106).
  - B trains on Dec 17-May 31 rows (forward draft :39), so its coverage reaches any forward date up to May 31.
  - A 07-12 w at the decision hours would satisfy rule 4 for a 07-12 arm. It never does for a 13-16 claim
    (feasibility.md:161-162).

## Verdict up front

**Recommend a STAGED GO.**

- **GO now for stages 1-2.** They are code plus light runs on inputs already on the WS. No download is needed. They
  take about 3-4 working days and decide E1.
- **Conditional GO for stage 3**, the rule-4 07-12 w screen on season 2026. It is the market path's real kill point
  and needs one free official NBM fetch.
- **Joining the 12-17 forward test (stage 4a) is a stretch, not the plan.**
  - Under the stated rule-19 bound (row 82: power 0.47-0.57 at 45 dates at 07-12; feasibility.md:122-124), E1's E3
    rule (projected power ≥ 0.8 at N = 45; spec_e1 :107-111) will most likely say DON'T ADD.
  - The realistic market test is a **separate 07-12 forward prereg (stage 4b)** of about 80-100 dates
    (feasibility.md:135-136). Its D0 must be no later than about **2027-02-15**, so that 100 dates end inside B's
    May 31 coverage.

## Stage 1: E1-(i) history N extract plus LOYO season-L6 states (no download)

**What.** An own-observation nowcast N for row 28's Dec 17-May 31 2021-25 history rows at 07-12. It is built only
from row 28's bound IEM manifests:

- `manifest_iem.json` `17aca6d162316aeb4b391cd145ca830578e8191e1a49a878bb6e93ed699ad61f`, Dec 16-Jun 1 windows;
- `manifest_iem_gap.json` `bdf84209d1ef99c2cff74caf0b81201b63e873944fd2cb8607dc9277fa9fb402`, May 31-Dec 17 windows;
- both from `FREEZE_RECORD.md`:19-22 on the row-28 branch, held under `C:\t\L59\row28\fetch\`.

**Why these files suffice (from the fetcher code, not the files).**

- Each request asks IEM `asos.py` for `tmpc` plus the **raw `metar` string**, routine (3) and special (4) reports, for
  the 11 markets plus 300 pool stations, over the Dec 16-Jun 1 window of each season 2021-25 (`row28_fetch_v1.py`:11,
  :192-203).
- The raw METAR carries everything the L6 OWN columns need: temperature, dewpoint, the T-group, wind, cover and
  ceiling (`mg_serve_core.py`:153-197, :256-265; OWN list :286-287).
- Only the 11 market stations are needed. The 300 pool stations are not read.

**Comparator S at 07-12, as served** (code-traced on the docs head; erratum 1):

- It is the L6 stack over MG-1, with frozen coefficients `07a67425…ee17e9` on N from the season-L6 state
  `800072c7…2ee2db` (`l6g_forward_frame.py`:41-42; `mg2_composite.py`:14, :786).
- There is no date gate (`mg2_composite.py`:53, :433-441).
- The stack falls back to MG-1 exactly only where N is missing or an hour has no coefficient (`l6_stack.py`:13,
  :67-68, :86-89).

**LOYO states (so Dec 17-31 is not in-sample).**

- The season-L6 HGB trains on all month-10/11/12 rows of 2021-25 (`C:\t\l3\sml6\rule_sml6.md` sha256 `81649748…`,
  :23-24), so Dec 17-31 rows of 2021-24 are in its training.
- Plan: refit `make_model(OWN)` with year ≠ Y, exactly as that rule's own LOYO step does (`rule_sml6.md`:31-32), from
  L6's bound history (`upstream_obs_screen.build_history`, obs sha `37d97195…`, `rule_sml6.md`:23-24). No new input.
- Four states are needed, excluding Y = 2021, 2022, 2023 and 2024. A Dec 17-31 row of calendar year Y is scored with
  the state that excludes Y.
  - Dec 2020 is not in training, so season-year 2021's December needs no LOYO state.
  - Jan-May rows are never in training (months 10-12 only), so they use the bound state `800072c7` unchanged, which
    is exactly what is served forward.
- Stage-1 code is a new, sha-pinned research script (v1). B-bound modules, `mg2_composite.py`, `mg_serve_core.py`
  and prm are imported read-only, never edited.

**PIT semantics (to be fixed in a dated E1 spec amendment before any run).**

- **Cutoff.** Each history row's cutoff t is row 28's nominal local cutoff for hour h (the `extract_market` row).
  - A METAR is usable only if its observation time + 10 min ≤ t. This mirrors the captured rule "rows usable from
    observation + 10 min" (`mg2_composite.py`:782-783).
  - Disclosure: IEM is an archive. It may hold corrected reports, and receipt time is unknown. History PIT is
    therefore nominal; forward is as-of-capture.
- **prev_dmax.** Forward serving takes the verified bundle's D-1 record (`mg2_composite.py`:788-789). History uses
  D-1's routine-METAR maximum over the local day. This asymmetry is disclosed, as row 28 disclosed F
  (`prereg_row28.md`:175).
- **Parity unit test.** Identical METAR lines must give byte-equal OWN features through the serve core's parser and
  feature path (`mg_serve_core.py`:153-265). The history builder may only call those functions; it never
  re-implements them.

**Effort, disk, RAM.**

| Item | Effort | Disk | RAM |
| --- | --- | --- | --- |
| Builder plus parity tests | about 1 day | none | none |
| Parse | light | about 0.1 GB out | under 2 GB |
| LOYO fits | heavy | small | about 2-4 GB |
| E1 run | heavy | about 8 GB | about 5.1 GB peak |

- **Parse.** It reads the 11 market stations' share of the 0.87 + 0.99 GB kept IEM CSVs (`prereg_row28.md`:504,
  :506), which is about 11/311 of it. It writes one features table and one N table (well under 1 GB).
- **LOYO fits.** Four HGB fits on Oct-Dec history (the same work as DWL 46's LOYO), under `workstation_heavy`,
  about 1 h.
- **E1 run.** As costed in spec_e1 :82-89: build about 1.5-2.5 h, fit and score about 1-2 h, 45 GiB disk floor and a
  12.8 GB memory stop. C: has about 74 GiB free now (Get-Volume, 15:12).

**Records.** These must exist before any run:

- a dated E1 spec amendment adding the N extract, LOYO and PIT text, with its sha;
- a DEV_WINDOW_LEDGER row (next free number) with the reuse count (spec_e1 :91-100);
- a source manifest and sha for the N table.

**Kill points (stage 1).**

- **K1a, control.** A refit of all five years must reproduce the bound state's predictions on the frozen
  season-matched dev nowcast pin (`mg2_composite.py`:73) within the serve tolerance (the `l6_own_state.py`:33, :84 control pattern,
  1e-9). If it does not, the LOYO states are not served-equivalent: STOP (i) and report.
- **K1b, coverage.** N must exist for at least 90% of 07-12 history rows (the `COVERAGE_MIN` 0.90 analogue,
  `mg2_composite.py`:58). Otherwise S is mostly MG-1 and E1 is not the served comparison: STOP.
- **K1c, E1's pre-stated E3 rule** (spec_e1 :102-112). DON'T ADD means no 07-12 B−S arm in the 12-17 forward test.
  **That alone does not kill the market path (stage 3)**, which rests on w, not on B−S.

## Stage 2: B's 07-12 fit as a separate state

- **History fits.** Arm B's spec, fitted per hour for h = 7..12 by the same routine (`row28_run_v12.py`:2011-2016), in
  a new runner `row28_run_v13.py` (v12 stays unchanged; spec_e1 :32-35).
  - The bound builder already covers hours 7-20 (`prereg_row28.md`:63; `pooled_residual_model.py`:97, read only).
  - This is shared by stage 1 (E1 scores it) and stage 3.
- **Forward state.** L56's answer (register :507) is to use a **separate state file**, because one file with hours
  7..16 would change the 13-16 sha.
  - `arm_state(hours=...)` is parameterised. The emit gate is `INTRADAY_CUTOFF_HOURS`.
  - **The fit/emit CLI is pinned to `SCORED_HOURS` 13-16** (`row28_run_v12.py`:175, :3059). A forward 07-12 state
    needs a master ruling plus a small CLI change.
- **Parity.** At 07-12, F is still defined (WU-hourly max up to the cutoff; serving reads captured METAR). A METAR
  versus WU gap is a larger share of a small F (extension_0712 :40-45). The forward parity control needs a 07-12 leg.
- **Effort.**
  - v13 history fits: about 0.5-1 day of code plus 1-2 h under `workstation_heavy`.
  - Forward 07-12 state and CLI: about 0.5-1 day for L56's code path. L56 is busy with the equivalence run.
  - Disk and RAM are as row 28's fit (spec_e1 :82-85).
- **Questions for L56, through master only** (L56's branch is not touched):
  - Effort and date for a separate 07-12 state file and the `SCORED_HOURS` CLI change.
  - Whether L59 may write that CLI change as a new versioned file on its own branch.
- **K2.** The 13-16 state sha must be byte-unchanged. A 07-12 emission parity test (history row versus emitter on the
  same inputs) must pass before any forward use. If either fails: STOP and ask.

## Stage 3: the rule-4 07-12 w screen on season 2026 (history tier; the market path's kill point)

- **Scope.** A walk-forward log pool of market and B at 07-12, against the date-deranged placebo and the floor-only
  control (MIM rule 4, `MODEL_IMPROVEMENT_METHOD.md`:160-161; rung 4 :93-97).
  - It runs on L52 history prices for season-year 2026, 2025-12-17..**2026-05-26**. The season ends before the sealed
    panel 05-27..07-30 (feasibility.md:21-30).
  - It is a SCREEN under its own frozen prereg.
- **Inputs K112 lacks (builds 1-4 of feasibility.md:146-157).**
  - **Build 1:** PIT NBM corpora for 2025-12-17..2026-05-26, then B's 07-12 emission on those rows.
    - Costed by row 28's own fetch: 831 requests streamed 26.06 GB for five seasons (`prereg_row28.md`:502). One
      season is therefore about 166 requests, about 5 GB streamed and discarded, and about 0.2 GB kept, in about 1-2 h.
    - It is free official data under the same date-exclusion assertions (`prereg_row28.md`:512-516).
    - It needs master's GO as an input-only fetch, plus the V4.3/V5.0 tail decision (end 05-05, or label 05-06..05-26).
    - The L47b 2026 NBP rows cover neither Dec 17-31 nor hours 7-20 (feasibility.md:55-59).
  - **Build 2:** price completeness at 07-12 per market-date, from L52 point timestamps or counts only. This gives the
    rule-16 population and N. The upper bound is 1,130 market-dates; row 113's completeness kept about half
    (feasibility.md:88-94).
  - **Build 3:** the label-integrity rule fixed before freeze (feasibility.md:96-116).
  - **Build 4:** reuse disclosure. The 2026 season was K112 dev data (`prereg_row28.md`:528). It needs a DWL row and an
    owner yes through master if SoP:50's scope requires one.
- **Effort.**
  - Builds 1-4: about 2 days of code plus about 3 h of light or queued runs.
  - Prereg with `prereg_check`: about 0.5 day.
  - Run: about 1-2 h under `workstation_heavy`.
  - Disk is under 10 GB peak and RAM under 6 GB.
- **Power (rules 6, 16, 19).** No same-kind w contrast exists, so rule 19 needs the stated bound: row 82's projection
  at 07-12 (feasibility.md:118-137). The screen launches only if the build-2 population gives projected power ≥ 0.5
  at half the bound's effect (MIM :163-164).
- **Kill points.**
  - **K3a:** projected power < 0.5 on the build-2 population. Do not launch (rule 6), and the market path is
    UNTESTABLE on history.
  - **K3b:** walk-forward w does not beat both the placebo and the floor-only control. KILL B's 07-12 market path
    (rule 4).
  - **K3c:** the label cap or any integrity HALT before scoring allows a reviewed amendment (as row 28 §4). After any
    score, no re-run.

## Stage 4: forward timeline

**Today is 11-03.** Heavy work is serial on the WS, and master's attention is also held by the MG-1 look (after
11-28) and B's look (12-13).

| Window | Work | Gate |
| --- | --- | --- |
| 11-04..11-10 | Stage 1 builder, parity tests and LOYO states; E1 amendment and DWL row; v13 history fits (stage 2); E1 run | K1a, K1b, then K1c about 11-11 |
| 11-11..11-17 | Build 1 fetch (master GO); builds 2-4; forward 07-12 state and CLI (L56, ruling) | K2 |
| 11-18..11-25 | Stage-3 prereg frozen; screen run | K3a, then K3b about 11-25 |
| 11-26..12-10 | (4a) only if E3 = ADD and K3 passed: forward draft adds the 07-12 B−S arm as the fixed-sequence secondary behind 13-16 (extension_0712 §(c), :85); 07-12 emitter tested; `prereg_check --forward`; freeze before D0 12-17 (forward draft :52), with the owner's 12-17 embargo OK (:7-9) | freeze by about 12-10 |
| about 12-01..02-15 | (4b) if K3 passed: a separate 07-12 forward market-test prereg; D0 after its own freeze, about 80-100 dates; look after F8-MH (≥ 2027-01-27) and every earlier-frozen claimant (rule 9) | D0 no later than about 02-15 so its dates end by 05-31 |

**What can slip to a later forward window.**

- (4a) slips entirely to (4b) if E1 or stage 3 is late. A 07-12 arm cannot join the 12-17 test after that test's
  freeze.
- (4b) can start any date after its own freeze until about 02-15. After that, about 100 dates no longer fit inside
  B's May 31 coverage, so R21's reopen shape fails and (4b) waits for the next Dec 17 season.
- Stage 1 (E1) itself can slip without blocking stage 3. E1 informs only the B−S arm.

## Kill points in order

| Point | Fails when | Result |
| --- | --- | --- |
| K1a | control not reproduced | STOP (i) |
| K1b | N coverage < 0.90 | STOP E1 |
| K1c | E3 says DON'T ADD | no 07-12 arm in the 12-17 test only |
| K2 | 13-16 sha changed or 07-12 parity fails | STOP and ask |
| K3a | power < 0.5 | history market path UNTESTABLE |
| K3b | w does not beat placebo and floor-only | KILL the 07-12 market path, to the register |
| 4b | no D0 by about 02-15 | defer to the next season |

## Not decided here (for master)

- GO / NO-GO by stage.
- The build-1 fetch GO.
- The V4/V5.0 tail.
- The label-cap option.
- The `SCORED_HOURS` CLI ruling and who writes it.
- Whether (4b) is wanted at all, given the B−S verdict at 13-16 claims model improvement only (feasibility.md:163-164).

Nothing here is an owner approval. Any owner question (the 12-17 embargo line, the reuse scope) goes through master.

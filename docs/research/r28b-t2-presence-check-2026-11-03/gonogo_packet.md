# T+2 sibling go/no-go packet for master's 11-20 decision (DRAFT; outcome-blind)

- **Status.** Lane L59, WS, 2026-11-03. Draft only.
- **Inputs used.**
  - The presence counts from `t2_presence_check_v1.py` (sha256 `b6e4bc83…`): one result file per run, both runs
    accepted or ordered by master.
  - Recorded figures from the T+1 prereg draft, rev 11 (`claude/t1-forward-prereg-20261030` @ `8f8158d1f`,
    `docs/research/t1-forward-prereg-2026-10-30/README.md`).
  - Clarification 6 §6 (`claude/b1-clar6-look-chain-draft-20261103` @ `f89e631cb`,
    `docs/research/b-look-prep-2026-10-31/b1-clarification-6-look-chain-2026-11-03.md`).
  - Recorder documentation.
- **Not read:** no outcome, price or label value; no slot timing (the 404-block timing stays unverified, per master).
- **The decision is master's on 11-20, after the census lead-2 counts.** The slot is Clar 6 §6 "T+2 go/no-go",
  `:267-270`.

## DECISION (master, 2026-11-03): NO-GO, DEFERRED, not killed

- **Why now.** Master decided on 11-03 rather than 11-20, because the census lead-2 evidence is already zero
  (`docs/operations/FINDINGS_DIGEST.md:88`) and nothing before 11-20 can change rule 6. This is fail-fast.
- **Reasons (master):**
  - rule 6 fails at the reachable N (60-75 dates; power 0.25-0.30 at 1.5×);
  - it is last in the rule-9 queue;
  - the A2 ENS recorder gap;
  - zero census lead-2 evidence.
- **Reopen triggers:** (1)-(3) of this packet's recommendation, verbatim.
- **No owner question is raised,** because no task is proposed.
- **Decision tip.** This packet was decided at sha256 `985a3e121743547e85c8708267388a952f1266e9a6a3c40f1543f2582eeb6c0c`
  (branch tip `201e58151`).
- **Clarification 6's T+2 slot** is filled by lane L16 on its own branch.
- **New reason code, noted without investigation (master).** `gamma_guard` appeared on 2026-11-02 in one cycle per
  market (10 in US10; run `fc1440af…`). It was absent on 10-30..11-01. No slot timing or row was read to explain it.

## Recommendation: NO-GO (defer), with named reopen triggers

- **It fails rule 6 at the N it can reach.** At the stated conservative bound, a T+2 screen cannot reach power 0.5 at
  the N it can accrue by its earliest possible read.
  - At 1.5× the basis σ, the reachable N of about 60-75 gives analytic power 0.25-0.30. The simulated power, with the
    futility path, would be lower.
  - Power 0.5 needs about 169 scored dates (simulation-scaled).
- **Its read comes last in the queue.** By rule 9 it would be the last-frozen claimant of every date it accrues.
  - It reads nothing before T+1's final look, which itself waits for 82 countable dates and the PT-1 and F8-MH looks.
  - So it cannot shorten any timeline or inform the T+1 result.
- **There is no prior evidence for T+2.** The 88a census found no full ladder at any lead ("census 0/0/0",
  `docs/operations/FINDINGS_DIGEST.md:88`), so the lead-2 counts give nothing beyond zero. The presence check shows
  the comparator side is recordable (below), but recordable is not powered.
- **Reopen triggers (any one):**
  1. T+1's final look PASSES, so a lead-2 extension becomes a question worth its own N.
  2. A same-kind T+2 SD exists, for example from a later T+2 history source, and rule 19 then allows a projection
     from it.
  3. Master accepts a look date late enough for about 170+ countable T+2 dates (about May 2027 or later from a late-
     November D0).

## (a) Power at its own N (rules 6, 16, 19)

- **Basis (named).** The recorded dev back-out σ_d = **0.085 dR** (HRRR R-K), with ρ = 0.28 (planned, the largest
  measured market pair), VIF 1.78, and the futility inflation k = 1.07 (T+1 README:288-298).
  - This is the planning σ of T+1, which is not itself a T+1 or T+2 measurement. T+1's SD is a near-twin (rule 19),
    so it is NOT the basis. The bound is stated as 1.5× and 2× of the named basis.
  - **Effect.** No T+2 effect exists. The packet borrows T+1's declared screening effect δ_s = 0.030 dR (T+1
    README:297-300) as a declared, never-shrunk screen size, not a measurement.
- **Formula, as T+1's own (README:304):** power = Φ(δ_s·√N / (σ·√VIF·k) − 1.96). The simulation scaling is T+1's
  recorded ratio of simulated to analytic N for power 0.5: 75/63 (README:316-317).

| σ (dR) | N for power 0.5, analytic | N for power 0.5, simulation-scaled | N80, analytic | Power at N = 60 / 72 / 75 (analytic) |
| --- | --- | --- | --- | --- |
| 0.085 (basis, reference only) | 63 | about 75 | 129 | 0.48 / 0.56 / 0.57 |
| **0.1275 (1.5×)** | **142** | **about 169** | 289 | **0.25 / 0.29 / 0.30** |
| **0.170 (2×)** | **252** | **about 299** | 514 | **0.16 / 0.18 / 0.19** |

The basis row reproduces T+1's own table (README:334-338: 63 and 129), which checks the arithmetic.

- **Realised population (rule 16): the comparator side, from the presence counts.**
  - Runs: `322d29af…` (10-30..11-01) and `fc1440af…` (11-02). The 10-30 day was partial: 13 cycles, 3 of them
    top-of-hour.
  - US10 h2-complete cycles on the three full days:
    - 10-31: 813/960;
    - 11-01: 811/960;
    - 11-02: 844/960;
    - **total 2,468/2,880 = 85.7%.**
  - Every US10 market had **19-22 of 24 complete top-of-hour cycles** on each full day. Under T+1's countable rule
    (at least 8 markets with at least 12 hours covered, README:129-130), all 3 full days are countable on the
    comparator side.
  - Reason codes (US10, 3 full days):
    - `gamma_http_404` 144 + 144 + 104;
    - `ladder_incomplete` 3 + 5 + 2;
    - `gamma_guard` 0 + 0 + 10 (one cycle per market on 11-02).
  - The arms' coverage is not measured, and A2 may lose part of the day (part (b)). Rule 16's population is
    therefore at most the comparator-countable dates.
- **Reachable N by its look date (rule 9).**
  - **Claims queue.** A T+2 sibling would freeze after every row of Clar 6's claim table (`:240-248`). It is
    therefore last in rule-9 order on every date it accrues:
    - MG-1 to 11-28 for A1/A3 (`:240`);
    - B to 12-12 (`:242`);
    - L6_G and row 72 (`:243-244`);
    - F8-MH 11-02..01-25, look 01-26 (`:245`);
    - T+1, whose final look needs at least 82 countable dates and comes after the PT-1 and F8-MH looks (`:246`);
    - PT-1 12-12..01-25 if bound (`:247`);
    - row 28b 12-17..01-30, read on or after 01-31 (`:248`).
  - **Earliest read.** The earliest T+2 read is after T+1's final look, about late January or early February 2027
    (T+1 README:395-396), if T+1 freezes soon.
  - **Accrual.** It runs from the first capture day after its freeze, about 11-23 at the earliest after an 11-20 go,
    to about 02-05. That is **about 60-75 dates, at most** (all comparator-countable on the evidence so far).
  - **At that N,** power is 0.25-0.30 at 1.5× and 0.16-0.19 at 2× (analytic). It fails rule 6's 0.5 floor.
  - **To reach power 0.5 at 1.5×,** the look must wait for about 169 countable dates: about May 2027 from a late-
    November D0. That is a different, unrequested design.

## (b) Emitter design sketch (prose only; no code file)

- **File.** A NEW file, for example `tools/research/t2_forward_emitter.py` (the name is a proposal). It is never an
  edit of `tools/research/t1_forward_emitter.py`, which is pinned at `5d348b75`. It may copy that file's structure.
- **What it emits.** For capture day D: every (market, local top-of-hour on D) snapshot for target T = D + 2, on US10
  plus Toronto as T+1 does (T+1 README:121-128). Each arm is a pmf over native-unit integer bins plus the mass below
  and above the grid. Output goes to a new append-only store with a sha256 manifest, and parity checks VOID a date
  without dropping rows. It does no band mapping and reads no prices.
- **A1, NBM NBP at lead 65 from 07Z.**
  - Values: the TXN 10/25/50/75/90 percentiles in the column valid at 00 UTC on T + 1 (= D + 3). From the 07Z cycle
    on D, that column is FHR 65.
  - Structural check (FHR index only): FHR 65 is present in the dev-dated block `C:\t\l48\dl_meta\nbp\nbptx_20260815_07.txt`
    (sha256 `fffd77ee…`; index 17..221 by 12 h, maximum lead 221 h in all 9,591 blocks).
  - Receipt rule: A1 uses that cycle once it is received. Snapshots before its receipt are A1-uncovered unless master
    allows the D−1 07Z cycle at FHR 89, which is also present in the index. That is a design choice for master, not
    taken here.
  - Inputs: the NBM text recorder `C:\t\nbm_text\forward`, through the same path guard as T+1 (refuse the price
    recorder).
- **A2, ECMWF ENS (gap, by documentation).** The ENS recorder keeps `mx2t3` steps 3..72 h by 3, which covers local days
  1-3 of each run (`docs/research/ecmwf-ens-forward-recorder-2026-10-30.md:18, 26` on
  `claude/ecmwf-ens-recorder-20261030`).
  - For T = D + 2, only runs dated D reach T. The 00Z run's 72 h edge falls before local midnight ending T in every
    US zone, so the day is partial.
  - Snapshots before the D 00Z run's receipt have no A2 coverage under T+1's 24 h run-age rule.
  - Covering it would need longer steps (a recorder change and an owner-gated task question), or a declared
    partial-day rule. Neither is drafted.
- **A3.** 0.5·A1 + 0.5·A2 where both are covered, as T+1 does.
- **Reads nothing else.** No price, label or outcome, and no registration. It writes only under its `--out`.

## (c) New daily task: OWNER QUESTION for master to carry (not drafted; nothing approved)

- **The question.** "Does the owner approve a new WS daily scheduled task to run a T+2 forward emitter, separate from
  the existing 'L3 T+1 forward daily emit'?"
  - No task name, registrar, trigger or script is drafted, and nothing here assumes a yes.
- **A conditional second question.** If A2 must cover all of day T, the ENS recorder's step range would need
  extending. That changes a running recorder and would be its own owner question.

## (d) Recommendation summary

**NO-GO now** (defer):

- Rule 6 fails at the reachable N under the stated rule-19 bound.
- The read is last in the rule-9 queue.
- A2 does not fully cover T+2 with the current recorder.
- There is no T+2 prior evidence (census zero).

The comparator side is recordable (85.7% of US10 h2 cycles complete; all full days countable), so nothing structural
blocks a later GO under one of the three reopen triggers.

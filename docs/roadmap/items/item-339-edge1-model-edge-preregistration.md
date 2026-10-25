# 339. EDGE-1 Model-Edge Pre-Registration Family [OPEN 2026-10-21 - OWNER APPROVED; SIGNING AFTER THE THURSDAY FABLE DELTA]

Goal: score the remaining model options against market prices once each, fairly and on new settled dates, under one
signed pre-registration family (EDGE-1, with MG-1 and NBM-2 read by the same go / no-go rule), so the 2026-12-21
programme decision is GO, NO-GO or INCONCLUSIVE by a rule fixed in advance.

Owner/package: model-edge programme (workstation research; production for landing and the forward captures). Bundle:
`docs/research/model-edge-2026-10/` on `claude/edge1-prereg-drafts-20261019` (GNG rule, EDGE-1 annex, methods annex,
alpha ledger); harness v3 on `claude/harness-v3-20261019`.

Source: owner approval of the programme 2026-10-19 and of every bundle-B default 2026-10-21 12:14 (both relayed by
master-agent; [DECISION_LOG](../../operations/DECISION_LOG.md) rows of those dates). The questions answered on 10-21 are
those listed at `d138c3c54` (GNG §5 (a)-(r), §6).

Why this matters: the owner's first objective is to find out fairly and fast whether the model can develop an edge over
market prices; if it cannot after every option, the maker work may move to another domain
([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md) objectives). Development dates (<= 2026-09-29) cannot answer it:
replay there is current code, not what was served (EF §10v).

Status:

- **Approved 2026-10-21** (every Recommended default). Not yet signed: the signed copies and their signing rows land
  after the Thursday Fable delta review, before D0.
- **D0:** 2026-10-28. The 10-25 branch is unreachable: under amendment (s) (A) the A0 freeze is on N13, which now
  lands 10-24/25 (DECISION_LOG 2026-10-22); C on 10-23/24 re-pins once under (s-C) and does not move D0 earlier. Both
  amendments are pending the owner. If C does not PASS on 10-23/24, D0 is the first full day after the next C PASS
  night (never before 10-28), or 10-28 under Option 2 (C after 12-21) (EDGE-1 annex §1.2, §2.1; OD-A6 = not held).
- **Arms:** A0 (served plus the binding twin T1, NWS hourly alone; T0 climatology non-binding); A1 (A0 + t3-r3 + A1-1),
  looks deferred until after the t3-r3 look; A2 closed in development (E2 not a forward instrument). NBM-2 has no dates
  before 2027 and is absent from 12-21. MG-1 is its own signed instrument and is read by the GNG rule at its own looks.
  Under the default bar the number of TESTABLE EDGE-1 hypotheses is expected to be 0 (H-A0 measured UNTESTABLE; H-A1
  preliminary, EDGE-1 annex §8). E3 is UNTESTABLE for weather in this programme (OD-G2).
- **Dates:** Gate 1 (2026-12-07) folds into 12-21 unless at least one EDGE-1 hypothesis is TESTABLE; primary decision
  2026-12-21; overturn-only review 2027-01-25. The retrain is waived for 12-21 (best case a futility-only R0 from 11-17).

R0 rebuild notes (Lane D, 2026-10-24; research only, nothing served):

- **Leaf pick: `min_samples_leaf` stays 20** (the served value). Master ruling (a): pick by blocked
  leave-one-year-out validation over the 2021-25 Nov windows (centre 2026-11-24, R0 columns, US PIT corpora), per
  hour and per market, date-clustered bootstrap CIs (2,000 draws, seed 20261024). Rule pre-declared before computing,
  with master's dated clarification appended: a candidate (10 or 5) qualifies only if its mean blocked log loss over
  07-12 across markets is below leaf 20's AND no market is CI-worse than leaf 20; the lower mean wins, ties go to
  the larger leaf. Rule file sha256 `7e0749d965c933ebf3e8496702199bf98942b1b4f65c457a76d4d3b24f918dcc`
  (workstation-local, `C:\t\r0runs\leaf_pick_rule.md`). Neither candidate qualifies. 07-12 mean across the five
  markets: 20 = 4.459, 10 = 4.549, 5 = 4.679. Per market (75 dates, 1,050 rows each; Δ vs 20, positive is worse,
  95% CI):

  | Market | Leaf 20 | Δ leaf 10 | Δ leaf 5 |
  | --- | --- | --- | --- |
  | atlanta | 4.333 | +0.106 [+0.013, +0.201] CI-worse | +0.255 [+0.111, +0.383] CI-worse |
  | austin | 4.613 | +0.066 [-0.027, +0.155] | +0.142 [+0.016, +0.258] CI-worse |
  | chicago | 4.292 | +0.105 [-0.005, +0.229] | +0.280 [+0.143, +0.421] CI-worse |
  | dallas | 4.622 | +0.138 [+0.050, +0.225] CI-worse | +0.278 [+0.161, +0.395] CI-worse |
  | denver | 4.436 | +0.034 [-0.068, +0.127] | +0.146 [+0.026, +0.259] CI-worse |

  Hour 07: leaf 10 is worse in four markets (denver -0.047, CI spans 0); leaf 5 is CI-worse in atlanta, chicago and
  dallas. Hour 12 is leaf 10's best hour (chicago -0.108, austin -0.024, dallas -0.004, all CIs span 0); leaf
  5 is worse everywhere. Smaller leaves look better at some 15-20h cutoffs, outside the declared window, so they do
  not count. Trees: at most 3 leaves per tree at leaf 20, 7 at 10, 14-15 at 5; every tree splits. Routing of the
  finding to the digest and EF waits for the fair-comparator results (master, 2026-10-24); until then it lives
  here only.
- **Fleet and in-season (master rulings 2026-10-24):** the 22-fit leaf-20 fleet is cancelled (9 fits had finished;
  none was rerun). The 11 in-season fits (Aug-Sep PIT corpus, centre 2026-09-07) are deferred and not queued. Only
  the five floored Oct-Dec leaf-20 reruns (atlanta, austin, chicago, dallas, denver) run, for the L3 fair comparison:
  per-row floored scores from `ff50543b6`, with `--validation-row-distributions`.
- **Pregate e1d1f3200 was void by load:** receipt `pg-e1d1f3200bec-20261024T144900-71500` ran with the CPU at 99%,
  and only timing tests failed; its tip is superseded by `ff50543b6`, which passed its own pregate.

Pointers:

- Owner decisions: [DECISION_LOG](../../operations/DECISION_LOG.md) rows 2026-10-19 (programme) and 2026-10-21 (bundle B).
- Retrain reservation, narrow scope: [reserved confirmation window](../../operations/reserved-confirmation-window.md).
- Code checks behind the arms: EF §10u (HGB stages that never act; NBM reaches no band) and EF §10v (dev replay base is
  current code; the binding twin comparison is forward at the frozen hash) in
  [established findings](../../operations/ESTABLISHED_FINDINGS.md); [lever-5 note](../../research/model-edge-lever5-2026-10-19.md).
- No-go bar: [exhaustion register](../../operations/EXHAUSTION_REGISTER.md).

Acceptance:

- [x] Owner answers to bundle B (GNG §5 (a)-(r), §6): every default, 2026-10-21.
- [ ] Fable delta review of the bundle; signed copies land with their signing rows before D0.
- [ ] D0 2026-10-28 confirmed once N13's serving time and the C outcome are in the night receipts.
- [ ] Retrain prerequisite: per-model column allowlist head `claude/retrain-column-allowlist-20261021` built by 10-27,
  landed by 10-30. R0 drops `pressure` and `pressure_trend_3h` and retrains base models only (DECISION_LOG 2026-10-21).
- [ ] Each declared look read once at its date under the signed rule; result recorded in EF and the digest.
- [ ] Programme decision 2026-12-21 recorded by the owner (DECISION_LOG), or Gate 1 if it applies.

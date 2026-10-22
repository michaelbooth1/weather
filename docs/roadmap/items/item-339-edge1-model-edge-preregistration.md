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

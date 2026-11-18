# Faster iteration plan: answer to the owner (2026-10-30)

> **Status: dated rationale, 2026-10-30. Adopted by the owner the same evening** (nine decisions, all as master-agent
> recommended; [DECISION_LOG](../../operations/DECISION_LOG.md)). The binding rules are in
> [MODEL_IMPROVEMENT_METHOD §5](../../operations/MODEL_IMPROVEMENT_METHOD.md); where this file differs, that section wins.
> Written by a 14-agent workstation swarm (master-agent synthesis) after the owner asked why each model iteration costs
> 45 forward days. The owner was asked a re-numbered list: Q8 here (pilot) was answered separately (postponed), MG-3 was
> dropped, paid data was declined for now, and Q5 here (the PT-1 sealed-scorer clause) was not put to the owner and is
> not adopted. Since writing, T+1 prices are recorded on the workstation (forward-only: no receipt-dated day-ahead
> history exists). Bracketed citations are to canonical files.

**Short answer.** Ten iterations do not have to cost 10 × 45 days. One iteration means taking an idea to a kill or keep on history and dev data, and that already takes 1-3 days on the workstation. R-Q went from rule to kill in one day [DEV_WINDOW_LEDGER row 71]. More than 90% of the calendar is forward accrual plus a queue of single-look tests [B_FORWARD_TEST_DESIGN §3, §9; reserved-confirmation-window.md].

Seven-day looks can only stop a disaster. At 7 dates a test can only resolve a difference of 0.0084, which is the whole dev gap. The useful kill look comes at 14 dates. Confirming a market edge still takes 67-110 dates, so we pay that once, for the best candidate [B §(d)].

Note: sigma_d = 0.0079 is a band-Brier SD, not log-loss [B §5]. All look boundaries below are hand approximations and must be simulated before anything is bound.

## 1. The plan in 8 rules

1. **Two currencies.** History and dev reads are cheap and can only kill. Only frozen, sha-pinned candidates or batches may spend forward dates [MODEL_IMPROVEMENT_METHOD §3].
2. **Kill at the cheapest tier that can.** Tiers in order: outcome-free checks, then history LOYO, then dev, then a forward futility look. About 5 of the 9 candidates that passed LOYO and then failed dev could have been caught earlier by cheap checks: intercept-only gains, gains the HGB arm absorbs, the NBM v5.0 change, and an underpowered 00-06 block [EXHAUSTION_REGISTER §6 X18-X43].
3. **w comes first, not R.** A candidate earns a market test only if its walk-forward weight w beats both the placebo and the floor-only control, and it then passes a dev tradability replay [MODEL_IMPROVEMENT_METHOD §3 rung 4; COOL_SEASON_PAPER_TEST_PREREG §5.3]. A dev win against served or MG-1 is not edge progress. MG-1 beat served but has w of 0.008 [ESTABLISHED_FINDINGS §10ad].
4. **Batch small levers.** A lever smaller than about half the dev MDE80 (roughly 0.0025 at 07-12) goes into a batch pool and never gets a solo dev read or forward test [LEVER_INVENTORY lines 40-41, row 23].
5. **Size each test from its own numbers.** N is set from the paired sigma measured for that pair and half the dev effect, with a minimum of about 20 dates before any PASS. No new screen launches with power below 0.5. A candidate's training coverage must reach its last forward date, because the current states end on 12-16 [B §3; l6g_forward_prereg_DRAFT §8].
6. **New pre-registrations carry futility looks; bound tests stay untouched.** Every new pre-registration gets non-binding looks at 14, 21 and 31 dates, a gross-harm stop at 7 dates, and a final boundary that does not change. B, MG-1, L6_G and MG-3 stay exactly as bound [B §6, §8(4)].
7. **One date rule.** No outcome, label or price on a date is read until every test that claims that date has taken its look. Market-edge claims go only on dates disjoint from B's [B §8(4), §10; l6g §7(2), §9].
8. **Record first, and fix quickly.** Recorders for forward-only free sources start now. A standing defect lane runs alongside, because every served gain so far came from a defect fix [ESTABLISHED_FINDINGS §3, §10q; DATA_LAYER_V2_PLAN lines 144, 292].

## 2. Candidate pipeline

| Stage | Gate | Duration | Where |
|---|---|---|---|
| S0 Intake | Says why the market might lack this information. Exhausted families are refused unless there is a new mechanism. | <1 h | WS coordinator |
| S1 Outcome-free checks | Coverage; per-version check; availability dated by receipt, with latency checked per year for 2021-25 | minutes-4 h | WS (light) |
| S2 History | Market-residual P0 (does it predict the market's error, or only ours?). Spearman P0 for spread inputs. Season-matched LOYO in served form against the strongest incumbent, with a slope term. Oct-Dec features must be clear of the +1 h label shift [ESTABLISHED_FINDINGS §10w]. | hours-1 day | WS heavy slot |
| S3 Dev (kill-only) | Ledger row first; rungs 1-4 including market R and w; then a tradability replay if w passes | 0.5-1 day | WS |
| S4 Freeze | Joint LOYO, serve parity, positive control, sized N, futility block, VOID and drop rules | 2-3 days | WS builds, master binds |
| S5 Blind accrual | Daily emission from the export bundle. Parity checks run alongside, and failures VOID dates. | continuous | WS. The host only exports. |
| S6 Futility looks | Sealed scorer outputs CONTINUE/STOP only and stores no interim numbers. Kills use each arm's registered comparator. | hours per look | WS |
| S7 Edge test | Only after the w and tradability gates pass; fresh dates; 67-110 dates | 2-4 months | WS scorer, owner price line |

## 3. What we stop doing

- Treating every iteration as a forward test.
- Using N = 45 by convention.
- Running single-lever forward screens. L6_G finishes as bound, but we launch no more like it.
- Retrying exhausted families: width or scale maps, spread used as a scale, NBM debias, extra daily-max NWP, extra station feeds, dead-bucket or evening plays [EXHAUSTION_REGISTER §6].
- Running 07-12 sharpness inputs that are scored on our own error. The R-H tag tests were null [ESTABLISHED_FINDINGS §10ag].
- Asking the owner for an exemption per candidate.
- Waiting for a dev win before recording a source.
- Per-slice veto gates [RETRACTED_AND_FALSE_LEADS §2].
- Renumbering ledger rows, and VOIDing a run over a deviation outside the decision set.
- Feeding the dev reuse count into forward alpha.
- Reporting kill throughput as edge progress.

## 4. Next 14 days

1. **Master, 10-30.** Send the owner the decisions in §5 as plain chat text.
2. **Master, night 10-30/31, plus WS L-E.** Audit recorders without reading outcomes: NBP CYYZ landed? HRRR recorder alive? DLv2 S4/S5/S7 running? GEFS 06Z healthy? Publish a recording ledger [STATE_OF_PLAY lines 41, 56; DELEGATION_CONTRACT §4].
3. **Master, docs-only, before 11-29.** Land a look-chain clarification: receipted looks in the order MG-1, then B, then L6_G/MG-3, then PT-1 are not pre-look reads for the later tests. This applies to the closed list only [B §8(4); l6g §7(2)].
4. **WS L-A, 10-31 to 11-06.** Defect trace: the Open-Meteo +1 h shift on standard-time rows, M0 keying, emitters across the 11-01 DST change.
5. **WS L-F, 11-01 to 11-03.** On dev dates ≤09-29, with a ledger row first: measure lag-1 autocorrelation, the block-bootstrap SE and the paired sigma for each pair. Simulate the boundaries. Write checklist sections (f) power gate and (g) futility.
6. **WS L-B, 11-01 to 11-03.** Toronto sprint: NBP/NBS/NBH CYYZ history, per-version check, a dev read against served and the market. Disclose the earlier L11 read.
7. **WS L-C, 11-01 to 11-05.** Market-residual P0 on every live survivor and every new source. Run the dev tradability replay on the best w.
8. **WS L-E, 11-01 onward.** Recorder pack: MOSMIX_L, ECCC UMOS/HRDPS, GEFS 00/12/18Z, IEM MOS at 15 s spacing, and HRRR in a separate process from MG-3. Open-Meteo only behind master's call meter. Bulk pulls outside 12:00-18:00, one connection, at most 4 MiB/s [DATA_LAYER_V2_PLAN lines 235-238]. Start an outcome-blind day-2 (T+1) emitter.
9. **Master, night 11-01/02.** Land NBP CYYZ capture in the first roll-sensitive slot, if the audit shows it absent [HOST_LOAD_POLICY rules 8, 10].
10. **Master, by 11-06.** Draft PT-1 fixes: PT_D0 must clear B's 45th date and L6_G's dates through 12-14 [COOL_SEASON_PAPER_TEST_PREREG §4.2-4.3].
11. **WS L-D, 11-02 to 11-10.** R-ODC serve parity. Assemble the successor batch with per-component Oct-Dec LOYO. Freeze it as paired screens; it accrues blind.
12. **Master export, WS scoring, about 11-10, if Q3 is yes.** One-shot G1 read: a cool-season atlas of the market gap plus kill-only screens.
13. **Master, 11-13.** Two-week review and STATE_OF_PLAY rewrite.

## 5. Owner decisions

1. Adopt this pipeline, including the w-first gate and futility looks in new pre-registrations only? **Yes.**
2. Adopt a standing accrual rule? Frozen arms in a registry accrue outcome-blind from freeze with no per-candidate exemption. Their looks come only after every claiming test has looked, and arms on B's dates are screens only. **Yes.**
3. Open 09-30..10-14 once, as an atlas plus kill-only read? Conditions: maker replay v2 resolved first, Austin 10-03 excluded, MG-2 excluded until PT-1 binds [DECISION_LOG lines 58, 117, 209]. **Yes.**
4. Let spent dates join dev, with prices, after their last claiming look? That means 10-15..10-28 after MG-1's look and the 88a close, and the B block after the December look day. **Yes.**
5. Add a PT-1 clause: sealed CONTINUE/STOP scorers on PT-1 dates do not void it? Without it, no new US futility look happens before late January. **Yes.**
6. Approve one keepalive task for the recorders? This needs your direct yes in the WS chat. **Yes.**
7. Let the WS record pre-registered kills itself (master audits daily) and run 4-6 lanes inside the 3-slot heavy cap after the token mode ends on 10-31? **Yes.**
8. Is pilot session 1 on 10-31 postponed? If yes, the 10:00-19:30 WS freeze is lifted [DECISION_LOG row 286]. **Your call.**
9. Keep B exactly as bound? **Yes.**

## 6. What to expect

- **November:** history and dev verdicts arrive within days. The G1 read lands around 11-10, if opened. MG-1 looks after 11-28.
- **December:** B looks on 12-13 and will very likely FAIL. L6_G, MG-3 and the first batch read around 12-15 to 12-20.
- **Edge test:** a candidate that clears the w gate and is frozen by mid-December gets an answer around late February to April 2027, on fresh dates.
- **Honest risk: the answer is probably no.** The best dev composite is R 1.159 against the market, and an edge test only pays at roughly R ≤ 0.88. That gap of about 0.015 is bigger than any single step ever found (−0.0139) [FINDINGS_DIGEST; ESTABLISHED_FINDINGS §10ae, §10ah].
- **Tradability:** at w of 0.008, a taker trade earns roughly 0.16 cents a share against about 2.25 cents of cost. w would have to rise more than tenfold to break even. That is my linear approximation [COOL_SEASON_PAPER_TEST_PREREG lines 234-235]. Faster verdicts will mostly be faster kills. Only new information can change the answer.

## 7. Disagreements and how I resolved them

- **Futility tooling now or later.** The edge critique said not to build forward machinery for arms that dev already rejects. Resolution: write boundaries into the pre-registration template now (cheap), and build the sealed scorer when the first arm needs a look.
- **What the folds are for.** Proposals wanted market kill screens. Critiques said this is the wrong comparator for paired arms and that the folds could serve as an atlas instead. Resolution: one read that does both, with each kill on the arm's own comparator.
- **Edge eligibility.** Proposals keyed on R, the non-inferiority margin, or R < 1. Resolution: w beats the placebo and floor-only control, plus tradability, plus the −0.0066 R gate.
- **Timing of dates to dev, and of the first cohort look.** Proposal 3 (after MG-1's look) and proposal 4 (right after B's look) would void B, L6_G or MG-3. Resolution: only after the last claiming look.
- **Edge claims on B-shared dates.** Rejected. Arms there are screens only [B §10].
- **Paired sigma of 0.0017.** Rejected because it was a unit conversion. It will be measured directly.
- **More than 3 heavy slots by master ruling.** No. The cap is an owner decision [HOST_LOAD_POLICY lines 116-121].
- **Token mode "memory-only".** It is a real owner instruction. Let it expire on 10-31 and record it in the decision log.
- **Pilot postponement.** The canon still says 10-31, so ask (Q8).
- **MRMS release and a pre-88a T+1 read.** Dropped. MRMS is too small to be worth a question, and T+1 books exist only in 88a [FINDINGS_DIGEST line 53].
- **Toronto inside MG-1's window.** The reservation is by date and model family, not by market. Master rules before any forward read [reserved-confirmation-window.md line 28].
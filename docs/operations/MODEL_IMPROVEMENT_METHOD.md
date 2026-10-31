# Model-improvement method

Status: canonical method. Written for LLM agents. Owner directive 2026-10-23 (model improvement
only, then a real edge test): this file says how a model lane finds, builds and measures a candidate.

- **Owns:** the order of work for a model-improvement lane: locate the loss, start from the simple
  baseline, add one ingredient per rung, climb the measurement ladder, and the pre-registration
  discipline that makes each rung citable.
- **Read when:** opening a model, source or blend lane; choosing what to build next; about to score a
  candidate against served, MG-1 or the market; reviewing a lane's result.
- **Do not use for:** the results themselves ([findings digest](FINDINGS_DIGEST.md), then
  [established findings](ESTABLISHED_FINDINGS.md)); the sections a rule file must contain, which
  `prereg_check` enforces ([pre-registration checklist](PREREGISTRATION_CHECKLIST.md)); which candidates
  have already read the development dates ([dev-window reuse ledger](DEV_WINDOW_LEDGER.md)); which dates
  are held out ([reserved confirmation window](reserved-confirmation-window.md)); today's evidence
  cutoff and embargoes ([state of play](STATE_OF_PLAY.md)).
- **Update when:** a lane shows a rung of this method wrong or missing, a measurement ruling changes the
  ladder, or a new class of look-ahead or unfair comparator costs a lane a result.

Every figure below is quoted from the cited record. Re-verify it there before using it in a decision.

## 1. Locate the loss before building anything

The worked example is P3d_N, the afternoon (13:00+) half of the MG-2 composite. It was found in this
order.

1. **Where the loss is (lane L5, then lane L7's loss atlas).** At 07-12 the served-minus-market Brier
   excess is mostly the centre: the Shapley centre share is 76.5% [63.1, 88.7], served is cold by
   −1.44 F [−2.20, −0.69], and the zero-parameter NBM read MG-1 cuts the 07-12 excess from 0.0258 to
   0.0117 ([morning loss diagnosis](../research/morning-loss-diagnosis-2026-10-24.md); dev-window ledger
   rows 15 and 18). The loss atlas (`python -m weather.reporting.scorecards.loss_atlas`) reproduces the
   served control and these figures before it reads any candidate (ledger row 18). In delta mode it
   shows that MG-1 closes 53.7% of served's 07-12 excess (row 19).
2. **Rung 1, the observed floor (`high_so_far`).** L3's three-feature OLS on the forecast high, the
   observed running high and the current temperature, hard-floored at the observed high, beats served on
   the dev window: 07-12 dR −0.179 [−0.232, −0.127]. A forecast plus the floor alone gives −0.078 at
   07-12 but +0.210 at 12-16, so the gain is the running-high regression, not the floor (EF §10ab). The
   serve-equivalent running max (L8's `running_max_since_midnight`) equals L3's reading on all 9,224
   replay hours (EF §10ab).
3. **Rung 2, the NBM centre (`v2_mean`).** On blocked leave-one-year-out 2021-25, a PIT NBM mean beside
   the forecast is KEEP: −0.096 [−0.114, −0.078] nats at 07-12 (L9, EF §10ac). The forecast input of P3d
   (Open-Meteo Previous Runs, lead 1) is not in the capture, so it failed serve parity, with a served
   forecast MAE of 2.26 °F at 13-16 (EF §10aa). The MG-2 pick rule's option N therefore swapped in the
   captured NBM 07Z mean (A_N). The A_N control is −0.3915 [−0.5567, −0.2488] against MG-1 at 13-16
   (ledger row 29; EF §10ae).
4. **Rung 3, the pooled residual.** Pooled over the 11 US markets, L2's residual model beats L3's
   OLS + floor by −0.147 nats at 07-12. Pooling is the lever: the per-market twin only ties OLS + floor
   (EF §10aa). On the captured NBM mean and L8's running max this is P3d_N. In the single MG-2 pick it
   beats A_N at 13-16 by −0.155 [−0.218, −0.098] (ledger row 31; EF §10ae).
5. **Then the market.** P3d_N alone is still worse than the market: R 1.28 at 13-16 and 1.19 at 07-12.
   Its blend weight is about 0 (EF §10ad). Every rung is model against model, and none of them is edge.

Each rung changed one ingredient and was measured against the rung below it, on identical rows. A rung
that does not beat its predecessor is killed and recorded, not carried along. Examples are L9's
overnight low, dewpoint and hour-pooled slopes (EF §10ac).

## 2. Simple baseline first

Every new lane starts with the pooled OLS / NBM baseline: OLS plus a hard floor on the observed running
max, with the NBM mean as a regressor where it is captured. **A complex model is built further only after
it beats that baseline on the dev scorecard, on identical rows.** The evidence:

- **Lane B, new cities:** OLS + floor beats the forecast baseline in every block. HGB + floor is worse
  than OLS + floor in every block except one tie, and far worse late in the day (17-20 Brier +0.14 to
  +0.41), because per-cutoff trees cannot reproduce the late-day near-identity on the observed high.
  A residual HGB on top of OLS is indistinguishable from OLS
  ([new-city model lane](NEW_CITY_MODEL_LANE.md)).
- **R0 HGB against a floored baseline:** OLS + floor beats lane D's floored R0 by −1.820
  [−2.098, −1.563] nats at 07-12, in 5 of 5 markets (EF §10ab). Full-year R0 + floor is still +1.02
  [+0.86, +1.18] worse than OLS + floor (EF §10z).
- **L3 OLS + floor** beats served on the dev window (rung 1 above) with three features, no trees and no
  calibration stage. The residual-HGB variant is indistinguishable from it (EF §10ab).

The baseline must be fair. It gets the same floor, the same calibration and the same rows as the
candidate. Raw R0 is not a baseline ([checklist, the unfair raw-R0 lesson](PREREGISTRATION_CHECKLIST.md)).

## 3. The measurement ladder

Climb in this order. A candidate that fails a rung does not proceed to the next one.

1. **Dev R against the served model** on the dev scorecard (`weather.reporting.scorecards.dev_scorecard`).
   Use the paired `model_minus_control` on identical rows. Report the served positive control first.
   A pass here is necessary and cheap: served under-uses its own captured guidance (RF "Capture NBH").
2. **Against MG-1**, the zero-parameter NBM read. Both of L3's arms beat served but fail this gate at
   07-12: +0.080 [+0.020, +0.142] (EF §10ab). Beating served while losing to MG-1 means the candidate
   adds nothing that captured guidance does not already carry.
3. **Capture-time, no-look-ahead, against the market.** Every input to a read against the market comes
   from the latest snapshot captured at or before the row's own capture time, and from no METAR row
   received after it. **Master ruling (2026-10-25): the capture-time arm is PRIMARY for every market
   comparison.** `last_in_hour` features (the last snapshot in the hour, applied to every row of that
   hour) are allowed only for the MG-2 vs MG-1 gate, where both arms are models. Report R = candidate
   Brier / market Brier per hour.
4. **The blend weight w.** Fit a walk-forward log pool of market and candidate. **A w of about 0 means
   the candidate carries no information beyond the market, whatever its R.** Run the w = 0 identity, a
   placebo (vectors deranged across dates) and a floor-only control (market plus the hard floor) beside
   it. In L11 the 13-16 "gain" over the market was the floor zeroing already-dead buckets, not model
   information: MG-1's blend R 0.9858 against floor-only 0.9845 (EF §10ad).

**The look-ahead lesson (L11 audit, EF §10ad, RF "Dead-bucket stage A").** Stage A of the dead-bucket
read dated the floor by the METAR's observation time plus an assumed 10 minutes. It showed $0.37/day.
Re-dated by when the capture actually held that METAR (rule r4), it is $0.03/day [0.00, 0.09] on 21
trades. The 57 obs-dated trades were exactly the book rows read before the system had the killing
report. The same audit found P3d_N's dev emitter applying each hour's last snapshot to every row in
the hour, which exposes about 6% of rows. That can only flatter the candidate, so its nulls stand
firmer. Date every input by receipt, not by observation.

## 4. Pre-registration checklist

The rule file's required sections are owned by the [pre-registration checklist](PREREGISTRATION_CHECKLIST.md)
and checked by `python -m weather.reporting.scorecards.prereg_check <rule.md>`. On top of those sections, every
lane does all of the following.

- [ ] **Rule file and sha256 recorded before any result exists.** Commit it, or at least pin its sha256
      in a pushed record, before the first scored row. Examples: L11 r4 `fac8cd72…` recorded before any
      row; L9's ladder rule (EF §10ac).
- [ ] **Blocked leave-one-year-out validation** for historical fits (2021-25 corpora). Whole years are
      held out, never random rows (EF §10ab, §10ac).
- [ ] **Date-clustered bootstrap, 2,000 draws, fixed seed,** with the crossed date x market interval
      beside it where markets are pooled (EF §5). Report the MDE80.
- [ ] **Per-hour reporting, with 07-12 called out.** It is the window where the loss sits (§1). Pooled
      blocks hide sign changes: guidance helps in the morning and harms the afternoon (EF §10p).
- [ ] **Identical rows against the right baseline.** Same floor, same calibration, same rows. State the
      coverage and the fallback rows.
- [ ] **Evidence cutoff and embargo windows.** Never read an outcome, price or label dated after the
      cutoff that [STATE_OF_PLAY](STATE_OF_PLAY.md) names (2026-09-29 when this method was written).
      Never read the reserved MG-1 window that [the reserved confirmation window](reserved-confirmation-window.md)
      defines. Name both in the rule.
- [ ] **No oracle.** No input built from the outcome, from the settled band, or from data received after
      the row's capture time (§3, rung 3).
- [ ] **Dated Clarifications, never edits to a frozen rule.** A Clarification is a new dated section with
      its own sha256, written before the rows it governs are read. Example: L11's Toronto rule
      `12902246…` keeps its original sha beside the Clarification 1 document `46c48626…`.
- [ ] **Superseded runs are recorded, never deleted.** Keep the old run's pins and say what superseded it.
      Examples: Toronto run 1, and stage A's suspended reading, which stays in its results file with the
      audit appended.
- [ ] **A sanity control that makes the result NOT INTERPRETABLE if it fails.** Declare it in the rule
      with its threshold. Examples: the loss atlas refuses (exit 7) unless the served control reproduces;
      r4 required at least 0.95 of doubly dead buckets to have a receipt at or after the killing report,
      and got 0.972; the Toronto Celsius check matched the IEM high on 60 of 60 days.
- [ ] **A dev-ledger row before scoring** (`pending`), filled after it ([ledger](DEV_WINDOW_LEDGER.md)).
- [ ] **Cite the published dev reuse count.** Name the ledger's "Dev reuse count" (one number, ledger section of
      that name) as the multiplicity denominator the rule inherits, plus one for the new row.

A dev-window win is selection evidence only. It earns a pre-registration on new dates and a forward
shadow, never a promotion (EF §5).

## 5. Fast-iteration pipeline (owner 2026-10-30)

The owner approved nine decisions on 2026-10-30, all as master-agent recommended ([DECISION_LOG](DECISION_LOG.md)).
The rationale is the dated [iterate-faster plan](../research/iterate-faster-2026-10-30/plan.md). They add these rules.

1. **Two currencies.** History and dev reads are cheap and can only kill. Forward dates are spent only on frozen,
   sha-pinned candidates or batches.
2. **Kill at the cheapest tier that can.** Intake must say why the market might lack the information; an exhausted family
   ([exhaustion register](EXHAUSTION_REGISTER.md) §6) is refused without a new mechanism. Then outcome-free checks (coverage,
   per-version, receipt-dated availability), history (LOYO), dev, and only then a forward look.
3. **Market-facing ideas go to the market-residual P0 first.** Does the signal predict the market's error at the same hour?
   One rule, a ledger row first, BH at q = 0.10 across arms, a calibration-matched placebo (the residual deranged across
   dates, 20 seeds), and per-date rows written beside the result.
4. **w first.** A candidate earns a market test only if its walk-forward w beats the placebo and the floor-only control
   (§3 rung 4) and it then passes a dev tradability replay. A dev win against served or MG-1 is not edge progress.
5. **Batch small levers.** A lever smaller than about half the dev MDE80 goes into a batch, never a solo forward test.
6. **Size each test from its own numbers:** N from the pair's measured sigma at half the dev effect, at least 20 dates before
   any PASS, no screen launched below power 0.5, and training coverage that reaches the last forward date.
7. **Futility looks in new pre-registrations only** (Rule B, [power and futility read](../research/iterate-faster-2026-10-30/prereg-power-futility.md)):
   a harm stop at 7 dates, then stop at 14, 21 and 31 dates on the registered boundaries; inflate the MDE 4-7% and report
   a block-3 interval beside the date-clustered one. A look reads a date only when rule 9 allows it. Bound tests (B,
   MG-1, L6_G) never change; B gets no futility look.
8. **Standing blind accrual.** A frozen arm accrues outcome-blind from its freeze with no per-candidate owner exemption.
   It looks only after every test that claims its dates has looked. Arms on B's dates are screens, never edge claims.
9. **One date rule.** No outcome, label or price on a date is read until every test that claims that date has taken its
   look. After the last claiming look the date joins dev, prices included.
10. **2026-09-30..10-14 is opened once** for kill-only and atlas reads, after a written check that no running test claims
    those dates. Nothing read there supports an edge claim.
11. **The workstation records pre-registered kills itself** (ledger row and register row); master audits them daily.
12. **Record first.** Free forward-only sources start recording before any dev win; a standing defect lane runs alongside.

Rules 13-15 are a DRAFT from the 2026-10-31 research review (`claude/research-review-20261031` @ `acaf441b4`), pending
master review; they bind only once master accepts them.

13. **Archive what is ruled out.** Every ruled-out candidate keeps its rule, result record, receipts and ledger/register
    pointers under `C:\archive\ruled-out\<folder>` (workstation; copies, never moves), indexed by `INDEX.md` and
    `index.json` there and built by its `build_index.py`. A register or ledger kill cites its archive folder.
14. **Intake prior: already priced.** No new single free-source T+0 screen on the US11 opens unless its S0 names a
    mechanism by which the *market* lacks the information at that hour. "It beats served" is not a mechanism: on the dev
    scorecard served is 1.53x (00-16) to 1.77x (all hours) the market's Brier (EF §10aa; 1.77x on the 111h table too,
    EF §10q), so almost any public input beats it. Without the mechanism the default reading is that the crowd already
    prices the source, and the screen is refused at intake.
15. **A family kill cites a measurement on the member it closes.** A member closed only by extension from a sibling's
    result is labelled **CLOSED-BY-RULE (reopenable)**, never KILL or COVERED, and its register row names the sibling
    and the rule that extended it. A new mechanism or a measurement on the member itself reopens it.

## Update this file when

A lane shows a rung of this method wrong or missing, a ruling changes the measurement ladder, or a new
look-ahead or comparator trap costs a result. Results go to the digest and established findings, not here.

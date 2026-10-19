# DRAFT, UNSIGNED: EDGE-1 — model versus market, forward instrument annex, 2026-10-19

> **Status: DRAFT-UNSIGNED, NOT ACTIVE.** Written on the workstation (model-edge week 1) for the owner's single
> sign-off on Fri 2026-10-23. It authorises nothing: no scoring, no reservation, no alpha, no code, no stage, no
> serving change. It binds only once the owner signs it together with the
> [methods annex](prereg-template-and-methods-annex-DRAFT-2026-10-19.md) (section 11).
>
> **Signed SHA-256:** `________________________________________________________________` (left blank; recorded in the
> DECISION_LOG signing row with the methods-annex SHA-256 and the three arm hashes).
>
> **Data rule this draft was written under:** no label, settlement, market price, 88a, panel or score data for any
> UTC date >= 2026-09-30 was read; nothing for 2026-10-16..11-13 was read, counted or enumerated. Every number is from
> development dates <= 2026-09-29 (sizing only) or computed from no data (the futility table).

- **Owns:** the EDGE-1 instrument: arms, dates (both OD-A6 branches), hypotheses, looks, falsifiers, and its
  interaction with MG-1, the evening-fix scorer and t3-r3.
- **Methods:** adopts annex sections M0-M8 unchanged; deviations are listed in section 9.
- **Read when:** building an EDGE-1 arm, freezing its hash, building the scorer, or scheduling or running its looks.
- **Do not use for:** what a result triggers ([GO/NO-GO rule](go-no-go-rule-DRAFT-2026-10-19.md)); alpha accounting
  ([alpha ledger](alpha-ledger-DRAFT-2026-10-19.md)).

## 0. Why, and what EDGE-1 is not

- EF §1 / FD line 3: "the model does not beat the market, and the gap is missing information". That conclusion predates
  the serving repairs (lock-in v3 2026-10-06; v4 floor and M0 keying 2026-10-09), and the exhaustion register's first
  exit criterion (EXHAUSTION_REGISTER §5 order 1, L1) is a post-fix forward model-vs-market measurement, which is
  unregistered. EDGE-1 is that measurement, with a decision attached.
- **Not** a re-test of MG-1, the evening-fix scorer or t3-r3. Those stay exactly as signed (section 6).
- **Not** a promotion. A GO enters the existing release gates (GO/NO-GO rule §3); it serves nothing by itself.
- **Scope clause:** every EDGE-1 date is out of season (EF §2, MG-1 §3 season statement). A NO-GO means **"no
  out-of-season edge"** for these arms, not that no in-season edge exists.

## 1. Arms (frozen as hashes before D0; M5.2)

| Arm | Definition | Endpoint | Frozen when | Input-removed twin (M7.3) |
| --- | --- | --- | --- | --- |
| **A0** | The served model as served after 2026-10-09: `ML_MODEL_VERSION` v0.5.12 (lock-in v3 + v4 pre-lock-in floor + #189 keying), default switches, the active bundle; the captured served vector of record, release id per row. | E1 | arm hash taken at signature from the served release manifest | A0 with its forecast-feature inputs removed: the same post-processing (floor mask, lock-in stages, fallbacks) applied to a climatology-only centre [PLACEHOLDER: twin spec frozen by Thu 10-22] |
| **A1** | A0 + the t3-r3 stage `remaining_rise_floor_v1` (artifact sha256 `b727fe1a897f8786afcd89514f0bae4a82d9e03ad951f2d72db9e228dd2afb09`, as signed DL 2026-10-16) + the non-NBM development survivors listed below, composed in the listed order, **frozen as one hash**; shadow only. | E1 | one hash before D0 | A0 (A1 with every added stage removed) |
| **A2** | The E2 blend (M2): linear pool per block of **A0** and the snapshot market vector, weights w_b fit on 2026-07-31..2026-09-29 only, weight file frozen into the hash. | E2 | weight fit and hash before D0 | the same blend with A0 replaced by A0's twin |

**A1 survivor list — PLACEHOLDER, filled from the development screens by Thu 2026-10-22:**

| # | Survivor id | Registry / screen output hash | Reads NBM? (must be NO) | Order in A1 |
| --- | --- | --- | --- | --- |
| 1 | `<PLACEHOLDER>` | `<sha256>` | NO | `<n>` |

Rules for the list: a survivor must come from a development screen on dates <= 2026-09-29, read **no NBM station
guidance** (anything that does belongs to the MG-1 reserved family, reserved-confirmation-window.md), carry zero or
frozen parameters, and pass the screen's own training-score check (EF §5). An empty list is allowed (A1 = A0 + t3-r3).
Nothing may be added after the arm hash is frozen.

**A2 uses A0, not A1,** because A1 is not frozen before 10-22 and A1 inherits the t3-r3 conflict (section 6.3). Owner
option OD-E5: blend A1 instead.

## 2. Population, D0 and looks

- **Markets:** US11, the 11 US markets of EF §10q / MG-1 / t3-r3 (fixed). Toronto reported beside with no alpha (no
  NBM, item 337 no-METAR rows).
- **Countable date:** M0 (at least 9 of 11 countable markets; ledger labels only).
- **Every countable date from D0 counts, no skipping, until 45.** Interim at the 20th, final at the 45th.

### 2.1 OD-A6 and the two D0 branches

OD-A6 is in the evening-fix pre-registration (§3.3 and §10): *"Confirm the MG-1 narrow-scope reading and the 88a-hold
reading for snapshot market vectors."* Its current status in DECISION_LOG:

- 2026-10-13 signing row: "OD-A6 states no labelled default; master is asking the owner".
- 2026-10-15 row (owner "approve all", relayed): **"A6 MG-1 does not cover the anchor path, and the scorer runs with
  `--no-market` (primary NEW vs OLD Brier; 10-16..10-27 market prices stay unread)"**.

So the MG-1 half of OD-A6 is ruled; the 88a-hold half was **sidestepped, not ruled**: the evening-fix read avoids
market prices instead of deciding whether stored snapshot market vectors are covered by the 88a panel hold. Master-agent
(2026-10-19, relayed) recommends that the owner rule them **"not held for pre-registered forecast scoring"**. Both
branches are drafted; the owner's ruling selects one, and that ruling is a dated DECISION_LOG row written before D0.

| Branch | D0 | 20th countable date (interim N), earliest | 45th countable date (final N), earliest | Interim read, earliest | Final read, earliest |
| --- | --- | --- | --- | --- | --- |
| **Not held** (master-agent recommendation) | **2026-10-25** | 2026-11-13 | 2026-12-08 | 2026-11-15 (second local day after the 20th date's settlement; also after the 11-13 panel close) | 2026-12-10 |
| **Held** | **2026-10-28** | 2026-11-16 | 2026-12-11 | 2026-11-18 | 2026-12-13 |

- The calendar columns assume every date is countable; each missed date moves the look one date later. They are
  logistics (DL 2026-10-13), not rules.
- **Embargo, binding in both branches:** the owner refused all descriptive reads of UTC 2026-10-16..11-13 until the
  panel closes, with scored reads only after the close under a signed pre-registration (DL 2026-10-17). Every EDGE-1
  join therefore happens after 11-13 whatever the branch; under the not-held branch the interim's 20th date is the
  close date itself, so the interim cannot run before 11-14.
- **Gate 1 (2026-12-07)** in the GO/NO-GO rule sees the EDGE-1 interim, never its final, in both branches.
- **D0 non-outcome conditions (both branches):** D >= the branch date; the A1 and A2 shadow stages deployed with their
  frozen hashes before D's first T+0 snapshot in the earliest US timezone, with one full prior day of stored vectors
  (t3-r3 §5(b) form); D after the Toronto date of the signature. If the stages are late, A0 still starts at the branch
  date and A1/A2 start at their own first eligible date; each arm then counts its own 45 dates, and the D0 per arm is
  recorded in the signing commit's follow-up docs change.
- **Seasonal segments reported, no alpha:** before/after DST end 2026-11-01 (OD30 lapses 11-02); before/after any
  served-release change.

## 3. Hypotheses (the Holm family, M6)

| Id | Arm | Endpoint | Declared block | H1 |
| --- | --- | --- | --- | --- |
| H-A0 | A0 | E1 | 00-16 | R < 1 |
| H-A1 | A1 | E1 | 00-16 | R < 1 |
| H-A2 | A2 | E2 | 00-16 | D_E2 < 0 |

- **Family: one-sided α 0.025, Holm across the three** (0.025/3, then 0.025/2, then 0.025). A hypothesis marked
  UNTESTABLE before D0 (M4.4) leaves the family and k drops.
- **Why 00-16 and not each sub-block:** declaring the four sub-blocks for each arm would make k = 12 and the first Holm
  step 0.0021. The sub-blocks 00-05, 06-09, 10-12, 13-16 are reported with their intervals, no alpha; the GO/NO-GO
  rule's NO-GO test reads their **lower** bounds, which needs no alpha. Owner option OD-E3: declare per-block
  hypotheses instead.
- 17-23: differences only (M0 ratio floor), no alpha.
- **Seeds (fixed at signature):** fixed-market 20261023, crossed 20261024, 10,000 draws each (M3).

## 4. Looks

- **Interim (20 countable dates): futility only, non-binding, spends nothing.** Boundary per M4.2: **c = 0.2656** for
  each of H-A0, H-A1, H-A2 (α_d 0.025, β 0.20, t = 20/45). "EDGE-1 crossed futility in every arm" (GO/NO-GO Gate 1)
  means Z < c for every hypothesis still in the family.
- **Final (45 countable dates):** Holm on the three p-values, then the falsifiers (section 5) for each rejected
  hypothesis.
- **H-A1's interim and final are additionally gated by section 6.3** (the t3-r3 look).

## 5. Falsifiers binding on any GO (M7, restated with EDGE-1 values)

1. **Crossed (date × market):** crossed point estimate on the same side and crossed one-sided 80% upper bound below 1
   (E1) or 0 (E2) [80% PROPOSED, OD-T2].
2. **Per-market sign:** R_m < 1 (E1) or D_m < 0 (E2) in **at least 8 of 11** markets, block 00-16.
3. **Input-removed twin:** effect_twin / effect_arm **< 0.75** on the same rows, using the section 1 twins.

All three must hold for a GO; failing any one gives no GO from that hypothesis, with no amendment on the same dates.

## 6. Interaction with signed instruments (they stay exactly as signed)

### 6.1 MG-1 (`b044e0f1`, window bound D0 2026-10-15, provisional last 2026-11-28, may only move later)

- MG-1 reserves its dates only against NBM-guidance-to-band candidates (reserved-confirmation-window.md). **No EDGE-1
  arm reads NBM guidance**: A0's served model selects no NBM column (EF §10h); A1's survivors must be non-NBM (section
  1); A2 blends A0 with the market. Scoring the served vector and market vectors on reserved dates is in MG-1's
  exemption ("every other use of these dates' captures, served vectors and settlements").
- EDGE-1 never reads the MG-1 vector, its stage, or any NBM read; it never modifies MG-1. An arm hash that included
  any of them would be refused before D0.
- No (family, date) double-spend: MG-1's family is the morning NBM guidance read; EDGE-1's families are model-vs-market
  (E1) and blend-vs-market (E2).

### 6.2 Evening-fix scorer (prereg sha256 `16ed20df…`, window 10-16..10-27, outcome-blind extension to 10-29, one look 2026-10-29, `--no-market`)

- Its window ends before both D0 branches except for its extension dates 10-28 and 10-29, which overlap the "held"
  and "not held" EDGE-1 windows. Its family (NEW vs OLD lock-in anchor, 17-23) is different and it reads no market
  price, so there is no family double-spend; EDGE-1 reads nothing for 10-28/10-29 before the evening-fix read (10-29,
  latest 10-31) because the 10-17 embargo already holds every EDGE-1 join until after 11-13.
- A0 contains the evening fix. EDGE-1 does not test it; its 17-23 numbers are reported only as differences.

### 6.3 t3-r3 13-16 (signed sha256 `71cdb452…`, artifact `b727fe1a…`, one look at N = 45 from its first eligible date)

**Conflict, needs an owner decision (OD-E1).** A1 contains the t3-r3 stage. t3-r3 §6 forbids any settlement join,
Brier or market comparison on its holdout dates before its look, and §8 voids the look on "any holdout outcome read
before the look". Its first eligible date is not yet dated (stage deployment, §5), so its 45-date holdout will overlap
EDGE-1 in either branch. Scoring A1 at the EDGE-1 interim or final before the t3-r3 look would void t3-r3. Note also
that the reservation file records no t3-r3 reservation ("no date is held out against anything else") although DL
2026-10-15 took OD-B5's narrow default; the signed t3-r3 no-peeking rule binds either way.

Options (default **a**):
- **(a)** H-A1's looks are deferred until after the t3-r3 look; A1 keeps its frozen hash and its 45 dates, and its
  interim is skipped if the t3-r3 look comes later than the EDGE-1 final date (H-A1 is then final-only).
- **(b)** Drop t3-r3 from A1 (A1 = A0 + survivors), removing the overlap.
- **(c)** A new owner decision exempts A1 from t3-r3's no-peeking rule; this voids nothing only if the owner rules
  that A1-vs-market is not a t3-r3 outcome read, which this draft does not recommend.

### 6.4 Alpha ledger

EDGE-1 adds one family (three hypotheses, 0.025 one-sided, Holm) and reserves no date against any other family. It
spends no CAMPAIGN_LEDGER decision. Rows: [alpha ledger](alpha-ledger-DRAFT-2026-10-19.md) `EDGE1-*`.

## 7. Validity (M8) plus EDGE-1 specifics

- A served-release change on the 00-16 path inside the window voids the A0/A2 dates after it unless a segment rule is
  signed before it lands; the #162 landing and any item-337 flip are such changes (EXHAUSTION_REGISTER L18).
- The A1 and A2 shadow stages must store their arm hash per snapshot; coverage below 90% in 00-16 voids that arm.

## 8. Power

- **Power simulator run: `<SLOT: H3 (claude/harness-v3-20261019) run id and output SHA-256>`.**
- **MDE80 at 45 dates per hypothesis: `<SLOT: H3>`;** UNTESTABLE test per M4.4 applied before D0.
- **Projected futility probability at 20 dates: `<SLOT: H3>`.** Until it exists, "NO-GO is likely within ~20 dates"
  is INFERENCE.
- **Power cost of the interim: `<SLOT: computed by H3/H7>`.**
- Development sizing context only (dates <= 2026-09-29, EF §10q): A0-like served/market 00-16 ratio 1.49 (1.29 after
  both repairs, which includes MG-1, not an EDGE-1 arm). An E1 pass for A0 would need the post-fix out-of-season
  ratio to fall below 1 from that region; this draft predicts nothing.

## 9. Deviations from the methods annex

None.

## 10. What this draft does NOT claim

- No development figure is evidence; the A1 survivors are leads until scored here.
- No market-making result: E1/E2 are forecast endpoints. The maker endpoint E3 is a separate instrument
  (GO/NO-GO rule §2.3).
- No in-season claim (section 0 scope clause).

## 11. Signature

UNSIGNED. On signature the owner adds one DECISION_LOG row with this file's raw SHA-256, the methods annex's raw
SHA-256, the OD-A6 branch (D0), and the A0/A1/A2 arm hashes (A1/A2 may follow in a second row before D0, logistics
only if the arm definitions above are unchanged).

## 12. Owner decisions this draft needs

- **OD-A6 (88a hold for snapshot market vectors):** not held → D0 2026-10-25 (master-agent recommendation); held →
  D0 2026-10-28.
- **OD-E1:** the t3-r3 conflict (section 6.3): (a) default, (b), or (c).
- **OD-E2:** sign or amend (arms, N 20/45, Holm over H-A0/H-A1/H-A2).
- **OD-E3:** 00-16 declared block (default) or per-block hypotheses.
- **OD-E4:** the A1 survivor list as filled on 10-22 (logistics if it meets the section 1 rules).
- **OD-E5:** A2 blends A0 (default) or A1.

## Sources

- [Methods annex](prereg-template-and-methods-annex-DRAFT-2026-10-19.md); [GO/NO-GO rule](go-no-go-rule-DRAFT-2026-10-19.md); [alpha ledger](alpha-ledger-DRAFT-2026-10-19.md).
- [MG-1](../morning-guidance-read-mg1-preregistration-2026-10-04.md); [evening-fix](../evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md) §3.3, §10; [t3-r3](../remaining-rise-13-16-preregistration-DRAFT-2026-10-13.md) §5, §6, §8, §9.
- [Reserved confirmation window](../../operations/reserved-confirmation-window.md); [DECISION_LOG](../../operations/DECISION_LOG.md) rows 2026-10-04, 2026-10-13, 2026-10-15, 2026-10-16, 2026-10-17.
- [Exhaustion register](../../operations/EXHAUSTION_REGISTER.md) §0.2, §3 (L1, L18), §5; [findings digest](../../operations/FINDINGS_DIGEST.md); EF §1, §2, §5, §10h, §10q.

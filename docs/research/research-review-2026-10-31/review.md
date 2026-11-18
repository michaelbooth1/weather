> Dated research evidence, not canon and not instruction. An independent read-only review (Fable subagent) commissioned by the master agent on 2026-10-31 at the owner's request ("may be worth doing a focused review of all our research so far with a subagent see if any new takeaways"). Inputs: master 1a78e1ba0 plus the unlanded 10-30 workstation branches. Takeaways that are adopted are recorded in their owning canon documents; where this file and canon disagree, canon wins.

# Independent review of the model research, 2026-10-31

Read-only review of canon on master (1a78e1ba0) plus the unlanded branches successor-batch-20261030,
register-drafts-20261030, remaining-lever-map-20261030, claim-check-0930-1014-20261030 and the
register/method text on docs-owner-20261030. No data, logs or tapes were opened. "EF" = ESTABLISHED_FINDINGS,
"RF" = RETRACTED_AND_FALSE_LEADS, "FD" = FINDINGS_DIGEST, "XR" = EXHAUSTION_REGISTER, "DWL" = DEV_WINDOW_LEDGER,
"LI" = LEVER_INVENTORY_2026-10-26, "MIM" = MODEL_IMPROVEMENT_METHOD, "SOP" = STATE_OF_PLAY, "B" =
B_FORWARD_TEST_DESIGN. Confidence: H / M / L.

## Summary for the owner (plain language)

The research is unusually disciplined and I found no result I would reverse. But the pattern across roughly
100 screens is now clear enough to state as a conclusion rather than a list: every free public forecast and
observation source we can reach is already in the Polymarket price. Those sources beat our own model, which is
why our model loses to the market, but none of them beats the market. The market's remaining advantage has two
parts we cannot buy for free: it reprices on each METAR faster than our capture receives it (the afternoon gap),
and in the morning it knows how much to trust the guidance on a given day (the "sharpness" gap), and no ensemble
spread we tested predicts that.

Three things in canon are weaker than they read. Many "KILL (null)" verdicts are too small to see on a 43-date
window, not evidence of zero; a handful of helpful sub-threshold effects were never pooled; and the rule against
sharpening the forecast rests on a panel the register itself marks tainted plus one unpowered read. None of
these is likely to yield a tradable edge alone, but they should be relabelled.

The two inputs you just approved are the only untried directions with real upside: other venues' prices
(Kalshi history is free and overlaps our cities) and the 09-30..10-14 read, which today is blocked by a lapsed
maker-replay claim that needs one decision-log row from you. T+1/T+2 markets, where the market has no
observations yet, are blocked by the same claim, not by evidence.

My estimate: the chance that any forecast built from free data beats the T+0 market mid on the 11 US markets is
well under 10 percent. B will most likely read INCONCLUSIVE. The result that would most change that is a
cross-venue price test.

## Ranked takeaways (NEW first)

**1. NEW (H). Free public data is in the price; the gap is ours, not the market's secret.** Every free source
scored at capture time AGAINST THE MARKET on the dev window is null, wrong-signed or harmful: the K = 17
market-residual sweep of Open-Meteo centres, GEFS, NBM skew and METAR features (XR X46-X62, docs-owner), the
forecast-tracking family (X66-X70), Toronto NBM (X64/X65), and tonight's marine, GEFS spread, MOS, MRMS, GEM and
citypage reads (register drafts X73-X81; DWL rows 87-91). The same sources beat our served model handsomely
(MG-1 -0.0100 [-0.0179, -0.0035] over served, EF 10q; L6, P3d_N, EF 10ab/10aa). So the 1.4-1.8x served-vs-market
ratio measures a deficit in our pipeline, which the Oct-24..30 lanes have closed to R 1.16-1.28 (EF 10ad,
10ah), and the residual is information the market has and no free source carries. Consequence: stop screening
single free sources at T+0 for the US11; the default prior for any public feed is "already priced".

**2. NEW (M). Where the market's advantage actually sits: speed on observations, confidence on guidance.**
The gap grows through the day (served/market 1.44-1.45x at 00-09, 1.81x at 13-16 after both repairs, EF 10q
ladder), guidance helps overnight and harms the afternoon (EF 10p), and the dead-bucket audit shows the market
reprices on a METAR before our capture holds it ($0.37/day obs-dated became $0.03 receipt-dated; EF 10ad; X24
reopen condition "observation receipt latency falls well below book repricing"). So afternoon levers are a
latency race on public observations, which a free pipeline will not win. In the morning the loss is already full
size at h07 (LI row 2 caution) and sits in winner-bucket mass (market 0.415 vs 0.29-0.33 ours, EF 10ag); no free
spread predictor explains it (X37 NBM spread, X43 GEFS SD, X54/X55 multi-model dispersion, X75, X38/X39 HRRR
spread). My inference: the market's edge is judgement about when to trust the guidance plus execution speed.
Neither is a data source.

**3. NEW (H on the relabel, M on the size argument). Most "KILL (null)" rows are size statements, and the
register's own key says so.** XR section 2 defines a kill as "the interval excludes the 5% bar" and
"TESTED-UNDERPOWERED" as "the interval includes the bar". The dev MDE80 at 07-12 is 0.005-0.006 Brier against a
bar of about 0.0012 (EF 10y; LI "the dev window cannot confirm small steps"). Yet XR section 6 labels X4, X5,
X6, X8, X11, X17, X19 and X43A KILL with intervals that include the bar. The market-residual P0s have no bar in
Delta units at all; their CI half-widths are about +/-0.04-0.05 pooled (X59, X76, X78) and +/-0.16 for Toronto
alone (X80). The saving grace, which canon does not state: a B PASS needs R <= 0.95 (B section 6, margin
+0.0027), roughly a 5% Brier gain, which needs a correlation with the market residual of order 0.2, far above the
P0 detection limit. So the P0 kills are safe for the EDGE question and unsafe as statements about information.
Relabel the sub-bar rows TESTED-UNDERPOWERED or "KILL at edge size"; keep the reopen lines.

**4. NEW (M). The helpful sub-threshold set was never pooled on the window where it was measured.** MIM
section 5 rule 5 (10-30) and XR L14 require batching; the one batch run (successor C1/C2, DWL rows 85-86)
tested two components on Oct-Dec HISTORY and both dropped. Dev-measured helpful point estimates that were killed
singly and never pooled: R-Q A -0.00260 [-0.00650, +0.00094] (X43, four times its LOYO PASS effect), R-I
-0.0022 (X19), blend(L6, P3d_N_fix) - L6 -0.0096 [-0.0187, +0.0003] (X17), A2 -0.0016 (X8), upstream ASOS
-0.0005 (X11), F2 MRMS -0.0005 [-0.0010, -0.0001] (X7), R-PD -0.0232 [-0.0520, +0.0047] (X31), R-N -0.0105
(X32). Several were closed "at full breadth" (R-Q, R-I, R-M X36/X82) so they cannot re-enter under any rule
name. One pre-registered joint read of this set against the market (the w gate, MIM section 3 rung 4) is cheap
and is the last honest use of the dev window. Caveat: the set is selected for helpful signs, so treat a pass as
a screen only.

**5. NEW synthesis (M). The sharpening prohibition rests on a tainted panel plus one unpowered read, and was
extended by rule.** "Never sharpen globally" (FD; EF 1, 1c, 1g) comes from the 16.494% recalibration bound fitted
on B and scored on stratum C; XR section 1 row 3 marks that number TAINTED ("do not re-cite it for the post-10-09
path") because C carries the evening no-op. R-I then killed fitted width maps for every NBM-anchored arm on a dev
read whose CI [-0.0156, +0.0104] could not detect its own LOYO PASS (-0.00045 [-0.00094, -0.0000084]; X19).
LI flag F3 already objects to the scope; the power point is new. The lever is bounded, not large: re-centring
plus tempering still leaves +0.0065 of the +0.0102 P3d_N_fix 07-12 excess (LI "two facts"), so a global
temperature recovers at most a third. The same by-rule extension closed Oct-Dec trajectory rungs "by family, not
run" (X18/X20 in DWL row 92 batch note) and ECMWF ENS spread, never scored, as "COVERED" (register draft X5
replacement). Recommendation: one Oct-Dec LOYO rung for day-specific width under R9, and a rule that a family
kill must cite a measurement on the family member it closes.

**6. NEW (H, textual). The headline "two thirds of the 07-12 excess is sharpness" has no canonical source.**
SOP Headline and FD line 64 cite EF 10ag; EF 10ag gives winner-bucket mass and the 25%/15% re-centring figures
but does not contain the two-thirds statement (the word "sharpness" appears once in EF, at line 2014, in another
context). The figure is the LI drafter's reading of R-H's "re-centre plus temper leaves +0.0065", i.e. dated
evidence promoted to a headline. It also sits awkwardly beside FD line 3 ("the gap is missing information, not
calibration"): day-specific sharpness is dispersion information, so both are true only with that gloss. Move
the derivation into EF 10ag or re-cite.

**7. NEW (M). Other venues' prices are the highest-EV untried lever and have free history.** XR S31 is NOT
TESTED; EF has no mention of Kalshi. Reason the Polymarket price might lack it: a different, US-regulated trader
population on overlapping city markets, so the two venues' implied distributions should disagree on some
mornings and the consensus should beat either alone. Kalshi publishes historical candlesticks and trades for
settled markets through its public API at no cost, so a market-residual P0 on the dev window is possible
without a recorder: does the Kalshi-implied band distribution at minute t predict Polymarket's residual at t?
It also gives B a free secondary comparator (no alpha). If the cross-venue signal is null too, takeaway 1
hardens into "no free information of any kind". If it is real, it is maker fair value (pillar B), not forecast
edge, and that is fine. Confirm the overlapping city list and the 2026 Aug-Sep coverage before writing the rule.

**8. ALREADY KNOWN, under-weighted (H). The post-fix served-vs-market read has never been made, and the
09-30..10-14 window is blocked by a lapsed claim.** XR section 5 orders 1, 2 and 6 are URGENT and undone; they
are structurally blocked by the SOP outcome embargo. The owner's one-time read is the first chance. But the
claim check (claim-check-0930-1014 section 1) finds every cell BLOCKED by maker replay v2 (C1): its lapse date was
2026-10-30 (DL:200) and no DL row records the lapse. First action: an owner row releasing the panel; then the
per-block served/MG-2 vs market atlas on those 15 dates, kill-only. Also surface: the evening-fix scorer read was
due 10-29 (SOP open commitments) and no result is in canon on master.

**9. ALREADY KNOWN, re-ranked (M). T+1/T+2 is the one market class where the market lacks observations.**
XR L8 and row 28: never measured; the served model has no T+1 output (FD). EF 10p shows guidance helps most when
no observations exist (00-09 gains, afternoon harm), which predicts guidance is most valuable at T+1. The block
is the same C1 claim and the 88a hold, not evidence. A day-2 NBM read against the 88a T+1 mid (the frozen
10-02 study) should follow the C1 release.

**10. ALREADY KNOWN (H). The forward tests cannot confirm a plausible edge and are scored out of season.**
B at N = 45 has power 0.63 / 0.43 for R 0.95 and 0.27 / 0.18 for R 0.97 (B section (d)); the candidate's dev R is
1.16-1.28 (EF 10ad, 10ah). INCONCLUSIVE is the modal outcome. Dev is Aug-Sep; B, L6_G and PT-1 are Oct-Jan; the
one Aug-Sep gain tested on Oct-Dec history reversed (R-PD, X31 -> X72 harm) and L9 found overnight low and
dewpoint flip sign by season (EF 10ac).

**11. NEW (H). The multiplicity denominator cannot be counted from canon.** MIM section 4 requires every
pre-registration to cite the dev reuse count; DWL on master ends at row 71 with rows 34-35, 63-64, 66-67 and
72-84 on other branches, X44-X70 live on docs-owner, and the 134-rule swarm block plus 79a/81a/111h are "not
itemised" (DWL pre-ledger table). The MG-1 lead already "fails Bonferroni at 134 rules" (DWL row 1). Land the
ledger fragments before the next prereg and publish one number.

**12. Judgement (M). Bottom line.** P(a forecast from free data beats the T+0 mid on US11) is under 10 percent;
the gap to parity (R 1.16-1.28) is about ten times any lever found, and the two largest components are speed
and judgement. The single result that would most change this is a positive cross-venue P0 (takeaway 7); the
second is a T+1 read. In the next two weeks: (a) owner records the C1 lapse; (b) post-fix per-block atlas on
09-30..10-14; (c) Kalshi history P0 on dev plus that window; (d) T+1 market-only read; (e) the pooled sub-bar
w-gate read (takeaway 4); (f) stop all other T+0 free-source P0s on dev; (g) keep B, MG-1, L6_G, PT-1 blind. If
(b)-(e) are null, the model-edge programme has met its own exhaustion standard and the remaining question is
maker economics, where the zero-edge maker breaks even across a wide range and the binding unknown is the
informed-fill fraction f, which only own-account fills identify (EF 1b.3, 8c). That is a different programme and
the owner's call.

## Appendix for agents

### A. Cross-cutting patterns (question 1)

- Forecast products (NBM, NBH, NBS, MOS, HRRR, GFS, ECMWF IFS/ENS, ICON, AIGFS, GEM, citypage) beat served and
  tie the market: EF 10q, 10y, 10ab; X46-X57, X76/X77, X80/X81. Observations (METAR, 1-minute ASOS, upstream
  ring, soundings, MRMS, marine) are the same or harmful: X2, X3, X11, X59-X62, X73/X74, X78/X79.
- Nowcast information decays into the market as the day advances: guidance gain -0.0127 at 00-05, harm +0.0155
  at 17-23 (EF 10p); the 13-16 block is the largest residual (1.81x, EF 10q) and the "gain" there equals the
  floor-only control (EF 10ad).
- The only served improvements were repairs of self-inflicted defects: floor 07-31 (EF 3), lock-in v3/v4 (EF 10q,
  XR 0.1). Every "information lead" that looked large was a defect or a comparator error (RF: evening rules,
  R-D blend, SM-N, dead bucket, NBH).
- History LOYO wins do not carry to 2026 dev or across seasons: R-P intercept (X30), R-PD (X31/X72), NBS TXN
  (X35), R-S (X37), R-Q A (X43), Toronto NBM A/B (X64/X65). Pattern: a pooled LOYO win is a bias correction
  unless it has a slope term and a mechanism (X30 lesson).
- Pooling across markets is the one modelling lever that repeatedly helps (EF 10aa, 10ac); per-market anything
  is dead (X8, X36, X82).

### B. Kills that may be wrong or premature (question 2)

| Row | Why it may be premature | What would settle it |
| --- | --- | --- |
| X19 R-I width | Dev CI 6x the LOYO effect; family closed by rule; panel C basis TAINTED (XR 1 row 3) | Oct-Dec LOYO day-specific width under R9 |
| X43 R-Q A | Gate 1 PASS, dev point -0.0026 helpful, upper +0.0009; killed at full breadth | Enter the pooled sub-bar read |
| X17 blend(L6, P3d) | -0.0096 [-0.0187, +0.0003], near miss, labelled NULL | Same |
| X31/X32 00-06 | Dev underpowered at 00-06 (XR text); C2 Oct-Dec harm supports the close for Oct-Dec only | Forward 00-06 arm if ever cheap |
| X64/X65 Toronto NBM | V4.x history vs V5.0 dev, uncorrected (row text) | 60 V5.0.14 days, labels |
| X77 MOS-NAM | BH-rejected at q 0.097; Atlanta +0.267 [+0.100, +0.425], Houston +0.246 [+0.051, +0.441] post hoc | Regional mechanism first, forward recorder (N80 about 218 dates, prereg draft) |
| X5 ENS spread | Never scored; "COVERED" by X54/X55 which are Open-Meteo multi-model dispersion | One P0 on the ENS member spread |
| X18/X20 Oct-Dec | "Ruled out by family, not run" (DWL row 92 batch note) while R-ODC G1/G2 PASS on Oct-Dec history (rows 65, 69, 70) | Run the Oct-Dec LOYO batch |
| EF 1b 114 cells | B and C pooled; C tainted (XR 1 row 5); never re-run; "quotable" undefined in EF (no spread or fee threshold) | Order 6 on post-fix dates |
| S4 NBS precise null | Zero-parameter pooled 00-16 read (LI F2) | Already partly covered by X35 |

Kills that are sound and should stay: F1 1-minute ASOS harm (X2), AFD (X10), dead bucket (X24/X25), R-D and
SM-N retractions, NBM all-hours (EF 10p), full-year R0 (X1), marine and MRMS against the market (X73-X79).

### C. Contradictions and stale statements (question 3)

- FD closed thread "Searching for a quotable model edge: 114 cells, zero positive" vs XR 1 row 5 PARTLY /
  per-cell map TAINTED, never re-run.
- FD "served in-season gap 1.423246x" vs XR 1 row 1: a replay-instrument number, TAINTED as a description of
  today's served path; EF 10p (1.77x) vs 10q (1.73x) disagree on the all-hours figure.
- XR section 2 status key (KILL = interval excludes the bar) vs XR section 6 KILL labels on sub-bar intervals
  (takeaway 3).
- SOP Headline and FD line 64 cite EF 10ag for "two thirds sharpness"; EF 10ag does not say it (takeaway 6).
- XR S31 "needs an owner call first" vs the owner's approval of other venues' prices (update pending).
- XR section 5 orders 1, 2, 6 URGENT vs the SOP embargo that blocks them; claim check C14 notes the tension.
- LI row 9 "closed by rule extension, not by measurement" vs lever map "KILLED (X54, X55)" and the register
  draft's X5 "COVERED": multi-model dispersion kills used to close the whole sharpness-information family.
- Lever-map refresh "No eligible edge-bearing lever remains in the dev window as of 10-31" is true of the
  enumerated inventory only; S31, T+1/T+2, foreign cities and the post-fix read are outside the enumeration.
- SOP "forward NBP CYYZ capture approved in principle" vs Toronto NBM KILL at P0 (X64/X65): the capture is now
  justified only by the version-confound reopen path; say so.
- DWL on master lacks rows 72-84; X44-X70 unlanded; SOP last rewritten 10-28 and does not carry R-Q, the
  successor batch or the 10-30 method rules (MIM section 5 is on docs-owner only).
- Evening-fix scorer read (due 10-29) absent from canon on master.

### D. Directions not yet tried, ranked (question 4)

1. Cross-venue prices (Kalshi, read-only; owner-approved). Mechanism: segmented trader populations. Cost: low;
   free history via the public API; one P0 rule reusing 85f8192c mechanics. EV: the only lever that could
   plausibly reach Delta of order 0.2.
2. Post-fix per-block served/MG-2 vs market on 09-30..10-14 (owner-approved, kill-only). Mechanism: none
   claimed; it re-bases every ratio (XR order 1). Cost: one atlas run after the C1 release.
3. T+1/T+2 day-2 NBM vs the 88a T+1 mid. Mechanism: no observations exist yet, so the market's speed advantage
   is absent (EF 10p pattern). Cost: medium; blocked by C1/88a, not evidence.
4. Pooled sub-bar w-gate read on dev (takeaway 4). Cost: hours. EV small but it is the last legitimate dev use.
5. Oct-Dec LOYO batch for width (R9) and trajectory (X13, X18, X20). Kill-only, history, cheap.
6. Foreign cities (London, Paris, Seoul, Shanghai, Tokyo, HK). Mechanism: thinner, less-watched markets with
   quirky resolution sources (EF 10c, 10x); also the only lever on the 3.2% MDE floor (EF 1d). Cost: high
   (recorders, 30+ days). Already in flight as R1/R2.
7. Venue-rule label mechanics after 10-23 (routine-only, tenths half-up, KDEN): 1.3% of station-days flip a
   band (EF 10x); the crowd may still price WU-style. Small, forward-only, free.
Not recommended: any further single free source at T+0 for US11; paid feeds (F1 harm kills them, X2).

### E. Methodological risks (question 5)

- Multiplicity: 134 swarm rules plus about 90 K rows on one 43-date window; MG-1 fails Bonferroni (DWL row 1);
  the denominator is uncountable from master (takeaway 11). The B candidate (MG-2) was selected on this window,
  so B is a winner's-curse-corrected forward test only if N and the margin were sized from forward variance;
  they were sized from R-H's dev sigma (B section (d)).
- Dev reuse: every date 08-15..09-29 has been read with outcomes well over 100 times; further P0s there are
  screens at best (MIM section 5 rule 1).
- Power labels: see takeaway 3. The 5% bar (about -0.0012) has no written derivation in EF (subagent read).
- Serial correlation: date clustering handles within-day snapshot dependence; cross-date persistence is lag-1
  0.09-0.15 with block-3 SEs reported only in the newest rows (DWL rows 85, 86, 92); EF has no statement on it.
  Forward tests should report block intervals (MIM rule 7 does so for new preregs; B does not).
- Comparator: the mid of a thin book is the yardstick; B's +0.0027 margin and the maker's spread are the only
  economic translation. Dev replay does not reproduce served (EF 10v), so dev deltas are "current code +/-
  variant".
- Family kills by rule extension (takeaway 5) and relabelled sizes (takeaway 3) are the two ways the register
  can overstate exhaustion.
- Forward design: one look, no futility for B (by design), power 0.63/0.43 at R 0.95; season mismatch; Denver
  excluded (10 clusters).

### F. Sources read

FD, XR, DWL, RF, MIM, LI, SOP, B, CAMPAIGN_LEDGER head, reserved-window status line, EF sections 1b, 1c, 1d, 2,
5, 10h, 10j, 10p, 10q, 10y, 10ab, 10ad, 10ag, 10ah (via a read-only extraction pass); git objects:
successor-batch (DWL rows 85-92 and notes, proposal, c1_result, nbm_freshness, tenths_aliasing, kden notes, the
six P0 rule files), register-drafts (X71-X82), remaining-lever-map and its 10-31 refresh, claim-check, and
docs-owner's XR X44-X70 and MIM section 5.

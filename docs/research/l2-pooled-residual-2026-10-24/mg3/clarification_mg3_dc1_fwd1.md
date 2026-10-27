# MG3-DC-1 clarification FWD-1: the rebuilt 07-12 state, the amended drop check and the 11-08 fallback (item 341)

Lane L3, 2026-10-27. Master approved the item 341 proposal on 2026-10-27, relayed by the coordinator. The proposal
is sha256 `9bde9b0de6f2096451cba3ad673143bc98f5e94e6a0d7f6f94a0ac6b5dccc3bf`.

This clarification amends two documents:

| Document | sha256 | Sections amended |
| --- | --- | --- |
| MG3-DC-1, `rule_mg3_paired_dc.md` | `a7c697618cd26cfac1184c148a39ee1d20a1ea612e048bd350363ba34022a031` | §2.2a, §2.3, §6 and §8, and the fenced block |
| Clarification 0712-1, `clarification_mg3_dc1_0712.md` | `f9e25a90e56a81326552867fee61ad37b8c159fe56abf6972225be25d459651f` | the weight sha and its evidence |

- **Written before any fit.** It is pushed before any fit or read it governs, and it quotes no new score.
- **Companion documents.** The state, controls, RF-2 and the LOYO are in `rule_mg3_p3dh_state_fwd1.md` ("FWD-1").
  The re-scoped comparison is row 67, `rule_mg3_fwdcmp.md`.

## 0. What does not change

MG3-DC-1's candidate and comparator definitions stay as they are, except for the 07-12 state and weight shas below.
Also unchanged:

- the hours table (00-06, 13-15 SM-H except SF, SF 13-16, 16 and 17-23);
- the 10 markets, the dates logic and N;
- the statistic, the interval, α, the one look, the verdict;
- the void conditions;
- MG3_D0 earliest 11-11 and latest 11-20.

The L6 partner stays SM-L6 `800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db`.

## 1. §2.2a drop rule, amended (LOYO, 2021-25)

### Why

The rebuilt state trains on Oct-Dec 2021-25, including the 2024-25 rows the original check scored. A
frozen-state read would therefore be in-sample. Master ruled that the check uses all five held-out years.

### Statistic

ΔB_cool = mean over equal (date, market) cells of [Brier(MG-3 07-12 arm) − Brier(MG-2's bound 07-12 arm)].

- **Rows.** Local hours 07-12; history Oct-Dec rows (the five Oct-Dec centres) of 2021, 2022, 2023, 2024 and 2025;
  the 10 MG3-DC-1 markets.
- **MG-3's 07-12 arm.** It is FWD-1 §5's blend:
  - the rebuilt specification's blocked-LOYO fold distribution for the held-out year;
  - in the blend with SM-L6 and the RF-2 weights;
  - with the MG-1 fallback and the rule-4 floor.
- **The true bound partner.** This is MG-2's bound 07-12 arm, SM-L6. Its held-out-year vectors are row 46's
  `loyo_vectors.parquet` `0fde7553ffba47cc37ca54a342d59ccbfd3adcd3e1da53bb18ac4548ad35d433`, which cover Oct-Dec
  2021-25 at 07-12. The proxy clause of §2.2a does not apply.
- **Scoring.** Both arms are scored on FWD-1 §5's per-fold support, with open edges (`edge_brier` semantics).
- **No-cycle keys.** Keys with no published cycle keep NaN extras and are scored on both arms. Their counts, and
  the statistic recomputed with them dropped, are reported. That recomputation is never a gate.

### Interval and rule

- **Interval.** Date-clustered percentile bootstrap, 2,000 draws, seed 20260921, 95%. U is the upper bound.
- **Rule.**

| Result | Effect |
| --- | --- |
| U < 0 | MG-3's 07-12 arm stays: the rebuilt state, RF-2 and SM-L6 |
| U ≥ 0 | 07-12 reverts to MG-2's bound 07-12 arm (Δ = 0); H1 narrows to 13-15; the WIN-block condition applies to 13-15 only; N, the dates, α and the look are unchanged |
| not computable before binding | treated as U ≥ 0. This covers: the 2021-23 seal missing; a FWD-1 control failing; a coverage-gate refusal; fewer than 90% of the 2021-25 Oct-Dec cells covered |

### What else is reported (never gating)

- each held-out year, each month and each hour;
- each market;
- the Aug-Sep folds;
- support edge counts;
- coverage.

### Power (planning)

- Scale: row 49 (b)'s interval on the same statistic for 2024-25 has a half-width of 0.0065.
- Over 375 date clusters, MDE80 ≈ 0.0059 on the ΔB scale.
- The caveats are the proposal's §4: LOYO folds are noisier, there are 10 markets rather than 11, and row 49 sets
  the scale only.
- A null is reported as a null at this power.

### Unchanged

The check is history only. It never refits, re-weights or re-selects anything. No other reading of the LOYO can
change this rule.

## 2. §2.3 frozen artifacts, amended rows

| Artifact | sha256 |
| --- | --- |
| State rule | `9e63899ddcfcbd795f10f0437c7bd9f9b6fc9740767b8d824818ef0f7f95cc5d`, amended by FWD-1 (`rule_mg3_p3dh_state_fwd1.md`; its sha256 is in the sidecar file) |
| P3d_H 07-12 state | `<FILL@FWD1>`: the rebuilt state of FWD-1 §1, controls FWD-1 §3 (export parity, the dev re-emit written twice and byte-identical, fold reproduction); ledger row 66. It replaces `e92764773e1614aae548ccfd74b3a60740f25105578abd045b0808fe6dd159c0`, which is not bindable |
| P3d_H 13-16 state | **not served; PENDING permanently by design** (FWD-1 §2). SM-H replaced it at 13-15, and SF 13-16 and h16 are MG-2's arm. `e891d884…` is never bound. "Every §2.3 field filled" (MG3-DC-1 §3) excludes this row, and a filled value refuses the binding |
| Weights | `<FILL@RF2>`: RF-2 (FWD-1 §4), replacing RF-1 `891be5640cef9fd3924b98f89f1068108acdf404fbd52a4721cb5d8d9ae8ded5` |
| L6 partner | SM-L6 `800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db` (unchanged) |
| Drop check (`drop_0712`) | `<FILL@BINDING>`: the FWD-1 §5 LOYO rows sha, U, and the branch taken |

All other §2.3 rows are unchanged: the weight rule, RN-1 and land, the forward parity rule, the emitter, MG-2 and B.

## 3. Fallback deadline: 2026-11-08 (master ruling)

The deadline is 2026-11-08, 23:59 local. If by then the MG-3 binding commit does not carry all of these:

- the rebuilt 07-12 state;
- RF-2;
- a computed `drop_0712` with U < 0;

then the §2.2a revert applies. 07-12 goes to MG-2's bound 07-12 arm, and H1 becomes 13-15 only (SM-H, unaffected).

- MG3_D0 conditions and N are unchanged. MG-3 binds with 07-12 identical to MG-2.
- Nothing after 11-08 can restore the rebuilt 07-12 arm into MG3-DC-1.
- Any later use of it needs its own forward rule.

## 4. §6 size and power: re-size (planning only, recorded at binding)

**Why.** The §6 SNRs came from Aug-Sep history. They are replaced, history only, by:

| Block | Source |
| --- | --- |
| 07-12 | per-date SD and mean of the date-mean (blend − SM-L6) on FWD-1 §5's Oct-Dec 2021-25 LOYO rows (10 markets) |
| 13-15 | SMH-1's `SM_H − P3d_N_fwd` rows (`loyo_rows.jsonl` `f6f96cbceb3d3435431847470008300725161b5c39215e11a65ef696fb392fd5`), with SF = 0 |
| 07-15 pooled | the date-paired sum of the two |

**What is recorded at binding.** The power table Φ(SNR·f·√N − 1.96) for f = 1, ½, ¼ at N = 22, 27 and 31.

**Limits.** This changes no decision input: not N, the dates, α nor the look.

**Current planning values** (proposal §4, using the old SNRs):

| N | Power at f = 1 / f = ½ | MDE80 on ΔB(07-15) |
| --- | --- | --- |
| 31 | 0.92 / 0.40 | ≈ 0.0085 |
| 22 | 0.82 / 0.30 | ≈ 0.0101 |

## 5. §8 ledger, amended

- **Row 40** (RF-1) stays as a record.
- **Row 41.** Its control targets no longer exist: R-R gate 4 was the Aug-Sep arm, and R-K gate 3 has been
  replaced by SM-H. Row 41 is superseded by FWD-1 §6's positive control, recorded under row 66.
- **Row 66** (PENDING before any run): the FWD-1 rebuild, covering the freeze, the controls, RF-2, the LOYO, the
  drop check and the positive control.
- **Row 67** (PENDING before any run): the re-scoped comparison, `rule_mg3_fwdcmp.md`.

## 6. Clarification 0712-1, amended

- **§1.** The bound 07-12 weights become RF-2 `<FILL@RF2>`. The partner is unchanged: SM-L6 `800072c7…`.
- **§2, reason 1.** Row 49 measured the blend with the Aug-Sep-centred state `e9276477…`. It is replaced as evidence
  by this clarification's §1 drop-check result.
- **§2, reason 2** (it matches MG-2's own 07-12 arm) stands.
- **§2, reason 3** stands.
- **§4.** The RF-1 fit-window disclosure applies to RF-2 unchanged.
- **§5.** The binding builder writes the RF-2 sha in place of RF-1's, under the same verified-load and refusal
  rules.

## 7. Fenced block (supersedes MG3-DC-1's `mg3_dc_rule_v1` block)

```mg3_dc_rule_v1
rule_id: MG3-DC-1
amended_by: FWD-1
candidate: mg3_asof_capture
comparator: mg2_asof_capture_as_bound
dates: b_rule_v1_countable_dates_from_mg3_d0
mg3_d0_earliest: 2026-11-11
mg3_d0_latest: 2026-11-20
min_surviving_dates: 22
markets: atlanta,austin,chicago,dallas,houston,los-angeles,miami,nyc,san-francisco,seattle
hours_primary: 07-15
identical_hours_excluded: 00-06,16,17-23,san-francisco_13-16
metric: brier_difference_mg3_minus_mg2
interval: date_clustered_w_date_2000_seed_20260921
alpha_one_sided: 0.025
looks: 1
look_after: b_look_receipt
p3d_h_state_0712_sha256: <FILL@FWD1>
p3d_h_state_1316_sha256: not_served_pending_by_design
sm_h_state_1315_sha256: b6bc242a8c2b679069a4090b8912eea3b80af160b6bc228424c846fb3b87a477
weights_sha256: <FILL@RF2>
l6_partner: 800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db
drop_0712_rule: U_cool_ge_0_or_not_computable_or_coverage_lt_0.90_or_not_bound_by_2026-11-08_reverts_0712_to_mg2_arm
drop_0712_scope: loyo_heldout_years_2021-2025_octdec_0712_rebuilt_spec_fold_support_open_edges
drop_0712_partner: sm_l6_loyo_vectors_0fde7553ffba47cc37ca54a342d59ccbfd3adcd3e1da53bb18ac4548ad35d433
drop_0712: <FILL@BINDING>
fallback_deadline: 2026-11-08
release_binding_sha256: <FILL@BINDING>
parity_rule_sha256: 2c6e6045dca379854c281195e0a51a61f0de400bc517ed7faa444b2900a6593e
mg2_release_binding_sha256: <FILL@BINDING>
b_scorer_sha256: <FILL@BINDING>
```

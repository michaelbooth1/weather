# F3-SIM-1 preregistration

DRAFT — not frozen. Freezes when the master lands this file (the JSON is embedded below) on the docs light
path; the freeze time is that merge's committer time.

Read when preparing or auditing the freeze. This draft owns the proposed bindings and source checklist.
The [protocol](../../operations/F3_SIM_TRIAL.md) owns the statistical definitions;
[rollout](../../operations/F3_ROLLOUT.md) owns gates; [runbook](../../operations/f3-maker-expansion.md) owns execution.
Nulls and `_source_` fields deliberately prevent this draft from being treated as a frozen prereg.
No separate JSON file lands. Phase B must reconcile the WP-02 schema and validate the extracted block.

## 1. Trial and hypothesis

F3-SIM-1 is proposed charter trial T5, one alpha arm T5-R, H0: mu ≤ 0.
Only simulated reward harvesting is evaluated; no orders or money.
Keys: `trial_id`, `charter_trial`, `arms`. Producer: WP-05 text, WP-02 governance.

## 2. Estimand and economic minimum

CFD is (city, family, event_date_local). Cluster by event date; sum included CFD net to portfolio daily net.
The estimand is expected daily pUSD net for the simulated 300 sleeve; economic minimum 1.50/day, subject to OD-09.
Keys: `inference.economic_min_pusd_per_day`. Producer: WP-12 / WP-05 protocol.

## 3. Universe

U36-H is the alpha universe; U80 adds the diagnostic lowest families. Freeze the exact 36 highest and 44 lowest
keys from WP-01 strata against the T046 universe hash. Built-in highest, Hong Kong and WU shells are excluded.
Do not substitute remembered city lists for the configuration producer.
Keys: `universe`, `events_sha256`. Producer: WP-01 / WP-08 / WP-14.

## 4. Dates and coverage

Proposed event dates 2026-11-17..2026-12-24 (38). Below 95% Tier A heartbeat coverage excludes a CFD outcome-blind.
Freeze the heartbeat-only 11-17..11-22 base-rate receipt. Incomplete VR-5 pagination excludes and counts the CFD.
Keys: `dates`, `coverage_rule`. Producer: WP-02 / WP-09 / WP-14.

## 5. Policy and NWP

Use F2's frozen quote offset, book check, size, caps and sleeve-loss basis, with T+1 station-local retirement 23:45.
Pin policy, strata and NWP schedule; the blackout is release minus 5 to plus 30 minutes, lengthen-only before freeze.
No example policy or quarantined analysis supplies a frozen value.
Keys: `policy`, `nwp`. Producer: WP-01, F2 freeze receipt at the T033 seal.

## 6. Simulator economics and latency

Pin queue `back_at_price`, route `mirror_v1`, midpoint/competition rules, account-day reward unit,
daily fee assertion, rebate threshold, payout and redeem lags, max book age and coverage definition.
Excluded CFDs retain their capital trajectory. World B re-scores the frozen trajectory without reselecting bands.
Each input/post/cancel latency is at least the measured F0/F2 p95 exported by WP-15.
Keys: `economics`, `latency`, `input_pack` (proposed). Producer: WP-11 / WP-06 / WP-14 / WP-15.

## 7. Envelope

Pin the 8-cell highest pre-day grid (four UTC blocks × AEA/AP), envelope hash, per-cell counts and held-out ratios.
Each cell requires at least 20 entries and median odd/even held-out share ratio in [0.67,1.5]; otherwise reward zero.
US validation also needs at least 70% of sessions within 2×. Failure kills the trial.
Keys: `envelope`. Producer: WP-07, with WP-01 strata.

## 8. Worlds and cost reserve

World A freezes k, m and envelope from learning evidence; world B uses the frozen formulas at the final look.
Both must pass. Pin r_c(cell), floor 2%, and the 1.5 transfer multiplier to uncalibrated cells via WP-15's cost table.
Keys: `worlds`, `cost_table`. Producer: WP-15 bridge and WP-12 worlds.

## 9. b sample and valuation

State dates, strata, source hashes and independent outcomes for T5-R CF fills on admitted calibration and dev books.
Count one outcome per city-family-event-date with any CF fill. The power basis is `mde_settlement_lots`,
`bands_assumed` 5.5 [A], 50 shares per band-day [A] and s 0.47 [A], fixed before calibration.
Apply OD-07's MDE ratio rule (MTM ≤ 0.7 × settlement) only if approved; otherwise settlement primary.
Print both MDEs and Var(b-hat); joint bootstrap includes b uncertainty. K-20 transfer treatment must be supplied.
Keys: `b_sample`, `valuation_rule`. Producer: WP-12 power_projection_v1; OD-07.

## 10. Unresolved inventory

At 2026-12-27 12:00 America/Toronto unresolved lots use the final captured adjusted mid primary,
and full loss for D-UNRES. Venue resolution supplies actual payouts; weather reconstruction never substitutes.
Keys: `unresolved_rule`. Producer: WP-11 / WP-05 protocol.

## 11. Alpha, inference and PASS

OD-02 chooses 0.05 or 0.0375 for T5-R. Use circular moving blocks 1 and 3, 10,000 replicates,
and an explicitly pinned seed; choose the wider interval. PASS needs lower bound > 0 in both worlds,
point estimate ≥ 1.50/day, settlement estimate > 0, accuracy gate PASS and two-date replay-check PASS.
The [protocol verdict matrix](../../operations/F3_SIM_TRIAL.md#pass-rule-and-verdict-matrix) is pinned by hash.
Keys: `arms[].alpha`, `inference`, `pass_rule_id`, `verdict_matrix_sha256`. Producer: WP-12 / WP-05; OD-02/09.

## 12. Looks

Use the protocol's L0 11-23 counts-only; L1 12-01 harm; L2 12-03 futility/early warning;
L3 12-10; L4 12-20; final 12-28 from 18:00. Interim rules spend no alpha and never adopt diagnostics.
Admission clocks belong to WP-03 scope rows, not a second dated code table.
Keys: `looks`. Producer: WP-05 protocol / WP-03 / WP-12.

## 13. Accuracy gate

Replays use VR-11/VR-5 via the trial adapter. Pre-VR-11 sessions need parity PASS.
Pin S15 tolerances, full population, binding minimums (8 sessions, 6 filled orders, 3 paid pUSD),
and master-ruled K-17 pre-gate minimums. Missing sessions are excluded and counted; report paid/simulated CI80.
Keys: `accuracy_gate`. Producer: WP-15.

## 14. Claimants

The run-time list includes **T033/F2, B, MG-1, L6_G, row-28b, PT-1, F8-MH, row 72 R-ODC and the L3 T+1
forward emit**, plus **every reservation** in `docs/operations/reserved-confirmation-window.md` and
**every open forward row** of `docs/operations/DEV_WINDOW_LEDGER.md`, parsed again at run time.
Record each source path and line, family/date scope and its intersection in the claimant report; never rely only
on the named list. Run against calibration before any calibration read, then against the trial before freeze.
Unparseable rows fail closed. Any intersection must be narrowed and checked again before reading.
Keys: `claimants`, proposed `claimant_report_sha256`. Producer: WP-02 run-time report; freeze receipt pins report hash.

## 15. Read scopes and tokens

List only landed WP-03 rows activated by qualifying DECISION_LOG tokens: OD-04-b1/-b2/-c calibration,
OD-03-a trial, OD-03-b LFC final gate. A token quoted in this draft never activates a read.
Keys: `read_scopes`. Producer: WP-03 and master DECISION_LOG rows.

## 16. Capture regimes

Pin WP-08 receipts for 88a flips and Tier B state, including effective time, config hash and 24-hour check.
Keys: `capture_regimes`. Producer: WP-08 capture_regime_receipt_v1.

## 17. Admissibility table

All rows of revised design §2A.4 follow. The table has 14 parameter rows; the power-basis row is retained.
Only the exact UTF-8 LF bytes between these markers are hashed; do not normalize trailing whitespace.

<!-- admissibility:start -->
| Parameter | Value or rule | Source | Admissible because |
|---|---|---|---|
| Quote offset | F2's frozen confirmation offset | F2's freeze receipt at the T033 seal (Mon 11-16 17:55) | F2's own pre-declared rule and own records (owner opened own-session records 11-07 21:19) |
| Book check, size, caps | F2's `check_book`; 20 shares; $15.80/order; $19.60/band; $40/band-day; I + R + new + max(0, L + C − G) ≤ 300 | F2 code and policy at F2's freeze sha at the T033 seal (Mon 11-16 17:55) | owner money terms; code |
| Sleeve-loss basis | read from F2's freeze receipt | F2 | never a constant (N5) |
| NWP release times | GFS, AIFS, IFS open-data nominal availability per cycle | `[R] sources/nwp-catalog.md` §3 | documentation and file-time measurements, not market data |
| Blackout length | [t − 5, t + 30] min; may only be lengthened before freeze, from admissible fills | D3 §3.4; RE-1 (EF §10m) | RE-1 is own, dev-dated (09-23..09-25) |
| Local-midnight retirement | 23:45 local | ASSUMED conservative margin | not fitted to any data |
| Envelope (shape, A or κ, τ_r, lower-20% quantile) | fitted per transfer cell | calibration scopes (OD-04) + F2's own sessions | owner-opened scope |
| Transfer grid | 8 cells (§5.6) | pre-declared here | no data |
| World A k, m; cost reserve r_c; latencies | F2 learning sessions | own records | open |
| Bias allowance b (MTM only) | CF fills of T5-R on calibration scopes + dev ≤ 09-29; n_b counted as independent event outcomes with ≥ 1 CF fill (§5.10) | OD-04 + dev | owner-opened / dev |
| Power basis | settlement MDE = lots anchor (WP-12 §7.5), `bands_assumed` 5.5, 50 shares per band-day, s = 0.47 | capital arithmetic 300 / (19.6 + 1.75 × F) at an assumed F = $20 filled cost per band-day (D3 §6.2: F2's $19.60 per-band cap and $40 daily cap); fixed 11-09 before any calibration read | F2's caps plus an ASSUMED fill intensity; no a1–a4 input; not fitted (G6) |
| Cluster cap | ≤ 3 bands per geographic cluster | geographic grouping | not fitted |
| Coverage threshold, tolerances, economic minimum | 95%; S15 set; $1.50/day | ASSUMED | not fitted |
| Payout unit | account-day unless F0/F2 paid rows show per-condition | own records | open |
<!-- admissibility:end -->

Keys: `admissibility_table_sha256`. Producer: WP-05 table / WP-02 hash helper.

## 18. Frozen-element checklist

All frozen elements have a producing package or a master act. There is no producerless element.
The complete mapping has two schema destinations that WP-02 must add before freeze:
`input_pack.reader_version` and `input_pack.tzdata_version`. These are **proposals, not accepted schema**;
WP-14 already produces both in its pack manifest. The draft also proposes `input_pack.manifest_sha256`
to bind those values to the manifest. Until WP-02 confirms the shape, phase B must refuse to call this freeze-ready.

The claimant intersections live in the run-time report, whose hash WP-02 already records in the freeze receipt;
`claimant_report_sha256` in the draft is a proposed explicit prereg pin, not a missing producer.
The revised admissibility table contains **14 parameter rows**, despite the handoff's “13 rows” wording.
Every row is retained. Pending technical calls K-16 (completeness population), K-17 (pre-gate minimums),
K-20 (b transfer treatment) and K-2 (sealed accrual admission) are decisions, not missing producers.

| Frozen element (§5.11) | JSON key | Producing WP | Receipt / source (WS trial root unless stated) |
|---|---|---|---|
| Repository code | code.repo_sha | WP-02 / master | freeze_receipt.json: code; landing Git commit |
| T1 simulator code | code.t1_sha | WP-02 / WP-11 | run branch ancestry and simulator run receipt |
| Engine code | code.engine_sha | WP-11 / master | engine line tip and sim run receipt |
| Governance code and digest | code.gov_sha; code.f3_code_digest | WP-02 | freeze_receipt.json: code |
| F2 code and policy | code.f2_git_sha; code.f2_policy_sha256; policy.f2_freeze_receipt_sha256 | WP-01 / WP-15 | F2 policies/freeze.json at the T033 seal; lfc_bridge_v1 |
| Landed T046 code | code.t046_sha | WP-10 / master | landed squash commit; WU no-refinalize confirmation |
| Universe | universe.path; universe.sha256; universe.u36h_keys; universe.u80_keys | WP-01 | config/f3/strata.json and pinned config/weather_universe.json |
| Events | events_sha256 | WP-08 / WP-14 | VR-3 event inventory in verified trial_input_pack_v1 manifest |
| Pack reader version | input_pack.reader_version (PROPOSED; absent from WP-02 schema) | WP-14 | trial_input_pack_v1 manifest: reader_version |
| tzdata | input_pack.tzdata_version (PROPOSED; absent from WP-02 schema) | WP-14 | trial_input_pack_v1 manifest: tzdata_version |
| T5-R policy and frozen offset | policy.path; policy.sha256; policy.f2_frozen_offset_pusd | WP-01 | candidate f3_policy.json derived from F2 freeze receipt; config hash |
| Caps and sleeve basis | policy.sha256; policy.sleeve_loss_basis | WP-01 | f3_policy.json: caps and sleeve_loss_basis from F2 freeze receipt |
| G-NWP schedule and window | nwp.schedule_path; nwp.schedule_sha256; nwp.before_min; nwp.after_min | WP-01 | config/f3/nwp_release_schedule.json; lengthen-only window |
| Envelope file and grid | envelope.path; envelope.sha256; envelope.strata_sha256 | WP-07 / WP-01 | response_envelope_v1 and config/f3/strata.json |
| Per-cell entries and held-out results | envelope.cell_entry_counts; envelope.heldout; envelope.us_validation | WP-07 | response_envelope_v1 and envelope_validation_v1 |
| World A parameters | worlds.A | WP-12 / WP-15 | lfc_bridge_v1 learning export and response_envelope_v1 |
| Cost reserve r_c table | cost_table.path; cost_table.sha256 | WP-15 | f3_cost_table_v1 in exports/ |
| b sample | b_sample | WP-12 | power_projection_v1 plus independent-event b-sample receipt and source hashes |
| Latency bounds | latency | WP-15 | lfc_bridge_v1: latency_p95_s |
| Queue rule | economics.queue_rule | WP-11 | SimConfig and deterministic simulator run receipt |
| Reward unit | economics.reward_unit | WP-11 / WP-15 | lfc_bridge_v1.payout_unit_evidence; account-day primary |
| Coverage rule | coverage_rule.tier_a_min_share; coverage_rule.cfd_window | WP-09 / WP-14 / WP-02 | coverage_receipt_v1 and f3_coverage_accrual |
| Coverage base rate | coverage_rule.base_rate_receipt_sha256 | WP-02 | coverage/ receipts for event dates 11-17..11-22; counts only |
| Valuation rule and projection | valuation_rule | WP-12 / WP-05 | power_projection_v1; OD-07 token from DECISION_LOG |
| Alpha | arms[].alpha | WP-02 / WP-05 | DECISION_LOG: F3-OD-02-a or F3-OD-02-b |
| PASS rule | pass_rule_id | WP-12 / WP-05 | frozen protocol PASS rule; OD-09 DECISION_LOG row |
| Verdict matrix | verdict_matrix_sha256 | WP-05 / WP-12 | UTF-8 LF matrix in F3_SIM_TRIAL.md, delimited below |
| Economic minimum | inference.economic_min_pusd_per_day | WP-12 / WP-05 | OD-09; protocol rule |
| Looks and rules | looks | WP-02 / WP-03 / WP-12 | WP-03 LookWindow rows plus protocol looks; no copied admission clock |
| Diagnostics list and D-T1 cities | diagnostics | WP-05 / WP-12 | protocol arms; default highest-only T1 selection from design §3.3, frozen explicitly |
| Capture regimes | capture_regimes | WP-08 | capture_regime_receipt_v1 for rewards_sweep, event_driven and Tier B state |
| Admissibility table | admissibility_table_sha256 | WP-05 / WP-02 | PREREG.md bytes between admissibility markers; WP-02 hash helper |
| Claimants and intersections | claimants; claimant_report_sha256 (PROPOSED explicit report pin) | WP-02 | run-time claimant report; freeze_receipt.claimant_report_sha256 |
| Run-branch tip and log | code.run_sha; code.run_log_sha256 | master / WP-02 | codex/f3-run-20261113 tip and append-only run-branch log |
| Power basis | valuation_rule.settlement_mde_basis; valuation_rule.projection_sha256 | WP-12 | power_projection_v1: mde_settlement_lots, bands_assumed, n_b_independent and its counting rule |

All receipt paths above are producer contracts, not assertions that local runtime files already exist.
Before freeze, replace them with exact relative paths and hashes, remove proposed schema fields rejected by WP-02,
and validate every required key on the integrated line. No frozen value may be recovered from embargoed studies.
Keys: all mapped above. Producer: WP-05 checklist, each named WP, master integration bindings.

## 19. Master attestation

Unsigned draft attestation for landing: “no host-side read of trial-date prices, books, trades or outcomes before
this landing”. The master signs only after reconciling the read chain and the separate never-read research folders.
Keys: none; freeze receipt and landing attestation. Producer: master.

## 20. Deviations and clarifications

Empty at freeze. Later clarifications must be dated, outcome-blind and retained under charter §3.4; no re-cut after a read.
Keys: `clarifications`. Producer: master, with WP-05 text.

## Embedded prereg JSON (draft)

Frozen leaves are null; each `_source_<key>` names its producer and source receipt. These fields are draft
annotations and must be dropped before validation/freeze. `input_pack` and `claimant_report_sha256` are explicitly
proposed schema additions pending WP-02. `prereg_md_sha256` belongs only in the freeze receipt.

<!-- f3-prereg-json:start -->
```json
{
  "schema_version": "f3_prereg/1",
  "_source_schema_version": "WP-02 schema registration; phase B validates version",
  "trial_id": "F3-SIM-1",
  "_source_trial_id": "WP-05 protocol §Estimand",
  "charter_trial": "T5",
  "_source_charter_trial": "WP-05 Appendix A; master landing",
  "prereg_md_path": "docs/research/f3-sim-trial-2026-11/PREREG.md",
  "_source_prereg_md_path": "WP-05 this Markdown path",
  "arms": [
    {
      "arm_id": "T5-R",
      "alpha_bearing": true,
      "alpha": null,
      "universe": null,
      "window": null,
      "valuation": null
    }
  ],
  "_source_arms": "WP-05 protocol; WP-02 OD-02 DECISION_LOG token and WP-12 projection",
  "diagnostics": null,
  "_source_diagnostics": "WP-05 protocol arms and design §3.3 default highest-only D-T1 city list; WP-12",
  "code": {
    "repo_sha": null,
    "t1_sha": null,
    "engine_sha": null,
    "gov_sha": null,
    "run_sha": null,
    "run_log_sha256": null,
    "f2_git_sha": null,
    "f2_policy_sha256": null,
    "t046_sha": null,
    "f3_code_digest": null
  },
  "_source_code": "WP-02 freeze_receipt.code; master run-branch log; WP-11 run receipt; F2 freeze; T046 squash",
  "universe": {
    "path": null,
    "sha256": null,
    "u36h_keys": null,
    "u80_keys": null
  },
  "_source_universe": "WP-01 strata.json and weather_universe.json pins",
  "events_sha256": null,
  "_source_events_sha256": "WP-08/WP-14 verified VR-3 event inventory",
  "dates": {
    "first_event_date": null,
    "last_event_date": null,
    "n_dates": null
  },
  "_source_dates": "WP-05 protocol; WP-02 admitted scope",
  "coverage_rule": {
    "tier_a_min_share": null,
    "cfd_window": null,
    "base_rate_receipt_sha256": null
  },
  "_source_coverage_rule": "WP-02 coverage base-rate receipt from WP-09/WP-14 heartbeats",
  "policy": {
    "path": null,
    "sha256": null,
    "f2_frozen_offset_pusd": null,
    "f2_freeze_receipt_sha256": null,
    "sleeve_loss_basis": null
  },
  "_source_policy": "WP-01 candidate policy plus F2 policies/freeze.json at T033 seal",
  "nwp": {
    "schedule_path": null,
    "schedule_sha256": null,
    "before_min": null,
    "after_min": null
  },
  "_source_nwp": "WP-01 config/f3/nwp_release_schedule.json",
  "envelope": {
    "path": null,
    "sha256": null,
    "strata_sha256": null,
    "cell_entry_counts": null,
    "heldout": null,
    "us_validation": null
  },
  "_source_envelope": "WP-07 response_envelope_v1 and envelope_validation_v1",
  "worlds": {
    "A": {
      "k": null,
      "m": null,
      "envelope_quantile": null,
      "bridge_sha256": null
    },
    "B": {
      "formula_id": null,
      "k_fallback": null,
      "m_fallback": null,
      "min_fills": null
    }
  },
  "_source_worlds": "WP-12 formulas; WP-15 lfc_bridge_v1",
  "cost_table": {
    "path": null,
    "sha256": null
  },
  "_source_cost_table": "WP-15 exports/f3_cost_table_v1",
  "b_sample": {
    "dates": null,
    "n_independent_outcomes": null,
    "strata": null,
    "source_shas": null
  },
  "_source_b_sample": "WP-12 independent-event b-sample receipt and power_projection_v1; K-20 ruling",
  "latency": {
    "l_in_s": null,
    "l_post_s": null,
    "l_cancel_s": null,
    "source_sha256": null
  },
  "_source_latency": "WP-15 lfc_bridge_v1.latency_p95_s",
  "economics": {
    "queue_rule": null,
    "route_policy": null,
    "midpoint_rule": null,
    "competition_rule": null,
    "reward_unit": null,
    "fee_expected": null,
    "payout_lag_s": null,
    "redeem_lag_s": null,
    "stale_after_s": null,
    "coverage_definition": null,
    "excluded_cfds_in_capital": null,
    "world_b_rescore_rule": null
  },
  "_source_economics": "WP-11 SimConfig/run receipt; WP-06 adapter/replay contract",
  "valuation_rule": {
    "rule_id": null,
    "settlement_mde_basis": null,
    "projection_sha256": null,
    "primary": null
  },
  "_source_valuation_rule": "WP-12 power_projection_v1 with fixed §5.10 basis; OD-07 token",
  "unresolved_rule": {
    "cutoff_local": null,
    "primary": null,
    "sensitivity": null
  },
  "_source_unresolved_rule": "WP-05 protocol settlement; WP-11 SimConfig",
  "inference": {
    "bootstrap": null,
    "blocks": null,
    "replicates": null,
    "seed": null,
    "economic_min_pusd_per_day": null
  },
  "_source_inference": "WP-12 inference and fixed pre-read seed receipt; OD-09",
  "pass_rule_id": null,
  "_source_pass_rule_id": "WP-12 implementation and WP-05 protocol PASS rule; OD-09",
  "verdict_matrix_sha256": null,
  "_source_verdict_matrix_sha256": "WP-05 delimited protocol matrix bytes; WP-12",
  "looks": null,
  "_source_looks": "WP-05 protocol; WP-03 LookWindow admission rows; WP-12 rules",
  "accuracy_gate": {
    "tolerances": null,
    "minimums": null,
    "population_rule": null,
    "pre_gate_minimums": null
  },
  "_source_accuracy_gate": "WP-15 sim_accuracy_gate_v1, tolerances and K-17 minimums",
  "claimants": null,
  "_source_claimants": "WP-02 runtime_claimants report from canonical reservation and ledger rows; source path/line per claimant",
  "capture_regimes": null,
  "_source_capture_regimes": "WP-08 capture_regime_receipt_v1 hashes",
  "read_scopes": null,
  "_source_read_scopes": "WP-03 named scope rows and DECISION_LOG literal tokens",
  "admissibility_table_sha256": null,
  "_source_admissibility_table_sha256": "WP-02 helper hashes bytes between this file's admissibility markers",
  "clarifications": [],
  "_source_clarifications": "WP-05 empty at freeze; charter §3.4 governs later dated outcome-blind entries",
  "input_pack": {
    "manifest_sha256": null,
    "reader_version": null,
    "tzdata_version": null
  },
  "_source_input_pack": "PROPOSED schema destination; WP-14 trial_input_pack_v1 manifest, requires WP-02 agreement",
  "claimant_report_sha256": null,
  "_source_claimant_report_sha256": "PROPOSED explicit pin; WP-02 report hash also bound by freeze receipt"
}
```
<!-- f3-prereg-json:end -->

f3_prereg_json_sha256: PENDING

## Appendix A. Draft charter §4 row

The master lands this row with the T033 line-7 amendment; this file does not edit the charter.
Draft text below matches design Appendix G.2(2), one line. Fill admission date at landing and reconcile OD-01/02.

| T5 (F3-SIM-1) | Simulated reward-harvesting maker on the 36 non-built-in, METAR-settled highest city-families (arm T5-R: F2's frozen quote and book check, no model, T+1, 24 h net of the NWP blackout, $300 simulated sleeve under F2's caps); no orders, no money | Admitted by F3-OD-01 on <date> (T033 line 7 amended for one simulated claimant); prereg frozen at its landing merge's committer time, sha in the freeze receipt | event dates 2026-11-17..2026-12-24, captured unread until the freeze | L0 11-23 (counts), L1 12-01, L2 12-03 (early warning to the owner), L3 12-10, L4 12-20 (futility only, no α spent); final 12-28 from 18:00 | 0.05 under F3-OD-02-a (T033 cash-diagnostic for December) or 0.0375 under F3-OD-02-b |

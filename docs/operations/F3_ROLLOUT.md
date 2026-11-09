# F3 rollout gates

Status: durable gate definitions. **No live status is recorded here**; the master records gate states in
[item 347](../roadmap/items/item-347-weather-expansion-f3.md) and [STATE_OF_PLAY](STATE_OF_PLAY.md).
Read when planning or checking a gate. The [protocol](F3_SIM_TRIAL.md) owns statistical rules;
the [engine runbook](f3-maker-expansion.md) owns execution. This checklist grants no operational authority.
Dates below are the design's 2026 campaign deadlines, not progress reports. Clock: America/Toronto.
Design section numbers and sibling source IDs retained in the tables are review provenance, not additional
repository instructions. Use the linked protocol for the statistical rules and the runbook for command availability;
`f3 ...` denotes governance command shorthand until WP-02's package entry point lands.

## Phases

| Phase | Dates | Money | Delivers |
|---|---|---|---|
| 0 Capture | 11-09 → verified Mon 11-16 09:00, then continuous to 12-31 | none | books of every rewarded token, discovery, terms, trades, packs, METAR first-seen |
| 1 Shadow and calibration | 11-10 → 11-22 | none | engine on fixtures, then calibration scopes; envelope fits and US validation; accuracy pre-gate; kill test; power; blind plumbing (heartbeat counts only) on 11-17+ |
| 2 Fair trial | freeze Mon 11-23 (hard 11-30) → final look Mon 12-28 → verdict Thu 12-31 | none (simulated $300) | F3-SIM-1, T5-R, blind accrual, looks |
| 3 Live | **not in December**; from about 01-11 only after a PASS and MA-01 | owner-approved sleeve | owner-started tranches on the F2 machinery with a new campaign ID |

## Gates

SLIP moves a date; SCREEN_ONLY carries no alpha; KILL records the kill while capture continues; FALLBACK and NOTIFY follow the stated action. An em dash means the design sets no separate hard deadline.

### Phase 0

| Gate | Criterion | Evidence (schema, path) | Due | Hard | On fail | Decided by |
|---|---|---|---|---|---|---|
| P0-E1 | Owner yes `F3-OD-06` (registrations, all-family capture superseding R35, Chicago lowest, `rewards_sweep`, VR-5 task, retention) and `F3-OD-06-ed` (the `event_driven` flip on F2's built-in bands) | DECISION_LOG F3-OD-06 / F3-OD-06-ed; WP-08 capture-regime receipt | Wed 11-11 18:00 (hard Fri 11-13) | Fri 11-13 | SLIP; each day after 11-16 loses a trial date (MDE +1.3%/date). Without `-ed`: no flip; Tier B off and Tier A on the top-3-bins fallback until the owner answers [A] | Decision authority via DECISION_LOG; master verifies |
| P0-E2 | roll verdict recorded for each landing | scripts/ops/roll_verdict.ps1 receipt for the exact branch tip; master | per landing | — | SLIP to the next window | Master verifies receipt / disposition |
| P0-E3 | host: 24 h disk low ≥ 90 GiB; RAM rule (S6) in config | status.ps1 resource trail and config RAM rule; WP-04 | before registration | — | FALLBACK FB-1 | Master verifies receipt / disposition |
| P0-X1 | Tier A covers ≥ 99% of rewarded YES tokens on ≥ 95% of minutes over the field window (11-14 landing → 11-16 09:00, ≥ 48 h; N8), for every T1/T2/COVERED row and ≥ 95% of all rewarded tokens | coverage_receipt_v1; WP-09/WP-14 heartbeats and verified pack | Mon 11-16 09:00 | — | SLIP; CFDs below 95% excluded outcome-blind | Master verifies receipt / disposition |
| P0-X2 | zero HTTP 429 on any Polymarket caller for 48 h, **F2's own 429 counts included**; the window contains ≥ 1 F2 session; until it passes, no Tier B, no VR-5 backfill and no WS live GETs during F2 session hours (S-F, §4.1) | VR-11 heartbeats, 88a status and LFC-lane HTTP counts export; WP-09/WP-13/WP-15 | Mon 11-16 | — | stop widening; Tier A top-3 fallback | Master verifies receipt / disposition |
| P0-X3 | OB-1 overlap with the research METAR logger on 11-14..11-16, compared by report identity only (station, observation time, sha256 of the text), never values, by the master on the host | OB-1 report-identity overlap receipt; WP-08/master (no observation values) | Mon 11-16 | — | NOTIFY (T5-R does not need OB-1) | Master verifies receipt / disposition |
| P0-X4 | every U80 CFD for D..D+2 discovered ≥ 24 h before its local day | VR-3 discovery receipt in verified pack; WP-08/WP-14 | Mon 11-16 | — | SLIP | Master verifies receipt / disposition |
| P0-X5 | one sealed day builds and verifies as a pack on the WS | trial_input_pack_v1 manifest and verify receipt; WP-14 | Wed 11-18 | — | SLIP | Master verifies receipt / disposition |
| P0-X6 | no regression of existing capture: 10/10 workers; built-in selection unchanged | status.ps1 capture-health evidence and selection ratchet; master | continuous | — | revert config (§4.6) | Master verifies receipt / disposition |
| P0-X7 | VR-5 completeness: ≥ 99% of 88a WS `last_trade_price` trades matched for 2 days. **Population pending master ruling K-16** (WP-13 R1: built-in WS trades on trial dates are in no scope, so WP-13 proposes PILOT10/U80 trades on 11-14..11-16 under `F3-OD-04-b2`) | VR-5 completeness receipt; WP-13, population subject to K-16 | Tue 11-24 (can run from Wed 11-18) | — | no fill model → no trial (R7) | Master verifies receipt / disposition |

### Phase 1

| Gate | Criterion | Evidence (schema, path) | Due | Hard | On fail | Decided by |
|---|---|---|---|---|---|---|
| P1-E1 | OD-04 tokens in DECISION_LOG and the scope rows landed (WP-03) | DECISION_LOG tokens and WP-03 named scope rows | Thu 11-12 | — | calibration only on dev data; cells weaken (R20) | Decision authority via DECISION_LOG; master verifies |
| P1-E1b | `f3 claimants` against the three calibration scopes (b1, b2, c) exits 0, with the claimant list built at run time (G8) | WP-02 f3 claimants --scopes calibration report; before first read | Thu 11-12, **before the first calibration read** | before first calibration read | narrow the intersecting scope (for example b1 = U80 minus the built-in lowest families) and rerun before any read | Master verifies receipt / disposition |
| P1-E2 | T1sim `728d60e3` pinned in the engine branch | Engine Git ancestry and prereg code.t1_sha; WP-11 | Tue 11-10 | — | — | Master verifies receipt / disposition |
| P1-E3 | F0 session-1 records staged by the LFC lane | LFC-lane completeness manifest; WP-15 | Wed 11-11 | — | NOTIFY | Master verifies receipt / disposition |
| P1-X1 | §5.8 tolerances on F0 + learning sessions (relaxed minimums, K-17) | sim_accuracy_gate_v1 pre-gate under receipts/ or exports/; WP-15 | **Thu 11-19 18:00** (G1) | Mon 11-30 | fix and rerun; freeze slips (hard 11-30); still failing → SCREEN_ONLY | Master verifies receipt / disposition |
| P1-X2 | US validation passes (§5.6); per-cell entry counts and held-out results recorded | response_envelope_v1.us_validation and per-cell records under envelope/; WP-07 | **Thu 11-19 18:00** (G1) | — | **KILL** | Master verifies receipt / disposition |
| P1-X3 | K-A (Wed 11-18) and K-B (**Thu 11-19 18:00**) (§5.7) | kill_test_v1 under killtest/; WP-12 (K-A bridge from WP-15) | K-A: Wed 11-18; K-B: Thu 11-19 18:00 | before freeze | **KILL** | Master verifies receipt / disposition |
| P1-X4 | two runs of three pack days give identical digests | Two f3_accrual_receipt engine digests / simulator receipts; WP-11/WP-02 | Thu 11-19 | — | SLIP | Master verifies receipt / disposition |
| P1-X5 | outcome-free projection on the pre-declared basis (§5.10: `mde_settlement_lots`, `bands_assumed` 5.5, the n_b counting rule): MDE of the primary valuation (by the OD-07 rule) at T5-R's α ≤ $25/day | power_projection_v1 under power/; WP-12 | Fri 11-20 | — | SCREEN_ONLY | Master verifies receipt / disposition |
| P1-X6 | F0/F2 paid `REWARD` rows per condition: per-condition floor visible or not | lfc_bridge_v1.payout_unit_evidence under exports/; WP-15 | Fri 11-20 | — | account-day stays primary | Master verifies receipt / disposition |
| P1-X7 | heartbeat-only coverage on 11-17..11-22 recorded | f3_coverage_accrual base-rate receipt under coverage/; WP-02 | Mon 11-23 | — | — | Master verifies receipt / disposition |
| P1-X8 | `f3 claimants` exit 0 for the trial scope against the run-time claimant list (§5.1: the named seven, row 72 R-ODC, the L3 T+1 emit, every reservation and open forward ledger row) | WP-02 f3 claimants --scopes trial report and its hash | Sat 11-21 | — | narrow the universe, rerun | Master verifies receipt / disposition |
| P1-X9 | the read log shows zero non-coverage reads of event dates ≥ 11-17 | f3_freeze_receipt.trial_date_reads == 0; WP-02 read_log.jsonl and master attestation | at freeze | — | the arm becomes a screen | Master verifies receipt / disposition |

### Phase 2

| Gate | Criterion | Evidence (schema, path) | Due | Hard | On fail | Decided by |
|---|---|---|---|---|---|---|
| P2-E1 | DECISION_LOG rows with tokens `F3-OD-01`, `F3-OD-02-a` or `-b`, `F3-OD-03-a`, `F3-OD-03-b`, plus the T033 line-7 amendment and the charter §4 T5 row, landed on master | DECISION_LOG tokens, T033 line-7 amendment, EDGE_TRIAL_CHARTER §4 row; master | Sun 11-15 18:00 | Practical latest Mon 11-16 11:30; formal 17:54 only under the master ruling described below | SCREEN_ONLY | Decision authority via DECISION_LOG; master verifies |
| P2-E2 | tokens `F3-OD-07-rule` or `-settlement`, `F3-OD-08`, `F3-OD-09`, `F3-OD-13` | DECISION_LOG literal decision tokens; master | Fri 11-20 18:00 | Mon 11-23 09:00 | defaults apply (§7) | Decision authority via DECISION_LOG; master verifies |
| P2-E3 | P1-X1..X9 passed or their pre-declared outcomes applied | P1-X1..X9 receipts and pre-declared dispositions; master | Sun 11-22 | Mon 11-30 | per gate | Master verifies receipt / disposition |
| P2-E4 | `PREREG.md` with the JSON embedded (§5.11) landed via the light path before 12:00; `f3 freeze` receipt; charter §4 row already landed (P2-E1). **Dry run by Fri 11-20:** `docs_light_path.ps1 -CheckOnly` on a dummy PREREG docs branch and `f3 freeze --check-only` (G3) | PREREG.md landing commit + f3_freeze_receipt; both CheckOnly receipts; WP-02/master | Mon 11-23 11:30 | Mon 11-30 11:30 | SLIP | Master verifies receipt / disposition |
| P2-E5 | WS nightly task registered (OD-10) | Registration/readback receipt; WP-14/master under separate approval | Mon 11-23 | — | master runs it by hand | Master verifies receipt / disposition |

### Phase 3

| Gate | Criterion | Evidence (schema, path) | Due | Hard | On fail | Decided by |
|---|---|---|---|---|---|---|
| P3-E1 | T5-R PASS in both worlds with the binding accuracy gate PASS | f3_verdict + final f3_look_report + sim_accuracy_gate_v1; WP-12/WP-15 | January, after prerequisites | — | no live expansion | Master verifies receipt / disposition |
| P3-E2 | owner money yes MA-01 (sleeve, caps, tranche list, windows) | MA-01 DECISION_LOG row; separate future authority | January, after prerequisites | — | no live expansion | Decision authority via DECISION_LOG; master verifies |
| P3-E3 | F2's final look done; campaign exclusivity ends 12-31; new campaign ID | F2 final-look receipt and new campaign identity; separate future authority | January, after prerequisites | — | no live expansion | Master verifies receipt / disposition |
| P3-E4 | per tranche: universe v2 at a pinned sha, ≥ 7 days of recorder evidence at ≥ 95% coverage, adapter verified | Pinned universe, coverage and adapter receipts; separate future authority | January, after prerequisites | — | no live expansion | Master verifies receipt / disposition |
| P3-E5 | reviewed pinned release, Astra review, master pregate, the owner's one-time registration and `enabled` flip | Pinned release, reviews and pregate/registration receipts; separate future authority | January, after prerequisites | — | no live expansion | Decision authority via DECISION_LOG; master verifies |

P2-E1's formal 17:54 alternative counts only if the master explicitly rules that a pushed, dated docs
branch counts before the seal; this checklist assumes the practical 11:30 deadline. P2-E4's two dry runs
are due Fri 11-20: `docs_light_path.ps1 -CheckOnly` on a dummy docs branch and `f3 freeze --check-only`.
P0-X7's test population must be ruled under K-16 before reading; built-in trial-date trades are not silently admitted.

## Decision inventory

These are questions, recommendations and defaults, **not answers**. Literal tokens activate only in a DECISION_LOG
decision cell starting `OWNER DECISION` or `OWNER DECISIONS`, with the verbatim approval and the label `F3 tokens:`.
A token quoted in this file, a disclosure or a master recommendation activates nothing. Scope choices use suffixed YES.
The informational/deferred rows below carry no invented activation token.

| ID | Question | Recommendation | Deadline (Toronto) | Default if silent | Sources |
|---|---|---|---|---|---|
| **OD-01** | `F3-OD-01: YES`: admit F3-SIM-1 (charter trial T5, arm T5-R) as the one simulated December profit claimant by amending T033 line 7 (no F2 rule or byte changes). The exact amendment and charter §4 row text are in Appendix G.2 and go to the owner in P2 | **YES** | **Sun 11-15 18:00** (practical latest Mon 11-16 11:30; formal hard 17:54, see P2-E1) | F3-SIM runs as a screen; the expansion cannot claim edge in December | D2 OD-1, D3 OD-1, D5 OD-1 |
| **OD-02** | α: `F3-OD-02-a: YES` = T033 cash-diagnostic for December, T5-R 0.05; or `F3-OD-02-b: YES` = T033 0.0125, T5-R 0.0375 | **(a)**: T033 cannot PASS by its code, so the family error stays ≤ 0.05; MDE −5% vs (b) | **Sun 11-15 18:00** | (b) | D5 OD-1/IR-9, red S14, master E |
| **OD-03-a** | `F3-OD-03-a: YES`: the trial read scope for U80 event dates 11-17..12-24 (books, trades, terms, resolutions). **Read only by the frozen prereg code**: (1) heartbeat coverage counts nightly; (2) sealed accrual of these dates by the frozen code, either inside each look window or nightly after the freeze, with outputs sealed and every read logged (the master picks one by Fri 11-20, K-2); (3) outputs opened only at L0 (counts) 11-23, L1 12-01, L2 12-03, L3 12-10, L4 12-20 and the final look 12-28 from 18:00 | **YES** | **Sun 11-15 18:00** | no named test; screen only | D2 OD-2, D5 OD-2a, D3 OD-6, critic G10 |
| **OD-03-b** | `F3-OD-03-b: YES`: the books, trades and venue resolutions of the bands F0/F2 quoted on 11-17..12-22, read only by frozen code **inside the LFC lane** at the final look, after T033's own look opens Mon 12-28 18:00 (binding accuracy gate, world B; only aggregates leave the lane) | **YES** | **Sun 11-15 18:00** | the binding gate cannot run → no PASS is possible | D5 OD-2a, D3 OD-6, critic N-D |
| **OD-04-b1** | `F3-OD-04-b1: YES`: open U80 event dates **11-09..11-16** (books, trades, terms, resolutions) for describe, kill and calibration, never edge. Includes the 44 lowest families, the built-in lowest among them; P1-E1b checks the claimants first and narrows b1 if a reserved test claims them | **YES** | **Wed 11-11 18:00** | dev data only; most cells fail → reward 0 outside US; likely KILL at P1-X2 | D5 OD-2b, red M5 |
| **OD-04-b2** | `F3-OD-04-b2: YES`: open the ten 88a pilot highest rows for event dates **10-23..11-16** (books, trades, terms, resolutions; calibration and b sample, never edge). **This releases charter T1's "captured unread 10-15..~11-15" claim on those ten rows**; T033 superseded the charter T1–T4 family for December | **YES** | **Wed 11-11 18:00** | n_b loses ≈ 125 outcomes; P0-X7 cannot use pilot rows | D5 OD-2b, D3 OD-6 |
| **OD-04-c** | `F3-OD-04-c: YES`: open the public books and trades of the bands F0/F2 quote on **11-09..11-16**, read only **inside the LFC lane** (envelope validation, K-A/K-B inputs, pre-gate); only aggregates leave the lane | **YES** | **Wed 11-11 18:00** | no US validation → P1-X2 KILL | D5 OD-2c, D3 OD-6 |
| **OD-05** | Phase-2a exposure (§2A, including the T046 fixtures and the loggers): `F3-OD-05-i: YES` acknowledge the disclosure; `F3-OD-05-ii: YES` confirm the quarantine (§2A.3); `F3-OD-05-iii: NO` = the phase-2a sample (10-18..11-08) of the 36 non-built-in highest rows does **not** calibrate b (M2.5); and one of `F3-OD-05-iv-a: YES` = open the study retroactively as a named describe/kill-only read for the F3 design only, quarantine kept, or `F3-OD-05-iv-b: YES` = use only the embargo-safe variant and drop the phase-2a numbers from every decision (the January shortlist is then rebuilt from calibration-scope books). Neither iv token opens any code read | (i) yes; (ii) yes; (iii) **NO**; (iv) **a** | **Wed 11-11 18:00** | quarantine stands; b from OD-04 and dev; **iv-b applies until ruled** | master A, red M7/M2.5, D5 OD-2d, ranking OD 1, critic G5 |
| **OD-06** | `F3-OD-06: YES`: register `WeatherEvidenceHost`; passive outcome-blind capture of every temperature city-family including built-in lowest through VR-11 (a row that supersedes R35 by name); Chicago lowest; 88a `rewards_sweep: on`; the VR-5 nightly task `WeatherEvidenceBatch`; keep Tier B and VR-5 canonical with cold offload after 30 days | **YES** | **Wed 11-11 18:00** (hard Fri 11-13) | capture waits; trial dates lost after 11-16; lowest stays uncaptured | D1 OD-1/2/3/9, D4 OD5, D5 OD-7, red S4 |
| **OD-06-ed** | `F3-OD-06-ed: YES`: switch 88a's built-in reward reads to `built_in_reward_cadence: event_driven`. **This changes how terms are captured for F2's own 12 bands in the middle of F2's run** (red team S12); it lands Fri 11-13 on a night with no session start, writes a `capture_regime_receipt_v1`, and passes a 24 h check that no reward-term change on a built-in band is captured more than one cycle late; the receipt sha goes into the prereg | **YES** (without it the evidence-host callers exceed the 2 req/s bucket, Appendix A S12) | **Wed 11-11 18:00** (hard Fri 11-13) | no flip; Tier B off and Tier A on the top-3-bins fallback until answered [A] | red S12, D1 §8.4 |
| **OD-07** | Valuation (charter §2.6/§3.3 amendment): `F3-OD-07-rule: YES` = "MTM-surrogate primary iff projected MDE_MTM ≤ 0.7 × MDE_settlement on the pre-declared basis (§5.10), else settlement; settlement point estimate > 0 always; label 'MTM-surrogate PASS'"; or `F3-OD-07-settlement: YES` = settlement only | **Adopt the rule.** At the expected b sample (n_b ≈ 260–310 < ≈ 430) the rule is expected to select settlement, so P(PASS) ≈ 0.02 [A] either way unless the b sample turns out larger | **Fri 11-20 18:00** (hard Mon 11-23 09:00) | settlement only | D3 OD-2, D5 OD-3, red M1/M2, critic G6 |
| **OD-08** | `F3-OD-08: YES`: T5-R quotes T+1 24 h in simulation, net of the NWP blackout (×2.8); F2's 6 h window is diagnostic D-6H; the 14:00–20:00Z subtotal is reported | **YES** | Fri 11-20 18:00 | 24 h | D5 OD-4, ranking OD 3, red S3 |
| **OD-09** | `F3-OD-09: YES`: verdict matrix (§5.13), economic minimum $1.50/day, L2 early-warning numbers shown to the owner | **YES** | Fri 11-20 18:00 | as written here | D2 OD-6/7, D5 OD-5 |
| **OD-10** | `F3-OD-10: YES`: register a WS scheduled task for the nightly pack pull, verify and blind accrual (01:30–08:15, never in session hours) | **YES** | Fri 11-20 18:00 | master runs it by hand nightly (fragile) | D5 OD-8 |
| **OD-11** | `F3-OD-11: YES` = confirm no live expansion arm in December: no expansion order in the F2 campaign (D2's lowest probe withdrawn); no second account. Option shown: a separate-account validation arm (≈ 6 Cd that competes with the critical path; the venue's terms on a second account unverified; money outside T033's $300; its sessions could enter the binding gate at the final look) | **YES (no live arm)** | Sun 11-15 18:00 | no live arm | D5 OD-6, D3 OD-5, D2 OD-4 (withdrawn), red M4/S13, master D |
| **OD-12** | Keep F2 exactly as frozen (no city, family, window, offset or α change); no a1–a4 output informs F2's adaptation | **YES** (confirms T033) | Mon 11-09 (information) | already binding | D3 OD-7, red M7.3 |
| **OD-13** | `F3-OD-13: YES`: F3-SIM capital: $300 simulated sleeve with F2's caps; sleeve-loss basis read from F2's freeze receipt at the T033 seal | **YES** | Fri 11-20 18:00 | yes | D3 OD-3, red N5 |
| OD-14 | `F3-OD-14: YES`: ask the venue's support (no money, no account change): $1 minimum per market or per account; payment when the only in-band two-sided liquidity is the maker's own; reward switch-off after the local day starts; missing-AWC fallback timing | YES (optional) | Thu 11-12 | not asked; F0/F2 rows decide the unit | D5 OA-3, D4 OD6, ranking OD 2 |
| OD-15 | Free sign-ups: KNMI, Météo-France, AEMET, MetService beta | yes, when convenient (Later; no December role) | none | none | D1 OD-4, D5 OA-4, ranking OD 4 |
| OD-16 | MGM permission or IMGW contract | **NO** | none | no | D1 OD-5 |
| OD-17 | December forecast inputs: none. Lane D, IEM backfill, Open-Meteo bulk pulls, the NWP extractor and the `eccodes` wheel move to Later; no Open-Meteo Professional; the 10-14 Open-Meteo risk acceptance is cited, not re-asked | confirm | Wed 11-11 (information) | as stated | D1 OD-6/7/8, D2 OD-3/5, D5 OD-9, red S1/N6 |
| OD-18 | `F3-OD-18: YES`: TLS and dependencies: certifi code fix inside the evidence host (WP-04) yes; Windows store fix no; certifi as a direct pin in `requirements.txt` yes; the ten-module migration (including money-adjacent services) after 12-31 | as stated | Wed 11-11 18:00 | evidence-host fix only; no pin | D4 OD2/OD3, red S11 |
| OD-19 | Denver: `MarketSpec` and `locations.json` stay KBKF until the KDEN model passes; F3 readers use KDEN | YES (confirms DL 10-23) | none | DL 10-23 stands | D4 OD4 |
| OD-20 | Defer to Later: `WeatherUniverseEventRefresh` task, untracked `data/universe/events/`, eight-digit label alignment (after B's read) | defer | none | deferred | D4 OD1/OD8/OD9 |
| OD-21 | A cloud VM before 12-31 | **NO** | none | no | D1 OD-10, D4 OD7, D5 MA-7 |
| OD-22 | Project consequence at the verdict: read the pre-declared matrix as written | **YES** | Thu 12-31 | the owner's 11-05 rule applies | D5 OD-10 |

## Landing plan

| Night (00:30–09:00 Toronto) | Landing (master) |
|---|---|
| **Tue 11-10** | T046 **squash merge** of the round-7 tip after its review (ROLL-FREE); WP-10's WU-mode test follows as a post-landing confirmation |
| Thu 11-12 | WP-03 scopes in the window its verdict names |
| Fri 11-13 | 88a config flips (WP-08 config part; owner yes `F3-OD-06` and `F3-OD-06-ed`); WP-10 refresh hardening; then the master creates the run branch `codex/f3-run-20261113` (G2, §10.2) |
| **Sat 11-14** | S4 + WP-04 + WP-08 + WP-09 (RS window if the verdict says so: S4 touches `config_inventory.py`); master registers `WeatherEvidenceHost` (OD-06) |
| Sun 11-15 | slack slot for Sat |
| Mon 11-16, 00:30–12:00 (docs light path) | the DECISION_LOG rows for OD-01/02/03/11, the T033 line-7 amendment row and the charter §4 T5 row, together with the already-due T033 line-5 charter amendment (G9) |
| **Tue 11-17** | **P1 landing = WP-13 + WP-14a host side stacked** (VR-5 task, pack build, `export-day`, `m88a backfill`; G1). Then the master registers `WeatherEvidenceBatch` (OD-06), runs the VR-5 backfill 11-09..11-16, `m88a backfill --days 2026-10-23:2026-11-16` and `export-day` for UTC 11-14..11-16 under `F3-OD-04-b1/-b2/-c`, all inside 00:30–09:00 (fallback Wed 11-18 00:30–01:25) |
| Wed 11-18 01:30–03:30 | first WS pull of the `F3-CAL` pack, by hand (the WS task waits for OD-10); P0-X5 |
| Fri 11-20, 00:30–12:00 | `docs_light_path.ps1 -CheckOnly` dry run on a dummy PREREG docs branch (G3; changes nothing) |
| Mon 11-23, before 12:00 | `PREREG.md` (JSON embedded) on the docs light path = the freeze (§5.11) |
| Tue 12-01 01:00–04:00 | host controlled Windows update; no landing; verify capture recovery; re-run a missed pack night; L1 runs after 15:30 |

Every integration first needs the repository roll verdict for its exact tip and the owning guarded merge
procedure. The landing plan describes master actions; it does not authorize this package to perform them.

## Critical path and float

| # | Milestone | Planned | Hard | Float |
|---|---|---|---|---|
| M1 | P1 packet answered (capture, scopes, exposure) | Wed 11-11 | Fri 11-13 | 2 d |
| M2 | T046 landed (squash merge of the round-7 tip) | **Tue 11-10** | prereg pins the landed squash sha | n/a |
| M3 | P0 landed and registered | **Sat 11-14** | Sun 11-15 | 1 d, then dates slide |
| M4 | P0 verified; both research loggers stopped | Mon 11-16 09:00 | — | dates slide |
| M5 | **OD-01/02/03 recorded and landed with the T033 line-7 amendment and the charter §4 row** | Sun 11-15 18:00 | **Mon 11-16 11:30** (light path closes 12:00; seal 17:55) | **0 after Mon 11:30** |
| M6 | F2 learning rewards mature | Tue 11-17 | — | external |
| M6b | P1 landing (WP-13 + WP-14a host side); calibration exports | Tue 11-17 | Wed 11-18 01:25 | 0 d for an 11-19 read |
| M7 | K-A (Wed 11-18); K-B, envelope, pre-gate (Thu 11-19 18:00) | Wed 11-18 / Thu 11-19 | Fri 11-27 | 8 d |
| M8 | engine on real packs; determinism | Thu 11-19 | Fri 11-27 | 8 d |
| M9 | OD-07/08/09/13 recorded | Fri 11-20 | Mon 11-23 09:00 | 3 d |
| M10 | **T5-R frozen** | **Mon 11-23** | **Mon 11-30** | **≈ 5 d** (S-A) |
| M11 | first accrual night | Tue 11-24 | Tue 12-01 | ≈ 5 d |
| M12 | L1 / **L2 to owner** / L3 / L4 | 12-01 / **12-03** / 12-10 / 12-20 | fixed | 0 d |
| M12b | **timed dress rehearsal of the final look** on `F3-CAL` packs and pre-gate sessions (wall time reported; > 10 h → chunk before 12-28) | Sun 12-20 (outside F2 hours) | Tue 12-22 | 2 d |
| M13 | last F2 session; last T5-R event date | Tue 12-22; Thu 12-24 | fixed | 0 d |
| M14 | resolutions captured | Sun 12-27 12:00 | Mon 12-28 09:00 | < 1 d |
| M14b | binding gate and world B (they read F2's confirmation records inside the final window) | **from Mon 12-28 18:00** | Tue 12-29 | < 1 d |
| M15 | **final look** (read from 18:00, after T033's look opens) | **Mon 12-28** | 12-28 (charter §3.8) | **0 d** |
| M16 | verdict package accepted | Wed 12-30 | Thu 12-31 | 1 d |
| M17 | owner reads; project consequence | Thu 12-31 | Thu 12-31 | 0 d |

The critical chain is WP-01 → WP-06 → WP-11 → WP-15 → integration/power in WP-12.
WP-11 may start on WP-06's early delivery. Real calibration packs arrive Wed 11-18 01:30;
K-B, envelope and pre-gate read Thu 11-19 18:00. Review and landing leave about five days to hard freeze Mon 11-30.
The final look remains Mon 12-28 from 18:00. Rehearse the final load on F3-CAL by Sun 12-20;
wall time over 10 hours requires chunking or a reviewed K-2 admission change before the final look.

## Fallbacks

FB-1: if VR-11 has not landed by Sun 11-15 09:00, the master may use the reviewed, bounded 88a fallback
on the T1+T2 rows under a fresh roll verdict. It never extends the unsealed research logger.
Only dates with at least 95% coverage can enter. If lanes are short, drop docs polish first,
then D-QUEUE/D-UNRES; never remove the envelope or accuracy gate.

## Monday counts-only procedure

The master combines `f3 status --trial F3-SIM-1` with `status.ps1` EVIDENCE lines by hand.
Record days covered/sealed, manifest identity, read-log counts by scope/caller, next look, gate receipt references
and upcoming decisions in the numbered item and STATE_OF_PLAY. Never open sealed outputs for this report.
There is no JSON gate checker or weekly-status generator in this phase.

## Update this file when

Change this file when a gate definition, deadline, disposition or decision token changes by the governing process.
Record live gate states in the canonical state owners, not this file.

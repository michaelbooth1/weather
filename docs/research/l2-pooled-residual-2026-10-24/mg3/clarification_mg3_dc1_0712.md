# MG3-DC-1 clarification 0712-1: the 07-12 arm MG-3 binds (DRAFT for master's review)

- **Status: In force: master accepted 2026-10-27.** Lane L2, 2026-10-27. It amends MG3-DC-1
  `a7c697618cd26cfac1184c148a39ee1d20a1ea612e048bd350363ba34022a031` (`rule_mg3_paired_dc.md`) §2.1-2.2 only.
- **Written without new scores.** It quotes only results already filed in the dev-window ledger (rows 47 and 49)
  and relayed by master. No score, label, price or market row was read for it.

## 1. The ruling

Master ruled on 2026-10-27, relayed by the coordinator: **the MG-3 07-12 binding names the RF-1 blend weights
`891be5640cef9fd3924b98f89f1068108acdf404fbd52a4721cb5d8d9ae8ded5` with the L6 partner
`800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db` (SM-L6, season-matched L6).**

MG-3's 07-12 arm is therefore the blend of SM-L6 (`800072c7…`) with the frozen P3d_H 07-12 state (RN-1), weighted
by RF-1 (`891be564…`). The MG-1 fallback and rule-4 floor are unchanged. The frozen Aug-Sep weights
`c7b8ebc08d31ca30e5289d453ec2260bcc6659b32b379410f58b0d2b9b03530a` with the Aug-Sep L6 stack are not bound.

## 2. Reasons (master's)

1. **It is the configuration row 49 tested in season, as its primary.** Row 49 is L3, CS-1 row-49 rule, ledger at
   L3 commit `e4d224c72b56cd107d5b76d42fd8ed9732c7cd01`; result `row49.json`
   `44e94e999daecd0f67956aebf07d064dade0c255d2181d3b1fdc1c0886188642`. Its primary Brier differences:
   - vs MG-1: −0.0189 [−0.0270, −0.0107]
   - vs SM-L6: −0.0139 [−0.0205, −0.0075]
2. **It matches MG-2's own 07-12 arm** (`800072c7…`). The MG-3 − MG-2 pair at 07-12 therefore differs only in the
   blend.
3. **`c7b8ebc0…` with the Aug-Sep L6 was never row 49's primary.** No in-season evidence names it.

## 3. Evidence cited

| Item | Identity |
| --- | --- |
| Row 47: CS-1 (1c) result | `part1c.json` `8d87027a3d64b8b797ead731d29799d21db867bd87e0dfef01b01c32db4e1f40` |
| Row 49: row-49 sm-blend result | `row49.json` `44e94e999daecd0f67956aebf07d064dade0c255d2181d3b1fdc1c0886188642` |
| L3 dev-window ledger commit | `e4d224c72b56cd107d5b76d42fd8ed9732c7cd01` |
| CS-1 clarification 2026-10-27 (rows 47 and 49) | `31512de0708d3679aa9d7be5c02a7f2816d04caea7affeccfc194cac3cd24cd2` |
| Paired key set, Oct-Dec | `3a12f74a2544dae35fec6ed03d76a0f4969e9ff5d6de3da9bebc0ec9821f825a` |
| RF-1 weights | `891be5640cef9fd3924b98f89f1068108acdf404fbd52a4721cb5d8d9ae8ded5` (`refit_note_rf1.md`) |
| SM-L6 final state (L6 partner) | `800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db` |

## 4. Disclosures

- **RF-1 fit window.** RF-1 was fitted once, by the unchanged weight rule, on dev dates 2026-08-01..09-29 with
  SM-L6's dev vectors (`refit_note_rf1.md`). Its weights are fitted on Aug-Sep dates for a partner built for
  Oct-Dec. This is MG3-DC-1 §2.2's stated limitation, now applying to the bound branch.
- **December is unresolved.** Row 49's December reads do not exclude 0:
  - (a): −0.0149 [−0.0319, +0.0024]
  - (b): −0.0014 [−0.0168, +0.0122]
  The ruling binds the configuration for the whole MG-3 window. It does not claim a December gain.
- **Scope of the evidence.** Row 49 covers 2024-25 history: N = 9,830 rows in 150 date clusters. It is not
  2021-23 and not 2026.

## 5. What the binding builder must do

- `mg3_release_binding` writes both shas:
  - the weight table `891be564…`;
  - the 07-12 L6 partner `800072c7…`.
- Each is written only from a verified load: the file is loaded and checked against the pinned sha, then its sha
  is recorded from the bytes the load verified. This is the pattern of the SM-H state (`sm_h_load_state`).
- Any mismatch refuses: a different file, a change between load and record, or a missing partner sha.
- `mg3_verify_release` recomputes both and refuses on any difference.
- Code and tests land in their own commit after this clarification is accepted. Nothing binds before then.

## 6. What does not change

- MG3-DC-1's other hours (00-06, 13-15 SM-H except SF, SF 13-16, 16, 17-23).
- Its paired test against MG-2 on B's dates, its decision rule, and its timing.
- MG-2, Rule B-1, MG-1, PT-1 and L8's branch.
- §2.2a, the 07-12 drop rule.

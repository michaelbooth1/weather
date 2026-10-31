# Claim check for 2026-09-30..10-14 (kill-only and atlas read)

**Dated research evidence, 2026-10-30, workstation lane L8.** This is the written check that
[MODEL_IMPROVEMENT_METHOD](../../operations/MODEL_IMPROVEMENT_METHOD.md) §5 rule 10 and DECISION_LOG 2026-10-30
decision (3) require before the one-time read. Master decides the read; this file does not authorise one.

**Update 2026-10-31:** C1/C2 maker-economics reads closed per DL 2026-10-30; release used for row 80, the atlas and weather kill-only reads only.

**How it was made.** Docs and code reads only, at canon commit `e759a55d10e31dd48559ef99b9d2959c41271fd3`
(`claude/docs-owner-20261030`). Where a claiming text lives only on its own branch, the commit is named. No data was
read: no label, price, snapshot, panel, 88a or settlement file. No data directory was listed.

**Citations.** `file:line` refers to `e759a55d1` unless another commit is named. DL = `docs/operations/DECISION_LOG.md`,
SoP = `docs/operations/STATE_OF_PLAY.md`, RCW = `docs/operations/reserved-confirmation-window.md`.

**Data kinds:**
- **labels:** settlement band, WU or venue daily maximum, settlement ledger rows.
- **prices:** 88a maker-evidence books, prints and mids, CLOB or other order-book prices.
- **snapshots:** captured T+0 snapshot rows (served vector plus the market vector at capture) and harness layout rows
  built from them.

**Markets:** the 12 built-ins: toronto, nyc, atlanta, miami, austin, chicago, dallas, houston, denver, los-angeles,
san-francisco, seattle. "US11" means all of them except Toronto.

## 1. Verdict

**Every cell (15 dates × 12 markets × 3 kinds) is BLOCKED today.** One unresolved claim covers the whole window: maker
replay v2 (C1). Its panel is held unread for a successor registration by an owner decision, and both the code and
the data-layer contract enforce it.

The plan's own Q3 condition is "maker replay v2 resolved first". Canon contains no record that v2 is resolved. Its
lapse date is 2026-10-30 (DL:200), but no DL row records the lapse. No owner decision releases the panel's
"may be reused" status. `EMBARGO_WINDOWS` has not been edited.

Section 4 shows which cells would become FREE as each claim is resolved, so master can see the order of work.

## 2. Claims found

| ID | Claim | Dates, markets and kinds claimed | Status | Citations |
| --- | --- | --- | --- | --- |
| C1 | **Maker replay v2** (successor registration, DRAFT, unsigned) | Quote panel UTC 09-30..10-13 (88a = prices); settlement-only UTC 10-14 and 10-15 (labels of local targets <= 10-14); exporter inputs include plugin fair value (served vs bulletin), so snapshots are ambiguous. All 12 markets. | **Unresolved.** Owner 10-03: "the panel is UNREAD and may be reused by a new prospective registration signed before any export or read of it". The lapse moved to 2026-10-30, but no lapse or release row exists. | DL:58, DL:103, DL:179, DL:200; draft on `codex/maker-replay-v2-build-20261003` @ `1fd0c295f` §2 lines 46-56, §13 lines 562-564; `src/maker_core/shadow/admission.py:29-31` (FULL); `docs/operations/DATA_LAYER_V2_CONTRACT.md:115-136` (the platform embargo for every evidence family); `docs/operations/maker-shadow-runner.md:384-398` (lifting is a reviewed code change); `docs/operations/passive-maker-evidence-capture.md:442-445`; `docs/roadmap/items/item-330-maker-economics-refocus-master-plan.md:23` ("never opened"); `src/weather/reporting/market/cockpit_snapshot.py:36-44`; SoP:64 (88a hold 09-27..10-15) |
| C2 | **89a fill-toxicity panel B** (same-day) | Event dates 09-25..10-08 → 09-30..10-08 here; 88a prices and labels; all 12 markets (prereg line 55). | **Held "until after the v2 look"** (DL:153). If v2 lapses there is no v2 look, so the hold's end condition needs an owner ruling. | DL:35, DL:153; `docs/research/fill-toxicity-desk-study-preregistration-2026-09-23.md:55` |
| C3 | **T+1 fair-value read** (frozen prereg 2026-09-25, postponed) | Target dates 09-25..10-08, scored "only against captured 88a T+1/T+2 two-sided mids" and settlements → prices captured 09-30..10-07 and labels 09-30..10-08; markets not narrowed, so all 12 are taken as claimed. | **Postponed, not withdrawn.** | DL:100, DL:103 item (1); prereg `docs/research/t1-fair-value-preregistration-2026-09-25.md` @ `4b1ef8a07` lines 50-53; v2 draft @ `1fd0c295f` lines 66-67 |
| C4 | **RISE-T3R3 replication** (DEV_WINDOW_LEDGER row 80, frozen) | Path 1, under owner Q3 = yes: the 14 target dates 10-01..10-14, US11, 13-16 local. Reads a harness v3 layout (snapshots) and labels. One look. | **Frozen; claims these dates first.** Under rule 10 a PASS here is a screen, never an edge claim. | `docs/research/forecast-tracking-2026-10-30/rule_rise_t3r3_replication.md:48-56`, `:72-73`, `:79`, `:98-99`; `docs/operations/DEV_WINDOW_LEDGER.md:119`; SoP:70-71 |
| C5 | **Maker-P&L desk study** (10-01 prereg) and the **88a desk-study panel hold** | Events 10-17..10-30, all 12 markets; 88a retained UTC 10-15..10-30. It claims no target date in this window. It does hold UTC 10-15, which carries the local-evening hours of target 10-14 for US markets. Q16: the recorder-only pilot bands are outside its 12-market stratum (no effect here). | Running (descriptive only, DL:189). | prereg `docs/research/maker-pnl-adverse-selection-preregistration-2026-10-01.md` @ `67e44273b` lines 96-99 (pilot never reads 09-30+), 109-116 (panel); DL:90, DL:204; `src/maker_core/shadow/admission.py:32-34` (OUTCOME 10-15..11-13); SoP:64 |
| C6 | **Maker shadow scoring refusal**, UTC 09-30..11-13 | Is exactly C1 (FULL, 09-30..10-15) plus C5 (OUTCOME, 10-15..11-13). Code-enforced for every evidence family. | In force; end stays 11-13. | DL:189; SoP:61; `docs/operations/MAKER_PILOT_PLAN_2026-10.md:42`; code as in C1 and C5 |
| C7 | **Austin, target 2026-10-03** | Settlement band seen 2026-10-05 (exposure). Excluded from v2, and a named plan Q3 condition. | **Permanently excluded** from this read. | DL:117; v2 draft @ `1fd0c295f` lines 50-54, 69-70; `docs/research/iterate-faster-2026-10-30/plan.md:76` |
| C8 | **PT-1** (DRAFT, unbound) and the plan's condition "MG-2 excluded until PT-1 binds" | PT-1's own dates are 12-12..01-25 (no date claim here). w_h, the feasibility gate and G are fitted or checked on dev dates <= 09-29. Scoring MG-2 against the market on these dates before binding would inform an unbound design. | **Scope restriction on every cell** (§3). The plan cites DL "line 209" for it, but DL:209 is the maker-review move, so the citation does not support the condition. It is kept as binding because the owner adopted Q3 "as recommended" (DL:291). | RCW:32; `docs/operations/COOL_SEASON_PAPER_TEST_PREREG.md:6-10`, `:74-76`, `:123-125`, `:167-177`; DL:276-277; plan.md:76 |
| C9 | **MG-2 / B-1** | D0 10-29, 45 countable dates to 12-12. It voids only on a read of a B date (§8(4)). **No claim here (confirmed).** Two bound terms constrain the export (§3): the §(a) positive control is pinned to the dev layout manifest `4d53fdbdc551…`, and §10 says "Lanes keep working on dev dates ≤ 09-29". | Bound; nothing claimed. | `docs/operations/B_FORWARD_TEST_DESIGN.md:106-110`, `:132-133`, `:186`, `:239`, `:254-262`; SoP:47-49 |
| C10 | **MG-1 reserved window** | Local targets 10-15..11-28 (provisional), NBM-guidance candidates only. **No claim here.** It touches T+1/T+2 rows captured inside the window for targets >= 10-15. | Bound. | RCW:3-6, `:25-28`; `src/weather/mg1_reserved_window.py` |
| C11 | **L6_G** and **R-ODC P1** | Both have D0 10-31 and never backfill. **No claim here.** | Frozen. | `docs/research/gefs-members-l11-2026-10-26/l6g_forward_prereg_FROZEN_2026-10-30.md:9-11`; `l6g_forward_prereg_CLARIFICATION_1_2026-10-30.md:16`; `docs/research/rodc-forward-prereg-2026-10-29/prereg-draft.md:4`, `:90-92`, `:100-109` |
| C12 | **Descriptive reads of UTC 10-16..11-13 refused** | Outside this window. A local target <= 10-14 ends by UTC 10-15 08:00, so no in-window target reaches UTC 10-16. **No claim here.** | In force. | DL:237; SoP:43 |
| C13 | Other signed or registered reads checked | Evening-fix (10-16..10-27, ext. to 10-29), t3-r3 13-16 (D >= 10-16), the second exam candidate one-sided-edge-v0 (panel 10-16..10-29), LFC session 0 (off the built-in slugs), the lowest-temperature desk study (post-10-14 capture), EDGE-1 (postponed). **None claims 09-30..10-14.** DL:262 kept "the outcome-read embargo after 09-29" for the edge test; DL:291 (3) later opens this window for kill-only reads, never an edge claim. | — | `docs/research/evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md:71-78`; `docs/research/remaining-rise-13-16-preregistration-DRAFT-2026-10-13.md:130`; `cockpit_snapshot.py:45-52`; `docs/research/live-fill-calibration-session0-spec-2026-10-09.md:27-40`; `docs/research/lowest-temperature-desk-study-preregistration-2026-10-02.md:22`; DL:262, DL:291 |
| C14 | Unregistered plans that name these dates | Exhaustion register follow-up orders 1, 2 and 6 name "post-10-09" served dates (the first dates after the serving fixes), but none is registered. **Not a claim.** Note: reading 10-10..10-14 now means those dates are no longer fresh for any of these plans. | Not registered. | `docs/operations/EXHAUSTION_REGISTER.md:325-335` |
| C15 | 88a freeze "until after 10-14"; the 10-23 embargo bullet | The freeze covers capture code, not reads. The SoP embargo bullet already carries the 10-30 opening "after a claim check". **Not claims.** | — | DL:137; SoP:42-43, SoP:79 |

## 3. Constraints on any FREE cell (apply to the whole export)

1. **No edge claim.** The read is kill-only or atlas (§5 rule 10; DL:291 (3)).
2. **No MG-2 scoring until PT-1 binds (C8).** No score of MG-2, of its bound components as composed, or of the PT-1
   rule against the market or labels. These dates do not enter PT-1's w_h, feasibility or G dev set.
3. **Do not disturb B (C9).** B's §(a) control layout manifest and the dev scorecard's default folds stay unchanged.
   Any added date goes into a separate layout. B §10:239 says lanes work on dev dates <= 09-29, and DL:291 (3) is the
   later owner text. Master should confirm that the B-side wording does not bind this one read.
4. **Filter by local target date, not capture day (C5, C10, C12).** Drop any row whose target is >= 10-15, including
   T+1/T+2 rows captured inside the window. Drop any capture on UTC 10-15 or later.
5. **Unlocking C1 is a code change.** It needs a reviewed edit of `EMBARGO_WINDOWS`, then the contract table, under
   the embargo-agreement ratchet (`DATA_LAYER_V2_CONTRACT.md:124-128`), plus the item-330 and 88a runbook lines.
   The host export tool must not bypass `platform.embargo`.
6. **Order of looks (rule 9).** Row 80's single look (C4) is the first read of its cells. An atlas read of those cells
   in the same export must not run before row 80's look or feed into it.
7. **Austin 10-03 is out (C7)**, in every kind.

## 4. Grid (date × market × kind)

All cells are BLOCKED today because of C1. The "after" columns show what each cell becomes once the named claims are
resolved, assuming the §3 constraints hold. **None of these is a FREE ruling yet.**

Codes:
- **F** = FREE once the listed claims are resolved.
- **B-x** = still BLOCKED by claim x.
- **US11** = every market except Toronto.

### Labels

| Target date | Today | After C1 resolved | Also needs |
| --- | --- | --- | --- |
| 09-30 | BLOCKED (C1) | B-C2, B-C3 (all 12) | owner ruling on C2's hold, and on C3 withdrawn or released |
| 10-01, 10-02, 10-04 .. 10-08 | BLOCKED (C1) | B-C2, B-C3 (all 12); B-C4 (US11) | C2, C3; then row 80's look for US11 |
| 10-03 | BLOCKED (C1) | Austin: **B-C7 permanently**; others as 10-01 | as 10-01 |
| 10-09 .. 10-14 | BLOCKED (C1) | Toronto: **F**; US11: B-C4 | US11 FREE after row 80's single look |

### Prices (88a or any order-book store)

| Capture or target | Today | After C1 resolved | Also needs |
| --- | --- | --- | --- |
| Captured UTC 09-30..10-07 (targets 09-30..10-08) | BLOCKED (C1) | B-C2 (same-day 88a), B-C3 (T+1/T+2 mids), all 12 | C2 and C3 resolved |
| Captured UTC 10-08 (targets 10-08..10-10) | BLOCKED (C1) | target 10-08 same-day: B-C2; targets 10-09/10-10: **F** | C2 for target 10-08 |
| Captured UTC 10-09..10-14, targets <= 10-14 | BLOCKED (C1) | **F** (all 12, except Austin 10-03, which is out of range anyway) | — |
| Captured UTC 10-15 (target 10-14 evening hours, US) | BLOCKED (C1, C5) | **B-C5** (OUTCOME window, desk-study panel hold) | — (stays blocked; the window opening covers only 09-30..10-14) |

Row 80 reads no 88a prices, so C4 does not block prices.

### Snapshots (T+0 capture rows, harness layout)

| Target date | Today | After C1 resolved | Also needs |
| --- | --- | --- | --- |
| 09-30 | BLOCKED (C1) | **F** (all 12) | — |
| 10-01 .. 10-14 | BLOCKED (C1) | Toronto: **F**; US11: B-C4; Austin 10-03: B-C7 | US11 FREE after row 80's single look |

Market-vector snapshots on panel minutes show the same prices that v2 scores against. That is why they are BLOCKED
under C1 even though DL:251 (a) puts them outside the 88a retention hold.

## 5. What master would need to decide or record

1. **Resolve C1.** Write a DL row saying the v2 draft lapsed or is abandoned, and that the panel is released from
   "may be reused" (owner). Then land a reviewed `EMBARGO_WINDOWS` change (plus the contract table and the
   runbook/item-330 lines) scoped to this read.
2. **Resolve C2 and C3.** Their holds end at the v2 look. If v2 lapses, the owner rules on each (withdrawn, or released
   for this read). Without that, 09-30..10-08 labels and 88a prices stay BLOCKED.
3. **Confirm C8 and C9.** The PT-1 condition rests on a citation that does not support it (DL "line 209"). B §10:239
   needs a ruling on whether it binds this read.
4. **Run row 80's look first** on US11 snapshots and labels 10-01..10-14, then the atlas on the same cells.

If only C1 is resolved, the FREE set is:
- Toronto labels and snapshots for targets 10-09..10-14;
- 88a prices captured UTC 10-09..10-14 for targets <= 10-14 (all 12), plus prices captured UTC 10-08 for targets
  10-09/10-10;
- all 12 markets' snapshots for 09-30.

After row 80's look, US11 labels and snapshots for 10-09..10-14 join that set.

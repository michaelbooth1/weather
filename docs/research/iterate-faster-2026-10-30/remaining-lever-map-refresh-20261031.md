# Remaining-lever map refresh (2026-10-31)

Lane L8, at the coordinator's request. A dated research note, not canonical guidance.

It refreshes §3 of `remaining-lever-map.md` at `5395f8b1f0a9d7685becae7e27261e7d09f292b2`, which this note does not
edit, after the 2026-10-30 rows and notes. The register, SoP, digest and EF are unchanged; the coordinator's
morning docs batch owns those.

**No eligible edge-bearing lever remains in the dev window as of 10-31.** This is true of the enumerated inventory
only; S31, T+1/T+2, foreign cities and the post-fix atlas are outside it (caveat added 2026-10-31, docs batch).

## 1. Disposition of the nine ELIGIBLE NOW items (map §3)

| Map rank | Item | Disposition | Evidence (full sha) |
| --- | --- | --- | --- |
| 1 | X5 ECMWF ENS member spread | **COVERED at family level** (closed 10-30). Spread against the market is closed by row 88 (X75) and X54/X55. | Register draft `38ae1c669b6d45d252d8c57cb1188e1d7654fe62` (`register-drafts-20261030.md`, for master review) |
| 2 | Row 11 DST / standard-time audit | **NOT OPEN**, and protective only. Forward emitters and recorders are all OK across 11-01, and live serving is fixed (`2960813738692a59f461aa3c59aeca5e3cf26feb`). The training-cache half is the held `a399941e32932c3ac3704fad3984cc673d608c70` set. The PIT corpus normalizer is already DST-correct (`PIT_FORECAST_TRAINING_CORPUS.md`, "DST and provider time labels"). | L2 audit `origin/claude/dst-fallback-audit-20261030` @ `a7c455f909acdc9e15558409921c074863b3833f` |
| 3 | Row 18 MOS/NBE vs the market | **KILL**, ledger row 89 | Result note `7ed78799ea72eb32631b6d26a802e170a08bec72` |
| 4 | Row 1b Toronto ECCC citypage / GEM | **KILL**, ledger row 90. Amendment 1 controls all PASS, so the KILL stands and is final. | Result `2db1ef79112053fccbf25c224caf1e942246b1d5`; amendment 1 result `63669344920aca41135d8bac28ac83dea83dfeaa` (code `ad6d71af6cd7176c68d58edd5a88508238a167c2`) |
| 5 | X7 / row 17 MRMS echo 13-16 | **KILL**, ledger row 91 (L3), synthetic sign control PASS | Result note `7e1531f7e37c0b9856d877d14a8bcc12cd3d35ac` |
| 6 | Oct-Dec LOYO batch (X13 / row 10b, X18, X20, X36) | **OWNED BY L3**, outside this lane | — |
| 7 | Row 4 KDEN | **BLOCKED**. Every route needs a download, the held caches, B-bound files or post-10-23 data. The history family is already measured in NEW_CITY_MODEL_LANE. LOYO was considered and not run (no edge power). | Note `6401e77c2716cb171eb2360f82dfdd7cdd47f089` |
| 8 | Row 15 NBM freshness audit | **CLOSED, hygiene-clean on S1.** No older-cycle reads in 1,108 sampled snapshots. The v2 half is blocked. The full scan was considered and not run (EV ≤ 0.0003). | Note `e907129c23d4b0bebf17afd87d6e3e8bf00a67e9` |
| 9 | Row 16 tenths aliasing | **KILL, premise false.** US ASOS stations report whole °F (96.7-99.99% are whole-°F images); KBKF is the discrimination control. | Note `04f07aa543b18442d9e92caf7406c52a0da17464` |

Kill checks for all nine searched the register (including `99be9e8136aac12bb0b6f938d0d6f5a46731b438`), RETRACTED,
SoP, the digest, EF and ledger rows 85-91, by name and by family. The notes cited above record each search.

## 2. BLOCKED items and what unlocks them

| Item (map row / register line) | Blocker | Unlock date or owner |
| --- | --- | --- |
| Row 12 MG-2; row 6 NBS (X35 diagnostic feeds a P3d_N training-side fix) | B-bound until B's look | **B look 12-13** |
| X1, X9; row 11 training-cache half; any lever needing fresh `forecast_history` / `open_meteo_archives` / `reanalysis_*` pulls | `a399941e32932c3ac3704fad3984cc673d608c70` HELD (master interim rule 2026-10-30) | **After 12-21** (and after `9142f5d21fd3065c881ac2aa1843d435bcb0f5c1`) |
| Any forward-date P0: rows 19 MOSMIX, 20 more markets, 22a AIFS, 24 T+1; X15, X31, X38 | Rule 9: no outcome, label or price on a date until every test claiming that date has taken its look (MG-1 10-15..11-28, B 10-29..12-12, L6_G and R-ODC P1 from D0 10-31, PT-1 12-12..01-25) | **Rule-9 readability 12-15** (B, L6_G and R-ODC dates after B's receipt) / **01-26** (PT-1 dates) |
| Row 8 t3-r3 stack; X70 | Row 80 replication | **Owner Q3** |
| X14 (R0) | Owner call | **Owner, X14** |
| Rows 26 (mesonets / WU / venues) and 27 (served path) | Owner / master call | **Owner, rows 26-27** |
| Row 19 MOSMIX; row 20 more markets (R1/R2, at least 30 days); row 22a AIFS (L22 `_single` recorder from night 10-30/31); row 22b-ii GraphCast (X51 UNTESTABLE); X30 NBM text; X32/X34/X44/X45 HRRR capture; X37 NBM V5 compression; X50/X51 capture defect; X64/X65 (at least 60 V5.0.14 days plus labels) | **Recorders** or capture: forward values must accrue first, then rule 9 applies | Recorder accrual, then the rule-9 dates above |
| Row 23 sub-MDE batching; X29 | Nothing to carry: no sub-MDE survivor and no dev winner | None; it re-opens only if a survivor appears |

## 3. Consequence

Every remaining lever with market edge power is either closed by the 10-30 rows and notes or blocked on one of four
things:
- B's look (12-13);
- `a399941e` (after 12-21);
- rule-9 readability (12-15 / 01-26);
- an owner call or a recorder.

No dev-window P0 or LOYO is proposed until one of those lifts.

# A9: maker replay v2 calibration-bundle transfer (short plan)

Written 2026-10-15 on the 32 GB workstation. r2 folded in master's answers on Q2, Q4-Q6 and the fence. **r3 (same day)
replaces the guessed paths with master's host stat, adds `calibration_v01_reference` (Q7 decided: transfer it) and
answers whether the missing 09-28 matters.**
**Plan only: nothing here has run on either host.** It is separate from
`O9-TRANSFER-PLAN.md` and its tools. `o9_stage.py` / `verify_o9.py` move book summaries only and are not reused
(O9-TRANSFER-PLAN.md:54-61, 375-377).

Refs: `M` = `origin/master` @ `90b2e1844`. `R` = `origin/claude/mrv2-owner-rulings-20261015` @ `4007292ac`, where
`transfer.py` lives; it is **not yet on the build line**. `L` = build line `origin/codex/maker-replay-v2-build-20261003`
@ `1fd0c295f`. `X` = exam tree `6ac18be7e` (M docs/operations/DECISION_LOG.md:89). `O9` = `night-plans/o9/O9-TRANSFER-PLAN.md`
on this branch. `DRV` = driver `src/maker_core/replay/v2/transfer_cli.py` on `claude/mrv2-transfer-driver-20261015`
@ `0f2944548` (R merged in; written by the workstation, reviewed by Fable, landed by master).

## Authority

- Owner, 2026-10-15 batch 2: O9 keeps the strict UTC cutoff 2026-09-30T00:00Z. A9 gets its own short plan
  (M DECISION_LOG.md:221).
- 2026-10-03 v2 design approval: sealed *panel* bundles go to the workstation only after signature, by scp against a
  transfer manifest (M DECISION_LOG.md:103 item 4). Calibration bundles are not panel bundles. They are the
  pre-signature P3 step (R docs/research/maker-replay-v2-engineering-plan-DRAFT.md:63-71).
- Master, 2026-10-15: Q2 workstation writes the driver; Q4 production runs the host side; Q5 the 10-21 night; Q6 one U6
  deploy tip; fence `0ea7a3c86` accepted; Q7 transfer `calibration_v01_reference`.

## 1. What the bundle is

- Exported day folders for the **calibration UTC dates 2026-09-27, 09-28 and 09-29** only
  (R src/maker_core/replay/v2/panel.py:37). A root is `<root>\receipt.json` plus `<root>\bundle\`, which holds
  exactly `bundle.json`, `export.json` and the listed streams (R src/maker_core/replay/v2/transfer.py:17-19, 180-185, 304).
- Three kinds (transfer.py:7-14, 100-113):
  - `calibration_night`: P1, night format v0.2/v0.3, from the U6 runner;
  - `calibration_hazard`: P2, calibration format v0.2/v0.3, from the U6 runner;
  - `calibration_v01_reference`: the E3 reference, a v0.1 calibration export from exam tree X. These already exist
    for some dates (§2).
- P3 is the scp of those bundles against a **committed** transfer manifest, then the v2 rehearsal, which fills E4-E7,
  the ceilings, N_cal and L_cal before signature (engineering-plan:65, 69-71; M docs/operations/STATE_OF_PLAY.md:66).

## 2. Host paths (master's stat, 2026-10-15)

Production root: **`C:\Users\micha\Desktop\github`** (`$G`). `C:\Users\Michael` does not exist on the host. Below,
`$S = "$G\weather\scratch"`.

| Item | Exact host path | State |
| --- | --- | --- |
| v0.1 ref 09-27 (attempt dir) | `$S\maker-replay-exam-c2b\calibration-20261003T050423Z\` | FOUND: holds `2026-09-27`, `calibration-ledger.jsonl` (1,885,470 B), `exporter-module-sha256.txt` and `.writer.lock` |
| v0.1 ref 09-29 (attempt dir) | `$S\maker-replay-exam-c2\calibration\` | FOUND: holds `2026-09-29`, `calibration-ledger.jsonl` (543,477 B) and `.writer.lock`. **`exporter-module-sha256.txt` sits one level up**, in `$S\maker-replay-exam-c2\` |
| v0.1 ref 09-28 | none | **NOT FOUND** anywhere (§5) |
| P1/P2 (v0.2/v0.3) | none yet | `$G\mrv2-cal` holds only `u6-deploy-20261010-0030` (p0-prechecks, p2-pins, refusal), which is not calibration input. `mrv2-nightly\v02` and `replay-panel` do not exist |
| A9 attempt dir (new) | `$G\mrv2-cal\a9-<yyyyMMdd-HHmm>\` with `p1-night\`, `p2-calibration\`, `transfer_manifest.json` | created on 10-21 (U6-DEPLOY-BLOCK.md:232 convention) |
| Inbox (workstation) | `data\research_inbox\maker-replay-v2-calibration\<kind>\<day>\` (leaf = the day; DRV requires it) | O9:284-285 |

The v0.1 layout is the exporter's own: `<attempt>\<day>\{receipt.json,bundle\}`, with the append-only ledger and the
writer lock in `<attempt>\` (R docs/operations/maker-replay-bundle.md:248-250). The calibration ledger can only hold
calibration dates, because X's exporter refuses any other day for that kind (X src/weather/market/maker_replay_night.py:172).
`exporter-module-sha256.txt` is an operator file, not exporter output. The binding module hash is the receipt's
`module_sha256` (X maker_replay_night.py:175, 204), which `build` records per entry (transfer.py:308).

**Lock and layout: no driver change needed.**
- `build` and `verify` read only `<root>\receipt.json` and `<root>\bundle\*`. Root = the **day folder**
  (DRV `parse_root`; transfer.py:180-185, 262-266). Both `.writer.lock` and the ledger sit in the parent attempt dir,
  so neither is named, read or copied by the root transfer.
- The c2 module file's position is irrelevant to the driver: it never reads that file.
- What the driver does check fails closed. A non-SEALED receipt refuses `transfer_receipt_not_sealed`
  (transfer.py:276-277); this matters because the 09-29 attempt in c2 is recorded as "spent" (R STATE_OF_PLAY.md:44-45).
  A `bundle\` holding anything beyond the listed files refuses `transfer_receipt_bundle_mismatch` (transfer.py:304).
- One risk: the v0.1 roots were written by X, not R. If X wrote an `input_hashes` key that PB2(a) rejects, `build`
  refuses. It does not mis-record. The driver then needs no change, but master must rule on X-era keys.

## 3. Data cutoff: strict UTC

1. **By name, before any byte (DRV).** `--root` must be `KIND=<folder named YYYY-MM-DD>`, checked as given and after
   resolving. The kind must be a calibration kind, and the day one of its days, strictly before
   `CALIBRATION_CARRY_FENCE`. Otherwise: `transfer_cli_kind_not_admitted`, `_day_embargoed` or `_day_not_in_kind`.
   `verify` re-checks every manifest entry (DRV `admitted_day`, `parse_root`).
2. **By day (library).** `days_of` allows only 09-27..29 for these kinds (transfer.py:135-141).
3. **By record.** The PB2(b) bounds scan refuses any `captured_at` outside `[day, day+1)` UTC; for 09-29 the upper
   bound is exactly 2026-09-30T00:00Z (transfer.py:53-56; DECISION_LOG.md:221). DRV always runs it.
4. **By carry key.** Fence F refuses a calibration `carry:` date at or after 2026-09-30 (`transfer_calibration_carry_after_fence`).
5. **By exporter.** U6 refuses UTC days in [09-30, 10-16) with `PANEL_GATED` (L replay_bundle_export_nightly.ps1:38-42, 151-153).
6. **Commands.** Every §6 command is a stat (`Get-Item`/`Get-ChildItem`), a hash, a copy, or a U6 export / DRV run
   on a literal date 09-27..29. No path, glob or argument names a date in 09-30..10-15. No wildcard sits at a
   day level, so nothing dated in that window can be stat'ed, opened, read or copied.

## 4. Integrity

- `build` reads three small JSON files per root and no stream byte (transfer.py:33-42). It records their sha256s, the
  module and v0.1-equivalent sha256s and each stream's identity (transfer.py:293-312).
- DRV writes the manifest as a **new** file (exclusive create, never inside a root), reads it back and prints
  `manifest_sha256`. That value is the out-of-band anchor (O9:19, 204-205).
- `verify` hashes the raw manifest and compares it with the relayed value **before** parsing. It requires the roots to
  cover the manifest exactly, re-applies every check, hashes every stream and runs the bounds scan (transfer.py:445-509).
- Module hashes: X's method requires exporter module hashes to agree across all exam bundles (DECISION_LOG.md:89).
  09-27 (c2b) and 09-29 (c2) come from different exam roots, so step 8 compares their recorded `module_sha256`s with
  each other and with both `exporter-module-sha256.txt` files.
- DRV exits 0 on PASS, 2 on refusal (one `refused: <code>` line) and 3 on error (no traceback).

## 5. Does missing 09-28 matter?

**Yes. A 09-27 + 09-29 bundle is complete as a transfer, but on that alone E3 is blocked, so signature is blocked.**
- **Transfer: not blocked.** The manifest has no coverage rule; `check_doc` only checks that each entry's day is in
  its kind (transfer.py:352-374). Two v0.1 roots plus the P1/P2 roots build and verify.
- **E3: blocked for 09-28.** The registration defines E3 per date. "Each calibration date's v0.2 bundle expands to
  its v0.1 calibration export … with an identical SHA-256. Hazard counts n_m and x_m are identical from both formats"
  (R docs/research/maker-replay-v2-registration-DRAFT.md:450; "on the three calibration dates", :360-364).
  - E3 is external evidence to the gate code (R src/maker_core/replay/v2/reachability.py:248-254). Without it E3 is
    `NOT_SUPPLIED`, so the executability status is `INCOMPLETE`, because "Only PASS passes" (reachability.py:322).
  - The v0.1 hazard n/x cannot be computed from two dates: `calibrate` refuses `calibration_requires_exact_three_dates`
    (R src/maker_core/replay/calibration.py:149-151).
- **Rehearsal and ceilings (E2, E4-E7): not affected by the v0.1 gap.** They need all three dates, but from the
  P1/P2 exports: `rehearsal_carried_requires_the_three_calibration_dates` (R src/maker_core/replay/v2/rehearsal.py:97-100),
  and `incomplete_ceiling_measurement` (R src/maker_core/replay/v2/ceilings.py:84-86; reachability.py:325-327).
  So 09-28's P1/P2 exports on 10-21 must SEAL. If 09-28 has no sealed capture, those refuse too, and the whole P3
  rehearsal is **blocked**, not degraded.
- **Remedy (master, Q10).** A v0.1 calibration export of 09-28 from exam tree X into a **new** attempt root
  `$S\maker-replay-exam-c2b\calibration-<UTC stamp>\` (never into c2 or the existing c2b attempt, whose ledgers
  refuse retries; maker-replay-bundle.md:251-252). It adds one slot of up to 2,700 s.

## 6. Order: the 10-21 night (master, Q5)

| Night (00:30) | Fixed use | A9 |
| --- | --- | --- |
| 10-16 / 10-17 / 10-18 | pyup B / cutover C / integration (O9:43; STATE_OF_PLAY.md:67-69) | none |
| 10-19 | O9 main run (O9:18, 36) | none |
| 10-20 | U6 first night, 04:10 (DECISION_LOG.md:213) | none; check U6's first receipt |
| **10-21** | U6 04:10; data layer v2 S2+S9+P1 (STATE_OF_PLAY.md:70) | P1/P2 exports (plus the 09-28 v0.1 export if Q10 is yes), **none started after 03:15**; then build and relay; the workstation pulls and verifies that morning |

The night fits at most four 2,700 s exports between 00:30 and a 03:15 last start (maker-replay-bundle.md:404-406).
Order: 09-28 first (it decides §5), then 09-27, then 09-29. Leftovers run on 10-22 (Q9), which still allows the
rehearsal before the 10-22..23 signature target, but only just (STATE_OF_PLAY.md:66).

## 7. Command sequence

**Production, on the host, 00:30-09:00.** `$D` is the one U6 deploy tip (Q6). `$MOD1`, `$WRAP1`, `$Data`, `$Rel` and
`$MinMiB` are the U6 pins (U6-DEPLOY-BLOCK.md:219-232). `$Prod = "$G\weather"`. `$T` is a clean checkout of the reviewed
DRV commit outside `$Prod` (roll-free).

1. Pre-checks: local time, `status.ps1` healthy, lease free, available MiB >= `$MinMiB`, volume free bytes
   (U6-DEPLOY-BLOCK.md:390-395).
2. Stat the v0.1 roots and side files. This is a stat only, with literal paths and no content read:
   ```powershell
   $G = 'C:\Users\micha\Desktop\github'; $S = "$G\weather\scratch"
   $V27 = "$S\maker-replay-exam-c2b\calibration-20261003T050423Z\2026-09-27"
   $V29 = "$S\maker-replay-exam-c2\calibration\2026-09-29"
   Get-ChildItem -LiteralPath $V27, $V29 -Recurse -File | Select-Object FullName, Length, LastWriteTime
   Get-Item -LiteralPath "$S\maker-replay-exam-c2b\calibration-20261003T050423Z\calibration-ledger.jsonl",
     "$S\maker-replay-exam-c2b\calibration-20261003T050423Z\exporter-module-sha256.txt",
     "$S\maker-replay-exam-c2\calibration\calibration-ledger.jsonl", "$S\maker-replay-exam-c2\exporter-module-sha256.txt" |
     Select-Object FullName, Length, LastWriteTime
   ```
   Each day folder must list `receipt.json` and `bundle\{bundle.json,events.jsonl,export.json}`. If one does not,
   that date has no v0.1 reference: stop and report to master. A `pending\` folder in it means that attempt was not
   sealed.
3. `$A9 = "$G\mrv2-cal\a9-$((Get-Date).ToString('yyyyMMdd-HHmm'))"`; `New-Item -ItemType Directory $A9`.
4. Run the exports serially for `$d` in `2026-09-28`, `2026-09-27`, `2026-09-29`. Stop the night on any non-zero exit,
   and start nothing after 03:15. The runner takes the lease itself (maker-replay-bundle.md:404).
   ```powershell
   powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$D\scripts\ops\replay_bundle_export_nightly.ps1" `
     -DeployRoot $D -ProductionRoot $Prod -DataRoot $Data -ReleaseRoot $Rel -OutputRoot "$A9\p1-night" `
     -ExpectedModuleSha256 $MOD1 -ExpectedSelfSha256 $WRAP1 -MinAvailableMiB $MinMiB -Kind night -Day $d
   # then the same line with -OutputRoot "$A9\p2-calibration" -Kind calibration
   ```
   If Q10 is yes, the 09-28 v0.1 export uses master's exam-tree command into a new c2b attempt root (not given here).
5. Build. It reads three small JSON files per root and no stream byte:
   ```powershell
   $env:PYTHONPATH = "$T\src"
   & "$Prod\venv\Scripts\python.exe" -P -B -m maker_core.replay.v2.transfer_cli build `
     --root "calibration_night=$A9\p1-night\2026-09-27"  --root "calibration_hazard=$A9\p2-calibration\2026-09-27" `
     --root "calibration_night=$A9\p1-night\2026-09-28"  --root "calibration_hazard=$A9\p2-calibration\2026-09-28" `
     --root "calibration_night=$A9\p1-night\2026-09-29"  --root "calibration_hazard=$A9\p2-calibration\2026-09-29" `
     --root "calibration_v01_reference=$V27" --root "calibration_v01_reference=$V29" `
     --host-id $env:COMPUTERNAME --out "$A9\transfer_manifest.json"
   ```
   Omit any root whose export did not SEAL. On exit 2, record the `refused:` line and stop.
6. Hash relay: `(Get-FileHash -Algorithm SHA256 "$A9\transfer_manifest.json").Hash.ToLower()` must equal the printed
   `manifest_sha256`. Also take `Get-FileHash` of the four side files from step 2. Relay out of band: the manifest
   hash, the `KIND=path` roots, the four side-file paths and hashes, and the byte totals. Keep `$A9`; it is evidence.

**Workstation (after the relay, no host lease).**

7. Pull with copies only, by exact name. The manifest goes first (`scp production-pc:<A9>/transfer_manifest.json $I\`),
   then the manifest is checked against the relayed hash. Then each root (`scp -r production-pc:<root> $I\<kind>\`),
   then the four side files by name into `$I\v01-side\{c2b,c2}\` (O9:279-283). **`.writer.lock` is never named or
   copied**: the roots are day folders, and the side files are pulled by name.
8. Verify via `workstation_heavy.ps1 -Kind weather_heavy`:
   `python -P -B -m maker_core.replay.v2.transfer_cli verify --manifest $I\transfer_manifest.json
   --expected-manifest-sha256 <relayed> --root calibration_night=$I\calibration_night\2026-09-27 ...` (every root).
   Keep the stdout receipt. Then check:
   - the side files' hashes match the relay;
   - each ledger's terminal row for its day is `SEALED`;
   - the two v0.1 entries' `module_sha256` equal each other and the module files (§4).
9. On PASS, commit the byte-identical manifest to `config/maker_replay_v2/transfer_manifest.json` on the branch master
   names (`config/` is roll-free), then run the P3 rehearsal (rehearse_cli.py:1-11).

## 8. Verification and rollback

- **PASS:** exit 0, verdict `PASS`, one bundle per manifest entry, each with counts and min/max inside its day.
- **Workstation rollback:** delete only `$I`, revert the manifest with a new commit (never a force-push), and report the
  refusal code.
- **Host:** nothing is moved or modified, and the exam roots are only stat'ed and copied. A failed export gets a new `$A9`
  attempt (M AGENTS.md:102).

## 9. Open questions (remaining)

- **Q8.** Are 09-27 (c2b) and 09-29 (c2) the v0.1 references, given the different exam roots, and given that c2's
  09-29 is recorded as "spent" (STATE_OF_PLAY.md:44-45)? Step 2 and `transfer_receipt_not_sealed` answer the seal
  question mechanically.
- **Q9.** Can the 10-22 night take leftover exports?
- **Q10.** Authorize a 09-28 v0.1 calibration export from exam tree X into a new c2b attempt root, and give its exact
  command? Without it, E3 cannot pass (§5).
- **Q11.** If X-era v0.1 `input_hashes` keys fail PB2(a) at build, is a reviewed X-key allowance acceptable, or do the
  v0.1 references need re-export?

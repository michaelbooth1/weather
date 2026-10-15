# A9: maker replay v2 calibration-bundle transfer (short plan)

Written 2026-10-15 on the 32 GB workstation; r2 (same day) folds in master's answers on Q2, Q4-Q6 and the fence.
**Plan only: nothing here has run on either host.** It is separate from
`O9-TRANSFER-PLAN.md` and its tools. `o9_stage.py` / `verify_o9.py` move book summaries only and are not reused
(O9-TRANSFER-PLAN.md:54-61, 375-377).

Refs: `M` = `origin/master` @ `90b2e1844`. `R` = `origin/claude/mrv2-owner-rulings-20261015` @ `67a708244`, where
`transfer.py` lives; it is **not yet on the build line**. `L` = build line `origin/codex/maker-replay-v2-build-20261003`
@ `1fd0c295f`. `O9` = `night-plans/o9/O9-TRANSFER-PLAN.md` on this branch. `F` = fence commit `0ea7a3c86` on R.
`DRV` = driver `src/maker_core/replay/v2/transfer_cli.py` on `claude/mrv2-transfer-driver-20261015` @ `51f90f19d`
(written by the workstation, reviewed by Fable, landed by master).

## Authority

- Owner, 2026-10-15 batch 2: O9 keeps the strict UTC cutoff 2026-09-30T00:00Z. A9 gets its own short plan
  (M docs/operations/DECISION_LOG.md:221).
- 2026-10-03 v2 design approval: sealed *panel* bundles go to the workstation only after signature, by scp against a
  transfer manifest (M DECISION_LOG.md:103 item 4). Calibration bundles are not panel bundles. They are the
  pre-signature P3 step (R docs/research/maker-replay-v2-engineering-plan-DRAFT.md:63-71).

## 1. What the bundle is

- Exported day folders for the three **calibration UTC dates 2026-09-27, 09-28 and 09-29** only
  (R src/maker_core/replay/v2/panel.py:37). Each root is `<root>/receipt.json` plus `<root>/bundle/`, which holds
  exactly `bundle.json`, `export.json` and the listed streams (R src/maker_core/replay/v2/transfer.py:17-19).
- Export kinds for calibration dates: `calibration_night` (night format, v0.2/v0.3), `calibration_hazard`
  (calibration format, v0.2/v0.3) and `calibration_v01_reference` (v0.1, the E3 reference)
  (transfer.py:7-14, 97-102, 134-135). That is at most 9 bundles, under `MAX_BUNDLES` = 32 (transfer.py:86).
- They come from P1 (night-format export of 09-27..29) and P2 (v0.2 calibration-format export compared with v0.1).
  P3 is the scp of those bundles to the workstation against a **committed** transfer manifest, followed by the v2
  rehearsal (engineering-plan:69-71). The P3 rehearsal fills gate values E4-E7, the ceilings, N_cal and L_cal before
  signature (engineering-plan:65, 71; M docs/operations/STATE_OF_PLAY.md:66).
- Producer: the U6 runner, run by hand with `-Day <date> -Kind night|calibration` (L scripts/ops/replay_bundle_export_nightly.ps1:25-26, 219-220).

## 2. Hosts and paths

The host's production root is **`C:\Users\micha\Desktop\github\weather`** in the host runbooks (U6 deploy block,
night-plans/2026-10-10/U6-DEPLOY-BLOCK.md:219; M docs/operations/wu-settlement-source-down-2026-08-07.md:115).
`C:\Users\Michael\Documents\github\weather` is the workstation checkout. The Q1 command stats both.

| Side | Path | Basis |
| --- | --- | --- |
| P1/P2 output (host) | `C:\Users\micha\Desktop\github\mrv2-cal\<attempt>\p1-night\<day>` and `...\p2-calibration\<day>`. U6 shakeout: `...\mrv2-cal\u6-deploy-<stamp>\shakeout\2026-09-27` | U6-DEPLOY-BLOCK.md:132, 232, 397-399 |
| v0.1 reference (host) | `<Prod>\scratch\maker-replay-exam-c2b\calibration-<UTC stamp>\<day>` (the 09-29 attempt in `...-c2` is spent) | R docs/operations/STATE_OF_PLAY.md:44-45 |
| A9 attempt dir (host) | `C:\Users\micha\Desktop\github\mrv2-cal\a9-<yyyyMMdd-HHmm>\` (P1, P2, manifest; outside the production tree) | U6-DEPLOY-BLOCK.md:232 convention |
| Manifest (committed) | `config/maker_replay_v2/transfer_manifest.json`, keyed per `(day, export_kind)` | transfer.py:3-4, 83 |
| Inbox (workstation) | `data\research_inbox\maker-replay-v2-calibration\<kind>\<day>\` (leaf = the day; the driver requires it) | O9:284-285; DRV transfer_cli.py `parse_root` |

A root is `<out>\<day>`, holding `receipt.json` and `bundle\` (F src/weather/market/maker_replay_night_v02.py:115-121).
Each kind needs its own `--out`: a second export of a day into the same `--out` refuses with
`day_already_sealed_or_attempted` (F maker_replay_night_v02.py:119-121).

### Q1: read-only stat of existing P1/P2/v0.1 bundles (09-27..09-29 only)

Every leaf is a literal calibration date, and wildcards stand only for attempt-stamp levels. No folder dated 09-30 or
later is named, stat'ed or opened, and no file content is read.

```powershell
$days  = '2026-09-27','2026-09-28','2026-09-29'
$bases = 'C:\Users\micha\Desktop\github', 'C:\Users\Michael\Documents\github'
$pat = foreach ($b in $bases) { foreach ($d in $days) {
  "$b\mrv2-cal\*\*\$d\receipt.json"; "$b\mrv2-cal\*\*\$d\bundle\*"
  "$b\mrv2-nightly\v02\$d\receipt.json"; "$b\mrv2-nightly\v02\$d\bundle\*"
  "$b\weather\scratch\maker-replay-exam-c2b\*\$d\receipt.json"; "$b\weather\scratch\maker-replay-exam-c2b\*\$d\bundle\*"
  "$b\weather\scratch\maker-replay-exam-c2\*\$d\receipt.json"; "$b\weather\scratch\maker-replay-exam-c2\*\$d\bundle\*"
  "$b\weather\scratch\replay-panel\$d\receipt.json"; "$b\weather\scratch\maker-replay-panel\$d\receipt.json" } }
Get-ChildItem -Path $pat -File -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime
```

## 3. Data cutoff: strict UTC

1. **By name, before any byte (the driver).**
   - `--root` must be `KIND=<folder named YYYY-MM-DD>`. The name is checked as given and again after resolving.
   - The kind must be a calibration kind, and the day must be one of that kind's days, strictly before
     `CALIBRATION_CARRY_FENCE`.
   - Otherwise the driver refuses with `transfer_cli_kind_not_admitted`, `transfer_cli_day_embargoed` or
     `transfer_cli_day_not_in_kind`. `verify` applies the same check to every manifest entry (DRV transfer_cli.py
     `admitted_day`, `parse_root`).
2. **By day (the library).** `days_of` allows only 09-27..09-29 for these kinds (transfer.py:129-136, 242-243,
   344-345). The rehearsal refuses other dates by path name (R tools/research/maker_replay_v2/run.py:20).
3. **By record.** The PB2(b) bounds scan refuses any `captured_at` outside `[day 00:00Z, day+1 00:00Z)`. For 09-29
   that upper bound is exactly 2026-09-30T00:00Z (transfer.py:53-56, 420-434; DECISION_LOG.md:221). The driver always
   runs this scan.
4. **By carry key.** Fence `F` refuses a calibration `carry:` date at or after 2026-09-30T00:00Z with
   `transfer_calibration_carry_after_fence:<day>`. Master accepted the fence.
5. **By exporter.** U6 refuses UTC days in [09-30, 10-16) with `PANEL_GATED`
   (L replay_bundle_export_nightly.ps1:38-42, 151-153).
6. **Known consequence.** A 09-29 target's settlement fact that sits on UTC 09-30 is excluded. O9 accepted the same
   trade-off (O9:123-132; engineering-plan:72).

## 4. Integrity

- `build` reads only `bundle.json`, `export.json` and `receipt.json` per root (transfer.py:33-42, 315-323). It records:
  - those three sha256s;
  - the module and v0.1-equivalent sha256s;
  - each stream's identity (transfer.py:103-105, 293-303).
- The driver writes the manifest as a **new** file: exclusive create, never inside a root. It reads the file back and
  prints `manifest_sha256`. That value is the out-of-band anchor (O9 D3 pattern, O9:19, 204-205).
- `verify` needs the relayed sha256 and compares the raw bytes **before** parsing. It then requires the roots to cover
  the manifest exactly. After that it re-applies every check, hashes every stream (pass one) and runs the bounds scan
  (transfer.py:445-509).
- P1/P2 bundles share the U6-pinned `module_sha256` (`-ExpectedModuleSha256`). The v0.1 references carry the exam
  tree's own module hash, recorded per entry (DECISION_LOG.md:89).
- Driver exit codes:
  - 0: PASS;
  - 2: refused, with one `refused: <code>` line;
  - 3: error, with no traceback.

## 5. Order: the 10-21 night (master, Q5)

| Night (00:30) | Fixed use | A9 |
| --- | --- | --- |
| 10-16 / 10-17 / 10-18 | pyup B / cutover C / integration (O9:43; STATE_OF_PLAY.md:67-69) | none |
| 10-19 | O9 main run (O9:18, 36) | none |
| 10-20 | U6 first night, 04:10 (DECISION_LOG.md:213) | none; check U6's first receipt |
| **10-21** | U6 04:10; data layer v2 S2+S9+P1 (STATE_OF_PLAY.md:70) | P1/P2 exports, none started after 03:15; then `build` and the relay; the workstation pulls and verifies that morning |

The night may not fit all six exports before 04:10:
- each export may take up to 2,700 s;
- runner starts are limited to 00:30-04:54 (R docs/operations/maker-replay-bundle.md:404-406).

Any leftover export runs on the 10-22 night. That still allows the rehearsal before the 10-22..23 signature target,
but only just (STATE_OF_PLAY.md:66). Master sequences A9 against data layer v2's lease use.

## 6. Command sequence

**Production, on the host (master-agent or host), inside 00:30-09:00.**

Variables:
- `$D` is the one U6 deploy tip (Q6).
- `$MOD1`, `$WRAP1`, `$Data`, `$Rel` and `$MinMiB` are the U6 pins (U6-DEPLOY-BLOCK.md:219-232).
- `$T` is a clean checkout of the reviewed driver commit, outside `$Prod`. It is roll-free.

1. Pre-checks: local time, `status.ps1` healthy, lease free, available MiB >= `$MinMiB`, and the volume's free bytes
   (U6-DEPLOY-BLOCK.md:390-395).
2. Run the Q1 command (§2). For each (day, kind) already SEALED from the pinned `$MOD1`, record its root and skip it.
3. `$A9 = "C:\Users\micha\Desktop\github\mrv2-cal\a9-$((Get-Date).ToString('yyyyMMdd-HHmm'))"`, then create it
   with `New-Item -ItemType Directory`.
4. For each missing `$d` in `2026-09-27`, `-28`, `-29`, run the exports serially. Stop the night on any non-zero
   exit. The runner takes the lease itself (maker-replay-bundle.md:404).
   ```powershell
   powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$D\scripts\ops\replay_bundle_export_nightly.ps1" `
     -DeployRoot $D -ProductionRoot $Prod -DataRoot $Data -ReleaseRoot $Rel -OutputRoot "$A9\p1-night" `
     -ExpectedModuleSha256 $MOD1 -ExpectedSelfSha256 $WRAP1 -MinAvailableMiB $MinMiB -Kind night -Day $d
   # then the same line with -OutputRoot "$A9\p2-calibration" -Kind calibration
   ```
5. Build. This step is light: it reads three small JSON files per root and no stream byte. The command assumes the
   Q7 recommendation; drop the v0.1 roots if master decides otherwise.
   ```powershell
   $env:PYTHONPATH = "$T\src"
   & "$Prod\venv\Scripts\python.exe" -P -B -m maker_core.replay.v2.transfer_cli build `
     --root "calibration_night=$A9\p1-night\2026-09-27" --root "calibration_hazard=$A9\p2-calibration\2026-09-27" `
     --root "calibration_v01_reference=$Prod\scratch\maker-replay-exam-c2b\calibration-<stamp>\2026-09-27" `
     <the same three for 09-28 and 09-29> --host-id $env:COMPUTERNAME --out "$A9\transfer_manifest.json"
   ```
6. Hash relay: `(Get-FileHash -Algorithm SHA256 "$A9\transfer_manifest.json").Hash.ToLower()` must equal the printed
   `manifest_sha256`. Relay to the workstation, out of band: that value, the nine `KIND=path` roots and the byte
   totals. Keep `$A9`; it is evidence.

**Workstation (after the relay, inside 00:30-09:00, no host lease).**

7. Pull the manifest first: `scp production-pc:<A9>/transfer_manifest.json $I\`, where `$I` is the inbox. Check it
   against the relayed sha256. Then pull each root: `scp -r production-pc:<root> $I\<kind>\` (O9:279-283).
8. Run verify through `workstation_heavy.ps1 -Kind weather_heavy`:
   `python -P -B -m maker_core.replay.v2.transfer_cli verify --manifest $I\transfer_manifest.json
   --expected-manifest-sha256 <relayed> --root calibration_night=$I\calibration_night\2026-09-27 ...` (all nine
   roots). Keep the stdout receipt.
9. On PASS, commit the byte-identical manifest to `config/maker_replay_v2/transfer_manifest.json` on the branch master
   names (`config/` is roll-free). Then run the P3 rehearsal (rehearse_cli.py:1-11).

## 7. Verification and rollback

- **PASS:** exit 0, verdict `PASS`, and one bundle per manifest entry, each with counts and min/max inside its day.
- **Workstation rollback:** delete only `$I`, revert the manifest with a new commit (never a force-push), and report
  the refusal code.
- **Host:** nothing is moved or modified. A failed export gets a new `$A9` attempt (M AGENTS.md:102).

## 8. Q7 recommendation: transfer `calibration_v01_reference`

**Recommendation: yes, transfer it.** Reasons:
- `transfer.py` already models it as a transfer kind, "the E3 reference, PM4" (transfer.py:14, 97-102).
- P2's hash comparison and the hazard n/x from both formats read every stream (engineering-plan:70). Doing that on the
  workstation keeps the reads off the capture host.
- The bundles are small: calibration bundles keep only descriptor, coverage and trade
  (R docs/roadmap/agent-report-2026-10-111e-followup.md:388).
- The same name, carry and bounds fences apply to it.

Caveats:
- Master picks the c2b attempt for each date (Q8).
- Its `module_sha256` is the exam tree's hash, recorded per entry.

## 9. Open questions (remaining)

- **Q1.** Run the §2 stat. What exists, under which roots, and with which module hash?
- **Q7.** Master decides on the §8 recommendation.
- **Q8.** Which `<stamp>` is the v0.1 reference for each date?
- **Q9.** Can the 10-22 night take any exports left over from 10-21?

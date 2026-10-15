# A9: maker replay v2 calibration-bundle transfer (short plan)

Written 2026-10-15 on the 32 GB workstation. **Plan only: nothing here has run on either host.** It is separate from
`O9-TRANSFER-PLAN.md` and its tools. `o9_stage.py` / `verify_o9.py` move book summaries only and are not reused
(O9-TRANSFER-PLAN.md:54-61, 375-377).

Refs: `M` = `origin/master` @ `90b2e1844`. `R` = `origin/claude/mrv2-owner-rulings-20261015` @ `67a708244`, where
`transfer.py` lives; it is **not yet on the build line**. `L` = build line `origin/codex/maker-replay-v2-build-20261003`
@ `1fd0c295f`. `O9` = `night-plans/o9/O9-TRANSFER-PLAN.md` on this branch.

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

| Side | Path | Basis |
| --- | --- | --- |
| Source (capture host) | `<OutputRoot>\<root per day and kind>`. U6 writes under `-OutputRoot`, which must be disjoint from data and release roots. **Exact path: master to confirm (Q1)** | L register_replay_bundle_export_nightly.ps1:12, 29-53 |
| v0.1 reference (host) | `scratch\maker-replay-exam-c2b\calibration-<UTC stamp>` (older state copy; the 09-29 attempt in `...-c2` is spent) | R docs/operations/STATE_OF_PLAY.md:44-45 |
| Manifest (committed) | `config/maker_replay_v2/transfer_manifest.json`, keyed per `(day, export_kind)` | transfer.py:3-4, 83 |
| Destination (workstation) | `data\research_inbox\maker-replay-v2-calibration\<day>\<kind>\` (proposed; follows the O9 inbox precedent). The rehearsal CLI reads `<root>/<date>/bundle` | O9:284-285; R tools/research/maker_replay_v2/rehearse_cli.py:54 |
| Transport | workstation `scp` over the `production-pc` alias, never through git. P3 text says "Owner `scp`" (Q4) | O9:272-276; engineering-plan:71 |

## 3. Data cutoff: strict UTC

1. **By day.** `days_of` allows only the three calibration dates for these kinds, in both `build` and `check_doc`
   (transfer.py:129-136, 242-243, 344-345). The rehearsal refuses other dates by path name before reading any byte
   (R tools/research/maker_replay_v2/run.py:20).
2. **By record.** The PB2(b) bounds scan refuses any record with `captured_at` outside `[day 00:00Z, day+1 00:00Z)`
   (transfer.py:53-56, 420-434). For 09-29 the upper bound is exactly 2026-09-30T00:00Z, the owner's strict UTC
   cutoff (DECISION_LOG.md:221). Only counts and min/max leave the scan (transfer.py:409-412). `verify` must run with
   `bounds_check=True`, which is the default (transfer.py:445).
3. **By exporter.** The U6 runner refuses every UTC day in [09-30, 10-16) with `PANEL_GATED`, exit 3
   (L replay_bundle_export_nightly.ps1:4-6, 38-42, 151-153).
4. **Gap (Q3).** A `carry:YYYY-MM-DD` input key is accepted for any calendar date, with no upper bound
   (transfer.py:109, 211-216). For A9, a calibration entry must refuse a carry date >= 2026-09-30.
5. **Known consequence.** The settlement fact for a 09-29 target may sit on UTC 09-30. P4 reports which day carries it
   (engineering-plan:72). Under strict UTC it is not in any calibration bundle, the same trade-off O9 accepted
   (O9:123-132).

## 4. Integrity

- **Per bundle.** `build` runs on the host and reads only `bundle.json`, `export.json` and `receipt.json`, never a
  stream byte (transfer.py:33-42, 315-323). It records the bundle/export/receipt,
  module and `v01_equivalent` sha256s and each stream's identity (decoded sha/bytes for v0.3)
  (transfer.py:103-105, 293-303). It requires `provenance == "captured"` and a `SEALED` receipt (transfer.py:248-251).
- **Exporter pin.** Every bundle must carry the same `module_sha256`, the one U6 pins (`-ExpectedModuleSha256`). This
  carries forward the v1 rule that exporter hashes agree across bundles (DECISION_LOG.md:89; L register:13).
- **Anchor.** Master relays the sha256 of the manifest document out of band. The workstation compares it before
  committing the manifest or pulling any bundle (the O9 D3 pattern, O9:19, 204-205).
- **Workstation verify.** Each of the three JSON files is hashed before it is parsed. All `build` checks are
  re-applied, then pass one hashes and counts every stream (transfer.py:43-47, 445-509).
- **Known gap.** LOW-A: `bundle.json` is re-read and parsed before its hash is compared. It fails closed
  (transfer.py:49-53).
- **No CLI.** `build` and `verify` are library functions only, with no CLI (transfer.py:315, 445). A small reviewed
  driver is needed (Q2).

## 5. Order relative to O9 (10-19) and U6 (10-20)

| Night (00:30) | Fixed use | A9 |
| --- | --- | --- |
| 10-16 / 10-17 | pyup Phase B / cutover C (O9:43; STATE_OF_PLAY.md:67) | none |
| 10-18 | #177, #182, #172 integration (STATE_OF_PLAY.md:69) | none |
| 10-19 | **O9 main run**, up to 60 min planned and a 2 h cap (O9:18, 36) | none: do not stack heavy work under the exclusive lease (O9:47-49) |
| 10-20 | **U6 first night**, registered at 04:10 (DECISION_LOG.md:213; STATE_OF_PLAY.md:81) | after U6's first receipt is checked: P1/P2 for the dates still missing, under the lease and serially, then `build` (light) |
| 10-20 / 10-21 morning | | relay the manifest sha256; workstation commits the manifest, pulls, runs `verify` and then the rehearsal |

Rationale:
- The P1/P2 bundles should come from the same deploy tree and module that U6 pins.
- The rehearsal has to finish before the signature target of 10-22..23 (STATE_OF_PLAY.md:66).
- **Master owns the slot (Q5).**

## 6. Who executes

- **Production (master-agent or host):** P1/P2 exports under `workload_admission.ps1`; `build`; recording and
  relaying the manifest sha256; keeping the host export roots (evidence, never deleted). These are production steps, like the U6 registration (DECISION_LOG.md:213).
- **Workstation:** reviews the driver; commits the manifest to the branch master names (`config/` is roll-free);
  pulls; runs `verify` and the rehearsal through `workstation_heavy.ps1` (run.py:23-24).

## 7. Verification and rollback

- **PASS** means the manifest sha matches the relayed value and `verify` returns one `Verified` per listed bundle,
  with bounds results whose max `captured_at` is below the day's end (transfer.py:123-126, 440-442). The receipt
  records the counts and min/max values only.
- **Workstation rollback.** Delete only the A9 inbox folder. Revert the manifest with a new commit, never a force-push.
  Report the refusal code (`transfer_*`, transfer.py:114-120).
- **Host.** Nothing is moved or modified, so there is no host rollback. A failed export is re-run under a new attempt,
  as in the integration-attempt precedent (M AGENTS.md:102).

## 8. Open questions

- **Q1.** Do P1/P2 bundles for 09-27..29 already exist on the host? If so, what are their exact roots and
  `module_sha256`? STATE_OF_PLAY lists P1-P4 as still to do (STATE_OF_PLAY.md:66).
- **Q2.** Who writes and reviews the `build`/`verify` driver, and does `transfer.py` land on the build line first?
  It is on R, not L (see Refs).
- **Q3.** Add a carry-date fence (< 2026-09-30) for the calibration kinds before A9 runs (§3.4)?
- **Q4.** Who runs the scp: the owner (P3 text) or the workstation (O9 precedent)?
- **Q5.** The slot: the 10-20 night after U6, or 10-21 (which overlaps the data layer v2 S2+S9+P1, STATE_OF_PLAY.md:70)?
- **Q6.** The U6 04:10 slot is only on `claude/u6-registrar-0410-20261009` (register:23). The build-line tip still
  allows only 00:35 (L register:17). Confirm the deploy tip before running P1/P2 from it.
- **Q7.** Does `calibration_v01_reference` transfer too, or does it stay on the host because E3 is computed there
  (engineering-plan:70)?

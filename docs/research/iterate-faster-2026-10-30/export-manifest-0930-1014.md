# Export manifest: released dates 2026-09-30..10-14 (draft)

Status: DRAFT for master's single host export. Lane L8, 2026-10-31. This is research evidence, not a canonical
document. It was written from code and repository text only. No data file, data directory or capture host was
read or listed.

**Update 2026-10-31:** C1/C2 maker-economics reads closed per DL 2026-10-30; release used for row 80, the atlas and weather kill-only reads only.

Authority: the owner's yes at about 23:5x on 2026-10-30, relayed by master. It releases 09-30..10-14 for weather
kill-only and atlas reads, covering C1, C2 and C3. C5, C7 and the MG-2/B outputs stay excluded. Row 80's look (C4)
is the first read. Claim ids follow `docs/research/iterate-faster-2026-10-30/claim-check-0930-1014.md` on
`claude/claim-check-0930-1014-20261030` @ `31b9218b101528d1d8a5911da2916e5cb3848197`. Its §3 constraints apply to
this whole export.

**Master's rulings, 2026-10-31 (relayed by the coordinator). They override anything below that disagrees.**

- **The boundary is the local target date.** A target of 10-14 or earlier is released, including a 10-14 label
  recorded on UTC 10-15. A target of 10-15 or later stays embargoed whatever its capture time (C5). There is no
  capture-time cut on slug-folder files.
- **The embargo edit does not land.** `0f9929736d83c13d60d37f91858d97ed586f701a` (and `e89cbb52`) stay unlanded
  as evidence: row 80, C2 and C3 do not need them, and landing them would open maker_shadow economics, which the
  owner did not release. A step that truly needs the 88a panel reads it with a research reader under this
  manifest, and master is told which step and why. C1's `export_gate` stays unedited.
- **Austin 10-03 is dropped by the readers** (C7).
- **The guidance extract is existing packaged code.** It needs no allowlist entry and runs under
  `workstation_heavy.ps1` if it is heavy. The row 80 look takes a heavy slot through the queue.
- **Orders 1 and 6: option (a).** 10-10..10-14 are read now as a descriptive order 1 slice and are excluded from
  order 6.
- **Master fills the byte sizes and runs the row 80 sub-manifest export**, with a size precheck. Its receipt names
  the ledgers that carry `snapshot_tape_sha256`.

## 1. Preconditions

1. **The embargo edit does NOT land (master, 2026-10-31).** `claude/embargo-release-0930-1014-20261031` @
   `0f9929736d83c13d60d37f91858d97ed586f701a` stays unlanded as evidence.
   - The export tool must not bypass `platform.embargo` (claim check §3.5).
   - `MakerEvidencePanel` therefore keeps refusing every 88a day 09-30..10-14
     (`src/weather/market/maker_shadow_panel.py:41-44`). A consumer that needs 88a reads the exported sealed
     segments with a research reader under this manifest, after telling master which step and why.
2. **Unlanded code still refuses on its own.** The maker replay v2 build branch has its own gate,
   `src/maker_core/replay/export_gate.py:39-43` on `codex/maker-replay-v2-build-20261003` @
   `1fd0c295f6b79fb63f7ddf3e6219b32511956e5a`. Its `GATED_DAYS` cover UTC 09-30..10-15, and
   `SIGNED_REGISTRATION_SHA256` is None, so it refuses every gated day. That gate does not read `EMBARGO_WINDOWS`.
   - Any C1 or C3 bundle export that runs that code stays refused until it is edited separately.
   - This manifest therefore lists **raw host files**, not bundles.
3. **One export, one destination, a fresh folder.**
   - The destination folder path must not contain `88a` or `panel`. `loss_atlas.FORBIDDEN_INPUT` refuses such
     paths (`src/weather/reporting/scorecards/loss_atlas.py:100`, `:110-113`).
   - Do not write into B's control layout (manifest `4d53fdbdc551…`), into `C:\swarm\v3layout`, or into any
     MG-2 input-export folder.

## 2. Date rule (applies to every file and every row)

- **Market set:** the 12 built-in markets. US11 is nyc, atlanta, austin, chicago, dallas, denver, houston,
  los-angeles, miami, san-francisco and seattle (`market_registry.BUILTIN_SPECS`, display unit F). The twelfth
  is toronto.
- **Target dates are local and inclusive: 2026-09-25..2026-10-14.** A slug folder's date is
  `date_from_event_slug(folder.name)`, and its market is `spec_for_slug(folder.name)`, as in
  `src/weather/reporting/research/guidance_extract.py:156-167`. Drop every target on or after 10-15. That includes
  T+1/T+2 rows captured inside the window.
- **No capture-time cut (master, 2026-10-31).** The boundary is the local target date only. A slug folder for
  a target of 10-14 or earlier is exported whole, including rows captured on UTC 10-15. A slug folder for a
  target of 10-15 or later is never exported, whatever its capture time. In shared multi-target files, rows are
  kept or dropped by their target date.
- **88a days are UTC days 2026-09-23..2026-10-14.** No `data/maker_evidence/2026-10-15/` and nothing later.
- **Days before 09-30 are not newly released.** Their rows serve as calibration and lookback for C1–C3, and they
  are subject to the same exclusions. If the workstation already holds an identical file (same sha256), skip it.
- **Labels are kept by target date, not by recorded time.**
  - Keep `settlements/<market>/ledger.jsonl` rows for targets 09-25..10-14 even when they were recorded on or after
    UTC 10-15. A target-10-14 settlement is usually recorded then.
  - Drop every other row of those ledgers. That covers targets on or after 10-15, before 09-25, and Austin 10-03.
  - Master confirmed on 2026-10-31 that a 10-14 label recorded on UTC 10-15 is released.

## 3. Excluded cells (never exported)

| Id | What | How it is enforced |
| --- | --- | --- |
| C5 | Every local target of 10-15 or later, whatever its capture time; the 88a day 10-15; the OUTCOME window 10-15..11-13 | The target-date rule and the 88a day range. No `maker_evidence/2026-10-15+`. No slug folder whose target is on or after 10-15. Target-10-14 rows captured on UTC 10-15 are released (master, 2026-10-31). |
| C7 | Austin, target 2026-10-03, in every kind | The readers drop it (master, 2026-10-31). The Austin 10-03 slug folder and ledger row are still left out of the row 80 sub-manifest, and `r80_layout.py` refuses the extract if they appear. For 88a, see §5 open point 1. |
| C8/C9 | MG-2 and B outputs until PT-1 binds | Not exported: `mg2_input_export.ps1` outputs, B-1 receipts and `b_control*` files, the MG-2 composite release files, dev scorecard and loss-atlas outputs on B dates, and the PT-1 dev set. These dates must not enter PT-1's w_h, feasibility or G set. |
| C4 order | Row 80's single look comes first | See §6. The rest of the export may be transferred, but no consumer reads US11 snapshots or labels for 10-01..10-14 before row 80's receipt exists. |
| standing | Credentials, wallet data, `config/local/*`, `.env*`, exchange account state | Never exported. |

## 4. Files

Paths are relative to the production data root (`weather.paths.DATA_ROOT`, the exporters' `--data-root`).
`<slug>` is an event slug folder that passes the §2 market and date rule. "gz variant" means the reader also
accepts `<name>.gz` (`Reader.variant`). Export whichever exists, and record which one.

### 4.1 Per-event slug folders: `snapshots/<slug>/`

| File | Needed by | Row filter | Bytes |
| --- | --- | --- | --- |
| `snapshots_long.csv` (gz variant) | Row 80 and atlas (via the layout builder, `guidance_extract.py:421`); C1/C3 support (`maker_plugin_sources.py:408`) | target ≤ 10-14 (whole folder) | host to fill |
| `features_long.csv` (gz variant) | Row 80 and atlas (`guidance_extract.py:430`) | target ≤ 10-14 (whole folder) | host to fill |
| `replay_inputs.jsonl` (gz variant) | Row 80 (`C:/t/l8ftr/rep.py:119`; METAR receipt rows); atlas `regimes --replay-root` (`loss_atlas.py:969`); layout builder (`guidance_extract.py:311`); C2 (`fill_toxicity_desk_study.py` input plan) | target ≤ 10-14 (whole folder) | host to fill |
| `forecast_payloads.jsonl` and/or `forecast_payloads_long.csv` | Layout builder NBM manifest rows (`guidance_extract.py:171-174`); C1/C3 (`maker_plugin_sources.py:411`) | target ≤ 10-14 (whole folder) | host to fill |
| `forecasts_long.csv` | C1/C3 support (`maker_plugin_sources.py:409`; lookback) | target ≤ 10-14 (whole folder) | host to fill |
| `snapshot_explanations.jsonl` | C1/C3 support (`maker_plugin_sources.py:410`) | target ≤ 10-14 (whole folder) | host to fill |
| `observation_payloads.jsonl` | C1/C3 support (`maker_plugin_sources.py:412`) | target ≤ 10-14 (whole folder) | host to fill |
| `settlement.json` (if present) | Row 80 and atlas label sidecar fallback (`settlement_io.py:439`, via `resolve_market_day_label`) | none; US11 targets 10-01..10-14 only, minus Austin 10-03 | host to fill |
| `clob_tokens.jsonl` or `clob_tokens.csv` | C1/C3 band tokens (`maker_plugin_sources.py:34`, `:218-226`) | none (token metadata) | host to fill |
| `forecast_payloads/sha256/<2>/<hash>.json` | C1/C3 legacy bulletins (`maker_plugin_sources.py:342`). Only hashes named by exported manifest rows. | file-level: only referenced hashes | host to fill |
| `order_books.jsonl` (gz variant), `order_books_summary.csv` (gz variant) | C2 (`fill_toxicity_desk_study.py:53-83` on `de76a4a9b67b25781c6c6f33b10691841e8630cc`) | target ≤ 10-14 (whole folder) | host to fill |
| `execution_tape/trades-NNNNN.jsonl`, `execution_tape/gaps-*.jsonl`, `execution_tape/status.json` | C2 (same input plan) | target ≤ 10-14 (whole folder) | host to fill |
| `reward_records.jsonl`, `rewards.jsonl`, `snapshots.jsonl` | C2 (same input plan) | target ≤ 10-14 (whole folder) | host to fill |

Market and target sets by consumer. The union is all 12 markets, targets 09-25..10-14, minus Austin 10-03.
- **Row 80 (C4):** US11, targets 10-01..10-14. It uses local hours 13-16, but export all hours of those folders:
  the layout builder needs the whole folder. No capture-time cut applies (master, 2026-10-31).
- **Atlas:** the same cells as row 80, read after it. Toronto 10-09..10-14 and all 12 markets for 09-30 also
  become readable (claim check §5).
- **C1:** all 12 markets, targets 09-28..10-14. Quote days are UTC 09-27..10-13 with leads 1..2, and 10-14 is a
  settlement-only day.
- **C2:** all 12 markets, event dates 09-25..10-08 (panel B, `fill_toxicity_desk_study.py:36-37`).
- **C3:** all 12 markets, targets 09-25..10-08 (prereg `t1-fair-value-preregistration-2026-09-25.md` @
  `4b1ef8a07`, lines 50-56).

### 4.2 Shared files

| Path | Needed by | Filter | Bytes |
| --- | --- | --- | --- |
| `settlements/<market>/ledger.jsonl`, 12 markets | Row 80/atlas labels (`dev_scorecard_data.py:56`, `DEFAULT_LABEL_SOURCE`); layout builder (`guidance_extract.py:465`); C1/C3 (`maker_plugin_sources.py:211`); C2 | Only rows for targets 09-25..10-14, minus Austin 10-03 (§2 label rule). A row-filtered copy, never the whole ledger. | host to fill |
| `snapshots/observation_triggers.jsonl` | C1/C3 (`maker_plugin_sources.py:185`); C2 | targets ≤ 10-14 (no capture-time cut); readers drop Austin 10-03 | host to fill |
| `forecast_payload_cas/<payload_ref>` | Layout builder NBM bulletins (`guidance_extract.py:215`); C1/C3 (`maker_plugin_sources.py:284`) | Only refs named by exported manifest rows, exported whole with no time cut (master's target-date ruling; late target-10-14 captures can name bulletins first seen on UTC 10-15) | host to fill |

### 4.3 88a sealed capture: `maker_evidence/<UTC day>/<HH>-<12 hex>/`

| Path | Needed by | Filter | Bytes |
| --- | --- | --- | --- |
| `manifest.json` plus every file it lists (`discovery.jsonl`, `books.jsonl`, `rewards.jsonl`, `reward-*`, `trades.jsonl`, `stream_lifecycle.jsonl`, `stream_gap.jsonl`; gz variants) | C1 (UTC 09-27..10-14); C2 (UTC 09-25..10-08); C3 (UTC 09-23..10-07, the T+1/T+2 quote days for targets 09-25..10-08) | Sealed segments only, where `manifest.json` exists (`maker_plugin_capture.py:264-279`). Copy segments whole and byte-identical: the readers verify sha256, size, offsets and record counts (`maker_plugin_capture.py:160-196`). | Repository records only estimates: about 60–90 MiB/day (`docs/roadmap/audits/wide-audit-2026-09-25.md:154`) and about 0.1 GB/day (`post-night-audit-2026-09-25.md:28`) before the pilot. `DEFAULT_STREAM_CAP` = 300,000,000 bytes/day (`maker_evidence_store.py:21`). Exact bytes: host to fill. |

Union of 88a days: **UTC 2026-09-23..2026-10-14**. Row 80 reads no 88a.

## 5. Open points for master (decide before the export)

1. **Austin 10-03 inside 88a.** Sealed segments are multi-market and hash-verified, so Austin 10-03 conditions
   cannot be removed from a segment without breaking its seal. There are two options:
   - (a) Export the segments whole, and require every C1–C3 reader to drop the Austin 10-03 event before reading
     any row. The bytes then reach the workstation.
   - (b) Run the host-side bundle projection with an Austin 10-03 drop, and export bundles instead of segments.
     That needs the export_gate edit in §1.2.

   C7 says "every kind", so (b) is the strict reading. **Ruled (master, 2026-10-31): the readers drop it**, which
   is option (a); `export_gate` stays unedited, so (b) is unavailable.
2. **C1's last quote days lose conditions.** Quote days UTC 10-13 and 10-14 carry lead-1/2 conditions for targets
   10-15/10-16, and the 10-15 settlement-only day is gone. Those conditions are dropped, not settled. The v2
   registration's panel was 09-30..10-13 quotes plus settlement days 10-14 and 10-15
   (`scripts/ops/maker_replay_exam_step.ps1:68-70`). C1 on this export is therefore a reduced panel.
3. **The atlas date guard.** `loss_atlas` runs on the dev scorecard's `DEV_LAST` = 2026-09-29 guard
   (`dev_scorecard_data.py:40`, refusal at `:137-150`). Both files are B-bound and read-only until 12-13. An atlas
   read of 10-01..10-14 needs either an in-process override like row 80's driver
   (`rep.py:227-235` sets `data.DEV_LAST`) or a ruling. Do not edit the files.
   Settled in [atlas-readiness-0930-1014.md](atlas-readiness-0930-1014.md): an override alone would fail the
   atlas positive control, so a new wrapper module is proposed. The layout builder needs one too; see
   [row80-look-runbook.md](row80-look-runbook.md) §3. Both modules are on `claude/released-window-tools-20261031`.
4. **The label recorded-time question** in §2. Ruled: a 10-14 label recorded on UTC 10-15 is released.
5. **The rule-6 order also binds C2 and C3.** C2 and C3 read US11 labels for targets 10-01..10-08, which are row 80
   cells, so they wait for row 80's receipt as well.
6. **A second date guard.** `src/weather/market/maker_counterfactual_tape.py:94-95, :138, :160` keeps its own
   `RESERVED_FIRST..RESERVED_LAST` = 09-30..10-15 guard. Any consumer that goes through it still refuses. It is
   not part of C1–C3 as traced and is not edited here.
7. **The tape-sha binding (settled by the target-date ruling).** A ledger row that records
   `snapshot_tape_sha256` is honoured only when the folder's `snapshots_long.csv` still has that sha
   (`settlement_io.py:373-387`). With no capture-time cut, target 10-14 folders are exported whole and their
   tapes keep their sha, so the 10-14 labels survive. If any exported tape still differs from its ledger sha,
   that market-day fails as `folder_error` in the extract (`guidance_extract.py:483-488`) and is dropped, not
   replaced. Master's export receipt names the ledgers that carry `snapshot_tape_sha256`.
8. **The guidance extract runs on the workstation, not through the host wrapper.**
   `scripts/ops/guidance_extract_run.ps1:97` always passes the production `data` root. The extract module
   (`weather.reporting.research.guidance_extract`) runs on the staged export with `--data-root` and
   `--from 2026-10-01 --to 2026-10-14`. It is existing packaged code and needs no allowlist entry (master); it runs
   under `workstation_heavy.ps1` if it is heavy. It also needs a clean parser worktree at `2e17ce0eb`.

## 6. Delivery and receipts

- **One receipt for the whole export.** For each exported file, record:
  - its source path, its exported path, sha256, bytes and row count;
  - the filter it went through ("whole", "target filter", "ledger target filter", "referenced-only");
  - the rows dropped by each rule (C5 target ≥ 10-15, C7 Austin 10-03 where it is dropped at export).
- **The row 80 subset gets its own sub-manifest and sha.** It is US11 slug folders for targets 10-01..10-14 plus
  the filtered US11 ledgers.
  - The row 80 driver builds its HARNESS v3 layout (`harness_v3_layout/1`, 10-01..10-14 only) from that subset
    first, and records the look.
  - Only after that receipt may the atlas, C1, C2 or C3 open US11 snapshots or labels for 10-01..10-14.
- **Nothing from the export is merged into an existing layout.** Every added date goes into a separate layout
  (claim check §3.3).
- **Absence is recorded, not filled.** If a listed file is missing on the host, write that in the receipt. Do not
  substitute another file.

# Export 2 sub-manifest: C1–C3 and atlas extras (draft, ready to send)

Status: draft by lane L8, 2026-10-31. Not sent. It is sent to the host **only after row 80's look receipt
exists** (export manifest §6, and §5 point 5: C2 and C3 read row 80 cells). Parent:
[export-manifest-0930-1014.md](export-manifest-0930-1014.md) §2 (date rule) and §4.1–4.3 (files). This file
lists only what export 1 (the row 80 sub-export) did not deliver. Every rule of the parent applies unchanged.

## 0. What export 1 already delivered (not repeated)

- US11 slug folders for targets 10-01..10-14, minus Austin 10-03, with `snapshots_long`, `features_long`,
  `replay_inputs`, `forecast_payloads(_long)` and `settlement.json`.
- 11 US11 target-09-30 lookback folders, holding forecast manifests only.
- The 75 `forecast_payload_cas` bulletins those manifests reference, with no time cut.
- 11 US11 ledgers, filtered by `event_slug` to targets 10-01..10-14 minus Austin 10-03, with each slug's whole
  revision history.

If the workstation already holds a byte-identical file (same sha256), the host skips it and the receipt says so.

## 1. Scope rules (from the parent, restated for the host)

- Markets: all 12 (US11 plus toronto). Local targets **2026-09-25..2026-10-14**. Nothing with a target of 10-15
  or later, whatever its capture time (C5). No capture-time cut.
- Austin 10-03: no slug folder and no ledger rows (C7). Inside 88a segments it stays, because segments are
  exported whole and the readers drop it (master, ruling (a)).
- 88a: UTC days **2026-09-23..2026-10-14** only. No `maker_evidence/2026-10-15/` and nothing later.
- Days before 09-30 are not newly released. They are calibration and lookback for C1–C3, under the same
  exclusions.
- The C2/C3 pre-read guard (`tools/research/released_window/c23_preread_guard.py`, branch
  `claude/c23-preread-guard-20261031`) runs over the staged copy before either reader. It refuses any day or
  target of 10-15 or later and any Austin 10-03 folder or ledger row.

## 2. Slug folders: `snapshots/<slug>/`

| Set | Markets | Targets | Files | Consumer |
| --- | --- | --- | --- | --- |
| A. Toronto | toronto | 09-25..10-14 | whole folder: every file in parent §4.1 that exists | atlas (Toronto 10-09..10-14), C1 (09-28..10-14), C2 and C3 (09-25..10-08) |
| B. The 12 markets on 09-30 | US11 + toronto | 09-30 | whole folder. For US11 this completes the manifest-only lookback folders of export 1 | atlas (all 12 on 09-30), C1, C2, C3 |
| C. Pre-window calibration | US11 + toronto | 09-25..09-29 | whole folder | C1 (09-28..09-29), C2 and C3 (09-25..09-29) |
| D. Completing export 1 | US11 minus Austin 10-03 | 10-01..10-14 | only the files export 1 did not carry: `forecasts_long.csv`, `snapshot_explanations.jsonl`, `observation_payloads.jsonl`, `clob_tokens.jsonl`/`.csv`, `forecast_payloads/sha256/<2>/<hash>.json` (referenced hashes only), `order_books.jsonl` and `order_books_summary.csv`, `execution_tape/trades-NNNNN.jsonl`, `execution_tape/gaps-*.jsonl`, `execution_tape/status.json`, `reward_records.jsonl`, `rewards.jsonl`, `snapshots.jsonl` (gz variants as found) | C1/C3 support, C2 |

- The gz variant rule follows the parent: export whichever exists and record which one.
- Set A's 10-14 folder and set D's 10-14 files are exported whole, including rows captured on UTC 10-15.

## 3. Shared files

| Path | Filter | Consumer |
| --- | --- | --- |
| `settlements/<market>/ledger.jsonl`, all 12 markets | by `event_slug`, keeping each slug's whole revision history, for targets 09-25..10-14 minus Austin 10-03. For US11 only the slugs export 1 did not carry (09-25..09-30). For toronto, 09-25..10-14 | C1/C3 (`maker_plugin_sources.py:211`), C2, atlas |
| `snapshots/observation_triggers.jsonl` | rows with target ≤ 10-14 (no capture-time cut); readers drop Austin 10-03 | C1/C3 (`maker_plugin_sources.py:185`), C2 |
| `forecast_payload_cas/<payload_ref>` | refs named by manifests in sets A–C not already exported, whole, with no time cut | C1/C3 (`maker_plugin_sources.py:284`) |

## 4. 88a sealed capture: `maker_evidence/<UTC day>/<HH>-<12 hex>/`

- UTC days 09-23..10-14. This is the union of C1 (09-27..10-14), C2 (09-25..10-08) and C3 (09-23..10-07).
- Sealed segments only (a `manifest.json` exists), copied whole and byte-identical with every file the manifest
  lists (parent §4.3).
- No `maker_evidence/2026-10-15/` or later. The pre-read guard refuses one.

## 5. Not in export 2

- Any slug folder, ledger row, 88a day or CAS ref selected only by a 10-15 or later target or day (C5).
- Austin 10-03 slug folder and ledger rows (C7).
- MG-2/B outputs and the C5 OUTCOME window 10-15..11-13.
- Bundles. `export_gate` stays unedited, so the export carries raw host files only (parent §1.2).

## 6. Receipt

- One receipt for export 2, in the shape of parent §6: source path, exported path, sha256, bytes, row count,
  filter ("whole", "target filter", "ledger slug filter", "referenced-only"), and rows dropped by each rule.
- Also record:
  - the set (A–D, shared, 88a) of each file;
  - every file skipped as byte-identical to one already on the workstation;
  - the row 80 look receipt sha this export waited for.
- Absence is recorded, not filled.

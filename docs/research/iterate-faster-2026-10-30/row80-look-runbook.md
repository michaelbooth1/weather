# Runbook: the row 80 look on 10-01..10-14 (draft)

Status: DRAFT, lane L8, 2026-10-31. This is research evidence, not a canonical document. It was written from code
only; no data was read.

- **What it runs.** It executes the frozen rule `docs/research/forecast-tracking-2026-10-30/rule_rise_t3r3_replication.md`
  (DEV_WINDOW_LEDGER row 80, branch `claude/ledger-80-rise-replication-20261030` @
  `1a1616c7c5e611b09b0e009293dd75c200b4bd46`), on path 1, the owner's Q3 = yes.
- **Where its inputs come from.** The host export is described in
  [export-manifest-0930-1014.md](export-manifest-0930-1014.md).

**This look is the FIRST read of US11 snapshots and labels for 10-01..10-14 (rule 9; claim check C4).** Nothing
in this runbook before step 4 computes a score, a Brier value, a ratio or any label-versus-forecast comparison.
The atlas, C1, C2, C3 and every kill-only screen open these cells only after step 4's `receipt.json` exists.

## 0. Frozen pieces (check by sha before anything runs)

| Piece | Where | sha256 |
| --- | --- | --- |
| Driver `rep.py` (frozen with the rule) | `C:\t\l8ftr\rep.py` | `e85732d1726fba9b52d1d1d8fa1e9b0dda8b0f92f2c2eb6da55fe450a14a0a8e` |
| Row 79 driver `ftr.py` (rep refuses any other) | `C:\t\l8ftr\ftr.py` | `ab8ced550699d74d734fcd73cfde152e46922ab0983d5228e92086425abaaeaf` |
| t3-r3 table, months 8-12 (label-free; already built) | `C:\t\l8ftr\out_rep\t3_table_m8_12.json` | `1080145c4d4ba454fe83a2f3cb6ded9844c28bd5eefe898659b89056f84ebe8a` |
| Run env (sys.path from ftr; the statistic is `mr_sweep.p0_candidate`) | `C:\wt\l3loyoenv`, clean | HEAD `8bb0f9563582885c4d01d34b67476f2563260e43` |
| Interpreter used for t3ext and devcheck | `C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe` (`-I`) | — |
| Layout builder code (HARNESS v3) | `claude/harness-v3-20261019` @ `2f3f3e8e6b542a419204afe802dae4545abc10d7` | `harness_sha256` must equal the rule's `8db69adc…9f74` |
| Guidance extract | `src/weather/reporting/research/guidance_extract.py` on master `1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de` | record at run time |
| NBM parser worktree (extract `--parser-worktree`) | a clean detached worktree at `2e17ce0eb` (`harness.PARSER_HEAD`) | record its HEAD |

`C:\t\l8ftr\out_rep\look\` must not exist. `rep.py` refuses a second look (`rep.py:223-224`).

## 1. Inputs from the host export (row 80 sub-manifest)

Only the row 80 subset is needed: US11 (nyc, atlanta, austin, chicago, dallas, denver, houston, los-angeles,
miami, san-francisco, seattle), local targets 2026-10-01..2026-10-14, and Austin 10-03 excluded. All hours are
included, with the capture cut (rows captured at or after 2026-10-15T00:00Z dropped).

| Exported path (relative to the export data root) | Read by |
| --- | --- |
| `snapshots/<slug>/snapshots_long.csv` | extract (`guidance_extract.py:421`) |
| `snapshots/<slug>/features_long.csv` | extract (`:430`) |
| `snapshots/<slug>/replay_inputs.jsonl` | extract (`:311`) and `rep.py:119` (the METAR receipt rows) |
| `snapshots/<slug>/forecast_payloads.jsonl` and/or `forecast_payloads_long.csv` | extract NBM manifest rows (`:171-174`) |
| `snapshots/<slug>/settlement.json` (if present) | label sidecar fallback (`settlement_io.py:439`) |
| `settlements/<market>/ledger.jsonl`, US11, rows for targets 10-01..10-14 only, minus Austin 10-03 | labels (`guidance_extract.py:465`, `settlement_io.resolve_market_day_label`) |
| `forecast_payload_cas/<payload_ref>`, refs named by the exported manifest rows only | NBM bulletins (`:215`) |

Stage the export at a fresh workstation path whose name contains neither `88a` nor `panel`, for example
`C:\t\r80\data`. Verify every file against the sub-manifest sha256 before step 2, and write
`C:\t\r80\import_receipt.json` with the sub-manifest sha and any missing file. A missing file is recorded, never
substituted.

**Known loss: target 10-14 labels.** A ledger row that records `snapshot_tape_sha256` is honoured only when the
folder's `snapshots_long.csv` still has that sha (`settlement_io.py:373-387`). The capture cut rewrites the 10-14
tapes, because US evening hours fall on UTC 10-15. Those market-days then fail as `folder_error` in the extract
(`guidance_extract.py:483-488`) and are dropped. The rule allows this: "Dates without labels or layout rows are
dropped, not replaced" (rule §4). The look stays testable if at least 10 dates and 1,000 snapshots remain. The
host receipt should state which ledgers carry `snapshot_tape_sha256`.

## 2. Guidance extract on the staged copy (workstation)

Do not use `guidance_extract_run.ps1`. It reads the live production data root (`:97`), which would include the
UTC 10-15 rows (C5).

```text
python -m weather.reporting.research.guidance_extract --data-root C:\t\r80\data --out C:\t\r80\extract ^
  --from 2026-10-01 --to 2026-10-14 --parser-worktree <clean 2e17ce0eb worktree>
```

- **Run it from master's tree.** It writes `guidance_rows.jsonl.gz`, `market_days.jsonl.gz`, `manifest.json` and
  `SHA256SUMS`. Its status must be `COMPLETE`.
- **It is not on the `weather_heavy` allowlist** (`scripts/ops/workload_admission.ps1`, the offline module list).
  Admission therefore needs either master's allowlist entry and `workstation_heavy.ps1 -Kind weather_heavy
  -Queue -MinAvailableMemoryGB 3`, or a coordinator ruling that it is light.
- **It computes no score.** It writes the settled label into each row, which is plumbing and not a look.

## 3. Build the HARNESS v3 layout (10-01..10-14 only)

The dev builder refuses every date after 09-29. The refusals are at `harness.py:46` (`LAST_TARGET_DATE`), `:195`,
`:289` and `:572`, and at `v3_outcomes.py:28` and `:71-72`. `rep.py` is frozen and cannot carry a builder
override. The B-bound dev scorecard files must not be edited. A **new wrapper module** is therefore needed. It
needs the coordinator's allowlist check.

**Proposed: `tools/research/released_window/r80_layout.py`.** It does not exist yet. It runs from a clean
worktree of `2f3f3e8e6b542a419204afe802dae4545abc10d7`. It does only this:

1. It refuses unless the extract is `COMPLETE` and `harness.verify_extract` passes.
2. It refuses unless every extract target date is within 10-01..10-14 and every market is in US11, with no Austin
   10-03 row and no `captured_at_utc` at or after 2026-10-15T00:00Z.
3. In-process only, it sets `harness.LAST_TARGET_DATE = "2026-10-14"` and `v3_outcomes.DEV_LAST_DATE = "2026-10-14"`.
   Both are module globals that are read at call time; no file is edited.
4. It calls `harness.build_cache(root=C:\t\r80\extract, cache=C:\t\r80\cache)`. It never uses the default
   `C:\swarm\cache` (the dev cache) and never `force`.
5. It calls `v3_outcomes.split_v2_cache(C:\t\r80\layout, cache=C:\t\r80\cache)`.
6. It asserts that the manifest's `source.harness_sha256` equals the rule's `8db69adc…9f74`, and that every file's
   `dates` list is within 10-01..10-14.
7. It writes `C:\t\r80\layout_receipt.json` holding the extract sha, cache receipt, layout manifest sha and the
   overrides used. It prints no score.

It does not touch B's control layout (manifest `4d53fdbdc551…`), `C:\swarm\v3layout` or any default fold.

## 4. The look (once)

```text
cd C:\t\l8ftr
C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe -I rep.py look ^
  --layout C:\t\r80\layout --replay C:\t\r80\data --approval "<DECISION_LOG row of the owner's 2026-10-30 release>"
```

- `--path` defaults to `q3`, and the forward path is refused (`rep.py:219-221`).
- `--replay` is the staged data root, because `rep.py:119` reads `<replay>/snapshots/<slug>/replay_inputs.jsonl`.
- The approval text is master's DL reference. `rep.py:217-218` refuses anything shorter than 8 characters.
- **Admission.** The look reads 14 dates at hours 13-16. The devcheck and t3ext stages ran directly as light
  scripts. The coordinator decides whether the look is light (sha recorded) or goes through the queue.
  `rep.py` is a script, not an allowlisted `-m` module.

Guards inside `rep.py` (frozen; nothing to set by hand):

- `check_ftr()` checks ftr's sha.
- The DEV_LAST override is `rep.py:232-235`: `data.DEV_LAST = date(2026, 10, 14)` in-process, set only to the
  registered last date. Every dev scorecard guard reads that global at call time (`dev_scorecard_data.py:88`,
  `:141`, `:158` at the pin). `WU_LABEL_RULE_LAST` 2026-10-22 still applies.
- It refuses a layout that holds a date outside 10-01..10-14 (`:237-238`).
- The hours are 13-16 (`ftr.HOURS`). The testability floor is 10 dates and 1,000 snapshots (`:247`).
- The statistic is `mr_sweep.p0_candidate`, one-sided at α 0.05. The verdict is REPLICATED, NOT REPLICATED or
  UNTESTABLE.

## 5. Receipts and archive

- **What `rep.py` writes.** `C:\t\l8ftr\out_rep\look\rows.jsonl` and `receipt.json`. The receipt holds the ledger
  row, the approval, the path, the run-env HEAD, the rep, ftr and t3 shas, the layout manifest sha, the registered
  and scored dates, malformed replay lines, the full result and the verdict. It prints the receipt sha.
- **What to report.** Report it together with `import_receipt.json`, the extract `SHA256SUMS` and
  `layout_receipt.json`.
- **Owner rule.** If the verdict rules RISE-T3R3 out (NOT REPLICATED or UNTESTABLE), copy the rule (prereg), the
  rep, ftr and builder shas, `out_rep/look/`, the three receipts and the logs to
  `C:\archive\ruled-out\row-80-rise-t3r3-replication\`. Never delete them.
- **Under rule 10, a PASS is a screen, never an edge claim.**

## 6. What needs the host export

- Only the row 80 sub-manifest in §1. Row 80 reads no 88a, no order books and nothing for Toronto.
- The parser worktree and all code are on the workstation already, or come from git.

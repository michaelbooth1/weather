# Runbook: the row 80 look on 10-01..10-14 (draft)

Status: DRAFT, lane L8, 2026-10-31. This is research evidence, not a canonical document. It was written from code
only; no data was read.

- **What it runs.** It executes the frozen rule `docs/research/forecast-tracking-2026-10-30/rule_rise_t3r3_replication.md`
  (DEV_WINDOW_LEDGER row 80, branch `claude/ledger-80-rise-replication-20261030` @
  `1a1616c7c5e611b09b0e009293dd75c200b4bd46`), on path 1, the owner's Q3 = yes.
- **Where its inputs come from.** The host export is described in
  [export-manifest-0930-1014.md](export-manifest-0930-1014.md).

**Master's rulings, 2026-10-31:**

- **The boundary is the local target date.** A target of 10-14 or earlier is released, including a 10-14 label
  recorded on UTC 10-15. A target of 10-15 or later stays embargoed whatever its capture time (C5).
- **The embargo edit `0f9929736` does not land.** Row 80 does not need it.
- **Admission.** The guidance extract is existing packaged code and needs no allowlist entry. It runs under
  `workstation_heavy.ps1` if it is heavy. The look takes a heavy slot through the queue.
- **The `--approval` string** is `owner 2026-10-30 release of 2026-09-30..10-14 (DECISION_LOG 2026-10-30 row, origin/master 5f4d87818)`, as issued
  by master once the owner decision rows landed on origin/master 5f4d87818.
- **Austin 10-03 is dropped by the readers.**
- **The export.** Master runs the row 80 sub-manifest export, with a size precheck.

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
| Layout wrapper `r80_layout.py` | `claude/released-window-tools-20261031` @ `25c8d3a3517e64a4fa906c41ce9e5ed2ee9a0a82` | `31750c1c254b87fb0868c29e272ff8af7e5f2a2109d256c68b201e5a692017f2` |
| Guidance extract | `src/weather/reporting/research/guidance_extract.py` on master `1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de` | record at run time |
| NBM parser worktree (extract `--parser-worktree`) | a clean detached worktree at `2e17ce0eb` (`harness.PARSER_HEAD`) | record its HEAD |

`C:\t\l8ftr\out_rep\look\` must not exist. `rep.py` refuses a second look (`rep.py:223-224`).

## 1. Inputs from the host export (row 80 sub-manifest)

Only the row 80 subset is needed: US11 (nyc, atlanta, austin, chicago, dallas, denver, houston, los-angeles,
miami, san-francisco, seattle), local targets 2026-10-01..2026-10-14, and Austin 10-03 excluded. Folders are
exported whole, with all hours. There is no capture-time cut: target-10-14 rows captured on UTC 10-15 are
released. By C5 the export holds no 10-15 folder, so the extract's bulletin index, which reads manifests for
targets `--from` - 1 day through `--to` + 1 day (`guidance_extract.py:192`), sees no 10-15 manifests: bulletins
listed only there are missing and some first-seen times can be later, so v2 guidance for the latest 10-14
captures can differ from an extract over the full data root.

| Exported path (relative to the export data root) | Read by |
| --- | --- |
| `snapshots/<slug>/snapshots_long.csv` | extract (`guidance_extract.py:421`) |
| `snapshots/<slug>/features_long.csv` | extract (`:430`) |
| `snapshots/<slug>/replay_inputs.jsonl` | extract (`:311`) and `rep.py:119` (the METAR receipt rows) |
| `snapshots/<slug>/forecast_payloads.jsonl` and/or `forecast_payloads_long.csv` | extract NBM manifest rows (`:171-174`) |
| `snapshots/<slug>/settlement.json` (if present) | label sidecar fallback (`settlement_io.py:439`) |
| `settlements/<market>/ledger.jsonl`, US11, rows for targets 10-01..10-14 only, minus Austin 10-03 | labels (`guidance_extract.py:465`, `settlement_io.resolve_market_day_label`) |
| `snapshots/<slug>/forecast_payloads.jsonl` and/or `forecast_payloads_long.csv` for the 11 US11 target-09-30 lookback folders (manifests only; no tape, ledger rows or sidecar) | extract bulletin index only (`:192`, `--from` - 1 day); never a market-day, since the extraction loop covers `--from`..`--to` only (`:482`) |
| `forecast_payload_cas/<payload_ref>`, refs named by the exported manifest rows, exported whole with no time cut | NBM bulletins (`:215`) |

Stage the export at a fresh workstation path whose name contains neither `88a` nor `panel`, for example
`C:\t\r80\data`. Verify every file against the sub-manifest sha256 before step 2, and write
`C:\t\r80\import_receipt.json` with the sub-manifest sha and any missing file. A missing file is recorded, never
substituted.

**Record the C5 gap.** `import_receipt.json`, and the look receipt after it, record the note
`10-15 manifests absent by C5; extract not identical to a full-root extract` (see the C5 sentence above).

**The staging reader drops Austin 10-03.** If the export holds the Austin 10-03 folder or ledger row, leave it
out of `C:\t\r80\data` and record that in `import_receipt.json`. `r80_layout.py` refuses an extract that still
holds it.

**Tape-sha binding.** A ledger row that records `snapshot_tape_sha256` is honoured only when the folder's
`snapshots_long.csv` still has that sha (`settlement_io.py:373-387`). Under the target-date ruling, folders are
exported whole, so the tapes keep their sha. Any market-day whose tape still differs fails as `folder_error` in
the extract (`guidance_extract.py:483-488`) and is dropped, not replaced (rule §4). The look stays testable if at
least 10 dates and 1,000 snapshots remain. Master's export receipt names the ledgers that carry
`snapshot_tape_sha256`.

## 2. Guidance extract on the staged copy (workstation)

Do not use `guidance_extract_run.ps1`. It always reads the production data root (`:97`), not the staged export.
The extract's `--from` and `--to` keep it to targets 10-01..10-14.

```text
python -m weather.reporting.research.guidance_extract --data-root C:\t\r80\data --out C:\t\r80\extract ^
  --from 2026-10-01 --to 2026-10-14 --parser-worktree <clean 2e17ce0eb worktree>
```

- **Run it from master's tree.** It writes `guidance_rows.jsonl.gz`, `market_days.jsonl.gz`, `manifest.json` and
  `SHA256SUMS`. Its status must be `COMPLETE`.
- **Admission (master, 2026-10-31).** It is existing packaged code and needs no allowlist entry. If it is heavy, it
  runs under `workstation_heavy.ps1 -Queue -MinAvailableMemoryGB 3`, with the coordinator's admission.
- **It computes no score.** It writes the settled label into each row, which is plumbing and not a look.

## 3. Build the HARNESS v3 layout (10-01..10-14 only)

The dev builder refuses every date after 09-29. The refusals are at `harness.py:46` (`LAST_TARGET_DATE`), `:195`,
`:289` and `:572`, and at `v3_outcomes.py:28` and `:71-72`. `rep.py` is frozen and cannot carry a builder
override. The B-bound dev scorecard files must not be edited. A **new wrapper module** is therefore needed.

**`tools/research/released_window/r80_layout.py`** is on `claude/released-window-tools-20261031` @
`25c8d3a3517e64a4fa906c41ce9e5ed2ee9a0a82` (module bytes unchanged at the branch tip
`d155a665a53fe39a261e5b7aa55683a8ba2defe9`). It imports the harness from a clean worktree of
`2f3f3e8e6b542a419204afe802dae4545abc10d7`. Run it as a script with an isolated interpreter, never with `-m`.

**Admission (master, 2026-10-31): option (a), a direct run by path.** `workstation_heavy.ps1` admits only `-m`
modules, and this file cannot run as one, so it gets no allowlist line and no launcher. Before the run, compute the
file's sha256 and refuse to run unless it equals
`31750c1c254b87fb0868c29e272ff8af7e5f2a2109d256c68b201e5a692017f2` (step 0 table). Record that sha in
`import_receipt.json`; `layout_receipt.json` records it again as `module_sha256`, and the two must match.

**Receipt pins (master, 2026-10-31).** `ROW80_RECEIPT_SHA256` =
`6c0f4a1d4b5e5e12445fc79203b2c6ab66dbe1e0e21e7451ac1e6cb3bbc54504`; `SHA256SUMS` =
`c0246a6593655da04b7e600385174e5a1d1cd5b36217896cde13c7cceceb73fa`. Both are verified before step 2, and a
mismatch stops the run.

```text
python -I tools\research\released_window\r80_layout.py --harness-worktree <clean 2f3f3e8e worktree> ^
  --extract C:\t\r80\extract --out C:\t\r80\build
```

It does only this:

1. It refuses unless the harness worktree is a clean checkout of the pin, `harness_sha256` equals the rule's
   `8db69adc…9f74`, and `PARSER_HEAD` is `2e17ce0eb`.
2. It refuses any path naming `88a` or `panel`, any `--out` under `C:\swarm`, and a `--out` that is not new or
   empty.
3. It refuses unless the extract is `COMPLETE` and `harness.verify_extract` passes.
4. It refuses unless every extract target date is within 10-01..10-14 and every market is in US11, with no
   Austin 10-03 row. A target of 10-15 or later is refused whatever its capture time; capture time is not
   checked.
5. In-process only, it sets `harness.LAST_TARGET_DATE` and `v3_outcomes.DEV_LAST_DATE` to `"2026-10-14"`. It
   restores both afterwards. Both are module globals that are read at call time; no file is edited.
6. It calls `harness.build_cache(root=<extract>, cache=<out>\cache)`, never with `force`, and then
   `v3_outcomes.split_v2_cache(<out>\layout, cache=<out>\cache)`.
7. It asserts that the manifest's `source.harness_sha256` equals the rule's value, and that every file's `dates`
   list is within 10-01..10-14.
8. It writes `<out>\layout_receipt.json` holding the extract verification, cache receipt sha, layout manifest
   sha and the overrides used. It prints no score.

It does not touch B's control layout (manifest `4d53fdbdc551…`), `C:\swarm\v3layout` or any default fold.

## 4. The look (once)

```text
cd C:\t\l8ftr
C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe -I rep.py look ^
  --layout C:\t\r80\build\layout --replay C:\t\r80\data ^
  --approval "owner 2026-10-30 release of 2026-09-30..10-14 (DECISION_LOG 2026-10-30 row, origin/master 5f4d87818)"
```

- `--path` defaults to `q3`, and the forward path is refused (`rep.py:219-221`).
- `--replay` is the staged data root, because `rep.py:119` reads `<replay>/snapshots/<slug>/replay_inputs.jsonl`.
- Use the approval text above, or the exact DECISION_LOG row text if master has sent it by then.
  `rep.py:217-218` refuses anything shorter than 8 characters.
- **Admission (master, 2026-10-31).** The look takes a heavy slot through the queue, with the coordinator's
  admission.

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

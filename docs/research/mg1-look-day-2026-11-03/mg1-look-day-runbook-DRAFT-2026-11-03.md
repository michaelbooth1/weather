# MG-1 look-day runbook, 2026-11-03 (DRAFT)

- **Status: DRAFT by lane L16, 2026-11-03, for master review.** It is not in force, not signed and not an owner
  decision. It is the MG-1 counterpart of B-1 Clarification 6 (the B look chain), and it is due to master before
  2026-11-25. It is not a `b1-clarification-*` file, so R14's record globs do not freeze it.
- **Placeholders:** every `<PIN: …>` is a sha256 that §2 lists and master fills. Every `<…>` path or date is
  master's to fill on the day. **MISSING** marks a flag, command or producer that does not exist in the code on
  the named branches. Nothing here invents one.
- **Code read** (commands, flags and refusals are quoted from these trees, cited as `file:line`):

  | Short name | Branch | Tip |
  | --- | --- | --- |
  | look | `claude/mg1-look-scoring-r11-20261103` | `8c307dbb8e272cec4b8b30c6dd4251d2f6e4a576` (WIP) |
  | countable | `claude/mg1-countable-head2-r11-20261103` | `f118e0d8072dae85fc30b70a32bcdb0d54f1ce3e` |
  | R24 base (combo C) | `claude/r24-venue-label-audit-20261101` | `513475d31584dccb6222edec9eee31630aa8a761` |
  | freeze-keys | `claude/r24-freeze-keys-20261103` | `a1676b09f5db89dda5f02a4da083d0b1352f36e4` (parent: the R24 base) |

  `mg1_look.py` lines are on look, `mg1_countable.py` lines on countable, and `venue_label_audit.py` lines on
  freeze-keys.
- **Rulings cited:**
  - Master rulings 2026-11-01 (R11, R24, C9, C10, C14): WS copy `C:\t\rulings-20261101\rulings.md`, sha256
    `2499b5afec7a258378da9235689b594ae72a7c9f627d79c3b8c64ad489e2b44d`, cited as "rulings:<line>".
  - Master rulings 2026-11-03 (A1-A14, T1-T5): host file `C:\tmp\agent-kit\rulings-20261103-mg1-b.md`, sha256
    `28c4f298c9d128189468ab62562ebb79e055a6c42328315c8182178642b01906`. It is quoted from the WS coordinator's
    verbatim condensed copy `C:\t\mg1-b-rulings-20261103\rulings_condensed.md`, sha256
    `f1ded718b1fc8e7fc5598b59b12f6557276abfd2b341accaa7d51ff44cbad016`, and cited as "11-03:<line>".
  - Master's 2026-11-03 messages, cited by ruling name:
    - Q1: `skipped_dates` means T2; a market-day in neither list, or any inconsistency, holds.
    - Q2: the `label_dates` key list.
    - Q3: `A1_MIN_NEGATIVE_MARKETS`.
    - B2: the pin timetable (mg1_look 11-12/13).
    - "Unexplained absence holds".
- **History only:** nothing in this draft comes from an outcome, label, price, settlement, ledger or panel value.
  It cites code and rulings only.

## 0. Rules for every step

- **Host and checkout.** Every step runs on the capture host, from the production root. The look's start marker
  and receipt live at the fixed `data/mg1_look/` path of the checkout that runs it (`mg1_look.py:11-22`, `:72`).
  B's VOID 5 compares those bytes (`receipt_problems`, `mg1_look.py:195-227`).
- **Lease and window.** Run each step 00:30-09:00 under `Enter-WeatherHeavyWorkloadLease`, and refuse on
  `$null`. Keep clear of the 04:15, 06:50 and 07:00 tasks, the sequencer suites and Stage A (rulings:241 R24 (1);
  `docs/operations/HOST_LOAD_POLICY.md` "An agent's one-off wrapper"). Steps run serially, one at a time (C14,
  rulings:705).
  - **MISSING:** a repository-owned lease wrapper for these modules. None of `mg1_countable`, `mg1_look` or
    `venue_label_audit` is named in `scripts/ops/workload_admission.ps1` on any of the four trees. Master runs
    them through the one-off pattern of the host load policy.
- **Embargo.** Before the look, master reads only stdout, receipts, manifests and the counts-only audit. It never
  reads a CSV, a METAR file or a label value (R24 (2), rulings:240). After the look, the result file is read only
  as §1 step 7 says.
- **Logging.** Every step's full stdout and stderr, its exit code, `Get-Date -Format o` before and after, and the
  sha256 of every file it wrote go into master's look log. The log's path is not fixed by any code (**MISSING**:
  look-log path).
- **Command form.** One bare line per command. Every module runs as `.\venv\Scripts\python.exe -m <module>`.
  The look must run exactly as `python -m weather.calibration.mg1_look`, because only that `__main__` name at the
  registered bytes can stamp (`mg1_look.py:150-162`; `mg1_reserved_window.registered_confirmation_entry`).

## 1. Sequence (closed list)

Step R comes first, then steps 1 to 7 in this order, each once, except the conditional step 2a. The C14 ruling
fixes the look morning (rulings:705): "the MG-1 look is on or after 11-30. That morning runs serially under the
lease: P3 --final, then freeze --look mg1 (which includes the refresh), then the look."

### Step R. Owner-constant record (before step 3 and before the mg1_look pin)

The owner's open questions are one constant each in `mg1_look.py` (11-03:8; `mg1_look.py:237-247`). Each answer
is a one-line change, recorded in a dated note before the look (`mg1_look.py:237-239`). Master carries these
questions with the owner; they are not asked in the WS chat (11-03:8).

| Constant | Line | Branches built (`OWNER_CHOICES`, `:247-248`) | Value in force at 8c307dbb8 | Owner answer |
| --- | --- | --- | --- | --- |
| `A1_DENVER_SCORED` (A1) | `:240` | `True`, `False` | `True` | owner question, open |
| `A1_MIN_NEGATIVE_MARKETS` (A1, Q3) | `:243` | `1` to `len(MARKETS)` | `8` | owner question, open |
| `A5_BAR` (A5) | `:242` | `"as_written"`, `"magnitude"` | `"as_written"` | owner question, open |
| `A12_FALSIFIER_4` (A12) | `:245` | `"point"`, `"interval"` | `"point"` | owner question, open |

This draft proposes no answer. The record step is:

1. Master records each owner answer, verbatim and dated, in DECISION_LOG and in the dated note.
2. The one-line edit of each changed constant lands in `mg1_look.py`.
3. Then the entry pin is re-registered at the new bytes (`MG1_CONFIRMATION_ENTRY_POINTS`), and the final
   `mg1_look` sha goes into §2.

The code forces this order:

- **Before P3.** `support_markets()` reads `A1_DENVER_SCORED` (`mg1_look.py:307-310`). `mg1_countable` takes its
  support set from it (`mg1_countable.py:79-83`). At the look, `_parse_countable` refuses a list whose per-date
  `markets` keys are not exactly the support set in force (`mg1_look.py:329-331`). So A1 must be fixed before step
  3 writes the final list. P1 and P2 (steps 1 and 2) run under the value then in force and are report-only.
- **Before the pin.** Any constant edit changes the `mg1_look.py` bytes. Every caller is then refused until the
  entry sha is re-registered, and the edited look is refused too (`mg1_reserved_window.py:39-43` on look). C10
  (rulings:701) rules that no `mg1_look.py` edit may follow the S1 commit, or B's VOID 5 trips. Under the B2
  timetable, the mg1_look pin is 11-12/13 and S1 is 11-22..25. **An owner answer that arrives after the pin
  means a re-pin before S1.** After S1, it would be a master ruling.
- **Refusal.** `owner_constants()` refuses any value outside the built branches, and any
  `A1_MIN_NEGATIVE_MARKETS` above the scored-market count (`mg1_look.py:291-304`), when `score` starts
  (`:953`).
  - **Master's action:** fix the constant by a reviewed edit and re-pin. Nothing is consumed.
- **Logged:** the four values in force are written into the result as `owner_constants` (`mg1_look.py:979-980`).

### Step 1. P1 countability report, 2026-11-14

```powershell
.\venv\Scripts\python.exe -m weather.calibration.mg1_countable --ledger-root <SETTLEMENTS_ROOT>
```

- **Flags:**
  - `--ledger-root` is required (`mg1_countable.py:250`).
  - Report mode is the default, with no `--final` (`:251`, `:263-264`).
  - **MISSING:** a report `--out`. `--out` is read only with `--final` (`:252`, `:259-262`), so the report goes to
    stdout only.
- **Preconditions:**
  - Run at or after `NOT_BEFORE_UTC` 2026-11-14T00:00Z (`:59`, `:181-182`), in the slot 11-14 07:15-08:55 under
    the lease (rulings:54).
  - The mg1_look head and Head 2 have landed together as one head (C10, rulings:701; rulings:53).
- **Refusals** (exit 2, stdout `{"status": "refused", "reason": …}`, `:265-267`; nothing is written):
  - before 11-14T00:00Z (`:181-182`);
  - the MG-1 window is not recorded (`:163-164`);
  - no date from D0 has ended in every support market (`:185-186`);
  - a support market's settlement ledger is missing (`:118-119`).
  - **Master's action:** fix the cause and re-run the same day if the slot allows, else the next admitted
    morning.
- **Outcome** (exit 0): JSON with:
  - per-date `status` only (`countable` / `non_countable` / `pending`);
  - `counts`, `countable_reached`, `required_mg1_last`, `recorded_mg1_last`, `extend_mg1_last`;
  - `ledger_sha256` per market, `module_sha256`, `host`, `run_utc` (`:191-200`).
  - Nothing per market-day is printed.
- **Master's action on the outcome:**
  - `extend_mg1_last` true, or any `non_countable` / `pending` date: step 2a (R11 (4), rulings:12).
  - Otherwise: a dated no-move note (rulings:54).
- **Logged:** the stdout JSON, its sha256, and the run time.

### Step 2. P2 countability report, 2026-11-27

The command is step 1's. The preconditions, refusals and outcome are step 1's, on 11-27 (rulings:11, :54).
Master's action is the same.

### Step 2a. MG1_LAST extension (only when P1, P2 or P3 requires it)

- **What changes:** one commit covering `MG1_LAST`, the reservation status line, rows 25/26/39 of
  `reserved-confirmation-window.md`, and the DLv2 row (R11 (4), rulings:12). MG1_LAST is extended only, never
  shortened.
- **How it lands:**
  - It is suite-gated, never the light path, because it edits a `.py` file (C9, rulings:700).
  - Master runs `scripts\ops\roll_verdict.ps1 -Branch <b>`:
    - RS: the 01:00-04:00 quiet-window merge within two nights;
    - otherwise: the next suite-gated combo (rulings:27 (5), :54).
  - No agent derives the verdict by hand.
- **Refusal it prevents:**
  - `read_countable` refuses a 45th countable date after the recorded `MG1_LAST` (`mg1_look.py:367-369`).
  - `final_rows` refuses the same (`mg1_countable.py:219-221`).
- **Logged:** the commit sha, the verdict output verbatim, and the new `MG1_LAST`.

### Step 3. P3 final countable list, 2026-11-30 (if nothing moved)

```powershell
.\venv\Scripts\python.exe -m weather.calibration.mg1_countable --ledger-root <SETTLEMENTS_ROOT> --final --out <COUNTABLE_PATH>
```

- **Flags:** `--ledger-root`, `--final`, `--out` (`mg1_countable.py:250-252`). `--final` without `--out` is
  refused (`:260-261`).
- **Preconditions:**
  - The first admitted morning at least two days after the 45th date: 11-30 if there is no move (rulings:11,
    :54; C14 rulings:705; `FINAL_MIN_DAYS_AFTER` `:60`, `:222-223`).
  - Step R's A1 answer is in the landed `mg1_look.py`.
  - Any extension from step 2a has landed.
- **Refusals** (exit 2; nothing written):
  - `--out` exists (`:235-236`);
  - fewer than 45 countable dates among the ended dates (`:216-217`);
  - the 45th date is after the recorded `MG1_LAST` (`:219-221`);
  - less than two days after the 45th date (`:222-223`);
  - `write_countable` refused (`:239-242`, `mg1_look.py:373-400`).
  - **Master's action:**
    - on the `MG1_LAST` refusal: step 2a, then P3 again (rerun "only when its own output requires a move",
      rulings:54);
    - otherwise: fix the cause and re-run on the next admitted morning. The look moves with it (C14).
- **Outcome** (exit 0): `mg1_countable/1` written once, mode "x" (`mg1_look.py:373-400`). Stdout carries `sha256`,
  `dates`, `last` (the 45th date, `D45` below), `ledger_sha256`, `module_sha256` and `host`
  (`mg1_countable.py:243-245`). Pending counts as non-countable (`:12`, `:224`).
  - Both Clarification 1 caveats are null, with `caveat_reasons` (`:62`, `:225-226`).
- **Logged:** the stdout JSON, the list's sha256, and `D45`.

### Step 4. R24 refresh and freeze --look mg1 (same morning, after step 3)

R24's weekly refresh, Mondays 11-09, 11-16, 11-23 and 11-30 (rulings:295), is the routine run before this step:

```powershell
.\venv\Scripts\python.exe -m weather.backtesting.venue_label_audit refresh --through <D>
```

On the look morning, the freeze includes its own refresh (`venue_label_audit.py:410-418`; C14). So no separate
refresh runs that morning.

- **The weekly refresh is a hand run.** **MISSING:** a scheduled task. No `scripts/ops` file on the four trees
  names `venue_label_audit`.
- **Its refusals:**
  - `--through` after today (`:349-350`);
  - `--start` after `--through` (`:351-352`);
  - an existing run folder (`:356-359`).
- **Exit 3 on `STATION_DRIFT`** (`:77`, `:517`). Master rules it outcome-blind the same day; for a real station
  change, master adds a dated `venue_rule_stations.json` entry (rulings:295).

```powershell
.\venv\Scripts\python.exe -m weather.backtesting.venue_label_audit freeze --look mg1 --through <FREEZE_THROUGH>
```

- **Flags:**
  - `--label-root` is a top-level flag, before the subcommand; its default is `DEFAULT_LABEL_ROOT`
    (`venue_label_audit.py:480`).
  - `freeze --through` is required (`:484`).
  - `--start` defaults to `2026-10-22` (`:71`, `:485`).
  - `--look` is required (`:487`).
  - The look reads only look id `mg1` (`FREEZE_LOOK_ID`, `mg1_look.py:252`, checked at `:436-438`).
- **`<FREEZE_THROUGH>` is master's value, with these constraints from the code:**
  - It is not after today (`:349-350`).
  - It is not before `D45`, or the look holds (`mg1_look.py:440-441`).
  - The R24 doc example is `--through 2026-11-29`. No MG-1 counterpart of B4 ("latest date final in all
    markets") is ruled. **Open for master.**
- **Preconditions:**
  - Step 3 is done, so `D45` is known.
  - The freeze runs after `D45` has ended in every scored market (`settled_at`, `mg1_look.py:403-410`). The look
    refuses labels frozen earlier (`:442-444`), and a look id is frozen only once (`venue_label_audit.py:416-417`).
  - The lease is free (rulings:296: "about 05:00 or later, lease free").
- **Refusals** (exit 2, stderr `refused: …`, `:514-515`):
  - a bad look id (`:413-414`);
  - `frozen/mg1` exists (`:416-417`);
  - any refresh refusal;
  - a build manifest without `label_dates` or `skipped_dates`, refused before any folder is made (`:422-425`).
  - **Master's action:** a refusal before `frozen/mg1` exists can be re-run with a new run id. A failed refresh
    makes no `frozen/mg1` (the folder is made at `:426`, after the refresh at `:418`).
- **Outcomes that are not refusals:**
  - **Exit 3 (`STATION_DRIFT`):** `frozen/mg1/freeze_receipt.json` IS written, with `audit_status` (`:455`).
    `mg1_look` does not read `audit_status`. **Master's action: hold the look and rule the drift outcome-blind
    before step 6.** See §4 item 1.
  - **A missing source file** is recorded with `sha256` null and `missing_source` (`:436-438`), and the freeze
    still writes. The look then refuses (`mg1_look.py:457-460`). See §4 item 2.
- **Outcome** (exit 0): stdout carries `look_dir`, `freeze_receipt_sha256` and `frozen_sha256` per market for
  `label_csv`, `manifest` and `wu_daily_summary`, plus the counts-only audit (`:504-507`, `:516`).
- **Logged** (R24 (3), rulings:241: "Log the shas before the look"): the stdout, the freeze receipt's sha256, and
  each frozen file's sha256.

### Step 5. Keys-only checks of the freeze (master, read-only, before step 6)

Master reads only `frozen/mg1/freeze_receipt.json` and the audit. It never reads a frozen CSV. It checks:

- `schema_version` is `venue_label_freeze_receipt_v1` and `look_id` is `mg1` (`mg1_look.py:251-252`, `:436-438`);
- `through` is on or after `D45`;
- `frozen_at_utc` is after `settled_at(D45)`;
- `audit_status` is not `STATION_DRIFT`;
- every scored market has `label_csv_matches_manifest` and `wu_daily_summary_matches_manifest` true, and no null
  `sha256` (`:449-460`);
- every scored market has a `label_dates` list and a `skipped_dates` map, keys only (`venue_label_audit.py:68`,
  `:446-447`).

The pre-stamp `label_key_check` (Q2; `mg1_look.py:472-532`) is the code-side check. It reads:

- the receipt's `label_dates` and `skipped_dates`;
- the frozen manifest's `skipped_dates` and `label_source_counts`.

It parses no CSV and calls no reader.

- **MISSING:** a standalone command for it. There is no `check-labels` subcommand and no dry-run flag; the only
  subcommands are `check-receipt` and `run` (`:1038-1050`). The check runs only inside step 6, after the layout
  hole check (`:970-971`) and before the stamp (`:998`). If every pre-stamp check passes, step 6 goes straight
  on to the stamp.
- **Logged:** each check as pass or fail, with the receipt fields read (the keys and the counts).

### Step 6. The look

```powershell
.\venv\Scripts\python.exe -m weather.calibration.mg1_look run --rule <MG1_RULE_PATH> --layout <LAYOUT_ROOT> --countable <COUNTABLE_PATH> --label-freeze <FREEZE_RECEIPT_PATH> --market <MARKET_PARQUET> --out <OUT_DIR> [--shadow <SHADOW>] [--serving-change <YYYY-MM-DD> ...]
```

- **Flags** (`mg1_look.py:1041-1050`):
  - `--rule`: the signed pre-registration, sha256 `MG1_RULE_SHA256` (`:69-70`).
  - `--layout`: the label-free snapshots and bands (`:546-548`). The WS ships the concat layout and its
    `SHA256SUMS` to the host before P3 (rulings:53). **MISSING on the named branches:** its producer. R11 Head 1
    (`mg1_layout.py`, `claude/r11-head1-20261101`) is not one of the trees read here, so no flag of it is quoted.
  - `--countable`: step 3's file.
  - `--label-freeze`: `frozen/mg1/freeze_receipt.json` from step 4 (`:1045-1046`). The frozen files are read
    from that receipt's own folder (`:446-456`).
  - `--market`: the capture-time prices parquet, columns `row_key`, `band_index` and `p_market_yes`, read only at
    the join (`:753`). **MISSING on the named branches:** its producer.
  - `--out`: the folder for `mg1_look_result.json` (`:230`, `:965-968`).
  - `--shadow`: optional; the captured `nbm_v2_guidance_read_v1` shadow vector, "when it exists" (`:1049`).
    Whether it is passed is **open for master**.
  - `--serving-change`: repeatable; serving-change dates under pre-registration section 2 (`:1050`). The list is
    master's.
- **Preconditions:**
  - Step R is recorded, and the landed `mg1_look.py` sha equals the registered entry pin (§2).
  - The window has closed: today is after the recorded `MG1_LAST` (`:957-959`).
  - `D45` has ended in every scored market (`:960-963`).
  - Steps 3 to 5 are done the same morning, under the lease.
  - Neither `data/mg1_look/started-<rule sha>.json` nor `receipt-<rule sha>.json` exists (`:139-141`).
  - The result file does not exist (`:966-968`).
- **Before the stamp (nothing consumed).** These all exit 2, with stderr `refused: …`; a hold's message begins
  `held:` (`:1064-1066`). **MISSING:** a separate exit code for a hold. Master tells a hold from a refusal only
  by that text.
  - **Refused:**
    - an owner constant outside the built branches (`:953`);
    - the rule sha (`:134-137`);
    - an existing start marker or receipt (`:139-141`);
    - a countable list that is malformed, starts off D0, skips a date, has other than 45 countable dates, or has
      `markets` keys other than the support set (`:313-351`);
    - `D45` after `MG1_LAST` (`:367-369`);
    - the window not closed (`:958-959`);
    - `D45` not ended (`:960-963`);
    - the freeze receipt missing, unreadable, of the wrong schema or look id, frozen before `settled_at(D45)`,
      lacking a market, mismatched against its manifest, or with a frozen file missing or differing from its
      sha (`:428-460`);
    - `label_dates` missing (`:501-505`);
    - the result exists (`:966-968`);
    - a repeated layout `row_key` (`:553-554`).
  - **Held** (`MG1LookHeld`, `:83-84`; master rules from the message alone):
    - freeze `through` before `D45` (`:440-441`);
    - a countable market-day with no layout rows (A3 hole, `:555-559`);
    - label-metadata inconsistencies: the key list not sorted and distinct, differing from the manifest's,
      `skipped_dates` differing, a count mismatch against `label_source_counts`, or an overlap with
      `skipped_dates` (`:513-524`);
    - a countable market-day in `skipped_dates`, or in neither list (Q1; "Unexplained absence holds";
      `:525-531`);
    - used rows whose `v2_status` is not "available" (A6, `:973-976`).
  - **Master's action on a refusal or hold:** fix the input or rule from the message. The look is not spent: no
    marker, no receipt and no result exist.
- **The stamp.** The first `join_outcomes` call checks the registered entry point (`:155-157`), then writes
  `started-<rule sha>.json` (mode "x") with `looked_at_utc`, before the loader runs (`:158-161`). From here on,
  the look is spent.
- **After the stamp:**
  - A label refusal the metadata did not predict masks that market-day (T2, 11-03:20). It is disclosed in
    `label_masked` and raises the receipt flag `label_refusal_unpredicted_by_metadata` (`:1002-1007`).
  - Every exit writes the result and the receipt: a verdict, a VOID (`:940-943`), or ABORTED (`:1017-1023`).
  - On ABORTED, the exception is re-raised after the receipt is written, so the exit is non-zero, with a
    traceback rather than `refused:`.
  - **Master's action:** none re-runs. MG-1 has exactly one look (`:128`, `:968`). A VOID's dates "are spent
    and are not re-run" (`:942`).
- **Outcome** (exit 0): stdout `{"receipt": <path>, "decision": …}` (`:1067-1068`). The receipt is
  `data/mg1_look/receipt-<rule sha>.json`, `mg1_look_receipt/1`, with the fields `RECEIPT_FIELDS` (`:73-76`),
  including `label_freeze_receipt_sha256` and `flags`.
- **Logged:** the stdout and stderr, the exit code, and the sha256 of the start marker, the receipt and the
  result.

### Step 7. Receipt check and receipt commit

```powershell
.\venv\Scripts\python.exe -m weather.calibration.mg1_look check-receipt --receipt data\mg1_look\receipt-<MG1_RULE_SHA256>.json
```

- **Flags:** `--receipt` (`mg1_look.py:1039-1040`). It prints `{"receipt", "problems"}` and exits 1 if any
  problem is found (`:1056-1059`). It reads no outcome.
- **Checks:** `receipt_problems` (`:195-227`) checks:
  - the schema and the fields;
  - `body_sha256`;
  - the signed rule;
  - that the entry point is registered at its recorded sha;
  - that the bytes equal the receipt at the fixed path.
- **Master's action on a problem:** the look is spent either way. B's VOID 5 runs the same checks, so master
  rules before B's look session.
- **The commit:** the receipt, the start marker, the result and step 4's freeze receipt are copied into the
  repository record the same day (`mg1_look.py:21-22`; `look-day-dry-run-checklist.md:63`). The commit carries
  their sha256s and the look-log extract. Master owns this commit.
  - **MISSING:** the record's path and file names. No code or doc on the four trees fixes them.
- **Logged:** the check output, the commit sha, and each copied file's sha256, which must equal the
  originals'.

## 2. Closed sha list (master fills every PIN before step 6)

| Item | Path | Current value (tree) | Final |
| --- | --- | --- | --- |
| mg1_look | `src/weather/calibration/mg1_look.py` | `825d57a31f2415f4ac2d81530884c29e914c613165a76cea0983b519a8df077c` (look, WIP); master `1e691c58b68a203aebaed3f505295971f56821e92555e3bc12ef8a4db23ff305` cannot score | `<PIN: mg1_look final, after step R>` |
| entry pin | `MG1_CONFIRMATION_ENTRY_POINTS["weather.calibration.mg1_look"]` in `src/weather/mg1_reserved_window.py` | `825d57a3…` (look, `:69-70`); `1e691c58…` (master) | `<PIN: equals mg1_look final>` |
| mg1_reserved_window | `src/weather/mg1_reserved_window.py` | `0195e35ba49f2ab98ffac09b0fa5a1cb0a831ea9035fca7d0f0cac7ca6f0bcca` (look); `32906db3ebc32b16ba9397933aae33d39a3ca7cc02b0d6242620fb5ad244910c` (countable) | `<PIN: after the combined head and any MG1_LAST move>` |
| mg1_countable | `src/weather/calibration/mg1_countable.py` | `9f59b90be66b0500db6ed6c7e9c77bf1bb4c5e61b41269e0b19560f5ef0f4db3` (countable) | `<PIN: mg1_countable final>` |
| venue_label_audit with freeze-keys | `src/weather/backtesting/venue_label_audit.py` | `2f84e5514d9a2db81c37d299121f60a25d2838c6995e9e51250c6cfe93ba8ddd` (freeze-keys); R24 base `7670fd08f006275bd5766fdce05344586512411a56e34183c1ba2b6fb51c64ce` has no key copy | `<PIN: venue_label_audit final>` |
| venue_rule_labels (writes the manifest `label_dates`) | `src/weather/backtesting/venue_rule_labels.py` | `1842b6da48af90a62999262dd6b92b1b66eaaf323553bb90455c020e5be83405` (freeze-keys); `7bababd2…` elsewhere has no `label_dates` | `<PIN: venue_rule_labels final>` |
| read_venue_labels | `src/weather/backtesting/venue_label_reader.py` | `a4483777143446f309d569ad90e0b9fac695d371bbb1d62b6a7d6367e6a32b66` (all four trees and master) | `<PIN: venue_label_reader at the look>` |
| MG-1 rule | `docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md` | `b044e0f196512379d2f74a22a2a97a10cf58fdbcf5a255c4eb6a470f7f6ba665` (`MG1_RULE_SHA256`, `mg1_look.py:70`) | fixed |
| mg1.py (recorded in the receipt) | `src/weather/reporting/scorecards/free_source_candidates/mg1.py` | `ad6e524ee103072e7738d78264cf1df855a30b01b43099425d4a1de7ae3d889d` (master) | `<PIN: mg1.py at the look>` |

Countable's tree was built on mg1_look `4489e0f30`. Its file there hashes to `8baede1d…`, not look's `825d57a3…`.
The pins above are therefore for the combined head that C10 requires (rulings:701), not for either branch alone.

## 3. Outcome summary for master

| Step | Exit | Meaning | Master does |
| --- | --- | --- | --- |
| R | refusal in `score` | an owner constant is outside the built branches | reviewed edit and re-pin; nothing consumed |
| 1, 2 | 2 | refused, nothing written | fix, re-run in an admitted slot |
| 1, 2 | 0, extension required | `MG1_LAST` must move | step 2a |
| 3 | 2 | refused, nothing written | 2a if `MG1_LAST`; else the next morning, and the look moves with it |
| 4 | 2 | refused; `frozen/mg1` absent | re-run (new run id) |
| 4 | 3 | `STATION_DRIFT`; `frozen/mg1` written | hold the look; rule the drift outcome-blind (§4 item 1) |
| 5 | n/a | a keys-only check fails | hold the look; rule |
| 6 | 2, `refused:` | refused before the stamp; nothing consumed | fix the input |
| 6 | 2, `refused: held:` | held before the stamp; nothing consumed | rule from the message |
| 6 | 0 | verdict or VOID, receipt written | step 7; never re-run |
| 6 | non-zero, traceback | ABORTED after the stamp, receipt written | step 7; never re-run |
| 7 | 1 | receipt problems | rule before B's session |

## 4. Open items for master (found in the code; no fix proposed here)

1. **The look does not gate on `audit_status`.** `freeze` writes `frozen/mg1` and its receipt even on
   `STATION_DRIFT` (exit 3; `venue_label_audit.py:455`, `:517`). `mg1_look` never reads `audit_status`.
   `frozen/mg1` cannot be frozen again (`:416-417`), and the look reads only look id `mg1` (`mg1_look.py:252`).
   Once ruled, what proceeds is master's ruling.
2. **A freeze that dies mid-copy.** If the freeze dies after `look_dir.mkdir` (`venue_label_audit.py:426`) and
   before its receipt (`:461`), `frozen/mg1` exists without a receipt. Every later freeze for `mg1` is then
   refused, and the look refuses the missing receipt. A null-sha source has the same end. Evidence is never
   deleted, so recovery needs a ruling.
3. **No standalone pre-stamp label check** (§1 step 5, MISSING). If every check passes, the check runs straight
   on to the stamp.
4. **Held and refused share exit 2.** They differ only in the `held:` text (`mg1_look.py:1064-1066`).
5. **Producers missing on the named branches:** `--layout` (R11 Head 1, not read here), `--market`, the
   look-log path, and the receipt-commit record path.
6. **`<FREEZE_THROUGH>` for MG-1 is not ruled** (§1 step 4). The code needs at least `D45` and at most today.
7. **The owner-constant timing against the B2 pin timetable** (§1 step R). An answer after 11-12/13 means a
   re-pin; one after S1 cannot land without tripping B's VOID 5 (C10).

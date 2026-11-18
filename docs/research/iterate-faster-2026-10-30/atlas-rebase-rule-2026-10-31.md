# Atlas re-base rule: served vs market per block on the released window (export 2's first consumer)

Status: RULE DRAFT for master's review. Lane L16, 2026-10-31.
- This file is research evidence, not a canonical document.
- It was written from code, docs, file listings and SHA256SUMS paths only. No data row, label, price or score was
  read for it.
- It fixes everything below **before any read**. No read happens until master freezes this rule and the
  coordinator admits the job.

## 0. Authority and claim check

- **Release.** DECISION_LOG 2026-10-30 (two rows) opens 09-30..10-14 once for kill-only and atlas reads, after the
  written claim check. Those rows also fix:
  - C4: row 80's look first;
  - C5: the local-target-date boundary;
  - C7: Austin 10-03 out;
  - MG-2/B outputs excluded;
  - "never support an edge claim".
- **Method.** MODEL_IMPROVEMENT_METHOD §5 rule 10 restates the same release.
- **Register.** EXHAUSTION_REGISTER §5 **order 1** (L1 / rows 1, 2, 12): "re-arm a served-vs-market daily
  scoreboard". It is unblocked for 09-30..10-14 as a kill-only / atlas read. Order 1 closes only at 45 countable
  post-10-09 dates.
- **Master's ruling (a), 2026-10-31.** 10-10..10-14 are read now as a descriptive order 1 slice, and order 6
  excludes them. Recorded in `atlas-readiness-0930-1014.md` §1, branch
  `claude/embargo-release-export-manifest-20261031`.
- **Prior-work grep.** I checked origin/master `265fa99cb` on 2026-10-31.

  | Source | Rows / lines checked | Finding |
  | --- | --- | --- |
  | EXHAUSTION_REGISTER | rows 1, 2, 11, 12; §5 orders 1, 2, 6; X27 (R-H atlas), X28 (L10 gap atlas) | no served-vs-market number exists for the path served since the fixes (register line 161); X27 and X28 are dev-window atlases and do not cover these dates; row 11's 1.6639 -> 1.4980 is the order 1 positive control |
  | FINDINGS_DIGEST | lines 34 (1.423246x, TAINTED as a description of today's served model), 64 (R-H atlas `ff7ee231…`), 79 (MG-2 chain, L7 atlas control) | nothing re-based on released dates |
  | STATE_OF_PLAY | lines 23, 46-48, 69 | "row 80 look, then the atlas (served-vs-market re-base)"; release conditions as above |

  No prior kill or close covers this read.

## 1. Question

**Question.** On the released targets, what is the served-vs-market Brier ratio R (served / market) per hour block
and market, and how does it compare with the dev atlas?

**Purpose.** This is a re-base of order 1's gap description. It is descriptive only: no model is selected, tuned or
compared, and no candidate other than `served` (with `market` as the reference) is scored.

## 2. Scope (fixed)

| Part | Markets | Local target dates | Stratum label | Runnable now? |
| --- | --- | --- | --- | --- |
| **P1. Row 80's cells** | US11 (all °F markets) | 10-01..10-14, minus Austin 10-03 | `pre` 10-01..10-09; `post` 10-10..10-14 | **Yes**, with the wrapper as it is |
| **P2. All 12 on 09-30** | US11 + toronto | 09-30 | `d0930` | **No.** Tooling gaps, §6 |
| **P3. Toronto** | toronto | 10-09..10-14 | `tor_pre` 10-09; `tor_post` 10-10..10-14 | **No.** Tooling gaps, §6 |

- **Boundary.** The boundary is the local target date: a target of 10-14 or earlier is in, including a 10-14 label
  recorded on UTC 10-15. Nothing with a target of 10-15 or later is in, whatever its capture time.
- **Austin 10-03** is excluded everywhere, and the dropped snapshot count is recorded.
- **Exclusions.** MG-2, MG-1, B, composite or any non-served candidate is refused by name. No MG-2/B output file is
  an input.
- **Strata are never pooled,** not across P1/P2/P3 and not across pre/post. P2 and P3 each get their own payload.

## 3. Exact inputs

### P1 (no export 2 file is needed)

| Input | Path | Pin |
| --- | --- | --- |
| Wrapper | `tools/research/released_window/served_market_blocks.py`, branch `claude/released-window-tools-20261031` @ `d155a665a53fe39a261e5b7aa55683a8ba2defe9` | sha256 `b2430135bda4c7ba6a4f66665146b16769b881b456f994659daf81f1304d9fe4` (unchanged since `25c8d3a35`) |
| Row 80 look receipt | `C:\archive\ruled-out\row-80-rise-t3r3-replication\outputs\look\receipt.json` | sha256 `a91915e52cbbfebf12ab650d4ae07d95082415727c767120f52f757fd4e8feda`; the wrapper requires `ledger_row` 80, a verdict, and `layout_manifest_sha256` equal to the release layout's |
| Release layout (row 80's) | `C:\t\r80\build\layout` (`manifest.json`, `inputs_bands.parquet`, `inputs_snapshots.parquet`, `labels.parquet`, `market.parquet`) | `manifest.json` sha256 `d7601613027d42673ca4259bb4df8526022f68d4286655962178d288fa635c42`; `C:\t\r80\build\layout_receipt.json` sha256 `243ea99186864e317aba962e8bb8f9b760e1bf6d9c222b38c0afd1f18576ec3c` |
| Dev layout, read only for the positive control | `C:\swarm\v3layout` | `manifest.json` sha256 `4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22`. This is B's *control layout*, a dev input ≤ 09-29, not a B output. It is read only, never rebuilt (**OP1**) |
| Floor fixture | `tests/fixtures/reporting/dev_scorecard/hard_floor_snapshot_deltas.csv.gz` (master) | sha256 `106f37f4defc39bf49cdf316b97a55cfb0fa0e331427a97d6f309b89555b2cb0` |
| B-bound code, imported read-only | `dev_scorecard`, `dev_scorecard_data`, `loss_atlas` on master | the receipt records `dev_scorecard_code_sha256` and `loss_atlas_code_sha256`; none of these files is edited |

### P2 and P3 inputs

These are fixed now; they are used only once §6's tooling exists.

**From export 2 batch 1, `C:\t\ex2b1`.**
- SHA256SUMS sha256 `84a161601a6e90a3a3fd0a420ac4d071e78ad7ce8c795641c4e824c89a070c3c`; receipt sha256
  `2d4c34b269e8b7c98f8c04fb912f737ef743f74753711512ca6629596d4562df`.
- Every file is verified against SUMS before the read.

| Input | Under `C:\t\ex2b1\data\` | Used by |
| --- | --- | --- |
| The 12 target-09-30 slug folders, `snapshots/highest-temperature-in-<m>-on-september-30-2026/`, as listed in SUMS: `snapshots_long.csv`, `forecasts_long.csv`, `snapshot_explanations.jsonl`, `observation_payloads.jsonl`, `clob_tokens.jsonl`, `forecast_payloads/sha256/…`, and `forecast_payloads(.jsonl\|_long.csv)` where present | as listed | P2 |
| The 12 target-09-29 slug folders' forecast manifests only | `snapshots/…-on-september-29-2026/forecast_payloads*` | the P2 bulletin index (`guidance_extract.py:192` reads `--from` − 1 day) |
| The toronto target 10-09 folder | not in batch 1 (SUMS lists toronto targets 09-25..10-08 only) | P3 |
| `settlements/<m>/ledger.jsonl`, all 12 | as listed | labels: P2 (09-30, all 12); P3 (toronto) |
| `snapshots/observation_triggers.jsonl` | as listed | P2, P3 |
| `forecast_payload_cas/…` (25 refs) | as listed | P2, P3 bulletins |

**From batch2-rest, pulled only by need.**
- The toronto slug folders for targets **10-09..10-14**, whole (sub-manifest set A).
- The toronto `ledger.jsonl` rows for 10-09..10-14, if batch 1's toronto ledger does not carry them. Checked against
  the export receipt by row count, not by reading labels.
- Any `forecast_payload_cas` refs named by those manifests.
- `features_long.csv` and `replay_inputs.jsonl` for the 12 target-09-30 folders, **if they exist on the host**. Batch
  1's SUMS lists neither, and the guidance extract reads both (`guidance_extract.py:311,430`). Absence is recorded,
  not filled.

**Never inputs.** No 88a segment, no order book and no `maker_evidence` file is an input to any part. The "market"
column is the layout's own market column (readiness §4). A book-level market price would be an 88a read, and that
is outside this rule.

## 4. Order of operations (P1, exactly the wrapper's order; each step refuses and stops)

1. **Guards.**
   - No path names `88a` or `panel`.
   - `--out` is new or empty and outside `C:\swarm`.
   - The candidate is `served`.
   - The ruling string is given.
   - `dev_scorecard_data.DEV_LAST` is still 2026-09-29.
2. **Row 80 receipt.** As in §3, and it must name the same release layout manifest sha.
3. **EF §3 floor control** (`dev_scorecard.run_floor_control`): verdict PASS. It must reproduce row 11's
   1.6639 -> 1.4980 (`1.6639158425` / `1.4979600580`), which is order 1's positive control.
4. **Atlas positive control** (`loss_atlas.positive_control`, the atlas's own range and folds, on the dev layout):
   1.774 all / 1.526 00-16. A `ControlFailed` refuses the run; the control is never overridden.
5. **Release scope.**
   - Every release-layout file declares only targets inside 10-01..10-14.
   - Then, in process only, `DEV_LAST` is set to 10-14 and restored afterwards.
   - The release layout is loaded, and Austin 10-03 is dropped with a count.
6. **Scoring.**
   - Strata are `pre` and `post` (`--strata pre+post`, ruling (a)).
   - It runs `sc.score_rows` per block (`00-05`, `06-09`, `10-12`, `13-16`, `17-23`, plus `00-12`, `00-16`,
     `all`) and per market.
   - Intervals are crossed date × market for all markets, and date-clustered for one market.
   - `powered` is judged against `CLUSTER_FLOOR` 12.
7. **Outputs.** As in §5.

The fixed invocation, as one admitted `workstation_heavy.ps1 -Queue` job:

```
python -m tools.research.released_window.served_market_blocks
  --row80-receipt C:\archive\ruled-out\row-80-rise-t3r3-replication\outputs\look\receipt.json
  --floor-fixture tests/fixtures/reporting/dev_scorecard/hard_floor_snapshot_deltas.csv.gz
  --dev-layout C:\swarm\v3layout --release-layout C:\t\r80\build\layout
  --ruling "<master's DECISION_LOG ref for this read>" --strata pre+post --candidate served
  --out C:\t\atlas_rebase_p1
```

- **The `--ruling` string** is master's to issue (**OP2**).
- **The job needs `served_market_blocks` admitted.** The coordinator decides; the lane does not self-admit. The
  allowlist line is on `ba26d795e`, a draft for review.
- **The `tools` package must import from the wrapper's tree.**

## 5. Outputs and schema

Under `--out`, and only there:

- **`<sha>.json`**, schema `released_served_market_blocks/1`. Keys:
  - `evidence_class` = "descriptive, not countable";
  - `register` = "EXHAUSTION_REGISTER section 5 order 1";
  - `candidate`, `ruling`, `strata`, and `pooled` = false;
  - `cluster_floor`, `release_layout_manifest_sha256`, `label_source`;
  - `sections.<stratum>`: `dates` plus `rows[]`. Each row carries `market`, `block`, `n_dates`, `n_markets`,
    `min_clusters`, `powered`, and `served_ratio` (estimate and ci95).
- **`<sha>.md`**: one table per stratum (market | block | dates | R [95%] | powered).
- **`receipt.json`**, schema `released_served_market_blocks/1/receipt`. It holds:
  - the module, dev-scorecard and loss-atlas code shas;
  - the row 80 receipt (path, sha, verdict, layout sha);
  - the floor control (verdict, fixture sha, tracker method) and the positive control result, with the dev layout
    manifest sha;
  - the in-process override;
  - the dates per stratum, the excluded market-days, the snapshots dropped, the boundary string, and the payload
    sha.

P2 and P3 write the same schema under their own `--out` (`C:\t\atlas_rebase_p2`, `C:\t\atlas_rebase_p3`), with
`register` unchanged and the stratum labels from §2.

## 6. P2 and P3 are not runnable on current tooling (none of this is built here)

**P2 (09-30, all 12).**
- `served_market_blocks.check_release_manifest` refuses any date outside 10-01..10-14.
- `r80_layout.py` refuses extract targets outside 10-01..10-14.
- `dev_scorecard_data` refuses 09-30 as dev, because 09-30 is after `DEV_LAST`.
- A P2 read therefore needs:
  - a reviewed revision of both research tools with the window parameterised to exactly `{09-30}`, keeping every
    other guard;
  - a guidance extract over a staged copy of the batch 1 09-30 folders with `--from 2026-09-30 --to 2026-09-30`;
  - an admission.
- **US11 only:** for the reason in the Toronto bullet below, P2 can cover US11 only, unless P3's tooling exists.

**Toronto (P3, and Toronto in P2).**
- `guidance_extract.py:164` drops every market whose `display_unit` is not `F`.
- `r80_layout.US11` refuses toronto.
- No °C extract-to-layout path exists on master (readiness §1 and §4). Building one is code work on master,
  outside this rule, and B-bound files stay unedited.
- Until master scopes it, P3 is **NOT RUNNABLE** and is recorded as such in the atlas receipt.

**Ordering.** If master approves the P2/P3 tooling, it gets its own module review and admission. It then runs after
P1 under this rule unchanged. Its outputs are separate payloads, never pooled with P1.

## 7. Decision use (what each output can and cannot license)

| Output | Can license | Cannot license |
| --- | --- | --- |
| P1 `pre` (10-01..10-09, pre-fix served) | A descriptive re-base of rows 1-2's gap on released pre-fix dates, as a contrast with the dev atlas | Any edge claim; any statement about today's served path (the evening path changed 10-06/10-09) |
| P1 `post` (10-10..10-14, 5 dates) | A descriptive first slice of order 1 on post-fix served output | Closing order 1 (it needs 45 countable dates); any order 6 cell (ruling (a): these dates are spent for order 6) |
| P2 `d0930` (1 date) | A one-date descriptive point for the release's first day | Any interval-based statement (one date cluster) |
| P3 Toronto | Toronto's first served-vs-market description on released dates | Any Toronto guidance or source conclusion (register order 12) |
| Controls (floor, positive) | Validity of the run: on any failure the run is refused, and nothing is reported | — |

- **No edge claim.** Nothing here is cited as evidence for an edge claim, or for or against MG-1, MG-2, B or any
  candidate.
- **Labelling.** Every number is labelled "descriptive, not countable".

## 8. Can any output kill or close anything? No

- No output has a decision threshold.
- `powered` is false for every row by construction, because `CLUSTER_FLOOR` is 12 and the date clusters are 9
  (`pre`), 5 (`post`), 1 (P2) and 6 (P3).
- Order 1 closes only at 45 countable dates.
- Order 6, which may kill on these dates, is excluded from 10-10..10-14 by ruling (a) and is not drafted.
- So no D3 power-at-edge statement applies. Any later use of these numbers to kill or close needs its own
  pre-registration, with a D3 statement written before its read.

## 9. Archive

If master later rules any part out, its rule, the wrapper and tool shas, the outputs, the receipts and the logs go to
`C:\archive\ruled-out\<row-folder>\` with SHA256SUMS, exclusive-create, and are never deleted.

## 10. Open points for master

- **OP1.** The positive control reads B's control layout `C:\swarm\v3layout` (manifest `4d53fdbd…`) read-only.
  Confirm that this is not an "MG-2/B output" under the release's exclusion. I take it to be a dev input ≤ 09-29;
  readiness §3 relies on the same reading.
- **OP2.** The exact `--ruling` DECISION_LOG reference string for P1.
- **OP3.** Whether to commission the P2 (US11 09-30) window parameterisation and/or the P3 °C extract path, or to
  record those parts as NOT RUNNABLE.

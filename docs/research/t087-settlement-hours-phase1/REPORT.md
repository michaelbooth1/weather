# T087 E8 Phase 1 — DESCRIBE, machinery only

**DESCRIBE — Phase 1 complete; no real-data result.** Prepared on
2026-11-10 at 03:16 Toronto, from fetched `origin/master`
`73140b20eed0f81c8fa26bb5faf6defcb269533a`, in isolated worktree
`C:\wt\codex-t087-settlement-hours`, branch `codex/t087-settlement-hours`.
The main checkout's existing changes were left alone.

MEASURED (software only): **23 synthetic cases passed**, including a direct
strict-label parity check against the production daily builder on three
markets. Real observations read: **0**. Gamma requests: **0**. Real differing
market-days: **not measured**; interval not applicable. The synthetic example
has two deliberately constructed differing days, not an empirical finding.

Deliverables in `C:\t\codex\T087`:

- `settlement_hours.py`: offline analysis of one minimal JSON extract; uses
  repo routine classification, temperature parsing, corrections, native
  conversion, half-up rounding, station resolution and band grammar.
- `test_settlement_hours.py`: synthetic front-day, 27/30-hour anchors,
  fall-back DST fold, tied maxima, same-band degree changes, positive/negative
  half-up ties, SPECI/unknown exclusion, body fallback, COR and late-COR tests,
  station/date boundaries, refusal and pre-open Phase 1 guard controls.
- `EXTRACT_SPEC.md`: only the fields, dates, source paths and read receipt
  required of the master. `SOURCE_MAP.md` traces them to production code/docs.
- `PREREG.md`, frozen before synthetic computation;
  SHA-256 **`3b94e1661de07bbcb290da51e434f27540929f95b60c7adac67c1f008a66c19c`**.
- `out/synthetic-tests.xml`, `out/synthetic-example.json`; source hashes and
  handoff commit/remote/bundle evidence are recorded in `out/` at closeout.

DERIVED: a degree flip can remain inside the same event band. The script
parses the actual event band menu, including tails, and reports band flips
only. It retains every tied exact-maximum timestamp. For each comparable day
it reports strict/extended maxima, degrees and bands, paid-band agreement,
and the actual linked-window bounds. Separate missing/refused keys and
effective dates prevent coverage gaps from becoming apparent agreements.

DERIVED: “27 hours” and “30 hours” alone do not specify a look. EF §10x's
NYC example ends at local midnight; Chicago and Denver examples end at local
03:00. On ordinary dates all three examples start at 21:00 the previous
evening. DST changes elapsed-time geometry; tests retain both 01:30 reports
on 11-01 and calculate that example's 27-hour start as 22:00 the previous
evening. The script uses exact link timestamps minus elapsed hours in UTC.

**Scope limit:** the requested extract ends at the target local day's end.
The analysis therefore tests the link's start through that boundary, not a
30-hour response's next-morning tail. Every such result is explicitly marked
`next_morning_tail_not_read`. No next-morning temperature is requested. A
link requiring observations earlier than the authorized 21:00 boundary,
ending too early, or naming another station is refused. This limit must
accompany Phase 2's result; no conclusion about the whole untruncated query
would be supported by this extract.

ASSUMED for Phase 2, subject to the master's receipt: the extract contains
every available scoped routine observation and the correct dated link,
complete band menu and final paid band. `complete=false`, missing routine
temperatures or an unknown paid band yields a refusal. There is no WU read
or fallback. IEM has no receipt time; corrections follow the repo's IEM
convention. Recorded receipt timing requires only the next routine timestamp
for its deadline, with no next-day weather value.

Host/public inventory: the initial routine-only files' existence for
10-22..11-03 is documented by the canonical first-run receipt; later refresh
layout is code-traced. Present coverage through 11-09, absolute capture-host
root, run IDs and byte sizes are not observed. The master resolves
`weather.paths.REPO_ROOT` and receipt-listed source filenames on the host,
records sizes/hashes and copies only the permitted columns/rows. The public
underlying observation source is IEM ASOS. The paid band is public Gamma
resolution, read by master only. No full CSV, snapshot or Gamma response is
needed on the workstation. Phase 1 did not search local weather stores,
because its task explicitly calls for code/docs only and synthetic proof.

The fixed proposed Phase 2 census is 12 built-ins × 18 ended local dates,
10-23..11-09 = **216 requested keys**, not 216 observed/available keys. The
upper bound is frozen, never inferred from the run clock. Denver is included
for label integrity on KDEN; its model-scoring exclusion is irrelevant here.
Master can report missing keys without opening additional stores or fetching
weather. Any extension is a separately frozen instruction before its read.

New scope versus prior work: EF §10x already establishes the routine-report
rule and its URL examples; EF §10ai and the label contract establish the
cutover and earlier paid-band comparisons. This task does not re-measure
those studies. The new contrast is previous-evening inclusion on post-cutover
dates versus the paid band, still unopened. Bounded searches of both archive
indexes found no earlier T087/settlement-hours result. No fitted arm, edge
test or profitability claim is made. Evidence at stake is correct band labels;
there is no measured monetary effect and no live-order action.

Proposed ledger/exposure text (master owns landing; no canonical file edited):

> T087 E8 | 2026-11-10 | codex/t087-settlement-hours | D | prereg
> 3b94e1661de07bbcb290da51e434f27540929f95b60c7adac67c1f008a66c19c |
> Phase 1 code/docs and synthetic tests only; zero real dates consumed;
> proposed one named owner-opened label-integrity extract for local
> 2026-10-23..11-09, built-ins, settlement observations and final paid band
> only; Phase 2 not launched; DESCRIBE, never edge.

DEV_WINDOW_LEDGER's at-least-214 candidate count plus unknown pre-ledger
reads is disclosed in the prereg; this D task adds no K arm and consumes no
07-31..09-29 date. That ledger does not provide reuse counts for the proposed
post-cutover dates. Master logs the named Phase 2 exposure separately before
launch; no zero prior-exposure claim is inferred.

Reproduce synthetic checks (non-capture workstation, one file, serial):

```powershell
Set-Location C:\wt\codex-t087-settlement-hours
C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe -m pytest C:\t\codex\T087\test_settlement_hours.py -q --basetemp=C:\t\codex\T087\pytest-temp-next
```

The analysis CLI requires `--phase2-owner-extract` before it opens any
extract. That flag is **not authorization**: only the master's separately
logged Phase 2 launch may use it. On the master's host, copy this kit to its
task folder, run from the source-pinned repo root with its interpreter and
`PYTHONPATH` pointing to that repo's `src`, then after the log:

```powershell
python <task-folder>\settlement_hours.py --extract <master-minimal-extract.json> --out <new-result.json> --phase2-owner-extract
```

The extract/output are explicit paths, with no default data-store traversal,
no fetch and no overwrite. The JSON input is capped at 32 MiB. The actual
host/task absolute paths must be filled from the master's receipt, rather
than assuming workstation scratch paths exist on the capture host.

Roll assessment: the branch retains this kit solely under
`docs/research/t087-settlement-hours-phase1/`; no production Python module,
config, schema or capture closure changes. Each changed path is in the
canonically roll-free `docs/` category. No host roll-verdict command was run;
master retains its required script-derived verdict before any merge.
No registration, production write, SSH, restart, merge, data extraction,
price/model/session read or Phase 2 run occurred. No MUST-FIX defect is
claimed against production in this Phase 1 handoff.

Automatic approval review rejected deletion of
`C:\t\codex\T087\pytest-temp` with “blocked by policy”; it remains intact
outside the retained kit. No deletion workaround was attempted. The initial
synthetic run exposed unencoded `+00:00` in fixture URLs; fixtures now use
the documented `Z` form and all 23 cases pass. The tested analysis script
SHA-256 is `acae4dd5aed36160fe13e812739cf5b50cf9f862e5c987650152d62eab988fd1`.

Master next: copy only `EXTRACT_SPEC.md`'s fields, log the read and input
hash, then dispatch Phase 2. **Phase 1 stops here.**

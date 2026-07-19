# Agent Work Order — 2026-07-19a (maker scoring projection + input-budget restoration)

Composed by the operations master agent. The maker-paper input preflight is
now structurally broken and hard-stops EVERY settled-day barrier from
2026-07-18 onward (`post_label_maker_evidence`, step_result_status=BLOCK).
No evidence-window override can fix it.

## Why the preflight broke

Two stacked effects made per-run quote tapes 4-6x larger:

1. **Provenance fattening (intentional, keep it):** since the 2026-07-16
   worker-release-binding hardening, every model-variant quote row carries
   `model_variant_runtime_identity` (~390 bytes) plus populated lineage/CLOB
   identity fields. Rows are ~3x wider. This is required for PIT
   countability — do NOT strip it from the canonical tapes.
2. **Quote-intent row doubling (diagnose):** base `quote_intents_long.csv`
   rows per day: Jul 15 = 15,048; Jul 17 = 30,228; Jul 18 = 29,436.
   Something on Jul 17 doubled daily intent volume (event-gate behavior?
   TTL/re-quote cadence? genuinely busier markets?). Investigate and report;
   fix only if it is a defect, with its own receipt.

Result: runs are now 75-217 MB each (Jul 18 = 217 MB alone;
`model_variant_quote_intents_long.csv` = 160 MB of it), so 13 selected runs
= 814,672,216 bytes vs the 536,870,912 preflight cap. The cap was sized for
lean tapes; new runs exceed it permanently.

## Task — compact scoring projection

Do NOT raise the 512 MiB input cap, the 4 GiB private cap, or the 3 GiB
working-set cap. Instead make the maker scorer read exactly what it needs:

1. **Projection artifact:** define a `mm_scoring_projection_v0.1` CSV (or
   two: base + variant) containing only the columns
   `weather.market.mm_paper` / `mm_paper_aggregation` actually consume for
   scoring (quote/leg construction, TTL/expiry, permission, event-gate
   action, reward fields, sizes/prices, market/event/token keys, timestamps,
   variant id — audit the reader to enumerate; expect ~25-35 of the 177).
   Exclude runtime-identity blobs and other provenance-only fields; the
   canonical tape remains the provenance record.
2. **Writer:** the maker daily roll writes the projection alongside the
   canonical tapes at run finalization (atomic publish, same-directory temp
   file). Fail-closed: a run without a valid projection is selected by
   preflight using its canonical tapes (no silent skip).
3. **Backfill tool:** a CLI that derives projections for existing run
   folders from their canonical tapes (streaming, `iter_csv_rows`), so the
   current evidence window is covered on merge day. Idempotent,
   skip-existing, never modifies canonical tapes.
4. **Scorer + preflight:** `run_maker_paper_score_step` preflight measures
   and passes projection paths when present (canonical fallback per run
   otherwise); the bounded scorer consumes them through the existing
   streaming path. Output `mm_paper_v0.1` must be byte-equivalent modulo
   the input binding receipts — prove with a fixture that scores the same
   synthetic run from canonical and from projection.
5. **Budgets unchanged:** 14-run window restored as default; expected
   projection bytes ≈ 15-25% of canonical, giving years of headroom under
   512 MiB. Record projected-vs-canonical byte ratios in the report.

## Rules

Same repository, isolation, and rules as
`docs/roadmap/agent-work-order-2026-07-16.md` (read it first): NEW worktree
on branch `maker-projection-2026-07-19`, based on current `master`, focused
tests under commit_percent < 70, no main-worktree edits, no
scheduler/loop/release/data actions (the backfill tool is CODE — do not run
it against `data/`; master runs it at adoption), no merge/push.

**Capture-safety note for the master agent (not the delegate):** this
branch touches roll-sensitive modules (mm roll writer). Merge/push ONLY in
the 01:00-04:00 quiet window — a midday adoption roll on 2026-07-17 cost
the streak clock its day-3 grade and reset it to day 1 = 2026-07-18.

### Reporting

`docs/roadmap/agent-report-2026-07-19a.md` in your branch: the projection
column list with the reader-audit evidence, equivalence proof, the
row-doubling diagnosis, test counts, branch/commit ids.

---

*Context: barriers for 2026-07-18 onward are maker-blocked until this
lands; July 14/15/16 are certified. The streak clock (day 1 = Jul 18,
lockable ~Aug 1) does not depend on this step but DOES depend on the
quiet-window merge rule above.*

# Workstation handoff 2026-09-110k — portfolio ledger adapter for production snapshots; WU orphan proof caller

Written 2026-09-26 by the production agent after a read-only audit of the 110i and 110j Part A handbacks. Both are in the
integration branch `codex/integration-91a-110f-20260926` (tip `8180404a0` or newer) that lands in the 2026-09-27 quiet window.
Base your branches on `origin/master` after that landing (or on the integration tip if master has not moved yet).

## Part 1 — `account_read` must read the production snapshot files

The 110i report's production command (`python -m maker_core.portfolio report --snapshots .\data\wallet_ledger ...`) cannot
work on the files production actually has. Production snapshots in `data/wallet_ledger/*.json` are written by the production
agent's snapshot helper in this shape (`wallet_ledger_snapshot_v0.1`):

```
{ "kind": "...", "note": "...", "captured_at_utc": "...",
  "reads": { "summary": {...wallet reader /summary...}, "trades": [...], "positions": {...}, "open-orders": [...] } }
```

`src/maker_core/venue/account_read.py` (lines ~18-25) expects top-level `{account_id, captured_at_utc, summary, trades}`;
`reads.summary` carries no `account_id` and the trades list carries no `history_complete` flag. Build:

- An adapter for `wallet_ledger_snapshot_v0.1` (detect by the `reads` key; keep the existing shape working). `account_id` comes
  from an explicit CLI argument or campaigns-config field, never guessed; a missing trades-completeness signal makes the book
  `INCOMPLETE` with a named reason unless the trades read proves completeness (for example a terminal empty page).
- Synthetic fixtures in exactly that shape (field names only; do not ask for production files), including the 09-25/26
  sequence already used in 110i.
- A minimal example campaigns config for the owner's current reality: **only manual trades so far** (owner 2026-09-26), so a
  single `owner-discretionary` campaign plus disabled placeholders for `weather-maker` and `youtube-maker` with no start or
  capital. The owner sets automated campaign start and capital only when the next automated campaign begins. Document
  where the real file lives (`config/local/portfolio_campaigns.json`, git-ignored) and that the production agent authors it
  from the example.
- Update the 110i report's production command so it runs as written against that layout.

## Part 2 — a proof-carrying caller for WU atomic-write `.tmp` orphans

110j Part A added `WuAtomicOrphanProof` to `classify_storage_path` (`storage_classes.py` ~697-707), but `cleanup_preflight`
calls `classification_payload(path)` without a proof (~130, ~203), so the orphans still classify as canonical and no
approved route can delete them. Build the caller: a bounded planner that, for each `*.tmp` candidate in the WU history
directories, gathers the four proofs (writer PID not alive or its start time later than the file mtime; file older than
24 h; no open handle; the final sibling file exists), writes an exact manifest with sha256 and the proof record, and a
`cleanup_preflight` path that re-verifies the proofs at preflight and again immediately before unlink. File-by-file only;
receipt; lease-held PowerShell wrapper like 110j B's. Synthetic fixtures (live PID, reused PID, recent file, missing final
file, open handle) must all refuse.

## Boundaries and deliverables

Fixtures only; no production data, credentials, `.env` or venue calls. Include the repo-wide audits
(`test_schema_registry.py`, `test_import_architecture.py`, `test_agent_docs_audit.py`, `test_path_policy.py`) and the
maker-core import-boundary tests in the focused runs. Branches `codex/portfolio-ledger-adapter-20260926` (Part 1) and
`codex/wu-orphan-proof-caller-20260926` (Part 2); push authorized. Reports
`docs/roadmap/agent-report-2026-09-110k-1.md` and `-110k-2.md`, verdict first, roll classification per file, exact production
commands.

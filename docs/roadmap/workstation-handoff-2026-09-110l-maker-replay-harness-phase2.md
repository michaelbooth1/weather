# Workstation handoff 2026-09-110l — informed maker Phase 2: replay harness (`maker_core/replay/`)

Written 2026-09-26 by the production agent; owner approved starting Phase 2 now (2026-09-26), ahead of the first real-data
plugin dry run (110h, runs on production 2026-09-27 06:30). The design is fixed by
[the informed maker design](../operations/informed-maker-design-2026-09-25.md) §"Evaluation harness", §"Quoting kernel",
§"When to adjust", §"Reuse map" and the phased plan row "2 Replay harness"; the contracts by
[maker-core contracts](../operations/maker-core-contracts.md) v0.1 (additive-only). Build on fixtures only.

## Base

Branch `codex/maker-replay-harness-20260926` from `origin/codex/weather-maker-plugin-20260925` (tip `3b8c7b92d` or newer,
includes Phase 0 and the 110h dry-run loader), with `origin/codex/integration-91a-110f-20260926` (`8180404a0` or newer)
merged in; after tonight's landing, merge `origin/master` instead. Regenerate `docs/roadmap/correspondence-index.md` after
each merge commit.

## Build (domain-neutral core; zero `weather.*` imports in `maker_core`)

1. **Input bundle format** — a bounded, hashed, per-closed-UTC-day bundle: 88a v2 segments (per-minute both-token books,
   reward records on change, public trades) plus plugin-captured inputs and settlement facts, each with capture time and
   hash. Document it as a contract (additive to v0.1) so the YouTube plugin can produce the same shape. Reuse the 110h sealed
   segment reader for the weather side; the core sees only the neutral bundle.
2. **Event-sourced replay engine** — ordered by capture time; providers see only inputs captured at or before `t`; each tick:
   books/terms + `OutcomeView` + `InfoEvent`s + portfolio → `decide()` → `QuoteDecision`; requote/pull rules from
   §"When to adjust"; gaps in capture are exclusions, never zeros.
3. **Fill model** — lift 89a `fill_toxicity_model.simulate` by copy behind a facade (do not edit the original): strictly-through
   primary, at-price sensitivity (89a Clarifications 2/3). Always report both bounds. Cancel the sibling leg on a fill.
   Cash rule: legs within cash, no cross-market over-commitment.
4. **Scorer** (`replay/score.py`) per policy per band-day: reward accrual (k = 1.0 and 0.5), nominal rebate, markouts at
   1/5/30 min and settlement (reuse `execution_tape_markout.py` logic by copy behind a facade if it is loop-imported), held
   inventory settlement P&L, cash-hours, pulled-minute fraction, requotes, fills in vs out of event windows. Fees per EF §10o.
5. **Baselines** — no-quote, `blind_re1`, and clock-only pull at a matched pulled fraction. `blind_re1` must reproduce the
   recorded RE-1 journals (parity fixture from the Phase 0 kit).
6. **Inference** — date and date×market cluster bootstrap, 90% intervals, `UNDERPOWERED` below 10 clusters.
7. **Report** — JSON + Markdown per run with input hashes, coverage and exclusions, per-policy scores, both fill bounds,
   intervals, and a parity section. Deterministic: the same bundle gives the same bytes.
8. **Bounded CLI** — `python -m maker_core.replay run --bundle <dir> --policy <name> --out <dir>` plus a weather-side
   `bundle` command that exports one closed UTC day from production data read-only (sealed segments only, open-read-close,
   time/byte caps, output-only writes — same discipline as 110h).

## Guard rails

- **No scored read of real data.** The harness may run on production data only for coverage/parity diagnostics until the
  owner signs a pre-registration (hurdles, dates, clusters). Put a `--diagnostic-only` default in the CLI that suppresses
  policy comparisons unless an explicit pre-registration file hash is supplied.
- Replay optimism is the main risk (queue position, invisible cancels, 60 s books): document each assumption in the report.
- No venue calls, credentials, `.env` or production data; fixtures only. Everything heavy through `workstation_heavy.ps1`.

## Tests and deliverables

Fixtures: a synthetic 3-day, 2-market bundle; no-lookahead (an input captured after `t` must not change the decision at
`t`); a capture gap excluded, not zero; both fill bounds; sibling-leg cancel; cash over-commitment refused; `blind_re1`
parity; deterministic report bytes; bootstrap `UNDERPOWERED`; the diagnostic-only guard. Include the repo-wide audits
(`test_schema_registry.py`, `test_import_architecture.py`, `test_agent_docs_audit.py`, `test_path_policy.py`) and the
maker-core import-boundary tests. Push is authorized. Report `docs/roadmap/agent-report-2026-09-110l-maker-replay-harness.md`:
verdict first, bundle contract, roll classification per file, the exact production bundle-export command and its expected
size per day.

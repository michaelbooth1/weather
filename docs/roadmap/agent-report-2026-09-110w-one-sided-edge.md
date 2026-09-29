# Agent report 2026-09-110w — one-sided edge maker profile (second candidate)

**BUILT, fixtures only; draft registration UNSIGNED. `one-sided-edge-v0` is in its own modules, and no existing tracked
file changed. informed-v0 and blind_re1 decisions and input hashes are pinned byte-identical. Merge constraint: the
first exam's `source_hashes()` hashes every `src/maker_core/**/*.py`, so this branch must not be adopted on production
master before the 2026-10-15 look has executed.** Nothing was fitted, promoted, registered, scheduled or run against
production data.

Answers `workstation-handoff-2026-09-110w-one-sided-edge-profile.md` (on `origin/master`). Workstation session
(32 GB, non-capture); heavy runs used `scripts/ops/workstation_heavy.ps1`. Open questions served: none.

## Base and branch

Branch `codex/one-sided-edge-20260928`. It was created from `origin/codex/maker-replay-harness-20260926` at `98f768c7`,
the green line after the 111a/111b merges. Before any `src/maker_core/replay/` work, the owner asked for a check on
whether 111d had pushed. It had (report `04bc0523`), so `origin/codex/shadow-runner-20260927` at `b157c52a` was merged
first (fast-forward, no conflict). The draft PR is stacked on that branch.

## What was built

| File | Content |
| --- | --- |
| `src/maker_core/quoting/one_sided.py` | `EdgeProfile(Profile)`, `EdgeDecisionInputs(DecisionInputs)`, `EdgeQuoteDecision(QuoteDecision)`, `decide_one_sided()` |
| `src/maker_core/replay/one_sided.py` | `EdgeReplayConfig(ReplayConfig)`, `EdgeReplayEngine(ReplayEngine)`, `edge_replay()` |
| `src/maker_core/replay/one_sided_report.py` | `EDGE_POLICIES`, `read_edge_authorization()`, `fill_markout_cells()`, `edge_comparison_report()`, `edge_report_bytes()` |
| `tests/maker_core/test_one_sided.py` | 19 fixture tests, including the golden byte-identity pins |
| `docs/research/one-sided-edge-preregistration-draft-2026-09-29.md` | Unsigned second registration: panel 10-16..10-29, settlement-only 10-30, look 10-31 |

Kernel rule, per band per minute (`decide_one_sided`):

- **Hold:** a band that has filled holds to settlement (`HOLD_TO_SETTLEMENT`). Exit stays advisory through the
  existing `policy.inventory_action`.
- **Safety gates:** informed-v0's account, budget, book/terms freshness, post-only, last-three-hours, crossed/off-tick
  and qualified-mid gates, plus the conservative fill bound (`a` and markout >= 0.0043). T+0 is eligible for this
  profile only; the symmetric fallback still refuses T+0 through informed-v0's own gate.
- **Observation signal:** the plugin's `decided` event says only that a band is decided, not which way. The direction
  comes from the captured band shape (`bin_kind`) in the bundle's `plugin_input` snapshot rows, at capture time.
  - `lte`/`eq` means the band is dead: quote NO only, and YES is vetoed.
  - `gte` means the open-top band has been reached: NO is vetoed.
  - A missing or conflicting shape gives `DECIDED_DIRECTION_UNKNOWN` and nothing is quoted.
  - No plugin or exporter bytes changed, so informed-v0 input hashes are untouched.
- **Model signal:** off by default. It needs fixed `z` and `K`, a `scored` view, `(model_id, horizon)` in
  `skilled_cells`, and `z*sigma_eff + a <= |p - mid| <= K*sigma_eff`. Pull hints give `INFO_PULL`. A `widen` hint
  newer than the view gives `AWAIT_FRESH_VIEW`.
- **Fallback:** with no signal, or an edge inside the margin, the unchanged `decide()` runs with `informed_v0`. Its
  legs and reasons are kept, `SYMMETRIC_FALLBACK` is appended, and the edge input hash is stamped on the result.
  Vetoes still apply, so a reached open-top band never keeps a NO leg (`OBSERVED_VETO`).
- **One-sided leg:** the tightest reward-eligible distance behind the touch buffer. Size stays within the grade cap,
  cash and caps.
  - The mid must lie in [0.10, 0.90].
  - The reward score is `q_min(S, 0, mid)`, which is `S/3` inside that range and 0 outside.
  - The net screen is rewards minus `hazard * markout * size`. Expected edge is recorded on the decision but never
    credited.
  - At most one one-sided YES leg per event.
- **Transitions:** `SIDE_FLIP`, `SIGNAL_ONSET` (symmetric to one-sided) and `SIGNAL_LOST` (one-sided to none) cancel.
  `REQUOTE_REQUIRED` and `OUTSIDE_REQUOTE_WINDOW` reuse the lifecycle's existing replacement path.

Replay adapter: the candidate runs the informed lifecycle. The subclass overrides only `ingest`, `tick`,
`decide_inputs` and `run`. It hides `decided` events from the lifecycle's permanent `DECIDED` pull and hands the full
event set to the kernel. It sets `fill_seen` from held lots and computes "YES elsewhere in the event" from the other
bands' legs and lots. It returns results carrying the `EdgeReplayConfig`, whose `profile` field puts z, a, K and the
skilled cells into any registration's `replay_config` binding.

## Measured values

None. This is a build mission on synthetic fixtures; no bundle, settlement or score was read, and no interval was
computed on real data. The only evidence is fixture tests:

- Focused run, under the wrapper: `tests/maker_core`, the six `tests/market/test_maker_*` files, the schema-registry,
  import-architecture, agent-docs, documentation-transaction, path-policy and module-size audits, and the
  correspondence-index test. Result: **1520 passed, 1 skipped, 5 xfailed**.
- The one failure, `test_project_critical_files_are_tracked_or_ignored`, was the new test file being untracked before
  commit. It passes after commit (29/29).
- `python -m weather.operations.agent_docs_audit`: PASS.
- Golden pins were computed at `b157c52a` with no tracked file modified, and are asserted in
  `test_frozen_profiles_decisions_and_input_hashes_are_byte_identical`:

| Pin | Value |
| --- | --- |
| informed-v0 replay, 6-minute two-band scenario with one fill: decisions / digest | 16 / `768d0291…a045a7` |
| blind_re1 same scenario: decisions / digest | 14 / `2091cf25…fe8831` |
| `digest(informed_v0)` / `digest(blind_re1)` | `ce4b9f01…cd378` / `967054c8…d43c0` |
| `decide(conftest inputs).input_hash` | `7b62453b…3b24ed1` |

## Decisions the handoff left open, and deviations

1. **No existing file edited** (the owner asked to keep the profile out of the engine where possible).
   - `policy.py` has no dispatch line; the frozen `decide()` refuses `EdgeProfile` as `UNSUPPORTED_PROFILE`.
   - The handoff's "additive allowlists" are new tuples and functions in new modules: `EDGE_POLICIES`,
     `read_edge_authorization`, `edge_comparison_report` and `EdgeReplayConfig`. The existing `POLICIES`, reader,
     report, CLI and `ReplayConfig` bytes are untouched.
   - Why: changing `POLICIES` would break the signed first registration's `policies` check, and adding a
     `ReplayConfig` field would change `plain(config)` in its `bind_scope`.
2. **CLI: not done.** The first exam's `--compare` path is now bound to its execution pack (manifest, one-look
   receipt, hurdle evaluation). The second exam needs its own pack, and that pack's `replay_config` must carry the
   signed z/a/K. Allowlisting the policy name in exam-1's CLI would create a path that cannot be enrolled. Follow-up:
   an edge execution pack plus CLI subcommand after the parameter signature.
3. **Shadow session policy check: not done.** `ShadowEngine` is a separate `Lifecycle` subclass with its own codec.
   Allowlisting `one-sided-edge-v0` in `Manifest.__post_init__` without an edge-aware engine and codec would silently
   run informed-v0 under the edge name. Follow-up: an edge shadow engine; it needs `maker_core/shadow/*`, which 111d
   last owned.
4. **Pull hints do not pull a dead band's NO leg.** The running maximum only rises, so a later print cannot revive a
   dead band. Without this exemption the paired `new_high` pull (active forever after detection) would block the
   signal entirely.
5. **One YES per event** applies to one-sided YES legs. The symmetric fallback keeps informed-v0's event-cap
   behaviour; changing it would change the fallback.
6. **A signal that cannot be quoted does not fall back.** Examples: mid outside [0.10, 0.90], no eligible size, or a
   non-positive net. The fallback is for "no signal", and on a dead band it would be vetoed anyway.
7. **Screens:** the depth gate applies to the quoted side only. informed-v0's 0.15–0.70 share range is not applied;
   the net > 0 screen is.

## Per-file roll verdict

Derived from imports; `scripts\ops\roll_verdict.ps1 -Branch codex/one-sided-edge-20260928` needs production status
files and must be re-run there.

| File | Closures entered | Verdict |
| --- | --- | --- |
| `src/maker_core/quoting/one_sided.py` | none — imported only by the two modules below and the test | roll-free |
| `src/maker_core/replay/one_sided.py` | none — no `src/weather/**` module imports it | roll-free |
| `src/maker_core/replay/one_sided_report.py` | none | roll-free |
| `tests/maker_core/test_one_sided.py` | none | roll-free |
| `docs/research/one-sided-edge-preregistration-draft-2026-09-29.md`, this report, correspondence index | none | roll-free |

No `schema_registry*` file changed. **Roll-free is not merge-free here.** Adding any file under `src/maker_core/`
changes the first exam's source inventory, which is checked at the look (`executable_sources_changed_before_policy`).
Land after the 2026-10-15 look executes, which also fits the exam-period merge policy.

## Falsification status

The handoff has no falsification section; the fixture evidence cannot test the thesis. The draft registration's
hurdles are the falsification: the economic conjunction versus `blind_re1` and `no_quote`, plus the settlement markout
per filled share with a lower 90% bound > 0.

Owner decisions are needed at signature:

- whether candidate minus `informed-v0` is a hurdle;
- whether a pull hurdle applies;
- values for z, a, K and the skilled cells.

If the 10-15 reliability table marks no cell skilled, the model side stays off. The candidate then reduces to
decidedness NO legs plus the informed-v0 fallback, which is still a valid, narrower exam.

## What was NOT done

- No registration, enrollment, Scheduler change, production write, restart, merge, venue call, credential or `.env`
  access. No real-data replay. No `docs/research/maker-replay-*` file touched. No frozen informed-v0 semantics changed.
- CLI and shadow allowlists: deferred, for the reasons above.

## Reproduction

From a checkout of this branch on either host (the capture host inside its admitted window):

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/maker_core/test_one_sided.py
.\venv\Scripts\python.exe -m pytest -q tests/maker_core tests/operations/test_import_architecture.py tests/operations/test_module_size_audit.py tests/operations/test_schema_registry.py tests/operations/test_path_policy.py tests/operations/test_agent_docs_audit.py
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
git diff --name-only origin/codex/shadow-runner-20260927...origin/codex/one-sided-edge-20260928
scripts\ops\roll_verdict.ps1 -Branch codex/one-sided-edge-20260928
```

## Commit and branch

Code commit `c34a8426` on `codex/one-sided-edge-20260928`; the report commit and final head are in the PR.

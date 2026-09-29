# Repo long-term-health audit — shared brief (plan by Fable, 2026-09-26)

## Common preamble (binding)
Read-only, light, production capture host in protected evening hours. Allowed: `git ls-files`, `git grep`, `git log`, `git show`,
`git cat-file -s`, reading files. Forbidden: walks of `data/` or untracked trees, pytest, compileall, importing project modules,
writes anywhere except your own findings file `C:\tmp\agent-kit\repo-health-audit\<Dn>.md`. Never open `.env*`, `*.cred`, `*.key`, `*.pem`,
`config/local/*`. Do not run Get-ScheduledTask. **Batch your greps**: prefer one `git grep` with many `-e` patterns or `-f <patternfile>`
(write pattern files only under C:\tmp\agent-kit\repo-health-audit\tmp\) over hundreds of separate invocations; keep the host light.
Read AGENTS.md, docs/operations/STATE_OF_PLAY.md, and the relevant dimension of docs/roadmap/audits/full-audit-2026-09-18/ first.

## Baseline
2,489 tracked files (1,061 .py, 983 .md, 154 .json, 78 .ps1, 26 .pkl LFS); pack ~1.02 GB/35 packs. src/weather: reporting 177,
operations 122, market 83, calibration 35, sources 29, model 23, collection 17, 24 root modules. src/maker_core 13 files (empty stubs
portfolio/replay/runtime/venue on master). docs/roadmap 890 files (494 flat, 327 items, 63 audits). tools/research 224 (146 nbm_target_trace).
scripts/ops 86 (20 register_*.ps1; status.ps1 268 KB). 305 `__main__` entry points; 81 distinct `-m weather.*` invocations. Oversized:
point_in_time_evaluation.py 5,494 lines, pooled_candidate_replay.py 4,045, mm_paper.py 3,112, tests/operations/test_daily_refresh.py 7,168,
tests/market/test_taker_bot.py 4,348. 124 skip/xfail markers. Residue files: taker_bot src 33/tests 16/docs 79; streak src 16/scripts 23;
soak src 22; `_c\b` src 98/tests 89/tools 24; polymarket_us src 4/tests 9. Already covered (do not redo; verify dispositions): full-audit
2026-09-18, github-hygiene-review-2026-09-25, storage-value-assessment-2026-09-26 (data/ out of scope). Existing ratchets:
test_import_architecture, test_path_policy, test_schema_registry, test_agent_docs_audit, test_app_architecture, test_release_import_boundary,
test_physical_feature_family_ratchet, module_size_audit, dependency_pins. Note: a large integration branch lands tonight
(origin/codex/integration-91a-110f-20260926) adding 91a nightly compression, wallet reader, portfolio ledger (maker_core/portfolio, venue),
110g, storage registry changes; and the weather plugin + replay harness are on branches. Do not flag the maker_core stubs as dead.

## Rules
2.1 Never recommend deletion of: anything under data/; tapes, ledgers, wallet snapshots, execution-tape files; frozen pre-registrations and
their seed/.sha256 companions; any file cited by ESTABLISHED_FINDINGS, FINDINGS_DIGEST, RETRACTED_AND_FALSE_LEADS, an items/ file or an
audit; anything referenced by a register_*.ps1, a docs/operations runbook, README.md or a CI workflow; LFS model artifacts bound by
artifacts/manifests; sitecustomize.py / weather/__init__.py; held branches (workstation-research, live-canary-bot, item-206 shim).
"Archive" (keep in git, move to a history/archive dir) is the strongest category for evidence.
2.2 A grep is not a trace. Delete/archive needs all of: (a) no static import in src/app/tests/tools; (b) no `-m <dotted>` or basename mention
in scripts/, docs/operations/, README.md, .github/, .codex/; (c) no importlib/import_module/string-built module hit; (d) no scheduled-task
registration; (e) git log -1 date + message read; (f) for src modules, not imported by capture supervisors / loops. Record which were checked;
missing checks => confidence low.
2.3 Skeptic pass: for every delete/archive/consolidate row, a separate section argues the opposite (the one caller/runbook/finding that
would break), refutes with path:line or downgrades. Rows without a skeptic result are reported as `document` at most.
2.4 Roll sensitivity: anything imported by snapshot, CLOB, observation-trigger, execution-tape or maker-evidence supervisors is quiet-window
only; label it (production verifies with roll_verdict.ps1).

## Output schema (per finding row)
id | dimension | path(s) | evidence | category {delete, archive, consolidate, refactor, document, keep} | why it exists / what depends on it |
risk if removed | roll-sensitivity {roll-free, loop-imported (name), unknown} | effort {S,M,L} | confidence {high,med,low} |
skeptic-pass result | who {agent-alone, quiet-window, owner-decision, workstation}
Plus: "sound, leave alone" list; UNVERIFIED list; proposed ratchet(s) that would prevent regrowth in your dimension.
Write the full result to C:\tmp\agent-kit\repo-health-audit\<Dn>.md and return a summary under 400 words (top findings, counts by category).

# maker_core leak audit of workstation wrapper jobs (2026-10-31)

Read-only audit on the 32 GB workstation, git and logs only. Nothing was re-run. Requested by master after row 94
showed that the venv's editable install can resolve `maker_core` to the main checkout instead of the run tree.

## Mechanism

- `venv\Lib\site-packages\__editable__.weather_market-0.1.0.pth` (mtime 2026-07-21, before every wrapper job)
  appends `C:\Users\Michael\Documents\github\weather\src` to `sys.path`.
- `workstation_heavy.ps1 -Queue` runs with cwd = RepoRoot and does not set `PYTHONPATH`. Without `PYTHONPATH`,
  `weather` still resolves to the run tree (cwd bootstrap), but `maker_core` resolves to the **main checkout**.
- Direct proof from 2026-10-17: the first fit1 attempt (job pid 81996, no `PYTHONPATH`) failed with
  `No module named maker_core.replay.toxicity`. Main HEAD then had no `toxicity.py`, while the run tree did.

## Scope

- 364 `weather_heavy` wrapper starts across 64 trees, 2026-10-16T10:58Z to 2026-10-31T13:03Z (every
  `C:\wt\*\data\logs\heavy_workload_queue.jsonl` plus the main checkout's). Queue logs carry no module or arguments.
- Static scan: of the 73 allowlisted offline modules, only 3 can import `maker_core` in any of the 64 trees.
  They are `maker_core.replay.toxicity`, `maker_core.replay.v2.transfer_cli` and
  `weather.market.maker_counterfactual_tape` (`from maker_core.shadow.paper import FILL_RULES, crosses`).
  Calibration modules, including every P5/row 94 module, name `maker_core` only in forbidden-import lists.
- Launch scan of every Claude and Codex transcript and scratch launcher, matched to queue start times. The only
  wrapper jobs that ran these modules are the 17 B2 first-fit jobs of 2026-10-17.
  - The 2026-10-15 `transfer_cli` hits are allowlist and plan edits, not runs.
  - The 2026-10-25 cf-tape hit is a static closure trace, not a run.
  - No `transfer_cli` wrapper job ever ran.
- Main checkout HEAD from `git reflog --date=iso HEAD`. It was `01cad4b91a4f7c8f2c471e9236fb380f21d394d4` from
  2026-10-15 10:28 -0400 until 2026-10-21 15:13 -0400, so it covers every job below.

## Result

Outputs are under `data\analysis\b2-first-fit-20261017\`. Times are UTC queue starts; "PP" is the job's `PYTHONPATH`.

| Job | Date | Receipt sha256 | Run commit | Main commit | maker_core diff | Impact |
| --- | --- | --- | --- | --- | --- | --- |
| run1 to-jsonl strictly_through_YES, cfjsonl pid 119080, PP unset | 2026-10-17 13:36:52 | `b8a3cefbd40382e7e888a3b3ece41f4637fb884ea16a2db2dda16796bab38651` | `5937c03a186df381e63254bdb52e34317546fd8c` | `01cad4b91a4f7c8f2c471e9236fb380f21d394d4` | none (empty) | no impact: leaked to main, identical code |
| run1 to-jsonl strictly_through_NO, cfjsonl pid 104048, PP unset | 2026-10-17 14:52:35 | `0ac77eace0718dec61941847cb63acaa4ec8e683dd766f88d9620e6468d18a74` | `5937c03a186df381e63254bdb52e34317546fd8c` | `01cad4b91a4f7c8f2c471e9236fb380f21d394d4` | none (empty) | no impact: leaked to main, identical code |
| run1 to-jsonl at_price_YES, cfjsonl pid 164860, PP unset | 2026-10-17 14:53:00 | `be1c557c045c842e4e25b5ad7df557a43dfb3702e23e67e2a202c2cdc1a2cfcc` | `5937c03a186df381e63254bdb52e34317546fd8c` | `01cad4b91a4f7c8f2c471e9236fb380f21d394d4` | none (empty) | no impact: leaked to main, identical code |
| run1 to-jsonl at_price_NO, cfjsonl pid 15664, PP unset | 2026-10-17 14:53:25 | `e10ea14d4fee4cdaad67a471ae0f35a73061302b409c498166efca881ef8bee9` | `5937c03a186df381e63254bdb52e34317546fd8c` | `01cad4b91a4f7c8f2c471e9236fb380f21d394d4` | none (empty) | no impact: leaked to main, identical code |
| fit1 first attempt, b2run pid 81996, PP unset | 2026-10-17 14:57:41 | none (failed, output deleted) | `dfb3bc9d4795d5249159e525545accc43302cc80` | `01cad4b91a4f7c8f2c471e9236fb380f21d394d4` | 72 files (+15242/−1) | no impact: leaked, import failed, no output; rerun below |
| fit1 toxicity fit x4, b2run pids 169492 103804 129536 171428, PP `C:\wt\b2run;C:\wt\b2run\src` | 2026-10-17 14:58:21 to 14:59:48 | tables: ST_YES `a47c8e194c0365307ecd0e9dd756514bddeeceb3ec3d6e25fa57cffcb4b46464`, ST_NO `4e55b7fcc24c05ab2b420ffec1aedb395fdcb60d9d9e762fbf3daa4d888e6891`, AP_YES `3763c39dad0758817ad069b21f91294cb3c08f9c8181ed36b067292c66733eda`, AP_NO `d142497908e6b783931c6c89f6aae298b87f97cb32aa38f859684974778c8d57` | `dfb3bc9d4795d5249159e525545accc43302cc80` | `01cad4b91a4f7c8f2c471e9236fb380f21d394d4` | 72 files (+15242/−1) | no impact: PP put the run tree first, maker_core resolved in-tree |
| run2 to-jsonl x4, cfjsonl pids 72856 7916 135588 149868, PP `C:\wt\cfjsonl;C:\wt\cfjsonl\src` | 2026-10-17 15:07:00 to 15:08:21 | ST_YES `5f662d9c2c021d469573f6b9c36c6394cd9f9ed36bdf8f7c24967eef6495433b`, ST_NO `b9dde771b619751e9c2624c6e5d26a82524c887f3d33743790e18962230faf28`, AP_YES `24254ee1ef1d912c383229840d94a5b4c9347f29862a7652b13852e12b6e7806`, AP_NO `8f574efebb1ff841476c3bf2cbbe42282190a146aa5d05ac0a0f809c07daaa23` | `5937c03a186df381e63254bdb52e34317546fd8c` | `01cad4b91a4f7c8f2c471e9236fb380f21d394d4` | none (empty) | no impact: in-tree, and identical anyway |
| fit2 toxicity fit x4, b2run pids 26648 119916 132520 168452, PP `C:\wt\b2run;C:\wt\b2run\src` | 2026-10-17 15:08:48 to 15:11:29 | tables: ST_YES `74a87120574d290d8cb6d1d4f2a02f93a8f827487e47c5206afa7c8adbbdb63a`, ST_NO `aeecb15df1a6c8a13fbb871136a4e813bd3d18692e25530fb386409f5aaaa0b4`, AP_YES `9c3c179f8131196ff28ec15b04a282777c0e3b3f546f27e6f0c8c419344d68ad`, AP_NO `759cd6b38bbd85e9bfd35c16c45a876b075fa7d41d3b39fe775afb3da3225c08` | `dfb3bc9d4795d5249159e525545accc43302cc80` | `01cad4b91a4f7c8f2c471e9236fb380f21d394d4` | 72 files (+15242/−1) | no impact: PP put the run tree first, maker_core resolved in-tree |
| row 94 C4 and pooled read (L17), PP `<tree>\src` | 2026-10-31 | see ledger row 94 | see ledger row 94 | — | not applicable | no impact: no maker_core import; origin pre-flight PASS |

## Notes

- Run commits: `C:\wt\cfjsonl` was detached at `5937c03a1` from 2026-10-17 09:34 -0400 (its only reflog entry).
  `C:\wt\b2run` was at `dfb3bc9d4` (scratch: admit `maker_core.replay.toxicity`; never landed) from 10:57:25
  -0400, before its first job.
- The only leaked jobs that produced output are the four run1 to-jsonl jobs. They call
  `maker_core.shadow.paper.FILL_RULES` and `crosses`. `git diff --stat` of `src/maker_core` between main
  `01cad4b91` and `5937c03a1` is empty, so the leaked code was byte-identical to the run tree's code.
- The b2run diff (72 files) is the toxicity/replay-v2 build that main lacked. The jobs that produced fit1 and fit2
  resolved `maker_core` in-tree via `PYTHONPATH`. Proof: the one job without it could not import the module.
- Residual caveat: the audit uses main's committed HEAD. Uncommitted edits in the main checkout's
  `src/maker_core` at the time cannot be ruled out from git. The main checkout is clean there now.
- Launchers: b2q_run.ps1 (sha256 `24770cd1d498ab8d8c434227248daef793bccace0f6c81d516adc25940341c71`, called
  without `-PyPath`) launched run1. b2fit_queue.ps1 launched fit1; its first version had no `PYTHONPATH`, and the
  final version (sha256 `cdb47a11e75e9df5f6338006586c79d4e26977987aa2cc99983132d00d15b9c9`) sets it.
  lbl1_queue.ps1 (`bcf34afb54c83fee81aaa4064e1e2d9ca16520c6492c4e3b32d7595098452d39`) launched run2 and fit2.
- Audit scripts and outputs are archived at `C:\archive\ruled-out\_p5-subbar\maker_core_leak_audit\` (SHA256SUMS).

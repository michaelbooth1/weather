# N6 heads, landing night 2026-10-11 -> 2026-10-12

- Machine plan: branch `claude/night-plans`, `night-plans/2026-10-12/landing-night-plan-2026-10-12.json` (landing_night_plan_v0.1, plan_sha256 4caa53c15a2a68e0382bd94c7262e2de31559b9d00bed39082109094119de8bb; file sha256 fd375b3e0c7cafce3d857559153c9db77697083fc42728670663dfcffae0eb6f).
- Base: origin/master ac24b9941 (N5 landed + hook fix + wallet_reader). Zero drift at plan time; the head descends from it (fast-forward).

| Exec | Head | Tip | Members | Class (static) | qtest | Pre-gate (21 chunks) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | claude/integration-20261012-rf | 9b95018060a01d90431c77d06a99e2139eef4114 | DST-H3 0ff2acb06 (rebased 4446800c1), #272 D1 f28f505d9 (rebased 865c512d9 + 1adda88d6) | RF | 720 passed, 16 skipped | PASS 519 files, 9594 passed, 63 skipped, 0 failed; receipt sha256 fa1e2da2bcdfa6da5b2c4ef750b588d05d0b675480ab2912ea30b8ed7dc8f8c7 |

- Changed: quiet_window_merge.ps1, status.ps1, suite_gated_quiet_merge.ps1, 3 test files, 3 docs. No importable module (0 of 9).
- quiet_window_merge.ps1 is on the reconciler floor: the pre-gate ran the reconciler file (reconciler: INCLUDED).
- Merge-tree (git 2.54): the head tree d15174a9a equals the merge result on master. Each member merges clean alone on master, so either lands by itself if the other is dropped. Master repeats the host git 2.45 sim at landing.
- landing_preflight (--tests none): the only FAIL is correspondence_index --check, which also fails on master ac24b9941 itself (by design; the closeout regenerates it). --check-structure PASS on the head (4 rows pending closeout). preflight-rf.json sha256 cabd462b62ff17a5130a6474e8b795c65c4eecfd53bee6755e18ab4c955ecac6.
- Activation: none (no loop/task/scorer). The status.ps1 change reaches the pinned watchdog only on the owner's redeploy, which is already queued for #273 and needed before 11-01. The quiet_window_merge.ps1 change takes effect from the next quiet-window merge after landing.
- Drop order on overflow: 272-d1 first, dst-h3 last (it is needed before the 11-01 01:45 DST fall-back).
- Not in plan:
  - LFC N-11/N-12 fe5f54cfa (LFC line, held for the owner);
  - U6 D6 07dd78252 and research inventory f22bea073 (build line, owner yes pending).

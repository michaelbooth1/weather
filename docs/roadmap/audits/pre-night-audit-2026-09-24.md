# Pre-night audit — 2026-09-24

- **Owns:** the five-area read-only audit run before the 2026-09-24/25 night (live session running) and its dispositions.
- **Read when:** reviewing what was checked and changed before the night's landings.
- **Do not use for:** current state (STATE_OF_PLAY).

| Area | Verdict | Dispositions |
| --- | --- | --- |
| RE-1 code and live-session safety | SOUND for the running session (tip `d90d0a6e6`) | Future-only fixes on `2b9a0ca9e` (untested): `checkpoint=False` retries and wait loops keep the main-loop watchdog alive; replay pumps the heartbeat; cap test names/comment. `collect-evidence` for the running session only from 20:00 ET 09-25 |
| Tonight's landing plan | GO with two changes | Order: docs (light path) -> merge-tool fix -> start 88a bounded suite early -> 93a, 95c -> 88a in 01:00-04:00 + registration -> 94b re-tipped on master after 88a (it conflicts with 88a in `status.ps1`; keep both blocks) -> 89a. Never `Remove-Item -Recurse` |
| Host health | Healthy; no side effects from today's changes | Paper-maker tasks added to status's expected-disabled list (94b `e9623e8b1`); clock offset -0.17 s (no action); leftovers for owner review: `WeatherR1ReadinessSmoke_20260913_a1`, `WeatherDesktopShellRestore20260907`, two 08-30 stashes |
| Docs and canon consistency | FAIL-SOFT, ~25 stale lines | All fixed (`544ba32b3`) |
| 89a readiness | Conditional GO | `FROZEN_REF` bound to Clarifications 1-10 (`1a5dd82f9`, study checkout moved); runner gains window/disk/commit/output pre-checks, live peak memory, disk-floor kill; **accepted:** the run likely holds the lease through the 05:00/06:00 tiering, which then skips one day (~3 GiB reclaim) |

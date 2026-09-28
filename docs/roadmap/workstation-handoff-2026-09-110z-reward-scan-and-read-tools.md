# Workstation handoff 2026-09-110z — reward-opportunity scanner, settlement watcher, PR hygiene report

Written 2026-09-27 by the production agent; owner approved (2026-09-27) after a Fable tools review. All three are
read-only; nothing places, cancels or signs orders. Owner decision the same day: the wallet reader stays on the workstation
(its L2 credentials can cancel orders, and the capture host stays credential-free). Base `origin/master` after the
2026-09-27/28 landing; one branch per part.

## Part 1 — reward-opportunity scanner (`codex/reward-scan-20260928`)

`src/weather/market/reward_scan.py`, CLI `scan --out <dir>`: for each active market from `config/location_market_events.json`
(plus `--condition` ids, e.g. YouTube view markets), read public CLOB `/rewards/markets/<condition>` and `/book`, and the reader
`/rewards` via `wallet_reader_client`. Emit per outcome: daily reward rate, max spread, min size, mid, spread, mid inside
[0.10, 0.90] (one-sided score S/3, else 0), resting size inside the reward band on each side, cash needed at the tightest
eligible distance, and our current pool percentage. A GET-only allow-list enforced in one function; extend the import
ratchet so order, signing, RE-1 and credential modules are unreachable; output tagged `owner-discretionary`; no policy or
fair-value import. A roll-free 15-minute runner with `-WhatIf`, run on the workstation; the cockpit (110y) reads its latest file.

## Part 2 — settlement watcher (`codex/reader-settlement-route-20260928`)

A new wallet-reader route `/settlement`: for each held or recently filled market, the Gamma/data-api resolution state,
redeemable flag and terminal price, plus our settlement-proxy value in native units and the venue's weather.gov outcome where
applicable; flag disagreements, unredeemed winners and resolved-but-unreconciled positions. Same allow-list, budget and cache
rules as the other routes.

## Part 3 — PR hygiene report (`codex/pr-hygiene-report-20260928`)

A `gh`-based read-only script: per open PR, ancestry into `origin/master`, merge-tree conflicts, age, linked work record,
file-class roll heuristic (docs/config/ps1 vs Python), and a proposed action. It never closes, merges or pushes anything.

Fixtures only (recorded responses). Repo-wide audits in focused runs. Push and draft PRs are authorized; one report per
part, `docs/roadmap/agent-report-2026-09-110z-<part>.md`, verdict first, with exact start commands.

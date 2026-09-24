# Workstation handoff 2026-09-90a — market-maker architecture map and migration plan

Written 2026-09-24 by the production agent. **Owner goal 2026-09-24:** one multi-domain market maker (weather first, then
YouTube view markets and other Polymarket reward markets), with the foundation built and migrated **before RE-2 or any
unattended quoting** ([forward plan](../operations/forward-plan-2026-09-23.md), decision 5). Read-only analysis plus a
written design; no code changes, no venue calls.

**Start only when no RE-1 session is running** (check with the owner; session 4 ran from ~02:40Z 2026-09-24).

## 1. Map what exists

Inventory every maker-related module under `src/weather/market/` (and their tests), including at least the `re1_*` family,
`reward_quote`, `reward_share_estimate`, `mm_official_adapter`, `mm_exchange*`, `mm_stage2_*`, `mm_live_*`, `mm_policy`,
`info_event_calendar`, `maker_*` and the 84h/88a/89a branches (`origin/codex/re1-wallet-200-20260923`,
`origin/codex/maker-evidence-capture-20260923`, `origin/codex/fill-toxicity-desk-study-20260923`, `origin/codex/stage2-hold-build-20260921`).
For each: purpose, callers, whether it is domain-neutral or weather-specific, and which stack(s) use it. Name every
duplicated responsibility (for example two venue adapters, two selection paths, two journals) with file:line evidence.

## 2. Target layers

Place each responsibility in one of six layers and say what the layer's interface must be:

1. **Venue** — one Polymarket adapter: orders, reads, user stream, heartbeat, reward data, closed-order read quirks.
2. **Market universe (plugin)** — which markets exist, tokens, reward terms, close/settle times; weather is plugin 1.
3. **Fair value and information clock (plugin)** — a domain's price view and when information arrives (weather: METAR/NBM/
   band decidedness; YouTube: view-count updates, uploads — to be confirmed with the owner's YouTube work).
4. **Quoting engine** — reward scoring, pricing, repricing policy (leave-alone band, size-qualified mid, pull-and-cooldown,
   flicker filter, asymmetric reaction, requote budgets), all domain-neutral with per-plugin parameters.
5. **Portfolio risk and capital** — one wallet, caps per market, event, domain and in total.
6. **Execution safety and evidence** — journals, attempt markers, reconcile, cleanup, cancel-only, verdict reporting.

## 3. Deliverables

`docs/roadmap/agent-report-2026-09-90a-market-maker-architecture-map.md`: verdict first; the module map table; the
duplication list; the proposed package layout and plugin interfaces (signatures, not code); a migration order where each step
keeps the RE-1 suites green and is roll-verdict-aware on production; the tests that become the regression net; risks and
open owner questions (including where the YouTube work lives and how its models would plug in). Push branch
`codex/maker-architecture-map-20260924`; pushing is authorized.

## 4. Boundaries

Read-only: no `.env`, no credentials, no venue or network calls, no RE-1 worktree or campaign root, no production host.
Tests only if needed to confirm a claim, through `scripts/ops/workstation_heavy.ps1` with a short `--basetemp`, never during
an RE-1 session.

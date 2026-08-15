# 327. Two-Page Operator Frontend Reset [COMPLETE 2026-08-15 - CONTROL ROOM AND ACTIVE ROADMAP ONLY]

Goal: restart the local operator frontend from a small, explicit product surface
that contains only the maker-pilot Control Room and the active Roadmap.

Owner/package: app, weather.reporting.market, weather.reporting.roadmap,
weather.operations

Source: operator direction on 2026-08-15 to delete every other frontend page
and its unused code, retain the new Control Room, and improve the Roadmap for
agent and human use.

Why this matters: retaining obsolete views as routes, hidden modules, or page-
only helpers makes an agent-maintained project harder to understand and gives
stale product assumptions a path back into operations. The smallest honest
frontend is also the safest base for later product work.

Scope:

- [x] Make Control Room the default route and Roadmap the only other route;
  unknown and retired queries fall back to Control Room.
- [x] Delete the retired overview, per-market, model-pipeline, history,
  market-making, and operations views rather than hiding them.
- [x] Delete reporting helpers and tests whose only consumer was a retired
  page; move the read-only host digest into its operations owner and keep the
  Control Room reduction under its reporting owner.
- [x] Redesign Roadmap around all active `OPEN` and `PARTIAL` items, separating
  clear-path work from dependency-held work and surfacing index integrity.
- [x] Preserve a read-only frontend with no order, cancel, credential,
  promotion, host-control, or risk-setting action.
- [x] Update the launcher, product documentation, architecture contract,
  scoped agent guidance, runtime route smoke, and architecture ratchets to the
  two-page surface.

Acceptance: the router exposes only Control Room and Roadmap, the view package
contains only those two pages, retired page-only source and tests are absent,
legacy queries fail safely to Control Room, and deterministic route plus
documentation checks pass.

## Completion Notes

The application is intentionally a two-page, read-only operator surface. The
Control Room owns the International maker-pilot decision; Roadmap renders the
canonical active backlog, including partial work that the former page omitted.
The old frontend is deleted from executable code instead of being left behind
as dormant navigation or compatibility routes.

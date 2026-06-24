# 306. Daily-Roll Log Hygiene And Historical Error Separation [OPEN 2026-06-24 - OLD CONSOLE ERRORS OBSCURE CURRENT DAILY HEALTH]

Goal: separate historical daily-roll console errors from current health so log
audits can distinguish old disk/encoding failures from active-day blockers.

Source: settled 2026-06-23 log audit. Current disk preflights passed with ample
free space, but daily roll console logs still contained older no-space-left and
Unicode decode errors. The old errors were not active blockers for June 23, yet
they remained in the primary logs an operator would audit for daily health.

Why this matters: stale scary errors waste operator time and can hide the real
current blocker. Log audit should answer "what is broken now" first, then expose
historical incidents through archived records and recurrence reports.

Why it is not already covered: item 16 owns background process management, item
95 owns supervisor primitives, item 161 tracks loop restart noise, and item 199
recovers stale daily rollups. None defines log rotation, incident cutover, or a
current-window health summary for daily-roll console logs.

## Design

1. Add daily-roll log rotation or windowed current-log files for taker, maker,
   snapshot, and daily refresh loops.
2. Persist historical errors into dated incident records with first/last seen,
   owning loop, root-cause category, and resolution status.
3. Make current daily status reports read from the current window and link to
   historical incidents rather than replaying old console failures inline.
4. Add a recurrence detector that promotes an archived incident back to current
   only when it reappears in the current window.
5. Add tests or smoke fixtures for archived no-space-left and encoding errors
   that must not block current health unless they recur.

- [ ] Add current-window log files or rotation for daily-roll console logs.
- [ ] Write dated incident records for historical errors.
- [ ] Update daily status reports to separate current errors from archived
  incidents.
- [ ] Add recurrence detection from archived incident to current blocker.
- [ ] Add fixtures for stale disk-full and Unicode decode errors.

Acceptance: daily roll health reports show only current-window blockers as
current failures, historical disk/encoding incidents remain searchable in dated
incident records, and a repeated historical error becomes current again only
when it appears in the active log window.

Related: items 16, 95, 112, 154, 159, 161, 199, 205, 291, 295.

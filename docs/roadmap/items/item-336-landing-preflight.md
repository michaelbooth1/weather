# 336. Landing Preflight [PARTIAL 2026-10-06 - WORKSTATION TOOL IN REVIEW; LANDING AND ADOPTION OPEN]

Goal: land approved work on the first attempt by judging each head on the night's
cumulative merge on a workstation before production spends a lease on it.

Owner/package: `weather.operations.landing_preflight` and its
`landing_preflight_*` helpers. The durable contract is
[landing preflight](../../operations/LANDING_PREFLIGHT.md).

Source: the owner-approved Swarm L backlog and landing-speed program (2026-10-06,
relayed by master-agent), workstream 2. First-attempt landings were failing on
cross-PR traps: ratchet `Guards:` lines, EOF blank lines, generated-index
conflicts, fixtures another PR changes (#189 after #191) and merge-tool bugs.

Why this matters: the capture host lands a few items a night under a serial
lease; every failed attempt costs a slot. The preflight finds those failures on
the workstation, with the step that introduced each one.

Acceptance:

- [x] Cumulative two-parent synthetic chain over the night plan, deterministic,
  never touching the caller's checkout; any conflict exits 3 with pairwise
  attribution.
- [x] Docs audit, correspondence index, roadmap and schema-registry checks,
  `git diff --check` over the night span, ratchets from a union the head cannot
  shrink, affected-test selection with `head`/`interaction` classing, and an
  expected roll class with `binding: false`.
- [x] Refuses the capture host; heavy tests only through the workstation wrapper
  `-Queue`; exit codes 0–6 with `PASS_NO_TESTS` never exit 0.
- [x] Defender sign-off conditions C1–C14 met with a test per condition.
- [x] Dog-food on the real night plans with `--tests none` (the #189 interaction
  reproduced through the tool).
- [ ] CI green, review, and the guarded landing. The branch adds two rows to
  `src/weather/schema_registry_recent_data.py`, which is in the capture closure, so
  it is expected roll-sensitive and lands in the quiet window paired with another
  roll-sensitive head.
- [ ] Production decides whether and how the verdict feeds its landing checklist;
  until then it is non-binding pre-evidence only.
- [x] M3a (owner-adopted 2026-10-05): the handback carries the receipt
  (delegation contract §5), `--verify-receipt` refuses a stale or edited one, and
  `docs_transaction` is a real pre-check (FAIL on a missing required document or the
  transaction's `git diff --check`).
- [ ] Pilots (owner-approved, non-binding; stacked branch
  `codex/landing-preflight-pilots-20261006`): M13 `eof_newline_only`, M3b binding
  shadow, M5 dual-run recorder. Built and tested; adoption needs the evidence each
  pilot names (M5: the later of 5 concordant landings or 14 days).

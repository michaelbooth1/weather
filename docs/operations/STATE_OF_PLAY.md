# State of play

**Last rewritten: 2026-08-15 12:10 (daily deadline audited; unified client is
the next software gate).** Read this first, then
`ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` for evidence.

> **REWRITTEN, never appended. Capped at ~90 lines.** This page says what is
> happening now. Measurements belong in `ESTABLISHED_FINDINGS`; false claims in
> `RETRACTED_AND_FALSE_LEADS`; invariants in `AGENT_CONTEXT`; cross-host mechanics
> in `DELEGATION_CONTRACT`. Do not cite this page as quantitative evidence. The
> production operations master owns integration truth.

**Objectives:** protect capture continuity; make the **International
Polymarket** maker profitable after spread, adverse selection, inventory, fees,
and rebates actually received; use the weather model as quote-centre and risk
input only where evidence supports it. **We do not currently beat the market.**

## Closed decisions — do not relitigate without new evidence

- **International Polymarket only. Never use Polymarket US.** Historical US
  code, prose, artifacts, and baselines are not authorization.
- **This production PC is the live execution machine after physical
  relocation.** Fresh official eligibility for its real location, exact code,
  external credential references, fixed-scope wrapper, and every readiness and
  risk gate remain mandatory. The same-PC decision does not authorize an order.
- The first live lifecycle remains exactly one market, post-only, no naked
  sells, and a finite non-raisable 100 USDC-equivalent wallet cap. Existing
  lower ceilings remain non-raisable.
- **No alpha is allocated.** The model trails the market in the promotion
  window. Do not convert forecast disagreement into presumed edge.
- Free weather sources only; no paid provider. Release #1 is not the rebate
  pilot's critical path.
- Public execution rows support future received-time paths and markouts only.
  Own-account events, open orders, positions, fees, rebates, and settlement
  establish realized lifecycle and economics.
- The off-host weather mirror is operator-paused. Do not restart it until the
  operator decides the project has earned that cost.
- A new International economics baseline requires explicit operator review and
  acceptance. Never copy or auto-accept it to make drift green.

## Critical path

| Work | Current state / next action |
| --- | --- |
| Capture continuity | All core workers are current-code-bound and healthy. Protect the graded window and the rebuilding streak. |
| International Stage 0/1 | Exact-tip suite, guarded merge, and production adoption passed. This proves software consistency, not live authority. |
| Public execution tape | Recurring supervised capture is adopted, current, and connected. Retained gaps make today's full price path unusable; keep the healthy producer running and qualify future clean intervals. |
| Unified International client | Official `polymarket-client==0.6.0` branch is prepared but behind current production. Its real wheel contract and focused adapter suite pass in an isolated verification venv. Refresh it onto master, install the exact live dependency only in the next admitted heavy window, require that contract not to skip, then run an immutable full suite and quiet-window merge. |
| Bounded maker Stage 2 | Stacked on the client line. Refresh only after the unified client lands, then reprove the new exact tip independently. |
| Paper economics | Current ordinary maker preflight is countable but policy emits no quotes. The prepared paper-only market-harvest lane is the next way to measure quote availability, markouts, inventory, and modeled rebates without pretending the model has edge. |
| First live-money test | After relocation: fresh eligibility, explicit International baseline acceptance, credential import by reference, doctor, Stage 0, both tiny Stage 1 cancellation modes, then a reviewed one-market Stage 2 session. No unattended mutation. |
| Model evidence | Current scoring still blocks promotion. Relevant-season archive depth, not another speculative feature, is the main training constraint. |

## Host and workflow state

- Production `master` equals `origin/master`. Expected generated location config
  and operating-reference changes remain user/runtime-owned and must be
  preserved through integration.
- The settlement chain reached its repository-owned hard deadline; child-tree
  exit, lease release, and capture continuity passed. Its wrapper failed to
  make the interrupted status terminal, so the canonical dead-owner repair was
  run and selected the next verified resume step. A roll-free wrapper fix now
  requires terminal repair after every deadline teardown and emits a distinct
  failure result if that proof fails; integrate it after the graded window.
- `WeatherExecutionTapeSupervisor` is enabled as S4U/Limited at low priority.
  Do not restart it merely to reset historical gap counters.
- `WeatherEveningEvidenceRefresh` stays **Disabled** pending a proven wrapper-
  owned child-tree teardown. The weather mirror tasks stay Disabled.
- `WeatherTrainingWindow` is enabled for its next bounded overnight window.
- Windows still has a pending reboot. Do not reboot in the graded window; later
  maintenance must prove S4U recovery and restore the interactive session used
  by `WeatherOneShotPush`.
- AC sleep is disabled and disk, memory, clock sync, Defender, and volume health
  have current operating headroom. The LAN dashboard remains deferred and must
  use a private-network-only rule when enabled.
- The overnight chain audit failed before producing a receipt under Windows
  PowerShell 5.1. A roll-free fix now uses explicit generic-list conversion,
  writes an incomplete fail-closed receipt before self-disable, and fixes stale
  clock, failed-one-shot, and daily-deadline status wording. Publish and rerun it
  without weakening the audit's execution-tape failure.
- The bounded production suite now forces any checked-in live-SDK contract test
  to execute instead of silently skip. Ordinary developer tests may still omit
  optional live dependencies.

## Do not chase these as new incidents

- Execution-tape `DEGRADED` is retained coverage loss, not a current disconnect.
- A blocked promotion chain and zero ordinary quote permissions are honest
  evidence, not reasons to weaken gates.
- The accepted economics baseline is historical US data by design until an
  explicit International acceptance; the current drift BLOCK is correct.
- Disabled spent one-shots are terminal scheduler hygiene. Investigate their
  result and receipt, not the Disabled state by itself.

## Update this file when

Rewrite after the settlement-chain teardown, every merge/runtime adoption,
baseline decision, client/Stage 2 proof, or live-evidence milestone. Remove
superseded state rather than layering another dated handoff.

# State of play

**Last rewritten: 2026-08-21 21:05 America/Toronto.** Read this first, then
`ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` before model,
measurement, or research work.

> **REWRITTEN, never appended. Capped at about 90 lines.** This page answers
> what is happening now. Quantitative evidence belongs in
> `ESTABLISHED_FINDINGS`; false claims in `RETRACTED_AND_FALSE_LEADS`; durable
> invariants in `AGENT_CONTEXT`; cross-host mechanics in
> `DELEGATION_CONTRACT`. Do not cite this page as quantitative evidence.

**Objectives:** protect irreplaceable capture and settlement; determine whether
International maker spread plus paid rebates exceeds adverse selection,
inventory/settlement loss, fees, and operational costs; improve the weather
forecast as a quote-centre and risk-control input. **We do not beat the market.**

## Current truth

| Area | State / next action |
| --- | --- |
| Capture | The three streak-critical workers are healthy. The supervised public execution tape is connected and integrity-valid. Preserve the graded and near-close windows. |
| Production | `master`, checked-out `HEAD`, and `origin/master` are synchronized at baseline `a76ec7b5599d499011054f98e43564ad0563a58f`. Only the two expected generated location-config files are modified. |
| Integration repair | The immutable-attempt redesign has undergone repeated independent review. The current candidate adds crash-journal recovery, exact registration/task binding, terminal and Git-mutation mutexes, immutable publication evidence, reviewed resume/reconciliation, execution-tape recovery proof, and truthful status. It is not production until tonight's exact-tip suite and guarded merge pass. |
| Tonight's suite | `WeatherIntegrationRecoveryBootstrapSuiteFixed0822` runs the frozen target worktree at 00:35. The complete exact-tip suite is still pending; focused checks are not a substitute. |
| Tonight's merge | `WeatherIntegrationRecoveryBootstrapMergeFixed0822` starts at 01:30, may wait at most 60 minutes for that exact suite to finish, and invokes the hash-frozen quiet wrapper only after a correlated PASS. It must stage without committing, prove core capture plus any affected execution tape, record documentation, publish through `WeatherOneShotPush`, and verify `origin/master`. |
| Crash recovery | `WeatherBootRecovery` is temporarily bound to the frozen target script with its exact SHA256 and a zero-delay startup trigger for this first landing. Pending reboot signals remain, but no reboot is authorized during the run. Task Scheduler startup ordering is not absolute; retained markers and nonzero recovery keep ambiguous states fail-closed. |
| Documentation | The existing documentation transaction is COMPLETE and hash-consistent. A successful merge begins a new exact transaction before publication; a hard kill leaves content-addressed evidence for reviewed resume. |
| Live money | No live-money test is authorized or ready. The code must first pass the full suite, land, recover capture, publish, and produce complete evidence; location, credential, lifecycle, economics, and release gates remain separate. |

## Closed decisions — do not relitigate without new evidence

- International Polymarket only. Never use Polymarket US for a new probe,
  credential path, readiness decision, or mutation.
- No credential access or order mutation from the current Ontario location.
  Physical relocation changes nothing until a fresh official response matches
  the real location and no-circumvention confirmation.
- The first live test is a plumbing/evidence probe: one market, finite
  non-raisable 100 pUSD-equivalent wallet cap, post-only, no naked sells, and
  every existing lower ceiling.
- Candidate selection is never authorization. Authoritative user events, open
  orders, positions, balances, fees, rebates, cancellation, and settlement are
  required for realized lifecycle and economics.
- Model promotion remains blocked and is not the market-centred maker pilot's
  critical path. Do not weaken promotion, serving floors, freshness, economics,
  readers, risk, or post-only enforcement to manufacture permission.
- No alpha and no paid weather provider. Economics baseline acceptance remains
  an explicit informed operator action and is never scheduled automatically.

## Immediate execution order

1. Keep production, the frozen target worktree, the active RDP session, task
   definitions, and `WeatherOneShotPush` unchanged through tonight's attempt.
2. Let the 00:35 exact-tip bounded suite finish. Treat any missing, partial,
   stale, mismatched, or non-PASS evidence as refusal.
3. At 01:30, let the hash-bound gate wait only for that exact running suite.
   Merge only inside 01:00–04:00 and publish only after exact recovery proof.
4. In the morning, inspect the immutable suite/quiet/merge evidence, Git
   ancestry, remote acknowledgement, documentation transaction, and live
   worker identities. Restore `WeatherBootRecovery` to the landed production
   path only after success is unambiguous; otherwise retain the frozen guard.
5. Only after production adoption, recover the remaining execution evidence
   work and rerun paper/live-readiness gates. Do not infer trading readiness
   from an integration PASS.

## Host and workflow state

- The old `WeatherIntegrationRecoveryBootstrapSuite0822` and
  `WeatherIntegrationRecoveryBootstrapMerge0822` definitions are superseded;
  only the exact `Fixed0822` pair may be enabled for tonight.
- `WeatherEveningEvidenceRefresh`, `WeatherDataMirror`, training, and merge
  queue drivers remain disabled where required. No competing heavy or merge
  task may be introduced before this attempt finishes.
- AC sleep is disabled and wake timers are available. The interactive `micha`
  RDP session must remain logged on because `WeatherOneShotPush` intentionally
  uses the credential-bearing interactive token.
- Disabled tasks, Scheduler result zero, and mutable latest reports are not
  outcome evidence. Require immutable receipts, exact hashes, ancestry, and
  current worker identity.

## Update this file when

Rewrite after tonight's integration result, execution-evidence recovery, fresh
candidate selection, eligible-location readiness, or a live lifecycle result.
Remove superseded state rather than appending another handoff.

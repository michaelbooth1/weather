# Mission 09-80a — resting-quote session handback

**PARTIAL / NO-GO for the requested session. The handoff's W0 wallet falsifier
is reproduced; its W3 cancellation bound is unsupported. W1 is implemented,
W2 has inert definitions only, and no Stage 2 execution path is exposed.**
The full suite also exposes a new W2 registry failure, whose shared-file repair
awaits a scope extension; this is not a merge-ready or fully tested branch.

## Provenance and scope

- User instruction: execute the handoff from `codex/stage2-hold-handoff-20260921`.
  The requested scratch path is absent there; its committed canonical copy is
  `docs/roadmap/workstation-handoff-2026-09-80a-build-the-resting-quote-session.md`
  at `a1ee3ba986bedde452e6953236d4b0553cc6dde0`.
- Implementing branch: `codex/stage2-hold-build-20260921`, as the handoff specifies.
  Declared parent: `origin/codex/maker-reconcile-20260920`, exact base
  `cb95ffe3ba302b266b81ea5593dfbc5233e72659`. PR must target that parent until
  its adoption, not silently include its unmerged work in this mission's diff.
- Worktree: `scratch/w/stage2-hold-build-20260921` under the workstation repository;
  created with process-local `GIT_LFS_SKIP_SMUDGE=1`. The main checkout and every
  other task's worktree were preserved.
- Fetched canonical master was `84060d0c53e35b2812e6d90c5ee60c0a309eb501`;
  `git merge-base --is-ancestor 7efeb6eb3 origin/master` returned 1.
  The required reconciled base contains the dependency, as instructed.
- Frozen treatment read from `origin/codex/reward-epoch-design-20260920` at
  `a14ce80dc0189ddbcd1de1af11111f27e07bfe99`. No copy of its historical source
  was silently spliced into the implementation parent.

## Package dispositions

| Package | Delivered / remaining |
| --- | --- |
| W0 | Traced all four relaxations and reproduced the wallet falsifier with the actual shared validator. Stop condition taken; no partial restoration of runtime controls. |
| W1 | Pure `reward_quote.price_reward_quote`, Decimal prices/capital, both token touch checks, reward and capital refusals, many/single displayed-competition scenarios, golden and grid tests. The supplied 0.345 example gives 0.33 YES, 0.64 NO, 19.40 pUSD. No additional historical dry-run rows were available in the named pre-registration. |
| W2 | Frozen `stage1_v1` / `stage2_hold_v1` definitions, canonical bytes/hash, exact numeric ratchets, and a real parser requiring matching dated, unexpired grants in both authority sources. Current files refuse Stage 2. **Not complete:** scattered runtime constants remain unchanged; no adapter/sealer/host-schema integration. The four-key grant parser is a draft numeric-profile gate, never host or live authority. |
| W3 | Traced the cancellation falsifier; did not implement a runner claiming an unsupported dead-man bound. No fake-clock all-end-condition acceptance claim. |
| W4 | Deferred: no new stage, template, sealer or workload name. See the additional owning files required below. |
| W5 | Deferred: no SDK earnings/scoring reader, payout classification, frozen-prediction artifact or account access. No claim about SDK payout attribution. |
| W6 | Deferred: no command or three-band public-book rehearsal, no fabricated journals. |
| W7 | Pilot/portable proposals, owner decision draft and abort card, RE-1A scope-review addendum, items 330/67 and market guide updated; backlog regenerated; documentation checks run. No executable owner grant/config diff is offered before the control/schema decisions. |

## Falsifiers and source traces

### W0: the recorded wallet cannot satisfy restored isolation

Item 67's retained September 6 ledger and the detailed item on
`origin/codex/stage1-pass-docs-20260906` at
`8739902fe8cc71531d3bd9b89f1be1f7ab869bb8` explain why the controls changed.
The first cash reading was 275.48 pUSD; the final successful flow used
489.60767. These are published historical values, not new account reads.

Execution trace: `mm_live_bootstrap.collect_platform_bootstrap_payload` checks cash
backing, enters `balance_cap`, calls `collateral_within_capital_scope`, and
raises before heartbeat/cancel when the isolated wallet exceeds its cap.
`mm_pilot_capital`'s allocation branch permits greater cash; its isolated
branch requires cash <= 100. The new test exercises the actual validators at
275.48, 447.01397 and 489.60767: allocation passes, isolation fails, relabelling
the mixed declaration fails. A separately declared isolated wallet at 50 passes.
This meets W0's instruction to stop if restoration makes the September 6 flow
unrunnable. It does not imply that a fresh dedicated-wallet flow is impossible.

The other relaxation traces:

- Both runtime templates display `authorization_method=reviewed_command_invocation`,
  supply the stage marker without `input`, and call the geography collector
  with hardcoded physical-eligibility/no-circumvention booleans. The old attempt
  consumed a pasted command as a literal; the owner then rejected repeated
  prompts. Restoring prompts requires the templates, not a market-only helper.
- `_validate_credential_import_receipt` checks a past timestamp plus host,
  principal, exact fields/comparison; it imposes no maximum age. The September 6
  redesign removed the two-hour requirement because it forced recreation of a
  correctly deleted backup source. No credential or retained receipt was opened.
- `OfficialPolymarketGlobalAdapter.refresh_market_rules` binds token and condition,
  requires the current fee endpoint value to be finite and >= 0, and records it.
  `_require_candidate_market_rule_binding` compares fresh bps with the candidate;
  the lifecycle journals both values before its submit boundary. No zero-fee
  control was changed and no current venue fee is asserted by this report.

### W3: five-second cadence does not prove five-second dead-man cancellation

The lifecycle runs heartbeats at <= 5 seconds. After the last acknowledged
heartbeat and proof that the order is open, its dead-man path polls orders,
then rejects disappearance before 10 seconds or after 15 seconds. The
repository's `OfficialHeartbeatSender` makes a bodyless request, requires the
exact acknowledgment, and exposes no configurable venue cancellation timeout.
The SDK contract does not supply a shorter timer. Item 67 records the spent
dead-man observation at 10.359 seconds.

The venue's [published order guidance](https://github.com/Polymarket/agent-skills/blob/main/order-patterns.md#heartbeat)
also describes ten seconds with a five-second buffer (checked 2026-09-21).
Its heartbeat-ID example differs from the repository's pinned bodyless
contract; it is not evidence of a new current SLA. The direct current endpoint
documentation could not be retrieved in this session. Neither source supports
the handoff's requirement of cancellation within one five-second interval.
The timing clarification remains unanswered; the stop is preserved.

### Two-adapter proposal: capability reuse is not established

Trace: adapter initialization binds one token/condition and clamps to 10 pUSD;
`authorize_stage1_lifecycle` checks the bootstrap's token against that adapter;
`place_order` consumes its opaque capability before the fake/real client call.
The existing lifecycle first requires account-wide zero open orders and later
cancels its one order. Thus chaining two existing probes is not place-and-hold,
and one token's Stage 0 gate cannot simply authorize the opposite-token adapter.
A new runner could potentially own two independently bound capabilities and a
shared account heartbeat, but this mission does **not** claim that composition
has been validated. Raising a constructor argument still clamps at ten.

### Evidence budget: the short-session treatment cannot satisfy unchanged RE-1

The frozen table treats fewer than 180 visible two-sided minutes as incomplete;
the registration caps RE-1 at three sessions. One session allows only 45 minutes
and all three together allow 135. Do not raise the session count, reinterpret
the unit, or substitute a 360-minute selection prediction for measured earnings
minutes without a new dated treatment. The scope-review addendum preserves
the verdict table and records this conflict explicitly.

No economic sample was collected: zero market-days, date clusters, market
clusters, fills or payouts. Confidence intervals and profitability claims are
not applicable. None of these conclusions relies on the frozen data mirror.

## Required scope for a successor

The handoff's file-ownership sentence grants market files and named documents,
but the traced control owners also include
`scripts/ops/international_live_templates/{stage0,stage1_cancel_all}.py.tmpl`,
`src/weather/operations/international_live_{wrapper_sealer,session_runner}.py`,
`src/weather/execution_host.py`, and `scripts/ops/workload_admission.ps1`.
The assignment currently rejects extra fields and the workload regex admits
only three Stage 0/1 names. None was widened here. A successor needs explicit
ownership of these paths and their tests, alongside the corrected treatment.

Full-suite verification also exposed a shared-file dependency for inert W2:
`src/weather/schema_registry_data.py` must classify `stage1_v1` and
`stage2_hold_v1` as policy identifiers, using owner
`weather.market.mm_live_envelope`, classification `live_envelope_profile`,
and reason "Pilot risk-envelope policy identifier, not a serialized artifact
schema." This follows the existing explicit-exclusion contract; no audit or
unknown-schema check should be disabled. The exact two-entry proposal was
prepared and a scope extension requested. It is pending owner response; the
shared file has not been taken outside the assigned ownership boundary.

## Verification and publication

- W0/capital: **52 passed** through `workstation_heavy.ps1`.
- Independent pricer/profile/control/scoring set: **160 passed** before the
  additional existing-cap parity test.
- Final profile plus existing Stage 1 adapter/lifecycle regressions: **81 passed**.
- Full repository suite: **6,956 passed, 34 skipped, 2 failed; 991 subtests
  passed**, in 2,776.61 seconds through the workstation wrapper. The two
  failing nodes were then run at the clean exact parent: **1 passed, 1 failed**.
  `test_paid_provider_weather_policy_terms_do_not_regress` reproduces there
  because an unchanged historical collection-source audit names a prohibited
  provider endpoint. That historical evidence was not rewritten.
  `test_source_tree_strict_audit_has_only_explicit_exclusions` is new in this
  branch: the two envelope profile IDs need explicit central policy-identifier
  exclusions. The parent's schema audit passes. This regression is not
  attributed to the parent and this branch is not presented as fully tested.
- `compileall -q app src tests`: PASS through the shared-mutex wrapper.
- `agent_docs_audit --repo-root <worktree>`: PASS.
- Backlog generator `--fail-on-lint`, then `--check`: PASS.
- Original sandbox admission refused its different principal. A public
  identity comparison under the signed-in principal proved host/principal
  equality and non-capture status; the same unmodified wrapper then admitted
  all heavy commands. No admission bypass or assignment edit.
- Git comparison to the exact parent proves the legacy adapter, lifecycle,
  candidate/pilot CLI, policy, live runner, sealer, templates and assignment
  are byte-for-byte unchanged. The source family `schema_registry*` is untouched.
- Published package commits: W0 `dd817420d08ff322195b9b619110e0929e0c1f66`;
  W1 `0076520009c868fc2f603e9b9258a31e09f63f18`;
  inert W2 `698bab7fcb4d15978fee6fbfca36874602153b73`.
  The report/docs commit is the subsequent commit on the same branch.
- Publication disposition: topic branch only, draft PR against the declared
  reconcile parent; no merge or production adoption. GitHub CI and independent
  review are pending at report publication. The known local failures must be
  resolved under the appropriate file ownership before integration.

## Per-file roll verdict

Ran `scripts/ops/roll_verdict.ps1 -Branch codex/stage2-hold-build-20260921 -Base cb95ffe3b`.
Result: **UNDECIDABLE, exit 1: no live closure evidence**; snapshot, CLOB,
observation-trigger and enrichment status files are absent in this worktree.
No frozen mirror or manually invented closure was substituted. Re-run on the
production host before integration, including the reconcile parent's changes.

| Changed path | Disposition |
| --- | --- |
| `src/weather/market/reward_quote.py` | UNDECIDABLE; no current retained closures |
| `src/weather/market/mm_live_envelope.py` | UNDECIDABLE; no current retained closures |
| `tests/market/test_reward_quote.py` | UNDECIDABLE; no current retained closures |
| `tests/market/test_mm_live_envelope.py` | UNDECIDABLE; no current retained closures |
| `tests/market/test_stage2_handoff_constraints.py` | UNDECIDABLE; no current retained closures |
| `src/weather/market/AGENTS.md` | Markdown, roll-free by standing contract; no closure claim |
| `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md` | Documentation, roll-free by standing contract |
| `docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md` | Documentation, roll-free by standing contract |
| `docs/operations/README.md` | Required discoverability link, roll-free by standing contract |
| `docs/operations/stage2-hold-owner-authorization-draft.md` | Documentation, roll-free by standing contract |
| `docs/research/liquidity-reward-epoch-re1a-scope-review-2026-09-21.md` | Documentation, roll-free by standing contract |
| `docs/roadmap/items/item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md` | Documentation, roll-free by standing contract |
| `docs/roadmap/items/item-330-maker-economics-refocus-master-plan.md` | Documentation, roll-free by standing contract |
| `docs/roadmap/active-backlog.md` | Generated documentation, roll-free by standing contract |
| This report | Documentation, roll-free by standing contract |

## Reproduction

On the assigned non-capture workstation, from a checkout of the build branch;
use its installed project interpreter (or supply an existing project venv):

```powershell
$repo = (Get-Location).Path
$python = (Resolve-Path .\venv\Scripts\python.exe).Path
$testRoot = Join-Path $env:TEMP 'weather80a-reproduce'
$argsJson = @('-m','pytest','tests/market/test_stage2_handoff_constraints.py',
  'tests/market/test_reward_quote.py','tests/market/test_mm_live_envelope.py',
  'tests/market/test_mm_pilot_capital.py','tests/market/test_reward_share_estimate.py',
  '-q','--basetemp',$testRoot) | ConvertTo-Json -Compress
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($argsJson))
& .\scripts\ops\workstation_heavy.ps1 -Kind pytest -PythonPath $python `
  -ArgumentsBase64 $encoded -RepoRoot $repo
# Full suite: same wrapper, arguments @('-m','pytest','-q','--basetemp',$testRoot).
# Compile: same wrapper, Kind compileall, arguments @('-m','compileall','-q','app','src','tests').
& $python -m weather.operations.agent_docs_audit --repo-root $repo
& $python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
git diff --check origin/codex/maker-reconcile-20260920...HEAD
```

Use a fresh temp name; after completion verify its resolved path is exactly the
named child of the system temp directory before recursive cleanup. On the
capture host, use the repository's admitted bounded-suite procedure instead
of the workstation commands. No workstation-local scratch evidence is needed
to reproduce the new deterministic tests.

## What was not done

No real order, signature, cancellation, venue authentication/account read, wallet access,
exchange credential-store/file access, live SDK call, live authorization, capture or
production write, Scheduler registration/change, model fit, promotion, restart,
master merge, history rewrite, or branch/worktree deletion. Public web reads
were documentation only; no public-book rehearsal is claimed. Runtime evidence
written locally consists only of test output and the backlog generator's
ignored report. Temporary test layouts are cleaned after verification; the
worktree and non-secret verification receipts are retained for review.

# Agent report 2026-09-04 — v2 PIT collector P0 falsification

**Verdict: NO-GO — `NO_GO_ISSUE_EVIDENCE_NOT_IDENTIFIED`.** The
collector mission stopped at P0 before any HTTP transport, wrapper, schema,
fixture, or collector code was built. The exact v2 plan requires truthful
`issue_time_utc` and `available_at_utc` evidence, but the repository identifies
neither timestamp for `<field>_previous_day1`. Supplying either value would
require an assumption outside the immutable plan and would weaken
`stage_response`'s provenance boundary.

This is the handoff's declared successful falsification path. No provider probe
was used to resolve the ambiguity.

## Foundation PR gate

Draft PR [#7](https://github.com/michaelbooth1/weather/pull/7) targets `master`
from `codex/workstation-model-pit-foundation-2026-09-79a`.

```text
exact head       6e23e756f8a2c620df4d821411c923a77afb0553
exact tree       e1a1ddd09edb8e97131a74592c05235e44965c99
draft            true
mergeable        MERGEABLE
merge state      CLEAN
CI run           33461107365
CI head          6e23e756f8a2c620df4d821411c923a77afb0553
CI status        completed / success
review decision  none; zero reviews
```

The PR body records P0/P1 PASS, P2
`P2_NO_REPOSITORY_OWNED_V2_COLLECTOR`, the 4,299-pass workstation suite,
production `ROLL-SENSITIVE` exit 3, and that no model was fitted or live
authority created. The PR remains draft and was not merged, squashed, rebased,
or force-pushed.

## Git source and isolation

The handoff ref was fetched and verified before reading its instruction:

```text
handoff ref   origin/codex/pit-v2-collector-handoff-20260831
handoff tip   503a0ba5ef14403eed02c44762b374cdac707d95
parent ref    origin/codex/workstation-model-pit-foundation-2026-09-79a
parent tip    6e23e756f8a2c620df4d821411c923a77afb0553
parent tree   e1a1ddd09edb8e97131a74592c05235e44965c99
branch        codex/workstation-pit-v2-collector-2026-09-80a
```

The collector branch was created directly from the exact parent in the
separate development worktree
`scratch/w/pit-v2-collector-09-80a`. Final report-only tip and tree are reported
in the outer handback after this file is committed; a commit cannot contain its
own hash. No command entered or targeted the portable live checkout. The main
checkout remained clean and unchanged.

## P0 — issue and availability evidence trace

### Exact answer

| Required value | Provider-returned | Adopted deterministic contract | Verdict |
| --- | --- | --- | --- |
| `issue_time_utc` | No | No. Legacy code labels market-local `(target_date - lead_days) 00:00`, but canonical evidence explicitly says that value is not a provider run or publication time and must not satisfy this corpus contract. | Unidentified |
| `available_at_utc` | No | No producer or derivation rule exists. | Unidentified |

`fixed_lead_day_offset` establishes that values came from an earlier forecast
surface instead of the stitched settled archive. It does not establish an
exact UTC issue cycle, historical publication time, or availability time.

### Source trace

1. `src/weather/sources/forecast_history.py:469-496` reads provider valid times
   and `temperature_2m_previous_dayN`, then derives `issue_time` as market-local
   midnight on `target_date - N days`. The provider response does not supply
   that timestamp. The matching legacy test at
   `tests/sources/test_historical_sources.py:795-813` proves only that this
   code-derived label exists.
2. `docs/roadmap/agent-report-2026-08-03-workstation-scope-forecast-archive-extension.md:359-362`
   explicitly records that the local-midnight value is not a provider run ID
   or publication time and must not satisfy the immutable corpus contract.
3. The retained bounded provider evidence in
   `docs/roadmap/agent-report-2026-08-07-workstation-produce-the-first-retrained-candidate.md:140-146`
   records that successful Previous Runs responses exposed no
   `issue_time_utc`, `available_at_utc`, initialization time, or run ID. This
   mission did not repeat that probe.
4. `src/weather/sources/forecast_history.py:675-710` returns `resp.json()` and
   has no availability-time producer. Its daily normalizer merely groups on
   the derived issue label.
5. `src/weather/sources/forecast_training_corpus.py:392-423` pins the
   `_previous_day1` request but records
   `provider_contract_status: probe_required_before_collection`. The plan's
   issue contract at lines 448-457 requires both timestamps and cutoff
   inequalities but contains no timestamp derivation or publication-lag rule.
6. `stage_response` accepts caller-supplied issue evidence. Its validation at
   `src/weather/sources/forecast_training_corpus.py:785-831` checks presence,
   ordering, and cutoff only; it does not bind the timestamps to response
   fields or a code-owned run contract. The normalizer later copies the caller
   values.
7. `tests/sources/test_forecast_training_corpus.py:112-120` fabricates
   `00:00Z`, `06:00Z`, and `gfs-20210509-00z`. Those deterministic fixture
   values test gate behavior; they are not provider provenance.

Therefore the exact issue timestamp requested by P0 is not licensed, and the
availability timestamp is wholly absent. Reusing local midnight, inventing a
publication lag, copying a timestamp from a staged projection, or relabeling
retrieval time would violate the handoff.

## Falsification and downstream disposition

The first two handoff falsifiers triggered:

- exact issue or availability timestamps are not identified;
- the provider response does not expose enough information to satisfy
  `stage_response` without an assumption outside the plan.

Per the explicit P0 stop rule:

- P1 collector implementation was not entered;
- no production transport or injected fake transport was constructed;
- no PowerShell resource wrapper was added;
- no collector receipt, resume ledger, or fake functional receipt was emitted;
- P2 adversarial collector tests and the full workstation suite are not
  applicable to this report-only NO-GO branch.

The remaining falsifiers were not exercised because doing so would require
building the forbidden downstream surface after P0 had already stopped the
mission. The existing corpus module remains network-free and unchanged.

## Verification

The evidence trace was independently repeated read-only against the exact
parent and reconciled with the canonical source. After adding this report, the
report-only branch was checked with:

```powershell
$commonGitDir = (git rev-parse --path-format=absolute --git-common-dir).Trim()
$sharedCheckout = Split-Path $commonGitDir -Parent
$python311 = (Resolve-Path (
  Join-Path $sharedCheckout "venv\Scripts\python.exe"
)).Path
$repoRoot = (Get-Location).Path

function Invoke-WorkstationPython([string]$Kind, [string[]]$Arguments) {
  $json = ConvertTo-Json -Compress -InputObject @($Arguments)
  $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
  & .\scripts\ops\workstation_heavy.ps1 `
    -Kind $Kind `
    -PythonPath $python311 `
    -ArgumentsBase64 $b64 `
    -RepoRoot $repoRoot
  if ($LASTEXITCODE -ne 0) { throw "$Kind failed: $LASTEXITCODE" }
}

Invoke-WorkstationPython weather_heavy @(
  "-m", "weather.reporting.roadmap.roadmap_backlog", "--fail-on-lint", "--check"
)
Invoke-WorkstationPython weather_heavy @(
  "-m", "weather.operations.agent_docs_audit"
)
git diff --check 6e23e756f8a2c620df4d821411c923a77afb0553...HEAD
```

Results:

```text
roadmap parity       Roadmap backlog: OK (generated report matches sources)
agent docs audit     PASS (18 agent files, 831 Markdown files)
diff check           PASS
shared lease         released; lock opened with exclusive sharing
poison cleanup       PASS; heavy_workload_v1.poison absent
```

A focused or full Python suite would not test the report's historical/source
trace and was intentionally not rerun after the handoff's P0 stop. Foundation
exact-head CI independently completed green before collector-branch
publication.

## Changed-file and roll disposition

The cumulative collector-branch diff contains one Markdown file:

```text
docs/roadmap/agent-report-2026-09-04-workstation-pit-v2-collector.md
```

Per `DELEGATION_CONTRACT.md` section 3, `docs/` is roll-free and enters none of
the snapshot, CLOB, observation-trigger, or CLOB-enrichment loaded-source
closures. No schema registry or Python source changed. Production may still run
the repository-owned verdict command if it requires a host-local receipt; no
live closure evidence was available or inferred on this workstation.

## Reproduction

Production can reproduce the Git and source trace from repository-relative
paths without a provider call:

```powershell
git fetch origin codex/workstation-pit-v2-collector-2026-09-80a
$collector = "origin/codex/workstation-pit-v2-collector-2026-09-80a"
git rev-parse $collector
git merge-base --is-ancestor `
  6e23e756f8a2c620df4d821411c923a77afb0553 `
  $collector
git diff --check "6e23e756f8a2c620df4d821411c923a77afb0553...$collector"
git diff --stat "6e23e756f8a2c620df4d821411c923a77afb0553...$collector"
rg -n "provider_contract_status|issue_time_utc|available_at_utc" `
  src/weather/sources/forecast_training_corpus.py `
  src/weather/sources/forecast_history.py `
  tests/sources/test_forecast_training_corpus.py
```

## What was not done

```text
provider_contacted: false
exchange_contacted: false
credentials_read: false
production_written: false
frozen_mirror_read_or_written: false
portable_live_checkout_changed: false
scheduler_changed: false
capture_started_stopped_or_restarted: false
raw_response_or_corpus_created: false
model_fitted_or_scored: false
candidate_frozen: false
release_or_pointer_created: false
alpha_allocated: false
reserved_date_read: false
branch_merged_or_deleted: false
history_rewritten: false
```

No raw response, data tree, venv, SDK, binary, Git LFS object, secret, private
path, provider URL query, or machine-specific credential material was added.

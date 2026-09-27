# Agent report 2026-09-110l — maker replay harness

**All 313 recorded RE-1 minutes now match. Full-session parity remains NOT QUALIFIED.**
The [behavior-port continuation](#re-1-behavior-port--2026-09-27-continuation-from-0bd7adf98) supersedes the earlier
227/313 result: seven of twelve attempt projections match canonical minute/terminal bytes; five terminal differences
have named source-revision/input-coverage causes. Every retained submit/cancel intent matches. No recorded minute
divergence remains. No full-session, economic, production or live-readiness pass is claimed.
The engine, fill bounds, scorer, baselines, inference, reports and bounded exporter are implemented. Earlier notes are historical.

## Increment 1 — 2026-09-26

Owner authorized starting the multi-day build now and pushing working increments with interim notes. Mission:
`docs/roadmap/workstation-handoff-2026-09-110l-maker-replay-harness-phase2.md`, read from
`origin/codex/handoff-110k-20260926` at `b5a1cf81e`. Branch `codex/maker-replay-harness-20260926` starts at
`3b8c7b92d` (`origin/codex/weather-maker-plugin-20260925`) and merges integration `8180404a0` in local merge
`87526eeb`. The requested integration was not ancestral to fetched `origin/master` (`965374a0`) at intake. After production
lands it, subsequent increments should fetch and merge `origin/master`, preserving topic history and regenerating the index.

The merge preserved the implemented portfolio and weather plugin ownership descriptions and regenerated the correspondence
index. No source conflict occurred. Worktree: `scratch/w/maker-replay-harness-20260926` beneath the workstation checkout.
The original checkout was clean and is unchanged. No subagents were used.

### Delivered contract and behavior

- [Neutral bundle contract](../operations/maker-replay-bundle.md): one closed UTC capture day, bounded manifest and flat
  JSONL streams, byte/count/hash verification, per-record capture clock and payload/source hashes, deterministic ordering,
  explicit active intervals and stable market cluster labels. Plugin v0.1 remains unchanged.
- Immutable snapshots expose only records captured at or before the requested time. A fixture provider drives the existing
  `decide()` to prove that changing a later-captured input does not change an earlier decision. This is a substrate test,
  not the full event engine.
- Deterministic JSON/Markdown diagnostics report hashes, record counts and capture exclusions. Missing minutes do not
  become economic zeros; evaluable minutes are null until payload semantics and decision replay exist.
- The CLI defaults to diagnostic-only. A requested policy is recorded but never executed. Comparison and pre-registration
  flags refuse before bundle or registration IO. A hash alone is not an owner signature; the signed authorization verifier
  and score path must land together later. Neither `captured` nor `synthetic` labels bypass the guard.
- Strict byte/row/time limits, duplicate-key/nonfinite-number rejection, changed-file checks, redirected-path refusal and
  create-only output are covered by fixture tests. All paths are explicit; no `weather.*` import enters `maker_core`.

### Verification

Initial focused run through `scripts/ops/workstation_heavy.ps1`: **32 passed, 1 skipped** (Windows symlink creation is not
granted to this test process). Broader maker/plugin tests, required repository audits and compilation are pending below.
All inputs are synthetic except the already-tracked Phase 0 public quote-price parity fixture.

The first broader run returned **1,113 passed, 13 skipped, 2 failed**: critical new files were not yet staged, and the
documentation audit required a canonical map link and correspondence regeneration. The map link is now added; the index
must be regenerated after committing this report to record its Git-added date. No behavioral failure occurred.
`compileall -q app src tests` passed through the same workstation wrapper. Final audit recheck follows the source commit.

Logical test command (dispatch through the workstation wrapper using its literal base64-JSON argument contract):

```text
python -m pytest tests/maker_core tests/market/test_maker_plugin.py tests/market/test_maker_plugin_dry_run.py tests/operations/test_schema_registry.py tests/operations/test_import_architecture.py tests/operations/test_agent_docs_audit.py tests/operations/test_path_policy.py -q --basetemp <fresh-temp-dir>
```

This includes `test_maker_core_and_plugin_import_boundaries` and its negative controls. The RE-1 full-minute journal tests
already skip twelve attempts because sanitized full-session fixtures do not exist. Passing the retained first-price tests
does not discharge the handoff's full replay parity requirement.

### Roll classification per changed file

No production closures were accessed. Fresh mechanical classification must be obtained on production before adoption:

```powershell
scripts\ops\roll_verdict.ps1 -Branch origin/codex/maker-replay-harness-20260926
```

| Increment file | Classification / closure evidence |
| --- | --- |
| `src/maker_core/replay/__init__.py` | UNDECIDABLE without production closures; no production verdict claimed |
| `src/maker_core/replay/__main__.py` | UNDECIDABLE without production closures; offline CLI only |
| `src/maker_core/replay/bundle.py` | UNDECIDABLE without production closures; new neutral module |
| `src/maker_core/replay/timeline.py` | UNDECIDABLE without production closures; new neutral module |
| `src/maker_core/replay/diagnostics.py` | UNDECIDABLE without production closures; new neutral module |
| `tests/maker_core/test_replay_bundle.py` | Test-only; no claimed production closure membership |
| `tests/maker_core/fixtures/replay_bundle.py` | Synthetic test producer; no claimed production closure membership |
| `tests/maker_core/fixtures/README.md` | Roll-free Markdown |
| `docs/operations/maker-replay-bundle.md` | Roll-free documentation |
| `docs/operations/maker-core-contracts.md` | Roll-free documentation |
| `docs/operations/package-boundaries.md` | Roll-free documentation, including merge resolution |
| `README.md` | Roll-free operator command catalog |
| `docs/README.md` | Roll-free documentation map |
| This report | Roll-free documentation |
| `docs/roadmap/correspondence-index.md` | Roll-free generated documentation |

These are the increment's files, not a new verdict for the inherited integration and Phase 1 branches. No central schema
registry change was introduced by this increment. The existing integration merges registry additions from its own missions.

### Remaining increments and explicit blockers

1. Implement typed payload adapters and the weather-side exporter using 110h's sealed-segment reader. **Exact production
   bundle-export command: not yet implemented. Expected bytes/day: not measured.** Do not substitute the dry-run CLI or
   extrapolate tiny fixture sizes as a production estimate. Publish the real command and bounded fixture size measurements
   when its implementation exists, with production volume still labelled unmeasured until an authorized diagnostic export.
2. Implement the event engine around shared `decide()`, portfolio reservations, clock/terms changes, requotes and pulls.
3. Copy the 89a fill kernel behind a neutral facade; both fill bounds, sibling cancellation and cash commitment tests.
4. Add reward/nominal rebate/markout/settlement/cash-hour scores, no-quote and clock-only baselines, and date/crossed
   date×market 90% intervals with `UNDERPOWERED` below ten clusters. No inference has been run on this three-date,
   two-market synthetic fixture.
5. Add owner-signed pre-registration verification and exact policy/date/cluster/hurdle binding before any scored real-data
   path. Full-session RE-1 parity needs a separately authorized sanitized journal fixture; current fixtures are insufficient.
6. Operations-owned admission update: the workstation wrapper's allowlist does not yet include `maker_core.replay` or the
   future exporter. No guard/wrapper was changed to admit itself. Tests exercise the new CLI inside admitted pytest.

No production data, mirror, credentials, `.env`, venue, model fitting, Scheduler registration, capture restart, live trading,
production write or master merge occurred. Only the owner-requested dependency merge was performed in this local topic.
Publication commit and final verification are recorded in the next note after the working increment is committed.

### Increment 1 publication verification — 2026-09-26

Implementation, fixtures and the initial report are committed as **`5cfc32c8`**. After committing the source report,
`weather.reporting.roadmap.correspondence_index` regenerated its entry with the Git-added date. The two failed checks were
rerun through `workstation_heavy.ps1` and **both passed**: `test_project_critical_files_are_tracked_or_ignored` and
`test_agent_docs_audit_passes_repository_contracts`. Together with the initial broader run, every selected non-skipped
check has passed (1,115 distinct checks, 13 explicit skips). No broad suite was rerun merely to replace that evidence.
Compilation and `git diff --check` passed. This is local fixture verification, not full-repository or hosted CI qualification.

The mechanical local command
`scripts/ops/roll_verdict.ps1 -Branch codex/maker-replay-harness-20260926 -Base 87526eeb`
returned exit 1, **UNDECIDABLE: no live closure evidence**, naming all four missing snapshot/CLOB/observation/enrichment
status files. Nothing was copied from production to change that verdict. Before adoption, production must run the command
above against its actual target base and fresh closures, including the inherited dependencies.

Origin was fetched again before publication; master remained `965374a0`, so the integration-branch base is still the
owner-directed choice. The tested source commit and this appended note/index commit are the first increment to push.
Later notes in this report should append to this record, as the owner requested, rather than rewrite these observations.

## Continuation item 1 — event engine (2026-09-26)

**PASS on fixtures: capture-ordered engine and typed payload adapters implemented.**
Resume base is `e3274ea7`; fetched master remains before the instructed integration landing.
The engine invokes shared `decide()`, maintains reservations across bands, records
explicit excluded intervals, schedules information/freshness/close timers, latches
decidedness, and cancels before cooldown/replacement. Future captured probability
or event changes leave earlier decisions byte-identical. No external provider is
called. Numeric cash and hazard inputs remain explicit counterfactual assumptions.

Admitted fixture verification: **39 passed, 1 symlink-privilege skip** (engine and
bundle tests). It covers scheduled pull/re-entry, permanent decidedness, mid drift,
minimum-size changes, gaps, cash reservation and future payload-clock refusal.
The fill hook is inert in this item; item 2 supplies it. Scoring CLI remains refused.
New `engine.py` and `payloads.py` are neutral offline modules with no production
closure evidence; mechanical adoption verdict remains UNDECIDABLE. New scenario
and engine-test files are test-only; the contract and this report are roll-free.

## Continuation item 2 — fill facade (2026-09-26)

**PASS on fixtures: both 89a fill bounds, sibling cancellation and cash accounting.**
Item 1 was pushed as `f4b68464`. The original 89a simulate implementation is copied
at `de76a4a9b67b25781c6c6f33b10691841e8630cc`, with its unchanged test reference;
both-bound differential tests compare fills, exposures and quote diagnostics.
An explicit trade-health capture is required: absent prints alone do not prove
zero fills. Duplicate IDs cannot fill twice; conflicting IDs refuse. Equal-time
trades consume old quotes, both legs cancel after a fill, and cash/reservations
remain shared across markets. The conservative remainder cancellation and 60-second
coverage limit are deliberate lifecycle overlays on 89a's predicate.

Admitted engine/fill suite: **15 passed**. No real tape was read. New fill facade,
copied kernel and payload/engine changes have UNDECIDABLE production closure
classification pending the mechanical production verdict; fixture/reference/test
files are test-only; documentation is roll-free.

## Continuation item 3 — scorer (2026-09-26)

**PASS on fixtures: per-band-day scorer implemented.** Item 2 was pushed as
`d6e732d9`. Accrual uses changing reward terms and k=1/0.5; nominal fee-funded
rebates stay separate from cash. Maker fees follow EF §10o. Both-token markouts at
1/5/30 minutes and settlement retain missing counts and null missing valuations.
Settlement P&L never double-counts markouts. Inventory cash-hours include holding
after quote windows, while capture exclusions cannot become zero-return days.
The scorer includes pull fraction, quote/requote counts and event-window fills.

Admitted engine/fill/score suite: **21 passed**. Pure copied markout/rebate logic is
differentially checked against the existing owner module. New score module and
engine changes: production closure UNDECIDABLE; tests are test-only, docs roll-free.

## Continuation item 4 — baselines and available parity (2026-09-26)

**Baseline implementation PASS; full-session RE-1 parity remains UNAVAILABLE.**
Item 3 was pushed as `23ce28ee`. No-quote uses the same coverage denominator.
Blind RE-1 ignores plugin probability/events and retains one-band/first-fill-end
behavior. All 12 frozen selection-price fixtures and eight available first-minute
quote pairs pass through the event engine. The full-trace comparator checks every
field and terminal event; no full-session journal was fabricated to supply it.

Clock-only uses unavailable fair value, shared informed quoting safety, and fixed
UTC prefix pull windows. A bounded duration search matches aggregate pulled
fraction within one covered minute, using exposure only. This is an ex-post
descriptive control, not a deployable prediction. Unattainable matches report
UNMATCHED and cannot support an inferential clock comparison. No move or economic
outcome selects its schedule. Admitted replay regression suite: **36 passed**.
New baselines/parity modules and engine changes: closure UNDECIDABLE; tests
test-only; docs roll-free. Full-session parity remains an adoption limitation.

## Continuation item 5 — clustered inference (2026-09-26)

**PASS on synthetic panels.** Item 4 was pushed as `b9b3ea21`. Paired band-day
deltas are summed within date/market; an incomplete or unpaired band excludes the
whole market/date cell. Bootstrap resamples whole dates and, separately, independent
date and market multiplicities (crossed clustering). Both report 90% intervals,
counts, deterministic seeds, sparse empty-replicate counts and UNDERPOWERED below
ten required clusters. Cluster count is not a power claim; a descriptive normal
80%-power MDE approximation is labelled as such. No market-day IID fallback exists.

Admitted focused checks: **4 passed**, including shared market shocks that date-only
resampling cannot capture, three-date/two-market underpower, deterministic order,
and missing-cell exclusion. New inference source: closure UNDECIDABLE; tests
test-only; docs roll-free. No real-data estimate or alpha spend occurred.

## Continuation item 6 — reports and diagnostic-default gate (2026-09-26)

**PASS on fixtures.** Item 5 was pushed as `87865935`. JSON and Markdown always
include both bounds, hashes, exclusion intervals, scores, matched-clock status,
90% clustered intervals and the full-session parity limitation. Reordered copies
of the synthetic three-date/two-market panel produce identical report bytes.
Admitted report/envelope suite: **37 passed, 1 symlink-privilege skip**.

The CLI defaults to diagnostics. Comparison requires an explicit raw registration
hash pinned through a separate owner-approved source review. The approval table
is empty; neither synthetic labels nor arbitrary hashes admit a run. The owner
signature is review-attested, **not a claim of cryptographic signature verification**.
Registered hurdles, dates, clusters, policies, config and inference settings are
bound before scoring; the fixture test enrolls only an in-memory fictional owner.
New authorization/report modules and CLI/diagnostic changes: closure UNDECIDABLE;
tests test-only; docs roll-free. Weather exporter and final repository audits follow.

## Weather export and closeout — 2026-09-26

Item 6 was pushed as `87afb7a2`. The weather-side `bundle` command now reuses
110h's sealed 88a reader, projects both-token books, reward captures/references,
public prints, lifecycle evidence, plugin inputs/views/clocks, region factors and
reconciled ledger facts. It retains raw-file/segment/payload hashes and original
supporting clocks, never reads a growing 88a segment, and refuses changed support
files. Supporting plugin tables have 110h's stable-read checks; they are not
misrepresented as 88a seals. Missing trade health expires after 30 seconds;
unrecorded PONGs cannot turn silent periods into zero-fill observations.

`--carry-bundle` supplies prior hashed descriptors/band metadata for a later
settlement day with no new books. Empty active intervals mean settlement-only
metadata and add no quote minutes. The neutral decoder now accepts the weather
provider's reconciled status `match` as well as fixture `reconciled`. Blind RE-1
resets its first-fill-ended session at each UTC date boundary, carrying cash and
inventory; that explicit convention does not establish live-session parity.

Admitted exporter tests: **9 passed**, including gzip/reference round trips,
unchanged source files, disabled network access, lifecycle/token mapping,
caps/refusals, later settlement carry, and deterministic output. The two-minute,
three-band fixture measured **44,756 bytes**: bundle manifest 913, event stream
40,224, export metadata 3,619. This is a fixture measurement, **not a forecast of
production bytes/day**. Production size is unmeasured; each requested market/day
export is bounded at **64 MiB** and 100,000 records, with at most 1 GiB source reads
and 300 seconds. Over-cap days refuse, rather than silently truncate. Start with
one named market; do not infer fleet volume or success from this tiny fixture.

### Exact production export command (not executed)

Run from the adopted production repository root, after the UTC day closes and
inside the production admitted 00:30–09:00 window. The production operator must
check the current reserved-window and host-load contracts first. `scratch` must
already exist and the named output directory must not. This command is diagnostic
export only; no registration or policy-comparison flag is involved.

```powershell
$replayRepo = (Get-Location).Path
. .\scripts\ops\workload_admission.ps1
$replayLease = Enter-WeatherHeavyWorkloadLease -RepoRoot $replayRepo -Workload 'maker_replay_bundle_export'
if ($null -eq $replayLease) { throw 'Heavy-work lease unavailable' }
try {
    & .\venv\Scripts\python.exe -B -m weather.market.maker_replay_bundle bundle --date 2026-09-26 --data-root .\data --markets nyc --out .\scratch\maker-replay-bundle-20260926-nyc --max-input-bytes 1073741824 --max-output-bytes 67108864 --max-records 100000 --max-seconds 300
    if ($LASTEXITCODE -ne 0) { throw "Bundle export refused: $LASTEXITCODE" }
}
finally { Exit-WeatherHeavyWorkloadLease -Lease $replayLease }
```

The workstation's standalone heavy-module allowlist still needs an operations-owned
reviewed addition for replay/export. This mission did not change admission or
invoke these modules through a bypass; all implementation execution used fixture
tests under `workstation_heavy.ps1`. The command above is for the production
operator's distinct admitted lane, not authorization to run it on this workstation.

### Continuation roll classification per file

Production closure evidence is unavailable locally. The source classifications
below are therefore **UNDECIDABLE**, not an inferred roll-free verdict. The final
production `roll_verdict.ps1` covers the topic plus all inherited dependencies.

| File | Classification |
| --- | --- |
| `src/maker_core/replay/_fill89a.py` | UNDECIDABLE; copied offline kernel |
| `src/maker_core/replay/authorization.py` | UNDECIDABLE; reviewed hash gate |
| `src/maker_core/replay/baselines.py` | UNDECIDABLE; offline controls |
| `src/maker_core/replay/bundle.py` | UNDECIDABLE; neutral reader |
| `src/maker_core/replay/diagnostics.py` | UNDECIDABLE; diagnostic output |
| `src/maker_core/replay/engine.py` | UNDECIDABLE; pure replay |
| `src/maker_core/replay/fill_model.py` | UNDECIDABLE; fill facade |
| `src/maker_core/replay/inference.py` | UNDECIDABLE; clustered inference |
| `src/maker_core/replay/parity.py` | UNDECIDABLE; trace comparator |
| `src/maker_core/replay/payloads.py` | UNDECIDABLE; typed decoder |
| `src/maker_core/replay/report.py` | UNDECIDABLE; report composition |
| `src/maker_core/replay/score.py` | UNDECIDABLE; accounting |
| `src/maker_core/replay/__main__.py` | UNDECIDABLE; CLI |
| `src/weather/market/maker_replay_bundle.py` | UNDECIDABLE; offline exporter |
| `tests/maker_core/fixtures/fill89a_reference.py` | Test-only unchanged 89a reference |
| `tests/maker_core/fixtures/replay_scenario.py` | Test-only fictional captures |
| `tests/maker_core/test_replay_baselines.py` | Test-only |
| `tests/maker_core/test_replay_engine.py` | Test-only |
| `tests/maker_core/test_replay_fills.py` | Test-only |
| `tests/maker_core/test_replay_inference.py` | Test-only |
| `tests/maker_core/test_replay_report.py` | Test-only |
| `tests/maker_core/test_replay_score.py` | Test-only |
| `tests/market/test_maker_replay_bundle.py` | Test-only |
| `README.md` | Roll-free documentation |
| `docs/operations/maker-replay-bundle.md` | Roll-free contract |
| `docs/operations/package-boundaries.md` | Roll-free ownership map |
| `docs/roadmap/correspondence-index.md` | Roll-free generated index |
| This report | Roll-free report |

Final verification and publication evidence follows after the required audits.

### Final verification

The admitted full selected matrix returned **1,169 passed, 13 skipped, 1 failed**.
The sole failure was the generated correspondence index becoming stale as this
report acquired citations. Regeneration and the exact failed audit recheck passed.
The skips remain the twelve unavailable full RE-1 minute journals plus Windows
symlink-creation privilege. All four required repo audits passed, including schema,
import architecture (maker-core boundary and negative controls), agent docs, and
path policy. These are the selected repository audits, not a claim that every
test in the repository or hosted CI ran.

Final source review corrected expiry for delayed paired-book captures: the
60-second limit now starts at the book's original as-of clock, not its envelope
arrival. The new case and replay/baseline/fill/scorer regressions returned
**38 passed**. Across the selected matrix and that additional case, **1,171 distinct
checks passed**, with the 13 stated skips. Admitted `compileall -q app src tests`
passed. The documentation index was regenerated by its owning deterministic
generator; no hand-edited index or changed audit/admission gate was used.

All six requested implementation increments were pushed in order without pausing
between them: `f4b68464`, `d6e732d9`, `23ce28ee`, `b9b3ea21`, `87865935`, `87afb7a2`.
The final origin fetch still showed master `965374a0` without integration
`8180404a0` as an ancestor; no speculative master merge was performed. Keep the
draft PR open for review and production qualification. No source from 89a or the
loop-imported reward/markout modules was edited; copied facades keep the core free
of weather imports.

**Remaining acceptance limitations:** full-session RE-1 parity needs the separately
authorized sanitized journal export; the owner must approve/sign and pin an exact
registration before any real-data comparison; standalone workstation admission
needs its operations-owned review; production daily size/coverage and mechanical
roll classification remain unmeasured. Fixture success is not an economic or
live-readiness verdict. No production data, credentials, `.env`, venue, Scheduler,
live action, deployment, or master mutation occurred.

### Publication receipt

Final source/export closeout **`6c18e4abfbb773072ed0ffec0dac2f42ced18d27`** was
pushed and independently matched against `git ls-remote origin` for the requested
branch. The worktree was clean. Draft PR **#100** was updated in place and remains
draft, with its original weather-plugin base. No PR merge or production adoption
was performed.

Mechanical local `roll_verdict.ps1 -Branch codex/maker-replay-harness-20260926
-Base e3274ea7c` returned exit 1, **UNDECIDABLE: no live closure evidence**, listing
the same four absent supervisor/enrichment status files. No production evidence
was copied to change it. The production operator must obtain the real verdict
before adoption. Cleanup checked nine named pytest temporary targets: seven
directories were removed and two were already absent. Every existing target
passed exact-path, non-redirected Temp-root checks before removal.

## Recorded-session qualification — 2026-09-26 owner authorization

**NOT QUALIFIED. All twelve recorded attempts were tested; ten projected traces differ and no full lifecycle is qualified.**
This continuation starts at `ed6d43260` on `codex/maker-replay-harness-20260926`. The owner explicitly authorized read-only
workstation RE-1 journal access solely for this parity test, minimal fixture publication, repository audits, push, and draft
PR #100 update. No policy, quote kernel, live controller or guard was changed to make a decision match.

### Source and guard qualification

The campaign-analysis handoff identified the older analysis copy. Source inspection of
`2b9a0ca9e:src/weather/market/re1_attended_cli.py` and `re1_evidence.campaign_root()` located the fixed workstation profile
campaign root, `.weather-re1m-20260921`. Only the explicit `session-1` through `session-12` **journal.jsonl** files were
read. The older copy ends at attempt 9 and was not used. No `.env`, key, credential, selection, prediction, reconciliation
or user-stream file was opened; the already-tracked public selection fixture supplies its previously hashed price control.

Every journal passed the original RE-1 `SecretGuard` before use. The retained exporter freezes that class unchanged at
`2b9a0ca9e586d510b4aa879fad8f0e7331cfe2c8`; an AST comparison against the pinned Git source passed. It refuses a guard
change rather than silently scrubbing, verifies every hash-chain link, and repeats guarded hashing to prove stable inputs.
All twelve original SHA-256 values equal the earlier selection fixture's journal bindings. Their hashes, sizes, row counts
and every minute's source sequence are retained in
[the minimal fixture](../../tests/maker_core/fixtures/re1_sessions.json).

An additional substring check stopped on `rows.[].lifecycle_key`. The owner first authorized field-name-only classification;
no value was printed. Pinned `mm_official_adapter.py` assigns this field from `order_id` on normalized official order/trade
events. Automatic approval review correctly rejected resumption under classification-only authority. The owner then
explicitly approved resumption with this exact exception: same `order_id`, official normalized user-stream source, and
order/trade event type. The original SecretGuard remains unchanged, other suspicious fields/values still stop, and both
identifiers are absent from the fixture. The final retained exporter reproduced the complete projection byte-for-byte,
and the core's output SecretGuard also left it unchanged. This is an audited false-positive disposition, not a secret waiver.

### What the byte comparison means

RE-1 did not record native `QuoteDecision` objects. The test therefore compares **canonical JSON bytes of the common
action/legs projection**, not bytes of SDK payloads or reconstructed native decisions. Each recorded minute retains its
public books, reward terms, prices, affected leg indices and original capture clock. `at` is the preceding `market_snapshot`
record clock (when `observe()` runs), rather than the later `minute` record after potentially slow accrual/account calls.
Both clocks and source sequence are retained. No minute is resampled; attempt 6's two `minute_missed` events remain missing.

The driver executes the existing `blind_re1` `decide()` kernel on all twelve price controls, then each recorded minute,
carrying **its own** legs forward. Expected recorded legs never reset the carried path. An independent recorded-state
diagnostic separates the first local policy defect from later divergent state. RE-1's requote requests first cancel affected
legs; both controllers cancelling both legs is compared as `CANCEL`, not falsely failed on `REQUOTE` versus `CANCEL`
vocabulary. The partial-leg cancellation remains a genuine mismatch. Replacement/ack timing is not manufactured.

Terminal `fill_seen` is supplied as a recorded account input and exercises `FIRST_FILL_ENDS`; its projected reason is `fill`.
This is **conditional termination parity, not a fill-model test**. Other terminal reasons remain `UNSUPPORTED` on the actual
side and cannot match by construction from a quote-only kernel. The original reasons are retained unchanged on the expected
side. The driver is an offline kernel/session diagnostic, not a replay of the venue transport or the UTC-day bundle engine.

Explicit neutral scaffolding: selection capture time is absent from the older price fixture, so its price-only control gets
a neutral clock; domain/order identities are placeholders; market minimum is 1 (below all treatments); horizon is 2 (ignored
by blind); close is fixed session-end plus one day; and available cash/band/event/wallet caps are the treatment size, with
order cap 0.8 times size. These isolate quote/hold behavior without exporting balances. They cannot qualify historical
market-close or account-budget gates. Sequential posting, fresh-ask checks, transport failures, cancel acknowledgments,
heartbeat termination and cleanup remain uncovered. Zero recorded minutes never becomes a parity pass.

### Per-session result

"Equal bytes" covers all retained minutes plus the terminal projection. Initial selection prices match in all 12 attempts.
Every expected/actual trace SHA-256, mismatching minute index, first divergence and local reason count is in
[the findings artifact](../../tests/maker_core/fixtures/re1_session_findings.json); the fixture records every source SHA-256.

| Attempt | Launched session | Equal minutes / recorded | Terminal reason | Terminal projection equal | Equal bytes | Full session |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 37 / 42 | fill | yes, conditional | no | FAIL |
| 2 | 2 | 0 / 0 | fresh_ask | unsupported | no | INCOMPLETE |
| 3 | none, opening refused | 0 / 0 | fresh_ask_before_post | unsupported | no | INCOMPLETE |
| 4 | 3 | 2 / 2 | cancel_not_terminal | unsupported | no | INCOMPLETE |
| 5 | 4 | 70 / 88 | fill | yes, conditional | no | FAIL |
| 6 | 5 | 51 / 56 | heartbeat_stale | unsupported | no | FAIL |
| 7 | 6 | 0 / 0 | exception | unsupported | no | INCOMPLETE |
| 8 | 7 | 2 / 2 | fill | yes, conditional | yes | INCOMPLETE |
| 9 | 8 | 13 / 13 | fill | yes, conditional | yes | INCOMPLETE |
| 10 | 9 | 38 / 38 | exception | unsupported | no | INCOMPLETE |
| 11 | 10 | 0 / 0 | unexpected_open_orders | unsupported | no | INCOMPLETE |
| 12 | 11 | 14 / 72 | fill | yes, conditional | no | FAIL |

**227/313 minute decisions match; 86 differ on the carried path.** Two defects explain the first policy divergences:

- `SHARE_BELOW_PULL_FLOOR`: the shared kernel pulls below 5% even for blind RE-1; the recorded RE-1 `observe()` computes
  share but never applies this pull. First divergences: session 1 minute 38, session 5 minute 52, session 11 minute 15.
  Recorded-state diagnostics find 38 such local differences across sessions 1, 4, 5 and 11. Later carried differences include
  cancellation/re-entry state, so 86 is not a count of independent policy defects.
- Session 4 minute 71 (attempt 5, journal sequence 6233): RE-1 cancels only YES (`[0]`), while the kernel cancels both
  (`[0,1]`) under `OUTSIDE_REQUOTE_WINDOW`. RE-1 subsequently replaces only that leg; the carried paths then diverge.
  Session 3's both-leg requote has matching cancellation intent and fails qualification on transport coverage instead.

These findings are retained, not repaired in this qualification task. The twelve former journal-unavailable skips are
replaced with executable source-bound checks. Ten byte-equality cases are **strict expected failures**, so an unexpected
pass demands review; separate unmarked tests reproduce each complete findings record and catch crashes or changed findings.
The two passing byte cases cannot promote full-session status. No economics, model score, confidence interval or alpha spend
was computed; deterministic comparisons do not supply statistical market evidence.

### Reproduction and verification

From the branch root, through `scripts/ops/workstation_heavy.ps1` with the documented literal base64 argument contract:

```text
python -m pytest tests/maker_core/test_re1_parity.py tests/maker_core/test_re1_session_export.py tests/maker_core/test_replay_report.py -q --basetemp <fresh-temp-dir>
```

The ordinary tests use committed minimal fixtures only and need no campaign files or network. Focused result:
**44 passed, 10 xfailed**, all ten representing the explicitly retained byte-parity findings. Guard tests cover refusal before
forbidden-path opens, key/signature/credential detection without value output, hash-chain tampering and the exact lifecycle
identifier exception. The original guard/source, source-stability and exact projection recheck passed separately.
Repository-wide audit/import tests and final compilation/publication evidence are recorded in the closeout below.

The retained explicit-path `project_journals(paths, selections)` helper can regenerate the projection only under the same
owner authorization; it has no default path, live/venue imports or output writes. Its result must be canonicalized before
comparison. Raw journals remain outside Git. Re-running the committed tests needs none of this source access.

### Roll and authority

`src/maker_core/replay/report.py` changes only its truthful qualification message; production closure membership remains
UNDECIDABLE without the mechanical production verdict. All added/changed tests and fixture helpers are offline test-only;
the minimal JSON projections carry no claimed production closure membership. The report, bundle contract and fixture README
are roll-free documentation. No schema registry, admission wrapper, quoting policy or live controller was changed.
No venue calls, orders, cancels, credentials, production/mirror writes, Scheduler action, master merge or runtime adoption
occurred. Source-control publication is only to the authorized topic and existing draft PR #100.

### Recorded-session closeout

The admitted selected matrix completed with **1,209 passed, 1 skipped, 10 xfailed**. It included all `tests/maker_core`,
the weather replay exporter and plugin/dry-run tests, the four repository-wide schema/import-architecture/agent-docs/path
audit files, and roadmap-backlog tests. The sole skip is Windows symlink privilege; the ten strict expected failures are
the named byte-parity findings above. This is selected verification, not a claim that the entire repository suite ran.
`compileall -q app src tests` and both staged/cumulative `git diff --check` passed. Ordinary tests never accessed journals.

```text
python -m pytest tests/maker_core tests/market/test_maker_replay_bundle.py tests/market/test_maker_plugin.py tests/market/test_maker_plugin_dry_run.py tests/operations/test_schema_registry.py tests/operations/test_import_architecture.py tests/operations/test_agent_docs_audit.py tests/operations/test_path_policy.py tests/reporting/test_roadmap_backlog.py -q --basetemp <fresh-temp-dir>
python -m compileall -q app src tests
```

Both commands used the workstation heavy wrapper and its host/principal check, shared mutex and child-tree containment.
The sandbox identity was refused; executing the same wrapper as the attending principal passed, without changing admission.
The inherited integration dependency `8180404a0` remains disclosed; fetched `origin/master` was still `965374a0` and the PR
target remains `codex/weather-maker-plugin-20260925` at `3b8c7b92d`. No dependency or master was merged in this continuation.
The final canonical `agent_docs_audit`, `roadmap_backlog --fail-on-lint --check`, and `correspondence_index --check` CLIs
also passed inside the admitted wrapper. The correspondence index remained current and needed no rewrite.

Source/fixture commit **`4cdabbd4b7a0fa4f91ef4afa64a4a83f769f8592`** was pushed to the requested topic and matched by a fresh
`git ls-remote --exit-code --refs` query. The mechanical local
`roll_verdict.ps1 -Branch codex/maker-replay-harness-20260926 -Base ed6d43260` returned exit 1, **UNDECIDABLE: no live
closure evidence**, naming the four absent capture status files. Production must obtain its own verdict before adoption.
Cleanup checked nine exact task-owned pytest Temp targets: two existed and were removed after parent/reparse checks; seven
were already absent. The raw campaign remains read-only and unchanged. This receipt is a documentation-only follow-up.

## RE-1 behavior port — 2026-09-27 continuation from 0bd7adf98

Owner requested the exact RE-1 behavior rather than adapting the informed kernel to the recorded decisions. Work continued
on the same topic from `0bd7adf98de6c546baa64fff7ee7d45000d7f67e`. Fetch confirmed the RE-1 branch
`codex/re1-wallet-200-20260923` at `2b9a0ca9e586d510b4aa879fad8f0e7331cfe2c8`.
[The source manifest](../../tests/maker_core/fixtures/re1_live_source.json) records SHA-256s for `re1_attended`,
`re1_transport`, `re1_resilience`, `re1_sizing` and `reward_quote`. The source was read through Git, never imported into
the neutral runtime. No credentials, venue calls, orders, cancels or live processes were used.

### Corrected behavior and source evidence

The requested share-floor investigation found **no live RE-1 share-floor pull at any threshold or duration**.
`re1_attended.observe` records share and only requests requotes for distances outside the inclusive 1–3 cent window.
The old replay incorrectly applied the informed profile's immediate 5% pull. The new blind observer keeps the exact
live term/book checks and own-depth aggregation; selection/submit freshness, midpoint-range, touch-buffer and minimum
reward-width gates are not reapplied to resting prices. `informed_v0` retains its existing gates and cooldown.

The offline lifecycle carries its own generated prices and frozen session size. It cancels every affected leg in order,
confirms removal, then posts replacements in order; an unaffected sibling stays active. No 60-second requote cooldown
exists in RE-1. Sampling uses `max(previous + 60 seconds, now + 1 second)`. The controller permits four requote rounds,
ends before the fifth, and consumes at most ten submit attempts, including ambiguous failures. A lost POST acknowledgment
ends the session without retry; a fill during post, cancellation or terminal inventory proof ends it. Cancel confirmation
uses ten reads with one-second waits including the final wait. Missing own posts receive up to ten pre-submit read retries;
foreign orders fail immediately. Heartbeat timing is two seconds after success, one second on transient/resync failure,
eight seconds stale and twenty seconds main-loop stalled. A rotating-ID resync is not an acknowledgment.

Selection retains the size ladder and wallet-minus-ten reserve budget capped at 75. Session submit caps are 0.79 times
size per leg and min(0.98 times size, reserve budget) per pair. Initial paired opening checks, ten-second submit snapshot
freshness, actual post-signing ask checks and the three-minute remaining expiration horizon are exercised separately.
The neutral state machine emits intents only; it does not implement HTTP, account identity/signature verification or
cleanup IO. Six-hour sessions and UTC-day boundaries remain explicit. The historical campaign expiry and owner live
authorization are not authority granted by offline replay.

All twelve original journals were guarded again before projection with the unchanged pinned SecretGuard, the stronger
stop check and the already approved exact `lifecycle_key == order_id` exception. Hash chains and after-read source hashes
passed. The added fixture fields are public submit books/ask minima, anonymous leg indices, acknowledgment booleans,
exception types, and sequence/time boundaries. No order/token/account identifiers or raw payloads survive.

### Qualification by session

The projection compares canonical bytes of every recorded minute's timestamp, action, legs and affected cancel indices,
plus terminal timestamp/action/reason. Terminal timestamps are recorded envelopes, not predicted stop times. Selection
prices are checked separately. Expected minute prices, requote flags and terminal reasons never update carried state;
only generated intents and recorded acknowledgment inputs do. Recorded fill flags condition the first-fill gate and do
not validate a fill model. Source functions are frozen independently and compared against every recorded minute.

| Attempt | Launched session | Recorded minutes matching | Minute/terminal bytes | Remaining cause |
| --- | --- | --- | --- | --- |
| 1 | 1 | 42 / 42 | equal | projection scope only |
| 2 | 2 | 0 / 0 | equal | fresh-ask terminal reproduced; no minute observations |
| 3 | none | 0 / 0 | equal | opening fresh-ask refusal reproduced; no posts |
| 4 | 3 | 2 / 2 | different | legacy cancel-read retry inputs |
| 5 | 4 | 88 / 88 | equal | partial cancellation and replacement carried correctly |
| 6 | 5 | 56 / 56 | different | legacy heartbeat schedule / missing monotonic clock |
| 7 | 6 | 0 / 0 | different | legacy order-decode retry inputs |
| 8 | 7 | 2 / 2 | equal | projection scope only |
| 9 | 8 | 13 / 13 | equal | projection scope only |
| 10 | 9 | 38 / 38 | different | unjournaled RuntimeError detail |
| 11 | 10 | 0 / 0 | different | legacy post-visibility retry inputs |
| 12 | 11 | 72 / 72 | equal | projection scope only |

**313/313 recorded minutes, zero divergent minutes; seven equal projections and five explained terminal differences.**
All 86 prior minute differences are resolved by removing the informed share pull, preserving affected-leg cancellation,
and carrying generated replacements. [Findings](../../tests/maker_core/fixtures/re1_session_findings.json) retain each
session's actual/expected SHA-256 and explicit minute/lifecycle divergence arrays. The
[divergence ledger](../../tests/maker_core/fixtures/re1_divergence_ledger.json) names each remaining cause, binds it to
the source journal SHA-256 and specific sequences, and cites the source fixes:

- Attempt 4 acknowledged a cancel but exited after one open-order read still listed it (182/186/199; terminal 239).
  `26f60347` subsequently added ten polls. The newer controller needs reads the exited session cannot supply.
- Attempt 6 has a heartbeat request/unavailable boundary (5098/5103; terminal 5152). `f3df6f26` changed five-second
  cadence to two seconds. No monotonic watchdog ticks or responses at the new cadence are retained. Its two
  `minute_missed` records, sequences 351 and 2891, lack books/decisions and are separately excluded from the denominator.
- Attempt 7 stops with `UnexpectedResponseError` after an SDK response but before normalized order response (73/75;
  terminal 118). `f3df6f26` makes that error transient; hypothetical subsequent read outcomes are absent.
- Attempt 10 ends with `RuntimeError` (5369) after successful order/heartbeat boundaries (5323/5326).
  `Session.run` retains the type but no message, traceback or origin. The underlying fault cannot be identified more
  specifically from this journal, and the terminal label is not recycled into an input to force equality.
- Attempt 11 has one acknowledged post (46), then an empty open-order list (63; terminal 96). `10fa052a` adds retries
  for this strict-subset lag; the missing future reads are not fabricated.

The five parity checks use **strict, reasoned xfail**, not plain failures or silent skips. Unmarked checks reproduce the
full findings, require zero unclassified minute/lifecycle differences, and verify ledger/source sequence coverage.
An unexpected parity pass fails strict xfail and requires review. Account/signing bindings, monotonic transport scheduling
and cleanup remain outside the anonymous projection, even for the seven equal traces. Attempts 1/2 predate the paired
opening gate; only their retained checks are replayed.

### Capture-input limit and verification

No 88a-vs-live-book divergence is claimed: these 313 comparisons use the actual journal snapshots. The 88a adapter lacks
private acknowledgments and the actual post-signing live book. It now uses the same blind lifecycle but explicitly records
`RE1_TRANSPORT_ASSUMED` when assuming immediate success and a captured book for the later touch check. Such diagnostic
counterfactuals cannot establish live parity. Capture gaps end that session, and shared portfolio caps still apply.
The CLI remains diagnostic-only by default; scoring admission and the informed policy are unchanged.

Final selected verification: **1,245 passed, 1 skipped, 5 xfailed**. The skip is the documented Windows symlink privilege
case; the xfails are exactly the five named terminal findings. This is a selected regression matrix, not the entire repo
suite. It includes all maker-core tests, weather exporter/plugin/dry-run tests, schema/import-architecture/agent-docs/path
audits and roadmap tests. A final focused runtime/parity check also passed (64 passed, 5 xfailed). All commands ran through
`scripts/ops/workstation_heavy.ps1` with host/principal admission, shared mutex and child-tree containment.

```text
python -m pytest tests/maker_core tests/market/test_maker_replay_bundle.py tests/market/test_maker_plugin.py tests/market/test_maker_plugin_dry_run.py tests/operations/test_schema_registry.py tests/operations/test_import_architecture.py tests/operations/test_agent_docs_audit.py tests/operations/test_path_policy.py tests/reporting/test_roadmap_backlog.py -q --basetemp <fresh-temp-dir>
python -m compileall -q app src tests
python -m weather.operations.agent_docs_audit
python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
python -m weather.reporting.roadmap.correspondence_index --check
```

Compilation and all three canonical CLI audits passed. A separate comparison to `0bd7adf98` proved that **every original
expected projection field is unchanged** after removing the two added lifecycle/evidence fields. Another independent
comparison executed that commit's pure policy and confirmed **59 informed-policy cases byte-identical**, spanning reward
width, depth, fill hazard, resting/initial state, stale inputs, first fill and horizon refusal. These checks do not consult
local campaign data. Staged and cumulative whitespace checks passed; cumulative ancestry/diff review retained the declared
integration dependency `8180404a0`. Refreshed parent remains `3b8c7b92d`, and `origin/master` remains `965374a0`.

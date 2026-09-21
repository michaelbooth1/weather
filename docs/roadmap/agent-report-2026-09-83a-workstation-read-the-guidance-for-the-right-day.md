# Mission 2026-09-83a — read the guidance for the right day

**PARTIAL — parser repair and versioned replay implemented; NOT READY FOR HOST
QUALIFICATION. The required manifest fields and cross-pass download budget
cannot be completed inside the assigned file boundary. The repository parity
control still reports BLOCK for its four established defects. No gate was
relaxed or re-baselined.**

Branch: `codex/nbm-target-fix-20260921`. Base: fetched `origin/master`
`e28530af67c7371fc7b2c08bbd0e26cfe72a28f9`. Handoff/82a input:
`f80924693ba26f5f6ba7d6ba15a840e7dc74a768` on
`codex/nbm-target-fix-handoff-20260921`. Only the needed station fixtures were
copied; the research branch was not merged. The tested implementation commit is
`d7cc92b7c79574a3c75d057b2135e11f9a8600aa`.

## Exact remaining scope

1. `src/weather/collection/snapshot_store.py`: its `FORECAST_PAYLOAD_COLUMNS`
   and `write_forecast_payloads` construct a fixed manifest projection. They
   persist parser version, issue and provider valid times, but omit period
   kind, group/token, cycle age, raw TXN values and rejection reasons. National
   CAS stores only the bulletin body. Adding fields to the raw wrapper does
   not retain those fields in that manifest. Floor-filtered values/reasons
   need an explicit join from the existing feature diagnostics, without
   mutating captured inputs. This writer is outside mission ownership.
2. `src/weather/collection/forecast_payload_fetch_fanout.py`: receipt identity
   includes the capture-pass scope. A new scope fetches the same cycle again
   even when its verified national blob already exists. A reviewed cross-pass
   request/cycle index with age, integrity and truthful network attribution is
   needed. The cheaper alternative is an explicit target-date/version-bound
   prefetch cache policy; the current 120-minute source TTL is failure fallback,
   not a national-fetch cache. No new cache contract was invented here.
3. The parity CLI's existing known-defect manifest remains BLOCK, not a proof
   that corrected guidance is train/serve qualified. It has 100 known blocking
   findings, zero unexpected blocking findings and zero coverage blockers.
   The historical extractor still defaults live-only NBM fields to missing;
   a future training admission/loader contract is needed before claiming those
   rows are training-ready. No fit, candidate or training-gate exemption was
   attempted.

[The fixture-only contract probe](nbm-target-fix-20260921/contracts.json)
exercised the actual writer and cross-process fan-out: eight manifest rows
all lack six requested token fields; two consecutive scopes invoked the fake
network callback four times while producing only two distinct CAS blobs.
That is a failed acceptance contract, despite passing regression tests.
Production must not adopt this partial branch as the complete repair.

## P0 — publication and completeness

NOAA's [v5 text-product key](https://vlab.noaa.gov/web/mdl/nbm-textcard-v5.0)
describes complete elements at 01/07/13/19Z, some elements at 00/12Z, and
limited elements at other hours. These statements do not mean that TXN is
absent at 00/12Z. The retained September 17 00Z and 12Z KLGA blocks both
contain all seven TXN rows. 00Z carries today's maximum; 12Z starts with
tomorrow's minimum and has no today's maximum. The candidate list therefore
includes 00/01/07/12/13/19Z, with target-aware filtering.

Four additional cycle URLs were checked serially: 00Z and 12Z succeeded
(27,547,325 and 27,537,738 bytes); 02Z and 18Z returned 404 from NOAA's public
S3 archive. The first 02Z 404 interrupted the diagnostic before error receipts
were added; it was retried once. Thus five HTTP requests, two national
downloads, no national refetch, within the six-request allowance. Subsequent
diagnostics reused the cached bytes and cached 404 receipts. This does not
establish permanent nonpublication of every unsampled hour: those hours are
not evidenced as complete-TXN cycles. Source URLs, times and hashes are in
[P0](nbm-target-fix-20260921/p0.json); no production data or mirror was read.

Completeness defect confirmed with a real block: the same 00/12Z files contain
PGUM blocks with no TXN rows at all, yet version 1 marks the target available
with five null percentiles. These [small blocks](../../tests/fixtures/nbm_target_fix/p0/20260917T00Z-PGUM.txt)
are retained. Deterministic controls also remove each required row from a
configured station and test the -99 sentinel. Version 2 rejects incomplete rows.

## P1 — slot rule and station-local date

Version 2 selects exactly one FHR token valid at 00Z, requires all seven TXN
values, and assigns it to the local daytime date shared by the 12Z window
start and the 00Z label. NOAA's extreme window ends at 06Z the following day;
it is supporting daytime guidance, not an exact midnight-to-midnight
settlement maximum. For all eleven configured US stations, the label and
window start share the preceding UTC date in both standard and daylight time.
Missing target, missing data or unqualified geography returns unavailable,
never a minimum or a different target. The observed-high floor and tolerance
remain unchanged. Version 1 is callable explicitly with its original rule.

| Zone | Maximum window in standard time | In daylight time | 00Z label |
| --- | --- | --- | --- |
| Eastern (NYC, Atlanta, Miami) | D 07:00–D+1 01:00 | D 08:00–D+1 02:00 | D 19:00 / 20:00 |
| Central (Austin, Chicago, Dallas, Houston) | D 06:00–D+1 00:00 | D 07:00–D+1 01:00 | D 18:00 / 19:00 |
| Mountain (Denver) | D 05:00–23:00 | D 06:00–D+1 00:00 | D 17:00 / 18:00 |
| Pacific (LA, San Francisco, Seattle) | D 04:00–22:00 | D 05:00–23:00 | D 16:00 / 17:00 |

All configured US stations are unambiguous under that daytime naming rule.
Unknown station geography fails closed. Tests cover January, September and
both 2026 clock-transition dates. Toronto remains outside this US source.

## P2 — fetch budget

The newest eligible same-day cycle from 12Z onward is 07Z; tomorrow stays on
the newest complete-TXN cycle. HTTP 403/404 still falls through; incomplete
station guidance still falls through. The existing fan-out and shared payload
store remain in use, with no national files copied into Git.

| Scenario | Before | After (this partial branch) |
| --- | --- | --- |
| Healthy pass, only same-day targets after 13Z | 1 national file (wrong period) | 1 national file (07Z maximum) |
| Healthy pass, today and tomorrow after 13Z | 1 shared national file | 2 shared national files |
| Two distinct healthy pass scopes in one two-hour period, both targets | 2 callbacks | 4 callbacks; 2 distinct blobs |
| Worst-case candidate HTTP attempts per target, 24-hour inclusive search | 25 | at most 7 |
| Worst-case national responses per pass, assuming only the six evidenced issue hours publish | at most 7 distinct files | at most 7 distinct files |

The first two rows are exact fixture-path behavior. The two-scope repaired
count is measured by the retained probe; the old count follows the unchanged
legacy first-available selection and one shared scope receipt per cycle. The
worst-case HTTP bounds are algorithmic, not network-performance estimates;
if any of the other hours publish a usable old response the old upper bound
is 25. The old parser can stop at a slot even with null values, so its observed
cost may be lower for the wrong reason.

For K successful scopes during a two-hour period, the common two-target
pattern is K before versus 2K after. The extra K downloads exceed the allowed
one when K > 1. No compliant two-hour bound is proved. Persistent reuse is the
preferred repair; alternatively, an explicitly reviewed refresh/coalescing
policy could bound K. Neither is silently substituted in this branch.

## P3/P4 — provenance, replay and verification

Payloads record parser, issue/valid times, period kind, group/token, cycle age,
station timezone, raw TXN values and provider rejection reasons. Features add
four numeric provenance columns; existing names, units and dtypes are retained.
The feature schema advances to v1.17 and retains v1.16 as legacy. Registry
change is **not additive-only**: it changes the active feature-schema version.
No artifact file or selector was changed. The manifest gap above remains.

Shared replay and station-archive replay dispatch by recorded parser version;
absence means v1. Migration call sites pass it through. A real 13Z v1 record
reproduces p50=72 and tomorrow's 12Z validity exactly; v2 rejects that same-day
request. A 07Z v2 record reproduces its own maximum and provenance. Swapping
recorded versions fails the archive provenance check, even when temperature
values coincide. An old CSV header is not rewritten: appending new columns
requires a fresh station-archive root.

- Initial focused parser/fetch/floor checks: **155 passed**.
- Required parity, captured-input hash/replay, shared payload/persistence,
  migration and density replay tests: **91 passed**. First attempt: 19
  Windows path-length failures in CAS staging; same tests and assertions with
  `C:/tmp/83g2` passed. No CAS code, gate or baseline changed.
- Repository parity CLI: **BLOCK**, four of four known defects rediscovered,
  100 known blocking findings, zero unexpected findings and zero coverage
  blockers. It compared 225 features, covered 12 markets and 29 cases.
  [Full receipt](nbm-target-fix-20260921/train-serve-feature-parity.json).
- Final combined checks and documentation verification are recorded in the
  publication receipt below. No full-suite or host-qualification PASS is claimed.

## P5 — shadow inputs only

Read-only SHA-256 verified LFS object
`3b472bd32667256c6605a6f48c2c9c4ba7e58f140a89c504c4b4fbfcac6a497c`
(`feature_model_hgb_f_pooled_v0_3.pkl`, 6,310,781 bytes): **14 hourly bundles,
cutoffs 7 through 20, each selecting all 15 NBM columns**. No other bundle
selects them. [Selectors](nbm-target-fix-20260921/selectors.json).

The [complete input table](nbm-target-fix-20260921/inputs.csv) contains 1,320
feature comparisons: 44 September 17 station/cycle blocks × 15 columns × two
synthetic floor contexts. All 11 US stations and 01/07/13/19Z are covered.
Forecast high is fixed at 85°F; floor is absent or fixed at 80°F. These are
fixture contexts, not observed highs, outcomes or production forecasts.

Example: KLGA, 13Z September 17, target September 17, synthetic floor 80°F
and forecast high 85°F. `unavailable` denotes the same-cycle source; the live
search then goes to 07Z, rather than using the values below.

| Input suffix (`nbm_prob_tmax_`) | v1 | v2, same cycle |
| --- | --- | --- |
| p10 | dropped | unavailable |
| p25 | dropped | unavailable |
| p50 | dropped | unavailable |
| p75 | dropped | unavailable |
| p90 | dropped | unavailable |
| mean | dropped | unavailable |
| stddev | 1 | unavailable |
| iqr | 1 | unavailable |
| p10_p90_spread | 2 | unavailable |
| p50_vs_forecast_high | dropped | unavailable |
| p90_vs_forecast_high | dropped | unavailable |
| exceed_forecast_high | dropped | unavailable |
| physical_valid_flag | 0 | 0 (missing-guidance diagnostic) |
| impossible_flag | 1 | 1 (missing-guidance diagnostic) |
| floor_gap | -7 | unavailable |

The owning [source contract](../operations/nbm-target-period-contract.md)
records the shadow's input-regime boundary and future provenance admission.
Rows before and after that boundary must not be pooled. Active shadow status
on production is a supplied handoff fact, not workstation runtime attestation.

## Roll verdict and exclusions

`scripts/ops/roll_verdict.ps1 -Branch codex/nbm-target-fix-20260921 -Base origin/master`
returned **UNDECIDABLE: no live closure evidence**. All four required local
status files are absent. No mirror or production connection was used to fill
that gap. Per-file closure memberships must remain unverified; the publication
receipt inventories every file. Treat as roll-sensitive; production reruns
the tool and its bounded suite before any quiet-window adoption.

**Not done:** no model fit, candidate, forecast proposal, prediction/scoring,
Brier, probability evaluation, artifact rewrite, retirement, promotion, floor
weakening, alpha spend, outcome read, reservation change, paid source,
credential access, exchange call, production write, Scheduler registration or
mutation, capture restart, production merge, or master merge. No full-suite or
production-readiness claim. All source worktrees and prior evidence preserved.

## Reproduction on the workstation

Use PowerShell, from this worktree. All heavy commands use the required wrapper.
Fresh output/temp paths are mandatory; retain the national cache.

```powershell
$repo = 'C:/Users/Michael/Documents/github/weather/scratch/w/nbm-target-fix-20260921'
$python = 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe'
$cache = 'C:/Users/Michael/Documents/github/weather/scratch/nbm-target-trace-20260921/cache'
function Invoke-83a([string]$Kind, [string[]]$Tokens) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
        (ConvertTo-Json -InputObject $Tokens -Compress)))
    & "$repo/scripts/ops/workstation_heavy.ps1" -Kind $Kind -PythonPath $python `
        -ArgumentsBase64 $encoded -RepoRoot $repo
}
Invoke-83a weather_heavy @('-m','tools.research.nbm_target_fix','p0',
    '--cache',$cache,'--output',"$repo/scratch/p0-reproduce")
Invoke-83a weather_heavy @('-m','tools.research.nbm_target_fix','contracts',
    '--output','C:/tmp/83-contract-reproduce')
Invoke-83a weather_heavy @('-m','tools.research.nbm_target_fix','p5','--artifact',
    'C:/Users/Michael/Documents/github/weather/.git/lfs/objects/3b/47/3b472bd32667256c6605a6f48c2c9c4ba7e58f140a89c504c4b4fbfcac6a497c',
    '--output',"$repo/scratch/p5-reproduce")
Invoke-83a weather_heavy @('-m','weather.reporting.scorecards.train_serve_feature_parity',
    '--input',"$repo/tests/fixtures/train_serve_feature_parity_known_defects_v0.1.json",
    '--run-root',"$repo/scratch/parity-reproduce") # Expected BLOCK; do not suppress it.
```

Exact final test commands and cleanup disposition are in the publication receipt.
There is no forecast-skill estimate, interval, power calculation or alpha spend:
the station fixtures have one issue-date cluster and 11 market clusters, and
the tables describe parser inputs only.

## Publication receipt

Implementation commit: `d7cc92b7c79574a3c75d057b2135e11f9a8600aa`.
This report-only follow-up records its identity without changing tested code.

- Combined final regression command: **350 passed in 14.00 seconds**, no skips
  or expected failures. This includes all 91 mandatory parity/replay/migration
  controls. The preceding combined run had two failures: a new test read the
  wrong diagnostics dictionary, and the architecture test required new files
  to be staged. The test now uses the existing diagnostics API; exact-path
  staging satisfied the tracking contract. Neither production gate changed.
- The first final-run launch was refused because another workload held the
  shared lease. Retrying the unchanged admitted command succeeded; no lease
  was cleared or bypassed.
- Wrapped compileall: PASS. Agent documentation audit: PASS (18 agent files,
  890 Markdown files). Roadmap lint/generated-backlog check: PASS.
- `git diff --check` finds only upstream trailing spaces in the four newly
  extracted fixed-width P0 station blocks. Those spaces are retained with the
  evidence; all other paths pass. No whitespace rule was changed.
- [Verification command receipt](nbm-target-fix-20260921/verification.json)
  retains exact tokens, results and prior failure causes. The pytest XML is
  retained locally at `scratch/qualification-final.xml`.
- [Per-file roll inventory](nbm-target-fix-20260921/roll-inventory.json) and
  [tool output](nbm-target-fix-20260921/roll-verdict.txt): **UNDECIDABLE** because
  all four live closure records are absent. Memberships remain null; none was
  guessed. Production must obtain its own roll verdict and bounded-suite result.
- Archive version identity and first-capture immutability are covered by the
  final test run: reusing national bytes under v2 cannot overwrite v1, and a
  repeated v2 capture retains the first wrapper and its recorded cycle age.

Final checks reproduce with the `Invoke-83a` function above and the exact test
file list in `verification.json`:

```powershell
$receipt = Get-Content "$repo/docs/roadmap/nbm-target-fix-20260921/verification.json" -Raw |
    ConvertFrom-Json
Invoke-83a pytest (@('-m','pytest','-q') + @($receipt.test_files) +
    @('--basetemp','C:/tmp/83-final-reproduce'))
Invoke-83a compileall @('-m','compileall','-q','app','src','tests',
    'tools/research/nbm_target_fix.py')
& $python -m weather.operations.agent_docs_audit
& $python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
& "$repo/scripts/ops/roll_verdict.ps1" -Branch codex/nbm-target-fix-20260921 -Base origin/master
```

These are workstation reproduction commands, as this handoff requests, not
production heavy-work authority. The source worktree, cached national files,
original failure receipts, and retained diagnostics remain in place. The five
verified pytest basetemp directories were removed after retaining results:
`scratch/pytest-focused-1`, `scratch/pytest-gates-1`, `C:/tmp/83g2`,
`C:/tmp/83q1`, and `C:/tmp/83q2`. `C:/tmp/83probe1` retains the contract probe.

# Workstation report 2026-08-06 — re-specify the maker settlement gate

## Verdict

**NO-GO: the cadence-derived threshold is `0.000 s`, the `-09-18a` 2.165004-second
settlement gap remains FAIL, and the bound receipts cannot prove gap emptiness. Do not register or
start `WeatherMakerExecutionCapture`.**

The proposed materiality exception is not implementable on the retained evidence. Two distinct
San Francisco trades in the existing execution tape carry the same millisecond exchange timestamp,
so trade cadence supports no positive duration below which a fill is implausible. Independently,
all 60 bound session receipts omit quote, decision, fill, resting-state, and gap-proof fields. They
prove that public executions observed while connected were bound to the tape; they cannot positively
prove that nothing happened while disconnected.

The frozen rule is therefore:

| Rule field | Frozen value |
| --- | ---: |
| Maximum total unplanned gap duration in a settlement period | **`0.000 s`** |
| Maximum unplanned gap count in a settlement period | **`0`** |
| Emptiness requirement | Every gap must positively prove no resting quote, decision, or fill; current receipts do not |
| Overlap treatment | Any overlapping decision, quote, or fill must be uncountable and excluded; current receipts cannot bind this exclusion |
| Carry-forward requirement | The bound evidence must retain the complete gap inventory; schema `mm_execution_capture_bound_session_v0.1` does not |

This rule does not relax the existing continuity gate. That is the correct outcome: changing a
threshold to admit the known gap would violate the handoff's anti-tuning control and the delegation
contract. No new soak was started because a clean night would only reproduce the rejected lottery
and would not exercise the missing emptiness proof.

## Anti-tuning order

| Event | Timestamp |
| --- | --- |
| Rule and threshold commit | `f2e27e21c2b64df119eb6e1d61203a9aa4682470` (`2026-08-06T10:38:42-04:00`) |
| First push containing the frozen rule | `2026-08-06T14:38:56.9232344Z` |
| Earliest receipt in a new soak | **NONE — P1 was not run and no new soak evidence exists** |

The rule text and threshold were frozen in the first report commit. A follow-up provenance-only
commit fills the commit and push fields above; it does not alter the rule.

## P0 — cadence derivation

### Corpus and support

The load-bearing corpus is the already-retained `-09-18a` execution-only CLOB tape. The historical
raw CLOB tape was measured as a second, earlier regime rather than substituted for the current tape.

| Corpus | Support | Trades | Within-file/session adjacent intervals | Result |
| --- | --- | ---: | ---: | --- |
| Historical `market_ws.jsonl` | D=20 target dates, M=12 markets, 182 market-days; 265 files; 9,269,401,117 B | 411 | 229 | 0 same-ms; minimum positive interval `0.070 s` |
| `-09-18a` `mm_execution_tape.csv` | D=1 target date, M=12 markets, 12 market-days; 12 files; 1,416,029 B | 1,802 | 1,761 | **2 same-ms intervals**; minimum positive interval `0.001 s` |
| Combined descriptive support | D=21 target dates, M=12 markets, 194 market-days | 2,213 | 1,990 | **Observed minimum `0.000 s`** |

The canonical execution-tape path/size/file-SHA-256 manifest hashes to
`eb89c301b333306d6b0bdc90405bbd2097974a5a30c840ec95180f0caa529199`. The separate
265-file normalized CLOB CSV manifest hashes to
`e635bfe72f33cb3066dd0abea57a0d450c0533bf5ef7517282db3f6a0ab87de9`.

Intervals were calculated per market and, for the execution-only tape, within WebSocket session.
They never span a reconnect. Exchange timestamps are authoritative for the current tape and have
declared `0.001 s` precision. Distinct transaction hashes at the same exchange millisecond are
distinct trades, not duplicate rows:

| Market | Exchange timestamp ms | Transaction A | Transaction B |
| --- | ---: | --- | --- |
| San Francisco | `1785968774140` | `0x87d2461fbb8f768d42e4903d0b9d0a7f5ff3f0ef228d903b3ce6af32e8d29005` | `0x8cf845fb67b5b03c641beda657b3e62fd956ca4bcb1b77c4f3b867a9c89c2184` |
| San Francisco | `1785968828328` | `0x0cc965ca7f7efc55106a72a5472767eafdcae555323b141c8a161ee75c17f4f7` | `0x19b1340df8640d33f4ec2c39cee619e5c66895ea47d9a916cb7707ff35bddd1d` |

The current-tape per-market result is:

| Market | Trades | Adjacent intervals | Zero intervals | Minimum positive (s) | 1st percentile positive (s) | Median positive (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Atlanta | 13 | 9 | 0 | 0.031 | 2.967640 | 106.623000 |
| Austin | 162 | 159 | 0 | 0.021 | 0.024740 | 7.837000 |
| Chicago | 80 | 77 | 0 | 0.024 | 0.043000 | 15.616000 |
| Dallas | 93 | 90 | 0 | 0.176 | 0.189350 | 42.403500 |
| Denver | 247 | 243 | 0 | 0.003 | 0.003420 | 6.325000 |
| Houston | 34 | 30 | 0 | 0.138 | 0.197160 | 171.124000 |
| Los Angeles | 74 | 71 | 0 | 0.367 | 1.904200 | 2.954000 |
| Miami | 121 | 116 | 0 | 0.007 | 0.008900 | 0.913500 |
| NYC | 33 | 31 | 0 | 0.002 | 0.109100 | 213.862000 |
| San Francisco | 372 | 369 | **2** | 0.002 | 0.003000 | 2.572000 |
| Seattle | 487 | 484 | 0 | 0.001 | 0.003830 | 3.649000 |
| Toronto | 86 | 82 | 0 | 0.341 | 0.361250 | 69.201500 |
| Fleet | 1,802 | 1,761 | **2** | 0.001 | 0.004580 | 4.640000 |

The threshold uses the observed minimum including zero, not the 1st percentile or the known
2.165004-second gap. This is a deterministic corpus floor, not a population-effect estimate; no
confidence interval is claimed. The support is reported by date and market, and the single-date
current corpus is too weak to justify generalising upward. Crossed date × market resampling cannot
turn an observed same-millisecond pair into positive timing resolution.

### Consequence for `-09-18a`

`2.165004 s > 0.000 s`, so the settlement-period result remains **FAIL**. The other recovered gaps
also exceed the threshold:

| Gap | Start UTC | End UTC | Duration (s) | Disposition |
| ---: | --- | --- | ---: | --- |
| 1 | 2026-08-05T22:33:11.127042Z | 2026-08-05T22:33:14.965216Z | 3.838174 | FAIL |
| 2 | 2026-08-05T22:59:00.045104Z | 2026-08-05T22:59:02.078428Z | 2.033324 | FAIL |
| 3 | 2026-08-06T04:08:24.636461Z | 2026-08-06T04:08:26.801465Z | **2.165004** | **FAIL; settlement window** |
| 4 | 2026-08-06T04:31:08.759549Z | no fleet-ready recovery before 2026-08-06T04:40:01.276466Z | at least 532.516917 | FAIL |

## P0 falsifier — gap emptiness is not provable

The 60 receipts cover 12 events and 5 fleet sessions under
`mm_execution_capture_bound_session_v0.1`; all 60 are `INCOMPLETE`. Their 42-field union contains
session bounds, subscribed/observed asset bindings, message and execution counts, tape-prefix hashes,
and a receipt hash. It contains **zero fields** naming a quote, decision, fill, resting state, gap,
or overlap exclusion.

That means the receipts prove only what was observed while connected. For a disconnect they cannot
prove:

1. no maker quote was resting at gap start;
2. no decision or quote transition occurred during the gap;
3. no private fill occurred during the gap; or
4. every overlapping attribution window was excluded downstream.

Absence of a public execution row is not proof of any of those. Requirements 2–4 therefore cannot
be satisfied by this receipt version. Implementing them requires a new receipt/evidence contract
that binds maker quote/decision/fill state and a durable gap inventory. That work also requires a
new centrally registered schema; `src/weather/schema_registry_data.py` is concurrently owned and
was explicitly excluded by the handoff, so this mission reports the requirement instead of taking
that file.

## Mandatory falsification audit

1. **Threshold below 2.165 s — TRUE.** It is `0.000 s`; `-09-18a` remains FAIL.
2. **Gap emptiness not provable — TRUE.** The 60 receipts have no bound maker-state proof. This is
   the load-bearing result and redirects the next mission to receipt format.
3. **Reconnect gaps not the binding constraint — not newly tested.** In retained `-09-18a`
   evidence, continuity was the sole hard settlement failure; a new soak was not run because it
   could not test the missing receipt proof.
4. **Gaps correlate with market activity — INCONCLUSIVE, not assumed independent.** Across 1,802
   trades and 24,181.761 observed seconds the fleet rate was `0.07452/s`. Pooled observed edge
   windows around the four losses were `0.05000/s` at 60 s, `0.10238/s` at 300 s, and `0.08937/s`
   at 900 s. The first two 300-second edge rates were `0.16000/s` and `0.19500/s`; the settlement
   losses were `0.00167/s` and `0.00333/s`. Four endpoints, one date, and strong time-of-day
   confounding cannot establish or reject correlation.
5. **Steady-state failure materially above zero — TRUE under the frozen rule.** The retained four
   remote losses in 6 h 52 m remain non-countable, so the handoff's established roughly 25% failure
   probability per half-hour window is unchanged.

## P1 — no new soak

No public soak was launched and no isolated evidence root was created. A clean reconnect-free soak
would pass the old continuity condition by luck while providing no observation of the proposed gap
path. A soak with a gap would necessarily fail because the receipts cannot prove emptiness. Neither
outcome would resolve the falsifier, so generating it would add no decision-grade evidence.

## P2 — registration readiness only

`WeatherMakerExecutionCapture` is **not registrable**. The exact future operator command remains:

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
.\scripts\ops\register_mm_execution_capture.ps1 `
  -Repo C:\Users\micha\Desktop\github\weather `
  -UserId micha `
  -StartAt "00:55" `
  -SessionSeconds 86400 `
  -ReconnectSeconds 1
```

**Do not run that command from this report.** Registration is blocked until the receipt-format work
exists, is soaked under a precommitted positive rule if one can be justified, and receives a separate
operator decision.

## Roll verdict

The retained runtime identities used here are:

| Closure | Status file | Commit | Loaded source files |
| --- | --- | --- | ---: |
| Snapshot | `data/snapshots/loop_status.json` | `64273c2ed4a9` | 77 |
| CLOB | `data/snapshots/clob_loop_status.json` | `64273c2ed4a9` | 23 |
| Observation trigger | `data/snapshots/observation_trigger_status.json` | `64273c2ed4a9` | 85 |
| CLOB enrichment | `data/snapshots/clob_enrichment_status.json` | `5c004c4554d8` | 21 |

This mission authors only this Markdown report, which enters none of the four closures and is
roll-free. The carried `-09-18a` dependency changes 36 additional files. Of those,
`src/weather/schema_registry_data.py` enters **all four** closures and requires a coordinated
quiet-window roll; every other carried file enters none and is roll-free. The full per-file verdict
is below; the retained arrays were rechecked here rather than inferred from `SOURCE_PATTERNS`.

| Changed path | Snapshot | CLOB | Observation | Enrichment | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| `README.md` | no | no | no | no | roll-free |
| `docs/operations/HOST_LOAD_POLICY.md` | no | no | no | no | roll-free |
| `docs/operations/OPERATIONS_DESIGN.md` | no | no | no | no | roll-free |
| `docs/operations/closed-market-day-parquet-archive-contract.md` | no | no | no | no | roll-free |
| `docs/operations/data-storage-class-contract.md` | no | no | no | no | roll-free |
| `docs/roadmap/agent-report-2026-08-06-workstation-narrow-the-maker-producer.md` | no | no | no | no | roll-free |
| `docs/roadmap/agent-report-2026-08-06-workstation-respecify-the-maker-settlement-gate.md` | no | no | no | no | roll-free |
| `scripts/ops/AGENTS.md` | no | no | no | no | roll-free |
| `scripts/ops/register_mm_execution_capture.ps1` | no | no | no | no | roll-free |
| `src/weather/market/market_making_model_variants.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_day_countability.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_execution_capture.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper_aggregation.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper_constants.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper_reports.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper_scoring.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_reward_q_share.py` | no | no | no | no | roll-free |
| `src/weather/operations/closed_day_projection_registry.py` | no | no | no | no | roll-free |
| `src/weather/operations/closed_market_day_archive.py` | no | no | no | no | roll-free |
| `src/weather/operations/closed_market_day_archive_manifest_contract.py` | no | no | no | no | roll-free |
| `src/weather/operations/event_day_manifest.py` | no | no | no | no | roll-free |
| `src/weather/operations/storage_classes.py` | no | no | no | no | roll-free |
| `src/weather/reporting/market/trading_evidence.py` | no | no | no | no | roll-free |
| `src/weather/schema_registry_data.py` | **yes** | **yes** | **yes** | **yes** | coordinated quiet-window roll |
| `tests/market/test_mm_day_countability.py` | no | no | no | no | roll-free |
| `tests/market/test_mm_execution_capture.py` | no | no | no | no | roll-free |
| `tests/market/test_mm_paper.py` | no | no | no | no | roll-free |
| `tests/market/test_mm_paper_scoring.py` | no | no | no | no | roll-free |
| `tests/operations/test_closed_day_projection_tiering.py` | no | no | no | no | roll-free |
| `tests/operations/test_closed_market_day_archive.py` | no | no | no | no | roll-free |
| `tests/operations/test_event_day_archive_coverage.py` | no | no | no | no | roll-free |
| `tests/operations/test_event_day_manifest.py` | no | no | no | no | roll-free |
| `tests/operations/test_register_mm_execution_capture_script.py` | no | no | no | no | roll-free |
| `tests/operations/test_schema_registry.py` | no | no | no | no | roll-free |
| `tests/operations/test_storage_classes.py` | no | no | no | no | roll-free |
| `tests/reporting/test_trading_evidence.py` | no | no | no | no | roll-free |

## Verification

- `tests/market/test_mm_execution_capture.py`: **13 passed**;
- `tests/market/test_mm_day_countability.py`: **18 passed**;
- total focused verification: **31 passed**; and
- `git diff --check`: **PASS** after the provenance-only report update; and
- `weather.operations.agent_docs_audit`: **one pre-existing failure**, the known missing target in
  `agent-report-2026-08-02-workstation-spec-contract-repair.md`; this report adds no broken link.

The repository venv still points to the removed CPython 3.11 interpreter recorded by `-09-18a`.
The focused tests therefore used the bundled CPython 3.12 runtime, its compatible NumPy/Pandas
packages, and the retained venv's pure-Python pytest packages. No product failure was suppressed.

## What was not done

- no new soak or network connection;
- no registration, task creation, task mutation, task start, or scheduling;
- no producer, capture loop, or supervisor start/restart;
- no production or mirror write, and no write under any `data/` tree;
- no credential read, private exchange call, order, fill, trade, promotion, or release mutation;
- no reserved date declaration, consumption, enumeration, or read;
- no relaxation of `clob_freshness`, chain admission, promotion, `harvest_only`, or any other gate;
- no edit to a concurrent-owner file;
- no PR, no merge to `master`, no force-push, and no branch deletion.

## Reproduction and handback verification

The cadence source is ignored workstation evidence and does not exist at a production-checkout path.
This report does not invent a production path for it. The manifest hash and the two same-millisecond
transaction pairs above bind the load-bearing result; the production operator can compare them with
its authoritative retained tape if present.

The following commands use paths that exist on the production host and verify the committed rule,
branch scope, dependency tests, and registration surface without registering or starting anything:

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
git fetch origin codex/workstation-respecify-the-maker-settlement-gate-2026-09-25a
$branch = "origin/codex/workstation-respecify-the-maker-settlement-gate-2026-09-25a"
git log --oneline --decorate "origin/master..$branch"
git diff --check "origin/master...$branch"
git diff --name-only "origin/master...$branch"
git show "$branch`:docs/roadmap/agent-report-2026-08-06-workstation-respecify-the-maker-settlement-gate.md"
.\venv\Scripts\python.exe -m pytest -q `
  tests\market\test_mm_execution_capture.py `
  tests\market\test_mm_day_countability.py
.\venv\Scripts\python.exe -m weather.market.mm_execution_capture --help
```

## Branch and commits

- Branch: `codex/workstation-respecify-the-maker-settlement-gate-2026-09-25a`
- Base: `origin/master @ 9730012b5915c904032fa8075c7dbf06d47eab77`
- Carried dependency: `origin/codex/workstation-narrow-the-maker-producer-2026-09-18a @ 55d500de6a0a1837d9377fe1bb81961954a300da`
- Dependency merge on this branch: `aa3a30d5`
- Frozen-rule commit: `f2e27e21c2b64df119eb6e1d61203a9aa4682470`

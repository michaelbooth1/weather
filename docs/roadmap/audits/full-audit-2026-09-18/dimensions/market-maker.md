# Audit dimension: Market package A - maker / market-making economics and paper engine

Key: `market-maker` | Auditor run: 2026-09-18 | Host: production (read-only; Read/Grep/Glob + whitelisted git only)
Branch audited: `master` working tree (HEAD `3bdba3d15`), plus read-only `git show`/`git diff --stat` against
`codex/48h-maker-integration-20260912` (the unadopted cumulative maker candidate, PR 55).

No project file was modified. Nothing under `data/` was opened. No Python, tests, scripts or scheduler commands were run.
Every structural claim below was traced through at least one concrete code path; line numbers are for the `master` tree.

---

## 1. Scope

`src/weather/market/` holds 73 Python files. I took the maker / paper / economics subset:

| File | Depth |
| --- | --- |
| `mm_paper_scoring.py` (96 KB) | fill simulator, queue simulator, marks, financials, trade loader read in full; rest skimmed |
| `mm_paper.py` (132 KB) | payload builder, fill-evidence gate, markout slices, variant promotion gate, reward diagnostics, run selection |
| `mm_paper_aggregation.py` | spilled-leg expiry, tape index (trade/mark/queue lookups) |
| `mm_paper_constants.py`, `mm_paper_evidence.py`, `market_making_evidence.py` | full |
| `mm_paper_reports.py` | `permission_for_record` and known-edge permission only |
| `mm_policy.py` (78 KB) | config, sizing, `_base_output`, `_quote`, `_decide_market_harvest`, `decide_quote`, input assembly |
| `mm_risk.py` | sizing, halt, negative-risk simulator (caller trace) |
| `market_making_run.py` (93 KB) | `build_run_once` end to end, CLI |
| `market_making_run_support.py` | harvest input assembly, book audit, lifecycle fill transitions |
| `market_making_live_pilot.py`, `market_making_run_constants.py` | full |
| `market_making_readiness.py` | gate list and fill/vacuity logic |
| `live_forward_gate.py` | full (countability) |
| `maker_incentive_feasibility.py` | full |
| `exchange_economics.py` | leg binding / gate coverage; `exchange_economics_run_capture.py` full |
| `mm_scoring_projection.py` | column contract |
| `clob_recon.py` | policy-suggestion path only |
| `market_microstructure_constants.py`, `market_microstructure_features.py` (book-age only), `market_microstructure_capture.py` (WS sampling only), `execution_tape_store.py` (output layout only) | targeted |
| `mm_exchange_reports.py` | rebate reconciliation surface (grep-level + spot read) |

Outside the package but traced because the maker path depends on them:
`src/weather/operations/market_making_daily_roll.py`, `src/weather/operations/bot_run_liveness.py`,
`src/weather/operations/daily_refresh_trading_steps.py` (maker paper score step),
`scripts/ops/market_making_daily_roll_task.ps1`, `scripts/ops/register_market_making_daily_roll.ps1`,
`scripts/ops/register_clob_enrichment.ps1`.

Docs used: `docs/roadmap/items/item-330-*`, `item-328-*`, `item-326-*`, `docs/operations/ESTABLISHED_FINDINGS.md`
(sections 1b, 8b, 8bb, 8c, 8q), `STATE_OF_PLAY.md`, `AGENT_CONTEXT.md`, `src/weather/market/AGENTS.md`.

Left to the sibling auditor: live adapters, clients, credentials, order submission, taker, CLOB capture internals.

## 2. Method

1. Read the refocus plan (item 330) to establish what question the maker code is supposed to answer:
   *"gross trading P&L + paid maker rebates + paid liquidity rewards - all relevant costs"* at a feasible capital level.
2. Traced the production path end to end: scheduled task -> `market_making_daily_roll` -> `market_making_run`
   -> `mm_policy.decide_quote` -> quote tape -> daily `run_maker_paper_score_step` -> `mm_paper` ->
   `simulate_conservative_fills` -> known-edge map / readiness gates.
3. For each "X is never written / never called" claim, searched all of `src/weather` (and `scripts/`, `tools/`
   where relevant), then opened the producer or confirmed its absence.
4. Compared `master` with the unadopted maker branch using `git diff --stat` and `git show <rev>:<path>` to separate
   "defect in production" from "fixed but stranded".
5. Checked `ESTABLISHED_FINDINGS.md` before labelling anything new.

## 3. The short version

The maker code is careful, conservative and overwhelmingly fail-closed. It will not manufacture a profit. But as wired
on production `master` today it also cannot produce a single unit of evidence about the question item 330 asks:

* the scheduled 12-market maker roll runs the **model** permission profile, which the project's own measurement shows
  emits zero quotes; the only lane that can quote (`market_harvest`) is not scheduled and has run exactly one one-market tick;
* even if quotes existed, the fill simulator **does not read the continuous public execution tape** that was built for
  it; its trade sources are sparse WebSocket samples and two CSVs nothing writes;
* the paper engine carries **no inventory state**, so none of the policy's risk caps can ever bind in paper;
* everything that would make rewards or paid incentives measurable (about 4,900 lines in this package) sits on an
  unadopted branch, together with two fixes for defects that are live on `master`;
* and on that branch the economics model still takes adverse selection and fill fraction as **typed-in constants**.

In the project's own vocabulary: this dimension measures eligibility, never outcome, and at the moment it is not
measuring eligibility either.

---

## 4. Findings

Severity scale per the audit brief. `basis` and `known_status` are stated per finding.

### market-maker-1 (HIGH, new, verified_in_code) - The paper fill simulator is not connected to the execution tape

`load_trade_rows` reads exactly four inputs from the event folder: `trades_long.csv`, `market_trades.csv`,
`market_ws.jsonl`, `market_ws_events.csv` (`mm_paper_scoring.py:1486-1505`). `load_mark_rows` reads `price_history.csv`,
`order_books_summary.csv`, `market_ws_events.csv` (`mm_paper_scoring.py:1765-1776`).

The supervised continuous public execution tape (item 326, adopted 2026-08-15, described in memory and canon as the
only data that cannot be backfilled) writes to `snapshots/<event_slug>/execution_tape/trades*.jsonl`
(`execution_tape_store.py:564-566`). A search of all of `src/weather` for `execution_tape` returns seven files: the
store, the capture module, the supervisor, the runtime audit, storage classes, the schema registry and a status line
in `reporting/market/operator_control_room.py:212`. None is an analytic consumer. `scripts/` matches are all ops
lifecycle. `tools/` has none. Item 326 itself says "paper counterfactual markouts are the only use this tape may
support" (`item-326-...md:16-18`), and no code performs that use.

What the simulator does read:
* `trades_long.csv` / `market_trades.csv`: no writer exists anywhere in `src/weather` (only two readers:
  `mm_paper_scoring.py:1487-1488`, `clob_recon.py:274`).
* `market_ws*.{jsonl,csv}`: written only by the microstructure capture's bounded WS sample. The managed raw-book loop
  excludes WS by contract (`market_microstructure_constants.py:19-20`); the default sample is 1.0 s / 5 messages
  (`:25-26`); the enrichment loop that carried it was disarmed 2026-07-27 (`ESTABLISHED_FINDINGS.md:437-446`), and the
  measured yield was 71 executions in 1.1 million rows (`:426-435`).

`scripts/ops/register_clob_enrichment.ps1:14-18` records this same defect class on 2026-07-27: "The market-making paper
scorer has been reporting $0.00 over vacuous evidence because the apparatus feeding it was never connected." The
replacement evidence source was then built and never connected either.

Aggravating: an event with zero trade rows is reported (`mm_paper.py:2323-2326`) but is not a blocker in
`fill_evidence_completeness_summary` (`mm_paper.py:2280-2303`). With quote legs, books and a settlement present, an
event with no trade tape scores PASS with zero fills. "No tape" and "no adverse flow" are indistinguishable.

Impact: paper fills and markouts are structurally near zero regardless of strategy; the irreplaceable tape accrues
(and consumes disk) with no consumer.
Recommendation: add an `execution_tape/trades` reader to `load_trade_rows` and `load_mark_rows` honouring the gap
ledger; make `events_without_trade_rows` (and tape gaps overlapping a quote's life) a fill-evidence blocker.

### market-maker-2 (HIGH, known_open in part, verified_in_code + doc_claimed) - The scheduled maker roll runs a lane that cannot quote; the lane that can quote is unscheduled and cannot be reward-eligible

* The recurring task passes `--budget-usdc 500 --mode paper-live-forward --markets all --interval-seconds 60` plus three
  `--config` sizes and nothing else (`market_making_daily_roll_task.ps1:30-41`). `build_market_making_command` has no
  permission-profile parameter (`market_making_daily_roll.py:209-248`); the CLI default is `model`
  (`market_making_run.py:1999-2004`).
* In the `model` profile a loaded `no_quote` known-edge record or promotion `BLOCK` returns before any pricing
  (`mm_policy.py:1455-1464`). Canon measured 554,004 rows, D=8, M=12, every row `NO_QUOTE`
  (`ESTABLISHED_FINDINGS.md:1909-1932`). That part is known.
* New: item 328 added `market_harvest` precisely to escape this, and it has run one active-day, one-market tick
  (`item-328-...md:55-57, 115-119`; `ESTABLISHED_FINDINGS.md:2400-2409`). No scheduled job invokes it. So the recurring
  12-market, 60-second, 13-hour job keeps writing all-`NO_QUOTE` tapes (and, with `maker_model_variant_basket_enabled`
  defaulting to True at `mm_policy.py:116`, a second variant tape) while producing no evidence for item 330.
* `build_market_harvest_policy_config` clamps `quote_size` to `DEFAULT_POLICY_CONFIG["quote_size"]` = 5.0 shares and
  `max_band_notional` to 10.0 (`market_making_live_pilot.py:71-102`, `mm_policy.py:62,75`). The 2026-09-11 public capture
  recorded reward minimums of 100 shares (same-day) and 20 shares (later dates) (`item-330-...md:51-56`). A harvest
  quote can therefore never be reward-eligible. Canon already records "the reward-size floor exceeds the position cap"
  (`ESTABLISHED_FINDINGS.md:441-443`); the September refocus onto rewards did not revisit the clamp.
* `_decide_market_harvest` has no midpoint-range filter (`mm_policy.py:1337-1443`), while the live candidate gate is
  0.20-0.80 (`mm_live_candidate_cli.py:50-51`). The single proof tick quoted midpoints 0.9985 and 0.002
  (`ESTABLISHED_FINDINGS.md:2411-2413`). Paper harvest statistics would describe a different population from any
  live candidate.

Impact: evidence accrual on the refocus hypothesis is zero while the job still costs CPU, memory and disk on a host
with days of disk headroom.
Recommendation: decide explicitly - either schedule a bounded harvest run whose size/band ceilings and midpoint filter
match the intended live candidate, or pause the model-profile roll (and the variant basket) until promotion can change.

### market-maker-3 (HIGH, known_open, verified via git + code) - Item 330's economics code and two production-relevant fixes are stranded on an unadopted branch

`git diff --stat master...codex/48h-maker-integration-20260912 -- src/weather/market`: 26 files, +4,916 / -309. New
modules absent from `master`: `maker_opportunity_capture.py`, `maker_opportunity_inputs.py`, `maker_reward_simulation.py`,
`mm_liquidity_earnings_evidence.py`, `mm_paid_credit_activity.py`, `mm_pilot_capital.py`, `exchange_economics_sources.py`,
plus `mm_exchange_reports.py` +550. `STATE_OF_PLAY.md:38` and `item-330:5-18` record the branch as held behind the
reliability candidate.

Consequences on `master` today:
* No liquidity-reward reconciliation path exists. `actual_payout_evidence` is the literal `False` at every producer
  (`mm_paper.py:729`, `mm_paper.py:904`, `exchange_economics.py:617`, `exchange_economics.py:1676`); the readiness gate
  that reads it (`market_making_readiness.py:943, 1138-1149`) can never pass. Fail-closed, but permanently.
* Stale-input defect live on `master`: `_book_age` returns a precomputed `book_age_seconds` / `clob_book_age_seconds`
  before it ever looks at the timestamp (`mm_policy.py:1023-1028`), and that precomputed value is
  `snapshot_time - book_time` (`market_microstructure_features.py:373`), i.e. age relative to the model snapshot, not to
  the decision. A book 10 s older than a 14-minute-old snapshot passes the 120 s staleness check. The branch replaces
  this with `_row_age`, which reconciles reported age against the timestamp and returns None on disagreement. On the
  orchestrated path the market-level book audit (`market_making_run_support.py:684-714`) uses the real clock, so this is
  defence-in-depth rather than an open door; the standalone `run_policy_snapshot` has no such audit.
* Artifact-overrides-operator defect live on `master`: `config_with_clob_recon` merges recon suggestions over the
  caller's config (`mm_policy.py:603-611`, default enabled at `:88`). `clob_recon` caps its `quote_size` suggestion at its
  own default of 5.0 and can emit 0.0 (`clob_recon.py:31, 460-468, 614`), which silently defeats the scheduled task's
  `quote_size=20` and can zero all quoting with reason `NO_QUOTE_RISK_CAP`. The wrapper's own comment says its arguments
  "cannot drift" (`market_making_daily_roll_task.ps1:2`). The branch flips the default to False. Whether a recon artifact
  currently exists on the host was not checked (data/ out of scope).

Impact: the maker decision cannot advance, merge risk compounds against a master moving ~9 commits/day, and known-fixed
defects keep running.
Recommendation: carve the two small `mm_policy` fixes out as their own roll-assessed change; land the offline-only
accounting modules separately from the live-stage modules so they are not hostage to PR 61.

### market-maker-4 (MEDIUM, new, verified_in_code) - The paper engine has no inventory state, so no risk cap can bind and paper P&L is not the P&L of the stated policy

* `_risk_limited_size` and `_base_output` read `event_notional`, `band_notional`, `inventory_notional`, `daily_loss` from
  the input row, defaulting to 0 (`mm_policy.py:1034-1051, 1191-1194`). Across all of `src/weather` those keys appear in
  four files (`mm_policy.py`, `mm_risk.py`, `market_making_live_pilot.py`, `mm_live_candidate_cli.py`) and none assigns
  them onto an input row. `assemble_policy_inputs` (`mm_policy.py:1714-1763`) and the harvest assembler
  (`market_making_run_support.py:361-404`) do not set them.
* In paper mode the per-run `fills_long.csv` is only ever written as an empty header (`market_making_run.py:1752-1753`);
  the sole row writer is the live path (`mm_exchange.py:1359`); the only emitter of a `filled` lifecycle transition is
  `mm_exchange.py:1144-1148`. This is the current form of the recorded "fills.jsonl never written" observation.
* `mm_risk.sizing_decision` and the negative-risk collateral simulator have no callers outside `tests/market/test_mm_risk.py`.
* The ex-post scorer fills each leg independently with no cumulative per-band/event cap (`mm_paper_scoring.py:2372-2414`),
  and the run re-quotes full size every 60 s.
* Related: the scorer hard-codes a 60 s quote life (`mm_paper_constants.py:31`, `mm_paper_scoring.py:813-826`,
  `mm_paper_aggregation.py:201`) while runs record 120 s (`market_making_run_constants.py:11`) and harvest up to 600 s
  (`market_making_live_pilot.py:14`). The scoring projection does not carry `quote_ttl_seconds`
  (`mm_scoring_projection.py:49-121`) and the daily step passes no config (`daily_refresh_trading_steps.py:509-536`).

Impact: for binaries held to resolution, inventory accumulation is the dominant risk; paper results can neither confirm
nor bound it under the policy's own limits.
Recommendation: fold simulated fills back into per-band/event/day state (in the scorer if not in the run) and score
with the run's recorded TTL.

### market-maker-5 (MEDIUM, known_open, verified_in_code) - No component on any branch estimates fill probability or post-fill loss from data

* `assess_buy_plan` is a rigorous pure calculator with zero callers in `src/` or `scripts/`
  (`maker_incentive_feasibility.py:231`).
* On the unadopted branch, `maker_reward_simulation.py` defaults are `exit_loss_per_filled_share="0.02"`,
  `yes_remaining="1"`, `other_q="200"`, and its own assumptions block says "No rebates, settlement gain or spread capture
  assumed" (read via `git show`). Adverse selection and fill fraction are user inputs, not measurements.
* On `master`, rewards are forced to zero for the International platform (`mm_paper_scoring.py:838-848`,
  `mm_paper.py:701-738`), so paper cannot measure reward eligibility (time in qualifying range) either.
* Fills require a strict trade-through with recorded size and are capped at the through-trade's size
  (`mm_paper_scoring.py:1553-1559, 2384-2400`). That is deliberately conservative, but it means the sampled fills are
  exactly the most adversely selected subset and benign at-touch fills never appear. A paper NO-GO is therefore
  uninformative; only a paper GO would carry weight.

Canon already says own-account evidence is the only route to realized economics (`ESTABLISHED_FINDINGS.md:1959-1970`).
Recommendation: state in item 330 that G1 can only ever be an eligibility/capital screen, and stop describing paper
output as economics.

### market-maker-6 (MEDIUM, new, verified_in_code) - Statistical labels in the paper engine claim corrections the code does not apply

* `build_markout_slices` stamps every slice `"multiple_test_adjustment": "bonferroni_conservative"` and publishes
  `deflated_markout_30m_per_share`, but `z` is the unadjusted `confidence_z` = 1.96 and `adjustment_count` is used only
  as a label (`mm_paper.py:1141-1142, 1168-1170`; `mm_paper_constants.py:41`). The SE is per-fill iid although fills in
  one event-day share a settlement outcome. `anti_overfit_summary` repeats the label (`mm_paper.py:1200-1201`).
* `permission_for_record` can grant `edge_allowed` on that CI with 10 fills in a 9-dimension slice
  (`mm_paper_reports.py:1063-1077`; `mm_paper_constants.py:42-44`).
* The model-variant gate does apply a real Bonferroni alpha (`mm_paper.py:354`) but clusters on (date, market) with a
  minimum of 3 target dates (`mm_paper.py:334-337, 402-407`), treating same-date markets as independent, contrary to the
  project's crossed-clustering standard.

Latent today (promotion is BLOCK fleet-wide). Recommendation: apply the adjustment or drop the label; cluster by date.

### market-maker-7 (MEDIUM, new, verified_in_code) - The 14-day gates read a window of at most 14 run folders

The daily scorer admits the latest 14 active-day *run folders* that fit 512 MB
(`daily_refresh_trading_steps.py:91-92, 409-442`; `mm_paper.py:525-526`). `live_forward_days` is derived from those rows
(`mm_paper.py:1185-1195`). Two gates need 14 days from it: `fourteen_consecutive_countable_live_forward_days`
(`market_making_readiness.py:1111-1121, 530-540`) and `live_days >= min_edge_allowed_live_days`
(`mm_paper_reports.py:1066, 1073-1077`). Every relaunch mints a new run id and folder (`market_making_run.py:1342-1343`).
So the gates are satisfiable only if each of the last 14 folders is a distinct, consecutive, countable day and no byte
trimming occurs. One same-day restart or one trimmed run makes both unreachable until it ages out. This is the
"derived rule lives in the relationship" shape the project has been bitten by before.
Recommendation: select by distinct target date, not by folder count, or keep a cumulative countable-day ledger.

### market-maker-8 (MEDIUM, inferred) - At current free disk the maker roll refuses to launch

The wrapper passes `--min-free-bytes 34359738368` (32 GiB) (`market_making_daily_roll_task.ps1:17, 40`; registration
does not override it, `register_market_making_daily_roll.ps1:31`). `disk_capacity_preflight` returns `LOW_SPACE` below
that (`bot_run_liveness.py:58-73`) and `start_for_date` writes a disk-full status and returns without launching, on
both `start` and `ensure` (`market_making_daily_roll.py:1016-1020, 1058-1063, 1226-1253`). The lead's live state is 21 GB
free. I did not read the maker status file, hence `inferred`.
Impact: whatever maker paper evidence, countability rows and paper-roll outputs downstream consumers expect have
likely stopped, which can read as "no opportunity" rather than "did not run".

### market-maker-9 (MEDIUM, known_open on a branch only, doc_claimed) - Paper settlement P&L uses the WU proxy label; venue rules for the tested market are recorded as NOAA-first

Paper `net` P&L prefers held-to-resolution settlement P&L (`mm_paper_scoring.py:1995-1997`) and resolves it from the
local folder settlement or the WU-based ledger (`mm_paper_scoring.py:1792-1813`). `AGENT_CONTEXT.md:22-25` calls WU "the
settlement proxy". The unadopted branch's item-67 doc (lines 486-489, read via `git show`) records that the retained
venue Rules for the September NYC event "resolve from NOAA's LaGuardia hourly data first, with WU fallback only under
their stated delayed-data condition. This differs from the configured WU proxy." I could not find this on `master`
under `docs/operations`. I did not and could not verify venue rules (no network).
Impact: for a binary held to resolution a one-degree source disagreement flips the payout; no haircut or mismatch rate
is applied anywhere in the maker economics.
Recommendation: `reporting/source_gates/settlement_source_audit.py:207-250` already compares `polymarket_winning_band`
with the local label; publish that mismatch rate per market and carry it into G1.

### market-maker-10 (LOW-MEDIUM, new, verified_in_code) - Markouts have no staleness bound

`mark_at` returns the first mark at or after `fill_time + horizon` with no upper limit (`mm_paper_scoring.py:1781-1789`);
the spilled path is identical (`mm_paper_aggregation.py:460-478`). After a capture gap a "30s" or "30m" markout is
silently measured hours later. For unsettled fills the 30m mark is the P&L basis (`mm_paper_scoring.py:1998-2000`), and
the host currently has a multi-date settlement hole. Marks also mix book midpoints with last-trade prints
(`mm_paper_scoring.py:1751-1756`).
Recommendation: reject marks more than a small multiple of the book interval past the target and count the rejections.

### Report-only observations (not in the structured top 10)

* **Queue simulator false "through" for inside-spread quotes.** A bid that improves the best bid gets queue-ahead 0
  (`mm_paper_scoring.py:1648-1649`); on the next book snapshot the real best bid is still below the phantom quote, so
  `through = True` (`:1687-1689`) and the leg is classed `estimated_full_fill` / "book_moved_through_quote_price"
  (`:1709-1712`). Harvest quotes at mid +/- 1c are inside the spread by construction whenever the spread exceeds 2c.
  Diagnostic only (not P&L), but it feeds `queue_estimated_fill_quality` and the report. The only test covers a genuine
  through (`tests/market/test_mm_paper.py:1388-1390`).
* **Default-True chain for live-forward counting** when a run folder has no gate evidence
  (`mm_paper_evidence.py:115`, `mm_paper_scoring.py:646`, `mm_paper.py:1191`). Mostly unreachable in normal operation
  because gate files are written before the quote tape (`market_making_run.py:1657-1659` vs `1739-1744`); still the wrong
  default for a project whose rule is "never let a check skip silently".
* **Countability still does not require a quote** (`live_forward_gate.py:115-145, 211-218`). Unchanged since recorded in
  `ESTABLISHED_FINDINGS.md` section 8b. `gate_ok` also treats a missing `event_metadata_validation` gate as passing
  (`live_forward_gate.py:108-112`).
* **Band parsing on master**: `label_numbers` uses `-?\d+` (`mm_paper_scoring.py:208-211`), so "80-81" parses to
  `[80, -81]` and becomes `value_hi` when `bin_value_hi` is absent (`:222-226`). Fixed on the unadopted branch via
  `weather.units.temperature_band_key`. Latent for paper legs because quote rows normally carry `bin_value_hi`.
* **Inventory marked at mid / last print; flatten cost is fee only** (`mm_paper_scoring.py:1987-2003`), against item
  330's own rule "Do not quietly mark inventory at midpoint".
* `expected_reward_score` in `_quote` is `depth / 1000` clipped to 1 (`mm_policy.py:1323`), a placeholder with no venue
  meaning (harvest zeroes it).
* Size multipliers (early-hour 0.35, cadence 0.5, current-high 0.5) applied to a 5-share ceiling push harvest quotes
  below a typical exchange minimum, so harvest can only quote with no multiplier active (`mm_policy.py:1289-1308,
  1426-1436`). Exchange minimum not verified live.
* `_bootstrap_mean_ci` and hashed-seed determinism in the variant gate look sound; not re-derived.

---

## 5. Direct answers to the brief's questions

| Question | Answer |
| --- | --- |
| Paper-fill realism (queue, adverse selection, fills at touch, latency) | Fills are NOT assumed at touch: strict trade-through, recorded size, shared trade-size budget across legs. Queue position is computed but diagnostic only, and is wrong for inside-spread quotes. No placement/cancel latency. Sampled fills are the most adverse subset. Trade evidence feed is effectively empty (finding 1). |
| Fee / rebate / reward modelling, verified against account data? | Fee curve `size*rate*p*(1-p)` at 5 dp; rates bound per run from a hash-verified economics capture. Rebates: estimate reported, accepted value forced to 0 until `/rebates/current` evidence reconciles (`mm_exchange_reports.py:307-427`). Liquidity rewards: forced to 0; **no account-data verification path exists on master** (finding 3). |
| Inventory / settlement risk into resolution | Not modelled. No inventory state, caps cannot bind (finding 4); settlement uses the WU proxy with no mismatch haircut (finding 9). |
| Countability: "never required a QUOTE", "fills.jsonl never written" - current state | Both still true on master. `live_forward_gate.py` has no quote term; per-run fills file is header-only in paper. Quote presence is enforced only by the separate readiness gate. |
| Stale-input handling | Market-level book audit uses the real clock; per-row book age uses a precomputed value relative to snapshot time (fixed on the unadopted branch). Model/watcher ages trust reported values. |
| Can the economics answer "profitable after adverse selection"? | No, on any branch (finding 5). Master measures nothing at present (findings 1, 2). |
| Hard-coded parameters | `quote_size` 5 / band 10 / event 25 / daily loss 25; harvest half-spread 0.01, max spread 0.08; adverse-selection buffer 0.01; paper TTL 60 s; z = 1.96; 14 days / 10 fills; min 3 target dates; WS 1 s / 5 msgs; 32 GiB min free; 14 runs / 512 MB. Most are sensible as ceilings; the problems are the relationships between them (findings 2, 4, 7, 8). |
| Silent skips | Zero-trade events not a blocker (1); recon artifact silently overriding operator size (3); unbounded mark staleness (10); disk gate stopping the roll (8); default-True counting chain (report-only). |

## 6. Strengths (genuine)

1. **Incentives cannot leak into accepted P&L.** Rewards are zeroed with an explicit status and rebates carry
   `maker_rebate_accepted = 0.0` until a daily pUSD payout reconciles (`mm_paper_scoring.py:838-848, 1974-1994`).
2. **Execution-evidence hygiene.** `load_trade_rows` admits only genuine `last_trade_price` executions, reconciles
   identities and aliases, rejects negative latency and conflicting representations, and every rejection class blocks
   the fill-evidence gate (`mm_paper_scoring.py:1227-1550`; `mm_paper.py:2119-2132, 2285-2288`). This is the repair of
   the July "tape is not safely scoreable" ground.
3. **Content-bound economics.** Each run freezes a hash-verified economics snapshot and every paper leg is bound to it;
   a token match cannot rehabilitate stale or wrong-platform evidence (`exchange_economics_run_capture.py:102-143`;
   `exchange_economics.py:1186-1208`).
4. **Harvest lane safety.** Paper-only enforced at two layers, ceilings re-clamped after dynamic reconciliation, and a
   hard `RuntimeError` if a paper run ever emits live permission (`market_making_run.py:1303-1304, 1361-1364, 1711-1712`;
   `mm_policy.py:1339-1346`).
5. **`maker_incentive_feasibility.py`** is a model of how to write a diagnostic: Decimal throughout, mandatory unit
   provenance, coded input errors, separate order/capital/reward blockers, explicit `paid_rewards: None` and
   `live_order_authority: False`.
6. Readiness detects a vacuous PASS (`market_making_readiness.py:917-931`), and canon (sections 8b, 8bb, 8c) is unusually
   candid about what the maker track has not shown.

## 7. Not covered

* `mm_paper_reports.py` rendering and known-edge map builder beyond `permission_for_record`; `quote_blocker_diagnostics`;
  `build_early_hour_guardrail_shadow`.
* `info_event_calendar.py` (quote-pull windows), `snapshot_cadence_quality.py`, most of `market_making_preflight.py`,
  most of `clob_recon.py`, most of `exchange_economics.py` collection/validation.
* `mm_exchange.py` / `mm_exchange_reports.py` beyond the rebate surface (sibling scope).
* Unadopted-branch modules other than `maker_reward_simulation.py` and the two `mm_policy` / `mm_paper_scoring` diffs.
* No live state: I did not read `data/` (maker status, `mm_paper_report.json`, `MM_COUNTABILITY.md`, recon artifact),
  so findings 2 (current quote count), 3 (recon artifact present?) and 8 (roll actually refused?) carry that caveat.
* No tests executed; test adequacy judged by reading only.

## 8. Open questions for the lead / sibling auditor

1. The unadopted branch records an attended Stage 0/1 session on 2026-09-06 that placed real 0.005 pUSD BUY orders
   against a wallet reported at 447 pUSD (commit `8739902fe`, `STATE_OF_PLAY.md` diff). Item 330 (2026-09-04/05) says
   "no live trading". These are reconcilable only if the owner separately authorized that attended test; the sibling
   auditor should confirm the authority trail, and `master`'s `STATE_OF_PLAY.md` does not mention the session.
2. In the live path, are `event_notional` / `band_notional` / `daily_loss` fed from positions? On master no producer
   exists for any mode (finding 4), so the policy-level caps would not bind live either unless `mm_exchange`
   enforces them separately.
3. Is a `clob_recon` artifact with `policy_parameter_suggestions` present on the host today? If yes the scheduled
   `quote_size=20` has never been effective.
4. Does the venue's resolution source differ from WU for all 12 International markets or only NYC (finding 9)?
5. What is the daily byte cost of the all-`NO_QUOTE` base and variant quote tapes under `data/mm_runs`? Given ~4 days
   of disk headroom this is worth one bounded measurement by whoever owns storage.

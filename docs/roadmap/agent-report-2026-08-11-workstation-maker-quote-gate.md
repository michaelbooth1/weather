# Workstation report 2026-08-11 — can the maker quote at all?

## Verdict

**NO-GO in the current configuration: the maker cannot emit a market-centred quote, and
`KNOWN_EDGE_PERMISSION` is not the binding outcome constraint.** The post-`2026-07-31` retained
corpus contains 554,004 quote-intent rows across D=8 dates and M=12 markets; every row is
`NO_QUOTE`. The loaded map matched every row. All 293,964 rows labelled
`NO_QUOTE_KNOWN_EDGE_PERMISSION` had a present record whose permission was `no_quote` and whose
reason was `promotion_block`; zero came from `missing_known_edge_record`.

Removing only the map restriction on the actual 2026-08-06 run changed all 26,928 policy-eligible
rows to `NO_QUOTE_BLOCKED_PROMOTION` and produced **zero** quotes. Granting both promotion and
`harvest_only` made the existing model-dependent harvest branch reachable on 2,386/26,928 rows,
but removing the model fair value then produced **zero** quotes: 19,811 rows stopped at
`NO_QUOTE_MISSING_FAIR` and 7,117 at the information-event gate. Thus the current implementation
has no market-centred, no-model route.

This is not a map-coverage defect. It is a deliberate policy architecture: preflight dominates
failed inputs; a loaded `no_quote` record dominates policy; promotion `BLOCK` dominates
`harvest_only`; and the surviving harvest branch still requires model probability, model age, and
model-market disagreement. The operator decision is whether to authorize a separate **paper-only,
explicitly market-centred harvest lane** that does not inherit model promotion or model inputs.
Nothing on this branch makes that decision or changes the policy.

## Evidence boundary

- Branch: `codex/workstation-can-the-maker-quote-at-all-2026-09-48a`.
- Base: `origin/master` at `54df60cb5154c876bf10004accfd6231e4341f4a`.
- Primary population: the 15 canonical, non-quarantine `quote_intents_long.csv` tapes whose
  `target_date >= 2026-07-31`, 554,004 rows, 8 dates (`2026-07-31` through `2026-08-07`), 12
  markets, and 96 date × market cells. No pre-boundary row is pooled into any estimate.
- The workstation mirror has no 2026-08-08 tape. The handoff's production facts for that run
  (6,204 `NO_QUOTE`, 5,643 `KNOWN_EDGE_PERMISSION`) are retained as handed facts and are not used
  to infer a row-level map branch or to widen the workstation population.
- The reserved-confirmation-window check at run time reported **no reserved dates**.
- The map hash was
  `1E04BA58220F3B231834193FE9149939928AE4C619B940FD15204B04927D8BAB`.
- The actual-run replay inputs were:
  - `data/mm_runs/2026-08-06/20260806T174937785434Z/quote_intents_long.csv`, SHA-256
    `75681301EC1601B016A96DB7E2952E4E54E976E2ED865759D46E935532690705`;
  - `data/mm_runs/2026-08-07/20260807T165712017390Z/quote_intents_long.csv`, SHA-256
    `F9287190E92E66938AC8CE19627CD5EB8E34A7BB8753B83F61D5530EC08184BC`.
- This was read-only research over local retained evidence. No exchange/provider endpoint was
  called and nothing under `data/` was written.

## P0.1 — exact `NO_QUOTE` attribution

All 554,004 post-boundary rows are `NO_QUOTE`; there are zero `QUOTE` rows. The raw row-weighted
mix and crossed date × market intervals are:

| Primary reason | Rows | Share | Crossed 95% interval |
| --- | ---: | ---: | ---: |
| `NO_QUOTE_KNOWN_EDGE_PERMISSION` | 293,964 | 53.06% | [32.90%, 72.84%] |
| `NO_QUOTE_STALE_INPUT` | 166,782 | 30.10% | [14.79%, 48.82%] |
| `NO_QUOTE_MISSING_PREFLIGHT` | 65,769 | 11.87% | [4.59%, 17.16%] |
| `NO_QUOTE_BLOCKED_PROMOTION` | 27,489 | 4.96% | [0.00%, 16.39%] |

Intervals use 30,000 independent resamples of the date clusters and market clusters, seed
`20260948`, with their Cartesian multiplicities. Cluster support is D=8, M=12, MD=96. Exact row
counts are not uncertain; the intervals describe how poorly eight dates support generalizing the
reason mix.

The mix is not stable descriptively: known-edge's daily share spans **8.34% to 76.87%**. The first
four dates carry 47.31% known-edge rows and the last four 59.04%, a +11.73 percentage-point delta,
but the crossed interval is **[-19.56, +44.81] points**. Two-sided alpha-0.05 observed-effect power
is 0.104 and the 80%-power MDE is 48.36 points. The apparent first-half/second-half movement is
**not distinguishable from zero**.

| Date | Rows | Known-edge | Promotion | Stale | Missing preflight |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-07-31 | 60,456 | 46,475 (76.87%) | 4,180 (6.91%) | 9,669 (15.99%) | 132 (0.22%) |
| 2026-08-01 | 91,608 | 59,422 (64.87%) | 3,707 (4.05%) | 10,593 (11.56%) | 17,886 (19.52%) |
| 2026-08-02 | 95,964 | 8,008 (8.34%) | 2,057 (2.14%) | 67,837 (70.69%) | 18,062 (18.82%) |
| 2026-08-03 | 34,320 | 19,679 (57.34%) | 1,914 (5.58%) | 12,551 (36.57%) | 176 (0.51%) |
| 2026-08-04 | 95,040 | 58,630 (61.69%) | 5,357 (5.64%) | 10,967 (11.54%) | 20,086 (21.13%) |
| 2026-08-05 | 87,120 | 42,823 (49.15%) | 4,763 (5.47%) | 30,811 (35.37%) | 8,723 (10.01%) |
| 2026-08-06 | 50,820 | 31,757 (62.49%) | 3,267 (6.43%) | 15,367 (30.24%) | 429 (0.84%) |
| 2026-08-07 | 38,676 | 27,170 (70.25%) | 2,244 (5.80%) | 8,987 (23.24%) | 275 (0.71%) |

The market pattern is structural. Toronto has zero known-edge-primary rows and is the only market
with `NO_QUOTE_BLOCKED_PROMOTION` as the direct policy reason. Each of the eleven U.S. markets has
the same 46,167 row opportunities and a market-specific `no_quote` map record, so its direct
policy reason is known-edge whenever outer preflight passes. The exact date × market attribution
is in the appendix.

## P0.2 — which known-edge branch fired?

Exactly one branch explains all 293,964 known-edge-primary rows:

| Record branch | Permission | `known_edge_reason` | Record key | Promotion | Preflight | Rows |
| --- | --- | --- | --- | --- | --- | ---: |
| record present | `no_quote` | `promotion_block` | present | `BLOCK` | `PASS` | 293,964 |
| loaded map, missing record | — | — | — | — | — | **0** |
| map missing fallback | — | — | — | — | — | **0** |

The hypothesized loaded-but-incomplete failure mode is real in source but did not occur in this
population. `apply_known_edge_permission` assigns `no_quote/missing_known_edge_record` to an
unmatched row when the map exists and `harvest_only/known_edge_map_missing` when it does not. The
current corpus never entered either unmatched branch.

The runner has an outer precedence layer. When a market preflight is non-PASS,
`preflight_no_quote` overwrites the pure-policy reason with `NO_QUOTE_STALE_INPUT` or
`NO_QUOTE_MISSING_PREFLIGHT`. That accounts for 232,551 rows. For the remaining 321,453 PASS rows,
`decide_quote` checks `known_edge_permission == no_quote` first and promotion `BLOCK` second.
Therefore the known-edge label hides a promotion refusal that would survive removal of the map.

## P0.3 — what the 93 records cover

The loaded `mm_known_edge_map_v0.2` contains 93 records:

| Permission | Records | Main reason |
| --- | ---: | --- |
| `harvest_only` | 42 | `source_freshness_model_gap` |
| `edge_research` | 40 | dynamic-source replay gate clear (39) plus CLOB-overlay replay clear (1) |
| `no_quote` | 11 | `promotion_block`, one record for each U.S. market |
| `edge_allowed` | **0** | — |

On the post-boundary quote population:

- all **554,004/554,004 rows** have a non-empty `known_edge_record_key`;
- all **1,362/1,362 distinct observed market/cell tuples** have a record, for 100% row and cell
  coverage (cell tuple is the ten runtime matching dimensions written beside each quote intent);
- only **12/93 map records** are selected: the 11 market-specific `promotion_block/no_quote`
  records plus one wildcard `source_freshness_model_gap/harvest_only` record;
- 507,837 rows (exactly eleven markets × 46,167) select `no_quote`; 46,167 Toronto rows select
  `harvest_only`; 81 map records are never selected.

The map summary calls its 93 records `active_model_gap_cell_count`. That is now in direct tension
with the current decision problem: `-09-46a` found zero positive model edge in all 114 declared
quoting cells, and this map has zero `edge_allowed` records. The map is consistently enforcing a
conservative model/promotion state; it is not permissioning a positive edge that exists.

## P0.4 — is harvesting reachable, and does downstream policy honour it?

The replay used every policy-eligible row from the named production-origin 2026-08-06 tape and
the exact `run_config.json` policy. Replaying the recorded configuration reproduced all 26,928
pure-policy reasons with **zero mismatches**. The 7,524 outer-preflight rows remain separately
blocked and are not upgraded by any policy counterfactual.

| 2026-08-06 scenario, PASS rows only | Quote rows | Leading outcomes |
| --- | ---: | --- |
| Recorded configuration | 0 | 24,057 known-edge; 2,871 promotion |
| Map absent / every row `harvest_only`; promotion unchanged | **0** | 26,928 promotion |
| Promotion PASS; current map permission | 227 | 24,057 known-edge; 1,309 missing book; 1,045 information event; 275 disagreement; 15 wide spread |
| Promotion PASS; every row `harvest_only` | 2,386 | 13,105 missing book; 7,117 information event; 4,054 disagreement; 266 wide spread |
| Same, but no fair/model/candidate probability | **0** | 19,811 missing fair; 7,117 information event |

The 2026-08-07 132-row trace agrees. Its 110 policy-eligible rows replay exactly. Removing only the
map changes all 110 to promotion blocks; granting both promotion and harvest reaches the later
information-event gate on all 110 and still emits zero quotes.

So downstream does honour `harvest_only` only after promotion, preflight, model freshness, model
fair value, disagreement, information-event, book, spread, cadence, current-high and sizing gates.
That is not a no-model harvest route. The current configuration exposes `harvest_only` on Toronto,
but promotion is `BLOCK` on every post-boundary row, so it is unreachable in operation.

## What a countable day has actually certified

The live-forward countability gate does **not** require a quote. It certifies that every selected
market's paper-evidence preflight gates pass and that run-level useful work is live. The readiness
layer has a separate gate named `quote_permission_present_in_countable_paper`.

The mirror's seven counted dates make the distinction concrete. Six dates had 4,379 total
`QUOTE_HARVEST_MID` intent rows (300, 4,019, 5, 1, 15 and 39); the last counted date,
`2026-07-12`, had **1,848 rows and zero quote permissions**. Thus “countable” means the input and
evidence surface was eligible to evaluate. It does not certify that a strategy ran, that an order
was placed, that a fill occurred, or that any economic sample was obtained. With `fills.jsonl`
never written, the 7/55 clock is a data-plane qualification clock, not evidence that market making
worked.

## P1 — smallest honest design for model-independent market-centred paper quoting

**Design only; nothing below is implemented.** Deleting the map, changing a record, or relabelling
promotion is not sufficient. The smallest honest change is an explicit strategy lane with its own
operator permission and evidence contract:

1. Add a paper-only `market_harvest` permission that is separate from model promotion. Keep model
   `BLOCK` fully effective for edge/skew quotes; do not reinterpret it globally.
2. Give that lane a separate preflight profile. It must retain active-event validation, CLOB token
   discovery, current book/features, book continuity/freshness, information-event pulls, watcher
   health, exchange economics, post-only behaviour, and every risk/notional cap. It must not require
   `snapshot_model_rows` or `model_freshness` merely to quote the market mid.
3. Assemble harvest inputs from event metadata plus CLOB tokens/books/features rather than by
   iterating model snapshot rows. Today no snapshot rows means no policy rows.
4. Enter a harvest-specific decision branch before fair-value, model-age, overlay and
   model-disagreement calculations. Price only from the book mid, tick,
   `harvest_half_spread=0.01`, and `max_harvest_spread=0.08`; retain event, spread, cadence,
   current-high and risk sizing gates. Record that no model probability participated.
5. Keep shadow/paper mode, `live_trade_permission=false`, `$10 max_band_notional`, and reward
   assumption **$0**. Reward qualification requires $19.60 and is impossible under the current cap.

This requires an operator decision because it intentionally authorizes quoting without the model
promotion evidence the present gate demands. The present gate is internally consistent and should
not be called a defect.

One successful day would prove only route reachability and operational mechanics: nonzero quote
permissions, intended two-sided prices/sizes, lifecycle/post-only behaviour, uptime, gate exposure,
and a paper markout column under a declared **$0 reward** assumption. It would not identify `A` or
`f`, prove real fills, profitability, a unique break-even, reward eligibility, live readiness,
model edge, or promotion. One day is also not a powered comparative economic endpoint. Forward
execution capture remains the only route to `f`.

## Falsification results

- **“The map is loaded but incomplete” was falsified for the current retained population.** Coverage
  is 100%; no row fired `missing_known_edge_record`.
- **“Known-edge is the binding constraint” was falsified.** Removing it produces zero quotes because
  promotion survives on every policy-eligible row.
- **“The existing harvest branch is market-centred with no model input” was falsified.** It prices
  around mid, but requires fair probability, model age and a model-market disagreement veto.
- **“The gate is a repairable defect” was not established.** The source and replay show a deliberate
  conservative policy. The next action is an operator strategy decision, not a permission-map fix.

## Reproduction

Run from the production repository root. These commands read retained files and print to stdout;
they do not start the maker, call an endpoint, or write `data/`.

Exact post-boundary attribution and map join:

```powershell
$code = @'
import csv, json
from collections import Counter, defaultdict
from pathlib import Path

root = Path("data/mm_runs")
cells = defaultdict(Counter)
record_keys = Counter()
cell_state = set()
covered_cells = set()
for day in sorted(p for p in root.iterdir() if p.is_dir() and p.name != "_quarantine"):
    for run in sorted(p for p in day.iterdir() if p.is_dir() and p.name != "_quarantine"):
        tape = run / "quote_intents_long.csv"
        if not tape.is_file():
            continue
        with tape.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                target = str(row.get("target_date") or day.name)
                if target < "2026-07-31":
                    continue
                market = str(row.get("market_id") or "(missing)")
                cells[(target, market)][str(row.get("reason_code") or "(missing)")] += 1
                key = str(row.get("known_edge_record_key") or "")
                record_keys[key or "(missing)"] += 1
                cell = (market,) + tuple(str(row.get("known_edge_match_" + field) or "*") for field in (
                    "cutoff", "hour_utc", "band_distance_bucket", "band_type",
                    "casebook_taxonomy", "regime", "source_fresh", "source_freshness_state",
                    "book_imbalance_bucket",
                ))
                cell_state.add(cell)
                if key:
                    covered_cells.add(cell)
print("date,market,known_edge,promotion,stale,missing,total")
for (day, market), counts in sorted(cells.items()):
    print(day, market,
          counts["NO_QUOTE_KNOWN_EDGE_PERMISSION"],
          counts["NO_QUOTE_BLOCKED_PROMOTION"],
          counts["NO_QUOTE_STALE_INPUT"],
          counts["NO_QUOTE_MISSING_PREFLIGHT"],
          sum(counts.values()), sep=",")
print("record keys used", len(record_keys), record_keys)
print("cell coverage", len(covered_cells), len(cell_state))
print("map", json.loads(Path("data/backtest/mm_known_edge_map.json").read_text(encoding="utf-8-sig"))["summary"])
'@
$code | .\venv\Scripts\python.exe -
```

Actual-run policy replay:

```powershell
$code = @'
import csv, json
from collections import Counter
from datetime import datetime
from pathlib import Path
from weather.market.mm_policy import decide_quote

run = Path("data/mm_runs/2026-08-06/20260806T174937785434Z")
config = json.loads((run / "run_config.json").read_text(encoding="utf-8-sig"))["policy_config"]
outcomes = {name: Counter() for name in ("baseline", "no_map", "unlocked", "no_model")}
with (run / "quote_intents_long.csv").open("r", encoding="utf-8-sig", newline="") as handle:
    for row in csv.DictReader(handle):
        if row["reason_code"] in {"NO_QUOTE_STALE_INPUT", "NO_QUOTE_MISSING_PREFLIGHT"}:
            continue
        now = datetime.fromisoformat(row["generated_at_utc"].replace("Z", "+00:00"))
        outcomes["baseline"][decide_quote(dict(row), config=config, now=now)["reason_code"]] += 1
        harvest = dict(row, known_edge_permission="harvest_only",
                       known_edge_reason="known_edge_map_missing",
                       known_edge_record_key="", known_edge_allowed=False)
        outcomes["no_map"][decide_quote(harvest, config=config, now=now)["reason_code"]] += 1
        harvest["promotion_state"] = "PASS"
        outcomes["unlocked"][decide_quote(harvest, config=config, now=now)["reason_code"]] += 1
        no_model = dict(harvest, fair_probability="", model_probability="", candidate_p="")
        outcomes["no_model"][decide_quote(no_model, config=config, now=now)["reason_code"]] += 1
print(outcomes)
'@
$code | .\venv\Scripts\python.exe -
```

Crossed bootstrap:

```powershell
$code = @'
import csv, random, statistics
from collections import Counter, defaultdict
from pathlib import Path
from statistics import NormalDist

root = Path("data/mm_runs")
reasons = [
    "NO_QUOTE_KNOWN_EDGE_PERMISSION", "NO_QUOTE_BLOCKED_PROMOTION",
    "NO_QUOTE_STALE_INPUT", "NO_QUOTE_MISSING_PREFLIGHT",
]
cells = defaultdict(Counter)
for day in sorted(p for p in root.iterdir() if p.is_dir() and p.name != "_quarantine"):
    for run in sorted(p for p in day.iterdir() if p.is_dir() and p.name != "_quarantine"):
        tape = run / "quote_intents_long.csv"
        if not tape.is_file():
            continue
        with tape.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                target = str(row.get("target_date") or day.name)
                if target < "2026-07-31":
                    continue
                cells[(target, str(row.get("market_id") or "(missing)"))][
                    str(row.get("reason_code") or "(missing)")
                ] += 1
dates = sorted({day for day, market in cells})
markets = sorted({market for day, market in cells})

def ratio(sample_dates, sample_markets, reason):
    numerator = denominator = 0
    for day in sample_dates:
        for market in sample_markets:
            counts = cells[(day, market)]
            numerator += counts[reason]
            denominator += sum(counts.values())
    return numerator / denominator

def quantile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[min(lower + 1, len(ordered) - 1)] * weight

rng = random.Random(20260948)
replicates = {reason: [] for reason in reasons}
deltas = []
early, late = dates[:4], dates[4:]
for _ in range(30000):
    sampled_dates = [rng.choice(dates) for _ in dates]
    sampled_markets = [rng.choice(markets) for _ in markets]
    for reason in reasons:
        replicates[reason].append(ratio(sampled_dates, sampled_markets, reason))
    paired_markets = [rng.choice(markets) for _ in markets]
    sampled_early = [rng.choice(early) for _ in early]
    sampled_late = [rng.choice(late) for _ in late]
    deltas.append(
        ratio(sampled_late, paired_markets, reasons[0])
        - ratio(sampled_early, paired_markets, reasons[0])
    )
print("clusters", len(dates), len(markets), len(cells))
for reason in reasons:
    values = replicates[reason]
    print(reason, ratio(dates, markets, reason),
          quantile(values, 0.025), quantile(values, 0.975))
delta = ratio(late, markets, reasons[0]) - ratio(early, markets, reasons[0])
se = statistics.pstdev(deltas)
z975 = NormalDist().inv_cdf(0.975)
z80 = NormalDist().inv_cdf(0.8)
noncentrality = abs(delta) / se
power = ((1 - NormalDist().cdf(z975 - noncentrality))
         + NormalDist().cdf(-z975 - noncentrality))
print("late_minus_early", delta, quantile(deltas, 0.025), quantile(deltas, 0.975),
      "power", power, "80pct_mde", (z975 + z80) * se)
'@
$code | .\venv\Scripts\python.exe -
```

No workstation scratch path is required. Repository verification:

```powershell
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
scripts\ops\roll_verdict.ps1 -Branch codex/workstation-can-the-maker-quote-at-all-2026-09-48a
```

## Verification and handback

- Documentation audit: **PASS** — 18 agent files and 723 Markdown files.
- Repository-owned roll verdict on analysis commit `526617db222ea03ce36eb1cdd1b21f8b405576ad`:
  **ROLL-FREE**. It compared one changed file and found zero importable files. The live snapshot,
  CLOB and observation-trigger closures were current; the 300.7-hour dormant CLOB-enrichment
  closure was mechanically subsumed because all 21 files in it are covered by a live closure.
- Per-file roll verdict: `docs/roadmap/agent-report-2026-08-11-workstation-maker-quote-gate.md`
  enters no runtime closure and is roll-free.
- What was not done: no registration, no production write, no maker/chain/settlement run, no loop
  start or restart, no endpoint call, no known-edge-map edit, no fit, no candidate, no promotion,
  no order, no live-trading enablement, and no merge.
- Analysis/report commit: `526617db222ea03ce36eb1cdd1b21f8b405576ad`.
- Branch: `codex/workstation-can-the-maker-quote-at-all-2026-09-48a`.

## Appendix — exact post-boundary date × market reason counts

| Date | Market | Known-edge | Promotion | Stale | Missing preflight | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2026-07-31 | atlanta | 4,180 | 0 | 847 | 11 | 5,038 |
| 2026-07-31 | austin | 4,477 | 0 | 550 | 11 | 5,038 |
| 2026-07-31 | chicago | 4,488 | 0 | 550 | 0 | 5,038 |
| 2026-07-31 | dallas | 4,477 | 0 | 550 | 11 | 5,038 |
| 2026-07-31 | denver | 4,763 | 0 | 264 | 11 | 5,038 |
| 2026-07-31 | houston | 4,488 | 0 | 550 | 0 | 5,038 |
| 2026-07-31 | los-angeles | 1,243 | 0 | 3,795 | 0 | 5,038 |
| 2026-07-31 | miami | 4,191 | 0 | 847 | 0 | 5,038 |
| 2026-07-31 | nyc | 4,147 | 0 | 847 | 44 | 5,038 |
| 2026-07-31 | san-francisco | 4,994 | 0 | 11 | 33 | 5,038 |
| 2026-07-31 | seattle | 5,027 | 0 | 11 | 0 | 5,038 |
| 2026-07-31 | toronto | 0 | 4,180 | 847 | 11 | 5,038 |
| 2026-08-01 | atlanta | 5,302 | 0 | 792 | 1,540 | 7,634 |
| 2026-08-01 | austin | 3,971 | 0 | 2,189 | 1,474 | 7,634 |
| 2026-08-01 | chicago | 5,621 | 0 | 528 | 1,485 | 7,634 |
| 2026-08-01 | dallas | 3,993 | 0 | 2,167 | 1,474 | 7,634 |
| 2026-08-01 | denver | 5,874 | 0 | 264 | 1,496 | 7,634 |
| 2026-08-01 | houston | 5,621 | 0 | 528 | 1,485 | 7,634 |
| 2026-08-01 | los-angeles | 6,116 | 0 | 33 | 1,485 | 7,634 |
| 2026-08-01 | miami | 5,335 | 0 | 803 | 1,496 | 7,634 |
| 2026-08-01 | nyc | 5,346 | 0 | 803 | 1,485 | 7,634 |
| 2026-08-01 | san-francisco | 6,127 | 0 | 33 | 1,474 | 7,634 |
| 2026-08-01 | seattle | 6,116 | 0 | 22 | 1,496 | 7,634 |
| 2026-08-01 | toronto | 0 | 3,707 | 2,431 | 1,496 | 7,634 |
| 2026-08-02 | atlanta | 0 | 0 | 6,490 | 1,507 | 7,997 |
| 2026-08-02 | austin | 11 | 0 | 6,501 | 1,485 | 7,997 |
| 2026-08-02 | chicago | 11 | 0 | 6,457 | 1,529 | 7,997 |
| 2026-08-02 | dallas | 1,980 | 0 | 4,521 | 1,496 | 7,997 |
| 2026-08-02 | denver | 264 | 0 | 6,215 | 1,518 | 7,997 |
| 2026-08-02 | houston | 11 | 0 | 6,435 | 1,551 | 7,997 |
| 2026-08-02 | los-angeles | 2,563 | 0 | 3,938 | 1,496 | 7,997 |
| 2026-08-02 | miami | 0 | 0 | 6,501 | 1,496 | 7,997 |
| 2026-08-02 | nyc | 0 | 0 | 6,479 | 1,518 | 7,997 |
| 2026-08-02 | san-francisco | 2,607 | 0 | 3,905 | 1,485 | 7,997 |
| 2026-08-02 | seattle | 561 | 0 | 5,951 | 1,485 | 7,997 |
| 2026-08-02 | toronto | 0 | 2,057 | 4,444 | 1,496 | 7,997 |
| 2026-08-03 | atlanta | 1,914 | 0 | 946 | 0 | 2,860 |
| 2026-08-03 | austin | 2,222 | 0 | 616 | 22 | 2,860 |
| 2026-08-03 | chicago | 2,233 | 0 | 616 | 11 | 2,860 |
| 2026-08-03 | dallas | 2,222 | 0 | 616 | 22 | 2,860 |
| 2026-08-03 | denver | 2,552 | 0 | 297 | 11 | 2,860 |
| 2026-08-03 | houston | 11 | 0 | 2,827 | 22 | 2,860 |
| 2026-08-03 | los-angeles | 2,816 | 0 | 0 | 44 | 2,860 |
| 2026-08-03 | miami | 0 | 0 | 2,860 | 0 | 2,860 |
| 2026-08-03 | nyc | 0 | 0 | 2,827 | 33 | 2,860 |
| 2026-08-03 | san-francisco | 2,849 | 0 | 0 | 11 | 2,860 |
| 2026-08-03 | seattle | 2,860 | 0 | 0 | 0 | 2,860 |
| 2026-08-03 | toronto | 0 | 1,914 | 946 | 0 | 2,860 |
| 2026-08-04 | atlanta | 5,357 | 0 | 1,089 | 1,474 | 7,920 |
| 2026-08-04 | austin | 5,335 | 0 | 1,078 | 1,507 | 7,920 |
| 2026-08-04 | chicago | 5,357 | 0 | 1,078 | 1,485 | 7,920 |
| 2026-08-04 | dallas | 5,346 | 0 | 1,078 | 1,496 | 7,920 |
| 2026-08-04 | denver | 5,643 | 0 | 759 | 1,518 | 7,920 |
| 2026-08-04 | houston | 5,346 | 0 | 1,067 | 1,507 | 7,920 |
| 2026-08-04 | los-angeles | 5,918 | 0 | 528 | 1,474 | 7,920 |
| 2026-08-04 | miami | 3,146 | 0 | 1,078 | 3,696 | 7,920 |
| 2026-08-04 | nyc | 5,346 | 0 | 1,089 | 1,485 | 7,920 |
| 2026-08-04 | san-francisco | 5,918 | 0 | 517 | 1,485 | 7,920 |
| 2026-08-04 | seattle | 5,918 | 0 | 517 | 1,485 | 7,920 |
| 2026-08-04 | toronto | 0 | 5,357 | 1,089 | 1,474 | 7,920 |
| 2026-08-05 | atlanta | 5,665 | 0 | 902 | 693 | 7,260 |
| 2026-08-05 | austin | 5,929 | 0 | 572 | 759 | 7,260 |
| 2026-08-05 | chicago | 5,951 | 0 | 605 | 704 | 7,260 |
| 2026-08-05 | dallas | 2,178 | 0 | 4,400 | 682 | 7,260 |
| 2026-08-05 | denver | 792 | 0 | 5,786 | 682 | 7,260 |
| 2026-08-05 | houston | 5,918 | 0 | 605 | 737 | 7,260 |
| 2026-08-05 | los-angeles | 913 | 0 | 5,456 | 891 | 7,260 |
| 2026-08-05 | miami | 528 | 0 | 6,039 | 693 | 7,260 |
| 2026-08-05 | nyc | 5,654 | 0 | 858 | 748 | 7,260 |
| 2026-08-05 | san-francisco | 2,728 | 0 | 3,773 | 759 | 7,260 |
| 2026-08-05 | seattle | 6,567 | 0 | 11 | 682 | 7,260 |
| 2026-08-05 | toronto | 0 | 4,763 | 1,804 | 693 | 7,260 |
| 2026-08-06 | atlanta | 3,267 | 0 | 968 | 0 | 4,235 |
| 2026-08-06 | austin | 3,597 | 0 | 638 | 0 | 4,235 |
| 2026-08-06 | chicago | 3,597 | 0 | 638 | 0 | 4,235 |
| 2026-08-06 | dallas | 3,586 | 0 | 638 | 11 | 4,235 |
| 2026-08-06 | denver | 814 | 0 | 3,410 | 11 | 4,235 |
| 2026-08-06 | houston | 3,586 | 0 | 638 | 11 | 4,235 |
| 2026-08-06 | los-angeles | 4,224 | 0 | 0 | 11 | 4,235 |
| 2026-08-06 | miami | 495 | 0 | 3,718 | 22 | 4,235 |
| 2026-08-06 | nyc | 484 | 0 | 3,751 | 0 | 4,235 |
| 2026-08-06 | san-francisco | 4,235 | 0 | 0 | 0 | 4,235 |
| 2026-08-06 | seattle | 3,872 | 0 | 0 | 363 | 4,235 |
| 2026-08-06 | toronto | 0 | 3,267 | 968 | 0 | 4,235 |
| 2026-08-07 | atlanta | 2,321 | 0 | 891 | 11 | 3,223 |
| 2026-08-07 | austin | 2,552 | 0 | 594 | 77 | 3,223 |
| 2026-08-07 | chicago | 2,640 | 0 | 572 | 11 | 3,223 |
| 2026-08-07 | dallas | 2,563 | 0 | 616 | 44 | 3,223 |
| 2026-08-07 | denver | 2,827 | 0 | 385 | 11 | 3,223 |
| 2026-08-07 | houston | 2,541 | 0 | 660 | 22 | 3,223 |
| 2026-08-07 | los-angeles | 3,157 | 0 | 66 | 0 | 3,223 |
| 2026-08-07 | miami | 11 | 0 | 3,212 | 0 | 3,223 |
| 2026-08-07 | nyc | 2,321 | 0 | 869 | 33 | 3,223 |
| 2026-08-07 | san-francisco | 3,069 | 0 | 110 | 44 | 3,223 |
| 2026-08-07 | seattle | 3,168 | 0 | 44 | 11 | 3,223 |
| 2026-08-07 | toronto | 0 | 2,244 | 968 | 11 | 3,223 |

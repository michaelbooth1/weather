# Bounded maker opportunity capture and report

Status: canonical public-evidence diagnostic contract. Owner: market capture
and market reporting. No order, account, promotion or paid-profit authority.

The source collector is `weather.market.maker_opportunity_capture`;
`weather.market.maker_opportunity_inputs` validates its captured responses;
`weather.reporting.market.maker_opportunity_report` produces the offline report.
It calls the existing [explicit-input calculator](maker-incentive-feasibility.md)
for order and capital checks. It does not implement another reward formula.

## Scope and evidence

Freeze a selection before obtaining new books. Its JSON contains a nonempty
`policy_id` and one to six `selected` rows, each with `condition_id`,
`location_id`, `target_date`, and the canonical dated `event_slug`.
An optional `token_ids` object explicitly maps `YES` and `NO`. The capture
command requires the exact selection-file SHA-256 and also records the
canonical selection-object hash. Selection criteria and earlier-source hashes
belong in the selection manifest; this collector never ranks or expands it.

Only unauthenticated International public GETs are supported. Each condition
has one Gamma event response, CLOB market parameters, at most two exact-condition
raw-reward pages, and one book for each explicitly named outcome. Eight fixed
official documentation pages bind the contemporaneous rules. Sponsored reward
folding is explicitly disabled. A terminal `LTE=` cursor is necessary for
reward completeness; a missing terminal, duplicate condition, repeated cursor
or wrong identity blocks the attempt. API calendar dates remain calendar
dates, including the open-ended configuration sentinel.

The limits are resource and sampling bounds for this diagnostic, not venue
limits or economic optima: six conditions, two reward pages per condition,
2 MiB per response, 16 MiB of total raw bodies, and 32 MiB per packet/report.
They permit at most 44 sequential requests, each with a timeout at most 20
seconds. Review these bounds if a required exact-condition response cannot fit;
never silently truncate it or broaden the sample.

Every response retains exact bytes, SHA-256, method, URL, retrieval time, status
and origin under the [exchange source contract](exchange-economics-source-evidence.md).
A later capture error preserves completed responses with `INCOMPLETE` status.
A new attempt always uses a new output path. The report reparses the retained
bytes, validates complete expected scope and pagination, checks token and
condition agreement, and rejects synthetic fixture provenance by default.
An unsigned local capture is retained transport evidence, not independent
authentication of the venue.

Book best prices are selected by extrema, without assuming array order.
CLOB market and both book minimum/tick values must agree. The derived terms
manifest binds Gamma, CLOB parameters, rewards and both books by source hash.
The native event registry determines C/F identity; temperature quantities are
never converted by this report.

## What the initial adapter establishes

The official [order placement contract](https://docs.polymarket.com/trading/place-orders)
defines the book's `min_order_size` as shares and provides the quantity precision
table. The adapter binds that captured statement and table. Gamma's differently
documented `orderMinSize` is not substituted.

For each selected condition, the adapter considers a YES BUY at the captured
bid, a NO BUY at its bid, and the simultaneous pair. Quantity reaches both
exchange and reward minimums on the documented share grid. It checks direct
and complementary marketability, tick, accepting-order status, and backed
capital using the existing calculator.

Default planning inputs are 10 collateral units per order, a backed 100-unit
wallet and a 10-unit cleanup reserve. These are explicit scenario assumptions,
not account balances, recommendations or live limits. Existing inventory,
other own orders and reservations are assumed absent. A quote's affordability
does not prove its risk, fill probability or reward eligibility.

Input comparability uses a chosen 120-second book-retrieval age and 15-second
paired-book skew at the capture's completion time. These bounds belong only
to the historical diagnostic. A report generated later does not refresh its
books or make it current live evidence. Re-capture when a new observation is
required.

The initial adapter deliberately supplies no qualified adjusted midpoint or
campaign interval. Consequently, its terminal economic verdict is
`EVIDENCE_BLOCKED`, even when order/capital checks succeed. The calculator's
missing-Campaign blocker is rendered as `campaign:interval_unqualified`;
observed API allocations remain visible separately. The structural scoring
parameters are unused while the midpoint is absent; no score, reward share,
payment amount or earning-duration qualification is produced.

The [liquidity methodology](https://docs.polymarket.com/programs/liquidity-rewards)
names a size-cutoff-adjusted midpoint but does not, by that phrase alone,
identify a reproducible algorithm and value for the captured books.
Ordinary midpoint and anonymous aggregate depth cannot fill the missing
midpoint or per-maker denominator. Calendar allocation dates and daily
distribution timing also do not independently bind all epoch/sample semantics.
A source-backed extension must resolve those inputs before the adapter can
produce a qualified incentive scenario. The pure calculator remains available
for separately qualified explicit inputs.

Loss sensitivity is conditional algebra: suppose an entire future epoch pays
a stated pool, and compare specified all-in costs with the fraction of that
pool required to break even. A scenario may use the numeric configured daily
rate as a hypothetical pool size, but does not derive an actual pool, prorate
it by hours, infer fiat conversion, or establish minimum-payment treatment.
Adverse selection, inventory/settlement loss, forced exits, fees, cash operations
and operating costs must all be covered in the same asset. The explicit
zero-payment case retains the full cost as loss.

`paid_rewards` and `realized_pnl` remain null. The report does not select a
qualified primary/reserve opportunity and grants no live authority.

## Commands and verification

Run from the intended checkout with its canonical package bootstrap and project
interpreter. Public capture is a small, discrete read under the owning host's
authorized public-read scope; it is not a scheduled collector. The report reads
one bounded packet and makes at most eighteen pure calculator calls. Ordinary
host load rules still govern tests, larger replay and other heavy work.

```powershell
python -m weather.market.maker_opportunity_capture --selection <selection.json> --selection-sha256 <sha256> --output <new-capture.json>
python -m weather.reporting.market.maker_opportunity_report --capture <capture.json> --capture-sha256 <sha256> --output <new-report.json> --markdown <new-report.md>
```

Outputs default to ignored repository-owned `data/backtest/` paths through
`weather.paths`. Explicit paths permit isolated attempt directories.
Read-only reporting on a workstation consumes an explicitly handed-off packet;
it never reads or updates the frozen mirror and never queries providers.

Focused cases live in `tests/market/test_maker_opportunity_capture.py`.
Run that file, the existing calculator/source tests, schema registry and import
architecture checks through the required host wrapper. They cover native units,
explicit outcome ordering, tampered bytes, wrong identities, unknown request
scope, pagination, quantity/minimum provenance, preserved unknown rewards,
create-new publication, and the actual imported source paths.

## Update when

Update alongside collector/report schemas, request scope or bounds, source
qualification, supported order plans, scenario semantics or CLI flags. Current
campaign observations and decisions belong in retained reports and item 330.

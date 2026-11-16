# Complete pairs after a fill

Status: implementation contract. This file owns the complete-pairs quote
proposal, its inventory evidence and offline touch replay. Read it when changing
`lfc_pair_*`; [Pin B](lfc-autostart-pinb.md) owns the campaign and policy,
and [LFC autostart](lfc-autostart.md) owns execution authority and gates.

## Inventory and quotes

`post_fill_mode` is economic. Omitted historical snapshots mean `continue`;
explicit `continue` has the same economic digest. `complete_pairs` is a Pin B
successor beginning at policy revision 6. Changing the mode requires a new
revision and remains subject to the original freeze/evidence-lane rules.

`lfc_pair_inventory` consumes the canonical `lfc_own_trades` projection, with
its existing `money_counted` lifecycle rule. Exact own-order terminal totals
must agree before campaign lots authorize another quote. Provisional/final
state and provenance stay in the journal. Four-decimal positions, wallet
balances and a parent public trade's size never supply the residual quantity.
Live refresh reuses the band's K6 projection, so lagging REST cannot downgrade
a confirmed stream execution. The successful cleanup reconciliation GET also
feeds it, including fills first proved during final cancellation.
The SDK's retained `matched_at` supplies the canonical exchange match clock;
missing or conflicting time/identity/quantity evidence refuses.
Keep the canonical execution price for FIFO cost. Venue division can express
a price just beyond the posted tick; bind its allocation to the known limit
by equal cost under the existing upward native-cost rounding rule. Quantities
and FIFO costs retain trade precision.

For each condition, match opposing campaign-owned lots FIFO at trade
precision. Subtract evidenced capital-book removals, then calculate signed
`U = YES - NO`, remaining cost, and the average cost of the unmatched shares.
At `abs(U) <= 0.0001` the original selected arm applies. Above that threshold,
only the complementary leg can receive a new quote. The original cheap/paired
assignment is retained, including when the complement is the expensive leg.

The complementary quote keeps the ordinary full size and uses
`floor_to_tick(min(normal_quote, 1 - unpaired_average_cost - 0.015))`.
The minimum-margin calculation is exact until the final downward tick rounding.
A failed price bound, venue minimum, reward minimum or ordinary screen grants
no order. A valid proposal still needs the ordinary freshness, inventory,
cash, gross-cap, cooldown, budget, fixed-end and cleanup gates. Neither touch
evidence nor locked pair margin releases capital or proves settlement cash.
Like the existing depth pause, a price-only pause rechecks after sixty seconds
without repeating the fill cooldown when cleanup found no new fill.

A completion larger than the residual creates opposite residual inventory.
Recompute it symmetrically, retaining the existing money limits. A partial
completion of mixed-cost FIFO lots can have individual allocated margins below
the average-cost target; report those actual slices without replacing the
approved average-cost pricing formula. An unchanged binding cap must not spend
the requote budget merely because its distance from midpoint remains wide.

## Evidence and recovery

Retain signed U, residual quantity/cost/average, the effective and original leg
sets, normal price, raw pair cap, rounded proposal, screen refusal, completion
order/fill identities, canonical lifecycle/provenance, FIFO pair allocations,
locked margins, over-completion count, and UTC completion intervals.
The inventory adapter reconstructs the condition across campaign sessions;
missing recovered inventory never defaults to flat. Existing selection and
recovery authority still decide whether that condition may run.

Completion elapsed time is bounded by the band's fixed end. Repeated lifecycle
or provenance updates cannot double-count a fill or append to a closed terminal
journal. The ordinary post-fill book recorder also covers bands that continue
quoting the complement.

## Offline replay

For owner-supplied policy copies, `python -m weather.market.lfc_pair_policy
--upgrade-from <absolute-copy> --output <absolute-new-file>` prepares a disabled
successor. It changes only the ordinary revision, policy revision and mode of
a disabled revision-5 source. All money, dates and clock fields carry through;
the command has no task, account or enrollment capability.

The replay constructs no venue, credential resolver, live tick or order
capability. Run `python -m weather.market.lfc_pair_replay --help` for its two
required absolute paths. Heavy invocations use the workstation wrapper's
`weather_heavy` kind and this exact module, following the
[host load policy](HOST_LOAD_POLICY.md).

`--input-root` is an immutable copy directory, with a `copy_manifest.json`
array. Each row has the source path, absolute `copy` path, byte `length` and
`sha256`. Reads must be listed, hash-bound regular files inside that directory.
The copied inputs are the campaign policy, ledger, A091-format
`fills.csv`/`bands.csv`, session selections and retained per-band journals from the
two November 13 filled sessions. K6 verifies CSV fill identities and quantities
against stream and terminal REST executions and reconstructs exact held FIFO inventory.
The replay uses K6's execution prices after validating the native cost binding.
`--output` is a new JSON file outside the copy directory. Existing output files
are never overwritten. Source paths in the manifest are provenance only;
the replay never opens them.

The actual A inventory and the B-filtered observed-fill trace are distinct.
The latter suppresses observed same-side additions and prices above B's cap,
and assumes no replacement executions. For each proposed completion, a later
positive displayed ask at or below its price is **touch evidence**, never a
fill. Missing books produce missing touch evidence rather than a negative.
Book collection clocks, the cooldown and fixed end bound the comparison.

The report retains book coverage gaps and the illustrative independent binary
payout proxy `sum(U**2 * p * (1-p))`, using the same retained market mids for A
and B. These are descriptive inventory sensitivities, not profitability,
calibrated probabilities or a causal fill forecast. A separately labelled
full-size touch sensitivity shows the opposite residual a hypothetical
twenty-share execution would create, even when displayed size is smaller.

A full execution-day dry run additionally needs continuous opening-to-close
books and counterfactual private inventory, acknowledgements, stream,
geoblock pass/fail and cash proofs. The public-book replay identifies those
missing inputs instead of treating a recorded touch as that proof.

## Update when

Update when the post-fill economic mode, FIFO inventory binding, price formula,
evidence fields, replay inputs, touch semantics or supported CLI changes.

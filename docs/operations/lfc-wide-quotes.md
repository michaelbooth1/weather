# Wide quotes and consecutive policy successors

Status: implementation contract. This file owns wide quote distance, city
assignment, order scoring evidence and disabled successor preparation.
Read it when changing `lfc_wide_*`. [Pin B](lfc-autostart-pinb.md) owns campaign
admission; [pair completion](lfc-complete-pairs.md) owns inventory and its cap.
Code and policy preparation grant no activation or order authority.

## Prices and resting legs

`quote_offset_mode` is `standard` or `wide`. Historical omitted fields and
explicit standard defaults retain the original economic digest, arm assignment,
proposal bytes and controller trace, in both post-fill modes. Wide normal
quotes use the supported `wide_offset_cents`, currently exactly `3.0`.
The original date/city distance and paired/cheap hashes are still computed;
wide mode changes the effective offset and retains the original assignment.

Each native BUY price floors outward to the existing cent tick. A normal wide
entry must be in `[offset - 0.5c, 4.5c)` from the reward midpoint and strictly
inside the venue reward spread. A rounded entry at the outer boundary waits;
it is never tightened to manufacture reward eligibility.

A resting wide leg keeps the inclusive `[offset - 0.5c, 4.5c]` leave-alone band.
Only an affected leg with a different valid replacement can reprice. This also
applies to the wide completion leg; an unchanged binding pair cap spends no
reprice merely for remaining outside the band. Completion price calculation
still belongs to the pair module: floor the minimum of wide normal price and
the residual-average-cost cap. A valid complementary hedge can score zero.
Every ordinary price, minimum, depth, cash, capital and freshness screen applies.

A failed fresh normal entry uses the existing cancel/prove/wait loop, checking
again after sixty seconds. Without a new fill it does not repeat a fill
cooldown. A fill during cleanup still requires the original inventory proof
and cooldown. Size, money limits, submit/reprice budgets, fixed end, STOP,
geoblock and cleanup are unchanged.

## Explicit city partitions and evidence

`city_quote_offset_assignments` is an optional JSON list. Each row contains
`date`, `standard_cities` and `wide_cities`. Dates must be sorted, unique learning
dates. City lists must be sorted and unique, disjoint, and together exactly
cover `market_ids`. On that date the explicit partition overrides the global
mode. Other dates use the global mode. There is no runtime randomization.

The assignment list, mode and offset participate in economic revision,
digest, claim and immutable freeze binding. Deleting prior wide fields at the
same revision cannot silently restore standard economics. An economic edit
after the original seal remains successor learning; no seal is rewritten.

Per-order journal evidence binds the acknowledged order ID to the effective
mode, requested offset, adjusted reward midpoint, rounded scoring distance,
native per-leg reward score, size, reward terms, completion status and
assignment source. Each native leg scores once. Existing Q-min aggregation
and its central one-sided divisor remain unchanged. A score is planning
evidence, never an accrual or payment receipt.

## Create-only disabled successors

Use `python -m weather.market.lfc_wide_policy` from qualified code with an
owner-supplied disabled current policy copy. This helper accepts Pin B policies
at revision 6 or later and increments both ordinary and economic revisions.
It carries every unrelated key unchanged. It refuses an enabled source and
an existing output, and has no account, task or enrollment capability.

```powershell
python -m weather.market.lfc_wide_policy --upgrade-from <absolute-current-copy> --output <absolute-new-file> --post-fill-mode continue --quote-offset-mode wide
python -m weather.market.lfc_wide_policy --upgrade-from <absolute-wide-copy> --output <absolute-pairs-wide-file> --post-fill-mode complete_pairs --quote-offset-mode wide
python -m weather.market.lfc_wide_policy --upgrade-from <absolute-pairs-wide-copy> --output <absolute-split-file> --post-fill-mode complete_pairs --quote-offset-mode standard --city-assignments <absolute-partitions-json>
```

The optional assignment file is a JSON list in the format above. Supplying it
replaces that field; omitting it carries the existing list. Supply an empty
list explicitly to clear it. `--wide-offset-cents` accepts only the supported
value. Each invocation takes current+1; do not reuse an earlier ordinal for
different economics. A crossover can bind both dates in one explicit list;
the next day's disabled successor can carry that list unchanged. Reconcile
example ordinals with the owner's current policy at release-card time.

## Update when

Update with changes to supported offsets, entry/resting bands, city assignment,
scoring evidence, successor flags, revision handling or freeze semantics.

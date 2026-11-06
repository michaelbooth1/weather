# WS-1(b) maker feasibility: admission preflight

Historical task record, T002. **Incomplete: no empirical feasibility or power verdict.**
Read for the computation contract and the exact admission blocker; use the
[edge trial charter](../operations/EDGE_TRIAL_CHARTER.md) for trial requirements.
This note does not establish that T1 can or cannot conclude by year end.

## What was prepared and checked

The isolated branch was created from fetched `origin/master`. Unrelated changes
in the main checkout were preserved. Binding task inputs were `COMMON.md`,
T002's plan sections 1, 2 and 5, the WS-1(a) inventory, and repository canon.
The direct user task's dev-only cutoff is event date 2026-10-14; the newer
STATE_OF_PLAY opening paragraph also names that cutoff for maker evidence.
No maker-shadow tape, credential, sealed store or trial-date price was read.

Directory-entry inspection finds only the twelve built-in cities in the named
event/tape copies. There are no international R1/R2 event directories in those
roots. This does not prove absence in all stores named by the older inventory;
no complete inventory or content scan ran.

Bounded shape checks opened first records for September 25 maker evidence,
October 1 Atlanta public execution and summary data, and an August 15 Atlanta
settlement. They confirm that the copies contain per-condition reward records,
split token books and public executions. The settlement excerpt includes the
venue reconciliation's resolved winning condition. They do not establish
complete coverage, unique executions or any sample mean.

## Fixed computation contract

The archived `COMPUTATION_CONTRACT.md` fixes paired post-only YES/NO buys one
cent outward from the cumulative-size-adjusted midpoint, outward tick rounding,
20/50/100-share cases, and a separate actual-cap case. Historical terms must
precede the quote; unobserved intervals are not extrapolated to full days.

The informed-fill sensitivity fractions are **0.10, 0.25 and 0.50**, fixed before
computation. They are optimistic, central and conservative stress assumptions;
the small own-fill record does not identify population f. The middle case is
near one adverse short-horizon lot among five, not a fitted estimate or a
settlement-toxicity measurement. See [EF Â§10m](../operations/ESTABLISHED_FINDINGS.md).

The venue uses quadratic distance scores, complementary sides, a two-sided
minimum with a midrange single-sided adjustment, and normalization over makers.
The minimum size and maximum spread are market-specific. Public L2 gives
aggregate price-level size, without maker identities or constituent order
sizes. Thus the exact denominator is not identified. The prepared reward
scanner reports an aggregate-book scenario and a conservative displayed-book
interval; neither is paid income or an estimate of competition's response to
our posting. The live pilot's competition response remains material.
Source: [official liquidity reward methodology](https://docs.polymarket.com/programs/liquidity-rewards).

`study.py` is a prepared, unexecuted reward-screening script, **not a completed
queue-aware simulator**. Its self-check has not run. It verifies decompressed
journal hashes and offsets, admits token books by event date, matches captured
terms as of the sample, and emits bounded-day receipts. It supplies no fills,
net P&L or power results. Before running the last dev capture days, review the
universe journals' embedded selection scores for later event dates; do not
open co-located later-event economic data merely to filter it afterward.

## Arithmetic limits, not empirical results

At paired prices 0.49/0.49, backing costs 19.60, 49.00 and 98.00 for 20, 50 and
100 shares per side. Only the first meets the 19.60 per-band cap; each order
must also meet the 15.80 cap. Twenty shares cannot earn rewards when the
captured minimum is 100. Same-day versus next-day eligibility must use the
captured terms: EF Â§10m records intraday changes, so a blanket daily minimum
would be wrong. No empirical eligibility fraction was computed.

With 300 cash there is room for at most fifteen fully backed 19.60 bands,
assuming no inventory already ties up capital. At that backing, twelve cities
with one band use 235.20; two and four bands everywhere use 470.40 and 940.80.
At most seven complete two-band city-events or three complete four-band
city-events fit. Do not rely on venue acceptance of unbacked cross-market orders.
These limits concern paired quotes; they do not rule out cheaper one-sided
designs permitted by the venue's midrange scoring rule.

October 15 through December 27 contains **74 calendar dates**, not 74 verified
countable clusters. At the receipt's date, 23 calendar dates are through today
and 51 are strictly future. Settlement and evidence gaps can only lower the
usable total. More bands or cities cannot multiply the independent date count.

For independent date aggregates with positive mean mu and SD sigma_d, the
normal-approximation planning number for a one-sided 95% lower bound to cross
zero at the point estimate is `ceil((1.644854*sigma_d/mu)^2)`. Eighty-percent
power uses `ceil(((1.644854+0.841621)*sigma_d/mu)^2)` instead. With 74 dates the
corresponding mu/sigma_d thresholds are 0.19121 and 0.28905. These are different
criteria. They omit small-sample, serial-dependence, sequential-look and Holm
penalties. No N is computed without a matched measured effect and variance.

For K bands, the date variance depends on all within-date band covariances;
dividing the one-band variance by K without measuring those covariances is
invalid. The old four-date study's N=706 is not a new estimate for these designs
or for a measured effect: [EF Â§10r](../operations/ESTABLISHED_FINDINGS.md).

## Admission blocker and remaining work

The required workstation wrapper refused the prepared script's `--self-check`
with exit 1 **before Python started**:

> research script has no single allowlist entry

[Host load policy](../operations/HOST_LOAD_POLICY.md#workstation-and-portable-executor-scope)
requires an exact reviewed script path/hash. The
[delegation contract Â§2](../operations/DELEGATION_CONTRACT.md#2-standing-boundaries--inherited-by-every-delegated-workstation-mission)
says to request an unassigned file rather than taking it. The task assigns
scripts/outputs under T002 and a research note, not the guard's allowlist.
The requested scope expansion is one entry in `scripts/ops/workload_admission.ps1`.
No guard was edited or bypassed. Owner-chat authorization was requested and
was pending when this preflight was written.

The remaining work is the empirical scan, a queue-back fill/inventory/rebate
simulation with measured latency and actual venue settlement, city/date
aggregation and covariance, capital-feasible design comparison, and power.
Items 1â€“2 are not complete; `INTERIM.md` explicitly reports that fact to the
polling master. There is no supported city growth ranking. First use pilot
receipts to calibrate rewards, fills and markouts, then rank designs; do not
substitute the old passive-selection reward estimates.

The branch push also failed: Git could not obtain a GitHub username in the
noninteractive executor, and `gh auth status` reported the existing account's
authentication invalid. No credential or token was opened or printed, and no
login or machine configuration was changed. The local commit is retained; a
prerequisite-bound Git bundle in the output archive provides a handback path
for the master. The branch has not been published or merged.

## Receipts

The workstation-only archive is `C:\t\codex\T002\out\`. It contains the
prepared script and computation contract, `arithmetic.ps1`, its generated
`calendar_and_capital.json`, `admission.txt` and `receipt.json`. `SHA256SUMS`
identifies every archived file except itself. These are ignored local artifacts,
not presumed to exist in a clean checkout. The task's `INTERIM.md` names the
exact script hash. The branch is a preflight handback, not a finished study.

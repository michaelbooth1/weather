# WS-1(b): maker feasibility and power on the supplied dev copies

Historical descriptive study for T002. Read for the measured eligibility,
execution-coverage limits and conditional power calculation; use the
[edge trial charter](../operations/EDGE_TRIAL_CHARTER.md) for trial gates.
All event economics read here are dated no later than 2026-10-14.
This study supplies no fair-trial evidence or live-order authority.

## G1 verdict

**T1 year-end feasibility is not identifiable from these inputs at either
0.10x planning or 1.0x optimistic reward accrual.** The current study cannot
promise a December verdict and cannot establish a universal maker kill.
Missing fills are not zero fills, and a null net result is not no edge.
The simulator has not passed the charter's own-pilot accuracy gate.

## Data, policy and units

The approved run committed 20 UTC-day passes,
240 event execution passes and 2,134 band/local-DTE
cohorts across the twelve built-in cities. The day passes verified
26,566,613,576 decompressed journal bytes.
September 25 begins at UTC hour 06; the book window ends at the closing
midnight of UTC October 14 (2026-10-15T00:00Z).
Earlier execution tapes do not supply the matching full L2 and as-of
reward terms, so they cannot extend this paired-input study window.
Only the supplied dev event roots were used for identities and execution.
They contain no R1/R2 international dev event books. This is a limit on
the supplied corpus, not a claim that international markets lack liquidity.

A top-level names-only check of the three supplied event roots and the
two older inventory-listed snapshot roots found 1,231 dev directory
entries and only the twelve built-in city names. No child data files
in those older roots were opened; the structural receipt is archived.

Paired YES/NO buys rest one cent outward from the cumulative-size-adjusted
YES midpoint, snapped outward to tick and checked post-only against raw
prices. Each sample has at most 60 seconds of exposure. The execution
case uses 20 shares, a $19.60 band cap and $15.80 order cap, sits behind
displayed size at the exact price, cancels both legs after the first
partial fill and holds remaining inventory to the actual venue payout.
Decision and cancel-ack lags are assumed one second each, not measured.

Local-DTE cohorts are separate starting-flat counterfactual policies.
The T+0 study is not a continuation of unobserved T+1/T+2 inventory.

This research comparator does not apply the live pilot's separate
existing-depth guard. Live calibration and growth retain the
[pilot runbook](../operations/INTERNATIONAL_MM_LIVE_PILOT.md) guards
and local-DTE rules; this eligibility table grants no live authority.

The f values **0.10 / 0.25 / 0.50** were fixed before bulk computation.
They are low, middle and high adverse-selection stresses, not fitted
fractions. The middle value is near one short-horizon adverse lot among
five pilot lots; that tiny record does not identify population f.
Stress preserves guaranteed categorical payouts instead of making a
hedged YES/NO pair lose its guaranteed redemption.

The [official reward formula](https://docs.polymarket.com/programs/liquidity-rewards)
uses quadratic distance scores, complementary side scores, a midrange
single-side adjustment and normalization over makers and daily samples.
The run uses captured as-of condition size, spread and pool terms.
Aggregate L2 lacks maker identities and constituent order sizes, so the
exact competing denominator is unavailable. The aggregate-book scenario
and displayed-book bounds are retained; the scenario assumes a full
active daily epoch. Missing capture is never extrapolated into exposure.
The upper is the entire maximum captured pool per exposed UTC day;
it is not a prorated partial-day upper or an earned amount.
Reward numbers below are captured-period opportunities per local-DTE
cohort, not full-day earnings or expected paid cash. Cash reward can be
zero; the account/day $1 payment threshold is not applied.

Reward-only opportunity assumes quotes remain unfilled. It cannot
deduct exposure lost after an unknown fill. Expected paid income is
therefore unidentified even where this opportunity is positive.

The 0.10x planning factor stresses the historical selection-time reward
overstatement as competitors responded after posting (EF section 10m).
The 1.0x captured-book case is optimistic. Neither factor estimates the
current response, and 0.10x can penalize competition already in the book.

Weather maker fees are zero. Taker fees are 0.05*p*(1-p) per share and
25% fund maker rebates ([official fees](https://docs.polymarket.com/trading/fees),
EF section 10o). The script reports a fee-funded rebate accrual upper
and credits zero unverified rebate cash. No taker exit is assumed.

## Per-city actual-cap policy

One selected band, local T+0, excluding truncated October 14. R is the
covered reward accrual at 0.10x / 1.0x. Reward, spread, adverse costs, net,
SD and N use the same complete execution sequences; NA means unavailable.
Net and SD columns show the f=0.25 planning / optimistic cases. All f
cases, settled counterfactuals and 1/2/4-band designs are in the archive.

SD combines sample between-date variance with a maximum conditional
inventory variance. It is not a confidence bound on population SD.

NA means unavailable; NP means a nonpositive assumed mean and hence
no finite normal planning N at that point estimate. Neither is a kill.

| City | Covered R $ | Spread $ | AS f=.10/.25/.50 $ | Net $ | SD planning upper $ | N95 | Complete dates |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| atlanta | 0.0012/0.0123 | 0.095 | 0.575/1.437/2.875 | -1.342/-1.331 | 5.744/5.744 | NP/NP | 6 |
| austin | 0.0120/0.1200 | 0.045 | 0.213/0.532/1.065 | -0.475/-0.367 | 3.025/3.030 | NP/NP | 3 |
| chicago | 0.0019/0.0193 | 0.165 | 0.746/1.865/3.729 | -1.698/-1.681 | 8.420/8.420 | NP/NP | 2 |
| dallas | 0.0013/0.0134 | 0.106 | 0.673/1.683/3.366 | -1.576/-1.564 | 6.361/6.363 | NP/NP | 3 |
| denver | 0.0027/0.0266 | 0.139 | 0.367/0.918/1.837 | -0.777/-0.753 | 7.607/7.607 | NP/NP | 2 |
| houston | 0.0018/0.0184 | 0.124 | 0.794/1.985/3.971 | -1.860/-1.843 | 7.414/7.418 | NP/NP | 4 |
| los-angeles | 0.0033/0.0326 | 0.115 | 0.513/1.281/2.563 | -1.164/-1.134 | 6.770/6.772 | NP/NP | 7 |
| miami | 0.0067/0.0665 | 0.184 | 0.869/2.173/4.347 | -1.983/-1.923 | 7.626/7.609 | NP/NP | 2 |
| nyc | 0.0196/0.1960 | 0.041 | 0.154/0.385/0.769 | -0.325/-0.148 | 2.234/2.237 | NP/NP | 2 |
| san-francisco | 0.0030/0.0303 | 0.141 | 0.917/2.291/4.583 | -2.148/-2.120 | 7.654/7.650 | NP/NP | 3 |
| seattle | 0.0069/0.0686 | 0.196 | 0.671/1.676/3.353 | -1.473/-1.411 | 7.719/7.720 | NP/NP | 2 |
| toronto | 0.0001/0.0013 | 0.200 | 1.480/3.700/7.400 | -3.500/-3.499 | NA/NA | NP/NP | 1 |

Actual-venue-settlement counterfactual on the same covered one-band
dates, kept separate from the assumed-f stress. These are simulated
fills and reward accrual, not own-account realized profit. Variance is
between covered dates; a single date cannot estimate it.

| City | Dates | Net 0.10x / 1.0x $ | SD 0.10x / 1.0x $ | Variance 0.10x / 1.0x $ squared |
| --- | ---: | ---: | ---: | ---: |
| atlanta | 6 | -2.853/-2.841 | 6.894/6.892 | 47.530/47.497 |
| austin | 3 | -1.671/-1.563 | 3.182/3.204 | 10.126/10.266 |
| chicago | 2 | -0.833/-0.816 | 10.133/10.132 | 102.671/102.665 |
| dallas | 3 | -2.801/-2.789 | 8.193/8.200 | 67.128/67.234 |
| denver | 2 | -3.532/-3.508 | 2.355/2.357 | 5.547/5.555 |
| houston | 4 | 3.934/3.951 | 2.702/2.691 | 7.302/7.242 |
| los-angeles | 7 | 1.741/1.770 | 4.505/4.481 | 20.297/20.079 |
| miami | 2 | -5.152/-5.092 | 11.646/11.563 | 135.629/133.695 |
| nyc | 2 | -0.392/-0.215 | 1.913/1.718 | 3.658/2.951 |
| san-francisco | 3 | 4.715/4.742 | 3.031/3.059 | 9.187/9.355 |
| seattle | 2 | -1.127/-1.065 | 7.525/7.462 | 56.632/55.683 |
| toronto | 1 | 5.400/5.401 | NA/NA | NA/NA |

Some settlement point means are positive, including Houston, Los Angeles
and San Francisco; their small coverage-selected samples do not identify
whole-policy expected profit or population f. The separate settled
normal N/power values are archived, and are not used to select lucky
settlement outcomes as a G1 verdict.


Captured reward opportunity, same actual-cap one-band selection, over
all selected cohorts including unobserved ones. It assumes unknown
fills did not stop exposure; it is not the covered net sample above.
T+1/T+2 execution/net/power remain unobserved. These exclude the October
14 event. Per-cell date counts are in the derived opportunity CSV.

| City | T+0 R 0.10x / 1.0x $ | T+1 R 0.10x / 1.0x $ | T+2 R 0.10x / 1.0x $ |
| --- | ---: | ---: | ---: |
| atlanta | 0.908/9.080 | 0.276/2.761 | 0.505/5.045 |
| austin | 0.911/9.114 | 0.284/2.840 | 0.658/6.580 |
| chicago | 0.687/6.868 | 0.277/2.770 | 0.499/4.988 |
| dallas | 0.765/7.648 | 0.272/2.723 | 0.409/4.093 |
| denver | 0.997/9.969 | 0.256/2.563 | 0.586/5.861 |
| houston | 1.115/11.150 | 0.301/3.010 | 0.630/6.300 |
| los-angeles | 0.822/8.222 | 0.335/3.349 | 0.219/2.186 |
| miami | 0.660/6.597 | 0.246/2.460 | 0.362/3.619 |
| nyc | 1.788/17.884 | 0.239/2.392 | 0.447/4.474 |
| san-francisco | 0.447/4.474 | 0.206/2.058 | 0.348/3.477 |
| seattle | 1.006/10.064 | 0.244/2.436 | 0.515/5.149 |
| toronto | 0.622/6.225 | 0.219/2.185 | 0.381/3.813 |

## Size eligibility and backing

Eligibility below is the fraction of captured band samples satisfying
all policy checks, not just the reward minimum. The minimum-100 column
is counted before price/capital checks. Unconstrained larger sizes are
comparators and cannot be substituted into the actual-cap policy.

Opportunity is per observed band/local-DTE day, before unknown fills,
and is distinct from the covered selected-band accrual above.

| Local DTE | Shares/side | Actual caps | Eligible % | Minimum >=100 % | Eligible mean backing $ | R opportunity 0.10x / 1.0x $ |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 0 | 20 | False | 27.16 | 70.09 | 19.52 | 0.728/7.283 |
| 0 | 50 | False | 27.16 | 70.09 | 48.79 | 0.811/8.114 |
| 0 | 100 | False | 86.05 | 70.09 | 97.55 | 1.851/18.510 |
| 0 | 20 | True | 15.77 | 70.09 | 19.51 | 0.533/5.333 |
| 1 | 20 | False | 99.27 | 0.00 | 19.50 | 0.182/1.820 |
| 1 | 50 | False | 99.27 | 0.00 | 48.75 | 0.359/3.592 |
| 1 | 100 | False | 99.27 | 0.00 | 97.49 | 0.566/5.662 |
| 1 | 20 | True | 64.65 | 0.00 | 19.49 | 0.148/1.479 |
| 2 | 20 | False | 89.72 | 0.00 | 19.50 | 0.223/2.230 |
| 2 | 50 | False | 89.72 | 0.00 | 48.75 | 0.283/2.827 |
| 2 | 100 | False | 89.72 | 0.00 | 97.49 | 0.350/3.498 |
| 2 | 20 | True | 53.37 | 0.00 | 19.49 | 0.163/1.633 |

At .49/.49 paired prices, 20/50/100 shares require $19.60/$49/$98.
Twenty and fifty fail a 100-share minimum; 100 meets it subject to
book/post-only checks but violates the current band cap. Next-day
eligibility must use the captured terms. Every quote also needs its
individual order to fit $15.80. All size/city/DTE opportunity outputs
including zero-eligibility periods are retained in derived CSV files.

$300 backs at most fifteen $19.60 bands before inventory. One, two and
four bands cost $19.60/$39.20/$78.40 per event; three overlapping cohorts
reserve $58.80/$117.60/$235.20, allowing at most five/two/one such city
schedules. All twelve cities at once with one cohort cost $235.20
(one band), $470.40 (two) or $940.80 (four). Pooled statistics are a
population description, not an executable all-city portfolio. The run
does not simulate the full bankroll path or reuse cash across markets.

## Coverage, truncation and power

Complete observed band cohorts: **175 / 2,134**.
Of these, 163 ended with a fill; median live exposure was
125.56 seconds (mean 216.59).
Each live quote must lie after local midnight and the first recorded
print, be bracketed by prints, and cross no print gap above 300 seconds.
A print-gap proxy cannot distinguish an outage from a quiet market.
Any unknown live interval invalidates the entire cohort; the simulation
never resumes from an assumed zero inventory. T+1/T+2 are reward-only.

| DTE | coverage_reasons key | Quote windows |
| ---: | --- | ---: |
| 0 | before_first_record_or_local_midnight | 311 |
| 0 | covered | 1,361 |
| 0 | internal_gap_or_after_last_record | 220 |
| 0 | prior_execution_unobserved | 86,954 |
| 1 | future_day_reward_only | 667 |
| 1 | prior_execution_unobserved | 702,394 |
| 2 | future_day_reward_only | 761 |
| 2 | prior_execution_unobserved | 527,048 |

The archive records coverage by city and event, including first/last
prints and internal gaps. Counts named prior_execution_unobserved are
subsequent windows after the first uncertainty, not separate outages.
The October 14 event loses its local evening because input UTC days
stop at the October 14-to-15 UTC boundary. The sensitivity retains and removes that
date for every city, 1/2/4 bands, both multipliers and all f values.

| Bands/event | Pooled complete dates incl. 10-14 | Excl. 10-14 |
| ---: | ---: | ---: |
| 1 | 0 | 0 |
| 2 | 0 | 0 |
| 4 | 0 | 0 |

At 0.10x planning all observed design/f means are nonpositive, with
and without October 14. The only short nominal lead is NYC two bands
at 1.0x, based on just 2 covered dates: 2026-09-26, 2026-10-05.
It reserves $117.60 for three cohorts. These estimates are conditional
on coverage selection and assumed reward/f values; the accuracy gate,
small-sample uncertainty, serial dependence, looks and Holm are absent.

| f | Mean 0.10x $ | Mean 1.0x $ | SD upper 1.0x $ | N95 1.0x | N80 1.0x | Power at 74, 1.0x |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.10 | -0.00793 | 1.27127 | 3.89538 | 26 | 59 | 0.8775 |
| 0.25 | -0.34445 | 0.93475 | 3.82388 | 46 | 104 | 0.6765 |
| 0.50 | -0.90531 | 0.37389 | 3.71599 | 268 | 611 | 0.2179 |

N95 is the point-estimate crossing criterion requested by the task;
N80 is a different planning criterion, not an extra charter gate.
Only the optimistic low-f case has nominal N80 below the calendar
ceiling. At f=.25 N95=46 fits nominally, while N80=104 exceeds 74.
Two selected dates do not support a reliable whole-policy power claim.
Other positive 1.0x f-stress cases require N95=1,990 (NYC one band, f=.10) or
116,954 (Austin two bands, f=.10). No four-band design has a complete
selected date. Removing October 14 changes Toronto one band from two
covered dates to one and two bands from one to zero; other covered
per-city samples and the NYC nominal lead are unchanged.


N95, N80 and power at 74 dates are unidentified wherever the date effect
and variance are missing, at both reward multipliers and every f. The
conditional normal formulas are ceil((1.644854*SD/mean)^2) for the
point lower bound to cross zero, and ceil(((1.644854+.841621)*SD/mean)^2)
for 80% probability of crossing. The implementation floors N at twenty.
Variance aggregates bands within event date, keeps categorical inventory
risk, and pools cities only on common complete dates. It cannot divide
variance by the number of bands or count cities as independent dates.

October 15 through December 27 offers at most **74 calendar clusters**:
23 through November 6 including that partial date, and 51 strictly
future. For twelve cities this is at most 888 calendar city-event
opportunities (276 through November 6 and 612 future), before evidence
or capital limits. Those opportunities cannot multiply date-cluster N.
Later-date economics remain unread. Actual countability,
settlement, serial correlation, small samples, sequential looks and
Holm can reduce usable dates or increase required N. The old four-date
706-date result in EF section 10r remains scoped to its old design;
it is not a replacement estimate for this study.

## Growth recommendation

There is no supported ranking of cities or bands by power per dollar.
Retain the owner-planned Toronto/Denver pilot for calibration first,
using eligible 20-share next-day bands. Establish paid reward, queue,
cancel latency and settlement-markout agreement before capital growth.
NYC two bands is the next research/calibration hypothesis because it is
the only nominal optimistic mid-f lead. It is not a capital-growth
recommendation from this two-date, coverage-selected sample. Compare
one-band city schedules before adding a second or fourth
band: the latter consume capital and share date shocks. Reward-only
opportunity ranking is archived for selecting calibration candidates,
but is not a power or net-profit ranking. R1/R2 expansion needs admitted
dev books, captured reward terms and matching execution first.

## DISCLOSURES

- B012(a): reward fields pass float conversion before boolean rejection;
  the NO-book tick size is not checked. The reviewed pin is unchanged.
- B012(b): a missing reward term or complement can leave the previous
  quote live for up to 60 seconds beyond an unobserved book.
- B012(c): 27 mixed selected designs are affected by the
  known reward-only understatement. The derived opportunity audit adds
  both parts for disclosure only; it never creates a net observation.
  Maximum omitted 1.0x opportunity per event/design: $0.364698.
- B012(d): October 14 dt=0 is truncated; both sensitivities are archived.
- B012(e): a >300-second print gap can exclude a quiet but operating
  market. No covered sample means not identifiable, not no edge.
- Exposure is conditional on the recorder's reward-ranked top-ten band
  selection. Owner manual orders from September 29 through October 14
  remain in displayed competition. Our competition response is unknown.
- Economic-identity deduplication can collapse distinct identical fills;
  lower volume is not conservative for net P&L. Queue changes and
  post-only acceptance after the assumed lag are not observed.
- Selection uses a first-minute candidate window; live selection timing
  needs validation. Coverage admission can retain early fills while
  excluding longer quiet cohorts. This outcome-dependent selection
  prevents interpreting covered-sample profits as all-policy profits.
  Normal N values are conditional planning rather than a trial.
- Exact paid rewards, account payment thresholds, calibrated own latency,
  full bankroll constraints and the accuracy gate remain unresolved.

- Ten missing provided settlements (Denver/Toronto September 25-29)
  were fetched from the existing free official venue projection source
  and strictly validated; the original inputs and failed-run log remain.
- The controller used the canonical three-slot workstation allowance
  after initial one-slot refusals. The agent's review proposal had listed
  one slot; the authority re-check and setting changes are receipted.
  T002 chunks stayed serial; hold, memory and commit gates were retained.

## B010 re-check and verification

Before bulk execution, the re-check fixed unknown-inventory resets,
retained ineligible cancellation controls, ordered same-hour segments
by manifest seal time, deduplicated minutes, rejected malformed clocks
and mapped economics, and tightened source/output/settlement receipts.
Both reward multipliers now apply to every f and settled calculation.
The reviewed source passed 95 small synthetic checks and a bounded
captured book/reward/venue-winner trace. These are not pilot calibration.
Final generated-output consistency checks passed 22,141 assertions.
The documentation audit and exact final archive hashes are recorded in
the handback receipts. The B012 pin was not changed for its low items.

The light-report memory probe was corrected to measure the actual
interpreter: the initial external probe saw only the virtualenv launcher.
Both scopes are labelled in the archived memory receipts.

## Reproduction and OPEN QUESTIONS

Archive: `C:/t/codex/T002/out/`; raw computation output and receipts are
in `stream-v3-attempt1/`, generated reporting in `derived/`, and launcher
records in `run_logs/`. `SHA256SUMS` covers scripts and outputs. The
archive README identifies the approved source and reviewed allowlist;
earlier unexecuted/forbidden versions remain historical evidence.

The master must decide whether to admit a dev-only cut of the mixed
88a execution journals plus recorder-uptime evidence. The current
per-event tapes cannot identify pre-event fills. Any new input family
and simulator revision needs separate review before running. The T1
preregistration still needs calibrated latency/reward/fill tolerances,
a conservative f, capital path, countability, multiplicity and look rules.
No change to the master-owned STATE_OF_PLAY or DECISION_LOG was made.
Proposed state: G1 feasibility unresolved for lack of identifiable net
effect and variance; this study supplies neither a T1 PASS nor a kill.

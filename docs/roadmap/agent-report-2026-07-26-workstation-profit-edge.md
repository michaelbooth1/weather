# Agent report - 2026-07-26 profit-relevant edge queue

Status: **MISSION 1 COMPLETE - NO HISTORICALLY ESTABLISHED EXPLOITABLE SLICE;
MISSION 2 COMPLETE - BUG WITH A CURRENT-MAX AUTHORITY GAP;
MISSION 3 PREREGISTERED ONLY / NOT FIT**.

This report closes the ordered queue in
`docs/roadmap/workstation-handoff-2026-07-26-profit-relevant-edge.md`
(SHA-256
`534b9da552f3f9ba60a1a4f87c53221755ad86539ad011a5ace9650ff87fb75e`).

## Executive verdict

**No preregistered slice passes the historical exploitability screen.**

| Mission / question | Verdict | Basis |
| :--- | :--- | :--- |
| Where is the model-versus-market gap? | Disproportionately concentrated near resolution | Near-resolved partitions have the largest Brier gap (`0.0481532590`), despite being only 29.42% of the population, and are 97.42% of evening opportunities. |
| Is any measured disagreement historically established as exploitable? | **NO** | Every uncertainty, hour, and fixed-rule slice fails the frozen support/inference screen. The all-hours point estimate is positive, but both lower bounds are negative and only 49.61% of market-days are positive. |
| What is the evening result? | **LOSS-AVOIDANCE LIABILITY** | A naive taker loses `0.468218` over 735 one-share opportunities. Separately, near-resolved rows explain 99.96% of signed evening excess Brier loss. |
| Why is hour 20 wrong? | **BUG WITH A CURRENT-MAX AUTHORITY GAP** | The observed trajectory is present. The incumbent blend runs after the printed-high floor and restores impossible mass; separately, the 38 above-floor settlements expose an unresolved authority/freshness information hypothesis. |
| What model work was done? | **NONE** | Mission 3 freezes `authoritative_wu_print_freshness_v0.1` and an untouched future window. It does not implement, fit, tune, or evaluate it. |
| Does this authorize deployment or trading? | **NO** | Prices are diagnostic proxies, no execution was measured, and no production or trading action was taken. |

## Final identities and containment

| Purpose | Identity |
| :--- | :--- |
| Integration base and refreshed `origin/master` | `890c8195511402656b66b487d2c8f5bb4207693e` |
| Topic branch | `codex/workstation-profit-edge-2026-07-26` |
| Mission 1 implementation commits | `08a36c13`, `7eecce60`, `ced7308e` |
| Authoritative Mission 1 code identity | `ced7308e1f233fc69fe86b8dfce34b328a52e2fd` |
| Mission 3 preregistration commit | `ad3218b42114994ff48d5582d35d7766498834f3` |
| Inherited accepted skill-gap commits | `7b59d28e`, `7ac5e536`, `a84bd887`, `1623c76f`, `ba2c299a`, `b08b14fb`, `c7aba44b` |
| Repaired candidate variant | `simplex-remeasurement-repaired-803b3de6` |
| `candidate-variant-rows.csv` | 156,464,494 bytes; SHA-256 `cf661e9fb396e95db4e98f2aa29fd32dda2fb9b992099e4d0d6fcfea89b68a4b` |
| Frozen corpus manifest | 5,444,181 bytes; SHA-256 `128db63ec78c92a4126f886caec078dcab6786b47d0d65ad0aff10f5f1dc1dc5` |
| Pooled v0.3 artifact | 6,310,781 bytes; SHA-256 `3b472bd32667256c6605a6f48c2c9c4ba7e58f140a89c504c4b4fbfcac6a497c` |
| Declared output root | `C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\profit-edge-20260726` |
| Protected data root | `C:\Users\Michael\Documents\github\weather\data` |

The topic branch contains the refreshed integration base. The seven inherited
commits are the accepted, closed skill-gap queue; they remain visible because
this topic is stacked on that accepted topic history.

The protected main data mirror remained OS-denied/read-only. A fresh, exact-path
canary returned `System.UnauthorizedAccessException`; it was absent before and
after the attempt. The containment receipt has SHA-256
`727de3e188f897c2b0f4f9170133e4e70dcee0323d71e2c7d43f76e3c1517aa2`.
The analytical harnesses report unchanged primary and feature-input hashes and
zero analytical protected-data write attempts. Test temporary directories,
bytecode caches, and retained evidence were directed below the declared output
root.

The declared research ceilings were 4,096 MiB private memory and 2,560 MiB
working set. They are policy values, not a new Windows Job/process-tree
resource proof: this queue retained no observed-peak or Job-lifetime receipt,
so resource enforcement is not claimed here.

## Mission 1 - where money is, and where the model is merely wrong

Mission 1 is a retrospective measurement over already-settled history. It is
not a strategy backtest, expected-return forecast, or authorization to trade.
It fit or tuned nothing and consumed no opened-window outcomes.

### Evidence identity

| Evidence | Bytes | SHA-256 |
| :--- | ---: | :--- |
| Frozen predeclaration | 5,818 | `ff13b66dd003e8468d197b3963a0ec398426d336a6cb84d73a62dc8f4a775c11` |
| Authoritative JSON | 488,734 | `ef3168244aca4b2f170e750e234588542cba90980c59b32bf301bcfb41cfeb85` |
| Authoritative Markdown | 15,232 | `df3d8507a10d6c4a1bc9eb3724bde66107df428cb92a2eb5793fa0613e11fe19` |
| Trade-slice CSV | 51,255 | `2f5b51be166dfcdcf968696a7ad7180d91c90ae3c10b310ad147301d20cf2b73` |
| Independent validator | 7,321 | `025095361d90e752cad3afd30ad7c1cff7288e1a2de366319605e6db11f92b53` |
| Independent PASS receipt | 2,280 | `99d9ea68d849dc2cc32f0562e146facc2e41701c4e015e06949bdf763b39ce2e` |

The independent validator passed 21 of 21 checks without importing the
analyzer.

### Population and frozen method

- 206,745 band rows form 18,793 complete partitions.
- 18,791 partitions are on the target-local day; two are non-target-day.
- Earliest market-local hourly selection yields 2,962 target-day
  opportunities across 11 F markets, 129 market-days, and 12 target dates.
- Two verified same-second collision partitions remain in Brier measurement
  but are excluded from trading. Maximum candidate mass residual is
  `6.66e-16`.
- Brier uses raw Gamma `market_yes`; only uncertainty classification normalizes
  market prices. Mean raw market mass is `1.013195658`, and 79.8436% of
  partitions fall within 0.05 of unit mass.
- Each market/date/local-hour contributes its earliest partition. The rule
  evaluates every non-extreme YES and complementary NO, subtracts the fee from
  predicted edge, and selects at most one strictly positive predicted-net edge,
  largest first with a band-key tie break.
- YES uses the recorded price. NO is synthesized as `1 - market_yes`. Taker
  fee is `0.05 * p * (1 - p)`. The favorable maker sensitivity is gross P&L
  plus 25% of that fee; it is not a realized rebate.
- Inference is equal-market-day, with a 10,000-repetition target-date-block
  bootstrap and leave-one-date-out sensitivity.
- A slice passes only with at least 100 trades, at least 30 market-days,
  positive mean P&L, positive normal lower bound, and more than 50% positive
  market-days.

### Uncertainty-stratified Brier

| Market uncertainty | Partitions | Weight | Entropy | 1 - top | Raw mass | Model Brier | Market Brier | Gap |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Near resolved, top >= 0.95 | 5,529 | 29.4205% | `0.0272` | `0.0091` | `1.0045` | `0.0483919055` | `0.0002386465` | `0.0481532590` |
| Low, top 0.80-0.95 | 921 | 4.9008% | `0.1598` | `0.1008` | `1.0000` | `0.0262137664` | `0.0113049866` | `0.0149087798` |
| Moderate, top 0.60-0.80 | 2,429 | 12.9250% | `0.3937` | `0.3370` | `1.0066` | `0.0588358684` | `0.0428901826` | `0.0159456858` |
| High, top < 0.60 | 9,914 | 52.7537% | `0.5328` | `0.5323` | `1.0209` | `0.0737954834` | `0.0591458956` | `0.0146495878` |
| **Overall** | **18,793** | **100%** | - | - | **`1.0132`** | **`0.0620561138`** | **`0.0373686308`** | **`0.0246874830`** |

The error ranking and money ranking are different. The widest gap is in
near-resolved markets, where closing the model gap primarily prevents bad
signals rather than uncovering a trade. Near-resolved partitions are 29.42% of
the population but contribute 57.39% of total signed excess squared loss.

The locked `top >= 0.99` sensitivity contains 4,426 partitions (23.55%) and
widens to model Brier `0.049971663` versus market Brier `0.000000803`. Restricting
to the 15,005 partitions whose raw market mass lies within 0.05 of one still
gives model Brier `0.060064298`, market Brier `0.033075423`, and gap
`0.026988875`. The conclusion is not an artifact of the least simplex-like
market rows.

### P&L ranking by uncertainty

Totals are dollars over one-share positions. Means are cents per traded share;
confidence bounds are dollars per share.

| Bucket | Trades / days | Total net | Mean cents | Normal low | Date low | Positive days | Maker sensitivity | Pass |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| Moderate | 372 / 104 | `+10.998169` | `+2.956497` | `-0.031652` | `-0.041826` | 38.46% | `+15.303583` | No |
| High | 1,536 / 126 | `+2.003150` | `+0.130413` | `-0.062746` | `-0.065561` | 46.83% | `+19.574212` | No |
| Low | 175 / 108 | `-0.026335` | `-0.015049` | `-0.052107` | `-0.054022` | 12.96% | `+0.672209` | No |
| Near resolved | 879 / 129 | `-4.031129` | `-0.458604` | `-0.005057` | `-0.005047` | 1.55% | `-3.788468` | No |

Across all 2,962 target-day hours, total taker net is `+8.943855` and
the ordinary per-trade mean is `+0.301953` cents. That point estimate is not
evidence of edge: the equal-market-day normal lower bound is `-0.030205`, the
target-date-block lower bound is `-0.034282`, and only 49.61% of market-days
are positive. All 24 hour slices fail:

| Hour | Trades | Total net | Mean cents | Normal low | Date low | Positive days | Maker sensitivity | Pass |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 00 | 118 | `+0.075012` | `+0.063569` | `-0.074124` | `-0.050879` | 45.76% | `+1.418747` | No |
| 01 | 118 | `+6.523538` | `+5.528422` | `-0.017585` | `-0.002220` | 50.85% | `+7.919116` | No |
| 02 | 118 | `+2.389195` | `+2.024741` | `-0.053578` | `-0.077939` | 46.61% | `+3.775201` | No |
| 03 | 118 | `-3.625528` | `-3.072481` | `-0.106277` | `-0.132007` | 39.83% | `-2.307368` | No |
| 04 | 118 | `-1.632807` | `-1.383735` | `-0.091048` | `-0.123490` | 39.83% | `-0.301173` | No |
| 05 | 118 | `-2.926291` | `-2.479908` | `-0.105571` | `-0.137367` | 37.29% | `-1.601552` | No |
| 06 | 118 | `+3.000268` | `+2.542600` | `-0.051927` | `-0.071228` | 41.53% | `+4.313058` | No |
| 07 | 121 | `+0.772092` | `+0.638092` | `-0.068963` | `-0.075103` | 38.84% | `+2.089477` | No |
| 08 | 122 | `-2.259628` | `-1.852154` | `-0.095715` | `-0.100075` | 40.98% | `-0.785718` | No |
| 09 | 126 | `+6.064465` | `+4.813068` | `-0.029019` | `-0.035482` | 47.62% | `+7.623259` | No |
| 10 | 129 | `+0.575370` | `+0.446023` | `-0.070375` | `-0.059316` | 41.09% | `+2.129283` | No |
| 11 | 129 | `+3.452557` | `+2.676401` | `-0.048310` | `-0.026901` | 42.64% | `+5.028111` | No |
| 12 | 129 | `-1.502571` | `-1.164784` | `-0.088094` | `-0.107953` | 35.66% | `-0.001857` | No |
| 13 | 129 | `-4.771795` | `-3.699066` | `-0.099329` | `-0.091483` | 26.36% | `-3.516426` | No |
| 14 | 129 | `+0.562770` | `+0.436255` | `-0.059699` | `-0.086575` | 27.13% | `+1.696183` | No |
| 15 | 129 | `-0.822413` | `-0.637529` | `-0.065064` | `-0.054220` | 22.48% | `+0.103103` | No |
| 16 | 129 | `+1.071191` | `+0.830381` | `-0.036930` | `-0.031441` | 16.28% | `+1.633452` | No |
| 17 | 129 | `+2.466648` | `+1.912130` | `-0.012538` | `-0.004563` | 12.40% | `+2.821463` | No |
| 18 | 128 | `+0.264482` | `+0.206626` | `-0.010906` | `-0.009254` | 3.91% | `+0.387630` | No |
| 19 | 126 | `-0.228759` | `-0.181554` | `-0.006027` | `-0.004803` | 0.79% | `-0.188435` | No |
| 20 | 124 | `-0.204191` | `-0.164670` | `-0.001970` | `-0.002063` | 0.00% | `-0.192077` | No |
| 21 | 121 | `-0.122313` | `-0.101085` | `-0.001210` | `-0.001193` | 0.00% | `-0.115047` | No |
| 22 | 118 | `-0.088194` | `-0.074741` | `-0.000885` | `-0.000911` | 0.00% | `-0.082952` | No |
| 23 | 118 | `-0.089244` | `-0.075630` | `-0.000892` | `-0.000930` | 0.00% | `-0.083939` | No |

The visually strongest supported hours still have negative lower bounds. The
only positive-bound cell in the exhaustive hour-by-uncertainty cross-ranking
is hour 17 / moderate, with five trades on five days; it fails the support rule
by a wide margin. The complete cross-ranking is retained in
`mission1/profit_edge_analysis.json` under `profit_ranking` and in
`mission1/profit_edge_trade_slices.csv`, with the identities listed above.

### Evening liability

For the 18:00-23:00 hourly opportunities:

- 735 trades over 129 market-days and 12 dates;
- gross `-0.313500`, taker fees `0.154718`, and net `-0.468218`;
- mean `-0.063703` cents per share;
- 729 of 735 trades are negative (99.1837%);
- only 4.6512% of market-days are positive;
- normal and date-block lower bounds are `-0.003054` and `-0.002653`;
- favorable maker sensitivity is still negative at `-0.274820`;
- side mix is 8 YES and 727 synthetic NO.

| Hour | Trades | Net |
| ---: | ---: | ---: |
| 18 | 128 | `+0.264482` |
| 19 | 126 | `-0.228759` |
| 20 | 124 | `-0.204191` |
| 21 | 121 | `-0.122313` |
| 22 | 118 | `-0.088194` |
| 23 | 118 | `-0.089244` |

| Evening uncertainty | Trades | Net |
| :--- | ---: | ---: |
| Near resolved | 716 | `-1.580574` |
| Low | 16 | `-0.231299` |
| Moderate | 1 | `+0.253308` |
| High | 2 | `+1.090346` |

Near-resolved partitions are 97.4150% of evening opportunities and 99.9634% of
signed evening excess Brier loss. Their taker P&L is `-1.580574`; the less
certain buckets partly offset that loss, yielding the `-0.468218` overall
total. The three positive uncertain-bucket trades are far too sparse to
establish edge.

Counting only the first evening trade per market-day gives 129 trades, net
`+0.241406`, and mean `+0.187137` cents. It is also not evidence: 124 of 129
trades are negative, only 3.876% of days are positive, and the normal and
date-block lower bounds are `-0.011006` and `-0.009690`.

### Fixed-rule sensitivities

Tau is a predicted-net-edge threshold in dollars per share. Means below are
taker net dollars per traded share.

| Rule | All trades | All $/share | Mean net $/$ notional | Evening trades | Evening $/share | First/day trades | First/day $/share | Pass |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| Symmetric tau 0.00 | 2,962 | `+0.003020` | `-0.412671` | 735 | `-0.000637` | 129 | `+0.001871` | No |
| Symmetric tau 0.03 | 2,939 | `+0.003500` | `-0.411539` | 732 | `-0.000632` | 129 | `+0.001572` | No |
| Symmetric tau 0.05 | 2,905 | `+0.004491` | `-0.409469` | 724 | `-0.000594` | 129 | `+0.001674` | No |
| Symmetric tau 0.08 | 2,788 | `+0.003582` | `-0.421637` | 692 | `-0.000420` | 128 | `+0.004360` | No |
| Symmetric tau 0.10 | 2,680 | `+0.002512` | `-0.421296` | 660 | `-0.000207` | 128 | `+0.005195` | No |
| YES-only tau 0.00 | 2,961 | `-0.003235` | `-0.568157` | 734 | `-0.000087` | 129 | `+0.004205` | No |

No threshold rescues evening P&L. Mean per-dollar-notional taker return is
negative under every sensitivity. The all-hours and first/day per-share point
estimates remain unsupported under the frozen inference rule.

### Execution boundary

`market_yes` is Gamma `outcomePrices`, not an executable CLOB ask. NO prices
are synthetic complements. The evidence contains no spread, depth, slippage,
latency, fill, capacity, queue position, maker eligibility, or actual rebate
measurement. The favorable maker column is a sensitivity, not maker economics.
Therefore the correct exploitable-subset answer is **none established**.

## Mission 2 - hour-20 causal diagnosis

Mission 2 reconstructed exact features from captured `replay_inputs` using the
production feature builder. It did not use the misleading worktree-local raw
feature view as the causal trace. It fit, tuned, and changed nothing.

### Evidence identity and validation

| Evidence | Bytes | SHA-256 |
| :--- | ---: | :--- |
| Diagnosis harness | 43,313 | `5aef8a2672ea6f37a7fba444321367aa170ce0065b8694d2897b6fedf3005f16` |
| Diagnosis JSON | 127,164 | `62d62a6df7dada26d228c4a470c0e2b508d2197fc8289eedbc149fd4cd4de45a` |
| Diagnosis Markdown | 2,985 | `16625a978c707508d2e2a694a8773d19b6ebe79d34261ed49c734747785f3229` |
| Case CSV | 64,306 | `62098846077d58c89caf500488d9d24e6db207905804fe0584377bdf94de98c8` |
| Independent validator | 11,896 | `074794eb86145e254cdd714ab6132eb038efdf11055e4d046358908a4e36211d` |
| Independent PASS receipt | 7,548 | `b3c06aa2cdf7b2bf76e8fb00c2a12b926c390a7ec1ea63c5302b347048c3207c` |

The frozen cut has 124 earliest target-market-local hour-20 partitions, 1,364
band rows, 11 markets, and 12 dates. The feature context contains 141 files,
31,619,087 bytes, with identity-set SHA-256
`0a022384b72e14b8607ed5967fe704afa0328bcf7768b7371e901587e527aaca`.
All 18,793 snapshots reconstructed without a feature error, and the final
candidate/incumbent blend plus normalization reproduces every frozen final
probability exactly.

The independent validator passed 27 of 27 checks without importing the
diagnosis harness. It independently reconciles the case CSV and materialized
JSON, the blend and floor arithmetic, and executable source ordering. It does
not independently re-derive the 124 representatives from raw inputs or
recompute recorded-live scores; those are explicit evidence limits.

### Stage trace

Row Brier matches the Mission 1 per-band convention. Categorical Brier sums
band losses within a partition, then weights market-days equally.

| Stage | Row Brier | Categorical Brier | Mean winner probability | Top-band accuracy |
| :--- | ---: | ---: | ---: | ---: |
| Final candidate | `0.0481810450` | `0.5299914950` | `0.541190` | 69.35% |
| Candidate before incumbent blend | `0.0557472985` | `0.6132202830` | `0.684233` | 69.35% |
| Incumbent replay | `0.0642695441` | `0.7069649854` | `0.392608` | 52.42% |
| Recorded live | `0.0659177088` | `0.7250947965` | `0.408305` | 52.42% |
| Raw market YES | `0.0000011080` | `0.0000121875` | `0.998431` | 100.00% |

### What exists and what the artifact consumes

- `high_so_far`, `current_temp`, and `live_reading_temp` are populated in all
  124 selected partitions. The current-high trajectory is **not omitted**.
- The hour-20 artifact has 278 features and includes current/high/live
  temperature, current maximum dispositions, hours at peak, warming rate, and
  lock-in strength. It does not include the exact latest accepted WU history
  time or minute.
- No current maximum is trusted: 69 are support-only, 15 quarantined, and 40
  missing. None of the support-only or quarantined values exceeds the printed
  high in this cut. There is therefore no evidence that a larger eligible
  trusted maximum was ignored.
- All source-health groups report failures. In 114 of 124 partitions the state
  is failed `weather_forecast`, `wu_current`, and `wu_history`.

The printed floor identifies the eventual winning band in 86 of 124
partitions. On those aligned days, preblend categorical Brier is
`0.000499319`, mean winner probability is `0.986569`, and mean lock-in strength
is `0.959070`.

In the other 38 partitions, the settlement band remains 1-11 degrees above the
printed floor (median 5, mean 5.4211), and every one reports failed weather
forecast/WU current/WU history. Preblend categorical Brier is nearly maximal
at `1.999904571`, mean winning-band probability is `2.06e-7`, and lock-in
strength is zero. This association motivates the authority/freshness
hypothesis; it does not by itself prove that source failure caused the misses,
because many aligned partitions carry the same failed-source label.

### Concrete bug trace

The executable order is:

1. candidate postprocessing applies the printed-high hard floor;
2. the preblend vector is captured;
3. the incumbent is blended using context-specific alpha;
4. final simplex normalization/cleanup runs;
5. the physical floor is not reapplied.

Alpha is below one on 1,327 of 1,364 rows (97.2874%); median alpha is 0.50.
Preblend has zero partitions with impossible mass above `1e-9`. Incumbent
replay has 118; final output has 108 of 124. Final impossible mass averages
10.0843%, has median 4.8515%, and reaches 49.5856%.

The impossible bands contribute `0.001421936` row Brier, 2.9512% of final
hour-20 squared loss. The bug is real, but it is not the whole gap. The blend
improves aggregate hour-20 Brier relative to preblend by partly rescuing the 38
above-floor-settlement cases, while damaging aligned cases and violating a
physical invariant.

Dallas on 2026-07-07 is the largest invariant violation: the printed floor and
winner are both 100-101 F, preblend winner probability is `0.999999927`,
incumbent probability is `0.003513626`, and final probability is `0.501756776`.
The blend restores `0.495855773` below the observed floor.

### Diagnosis

**BUG WITH A CURRENT-MAX AUTHORITY GAP.**

The bug is postprocessing order: incumbent blending restores probability to
bands already made physically impossible by the printed high. The separate
observed information gap is the absence of exact authoritative print
freshness: the model receives a numeric trajectory in every selected case but
does not receive the age/state features needed to test whether a recent
successful authoritative print should be treated differently from failed,
stale, or missing authority. That causal claim remains a preregistered
hypothesis.

This is not a global-calibration result, not pure-climatology domination, and
not evidence that current-high inputs are absent. It is a loss-avoidance
diagnosis. No fix was implemented.

## Mission 3 - frozen before model work

Mission 3 is complete as a preregistration only:
`docs/roadmap/profit-edge-information-preregistration-2026-07-26.md`,
commit `ad3218b4`, SHA-256
`83517f2ded3933d4329dbcccb25a1e030c6971291225b14186e2120f2b5a437b`.

Candidate `authoritative_wu_print_freshness_v0.1` adds only point-in-time
authority/freshness signals:

- age of the latest accepted WU history print;
- age since the captured successful WU-history acquisition;
- captured authority state (`fresh`, `stale`, `failed`, or `missing`);
- explicit missingness for each numeric age.

The hypothesis is that hour-20 lock-in should depend on whether the
authoritative printed trajectory is fresh, not only its numeric high. Values
must exist at or before capture; future WU rows, settlement summaries, outcomes,
market prices, and mutable current queries are prohibited.

The untouched confirmation panel is the first 14 complete eligible target
dates beginning `2026-07-27`; its ordered dates and all identities must be
sealed before an outcome score is opened. Success requires simplex/floor
correctness, at least `0.003` absolute hour-20 categorical-Brier improvement
with a paired date-block upper bound below zero, at least `0.03` winning-band
mass improvement, no hour-20 log-loss regression, 09:00-14:00 guardrails, and
a leakage audit.

The post-blend floor bug must be repaired identically in both comparator arms
and reported separately; its gain cannot be credited to this candidate. No
feature implementation, fitting, tuning, or confirmation-window outcome
inspection occurred.

## Protocol incidents and evidence limits

- The `08a36c13` generation is preserved under
  `mission1-invalidated-08a36c13`. It ranked P&L incorrectly and labelled
  ordinary row resampling as date-block bootstrap/leave-one-date-out.
- The `7eecce60` generation is preserved under
  `mission1-invalidated-7eecce60`. Its evidence contract omitted or ambiguously
  named required totals, cents, and attribution fields.
- The first independent Mission 1 validator receipt failed only because an
  absolute tolerance rejected floating summation-order differences
  (`8.82e-10` model and `-4.974e-9` market on totals near 7,725). It is
  preserved with SHA-256
  `2a5a57bc7cd4def47dcdcf87ec9fa9c2e2cdd849c453ba65d5abd8a274716482`.
  The final independent validator uses `rel_tol=1e-12, abs_tol=1e-10` and
  passes.
- A worktree-local/raw feature view initially suggested missing hour-20
  trajectory. That module-audit path was invalidated: exact captured-input
  replay proves high/current/live inputs in all 124 partitions. It is not used
  as Mission 2 evidence.
- Both independent validators validate materialized evidence contracts. They
  do not turn retrospective proxy prices into executable returns or establish
  future generalization.

## Final validation

| Check | Result |
| :--- | :--- |
| Focused profit analyzer plus architecture/module-size ratchets | **PASS** - 35 passed in 4.66 seconds |
| Independent Mission 1 validator | **PASS** - 21/21 checks, no analyzer import |
| Independent Mission 2 validator | **PASS** - 27/27 checks, no diagnosis-harness import |
| Full pytest | **PASS** - 3,157 passed, 3 skipped, 13 warnings, 812 subtests in 268.72 seconds |
| `compileall -q app src tests` | **PASS** |
| Agent documentation audit | **PASS** - 18 agent files, 475 Markdown files |
| `git diff --check` | **PASS** |

The full run used process-local PowerShell `Bypass`; it did not change host
execution policy. All temporary and bytecode paths still resolve below the
declared output root. The final validation receipt is 2,718 bytes with SHA-256
`84544a9d52acd9fad47d1e2302a7b17de15c9e44b0b3351a1417335cedf5ec02`.
A retained validation-only pytest adapter, 4,670 bytes with SHA-256
`1d5e7fe50070b03f71531fdc274055b6567874c1d7ad595ff230de474f8565d7`,
preserved the `Q:` spelling of a temporary SUBST alias after first performing
normalized, fail-closed reparse checks; it also injected the same rule into
generated experiment child guards. The complete 68-test Windows
PowerShell/Job/sandbox group passed before the final full run, including the
escape and mutation attack cases.

This adapter was necessary because a direct deep `--basetemp` produced
Windows `MAX_PATH` fixture failures and an extended-length `\\?\` root was
rejected by native Job/subprocess paths. Those runs were environment
diagnostics, not code-test failures and not the authoritative full result. The
two previously noted `test_long_job_guard` access violations did not reproduce
in the final contained run; this report makes no claim about a separate master
checkout or host context.

The final pre-publication fetch still resolved `origin/master` to
`890c8195511402656b66b487d2c8f5bb4207693e`; it is an ancestor of the topic,
which was 0 behind and 11 commits ahead before this report commit. The
cumulative diff was reviewed, the exact report path is staged, and only
`codex/workstation-profit-edge-2026-07-26` is pushed. No merge-readiness claim
is made.

## First-class NOT-DONE and NOT-REHEARSED

### NOT-DONE

- No implementation or fix of the post-blend printed-floor ordering bug.
- No implementation of `authoritative_wu_print_freshness_v0.1`.
- No fitting, tuning, threshold search, ablation, or confirmation-window
  outcome evaluation.
- No promotion, release, pointer, activation, serving, scheduler, collector,
  sizing, trading-surface, pull-request, merge, or master-push action.
- No claim of an exploitable subset, executable prices, fills, maker
  eligibility, capacity, future profit, or deployment readiness.
- Backups, durability, and tape work remained out of scope by operator
  direction.

### NOT-REHEARSED

- The preregistered feature extraction, training, leakage audit, and sealed
  14-date confirmation evaluation were not rehearsed.
- The post-blend floor fix was not rehearsed.
- CLOB depth, spread, slippage, queue position, fill probability, maker
  eligibility, and live execution were not rehearsed; captured Gamma prices
  and synthetic complementary NO prices are measurement proxies only.
- Promotion, release, serving, scheduler, collector, sizing, and trading paths
  were not rehearsed; the prior `promotion_refresh` authorization is spent.
- No opened-window outcome was consumed.

All retained evidence is retrospective diagnostic/research evidence only. It
authorizes no model change, cutover, or live action.

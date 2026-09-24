# Mission 92a — amended economic estimand and settlement follow-through

**NO ESTIMATE OF SUSTAINED ZERO-Q ECONOMICS: none of the 203 recorded minutes has zero modelled competition. A minimum-depth filter is not yet an economic improvement.** It retains only 0.493413 of 1.749721 observed reward across both reward days (28.20%), or 0.376038 of 1.632346 on September 24 (23.04%). For zero-Q picks, the smaller/wider quote is a better prospective test of capital efficiency than automatically excluding the band. It preserves *instantaneous modelled* reward while competition stays zero, not necessarily realized reward or fill performance.

This is an append-only follow-up to the
[initial report](agent-report-2026-09-92a-re1-campaign-analysis.md), which was
published before the next fetch delivered the same handoff's amendment at
`a31712e2d0e05fbdd24de96ee8acfa5f79c50fc5`. The original report and its cached
evidence remain intact. The script is extended on the same authorized branch,
`codex/re1-campaign-analysis-20260924`; no RE-1 execution code changes.

## Correct naming and reward attribution

**The filesystem's `session-*` names are attempt IDs.** Per the amendment,
attempts 1–9 map to owner sessions 1, 2, none, 3, 4, 5, 6, 7, 8. All initial
report tables used directory labels. The mapping below supplies the actual
session number; the script refuses a new attempt without an explicit mapping.
The four fills are owner sessions **1, 4, 7 and 8**, not owner sessions 1, 5,
8 and 9. Attempt 3 was an opening check and posted nothing.

September 24's observed accrued reward is attributable to:

- Miami September 25, 90–91°F: 0.451583 cumulative, consisting of session 3's
  observed 0.013563 and session 4's 0.438020 increment.
- Atlanta September 26, 80–81°F: session 5, 0.376038.
- Chicago September 24, 68–69°F: session 8, 0.804725.
- The LA attempt and Atlanta same-day sessions 6–7 have no observed earnings
  row; their zero entries mean absent credit at those polls, not a proven
  final zero. The opening check also contributes no observed credit.

Their 1.632346 total is from asynchronous condition reads. The supplied copy
does not timestamp or reproduce the owner's approximately 1.40 UI observation;
these bands explain the captured accrual, not an exact 1.40 reconciliation.
No payment receipt exists. Reward retention is an in-sample accounting sum of
observed session increments, **not the reward a different quoting strategy
would actually have earned**. Exposure and maker competition would change.

## Economic estimand and revised recommendation

The requested comparison is reward per band-minute at zero versus positive
competing Q, net of fill markout per band-hour. **The zero-Q minute denominator
is zero.** Attempts 2 and 4 were zero-Q *at selection*, but only attempt 4 has
minute samples, and both already have positive competition. Consequently the
two selection-stratum rows below are descriptive proxies, not an estimate of
the requested sustained-zero-Q treatment effect.

The zero-at-pick stratum has two recorded minutes, 0.013563 accrual and no
fills: 0.0067815 per recorded band-minute and 0.40689 per band-hour including
zero observed fill markout. The positive-at-pick stratum has 201 recorded
minutes, 1.736158 accrual and four fills. Its five-minute sampled-price marks
sum to -6.015231, giving **-1.277335 per recorded band-hour** after adding the
observed accrual. This is gross of unobserved fees/costs and uses sampled
public prices, not verified book midpoints or settlement. Missing Chicago
30-minute and Atlanta/Chicago 120-minute marks at the frozen 15:55Z read make
those pooled net outcomes NA. No missing fill is assigned zero markout.

Minute counts are the recorder's denominator, not a reconstructed continuous
two-order resting interval. Accrual polling is delayed and condition/day
cumulative. These limitations prevent causal comparison, and the two-minute
zero-at-pick stratum is especially weak. The Miami fill dominates the negative
five-minute mark; the Atlanta quick fill has a positive mark. **Fill hazard
alone is not the economic objective.**
The combined mark treats nominal accrued reward at par with the pUSD price
mark; it does not prove asset conversion, payment or realized cash P&L.

Accordingly, the initial depth threshold should be treated as one prospective
comparison arm, not a recommended blanket rejection of zero-Q bands. A
concrete alternative for the next experimental protocol is:

1. On a freshly verified zero-Q band, quote the smallest size at or above the
   captured reward minimum at `reward_max_spread - 1c`, with both BUY prices
   snapped away from the midpoint to the tick. Both captured empty-band picks
   have minimum size 20 and maximum spread 4.5c. Compared with 75 at 1.5c,
   reserve falls from 72 to **18.4**, and the per-leg share exposure falls
   73.3%; the modelled share is 100% in both cases only while Q remains zero.
2. Freeze a like-for-like comparison before more outcomes are read: reward
   per measured two-sided minute and reward plus matched-horizon markout per
   band-hour; separate zero-Q-at-pick from minutes actually at zero Q. Retain
   accrual, fill cost, marked inventory and later settlement side by side.
3. Reassess at ten elapsed minutes using observed share rather than selected
   share. Do not infer an optimal duration or a hard profitability stop from
   four fills, a censored heartbeat session and two zero-at-pick minutes.
   The original stability-window proposal likewise remains untested.

The counterfactual holds the adjusted midpoint, book, rate and competing Q
fixed. Scoring uses the repository's quadratic reward rule and Q-min formula,
implemented locally with decimal tick rounding. On the two zero-Q picks,
tick rounding makes the wider quotes 4c away and own Q falls from 23.1481 to
0.2469. If competing Q reaches 10, share drops from **69.83% to 2.41%** for
the smaller/wider quote. Unchanged reward is therefore a zero-competition
identity, not a robust prediction. For Miami's filled attempt, which already
had Q=1.6047 at pick, the smaller/wider model share is only 38.10% instead of
95.41%. No counterfactual fills, queue positions or realized payout are invented.

## Settlement record and reproduction

Four held-position costs sum to **43.788235**: NYC NO 2.6736, Miami YES 26.25,
Atlanta NO 10.864635, Chicago NO 4.00. All four were unresolved in public
market responses both at the original ~15:55Z read and a fresh ~16:10Z check.
Three target September 24; Miami targets September 25. A settlement payoff
requires exact condition/token/outcome binding, `closed=true` and exactly one
winning token. It is distinct from redemption or account reconciliation.

Rebuild with the initial report's command into a separate output directory.
`amendment_tables.md` produces the tables below; CSVs also retain full precision.
The initial public cache can be reused for exact comparison. New public reads
go to a new output namespace. The `positions.json` manifest contains public
condition/token identities and the four captured costs, but no credentials or
order/maker identifiers. Its SHA-256 is
`79c5743cb3231c4fc34cb6443502aa4fe4455b36d0e419640715d3fa0beca04e`.

Subsequent lightweight checks need only that manifest, not campaign access:

```powershell
& $projectPython tools/re1_campaign_analysis_20260924.py `
  --positions $positionsManifest --output $newSettlementScratch --fetch-public
```

This performs four public GETs, one per second, and writes new immutable cached
responses plus `settlements.csv/json`. It never trades, cancels, redeems or
reads a credential. The future settlement outcome remains pending. After an
initial automatic approval rejection, the owner explicitly approved read-only
follow-up. Codex heartbeat `follow-re-1-settlement` is ACTIVE every four hours,
with a prompt referencing the hash-bound local manifest instead of carrying
position details. It stays quiet on unchanged state, preserves fresh receipts,
and publishes an append-only resolution report on this analysis branch. It
pauses after all four positions resolve and the final report is pushed. This
is a Codex follow-up, not a Windows scheduled task or live-execution authority.

The same roll boundary as the initial report applies: one standalone tools
script and Markdown reports, expected roll-free, with the binding production
closure verdict owed. No production access, evidence mutation, RE-1 code
change, credential use, venue mutation, Scheduler registration, merge or
promotion occurred. No p-values or model were fitted. The initially published
report is preserved rather than silently changed to the amended question.

## Verification and retained evidence

Code commit `c41d9393600351f5d1c94b3c072cf90e824cc1f2` on
`codex/re1-campaign-analysis-20260924` implements this amendment. The script's
SHA-256 is `9db3b9992f6314e32db024a0a007a61bd63a665d868bf8bef872c6d3896f4daa`.
Offline reproduction retained nine attempts, four fills and 203 minute
samples, with all prediction bindings and before/after input hashes passing.
The 40-file input manifest is unchanged from the initial report:
`022daa89c2f31dc40c40755f2142b6f25dfb7f31c530fa10cae18a655c630c61`.

Ten deterministic scratch tests passed in 0.07 seconds through the shared
workstation lease. They cover winning/losing payouts, refusal to resolve an
open market, ambiguous winners and mismatched identity, refusal to write
inside the evidence copy, empty-band quote arithmetic and complementary-book
depth. Test payload: `-m pytest scratch/test_re1_analysis.py -q --basetemp
<owned-absolute-directory> --junitxml scratch/92a-checks.xml`. The disposable
test source is retained in the evidence bundle, SHA-256
`75b7da2d4769e4919dd06426f09919113fa1e5af02a5f0823229c2da9bd8c4db`.
The analysis script and tests also passed wrapped `compileall`. Documentation
audit passed (18 agent files, 921 Markdown files); diff checks passed.

Local evidence bundle `scratch/re1-92a-amendment-evidence-20260924.zip` has
SHA-256 `c8fd2f5866c78d79d7b09a09e4a3699c9587f7c182a7b716de9288b194519bb3`.
It contains generated tables, immutable public cache, the fresh 16:10Z
settlement receipts and deterministic test source/results, not the owner's
private campaign copy. The rebuilt `tables.json` hash is
`ed00cecc0b4b764cbc73e7d0b6423e2b4aa27d1b91d7effce05f828c2976d96f`.
The initial bundle remains separate and unchanged. For another host, transfer
the retained bundle explicitly or supply the owner-authorized copy and
rebuild; neither ignored scratch data nor the campaign is presumed present
in a clean checkout.

<!-- BEGIN AMENDMENT TABLES -->

## attempt_session_map

| attempt_directory | session_number | market | band | reward_day | observed_reward_increment |
| --- | --- | --- | --- | --- | --- |
| session-1 | 1 | nyc | Will the highest temperature in New York City be between 66-67°F on September 24? | 2026-09-23 | 0.1174 |
| session-2 | 2 | los-angeles | Will the highest temperature in Los Angeles be between 78-79°F on September 25? | 2026-09-24 | 0 |
| session-3 | NA | san-francisco | Will the highest temperature in San Francisco be between 70-71°F on September 25? | 2026-09-24 | 0 |
| session-4 | 3 | miami | Will the highest temperature in Miami be between 90-91°F on September 25? | 2026-09-24 | 0.0136 |
| session-5 | 4 | miami | Will the highest temperature in Miami be between 90-91°F on September 25? | 2026-09-24 | 0.4380 |
| session-6 | 5 | atlanta | Will the highest temperature in Atlanta be between 80-81°F on September 26? | 2026-09-24 | 0.3760 |
| session-7 | 6 | atlanta | Will the highest temperature in Atlanta be between 72-73°F on September 24? | 2026-09-24 | 0 |
| session-8 | 7 | atlanta | Will the highest temperature in Atlanta be between 72-73°F on September 24? | 2026-09-24 | 0 |
| session-9 | 8 | chicago | Will the highest temperature in Chicago be between 68-69°F on September 24? | 2026-09-24 | 0.8047 |

## minute_competition_support

| recorded_competition | minute_samples |
| --- | --- |
| zero | 0 |
| positive | 203 |

## economics

| group | attempts | minute_bearing_attempts | recorded_band_minutes | fills | observed_reward_increment | reward_per_recorded_band_minute | horizon_minutes | markout_total | reward_plus_markout_per_recorded_band_hour |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Q_pick_zero | 2 | 1 | 2 | 0 | 0.0136 | 0.0068 | 5 | 0 | 0.4069 |
| Q_pick_zero | 2 | 1 | 2 | 0 | 0.0136 | 0.0068 | 30 | 0 | 0.4069 |
| Q_pick_zero | 2 | 1 | 2 | 0 | 0.0136 | 0.0068 | 120 | 0 | 0.4069 |
| Q_pick_positive | 7 | 5 | 201 | 4 | 1.7362 | 0.0086 | 5 | -6.0152 | -1.2773 |
| Q_pick_positive | 7 | 5 | 201 | 4 | 1.7362 | 0.0086 | 30 | NA | NA |
| Q_pick_positive | 7 | 5 | 201 | 4 | 1.7362 | 0.0086 | 120 | NA | NA |

## thresholds

| rule | keep | exclude | fill_sessions_kept | minute_samples_kept | observed_reward_increment_retained | September24_reward_increment_retained |
| --- | --- | --- | --- | --- | --- | --- |
| Q>=10 | session-1, session-6 | session-2, session-3, session-4, session-5, session-7, session-8, session-9 | 1 | 98 | 0.4934 | 0.3760 |
| depth>=75_each | session-1, session-6 | session-2, session-3, session-4, session-5, session-7, session-8, session-9 | 1 | 98 | 0.4934 | 0.3760 |
| day_ahead>=1 | session-1, session-2, session-3, session-4, session-5, session-6 | session-7, session-8, session-9 | 2 | 188 | 0.9450 | 0.8276 |
| Q>=10_and_day_ahead>=1 | session-1, session-6 | session-2, session-3, session-4, session-5, session-7, session-8, session-9 | 1 | 98 | 0.4934 | 0.3760 |

## counterfactuals

| attempt | session_number | policy | competing_Q_pick | size | yes_buy | no_buy | own_Q | share_many | reserve | worst_one_leg_cost | share_if_competing_Q10 | reward_per_minute_fixed_book |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| session-1 | 1 | 75_at_1.5c | 40.1558 | 75.0000 | 0.4900 | 0.4800 | 33.3333 | 0.4536 | 72.7500 | 36.7500 | 0.7692 | 0.0170 |
| session-1 | 1 | minimum_at_max_minus_1c | 40.1558 | 20.0000 | 0.4700 | 0.4600 | 0.9877 | 0.0240 | 18.6000 | 9.4000 | 0.0899 | 0.0009 |
| session-2 | 2 | 75_at_1.5c | 0.0000 | 75.0000 | 0.3400 | 0.6200 | 23.1481 | 1.0000 | 72.0000 | 46.5000 | 0.6983 | 0.0312 |
| session-2 | 2 | minimum_at_max_minus_1c | 0.0000 | 20.0000 | 0.3200 | 0.6000 | 0.2469 | 1.0000 | 18.4000 | 12.0000 | 0.0241 | 0.0312 |
| session-3 | NA | 75_at_1.5c | 1.6988 | 75.0000 | 0.4100 | 0.5600 | 33.3333 | 0.9515 | 72.7500 | 42.0000 | 0.7692 | 0.0317 |
| session-3 | NA | minimum_at_max_minus_1c | 1.6988 | 20.0000 | 0.3900 | 0.5400 | 0.9877 | 0.3676 | 18.6000 | 10.8000 | 0.0899 | 0.0123 |
| session-4 | 3 | 75_at_1.5c | 0.0000 | 75.0000 | 0.3300 | 0.6300 | 23.1481 | 1.0000 | 72.0000 | 47.2500 | 0.6983 | 0.0340 |
| session-4 | 3 | minimum_at_max_minus_1c | 0.0000 | 20.0000 | 0.3100 | 0.6100 | 0.2469 | 1.0000 | 18.4000 | 12.2000 | 0.0241 | 0.0340 |
| session-5 | 4 | 75_at_1.5c | 1.6047 | 75.0000 | 0.3600 | 0.6100 | 33.3333 | 0.9541 | 72.7500 | 45.7500 | 0.7692 | 0.0272 |
| session-5 | 4 | minimum_at_max_minus_1c | 1.6047 | 20.0000 | 0.3400 | 0.5900 | 0.9877 | 0.3810 | 18.6000 | 11.8000 | 0.0899 | 0.0108 |
| session-6 | 5 | 75_at_1.5c | 19.4583 | 75.0000 | 0.4300 | 0.5400 | 33.3333 | 0.6314 | 72.7500 | 40.5000 | 0.7692 | 0.0228 |
| session-6 | 5 | minimum_at_max_minus_1c | 19.4583 | 20.0000 | 0.4100 | 0.5200 | 0.9877 | 0.0483 | 18.6000 | 10.4000 | 0.0899 | 0.0017 |
| session-7 | 6 | 75_at_1.5c | 2.9272 | 75.0000 | 0.3800 | 0.5800 | 23.1481 | 0.8877 | 72.0000 | 43.5000 | 0.6983 | 0.0518 |
| session-7 | 6 | minimum_at_max_minus_1c | 2.9272 | 20.0000 | 0.3600 | 0.5600 | 0.2469 | 0.0778 | 18.4000 | 11.2000 | 0.0241 | 0.0045 |
| session-8 | 7 | 75_at_1.5c | 4.5551 | 75.0000 | 0.3800 | 0.5900 | 33.3333 | 0.8798 | 72.7500 | 44.2500 | 0.7692 | 0.0544 |
| session-8 | 7 | minimum_at_max_minus_1c | 4.5551 | 20.0000 | 0.3600 | 0.5700 | 0.9877 | 0.1782 | 18.6000 | 11.4000 | 0.0899 | 0.0110 |
| session-9 | 8 | 75_at_1.5c | 2.1630 | 75.0000 | 0.5700 | 0.4000 | 33.3333 | 0.9391 | 72.7500 | 42.7500 | 0.7692 | 0.0724 |
| session-9 | 8 | minimum_at_max_minus_1c | 2.1630 | 20.0000 | 0.5500 | 0.3800 | 0.9877 | 0.3135 | 18.6000 | 11.0000 | 0.0899 | 0.0242 |

## settlements

| attempt | session_number | market | outcome | size | entry_cost | observed_at | resolved | winning_outcome | settlement_payoff | settlement_PnL | status | basis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| session-1 | 1 | nyc | No | 5.5700 | 2.6736 | 2026-09-24T15:55:42.254947+00:00 | False | NA | NA | NA | unresolved | venue_resolution_payoff_not_wallet_redemption |
| session-5 | 4 | miami | Yes | 75.0000 | 26.2500 | 2026-09-24T15:55:44.356672+00:00 | False | NA | NA | NA | unresolved | venue_resolution_payoff_not_wallet_redemption |
| session-8 | 7 | atlanta | No | 18.4146 | 10.8646 | 2026-09-24T15:55:46.461905+00:00 | False | NA | NA | NA | unresolved | venue_resolution_payoff_not_wallet_redemption |
| session-9 | 8 | chicago | No | 10.0000 | 4.0000 | 2026-09-24T15:55:48.543964+00:00 | False | NA | NA | NA | unresolved | venue_resolution_payoff_not_wallet_redemption |

<!-- END AMENDMENT TABLES -->

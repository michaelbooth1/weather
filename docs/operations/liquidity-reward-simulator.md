# Local liquidity reward simulator

Status: canonical. The owner requested local formula simulations on September 11,
2026. This adds an offline simulator page to the existing Streamlit router.

Open **Reward Simulator** in the page selector, or use `?market=simulator`.
The canonical local app entry point remains `app/streamlit_app.py`. Follow the
[development guide](../development.md) and host workload policy when launching.

## Calculation and scope

`weather.market.maker_reward_simulation` adapts explicit hypothetical inputs to
`maker_incentive_feasibility.assess_buy_plan`; it does not duplicate the scoring
implementation. A submitted YES BUY contributes to one side and a NO BUY to
the complementary side. The calculator applies size and spread cutoffs,
quadratic distance scoring, the central-midpoint one-sided adjustment, and
normalization including our own score.

[Polymarket's methodology](https://docs.polymarket.com/programs/liquidity-rewards)
defines the public scoring equations. The simulator assumes a common normalized
multiplier of one, a full hypothetical UTC day, 1,440 nonempty equally weighted
samples, a user-specified pool, and constant other-maker Q-min while we
participate. These choices are scenario inputs: the documentation's 10,080-sample
epoch example does not qualify a particular day's sample count or pool.

The other-maker input is the sum of each maker's Q-min after nonlinear side
aggregation. Anonymous book depth cannot identify it. Outside our selected
participation, the scenario assumes other makers keep the epoch samples
nonempty. Empty-sample redistribution and time-varying competition require
a separate explicit scenario model.

Each 30-minute, two-hour, six-hour and one-day row is a separate completed-day
scenario. Participation and remaining-share fractions are constant within the
selected window. A remainder below the reward cutoff scores zero. Filled
inventory cost remains committed alongside unfilled order reserves and cleanup.
Neither modeled fill fractions nor modeled exit losses become paper fills or
execution evidence.

[The official daily payout guide](https://help.polymarket.com/en/articles/13364466-liquidity-rewards)
says subminimum daily earnings are unpaid and do not carry between days. This
tool's threshold calculation assumes the modeled condition is the account's
only reward income, a completed day, and the entered minimum in reward units.
An actual account requires all qualifying income and an asset/fiat contract.

The reward asset (Polygon USDC.e) and collateral (pUSD) remain distinct. Users
enter the conversion assumption explicitly. Net scenarios subtract operating
cost and a per-filled-share all-in loss covering exit, adverse selection and
fees. No spread capture, settlement gains or rebates are invented. The separate
zero-payment result remains visible.

## Observed starting points

An optional bounded `maker_opportunity_capture` upload is reparsed and validated
before showing at most six supported single-asset presets. Identities, book
prices, size/spread terms, timestamp and input hash remain attached to the
export. The ordinary midpoint only seeds an assumed adjusted midpoint; the
configured daily rate only seeds an assumed whole-day pool. All edited settings
are explicit assumptions. Uploading a historical snapshot never asserts
current freshness or promotes a scenario into the public opportunity report.

The upload uses the capture owner's duplicate-key, finite-number and 32 MiB
packet bounds. It does not read arbitrary server paths or call external APIs.

## Output contract and verification

Downloadable `maker_reward_simulation` JSON retains inputs, their hash,
assumptions, source URLs, capital accounting, separate horizon results and
any chosen capture provenance. `paid_rewards` and `realized_pnl` remain null;
`live_order_authority` is false. The format is a hypothetical scenario, not
an earnings, credit, paper-order or live-readiness artifact.

Focused tests cover the published algebra, the inclusive 0.10/0.90 boundaries,
self-in-denominator normalization, backed paired orders, partial-fill cutoff,
daily minimum, zero participation/payment, conversion sensitivity, invalid
inputs, upload parsing, and interactive route changes. The simulator loads no
monitor data, credentials, SDK client or order adapter.

## Update when

Update with changed formula assumptions, simulation horizon/asset scope,
controls, export schemas or upload bounds. Keep observed opportunity
qualification in [the opportunity report](maker-opportunity-report.md).

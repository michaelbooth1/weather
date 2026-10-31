# Pre-registration checklist

Status: canonical checklist (lane L7, 2026-10-24; (f) and (g) DRAFT by lane L8, 2026-10-30, for master's
review). Enforced by `python -m weather.reporting.scorecards.prereg_check [--forward] <rule.md>`, which refuses a
rule file that lacks any section below.

- **Owns:** what a pre-registered rule file must state before any development-window candidate is scored,
  and the order of the steps around it; the (f) power gate and (g) futility sections that a pre-registration
  on forward dates adds (MODEL_IMPROVEMENT_METHOD §5 rules 6-7).
- **Read when:** writing a keep/kill or pick rule for a model, source or blend candidate; before scoring
  anything on the development window (2026-07-31..09-29) with the
  [dev scorecard](../research/dev-scorecard-2026-10-23.md) or the loss atlas.
- **Do not use for:** the results themselves ([findings digest](FINDINGS_DIGEST.md) and
  [established findings](ESTABLISHED_FINDINGS.md)); the list of candidates already scored
  ([dev-window reuse ledger](DEV_WINDOW_LEDGER.md)); confirmation looks on reserved dates
  ([reserved confirmation window](reserved-confirmation-window.md), [campaign ledger](CAMPAIGN_LEDGER.md)).
- **Update when:** a new required section is agreed (change the checker and its test in the same commit), or
  a lesson like the one in (b) costs a lane a result.

## The five required sections

The checker matches each heading (any level; an `(a)`..`(e)` prefix is optional) and the content named. A
section containing `TBD` or `TODO` does not count.

| | Heading | Must state | Why |
| --- | --- | --- | --- |
| (a) | `Positive control` | The control and its expected values, as numbers. For the dev window: served vs market pooled R **1.774** (all hours) and **1.526** (00-16) on the dev scorecard's default folds, which the loss atlas reproduces before it reads any candidate. | A harness that cannot reproduce a known number cannot be trusted with an unknown one. |
| (b) | `Comparator fairness` | That the comparator gets the **same floor and the same calibration** as the candidate (name both). On the dev scorecard both arms get the rule-4 floor mask and served fallback; a trainer-side comparison must floor and calibrate its baseline the way serving does. | The unfair raw-R0 lesson (below). |
| (c) | `Targeted loss slice` | The slice of the loss the candidate is meant to close and its expected size, taken from a loss-atlas run (cite the atlas sha256, at least 12 hex characters). | A candidate aimed at a slice the atlas shows is small cannot pay; a decision on the wrong slice is a post-hoc read. |
| (d) | `MDE and clusters` | The MDE (80% power, from the scorecard's centred bootstrap) and the cluster count (dates and markets). | 11 US market clusters cap crossed power (EF §10j); a null below the MDE is "no increment demonstrated", not "no effect". |
| (e) | `Dev-window reuse` | The reuse count from the [dev-window reuse ledger](DEV_WINDOW_LEDGER.md) (name `DEV_WINDOW_LEDGER` and the integer). | The edge test must correct for every candidate tried on these dates. |

### The unfair raw-R0 lesson (2026-10-24, two lanes)

Two lanes compared their candidate with **raw R0**: the trainer's validation HGB blended with climatology,
with no hard floor and no calibration. Serving applies both, so raw R0 is a comparator nobody serves; it is
worse than its own climatology baseline, and a floored bias-corrected forecast alone beats it.

- Lane L2 (pooled residual model): a −1.968 nats "win" at 07-12 against raw R0, withdrawn as a gain over
  serving. Record:
  [`docs/research/l2-pooled-residual-2026-10-24/README.md`](https://github.com/michaelbooth1/weather/blob/claude/pooled-residual-model-20261024/docs/research/l2-pooled-residual-2026-10-24/README.md)
  on `claude/pooled-residual-model-20261024` (`685c5beec`).
- Lane L3 (OLS + floor challenger): added floored R0, floored baseline and forecast + floor controls after the
  fact (commit `7a1b486c0` on `claude/r0-ols-floor-challenger-20261024`).

Fair means the same floor, the same calibration and the same rows. The paired dev-scorecard control
(`model_minus_control` on identical rows and crossed weights) is the default way to get it.

## Forward pre-registrations: (f) power gate and (g) futility

A pre-registration that spends forward dates must also carry (f) and (g), checked with `--forward`. They apply to
new pre-registrations only. Bound tests (B, MG-1, L6_G, R-ODC P1) never change, and B gets no futility look
(MODEL_IMPROVEMENT_METHOD §5 rule 7). Both sections are written as `- key: value` field lines so the checker can
read them.

| | Heading | Fields | Checked |
| --- | --- | --- | --- |
| (f) | `Power gate` | `sigma_d`, `rho`, `VIF`, `delta`, `N`, `MDE80`, `power`, `class`, `intervals`; optional `block3 ratio`; `N80` for a SCREEN | `sigma_d` names exactly one source block, `history` or `dev` (never pooled), and its file sha256 (12 hex or more). VIF ≥ max(1, (1+ρ)/(1−ρ), block3 ratio²). N ≥ 20. MDE80 ≥ 2.802 × σ_d × √VIF / √N (2% tolerance; the 4-7% heavy-tail inflation is welcome). Power ≥ 0.5 and no more than 0.02 above the normal power at delta. `class` is POWERED exactly when delta ≥ MDE80, otherwise SCREEN with N80. `intervals` names the date-clustered and the block-3 interval. |
| (g) | `Futility` | `look 7`, `look 14`, `look 21`, `look 31` (those before N), `final N`, `interim PASS` | The looks are exactly Rule B: `HARM if t > 3.143`, `FUTILE if z > +0.5`, `FUTILE if z > 0`, `FUTILE if z > -0.5`. `final N` equals (f)'s N. `interim PASS: never`. |

Rules the fields carry (MODEL_IMPROVEMENT_METHOD §5 rules 6-7; evidence: ledger rows 73 and 82):

- **sigma_d from the same pair on the same scale**, from the newest block, labelled history or dev, with its date range
  and file sha256. A dev back-out from an interval has no measured ρ: use the nearest measured pair's ρ and say so.
- **VIF from the long-run factor.** On dev, MG-1 − served has a daily lag-1 ρ of +0.42 (row 82). A block-3 VIF (1.74)
  then leaves Rule B a 5.1% false PASS; (1+ρ)/(1−ρ) = 2.44 brings it back to 2.9%, with power 0.80 at its own MDE80.
  The history pairs showed ρ between −0.06 and +0.07 (row 73).
- **delta is not the dev point alone.** It is in-sample and optimistic. State the power at the dev point and at half
  of it, and use half for `class`. Against the market, R ≈ 0.95 at 45 dates has power of only 0.47 to 0.57 at 07-12
  and 0.06 to 0.13 at 13-16 (row 82); such a test is a SCREEN or does not launch.
- **Final interval.** The verdict uses the scorer's date-clustered interval. A block-3 interval is reported beside it,
  and if the two disagree on the verdict, the more conservative verdict holds.
- **Looks.** z_k = mean_k / (s_k × √VIF / √k), with positive meaning harm. A stop is recorded as HARM (look 7) or
  FUTILE, and it is final for that pre-registration. No interim look produces a PASS, changes N or the estimand, or
  starts a refit. A look reads a date only when §5 rule 9 allows it, and its ledger row is committed before the read.
- **Operating characteristics on dev** (row 82; 20,000 paths). Under the null, Rule B stops 66% to 77% of runs by
  look 31, and its look-7 harm stop fires 0.3% to 2.1% of the time. At δ = MDE80 the futility looks cost 0.2 to 1.6
  points of power.

## Steps

1. Run the loss atlas for the base you will compare against (`python -m weather.reporting.scorecards.loss_atlas
   atlas --layout <layout> --candidate served --out <dir>`, through `scripts\ops\workstation_heavy.ps1`). It
   refuses (exit 7) unless the positive control in (a) reproduces. Take the slice and size for (c) from it.
2. Read the reuse count for (e) from the [ledger](DEV_WINDOW_LEDGER.md), then add your candidate's row with
   verdict `pending`.
3. Write the rule file with sections (a)-(e) and the keep/kill rule, and run
   `python -m weather.reporting.scorecards.prereg_check <rule.md>` until it passes.
4. Record the rule file's sha256 (the checker prints it) and commit the file **before** any result exists.
5. Score, then fill the ledger row (headline delta, CI, verdict) and run the atlas in delta mode
   (`--candidate-...` of the scored candidate) to show which slice it closed.
6. For a pre-registration on forward dates, add (f) and (g) from the forward template below and run the checker
   with `--forward` until it passes, before D0.

A dev-window win is provisional: it earns a pre-registration on new dates and a forward shadow, not a
promotion (EF §5).

## Template

<!-- template:start -->
```markdown
# Rule <id> (lane <lane>, <date>)

## (a) Positive control
Served vs market pooled R 1.774 (all hours) and 1.526 (00-16), dev scorecard default folds; the loss atlas
refuses otherwise.

## (b) Comparator fairness
The comparator gets the same rule-4 floor and the same calibration as the candidate, on identical rows
(paired control, crossed weights). Not raw R0.

## (c) Targeted loss slice
Loss atlas `0123456789ab` (the atlas JSON sha256 prefix): the 07-12 centre slice, expected size 0.0100 of the
0.0258 excess (Shapley centre share 76.5%).

## (d) MDE and clusters
MDE80 0.0060 (crossed) at 43 date clusters and 11 market clusters.

## (e) Dev-window reuse
DEV_WINDOW_LEDGER.md: this is candidate number 20 on 2026-07-31..09-29.

## Keep/kill rule
KEEP only if ...; otherwise KILL.
```
<!-- template:end -->

Forward pre-registrations append these two sections (checked with `--forward`):

<!-- forward-template:start -->
```markdown
## (f) Power gate
- sigma_d: 0.0110 (dev, MG-1 - served 00-16, 2026-08-15..09-29, s5_out.json sha256 b1a504bcf9e5)
- rho: +0.42
- block3 ratio: 1.32
- VIF: 2.45
- delta: 0.0060 (half the dev point; power at the dev point 0.99)
- N: 45
- MDE80: 0.0076 (2.802 x sigma_d x sqrt(VIF) / sqrt(N), inflated 5%)
- power: 0.64
- class: SCREEN
- N80: 65
- intervals: date-clustered (verdict) and block-3 (reported beside it)

## (g) Futility
- look 7: HARM if t > 3.143
- look 14: FUTILE if z > +0.5
- look 21: FUTILE if z > 0
- look 31: FUTILE if z > -0.5
- final N: 45
- interim PASS: never
```
<!-- forward-template:end -->

The template's numbers are placeholders shaped like real values; replace every one.

# Pre-registration checklist

Status: canonical checklist (lane L7, 2026-10-24). Enforced by
`python -m weather.reporting.scorecards.prereg_check <rule.md>`, which refuses a rule file that lacks any
section below.

- **Owns:** what a pre-registered rule file must state before any development-window candidate is scored,
  and the order of the steps around it.
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

The template's numbers are placeholders shaped like real values; replace every one.

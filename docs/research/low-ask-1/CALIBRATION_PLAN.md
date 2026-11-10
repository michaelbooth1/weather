# LOW-ASK-1 synthetic calibration job

Status: revised under MASTER RULINGS B1-B4; tiny synthetic checks only, full
study not run. Owns review/admission for `weather.backtesting.low_ask_calibration`.
The [preregistration](PREREG_LOW_ASK_1.md) owns the exact assumptions and rule.
Stop for the master's GO on the revised commit before any calibration run.

## Generated inputs and fixed scope

No market, price, label, outcome, weather, capture, account or credential file
is an input. All binary venue outcomes are invented. Later phases read only
named `train-000.json`..`train-119.json` and
`validate-000.json`..`validate-119.json` in the chosen task output directory.
`--out` must resolve under `C:\t\codex\T093\`; traversal, sibling paths and
reparse-point ancestors are refused. No glob or full panel store.

The 36 base arms cross phi {0,.22,.5}, common-city share {0,.25,.5}, fixed
persistent-city share {0,.25} and spread/clustered missingness. Cross these
with 810, 900 and Chicago-missing 825 supports (108 ask-.80 arms). Add ask-.93
nulls to phi=.5/common=.5, both persistent shares and mechanisms, at each
support: 12 more. All **120 size arms** enter the worst-case critical value.
The exact indexed list is `SIZE_ARMS`; no arm is selected after simulation.

At 810, seven dates and six further city-days are absent on distinct retained
dates: 68 dates have >=11 executable cities. Clustered puts three of those
seven absent dates together. At 900 nothing is absent; at 825 Chicago is
absent throughout. Capital blocks remain executable-validated. The 68-date/
11-city thresholds are provisional pending Nov 14-16 coverage commissioning.

Fixed normal-quantile city offsets have zero 12-city mean/unit variance and
are reused across panels. A common probit threshold preserves the declared
fixed-city average survival after the nonlinear CDF. AR/common innovations
remain random. Ask-.80 null survival is .818. Ask-.93 survival is the master's
rounded .9433 versus exact cost .943255. There is no simulated-profit
re-centring. Each effect adds delta/(10*support/900) before cash rationing.

## Actual cash and statistic

The generated account copies the core cash policy: $300 initial cash;
all-in debit at fill; realized $5/$0 payout after one day (.9) or three (.1)
per slot; permanent losses, retained gains, no reset. Resolve before fills
at the same instant. Refuse cash < cost or locked+cost >$300. Only this total
cap can bind. Integer microdollars exactly match Decimal costs at both asks.
The loop groups by UTC instant and selects the eligible city/cut prefix;
independent scalar Decimal witnesses cover its ordering and boundary behavior.

The final statistic remains mean/robust-scale without correcting the
policy's own drift. Each arm/effect reports cash_cap slots, P(binding), peak
locked cost, ending cash, mean policy profit, date SD and SD ratios to the
T086 planning proxy 1.4346 and the master's planning-arm proxy 1.63.

Bootstrap weights exactly match the final look's interleaved seeded draws.
Non-degenerate parity tests compare every date/block/crossed-bootstrap lower
bound, upper bound and p-value to `inference.interval`, plus its analytic
calibrated lower bound. Analytic failures skip the expensive bootstrap since
they cannot be rescued by it. Sealed trial output reports realized/planning SD.

## Size and planning power gates

Training/independent validation each have >=20,000 null panels per size arm.
Critical value is the worst **.9925** training quantile, with a normal-critical
floor. Every validation size upper bound must be <=.0125, using simultaneous
one-sided 95% Clopper-Pearson bounds (.05/120 each). Validation never retunes.
The calibrated analytic gate is conservative for the fuller bootstrap verdict.

Power uses 2,000 panels per ask-.80 arm/effect and the final 20,000 bootstrap
draws. Report the original **144** cells plus 288 added-support cells: **432**.
Ask-.93 additions are null-only. Only phi=.22/common=.5/persistent=0 at support
810, **both** missingness mechanisms, must have power lower bound >=.80 at
effect .6741 dollars/intended city-day. Those two bounds spend .05/2; other
diagnostic bounds use .05/432. This is the master's planning arm (alternative
SD proxy ~1.63 >= T086 1.4346, method rule 19), not a worst-arm power claim.
The other effects are .9490, .7490 and .5000. Null/power RNG streams are
disjoint; all four effects reuse the same predetermined power random numbers.
Power includes economic floor and executable completeness, conditional on the
external full-family unweighted Holm package of 2-4 claimants.

Every size arm and both planning bounds must clear for CALIBRATED. Otherwise
write SCREEN_ONLY and measured power plainly for the owner's effect/alpha/N
decision. No retuning, subset rescue or extension after validation. Monte Carlo
bounds are also checked against SciPy's independent exact binomial inversion.

## Admission and commands after GO

The branch adds this exact module name to both
`Get-WeatherWorkstationOfflineModule` and the repository host-load hook's
`_OFFLINE_WEATHER_MODULES`. Their equality test must pass. No hook is installed,
no Scheduler mutation occurs, and capture code/configuration is unchanged.
The [host load policy](../../operations/HOST_LOAD_POLICY.md) owns admission.
Never set the wrapper's admission environment flag manually.

Use the shared interpreter and this exact worktree through
`scripts/ops/workstation_heavy.ps1 -Kind weather_heavy -Queue`. Python tokens:

1. `-m weather.backtesting.low_ask_calibration train --out C:\t\codex\T093\out\calibration-r1 --arm-start <0..119> --arm-count <1..6>`
2. After all training receipts exist: same token sequence with `validate`,
   `--arm-count <1..3>` and each start index covered exactly once.
3. `-m weather.backtesting.low_ask_calibration summarize --out C:\t\codex\T093\out\calibration-r1`

These are argument tokens, never bare run commands. Queue behind the F2 pregate.
Start with one arm to measure time/memory, then at most six training/three
validation arms per call. Chunks enforce an 18-minute budget between bounded
batches; completed per-arm receipts are immutable. Keep/poll every executor ID.
Retain failed attempts. Resume an unchanged interrupted arm only without
overwriting receipts; a partial receipt requires a new attempt, preserving and
verifying complete prior receipts. Changed bytes require a new output attempt.

Honor HOLD_HEAVY, serial execution and memory hysteresis. From Wednesday onward
start no heavy job after 08:30; run nothing heavy 09:00-19:00 Toronto. Outside
that interval pause at >=90% commit and resume below 88%. No parallel jobs.
Expected largest allocation is the ~144-MB double bootstrap cross-weight matrix,
plus dependencies/buffers. Actual time and peak memory await the first GO run.

The aggregate receipt hashes every arm, code/inference/contracts/timezone and
NumPy/SciPy versions, with measured size/power and all diagnostic cells. Bind
its hash and string-valued critical/power fields in the final freeze. This plan
and its tiny tests do not establish scientific size or power.

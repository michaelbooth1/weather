# LOW-ASK-1 synthetic calibration job

Status: implemented, small synthetic parity checks only; full study not run.
Owns the review/admission recipe for `weather.backtesting.low_ask_calibration`.
The [preregistration](PREREG_LOW_ASK_1.md) owns the frozen assumptions and rule;
the master must confirm this candidate generator before a full calibration run.

This module accepts no market, price, label, outcome, observation or account
input. It generates bounded synthetic binary venue cash flows. Its only later
reads are its own named `train-00.json`..`train-35.json` and
`validate-00.json`..`validate-35.json` in the explicit synthetic output root.
No glob, capture export or environment credential is read.

The generator conditions on the minimum 68-date/810-both-filled support, with
spread and clustered missingness. This is conditional power, not a prediction
that capture will meet the counts. The nominal cash-lock mask refunds its
all-in debit, independently of the outcome. It does not calibrate every
realized-profit cash-feedback path. This limitation is an explicit master
confirmation item, not an accuracy claim. The actual paper simulator enforces
actual venue cash, corrections and locked capital.

Training and validation use 20,000 null panels per arm with disjoint RNG
streams. Training chooses the worst .995 quantile of mean/robust-scale, floored
at the one-sided normal critical value. Validation cannot raise that critical
value after seeing its size. Simultaneous Clopper-Pearson upper errors must
clear .0125. Power has 2,000 panels per arm/effect and runs the actual fixed
20,000 bootstrap weights, with small numerical boundary margins in the
conservative direction. Vectorized scale and pass decisions are checked
against the scalar deciding implementation on tiny synthetic panels.

The beta-quantile Monte Carlo bounds are cross-checked against SciPy's
independent binomial inversion at boundary and interior counts; see its
[exact Clopper-Pearson API](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html).

The global critical gate can only reduce false rejections relative to this
mean/scale calibration because the final bootstrap envelope can widen it.
Power includes the point economic floor and counts; it conditions on the
external full-family Holm package. No selected subset of covariance arms
may be reported as the deciding calibration.

Before running, the master reviews this module and its assumption/receipt
contract, admits the exact canonical module in
`Get-WeatherWorkstationOfflineModule`, and sends GO for the reviewed tip.
The branch changes no workload policy or capture configuration. The CLI
refuses without workstation-wrapper admission; do not set its admission
environment flag manually. The external research-script allowlist route is
unnecessary for this packaged CLI; its module admission is owned by the
[host load policy](../../operations/HOST_LOAD_POLICY.md).

Run serially, one arm per invocation at first. All chunks stop after an
18-minute budget between bounded batches, leaving completed arm receipts;
none overwrites an existing receipt. Retain a failed attempt; never silently
replace its code/parameters. An unchanged interrupted arm may be restarted
in a new output attempt with all prior receipts retained. The output root
must be absolute. Use the workstation-heavy wrapper's encoded argument
interface, with the shared project interpreter and this exact worktree.

1. `-m weather.backtesting.low_ask_calibration train --out <synthetic-root> --arm-start <0..35> --arm-count 1`
2. After all training receipts exist, repeat those arms with `validate`.
3. `-m weather.backtesting.low_ask_calibration summarize --out <synthetic-root>`

Every command must run under `scripts/ops/workstation_heavy.ps1 -Kind
weather_heavy`; these are Python argument tokens, not bare run commands.
Honor HOLD_HEAVY, memory hysteresis and the no-heavy live-day window. Retain
and poll the wrapper's executor session until completion. No parallel agents
or tool calls for these jobs. Inspect the first arm's time/peak memory before
deciding whether any larger chunk fits the host budget.

`CALIBRATION_RECEIPT.json` binds all arm hashes, code/contract/inference/timezone
and NumPy/SciPy versions. Status is CALIBRATED only if every size arm and the
planning-effect power lower bound clear. Otherwise SCREEN_ONLY; there is no
post-validation critical-value repair or data-dependent extension. Include
the receipt hash and string-valued critical/power fields in the actual freeze.

Expected retained outputs are small JSON receipts; the largest transient
allocation is the double-precision bootstrap-weight matrix (about 144 MB),
plus its weights/work buffers and dependencies. No full panel store is saved.
Wall time and peak memory are estimates until the first admitted arm runs.

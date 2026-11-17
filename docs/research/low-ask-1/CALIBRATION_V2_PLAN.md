# LOW-ASK-1 calibration-v2 owner-option plan

Preregistered before v2 simulations. This is a new owner-decision support
attempt for Option A, ask <=.90, under the master's 2026-11-11 07:4x task.
The completed v1 attempt at bfcf824a and its SCREEN_ONLY receipt are retained.
Output root is exactly `C:\t\codex\T093\out\calibration-v2`.

## Fixed scientific choices

- Calibration seed **20261111**, with independent NumPy SeedSequence streams
  `[20261111, arm_index, 0]` for training, `[...,1]` for validation and
  `[...,2]` for power. The four effects reuse their power stream within an arm.
  Bootstrap resampling uses fresh `random.Random(20261111)` draws. V1 defaults
  retain seed 20261110. New v2 receipts bind both seed roles and all parameters.
- Ask cap **.90**, inclusive. Ask-.93 size cases are replaced by ask-.90
  cases, with exact all-in cost/survival **.9145**. Ask-.80 cases retain .818.
  Above-cap slots skip execution and retain executable-input completeness.
- There is no authorized observed ask-distribution summary in the reviewed
  charter or input-contract shape. Cap-eligible fractions **1, .75, .50**
  are ASSUMED scenarios. Each generated city-day has one independent Bernoulli
  cap-eligibility draw shared by its two cuts, independent of outcome/source
  missingness. This preserves within-day cap dependence. It does not estimate
  the unknown real association between price eligibility and subsequent profit.
- Eligible-share edge remains the original planning edge. The expected
  scheduled-city-day effects before cash rationing are .6741, .505575 and
  .33705 at those fractions. There is no compensation by dividing the edge
  by the retained fraction. All source supports retain their existing 810/68
  executable-count gates, including above-cap skips.
- Cross the original 36 covariance/missingness cases and three source supports
  with the three fractions. Include the four strongest ask-.90 null stresses
  at every support/fraction. This gives **360 size arms**. A single critical
  value is the maximum .9925 training quantile over all 360, with the existing
  normal floor. Size validation uses .05/360 simultaneous CP tails.
- Power is computed only on the planning phi=.22/common=.5/persistent=0,
  support810/ask.80 cases, both mechanisms, at each fraction. Report four
  effects per case, **24 power cells**. The six .6741 bounds spend .05/6.
  Other diagnostic power bounds spend .05/24. Report a conditional power
  disposition for each fraction and the common size critical value.
- Null replication count 20,000 per arm/phase, power 2,000 per cell,
  bootstrap 20,000, alpha .0125, N75 dates, economic point floor .25,
  fixed centred city effects, retained-city null thresholds, realized $300
  cash and receipt delays remain as in v1. No parameter is tuned after validation.

## Execution and review

CLI adds `--arm-set cap90 --ask-cap .90`. It uses the same canonical module
and existing exact-name admission. `--arm-set v1` remains the default.
V2 refuses any output root except the one above and refuses to replace receipts.

The execution mask and resource guard exceed the master's immediate exception
for an arm-list/cap-constant-only change. Push this diff and stop for review
before the seeded v2 run. Tiny invented-fixture regression tests are permitted.

After GO, use the worktree workstation_heavy.ps1 -Kind weather_heavy -Queue,
serially, with at most six train or three validate arms per invocation. Check
commit <83% and `C:\t\codex\T045j\started.json` absent before starting. V2
also checks these conditions before imports and between bounded simulation
batches, including bootstrap generation. Detection stops the invocation and
retains all completed receipts. The existing 08:15 Toronto start guard and
09:00-19:00 protected period remain binding. No run overlaps the F2 pregate.

The owner receives c, size bounds and both planning powers/lower bounds for
each assumed fraction. Actual paper-policy changes and a scientific freeze
require the owner's design choice and the master's remaining confirmations.

## Option B validity

Separate bucket critical values alone do not calibrate the combined
scheduled-city-day profit statistic. Mixed-bucket positions share dates,
weather and the same capital account. A valid single family test needs a
preregistered combination rule and calibration of that complete procedure,
or a simultaneous construction controlling its total local .0125 error.
Selecting a favourable bucket after seeing results adds multiplicity.
Adding bucket claimants also changes the existing unweighted 2-4-claimant
Holm contract. This task provides words only for B.

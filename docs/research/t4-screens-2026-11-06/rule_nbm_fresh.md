# NBM-FRESH: newly received cycle versus market staleness

Status: pre-read rule, T008r1, master ruling B007, 2026-11-06 14:27 America/Toronto.
Ledger row 121 pins this file's SHA256. **No S1 until master confirms that row has landed
on master after C14.** Stop this lane if S1 is not complete by 2026-11-10 18:00
America/Toronto. No real data has been read for this rule. Later changes require a separately
dated, sha-pinned clarification before the affected read. This is a dev screen, not a T4 freeze.

## Intake, estimand and read boundary

The sole admitted mechanism is **market staleness to a newly received public NBM cycle**.
An unconditional NBM centre tilt remains CLOSED-BY-RULE (X110). K=1; no other signal,
threshold, lag horizon, city subset or hour block may be searched under this row.

US11 only, local hours 07:00-12:59, native Fahrenheit. Burn-in local target dates
2026-08-01..08-14; deciding dev dates 2026-08-15..09-29. Nothing after September 29,
including released October cells, is read. No sealed panel, maker-shadow tape, MG-2/B output,
corpus expansion, fitted model or serving change. No October replay. The MG-1 reservation,
post-September-29 embargo and COMMON remain binding. No trial dates are claimed by this rule.

Stages, strictly ordered: source/timing feasibility; **S1 label-free price lag**; rule-16
outcome-free power projection; one market-residual P0; w for a P0 survivor only.
A stop is final for this rule. A dev tradability replay and T4 prereg need their own rules.

## Source selection and capture-time contract

On resumption, inventory names/metadata first and pin a bounded input manifest before reading
values. The candidate source is the dev layout `C:/swarm/v3layout` and its captured NBM v2
fields; receipt provenance may be verified against the bounded pre-September-30 replay inputs.
Do not open mixed-date files unless a reviewed reader enforces the target-date boundary
before projecting values; a date in a pathname is insufficient. Exact files, sizes, hashes,
column allowlists and timestamp meanings go in the runner's pre-read receipt. No download.

Use captured CLOB YES mids, (best bid + best ask)/2, if the workstation holds dev books with
complete contemporaneous band support, sequencing and timestamp provenance. Do not substitute
public historical samples. If no dev CLOB store exists, use the layout `p_market` display-price
arm, explicitly labelled **DISPLAY PRICE, NOT EXECUTABLE CLOB MID** in every output. Select
the source from metadata before computing any lag; never switch sources after a result.
If CLOB exists but cannot provide valid timing/support, report UNTESTABLE rather than selecting
the display arm for a more favourable statistic. This rule grants no maker-tape read.

Require finite 0<=bid<=ask<=1, complete captured band support, positive market sum and known
receipt/capture timestamps. No complement imputation, interpolation, backfilled books or
last-in-hour emission. Normalise each market ladder to sum 1, retaining its raw sum for QC.
For display prices, require finite values in [0,1] and disclose that capture time alone does
not establish the age of the upstream price. This can establish only display-price lag.

A cycle is identified by station, target date, NBM model/parser version and cycle issue ID.
Require parser v2, status ok, native-unit confirmation and `v2_available_basis=response_received_at`.
Let r be the actual response_received_at of its first successful receipt; repeats do not
restart the clock. An issue time, inferred publication delay or first-observed snapshot is
not a receipt timestamp. All rows use only a cycle received at or before their capture.
Delta is the new v2_mean minus the last distinct previously received valid cycle's v2_mean
for the same station and target date. Missing predecessor means uncovered, not delta=0.

Eligible snapshot iff 0<=capture-r<=15 minutes AND abs(delta)>=1.0 F, and its local hour is
07-12. If a newer cycle arrives, it replaces the old one; never choose between cycles by score.
There is one signal; positive/negative revisions are pooled with their declared sign.

## S1: label-free price lag

S1 reads NBM inputs, market prices, timestamps and band geometry only, never labels or outcomes.
For each revision event with an eligible snapshot, use three **strictly prior-or-at** market
records: last at/before r-15 minutes, last strictly before r, and last at/before r+15 minutes.
Each must be no older than 5 minutes relative to its endpoint, be on the same target date and
band support, and lie within the dev date boundary. No later record fills an endpoint.
Events with another NBM cycle receipt in (r-15min,r+15min] are uncovered.

Market centre mu=sum(m_b*z_b). Interior z is (low+high)/2; open-tail representative is the
terminal boundary plus/minus half the median interior integer-band width (high-low+1), as
in [MR sweep sections 1 and 4](../mr-sweep-2026-10-30/rule_mr_sweep.md). Same geometry at all endpoints.
Define pre=sign(delta)*(mu_0-mu_-15), post=sign(delta)*(mu_+15-mu_0), D=post-pre, all in F.
Average events equally within market/date, markets equally within date, then dates equally.
At least 20 distinct deciding dates are required for S1 survival; otherwise UNTESTABLE.

Timestamp provenance must distinguish receipt from market movement **within the observed
snapshot cadence**. Record precision/uncertainty, actual endpoint offsets and cadence per event.
If the receipt is only first-seen at a snapshot, its uncertainty is at least that cadence and
the event is timing-unresolved. Unresolved events are excluded before statistics, with counts;
if the remaining population lacks 20 dates or cannot separate pre/post, verdict UNTESTABLE.
Never infer sub-cadence ordering from ties or from an assumed source delay.

Date-clustered and circular block-3 bootstrap, 2,000 draws each, seed 20261024, two-sided
95% intervals; use the smaller lower and larger upper bounds. S1 survives only if the wider
lower bound of mean D is >0 AND mean post>0. Otherwise **KILL at S1**: this predeclared price-lag
screen does not establish the mechanism. This is not proof of no possible market lag.
Report pre, post, D, per-date and per-market rows, both intervals and excluded-event counts.
No labelled P0, w or alternate lag runs after an S1 kill. S1 is necessary only, not profit.

## Candidate and comparator fairness

For every eligible snapshot, use the capture-valid trusted observed-high floor from the same
input path, preserving the effective WU print cutoff; never union transient observations or
use a later METAR. Use the same floor and calibration for market and candidate. No learned
recalibration is fitted. Keep raw normalised market as a diagnostic; the deciding residual
comparison uses its floor-masked, renormalised distribution m, so floor gain cannot be credited
to NBM. Missing floor provenance or all mass removed means uncovered and is reported.

With x=v2_mean, mu=sum(m*z), variance=max(sum(m*(z-mu)^2),0.25 F^2), define
s_b=(x-mu)*(z_b-mu)/variance. Let sigma_s be the band-entry SD of s on eligible **burn-in only**.
Then c_b=m_b*exp(s_b/sigma_s)/sum(m*exp(s/sigma_s)), evaluated stably by subtracting max(s/sigma_s).
Zero burn-in variance or absent burn-in coverage is UNTESTABLE; no score-period fit replaces it.
Floor-impossible bands remain zero. Both c and m sum to 1 within 1e-9 and are finite/in [0,1].
No model fit; the same receipt filter, floor, geometry and normalisation must be deployable.

## Full donor population and outcome-free power projection

Freeze a **covered-donor** policy: donor dates are deranged within market/local-hour/identical
band-support groups on eligible, capture-valid burn-in+dev snapshots. Sort dates, then snapshots
by capture timestamp and stable ID; snapshot rank k uses donor rank min(k,n_donor-1).
Groups with fewer than two dates are uncovered. Use 20 derangements, seeds 20260921..20260940.
For a recipient, c_pl=m+(c_donor-m_donor), clip to [1e-12,1], reapply recipient's floor and
normalise to 1. Refuse incompatible support rather than invent bands.
The population P is deciding snapshots covered AND donor-covered under **all 20** seeds,
including valid floor, burn-in scale and support checks. Freeze/write P and each seed's donor map.
Count realised population, events, dates and markets; nominal coverage alone is not the projection.

No real outcomes are opened to size P0. Use planted categorical outcomes on **this actual P**
and the actual c, m and 20 placebos to project the same P0 statistic below. For planning,
q_lambda=(1-lambda)*m+lambda*c, lambda in [0,1]; choose the smallest lambda producing population
expected paired correlation delta_edge=sqrt(0.05)=0.22360679775 (linear/Gaussian 5% squared-error
reduction heuristic from register section 6, necessary not sufficient). If that signal is
unattainable, UNTESTABLE at this bar. Also project delta_half=0.111803398875 and report both.
Compute expected residual first/second moments analytically from categorical q, with the same
band weights/centering used by P0; solve lambda by fixed 60-step bisection. No real y is used.

Run 2,000 synthetic paths per null/half/edge setting, seed 20261106, computing the exact P0
statistic (without nesting a bootstrap inside every path). Use independent date uniforms and
circular three-date blocks sharing their categorical uniform across dates/markets; the latter
is a conservative dependence sensitivity, not an empirical dependence estimate. Record each
setting's mean and SD of paired Delta. Define sigma_plan=1.10 times the largest of these six
SDs; 1.10 is a predeclared planning guard factor, not a measured variance bound. Project power
as both the path fraction Delta>1.96*sigma_plan and Phi(delta/sigma_plan-1.96), taking the
smaller value; report a one-sided 95% Wilson lower bound for the path fraction. This is a
normal-threshold planning approximation to the later bootstrap test, not measured test power.
Require >=20 deciding dates, null path rejection rate <=0.05 in both dependence designs, and
both the edge path-power lower bound and normal projected power >=0.50; otherwise UNTESTABLE,
no real-label P0. Report MDE80=1.05*2.802*sigma_plan (5% planning inflation) and half-effect
power beside it. Freeze simulation output and manifest before any label read. A failure or
unimplementable moment/variance calculation refuses the projection; never substitute a near-twin SD.

## One market-residual P0

Only after S1 and projection survive, join the scorecard's pre-September-30 winner labels on P.
Residual e=y-m; signal g=c-m; placebo g_j=c_pl,j-m. Pooled Pearson rho across snapshot/band
entries; Delta=rho(g,e)-mean_j rho(g_j,e). Degenerate variance is UNTESTABLE.
Resample whole target dates, 10,000 paired draws, seed 20261024. Draw b uses placebo j=b mod 20.
Do the same with circular block-3 dates. Per design, p=(1+count(Delta_boot<=0))/(10001).
Use max(p_date,p_block3) and the wider 95% bounds. BH q=0.10 with K=1; no removed/added arms.
P0 survives iff BH rejects and the wider lower bound>0. Otherwise KILL on this population,
with scope and achieved MDE stated; insufficient power is never called no information.
Report crossed date/market bounds beside, per-hour 07..12, per-market and per-date sufficient
sums for candidate and every placebo. Report realised/projected SD ratio and any population loss;
a changed population invalidates admission and requires a new outcome-free projection first.

## w gate, only for a P0 survivor

Walk-forward log pool, grid w=0.00..1.00 in 0.01 steps, pooled Brier fit at 07-12, only training
dates <=d-2 (burn-in permitted); tie chooses smallest w. Absent training rows means w=0.
Use identical rows for candidate, all 20 disagreement-placebos, w=0 and floor-only market.
Mean w>=0.05; blend/market Brier ratio wider upper<1; paired blend-minus-mean-placebo Brier
wider upper<0; paired blend-minus-floor-only Brier wider upper<0: **all four required**.
Date and block-3 bootstraps, 2,000 draws, seed 20261024; crossed bounds beside.
Failing any check is KILL for this dev screen. No floor-only gain is candidate information.
No taker replay, T4 accrual, executable-profit claim or promotion is authorised by w survival.

## Positive control

Before any real-label P0, reproduce the untouched default scorecard's served R=1.774 all hours
and 1.526 at 00-16 (round to three decimals), MG-1 07-12 excess 0.011957 (absolute tolerance
0.000001), independently of the restricted primary population. w=0 identity must hold within
1e-12. Synthetic zero/reversed/positive signals must exercise the expected verdict branches.
Mass/floor/receipt/date guards must fail on planted violations. Any failed control means
NOT INTERPRETABLE, not candidate KILL. No real labels are needed for S1 or power controls.

## Targeted loss slice

The row-18 served atlas `4d094a63eb25` locates 76.5% of the 07-12 served-minus-market excess
in the centre; this is context, not a measured NBM-FRESH effect. The hypothesis targets receipt
latency in that slice. No projected Brier or P&L gain is claimed from that atlas.

## MDE and clusters

Nominal layout: 43 date clusters, 11 market clusters, before the freshness/donor filter.
No candidate MDE or realised count is yet measured. Admission MDE/power is computed outcome-free
on the full P above at delta_edge=0.22360679775, with the declared dependence sensitivity;
the realised MDE80 and population are written before the first real-label join.

## Dev-window reuse

DEV_WINDOW_LEDGER row 121, K, counts from registration. Master B007 fixes pre-row count 213
(includes unlanded C14 row 120), then **214**, stated as **at least 214** because the pre-ledger
reads include an unitemised count. The three intake closures use no dev read and add no K rows.

## Receipts, execution and archive

The runner is not yet implemented or admitted. Before execution pin code sha, script sha,
inputs, versions and outputs in a reviewed receipt; COMMON's research-script review protocol
still applies. Every heavy run checks HOLD_HEAVY first and uses workstation_heavy.ps1; F0 has
priority. Stream input, keep light work below about 500 MB, retain/poll executor sessions,
respect the live freeze, and retry memory refusals only as COMMON allows. No source reads now.

Write immutable S1, donor-population, simulation, P0 and w receipts only as each tier is reached;
every receipt records stages not reached. Preserve per-date rows, source/cadence disclosure,
coverage exclusions, code/rule/input hashes, command, real clock, memory and runtime.
Task outputs go under C:\t\codex\T008r1\out\, indexed with per-file SHA256.
Every kill keeps rule, code, outputs and receipt in the never-cleaned ruled-out archive.
Never overwrite a consumed run. No result exists under this rule until the master's resume.

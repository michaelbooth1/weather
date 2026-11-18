# L5 item 2: NWS Area Forecast Discussion screen for the coastal markets, pre-registration (2026-10-24)

**Status:** frozen pre-registration (sha256 in the commit that adds it, the result and the lane report),
committed before the AFD candidate was scored. Development evidence only (dates <= 2026-09-29). Results go in
[the L5 diagnosis record](morning-loss-diagnosis-2026-10-24.md) as an addendum.

## Archive check (coordinator ruling 2)

The IEM AFOS archive (`mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py`, free, no account) holds the AFDs of
all five coastal WFOs for every requested month: 2021-25 July-September and 2026-07-01..09-29 (90 monthly
requests, serial, 2 s apart, 0 errors, 129 MB; nothing issued at or after 2026-09-30T00Z; receipts with sha256
in `C:\t\l5\afd\raw\receipts.jsonl`). Parsed products: LOX 4,561, MTR 4,418, OKX 5,675, MFL 3,384, SEW 2,285
(`tools/research/morning_loss/afd_features.py`). A numeric marine-layer depth is stated in 89% of LOX and 51%
of MTR products, almost never at SEW and never at OKX/MFL. Issuance is the WMO header's UTC time; IEM posts
within minutes, so a 5-minute lag is applied.

## Mechanism (stated before scoring)

The L5 diagnosis found a ~0.3-0.85 F centre residual in the coastal markets that no captured product or
per-market debias reproduces. Forecasters' discussions state marine-layer depth, stratus persistence and
burn-off timing, which bound the coastal afternoon high and are not in the NBM/NWS-grid point values.

## Rule

- Markets: san-francisco (MTR), los-angeles (LOX), seattle (SEW), nyc (OKX), miami (MFL). Window: local 07-12.
- Features of the WFO's newest AFD issued <= captured_at_utc − 5 min and <= 18 h old (else all 0 with
  `afd_missing` = 1): marine-layer depth (kft; 0 with `depth_missing` = 1 when not stated), stratus-term rate
  per 1,000 words, late-clearing flag, warm-minus-cool term count (definitions in `afd_features.py`).
- **Candidate `l5c_afd_features`:** mu = v2_mean + r, r = OLS of (y − v2_mean) on per-market intercepts plus
  the six AFD columns, fitted per fold on coastal training snapshots at 07-12 (walk-forward folds of the dev
  scorecard). **Matched control `l5c0_coastal_intercepts`:** the same with intercepts only. Both are MG-1
  verbatim for other markets and hours, and keep MG-1's sigma, floor and availability; candidate − control is
  the AFD increment alone. Code: `l5c_afd_common.py`, `l5c_afd_candidate.py`, `l5c0_intercept_control.py`.
- Scored with `dev_scorecard score --hourly --control-module l5c0_intercept_control.py` and
  `weather.calibration.l5_subset_scores` (adds a "07-12 coastal five" subset row; arm A rows unchanged), also
  against MG-1 as control for reference.

## Decision

- **KEEP** iff on the 07-12 pooled `ALL` row both crossed 95% intervals exclude zero below: candidate − served
  and candidate − matched control. **LEAD** iff not KEEP but the date-clustered candidate − control interval
  excludes zero below. Otherwise **KILL**. The coastal-five subset, per market (SF, LA called out), per hour and
  candidate − MG-1 are reported, not decided. Five market clusters: unpowered; one look.
- A KEEP or LEAD earns a pre-registration on new dates and a capture-design note (an AFD fetch is roll-free
  research; serving it would need a capture change and the roll verdict).

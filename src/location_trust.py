"""Per-location model trust score (0-100).

As markets are added, each location's model has a different amount of validating
data and a different calibration quality. This produces one interpretable score
per location answering: *how much should I trust this location's probabilities?*

It deliberately blends two things, because either alone is misleading:

  * **maturity** -- how many settled days back the estimate. A brand-new
    location (or a bootstrap borrowing another city's model) has no validation,
    so it reads as *Unproven* no matter how confident its outputs look.
  * **calibration** -- when settled days exist, how well the model's stated
    probabilities matched reality (expected calibration error). A location can
    only score high with *both* enough data *and* good calibration.

The score is about *calibration* (are the probabilities honest), not edge -- a
well-calibrated model that still loses to the market is trustworthy in the sense
that its 70% means 70%. Market skill is reported alongside as context.

Registry-driven: scores every market in the registry; new locations appear
automatically and rise as they accumulate clean settled days.

CLI:
  python -m src.location_trust [--out data/backtest/location_trust.json]
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import (
    DEFAULT_DAILY_SUMMARY,
    DEFAULT_SNAPSHOTS_ROOT,
    backtest_tape,
    expected_calibration_error,
    load_daily_summary,
    score_rows,
    settlement_for_tape,
)
from market_config import date_from_event_slug
from market_registry import all_specs, spec_for_slug
from settled_days import discover_settled_folders

# Tunables (documented so the score is explainable).
K_MATURITY = 8       # settled days for the maturity term to reach 0.5
ECE_GOOD = 0.04      # ECE at/below this -> calibration sub-score 1.0
ECE_POOR = 0.16      # ECE at/above this -> calibration sub-score 0.0
PRIOR = 0.15         # trust assigned to an unvalidated (bootstrap) location
MIN_DAYS_FOR_ECE = 2 # need at least this many settled days to trust an ECE

GRADE_BANDS = [(80, "Strong"), (65, "Good"), (45, "Moderate"), (25, "Low"), (0, "Unproven")]
DEFAULT_OUT = Path("data") / "backtest" / "location_trust.json"


def _clamp01(value):
    return max(0.0, min(1.0, value))


def grade_for(score):
    for threshold, label in GRADE_BANDS:
        if score >= threshold:
            return label
    return "Unproven"


def trust_from_components(n_settled, ece):
    """The pure scoring function: (settled-day count, measured ECE) -> score.

    ``ece`` may be None when there are too few settled days to measure it.
    """
    maturity = n_settled / (n_settled + K_MATURITY)
    if n_settled >= MIN_DAYS_FOR_ECE and ece is not None:
        calibration = _clamp01((ECE_POOR - ece) / (ECE_POOR - ECE_GOOD))
    else:
        calibration = None
    measured = calibration if calibration is not None else PRIOR
    # Confidence-discounted calibration: pulled toward the low prior until enough
    # settled days exist, and capped by how well-calibrated it actually is.
    trust01 = maturity * measured + (1 - maturity) * PRIOR
    score = round(100 * trust01)
    return {
        "trust_score": score,
        "grade": grade_for(score),
        "maturity_subscore": round(maturity, 3),
        "calibration_subscore": round(calibration, 3) if calibration is not None else None,
    }


def market_settled_folders(market_id, root, as_of):
    folders = []
    for folder in discover_settled_folders(root, as_of=as_of):
        spec = spec_for_slug(Path(folder).name)
        if spec and spec.id == market_id:
            folders.append(folder)
    return folders


def collect_scored_rows(folders, daily_index):
    rows = []
    for folder in folders:
        tape = Path(folder) / "snapshots_long.csv"
        if not tape.exists():
            continue
        df = pd.read_csv(tape)
        target_date = date_from_event_slug(Path(folder).name)
        bucket, _, _ = settlement_for_tape(df, target_date, daily_index, {})
        scored, _, _, _ = backtest_tape(df, bucket, [0.05], target_date=target_date)
        rows.extend(scored)
    return rows


def _rationale(n_settled, ece, components):
    if n_settled < MIN_DAYS_FOR_ECE:
        return (f"{n_settled} settled day(s) -- not yet validated; bootstrap model. "
                "Score rises as clean settled days accumulate.")
    quality = ("well-calibrated" if components["calibration_subscore"] >= 0.66
               else "moderately calibrated" if components["calibration_subscore"] >= 0.33
               else "poorly calibrated")
    return (f"{n_settled} settled days; ECE {ece:.3f} ({quality}). "
            f"Maturity {components['maturity_subscore']:.2f} of 1.0 -- more days raise confidence.")


def score_market(market_id, root=DEFAULT_SNAPSHOTS_ROOT, daily_summary=DEFAULT_DAILY_SUMMARY, as_of=None):
    daily_index = load_daily_summary(daily_summary)
    folders = market_settled_folders(market_id, root, as_of)
    n_settled = len(folders)
    rows = collect_scored_rows(folders, daily_index)
    ece = expected_calibration_error(rows, "model_probability") if rows else None
    scored = score_rows(rows) if rows else None

    components = trust_from_components(n_settled, ece)
    return {
        "market": market_id,
        **components,
        "settled_days": n_settled,
        "band_rows": len(rows),
        "model_ece": round(ece, 4) if ece is not None else None,
        "model_brier": round(scored["model_brier"], 4) if scored else None,
        "market_brier": round(scored["market_brier"], 4) if scored else None,
        "brier_skill_vs_market": round(scored["brier_skill_score"], 3) if scored else None,
        "rationale": _rationale(n_settled, ece, components),
    }


def score_all_markets(root=DEFAULT_SNAPSHOTS_ROOT, daily_summary=DEFAULT_DAILY_SUMMARY, as_of=None):
    return [score_market(spec.id, root, daily_summary, as_of) for spec in all_specs()]


def main():
    parser = argparse.ArgumentParser(description="Per-location model trust score (0-100).")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--daily-summary", default=str(DEFAULT_DAILY_SUMMARY))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    results = score_all_markets(args.snapshots_root, args.daily_summary)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    print(f"{'Location':10} {'Trust':>6}  {'Grade':10} {'Days':>4} {'ECE':>7} {'vs-mkt':>7}  Why")
    for r in results:
        ece = f"{r['model_ece']:.3f}" if r["model_ece"] is not None else "-"
        skill = f"{r['brier_skill_vs_market']:+.2f}" if r["brier_skill_vs_market"] is not None else "-"
        print(f"{r['market']:10} {r['trust_score']:>5}/100 {r['grade']:10} "
              f"{r['settled_days']:>4} {ece:>7} {skill:>7}  {r['rationale']}")
    print(f"\nWritten to {args.out}")


if __name__ == "__main__":
    main()

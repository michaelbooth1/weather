"""Implementation slice extracted from src/weather/reporting/hourly_model_performance.py."""

from weather.reporting.hourly.hourly_model_render import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def write_hour_csv(rows, path=DEFAULT_CSV_OUT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def write_outputs(
    payload,
    json_out=DEFAULT_JSON_OUT,
    report_out=DEFAULT_REPORT_OUT,
    csv_out=DEFAULT_CSV_OUT,
):
    json_out = Path(json_out)
    report_out = Path(report_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_out.write_text(render_report(payload), encoding="utf-8")
    csv_path = write_hour_csv(payload.get("by_hour") or [], csv_out)
    return json_out, report_out, csv_path


def build_parser():
    parser = argparse.ArgumentParser(description="Audit settlement-scored model performance by local capture hour.")
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument(
        "--context-root",
        default=str(DEFAULT_BACKTEST_ROOT),
        help="Directory containing companion analysis JSON files used for variable-weight context.",
    )
    parser.add_argument(
        "--quality-grades",
        default=",".join(DEFAULT_QUALITY_GRADES),
        help="Comma-separated settlement quality grades to include.",
    )
    parser.add_argument(
        "--strict-quality-grades-only",
        action="store_true",
        help="Do not include labels that are promotion-countable but outside --quality-grades.",
    )
    parser.add_argument("--markets", default="", help="Comma-separated market IDs to include.")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--min-rows", type=int, default=DEFAULT_MIN_ROWS)
    parser.add_argument("--top-hours", type=int, default=DEFAULT_TOP_HOURS)
    parser.add_argument("--min-regime-market-days", type=int, default=DEFAULT_MIN_REGIME_MARKET_DAYS)
    parser.add_argument(
        "--early-brier-regression-tolerance",
        type=float,
        default=DEFAULT_EARLY_BRIER_REGRESSION_TOLERANCE,
    )
    parser.add_argument(
        "--early-logloss-regression-tolerance",
        type=float,
        default=DEFAULT_EARLY_LOGLOSS_REGRESSION_TOLERANCE,
    )
    parser.add_argument("--early-ece-max", type=float, default=DEFAULT_EARLY_ECE_MAX)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--csv-out", default=str(DEFAULT_CSV_OUT))
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    quality_grades = parse_quality_grades(args.quality_grades)
    markets = parse_csv_values(args.markets)
    payload = build_hourly_performance(
        labels_csv=args.labels_csv,
        snapshots_root=args.snapshots_root,
        context_root=args.context_root,
        quality_grades=quality_grades,
        include_promotion_countable_labels=not args.strict_quality_grades_only,
        markets=markets,
        start_date=args.start_date,
        end_date=args.end_date,
        min_rows=args.min_rows,
        top_hours=args.top_hours,
        min_regime_market_days=args.min_regime_market_days,
        early_brier_regression_tolerance=args.early_brier_regression_tolerance,
        early_logloss_regression_tolerance=args.early_logloss_regression_tolerance,
        early_ece_max=args.early_ece_max,
    )
    json_out, report_out, csv_out = write_outputs(
        payload,
        json_out=args.json_out,
        report_out=args.report_out,
        csv_out=args.csv_out,
    )
    print(f"Wrote {relative_to_repo(json_out)}")
    print(f"Wrote {relative_to_repo(report_out)}")
    print(f"Wrote {relative_to_repo(csv_out)}")
    overall = payload.get("overall", {}).get("hourly_checkpoint") or {}
    if overall:
        print(
            "Hourly checkpoint model Brier "
            f"{overall['model_brier']:.4f} vs market {overall['market_brier']:.4f} "
            f"(delta {overall['brier_delta']:+.4f})"
        )
    if payload.get("best_hours"):
        print("Best hours: " + ", ".join(row["hour_label"] for row in payload["best_hours"]))
    if payload.get("worst_hours"):
        print("Worst hours: " + ", ".join(row["hour_label"] for row in payload["worst_hours"]))
    gate = payload.get("hourly_performance_gate") or {}
    if gate:
        print(f"Hourly performance gate: {gate.get('status')} ({gate.get('blocker_count', 0)} blocker(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]

"""Implementation slice extracted from src/weather/reporting/promotion_refresh.py."""

from weather.reporting.promotion.orchestration import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def build_parser():
    parser = argparse.ArgumentParser(
        description="Refresh promotion corpus, trust, pooled replay, and family promotion decisions."
    )
    parser.add_argument("folders", nargs="*", help="Optional snapshot folders; defaults to discovered settled folders.")
    parser.add_argument(
        "--output-root",
        default="",
        help=(
            "Canonical root for every promotion-derived output. When set, "
            "configured output paths are replaced with paths below this root "
            "before any promotion work starts."
        ),
    )
    parser.add_argument(
        "--frozen-corpus",
        default="",
        help="Identity-pinned promotion corpus to consume without rebuilding live folders.",
    )
    parser.add_argument(
        "--frozen-corpus-sha256",
        default="",
        help="Required exact file SHA-256 for --frozen-corpus.",
    )
    parser.add_argument(
        "--frozen-corpus-hash",
        default="",
        help="Required exact semantic corpus hash for --frozen-corpus.",
    )
    parser.add_argument(
        "--family-unit",
        default=DEFAULT_FAMILY_UNIT,
        choices=["F", "C", "all"],
        help="Native-unit family to evaluate; C is the inactive Toronto candidate lane.",
    )
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--quality-grades", default=",".join(DEFAULT_QUALITY_GRADES))
    parser.add_argument("--grade-only-admission", action="store_true",
                        help="Admit only the listed quality grades; do not admit partial days "
                             "whose labels are promotion_countable (item 319 material coverage).")
    parser.add_argument("--include-reconstructed", action="store_true")
    parser.add_argument("--allow-unsettled", action="store_true")
    parser.add_argument("--min-snapshots", type=int, default=1)
    parser.add_argument("--corpus-out", default=str(DEFAULT_CORPUS))
    parser.add_argument("--trust-out", default=str(DEFAULT_TRUST_OUT))
    parser.add_argument("--artifact", default=str(DEFAULT_BAND_ARTIFACT))
    parser.add_argument("--variant-registry", default=str(DEFAULT_VARIANT_REGISTRY_PATH))
    parser.add_argument("--candidate-report", default=str(DEFAULT_CANDIDATE_REPORT))
    parser.add_argument("--candidate-json", default=str(DEFAULT_CANDIDATE_JSON))
    parser.add_argument(
        "--precomputed-candidate-json",
        default="",
        help="Use an existing pooled-candidate replay JSON instead of rerunning candidate replay.",
    )
    parser.add_argument(
        "--precomputed-candidate-report",
        default="",
        help="Optional Markdown report path paired with --precomputed-candidate-json.",
    )
    parser.add_argument("--current-replay-report", default=str(DEFAULT_CURRENT_REPLAY_REPORT))
    parser.add_argument("--serving-gauntlet-report", default=str(DEFAULT_SERVING_GAUNTLET_REPORT))
    parser.add_argument("--serving-replay-report", default=str(DEFAULT_SERVING_REPLAY_REPORT))
    parser.add_argument("--hourly-performance-report", default=str(DEFAULT_HOURLY_PERFORMANCE))
    parser.add_argument(
        "--candidate-hourly-performance-report",
        default=str(DEFAULT_CANDIDATE_HOURLY_PERFORMANCE),
        help="Optional candidate-hourly JSON that can mitigate a current-serving hourly gate for this candidate.",
    )
    parser.add_argument("--ten-minute-performance-report", default=str(DEFAULT_TEN_MINUTE_PERFORMANCE))
    parser.add_argument(
        "--candidate-ten-minute-performance-report",
        default=str(DEFAULT_CANDIDATE_TEN_MINUTE_PERFORMANCE),
        help="Optional candidate 10-minute JSON that can mitigate a current-serving weak-slot gate for this candidate.",
    )
    parser.add_argument("--source-family-inventory", default=str(DEFAULT_SOURCE_FAMILY_INVENTORY))
    parser.add_argument("--physical-feature-family-ratchet", default=str(DEFAULT_PHYSICAL_FEATURE_FAMILY_RATCHET))
    parser.add_argument("--fleet-observability-report", default=str(DEFAULT_FLEET_OBSERVABILITY))
    parser.add_argument("--settled-day-freshness-report", default=str(DEFAULT_SETTLED_DAY_FRESHNESS))
    parser.add_argument("--data-layer-audit-report", default=str(DEFAULT_DATA_LAYER_AUDIT))
    parser.add_argument("--ingest-quality-gate-report", default=str(DEFAULT_INGEST_QUALITY_GATE))
    parser.add_argument("--daily-learning-report", default=str(DEFAULT_DAILY_LEARNING))
    parser.add_argument(
        "--per-location-artifact-quarantine-report",
        default=str(DEFAULT_PER_LOCATION_ARTIFACT_QUARANTINE),
    )
    parser.add_argument("--forecast-tracker", default=str(DEFAULT_FORECAST_TRACKER))
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--skip-serving-gauntlet", action="store_true")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--promotion-allowlist-out", default=str(DEFAULT_PROMOTION_ALLOWLIST))
    parser.add_argument("--incomplete-manifest", default=str(DEFAULT_INCOMPLETE_MANIFEST))
    parser.add_argument("--current-tol", type=float, default=0.003)
    parser.add_argument("--tol", type=float, default=0.003)
    parser.add_argument("--market-tol", type=float, default=0.003)
    parser.add_argument("--min-days", type=int, default=2)
    parser.add_argument("--min-trust", type=int, default=25)
    parser.add_argument("--max-fidelity-l1", type=float, default=FIDELITY_FAITHFUL_L1)
    parser.add_argument("--clob-max-age-seconds", type=float, default=180.0)
    parser.add_argument(
        "--replay-cache",
        default="read_write",
        choices=["read_write", "write_only", "off"],
        help="Per-market-day replay cache mode for candidate validation.",
    )
    parser.add_argument(
        "--replay-cache-root",
        default="",
        help="Replay cache root. Defaults to <corpus parent>/replay_cache.",
    )
    parser.add_argument("--disable-replay-cache-sentinel", action="store_true")
    parser.add_argument("--casebook", default=str(DEFAULT_CASEBOOK))
    parser.add_argument("--candidate-variant-out", default=None,
                        help="Item-69-compatible candidate variant CSV. Defaults to the active registry contract when available.")
    parser.add_argument("--candidate-variant-id", default=None)
    parser.add_argument("--candidate-variant-family", default=None)
    parser.add_argument("--candidate-variant-uses-market-features", action="store_true")
    parser.add_argument("--candidate-variant-control", action="store_true")
    parser.add_argument("--disable-candidate-variant-export", action="store_true",
                        help="Disable registry-default candidate variant export.")
    parser.add_argument("--min-artifact-free-bytes", type=int, default=DEFAULT_VARIANT_EXPORT_MIN_FREE_BYTES,
                        help="Require this much free disk headroom after estimated variant CSV exports. Use 0 to disable.")
    parser.add_argument(
        "--extra-location-transfer-report",
        default="",
        help="Optional no-market target-vs-extra transfer JSON to surface as a promotion blocker.",
    )
    parser.add_argument("--microstructure-artifact", default=str(DEFAULT_MICROSTRUCTURE_ARTIFACT))
    parser.add_argument("--microstructure-min-train-rows", type=int, default=500)
    parser.add_argument("--skip-microstructure-overlay", action="store_true")
    parser.add_argument("--require-exact-identity", action="store_true")
    parser.add_argument("--require-all-markets", action="store_true")
    parser.add_argument("--fail-on-block", action="store_true")
    parser.add_argument(
        "--heavy-analysis-max-age-days",
        type=float,
        default=7.0,
        help=(
            "Carry forward the serving gauntlet and heavy candidate diagnostics "
            "(microstructure/ablation/bridge) when the relevant artifact hash is "
            "unchanged, the prior verdict allows it, and the prior run is at most "
            "this many days old. 0 disables carry-forward."
        ),
    )
    parser.add_argument(
        "--force-heavy-analysis",
        action="store_true",
        help="Recompute the serving gauntlet and heavy diagnostics regardless of carry-forward eligibility.",
    )
    parser.add_argument("--long-job-state", default=str(DEFAULT_LONG_JOB_STATE_PATH))
    parser.add_argument("--long-job-lock", default=str(DEFAULT_LONG_JOB_LOCK_PATH))
    parser.add_argument("--long-job-priority", default="below_normal", choices=["normal", "below_normal", "idle"])
    parser.add_argument("--disable-long-job-guard", action="store_true")
    parser.add_argument("--force-long-job-lock", action="store_true")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.replay_cache_root == "":
        args.replay_cache_root = None
    payload, out_path, report_path = run_promotion_refresh(args)
    decisions = payload.get("decisions") or {}
    print(
        "Promotion refresh: "
        f"{len(decisions.get('promote_markets') or [])} promote, "
        f"{len(decisions.get('shadow_markets') or [])} shadow, "
        f"{len(decisions.get('blocked_markets') or [])} blocked"
    )
    print(f"JSON written to {out_path}")
    print(f"Report written to {report_path}")
    readiness = payload.get("readiness") or {}
    readiness_blocked = any(
        row.get("severity") == "block"
        for row in readiness.get("blockers") or []
    )
    if args.fail_on_block and (decisions.get("blocked_markets") or readiness_blocked):
        sys.exit(1)


if __name__ == "__main__":
    main()

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]

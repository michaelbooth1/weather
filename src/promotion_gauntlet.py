"""Promotion gauntlet for model changes.

The gauntlet consumes a pinned promotion corpus, replays the current code over
those exact inputs, and decides which markets are promotable, shadow-only, or
blocked. It is intentionally stricter than a research backtest: corpus pin
warnings and replay-fidelity failures are hard stops.
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import fmt_num, fmt_pct, fmt_signed, markdown_table
from location_trust import score_all_markets
from market_registry import REGISTRY
from promotion_corpus import DEFAULT_OUT as DEFAULT_CORPUS, folders_from_manifest, load_manifest
from replay_backtest import (
    DEFAULT_BASELINE,
    FIDELITY_FAITHFUL_L1,
    comparison,
    fidelity_summary,
    gate,
    grouped_comparison,
    run_replay_backtest,
)
from settled_days import DEFAULT_SNAPSHOTS_ROOT

DEFAULT_OUT = Path("data") / "backtest" / "promotion_gauntlet_report.md"
DEFAULT_REPLAY_REPORT = Path("data") / "backtest" / "promotion_replay_report.md"
DEFAULT_FORECAST_TRACKER = Path("data") / "backtest" / "forecast_vs_realized.json"


def _forecast_tracker_status(path):
    path = Path(path)
    if not path.exists():
        return {
            "status": "WARN",
            "message": f"forecast tracker missing at {path}",
            "path": str(path),
        }
    count = None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            count = len(payload)
        elif isinstance(payload, dict):
            for key in ("rows", "records", "items", "markets"):
                if isinstance(payload.get(key), list):
                    count = len(payload[key])
                    break
    except (OSError, json.JSONDecodeError):
        return {
            "status": "WARN",
            "message": f"forecast tracker exists but is unreadable at {path}",
            "path": str(path),
        }
    suffix = f"; {count} record(s)" if count is not None else ""
    return {
        "status": "INFO",
        "message": f"forecast tracker present at {path}{suffix}",
        "path": str(path),
    }


def _rows_by_market(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get("market_id")].append(row)
    return grouped


def _days_by_market(days):
    grouped = defaultdict(list)
    for day in days:
        grouped[day.get("market_id")].append(day)
    return grouped


def _fidelity_by_market(fidelity_rows):
    grouped = defaultdict(list)
    for row in fidelity_rows:
        grouped[row.get("market_id")].append(row)
    return {
        market_id: fidelity_summary(rows)
        for market_id, rows in grouped.items()
    }


def _baseline_gate_status(results, baseline_path, tol):
    if not baseline_path:
        aggregate = results.get("aggregate") or {}
        effect = aggregate.get("code_effect")
        if effect is None:
            return False, "missing aggregate code-effect"
        passed = effect <= tol
        verdict = "PASS" if passed else "FAIL"
        return passed, f"{verdict}: code effect {effect:+.4f} vs tolerance {tol:.4f}"
    passed, message = gate(baseline_path, results, tol)
    return passed, message


def _fidelity_gate_status(fidelity, max_l1, require_exact_identity):
    same_n = fidelity.get("same_identity_n") or 0
    if same_n:
        max_seen = fidelity.get("same_identity_max_l1")
        passed = max_seen is not None and max_seen <= max_l1
        verdict = "PASS" if passed else "FAIL"
        return passed, (
            f"{verdict}: {same_n} exact-identity snapshot(s), "
            f"max L1 {max_seen:.5f} vs limit {max_l1:.5f}"
        )
    if require_exact_identity:
        return False, "FAIL: no exact-identity snapshots in corpus"
    return True, "WARN: no exact-identity snapshots yet; legacy corpus cannot run the strict canary"


def _market_verdict(
    market_id,
    comp,
    days,
    fidelity,
    trust,
    code_tol,
    market_tol,
    min_days,
    min_trust,
    max_fidelity_l1,
    require_all_markets,
):
    reasons = []
    if not comp:
        return "BLOCK", ["no replay rows scored"]

    day_count = len([day for day in days if day.get("rows", 0) > 0])
    code_effect = comp.get("code_effect")
    if code_effect is None or code_effect > code_tol:
        reasons.append(f"code regression {code_effect:+.4f} > {code_tol:.4f}" if code_effect is not None else "missing code effect")

    same_n = fidelity.get("same_identity_n") or 0
    max_l1 = fidelity.get("same_identity_max_l1")
    if same_n and (max_l1 is None or max_l1 > max_fidelity_l1):
        reasons.append("market fidelity canary failed")

    if reasons:
        return "BLOCK", reasons

    shadow = []
    if day_count < min_days:
        shadow.append(f"{day_count} settled day(s) < {min_days}")
    replayed = comp.get("replayed_brier")
    market = comp.get("market_brier")
    if replayed is None or market is None or replayed > market + market_tol:
        shadow.append("not proven better than market on pinned rows")
    trust_score = (trust or {}).get("trust_score")
    if trust_score is None or trust_score < min_trust:
        shadow.append(f"trust {trust_score if trust_score is not None else '-'} < {min_trust}")

    if shadow and require_all_markets:
        return "BLOCK", shadow
    if shadow:
        return "SHADOW", shadow
    return "PASS", ["meets replay, market-skill, sample, and trust gates"]


def _per_market(results, trust_by_market, args):
    rows_by_market = _rows_by_market(results.get("all_rows") or [])
    days_by_market = _days_by_market(results.get("days") or [])
    fid_by_market = _fidelity_by_market(results.get("fidelity_rows") or [])
    corpus_markets = set(((results.get("promotion_corpus") or {}).get("by_market") or {}).keys())
    markets = sorted(set(rows_by_market) | set(days_by_market) | corpus_markets)
    output = []
    for market_id in markets:
        if market_id is None:
            continue
        comp = comparison(rows_by_market.get(market_id) or [])
        days = days_by_market.get(market_id) or []
        fid = fid_by_market.get(market_id) or {}
        trust = trust_by_market.get(market_id) or {}
        verdict, reasons = _market_verdict(
            market_id,
            comp,
            days,
            fid,
            trust,
            args.tol,
            args.market_tol,
            args.min_days,
            args.min_trust,
            args.max_fidelity_l1,
            args.require_all_markets,
        )
        output.append({
            "market_id": market_id,
            "city": REGISTRY[market_id].city_label if market_id in REGISTRY else market_id,
            "days": len([day for day in days if day.get("rows", 0) > 0]),
            "snapshots": sum(int(day.get("snapshots_scored") or 0) for day in days),
            "rows": (comp or {}).get("n", 0),
            "comparison": comp,
            "fidelity": fid,
            "trust": trust,
            "verdict": verdict,
            "reason": "; ".join(reasons),
        })
    return output


def _overall_verdict(corpus_ok, fidelity_ok, baseline_ok, market_rows):
    blockers = [row for row in market_rows if row["verdict"] == "BLOCK"]
    passes = [row for row in market_rows if row["verdict"] == "PASS"]
    shadows = [row for row in market_rows if row["verdict"] == "SHADOW"]
    if not corpus_ok or not fidelity_ok or not baseline_ok:
        return "BLOCK"
    if blockers and passes:
        return "PARTIAL_PASS"
    if blockers:
        return "BLOCK"
    if shadows:
        return "PASS_WITH_SHADOWS"
    if passes:
        return "PASS"
    return "BLOCK"


def _slice_table(rows, group_key, limit=12):
    items = grouped_comparison(rows, group_key)
    items = sorted(
        items,
        key=lambda item: (
            (item.get("code_effect") or 0.0) * (item.get("n") or 0),
            item.get("code_effect") or 0.0,
        ),
        reverse=True,
    )
    return items[:limit]


def _decomposition(results, market_rows):
    rows = results.get("all_rows") or []
    blockers = {row["market_id"] for row in market_rows if row["verdict"] == "BLOCK"}
    output = {
        "overall": {
            "by_market": _slice_table(rows, "market_id"),
            "by_hour": _slice_table(rows, "cutoff_hour"),
            "by_bin_type": _slice_table(rows, "bin_type"),
            "by_forecast_gap": _slice_table(rows, "feature_forecast_gap_bucket"),
            "by_live_reading_gap": _slice_table(rows, "feature_live_reading_gap_bucket"),
            "by_settlement_distance": _slice_table(rows, "settlement_distance_bucket"),
        },
        "blocking_markets": {},
    }
    for market_id in sorted(blockers):
        market_rows_only = [row for row in rows if row.get("market_id") == market_id]
        output["blocking_markets"][market_id] = {
            "by_hour": _slice_table(market_rows_only, "cutoff_hour", limit=6),
            "by_bin_type": _slice_table(market_rows_only, "bin_type", limit=6),
            "by_forecast_gap": _slice_table(market_rows_only, "feature_forecast_gap_bucket", limit=6),
            "by_live_reading_gap": _slice_table(market_rows_only, "feature_live_reading_gap_bucket", limit=6),
            "by_settlement_distance": _slice_table(market_rows_only, "settlement_distance_bucket", limit=6),
        }
    return output


def run_promotion_gauntlet(args):
    manifest = load_manifest(args.corpus)
    folders = [str(folder) for folder in folders_from_manifest(manifest, args.snapshots_root)]
    results = run_replay_backtest(
        folders,
        daily_summary_path=None,
        overrides={},
        out_path=args.replay_report,
        include_reconstructed=manifest.get("include_reconstructed", False),
        write=bool(args.replay_report),
        corpus_manifest=manifest,
    )

    trust_rows = score_all_markets(
        root=args.snapshots_root,
        as_of=manifest.get("as_of"),
    )
    trust_by_market = {row["market"]: row for row in trust_rows}
    market_rows = _per_market(results, trust_by_market, args)
    decomposition = _decomposition(results, market_rows)

    corpus_ok = not results.get("corpus_warnings")
    fidelity_ok, fidelity_message = _fidelity_gate_status(
        results.get("fidelity") or {},
        args.max_fidelity_l1,
        args.require_exact_identity,
    )
    baseline_path = None if args.no_baseline else args.baseline
    baseline_ok, baseline_message = _baseline_gate_status(results, baseline_path, args.tol)
    forecast_status = _forecast_tracker_status(args.forecast_tracker)
    overall = _overall_verdict(corpus_ok, fidelity_ok, baseline_ok, market_rows)

    report = {
        "generated_at": datetime.now().isoformat(),
        "verdict": overall,
        "corpus_ok": corpus_ok,
        "fidelity_ok": fidelity_ok,
        "fidelity_message": fidelity_message,
        "baseline_ok": baseline_ok,
        "baseline_message": baseline_message,
        "forecast_tracker": forecast_status,
        "results": results,
        "market_rows": market_rows,
        "decomposition": decomposition,
    }
    write_report(report, args.out)
    return report


def _market_table_rows(rows):
    output = []
    for row in rows:
        comp = row.get("comparison") or {}
        fid = row.get("fidelity") or {}
        trust = row.get("trust") or {}
        output.append([
            row["market_id"],
            row.get("days", 0),
            row.get("snapshots", 0),
            row.get("rows", 0),
            fmt_num(comp.get("replayed_brier")),
            fmt_num(comp.get("recorded_brier")),
            fmt_num(comp.get("market_brier")),
            fmt_signed(comp.get("code_effect")),
            fmt_signed(comp.get("replayed_skill"), 3),
            f"{trust.get('trust_score', '-')}/{100} {trust.get('grade', '')}".strip(),
            fid.get("same_identity_n", 0),
            row["verdict"],
            row["reason"],
        ])
    return output


def _market_list(rows, verdict):
    return ", ".join(row["market_id"] for row in rows if row["verdict"] == verdict) or "-"


def _slice_markdown(title, items):
    lines = ["", f"### {title}", ""]
    lines += markdown_table(
        ["Group", "Rows", "Replayed Brier", "Recorded Brier", "Market Brier", "Code Effect", "Skill"],
        [
            [
                str(item.get("group")) if item.get("group") not in (None, "") else "-",
                item.get("n", "-"),
                fmt_num(item.get("replayed_brier")),
                fmt_num(item.get("recorded_brier")),
                fmt_num(item.get("market_brier")),
                fmt_signed(item.get("code_effect")),
                fmt_signed(item.get("replayed_skill"), 3),
            ]
            for item in items
        ],
    )
    return lines


def write_report(report, out_path):
    results = report["results"]
    corpus = results.get("promotion_corpus") or {}
    fid = results.get("fidelity") or {}
    aggregate = results.get("aggregate") or {}
    lines = [
        "# Promotion Gauntlet",
        "",
        f"Generated: {report['generated_at']}",
        f"Decision: **{report['verdict']}**",
        "",
        "## Gate Summary",
        "",
    ]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [
            ["Corpus pin", "PASS" if report["corpus_ok"] else "FAIL",
             "all pinned tape/replay hashes matched" if report["corpus_ok"] else "corpus pin warnings present"],
            ["Replay fidelity", "PASS" if report["fidelity_ok"] else "FAIL", report["fidelity_message"]],
            ["Regression", "PASS" if report["baseline_ok"] else "FAIL", report["baseline_message"]],
            ["Forecast tracker", report["forecast_tracker"]["status"], report["forecast_tracker"]["message"]],
        ],
    )
    lines += [
        "",
        "## Corpus",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Hash", corpus.get("corpus_hash") or "-"],
            ["Path", corpus.get("path") or "-"],
            ["As of", corpus.get("as_of") or "-"],
            ["Market days", corpus.get("market_day_count") or 0],
            ["Pinned snapshots", corpus.get("snapshot_count") or 0],
            ["Band rows", corpus.get("band_row_count") or 0],
            ["Quality grades", ", ".join(corpus.get("quality_grades") or []) or "-"],
        ],
    )
    lines += [
        "",
        "## Aggregate Replay",
        "",
    ]
    lines += markdown_table(
        ["Rows", "Replayed Brier", "Recorded Brier", "Market Brier", "Code Effect", "Skill"],
        [[
            aggregate.get("n", 0),
            fmt_num(aggregate.get("replayed_brier")),
            fmt_num(aggregate.get("recorded_brier")),
            fmt_num(aggregate.get("market_brier")),
            fmt_signed(aggregate.get("code_effect")),
            fmt_signed(aggregate.get("replayed_skill"), 3),
        ]],
    )
    lines += [
        "",
        "## Fidelity Canary",
        "",
    ]
    lines += markdown_table(
        ["Cohort", "Snapshots", "Mean L1", "Max L1"],
        [
            ["Same replay identity", fid.get("same_identity_n", 0),
             fmt_num(fid.get("same_identity_mean_l1")), fmt_num(fid.get("same_identity_max_l1"))],
            ["Legacy same label", fid.get("legacy_same_version_n", 0),
             fmt_num(fid.get("legacy_same_version_mean_l1")), fmt_num(fid.get("legacy_same_version_max_l1"))],
            ["Changed identity", fid.get("changed_version_n", 0),
             fmt_num(fid.get("changed_version_mean_l1")), fmt_num(fid.get("changed_version_max_l1"))],
        ],
    )
    lines += [
        "",
        "## Per-Market Promotion",
        "",
    ]
    lines += markdown_table(
        ["Action", "Markets"],
        [
            ["Promote", _market_list(report["market_rows"], "PASS")],
            ["Shadow", _market_list(report["market_rows"], "SHADOW")],
            ["Blocked", _market_list(report["market_rows"], "BLOCK")],
        ],
    )
    lines += ["", "### Market Details", ""]
    lines += markdown_table(
        [
            "Market", "Days", "Snaps", "Rows", "Replayed Brier",
            "Recorded Brier", "Market Brier", "Code Effect", "Skill",
            "Trust", "Exact ID", "Verdict", "Reason",
        ],
        _market_table_rows(report["market_rows"]),
    )

    decomp = report.get("decomposition") or {}
    overall = decomp.get("overall") or {}
    lines += [
        "",
        "## Failure Decomposition",
        "",
        "Slices are sorted by positive code-effect contribution "
        "(worse replayed-vs-recorded movement first).",
    ]
    lines += _slice_markdown("Overall By Market", overall.get("by_market") or [])
    lines += _slice_markdown("Overall By Capture Hour", overall.get("by_hour") or [])
    lines += _slice_markdown("Overall By Bin Type", overall.get("by_bin_type") or [])
    lines += _slice_markdown("Overall By Forecast Gap", overall.get("by_forecast_gap") or [])
    lines += _slice_markdown("Overall By Live Reading Gap", overall.get("by_live_reading_gap") or [])
    lines += _slice_markdown("Overall By Settlement Distance", overall.get("by_settlement_distance") or [])

    blocking = decomp.get("blocking_markets") or {}
    if blocking:
        lines += ["", "## Blocking Market Drilldowns", ""]
        for market_id, slices in sorted(blocking.items()):
            lines += ["", f"### {market_id}", ""]
            for label, key in [
                ("Hour", "by_hour"),
                ("Bin Type", "by_bin_type"),
                ("Forecast Gap", "by_forecast_gap"),
                ("Live Reading Gap", "by_live_reading_gap"),
                ("Settlement Distance", "by_settlement_distance"),
            ]:
                lines += _slice_markdown(label, slices.get(key) or [])
    warnings = results.get("corpus_warnings") or []
    if warnings:
        lines += ["", "## Corpus Pin Warnings", ""]
        lines += [f"- {warning}" for warning in warnings]

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Run the pinned promotion gauntlet.")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--no-baseline", action="store_true",
                        help="Gate against recorded incumbent probabilities instead of a saved baseline.")
    parser.add_argument("--forecast-tracker", default=str(DEFAULT_FORECAST_TRACKER))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--replay-report", default=str(DEFAULT_REPLAY_REPORT),
                        help="Detailed replay report path. Empty string disables it.")
    parser.add_argument("--tol", type=float, default=0.003,
                        help="Allowed replayed-Brier regression vs baseline/recorded.")
    parser.add_argument("--market-tol", type=float, default=0.003,
                        help="Allowed Brier gap versus Polymarket before a market is shadow-only.")
    parser.add_argument("--min-days", type=int, default=2)
    parser.add_argument("--min-trust", type=int, default=25)
    parser.add_argument("--max-fidelity-l1", type=float, default=FIDELITY_FAITHFUL_L1)
    parser.add_argument("--require-exact-identity", action="store_true",
                        help="Fail if the corpus has no exact replay-identity canary rows.")
    parser.add_argument("--require-all-markets", action="store_true",
                        help="Treat shadow-only markets as blockers.")
    args = parser.parse_args()
    if args.replay_report == "":
        args.replay_report = None

    report = run_promotion_gauntlet(args)
    print(f"Promotion gauntlet: {report['verdict']}")
    print(f"Report written to {args.out}")
    if args.replay_report:
        print(f"Detailed replay report written to {args.replay_report}")
    if report["verdict"] == "BLOCK":
        sys.exit(1)


if __name__ == "__main__":
    main()

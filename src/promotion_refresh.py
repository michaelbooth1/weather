"""End-to-end promotion refresh for family-pooled candidates.

This is the Item 33/37 bridge: when more settled market-days appear, one
command refreshes the pinned promotion corpus, location trust, pooled candidate
replay, and per-market promotion decisions.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import fmt_num, fmt_signed, markdown_table
from location_trust import DEFAULT_OUT as DEFAULT_TRUST_OUT
from location_trust import score_all_markets
from market_registry import all_specs
from pooled_candidate_replay import run_pooled_candidate_replay
from pooled_feature_model import DEFAULT_BAND_ARTIFACT
from promotion_corpus import (
    DEFAULT_OUT as DEFAULT_CORPUS,
    DEFAULT_QUALITY_GRADES,
    build_promotion_corpus,
    parse_quality_grades,
    write_manifest,
)
from promotion_gauntlet import DEFAULT_FORECAST_TRACKER, run_promotion_gauntlet
from replay_backtest import DEFAULT_BASELINE, FIDELITY_FAITHFUL_L1
from settled_days import DEFAULT_SNAPSHOTS_ROOT


SCHEMA_VERSION = "promotion_refresh_v0.1"
DEFAULT_OUT = Path("data") / "backtest" / "f_family_promotion_refresh.json"
DEFAULT_REPORT = Path("data") / "backtest" / "f_family_promotion_refresh_report.md"
DEFAULT_CANDIDATE_REPORT = Path("data") / "backtest" / "pooled_candidate_replay_latest_report.md"
DEFAULT_CANDIDATE_JSON = Path("data") / "backtest" / "pooled_candidate_replay_latest.json"
DEFAULT_CURRENT_REPLAY_REPORT = Path("data") / "backtest" / "pooled_candidate_current_replay_latest_report.md"
DEFAULT_SERVING_GAUNTLET_REPORT = Path("data") / "backtest" / "promotion_gauntlet_latest_report.md"
DEFAULT_SERVING_REPLAY_REPORT = Path("data") / "backtest" / "promotion_replay_latest_report.md"
DEFAULT_FAMILY_UNIT = "F"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _as_path(value):
    return str(Path(value)) if value is not None else None


def _family_specs(family_unit=DEFAULT_FAMILY_UNIT, specs=None):
    source = list(specs) if specs is not None else list(all_specs())
    return [spec for spec in source if getattr(spec, "display_unit", None) == family_unit]


def _manifest_summary(manifest, corpus_path):
    summary = manifest.get("summary") or {}
    return {
        "path": str(corpus_path),
        "schema_version": manifest.get("schema_version"),
        "corpus_hash": manifest.get("corpus_hash"),
        "as_of": manifest.get("as_of"),
        "market_day_count": summary.get("market_day_count", 0),
        "snapshot_count": summary.get("snapshot_count", 0),
        "band_row_count": summary.get("band_row_count", 0),
        "identity_record_count": summary.get("identity_record_count", 0),
        "by_market": summary.get("by_market") or {},
        "quality_grades": manifest.get("quality_grades") or [],
        "skipped_count": len(manifest.get("skipped") or []),
        "skipped_by_reason": dict(sorted(
            Counter(item.get("reason") or "unknown" for item in manifest.get("skipped") or []).items()
        )),
    }


def _trust_summary(trust_rows, trust_path, family_ids):
    trust_by_market = {row.get("market"): row for row in trust_rows if row.get("market")}
    family_scores = [
        trust_by_market.get(market_id, {}).get("trust_score")
        for market_id in family_ids
    ]
    family_scores = [score for score in family_scores if score is not None]
    return {
        "path": str(trust_path),
        "market_count": len(trust_rows),
        "family_market_count": len(family_ids),
        "family_min_trust": min(family_scores) if family_scores else None,
        "family_max_trust": max(family_scores) if family_scores else None,
        "by_market": trust_by_market,
    }


def _candidate_summary(candidate_report, candidate_json_path, candidate_report_path):
    aggregate = candidate_report.get("aggregate") or {}
    return {
        "json_path": _as_path(candidate_json_path),
        "report_path": _as_path(candidate_report_path),
        "verdict": candidate_report.get("verdict"),
        "candidate_market_verdict": candidate_report.get("candidate_market_verdict"),
        "cutover_decision": candidate_report.get("cutover_decision"),
        "artifact": candidate_report.get("artifact") or {},
        "corpus": candidate_report.get("corpus") or {},
        "coverage": candidate_report.get("coverage") or {},
        "replay_gate": candidate_report.get("replay_gate") or {},
        "aggregate": {
            "rows": aggregate.get("n", 0),
            "candidate_brier": aggregate.get("candidate_brier"),
            "current_brier": aggregate.get("current_brier"),
            "recorded_brier": aggregate.get("recorded_brier"),
            "market_brier": aggregate.get("market_brier"),
            "delta_vs_current": aggregate.get("delta_vs_current"),
            "delta_vs_market": aggregate.get("delta_vs_market"),
            "candidate_skill": aggregate.get("candidate_skill"),
        },
    }


def _serving_gauntlet_summary(report, report_path, replay_report_path):
    if not report:
        return None
    return {
        "report_path": _as_path(report_path),
        "replay_report_path": _as_path(replay_report_path),
        "verdict": report.get("verdict"),
        "corpus_ok": report.get("corpus_ok"),
        "fidelity_ok": report.get("fidelity_ok"),
        "baseline_ok": report.get("baseline_ok"),
        "forecast_tracker": report.get("forecast_tracker") or {},
        "market_rows": report.get("market_rows") or [],
    }


def _comparison_metrics(comp):
    comp = comp or {}
    return {
        "rows": comp.get("n", 0),
        "candidate_brier": comp.get("candidate_brier"),
        "current_brier": comp.get("current_brier"),
        "recorded_brier": comp.get("recorded_brier"),
        "market_brier": comp.get("market_brier"),
        "delta_vs_current": comp.get("delta_vs_current"),
        "delta_vs_market": comp.get("delta_vs_market"),
        "candidate_skill": comp.get("candidate_skill"),
        "candidate_ece": comp.get("candidate_ece"),
        "base_rate": comp.get("base_rate"),
    }


def _action_for_verdict(verdict):
    if verdict == "PASS":
        return "PROMOTE_CANDIDATE"
    if verdict == "BLOCK":
        return "BLOCK_CANDIDATE"
    return "KEEP_SHADOW"


def build_family_decisions(
    manifest,
    trust_rows,
    candidate_report,
    family_unit=DEFAULT_FAMILY_UNIT,
    specs=None,
):
    """Return per-market promotion decisions for a unit family."""
    specs = _family_specs(family_unit, specs=specs)
    family_ids = {spec.id for spec in specs}
    corpus_counts = Counter(
        entry.get("market_id")
        for entry in manifest.get("entries") or []
        if entry.get("market_id") in family_ids
    )
    trust_by_market = {row.get("market"): row for row in trust_rows if row.get("market")}
    candidate_by_market = {
        row.get("market_id"): row
        for row in candidate_report.get("market_rows") or []
        if row.get("market_id")
    }
    replay_gate = candidate_report.get("replay_gate") or {"global_ok": True}
    global_ok = bool(replay_gate.get("global_ok", True))

    decisions = []
    for spec in sorted(specs, key=lambda item: item.id):
        row = candidate_by_market.get(spec.id)
        if row:
            verdict = row.get("verdict") or "BLOCK"
            reason = row.get("reason") or ""
            snapshots = row.get("snapshots", 0)
            band_rows = row.get("rows", 0)
            metrics = _comparison_metrics(row.get("comparison"))
        else:
            verdict = "SHADOW"
            reason = "no pinned candidate rows for this family market"
            snapshots = 0
            band_rows = 0
            metrics = _comparison_metrics(None)

        if verdict == "PASS" and not global_ok:
            verdict = "BLOCK"
            reason = f"global replay gate failed: {replay_gate.get('corpus_message') or replay_gate.get('fidelity_message')}"

        trust = trust_by_market.get(spec.id) or {}
        decisions.append({
            "market_id": spec.id,
            "city": spec.city_label,
            "family_unit": family_unit,
            "action": _action_for_verdict(verdict),
            "verdict": verdict,
            "reason": reason,
            "settled_days_in_corpus": int(corpus_counts.get(spec.id, 0)),
            "candidate_days": row.get("days", 0) if row else 0,
            "candidate_snapshots": snapshots,
            "candidate_band_rows": band_rows,
            "trust_score": trust.get("trust_score"),
            "trust_grade": trust.get("grade"),
            "trust_settled_days": trust.get("settled_days"),
            "metrics": metrics,
        })

    counts = Counter(item["action"] for item in decisions)
    return {
        "family_unit": family_unit,
        "family_market_count": len(specs),
        "global_replay_gate_ok": global_ok,
        "promote_markets": [item["market_id"] for item in decisions if item["action"] == "PROMOTE_CANDIDATE"],
        "shadow_markets": [item["market_id"] for item in decisions if item["action"] == "KEEP_SHADOW"],
        "blocked_markets": [item["market_id"] for item in decisions if item["action"] == "BLOCK_CANDIDATE"],
        "action_counts": dict(sorted(counts.items())),
        "markets": decisions,
    }


def _decision_table_rows(decisions):
    rows = []
    for item in decisions:
        metrics = item.get("metrics") or {}
        rows.append([
            item.get("market_id"),
            item.get("candidate_days"),
            item.get("candidate_snapshots"),
            item.get("candidate_band_rows"),
            f"{item.get('trust_score', '-')}/100 {item.get('trust_grade', '')}".strip(),
            fmt_num(metrics.get("candidate_brier")),
            fmt_num(metrics.get("current_brier")),
            fmt_num(metrics.get("market_brier")),
            fmt_signed(metrics.get("delta_vs_current"), 4),
            fmt_signed(metrics.get("delta_vs_market"), 4),
            item.get("action"),
            item.get("reason") or "-",
        ])
    return rows


def write_report(path, payload):
    path = Path(path)
    corpus = payload.get("corpus") or {}
    candidate = payload.get("candidate") or {}
    candidate_agg = candidate.get("aggregate") or {}
    replay_gate = candidate.get("replay_gate") or {}
    decisions = payload.get("decisions") or {}
    serving = payload.get("serving_gauntlet")

    lines = [
        "# F-Family Promotion Refresh",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Family unit: `{payload.get('family_unit')}`",
        "",
        "## Decision Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Candidate verdict", candidate.get("verdict") or "-"],
            ["Candidate market-only verdict", candidate.get("candidate_market_verdict") or "-"],
            ["Cutover decision", candidate.get("cutover_decision") or "-"],
            ["Promote", ", ".join(decisions.get("promote_markets") or []) or "-"],
            ["Shadow", ", ".join(decisions.get("shadow_markets") or []) or "-"],
            ["Blocked", ", ".join(decisions.get("blocked_markets") or []) or "-"],
        ],
    )
    lines += [
        "",
        "## Refresh Artifacts",
        "",
    ]
    lines += markdown_table(
        ["Artifact", "Path / Hash"],
        [
            ["Promotion corpus", f"{corpus.get('path')} / {corpus.get('corpus_hash')}"],
            ["Location trust", (payload.get("trust") or {}).get("path") or "-"],
            ["Candidate JSON", candidate.get("json_path") or "-"],
            ["Candidate report", candidate.get("report_path") or "-"],
            ["Serving gauntlet", (serving or {}).get("report_path") or "skipped"],
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
            ["As of", corpus.get("as_of") or "-"],
            ["Market days", corpus.get("market_day_count", 0)],
            ["Pinned snapshots", corpus.get("snapshot_count", 0)],
            ["Band rows", corpus.get("band_row_count", 0)],
            ["Identity records", corpus.get("identity_record_count", 0)],
            ["Skipped folders", corpus.get("skipped_count", 0)],
        ],
    )
    lines += [
        "",
        "## Candidate Replay",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Rows", candidate_agg.get("rows", 0)],
            ["Candidate Brier", fmt_num(candidate_agg.get("candidate_brier"))],
            ["Current Brier", fmt_num(candidate_agg.get("current_brier"))],
            ["Recorded Brier", fmt_num(candidate_agg.get("recorded_brier"))],
            ["Market Brier", fmt_num(candidate_agg.get("market_brier"))],
            ["Delta vs current", fmt_signed(candidate_agg.get("delta_vs_current"), 4)],
            ["Delta vs market", fmt_signed(candidate_agg.get("delta_vs_market"), 4)],
        ],
    )
    lines += [
        "",
        "## Global Replay Gate",
        "",
    ]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [
            ["Corpus pin", "PASS" if replay_gate.get("corpus_ok") else "FAIL", replay_gate.get("corpus_message") or "-"],
            ["Replay fidelity", "PASS" if replay_gate.get("fidelity_ok") else "FAIL", replay_gate.get("fidelity_message") or "-"],
        ],
    )
    if serving:
        lines += [
            "",
            "## Current-Serving Gauntlet",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Verdict", serving.get("verdict") or "-"],
                ["Corpus OK", serving.get("corpus_ok")],
                ["Fidelity OK", serving.get("fidelity_ok")],
                ["Regression OK", serving.get("baseline_ok")],
                ["Forecast tracker", (serving.get("forecast_tracker") or {}).get("message") or "-"],
            ],
        )
    lines += [
        "",
        "## Per-Market Decisions",
        "",
    ]
    lines += markdown_table(
        [
            "Market", "Days", "Snaps", "Rows", "Trust", "Candidate Brier",
            "Current Brier", "Market Brier", "Delta Current",
            "Delta Market", "Action", "Reason",
        ],
        _decision_table_rows(decisions.get("markets") or []),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _serving_gauntlet_args(args, corpus_path):
    return SimpleNamespace(
        corpus=str(corpus_path),
        snapshots_root=args.snapshots_root,
        baseline=args.baseline,
        no_baseline=args.no_baseline,
        forecast_tracker=args.forecast_tracker,
        out=args.serving_gauntlet_report,
        replay_report=args.serving_replay_report,
        tol=args.tol,
        market_tol=args.market_tol,
        min_days=args.min_days,
        min_trust=args.min_trust,
        max_fidelity_l1=args.max_fidelity_l1,
        require_exact_identity=args.require_exact_identity,
        require_all_markets=args.require_all_markets,
    )


def _candidate_args(args, corpus_path):
    return SimpleNamespace(
        corpus=str(corpus_path),
        snapshots_root=args.snapshots_root,
        artifact=args.artifact,
        out=args.candidate_report,
        json_out=args.candidate_json,
        replay_report=args.current_replay_report,
        current_tol=args.current_tol,
        market_tol=args.market_tol,
        min_days=args.min_days,
        min_trust=args.min_trust,
        max_fidelity_l1=args.max_fidelity_l1,
        require_exact_identity=args.require_exact_identity,
        require_all_markets=args.require_all_markets,
        fail_on_block=False,
    )


def run_promotion_refresh(args):
    quality_grades = parse_quality_grades(args.quality_grades)
    manifest = build_promotion_corpus(
        folders=args.folders,
        snapshots_root=args.snapshots_root,
        as_of=args.as_of,
        quality_grades=quality_grades,
        include_reconstructed=args.include_reconstructed,
        allow_unsettled=args.allow_unsettled,
        market_id=None,
        min_snapshots=args.min_snapshots,
    )
    corpus_path = write_manifest(manifest, args.corpus_out)

    trust_rows = score_all_markets(
        root=args.snapshots_root,
        as_of=manifest.get("as_of"),
    )
    trust_path = _write_json(args.trust_out, trust_rows)

    candidate_report = run_pooled_candidate_replay(_candidate_args(args, corpus_path))

    serving_report = None
    if not args.skip_serving_gauntlet:
        serving_report = run_promotion_gauntlet(_serving_gauntlet_args(args, corpus_path))

    family_ids = [spec.id for spec in _family_specs(args.family_unit)]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "family_unit": args.family_unit,
        "corpus": _manifest_summary(manifest, corpus_path),
        "trust": _trust_summary(trust_rows, trust_path, family_ids),
        "candidate": _candidate_summary(candidate_report, args.candidate_json, args.candidate_report),
        "serving_gauntlet": _serving_gauntlet_summary(
            serving_report,
            args.serving_gauntlet_report,
            args.serving_replay_report,
        ),
        "decisions": build_family_decisions(
            manifest,
            trust_rows,
            candidate_report,
            family_unit=args.family_unit,
        ),
    }
    out_path = _write_json(args.out, payload)
    report_path = write_report(args.report, payload)
    return payload, out_path, report_path


def build_parser():
    parser = argparse.ArgumentParser(
        description="Refresh promotion corpus, trust, pooled replay, and family promotion decisions."
    )
    parser.add_argument("folders", nargs="*", help="Optional snapshot folders; defaults to discovered settled folders.")
    parser.add_argument("--family-unit", default=DEFAULT_FAMILY_UNIT, choices=["F"])
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--quality-grades", default=",".join(DEFAULT_QUALITY_GRADES))
    parser.add_argument("--include-reconstructed", action="store_true")
    parser.add_argument("--allow-unsettled", action="store_true")
    parser.add_argument("--min-snapshots", type=int, default=1)
    parser.add_argument("--corpus-out", default=str(DEFAULT_CORPUS))
    parser.add_argument("--trust-out", default=str(DEFAULT_TRUST_OUT))
    parser.add_argument("--artifact", default=str(DEFAULT_BAND_ARTIFACT))
    parser.add_argument("--candidate-report", default=str(DEFAULT_CANDIDATE_REPORT))
    parser.add_argument("--candidate-json", default=str(DEFAULT_CANDIDATE_JSON))
    parser.add_argument("--current-replay-report", default=str(DEFAULT_CURRENT_REPLAY_REPORT))
    parser.add_argument("--serving-gauntlet-report", default=str(DEFAULT_SERVING_GAUNTLET_REPORT))
    parser.add_argument("--serving-replay-report", default=str(DEFAULT_SERVING_REPLAY_REPORT))
    parser.add_argument("--forecast-tracker", default=str(DEFAULT_FORECAST_TRACKER))
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--skip-serving-gauntlet", action="store_true")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--current-tol", type=float, default=0.003)
    parser.add_argument("--tol", type=float, default=0.003)
    parser.add_argument("--market-tol", type=float, default=0.003)
    parser.add_argument("--min-days", type=int, default=2)
    parser.add_argument("--min-trust", type=int, default=25)
    parser.add_argument("--max-fidelity-l1", type=float, default=FIDELITY_FAITHFUL_L1)
    parser.add_argument("--require-exact-identity", action="store_true")
    parser.add_argument("--require-all-markets", action="store_true")
    parser.add_argument("--fail-on-block", action="store_true")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
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
    if args.fail_on_block and decisions.get("blocked_markets"):
        sys.exit(1)


if __name__ == "__main__":
    main()

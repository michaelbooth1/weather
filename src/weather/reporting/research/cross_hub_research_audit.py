"""Cross-hub research audit for location performance and transferable lessons."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from weather.io import read_json, write_json_atomic
from weather.paths import data_path
from weather.reporting.source_gates import cross_hub_readiness
from weather.reporting.formatting import fmt_num, fmt_pct, fmt_signed, markdown_table


SCHEMA_VERSION = "cross_hub_research_audit_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_MM_RUNS_ROOT = data_path() / "mm_runs"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "cross_hub_research_audit.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "cross_hub_research_audit_report.md"
DEFAULT_PROMOTION = DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh.json"
DEFAULT_LOCATION_TRUST = DEFAULT_BACKTEST_ROOT / "location_trust.json"
DEFAULT_HOURLY_PERFORMANCE = DEFAULT_BACKTEST_ROOT / "hourly_model_performance.json"
DEFAULT_MM_PAPER = DEFAULT_BACKTEST_ROOT / "mm_paper_report.json"
DEFAULT_MARKET_TOL = cross_hub_readiness.DEFAULT_MARKET_TOL


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _counter_rows(counter: Counter, limit: int = 5) -> list[dict[str, Any]]:
    return [{"name": key, "count": count} for key, count in counter.most_common(limit)]


def summarize_run_logs(runs_root: str | Path = DEFAULT_MM_RUNS_ROOT) -> dict[str, Any]:
    """Summarize market-making run-summary logs by market."""
    runs_root = Path(runs_root)
    summaries = sorted(runs_root.glob("*/*/run_summary.json"), key=lambda path: path.stat().st_mtime)
    markets: dict[str, dict[str, Any]] = {}
    status_counts: dict[str, Counter] = defaultdict(Counter)
    preflight_counts: dict[str, Counter] = defaultdict(Counter)
    failing_gates: dict[str, Counter] = defaultdict(Counter)
    reason_kinds: dict[str, Counter] = defaultdict(Counter)
    blocking_reasons: dict[str, Counter] = defaultdict(Counter)
    csv_issues: dict[str, int] = defaultdict(int)
    total_book_captures: dict[str, int] = defaultdict(int)

    for path in summaries:
        payload = read_json(path, default={}) or {}
        preflight_status = payload.get("preflight_status") or "UNKNOWN"
        for row in payload.get("markets") or []:
            market_id = row.get("market_id")
            if not market_id:
                continue
            status = row.get("status") or "UNKNOWN"
            status_counts[market_id][status] += 1
            preflight_counts[market_id][preflight_status] += 1
            reason_kind = row.get("reason_kind")
            if reason_kind:
                reason_kinds[market_id][reason_kind] += 1
            for reason in row.get("blocking_reasons") or []:
                blocking_reasons[market_id][str(reason)] += 1
            for gate in row.get("gates") or []:
                if gate.get("ok") is False:
                    failing_gates[market_id][gate.get("name") or "unknown"] += 1
            csv_issues[market_id] += _safe_int((row.get("csv_encoding") or {}).get("issue_count"))
            total_book_captures[market_id] += _safe_int((row.get("book_audit") or {}).get("captures"))
            latest = markets.get(market_id, {}).get("latest") or {}
            if not latest or path.stat().st_mtime >= latest.get("_mtime", 0):
                book = row.get("book_audit") or {}
                markets.setdefault(market_id, {})["latest"] = {
                    "_mtime": path.stat().st_mtime,
                    "path": str(path),
                    "run_id": payload.get("run_id"),
                    "target_date": payload.get("target_date"),
                    "preflight_status": preflight_status,
                    "live_forward_gate_status": payload.get("live_forward_gate_status"),
                    "status": status,
                    "reason_kind": row.get("reason_kind"),
                    "blocking_reasons": row.get("blocking_reasons") or [],
                    "promotion_state": row.get("promotion_state"),
                    "promotion_action": row.get("promotion_action"),
                    "book_captures": _safe_int(book.get("captures")),
                    "book_ok": book.get("ok"),
                    "book_reason": book.get("reason"),
                    "model_age_seconds": row.get("model_age_seconds"),
                    "source_status_fresh": row.get("source_status_fresh"),
                    "csv_encoding_status": (row.get("csv_encoding") or {}).get("status"),
                    "failing_gates": [
                        gate.get("name") or "unknown"
                        for gate in row.get("gates") or []
                        if gate.get("ok") is False
                    ],
                }

    rows = {}
    for market_id, payload in markets.items():
        runs = sum(status_counts[market_id].values())
        pass_runs = status_counts[market_id].get("PASS", 0)
        latest = dict(payload.get("latest") or {})
        latest.pop("_mtime", None)
        rows[market_id] = {
            "run_count": runs,
            "pass_rate": (pass_runs / runs) if runs else None,
            "status_counts": dict(sorted(status_counts[market_id].items())),
            "preflight_status_counts": dict(sorted(preflight_counts[market_id].items())),
            "csv_issue_count": csv_issues[market_id],
            "total_book_captures": total_book_captures[market_id],
            "top_failing_gates": _counter_rows(failing_gates[market_id]),
            "top_reason_kinds": _counter_rows(reason_kinds[market_id]),
            "top_blocking_reasons": _counter_rows(blocking_reasons[market_id]),
            "latest": latest,
        }
    return {
        "schema_version": "cross_hub_run_log_summary_v0.1",
        "runs_root": str(runs_root),
        "run_summary_count": len(summaries),
        "markets": dict(sorted(rows.items())),
    }


def _trust_by_market(location_trust: Any) -> dict[str, dict[str, Any]]:
    if isinstance(location_trust, list):
        return {row.get("market"): row for row in location_trust if row.get("market")}
    if isinstance(location_trust, dict):
        return location_trust
    return {}


def _promotion_by_market(promotion: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row.get("market_id"): row
        for row in ((promotion.get("decisions") or {}).get("markets") or [])
        if row.get("market_id")
    }


def _gap_diagnostics_by_market(promotion: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    diagnostics = promotion.get("market_skill_diagnostics") or []
    if isinstance(diagnostics, list):
        for row in diagnostics:
            market_id = row.get("market_id")
            if market_id:
                rows[market_id].append(row)
    for items in rows.values():
        items.sort(key=lambda row: _safe_float(row.get("delta_vs_market")) or 0, reverse=True)
    return dict(rows)


def _gap_owner_targets(promotion: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in promotion.get("gap_owner_table") or []:
        for market_id in item.get("affected_markets") or []:
            rows[market_id].append(item)
    for items in rows.values():
        items.sort(key=lambda row: _safe_float(row.get("excess_brier_rows")) or 0, reverse=True)
    return dict(rows)


def _perf_class(readiness_row: dict[str, Any], market_tol: float) -> str:
    delta_market = _safe_float((readiness_row.get("candidate_vs_market") or {}).get("delta_vs_market"))
    delta_current = _safe_float((readiness_row.get("candidate_vs_current") or {}).get("delta_vs_current"))
    if delta_market is None or delta_current is None:
        return "unproven"
    if delta_current < 0 and delta_market <= 0:
        return "beats current and market"
    if delta_current < 0 and delta_market <= market_tol:
        return "beats current, market-competitive"
    if delta_current == 0 and delta_market <= market_tol:
        return "matches current, market-competitive"
    if delta_current < 0:
        return "beats current, trails market"
    return "unproven"


def _diagnosis(
    market_id: str,
    readiness_row: dict[str, Any],
    trust: dict[str, Any],
    run_log: dict[str, Any],
    gap_items: list[dict[str, Any]],
    *,
    market_tol: float,
) -> tuple[list[str], list[str]]:
    findings: list[str] = []
    lessons: list[str] = []
    perf_class = _perf_class(readiness_row, market_tol)
    delta_market = _safe_float((readiness_row.get("candidate_vs_market") or {}).get("delta_vs_market"))
    quote = readiness_row.get("quoteability") or {}
    source = readiness_row.get("source_redundancy") or {}
    latest = (run_log or {}).get("latest") or {}
    ece = _safe_float((trust or readiness_row.get("trust") or {}).get("model_ece"))

    if perf_class in {"beats current and market", "beats current, market-competitive"}:
        findings.append(perf_class)
        lessons.append("denver_atlanta_promotion_pattern")
    if market_id == "dallas" or (ece is not None and ece > 0.05):
        findings.append("trust/ECE blocks treating ops health as model readiness")
        lessons.append("dallas_trust_guardrail")
    elif readiness_row.get("model_label") == "model-blocked":
        findings.append("model gate blocks promotion")
    if delta_market is not None and delta_market > market_tol:
        findings.append(f"residual market gap {delta_market:+.4f} needs local repair")
        lessons.append("residual_market_gap_repair")
    if quote.get("quote_rows") and readiness_row.get("model_label") != "promote":
        findings.append("quote rows are not promotion evidence")
        lessons.append("quoteability_not_edge")
    if market_id in {"miami", "seattle"}:
        lessons.append("quoteability_not_edge")
    if source.get("source_count") and source.get("fresh_source_count") == source.get("source_count"):
        findings.append("source-state freshness is complete in latest fleet artifact")
        lessons.append("toronto_source_redundancy")
    if readiness_row.get("readiness_label") == "ops-blocked":
        findings.append("shared plumbing blocks live-forward claims")
        lessons.append("shared_plumbing_blocker")
    if latest.get("status") and latest.get("status") != "PASS":
        findings.append(f"latest run status {latest.get('status')}")
    elif latest.get("status") == "PASS":
        findings.append("latest run preflight/market gates pass")
    if gap_items:
        findings.append(f"top repair owner: {gap_items[0].get('owner') or gap_items[0].get('next_experiment')}")

    return sorted(dict.fromkeys(findings)), sorted(dict.fromkeys(lessons))


def _lesson_action(lesson_id: str) -> str:
    actions = {
        "denver_atlanta_promotion_pattern": "Promote only when the candidate improves current and stays market-competitive on daily-first evidence.",
        "toronto_source_redundancy": "Carry source freshness, official/local source layers, and provenance into every hub review.",
        "dallas_trust_guardrail": "Require trust/ECE clearance even when collection and run logs look healthy.",
        "quoteability_not_edge": "Review quote rows with Brier, market gap, trust, and no-quote reasons before inferring model edge.",
        "shared_plumbing_blocker": "Keep broad live-forward claims blocked until snapshot/live SLO, serialization, and preflight gates are clean.",
        "residual_market_gap_repair": "Route positive market gaps to local repair experiments instead of promoting from current-beating lift alone.",
    }
    return actions.get(lesson_id, "Manual review.")


def _build_transfer_lessons(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lesson_targets: dict[str, set[str]] = defaultdict(set)
    lesson_sources: dict[str, set[str]] = defaultdict(set)
    for row in markets:
        market_id = row.get("market_id")
        for lesson in row.get("transfer_lesson_ids") or []:
            lesson_targets[lesson].add(market_id)
            if lesson == "denver_atlanta_promotion_pattern" and row.get("model_label") == "promote":
                lesson_sources[lesson].add(market_id)
            elif lesson == "toronto_source_redundancy" and market_id == "toronto":
                lesson_sources[lesson].add(market_id)
            elif lesson == "dallas_trust_guardrail" and market_id == "dallas":
                lesson_sources[lesson].add(market_id)
            elif lesson == "quoteability_not_edge" and market_id in {"miami", "seattle"}:
                lesson_sources[lesson].add(market_id)
            elif lesson in {"shared_plumbing_blocker", "residual_market_gap_repair"}:
                lesson_sources[lesson].add("fleet")
    preferred_order = [
        "toronto_source_redundancy",
        "denver_atlanta_promotion_pattern",
        "dallas_trust_guardrail",
        "quoteability_not_edge",
        "residual_market_gap_repair",
        "shared_plumbing_blocker",
    ]
    rows = []
    for lesson in preferred_order:
        if not lesson_targets.get(lesson):
            continue
        rows.append({
            "lesson_id": lesson,
            "source_hubs": sorted(lesson_sources.get(lesson) or []),
            "target_hubs": sorted(lesson_targets[lesson]),
            "action": _lesson_action(lesson),
        })
    return rows


def build_research_audit(
    readiness: dict[str, Any],
    promotion: dict[str, Any],
    location_trust: Any,
    hourly_performance: dict[str, Any],
    run_logs: dict[str, Any],
    *,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> dict[str, Any]:
    trust_by_market = _trust_by_market(location_trust)
    promotion_by_market = _promotion_by_market(promotion)
    gap_by_market = _gap_diagnostics_by_market(promotion)
    gap_owners = _gap_owner_targets(promotion)
    log_by_market = run_logs.get("markets") or {}
    markets = []
    for row in readiness.get("markets") or []:
        market_id = row.get("market_id")
        if not market_id:
            continue
        trust = trust_by_market.get(market_id) or row.get("trust") or {}
        decision = promotion_by_market.get(market_id) or {}
        log_row = log_by_market.get(market_id) or {}
        gap_items = gap_by_market.get(market_id) or gap_owners.get(market_id) or []
        findings, lesson_ids = _diagnosis(
            market_id,
            row,
            trust,
            log_row,
            gap_items,
            market_tol=market_tol,
        )
        metrics = decision.get("metrics") or {}
        markets.append({
            "market_id": market_id,
            "city": row.get("city") or decision.get("city") or market_id,
            "readiness_label": row.get("readiness_label"),
            "model_label": row.get("model_label"),
            "performance_class": _perf_class(row, market_tol),
            "promotion_action": row.get("promotion_action"),
            "performance": {
                "candidate_brier": metrics.get("candidate_brier") or (row.get("candidate_vs_market") or {}).get("candidate_brier"),
                "current_brier": metrics.get("current_brier") or (row.get("candidate_vs_current") or {}).get("current_brier"),
                "market_brier": metrics.get("market_brier") or (row.get("candidate_vs_market") or {}).get("market_brier"),
                "delta_vs_current": metrics.get("delta_vs_current") or (row.get("candidate_vs_current") or {}).get("delta_vs_current"),
                "delta_vs_market": metrics.get("delta_vs_market") or (row.get("candidate_vs_market") or {}).get("delta_vs_market"),
                "candidate_ece": metrics.get("candidate_ece"),
                "rows": metrics.get("rows"),
            },
            "trust": trust,
            "collection": row.get("collection") or {},
            "source_redundancy": row.get("source_redundancy") or {},
            "quoteability": row.get("quoteability") or {},
            "live_forward_evidence": row.get("live_forward_evidence") or {},
            "run_log_evidence": log_row,
            "gap_diagnostics": gap_items[:3],
            "findings": findings,
            "transfer_lesson_ids": lesson_ids,
        })

    markets.sort(key=lambda row: (_safe_float((row.get("performance") or {}).get("delta_vs_market")) is None, _safe_float((row.get("performance") or {}).get("delta_vs_market")) or 0))
    for index, row in enumerate(markets, start=1):
        row["performance_rank_by_market_gap"] = index

    label_counts = Counter(row.get("model_label") for row in markets)
    largest_gaps = sorted(
        markets,
        key=lambda row: _safe_float((row.get("performance") or {}).get("delta_vs_market")) or -999,
        reverse=True,
    )[:5]
    best_gaps = markets[:5]
    transfer_lessons = _build_transfer_lessons(markets)
    hourly_gate = hourly_performance.get("hourly_performance_gate") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": cross_hub_readiness.utc_now(),
        "thresholds": {"market_tolerance": market_tol},
        "inputs": {
            "readiness_schema": readiness.get("schema_version"),
            "promotion_schema": promotion.get("schema_version"),
            "location_trust_rows": len(location_trust) if isinstance(location_trust, list) else len(location_trust or {}),
            "run_summary_count": run_logs.get("run_summary_count"),
        },
        "summary": {
            "market_count": len(markets),
            "model_label_counts": dict(sorted(label_counts.items())),
            "broad_live_claim_allowed": (readiness.get("broad_live_claim") or {}).get("allowed"),
            "broad_live_blockers": (readiness.get("broad_live_claim") or {}).get("blockers") or [],
            "hourly_performance_gate": {
                "blocker_count": hourly_gate.get("blocker_count"),
                "blockers": hourly_gate.get("blockers") or [],
            },
            "best_market_gap_hubs": [
                {
                    "market_id": row.get("market_id"),
                    "delta_vs_market": (row.get("performance") or {}).get("delta_vs_market"),
                    "model_label": row.get("model_label"),
                }
                for row in best_gaps
            ],
            "largest_market_gap_hubs": [
                {
                    "market_id": row.get("market_id"),
                    "delta_vs_market": (row.get("performance") or {}).get("delta_vs_market"),
                    "model_label": row.get("model_label"),
                }
                for row in largest_gaps
            ],
        },
        "transfer_lessons": transfer_lessons,
        "markets": markets,
    }


def _source_cell(row: dict[str, Any]) -> str:
    source = row.get("source_redundancy") or {}
    count = source.get("source_count")
    freshness = "-"
    if count:
        freshness = f"{source.get('fresh_source_count', 0)}/{count}"
    official = ",".join(source.get("official_or_local_families") or []) or "-"
    return f"{source.get('status')}; fresh {freshness}; official/local {official}"


def _quote_cell(row: dict[str, Any]) -> str:
    quote = row.get("quoteability") or {}
    reasons = quote.get("top_no_quote_reasons") or []
    reason = "-"
    if reasons:
        reason = f"{reasons[0].get('reason')}:{reasons[0].get('rows')}"
    return f"{quote.get('quote_rows', 0)}/{quote.get('rows', 0)} ({fmt_pct(quote.get('quote_rate'))}) top {reason}"


def _run_cell(row: dict[str, Any]) -> str:
    logs = row.get("run_log_evidence") or {}
    latest = logs.get("latest") or {}
    return (
        f"{logs.get('run_count', 0)} runs; pass {fmt_pct(logs.get('pass_rate'))}; "
        f"latest {latest.get('target_date') or '-'} {latest.get('status') or '-'} / preflight {latest.get('preflight_status') or '-'}"
    )


def _performance_cell(row: dict[str, Any]) -> str:
    perf = row.get("performance") or {}
    return (
        f"{row.get('performance_class')}; "
        f"dCur {fmt_signed(perf.get('delta_vs_current'), 4)}, "
        f"dMkt {fmt_signed(perf.get('delta_vs_market'), 4)}"
    )


def _trust_cell(row: dict[str, Any]) -> str:
    trust = row.get("trust") or {}
    return f"{trust.get('trust_score', '-')}/100 {trust.get('grade', '')}; ECE {fmt_num(trust.get('model_ece'))}"


def _market_table_rows(payload: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for row in payload.get("markets") or []:
        rows.append([
            row.get("market_id"),
            row.get("readiness_label"),
            row.get("model_label"),
            _performance_cell(row),
            _trust_cell(row),
            _source_cell(row),
            _quote_cell(row),
            _run_cell(row),
            "; ".join(row.get("findings") or []) or "-",
            ", ".join(row.get("transfer_lesson_ids") or []) or "-",
        ])
    return rows


def _comparison_rows(payload: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for row in payload.get("markets") or []:
        perf = row.get("performance") or {}
        quote = row.get("quoteability") or {}
        logs = row.get("run_log_evidence") or {}
        rows.append([
            row.get("performance_rank_by_market_gap"),
            row.get("market_id"),
            row.get("model_label"),
            fmt_signed(perf.get("delta_vs_market"), 4),
            fmt_signed(perf.get("delta_vs_current"), 4),
            row.get("trust", {}).get("trust_score", "-"),
            fmt_num(row.get("trust", {}).get("model_ece")),
            fmt_pct(quote.get("quote_rate")),
            fmt_pct(logs.get("pass_rate")),
        ])
    return rows


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    summary = payload.get("summary") or {}
    lines = [
        "# Cross-Hub Location Research Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Broad live claim allowed: `{summary.get('broad_live_claim_allowed')}`",
        "",
        "## Per-Location Audit",
        "",
    ]
    lines += markdown_table(
        [
            "Market",
            "Readiness",
            "Model",
            "Performance",
            "Trust/ECE",
            "Source",
            "Quote Logs",
            "Run/Log Evidence",
            "Diagnosis",
            "Transfer Lessons",
        ],
        _market_table_rows(payload),
    )
    lines += ["", "## Cross-Hub Comparison", ""]
    lines += markdown_table(
        ["Rank", "Market", "Model", "dMkt", "dCur", "Trust", "ECE", "Quote Rate", "Run Pass"],
        _comparison_rows(payload),
    )
    lines += ["", "## Transfer Lessons", ""]
    lines += markdown_table(
        ["Lesson", "Source Hubs", "Target Hubs", "Action"],
        [
            [
                row.get("lesson_id"),
                ", ".join(row.get("source_hubs") or []) or "-",
                ", ".join(row.get("target_hubs") or []) or "-",
                row.get("action"),
            ]
            for row in payload.get("transfer_lessons") or []
        ],
    )
    blockers = summary.get("broad_live_blockers") or []
    hourly_blockers = (summary.get("hourly_performance_gate") or {}).get("blockers") or []
    lines += ["", "## Shared Blockers", ""]
    if blockers or hourly_blockers:
        rows = [[row.get("gate"), row.get("detail")] for row in blockers]
        rows += [[row.get("gate"), row.get("detail")] for row in hourly_blockers]
        lines += markdown_table(["Gate", "Detail"], rows)
    else:
        lines += ["No shared blockers."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_payload_from_paths(
    *,
    promotion_path: str | Path = DEFAULT_PROMOTION,
    location_trust_path: str | Path = DEFAULT_LOCATION_TRUST,
    hourly_performance_path: str | Path = DEFAULT_HOURLY_PERFORMANCE,
    mm_paper_path: str | Path = DEFAULT_MM_PAPER,
    runs_root: str | Path = DEFAULT_MM_RUNS_ROOT,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> dict[str, Any]:
    readiness = cross_hub_readiness.build_payload_from_paths(runs_root=runs_root, market_tol=market_tol)
    promotion = read_json(promotion_path, default={}) or {}
    location_trust = read_json(location_trust_path, default=[]) or []
    hourly_performance = read_json(hourly_performance_path, default={}) or {}
    # Read for provenance and to keep the CLI sensitive to a missing or malformed mm paper artifact.
    read_json(mm_paper_path, default={})
    run_logs = summarize_run_logs(runs_root)
    payload = build_research_audit(
        readiness,
        promotion,
        location_trust,
        hourly_performance,
        run_logs,
        market_tol=market_tol,
    )
    payload["inputs"].update({
        "promotion": str(promotion_path),
        "location_trust": str(location_trust_path),
        "hourly_performance": str(hourly_performance_path),
        "mm_paper": str(mm_paper_path),
        "runs_root": str(runs_root),
    })
    return payload


def run(args: argparse.Namespace) -> tuple[dict[str, Any], Path, Path]:
    payload = build_payload_from_paths(
        promotion_path=args.promotion,
        location_trust_path=args.location_trust,
        hourly_performance_path=args.hourly_performance,
        mm_paper_path=args.mm_paper,
        runs_root=args.runs_root,
        market_tol=args.market_tol,
    )
    out = write_json_atomic(args.out, payload, trailing_newline=True)
    report = write_markdown_report(args.report, payload)
    return payload, out, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build cross-hub location research audit.")
    parser.add_argument("--promotion", default=str(DEFAULT_PROMOTION))
    parser.add_argument("--location-trust", default=str(DEFAULT_LOCATION_TRUST))
    parser.add_argument("--hourly-performance", default=str(DEFAULT_HOURLY_PERFORMANCE))
    parser.add_argument("--mm-paper", default=str(DEFAULT_MM_PAPER))
    parser.add_argument("--runs-root", default=str(DEFAULT_MM_RUNS_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _payload, out, report = run(args)
    print(f"Wrote {out}")
    print(f"Wrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

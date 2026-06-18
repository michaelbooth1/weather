"""Cross-hub readiness report for transfer lessons and promotion guardrails."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.io import read_csv_rows_with_diagnostics, read_json, write_json_atomic
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table


SCHEMA_VERSION = "cross_hub_readiness_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_MM_RUNS_ROOT = data_path() / "mm_runs"
DEFAULT_FLEET = DEFAULT_BACKTEST_ROOT / "fleet_observability.json"
DEFAULT_PROMOTION = DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh.json"
DEFAULT_MM_PAPER = DEFAULT_BACKTEST_ROOT / "mm_paper_report.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "cross_hub_readiness.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "cross_hub_readiness_report.md"
DEFAULT_MIN_TRUST = 25
DEFAULT_MAX_ECE = 0.05
DEFAULT_MARKET_TOL = 0.003


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _quote_action(row: dict[str, Any]) -> bool:
    action = str(row.get("action") or "").upper()
    reason = str(row.get("reason_code") or "").upper()
    return action.startswith("QUOTE") or reason.startswith("QUOTE") or _truthy(row.get("quote_permission"))


def _resolve_run_folder(runs_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [
        Path.cwd() / path,
        runs_root.parent.parent / path,
        runs_root.parent / path,
        runs_root / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _iter_run_folders(runs_root: Path, run_folders: list[str] | None = None) -> list[Path]:
    if run_folders is not None:
        return sorted(_resolve_run_folder(runs_root, value) for value in run_folders)
    return sorted(path.parent for path in runs_root.glob("*/*/quote_intents_long.csv"))


def quoteability_from_runs(
    runs_root: str | Path = DEFAULT_MM_RUNS_ROOT,
    run_folders: list[str] | None = None,
) -> dict[str, Any]:
    """Summarize quote rows and no-quote reasons by market from run tapes."""
    runs_root = Path(runs_root)
    rows_by_market: dict[str, Counter] = defaultdict(Counter)
    reason_by_market: dict[str, Counter] = defaultdict(Counter)
    run_ids_by_market: dict[str, set[str]] = defaultdict(set)
    diagnostics = {
        "files": 0,
        "legacy_encoding_files": 0,
        "decode_error_files": 0,
        "read_error_files": 0,
        "missing_files": 0,
    }
    for folder in _iter_run_folders(runs_root, run_folders):
        path = folder / "quote_intents_long.csv"
        rows, diag = read_csv_rows_with_diagnostics(path, attach_diagnostics=False)
        diagnostics["files"] += 1
        status = diag.get("status")
        if status == "legacy_encoding":
            diagnostics["legacy_encoding_files"] += 1
        elif status == "decode_error":
            diagnostics["decode_error_files"] += 1
        elif status == "read_error":
            diagnostics["read_error_files"] += 1
        elif status == "missing":
            diagnostics["missing_files"] += 1
        for row in rows:
            market_id = row.get("market_id") or "unknown"
            run_id = row.get("run_id") or folder.name
            run_ids_by_market[market_id].add(str(run_id))
            rows_by_market[market_id]["rows"] += 1
            if _quote_action(row):
                rows_by_market[market_id]["quote_rows"] += 1
            else:
                rows_by_market[market_id]["no_quote_rows"] += 1
                reason = row.get("reason_code") or row.get("orchestrator_reason_code") or "unknown"
                reason_by_market[market_id][str(reason or "unknown")] += 1

    markets = {}
    for market_id, counts in rows_by_market.items():
        rows = int(counts.get("rows", 0))
        quote_rows = int(counts.get("quote_rows", 0))
        markets[market_id] = {
            "rows": rows,
            "quote_rows": quote_rows,
            "no_quote_rows": int(counts.get("no_quote_rows", 0)),
            "quote_rate": (quote_rows / rows) if rows else None,
            "run_count": len(run_ids_by_market.get(market_id) or []),
            "top_no_quote_reasons": [
                {"reason": reason, "rows": count}
                for reason, count in reason_by_market[market_id].most_common(5)
            ],
        }
    return {
        "schema_version": "cross_hub_quoteability_v0.1",
        "runs_root": str(runs_root),
        "markets": dict(sorted(markets.items())),
        "diagnostics": diagnostics,
    }


def latest_run_summary(runs_root: str | Path = DEFAULT_MM_RUNS_ROOT) -> dict[str, Any]:
    runs_root = Path(runs_root)
    summaries = sorted(runs_root.glob("*/*/run_summary.json"), key=lambda path: path.stat().st_mtime)
    if not summaries:
        return {"exists": False, "markets": {}}
    path = summaries[-1]
    payload = read_json(path, default={}) or {}
    return {
        "exists": True,
        "path": str(path),
        "run_id": payload.get("run_id"),
        "target_date": payload.get("target_date"),
        "evidence_mode": payload.get("evidence_mode"),
        "preflight_status": payload.get("preflight_status"),
        "live_forward_gate_status": payload.get("live_forward_gate_status"),
        "reason_counts": payload.get("reason_counts") or {},
        "quote_permission_rows": payload.get("quote_permission_rows"),
        "markets": {
            row.get("market_id"): row
            for row in payload.get("markets") or []
            if row.get("market_id")
        },
    }


def source_redundancy_summary(collection_row: dict[str, Any]) -> dict[str, Any]:
    degradation = collection_row.get("source_family_degradation") or {}
    families = degradation.get("families") or {}
    official_or_local = sorted(
        family
        for family in families
        if family in {
            "eccc_citypage",
            "eccc_swob",
            "local_history",
            "marine_context",
            "metar",
            "nws",
            "nws_forecast",
            "wu_current",
            "wu_history",
        }
    )
    affected = int(degradation.get("affected_family_count") or 0)
    failed = int(degradation.get("failed_source_count") or 0)
    fallback = int(degradation.get("fallback_source_count") or 0)
    rate_limited = int(degradation.get("rate_limited_source_count") or 0)
    source_count = sum(int((details or {}).get("source_count") or 0) for details in families.values())
    fresh_source_count = sum(int((details or {}).get("fresh_source_count") or 0) for details in families.values())
    unknown_source_count = sum(int((details or {}).get("unknown_source_count") or 0) for details in families.values())
    status = "healthy"
    if failed:
        status = "failed"
    elif fallback or rate_limited or affected:
        status = "degraded"
    return {
        "available": bool(degradation.get("available")),
        "status": status,
        "family_count": len(families),
        "affected_family_count": affected,
        "failed_source_count": failed,
        "fallback_source_count": fallback,
        "rate_limited_source_count": rate_limited,
        "source_count": source_count,
        "fresh_source_count": fresh_source_count,
        "unknown_source_count": unknown_source_count,
        "official_or_local_families": official_or_local,
        "trading_evidence_allowed": degradation.get("trading_evidence_allowed"),
        "model_review_allowed": degradation.get("model_review_allowed"),
        "snapshot_id": degradation.get("snapshot_id"),
        "captured_at_utc": degradation.get("captured_at_utc"),
        "captured_at_local": degradation.get("captured_at_local"),
    }


def _promotion_by_market(promotion: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row.get("market_id"): row
        for row in ((promotion.get("decisions") or {}).get("markets") or [])
        if row.get("market_id")
    }


def _live_evidence_by_market(mm_paper: dict[str, Any]) -> dict[str, dict[str, Any]]:
    summary = (mm_paper.get("summary") or {}).get("per_market_live_forward_evidence") or {}
    rows: dict[str, dict[str, Any]] = defaultdict(dict)
    for evidence_class, item in summary.items():
        for market_id in item.get("countable_markets") or []:
            rows[market_id][evidence_class] = "countable"
        for market_id in item.get("blocked_markets") or []:
            rows[market_id][evidence_class] = "blocked"
    first_blockers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in mm_paper.get("per_market_evidence_credits") or []:
        if row.get("counts"):
            continue
        market_id = row.get("market_id")
        if not market_id:
            continue
        first_blockers[market_id].append({
            "evidence_class": row.get("evidence_class"),
            "blocking_gates": row.get("blocking_gates") or [],
            "first_failing_gate": row.get("first_failing_gate"),
            "owner": row.get("owner"),
            "root_cause": row.get("root_cause"),
            "suggested_command": row.get("suggested_command"),
        })
    for market_id, blockers in first_blockers.items():
        rows[market_id]["blockers"] = blockers[:5]
    return dict(rows)


def _broad_live_blockers(
    fleet: dict[str, Any],
    latest_run: dict[str, Any],
) -> list[dict[str, Any]]:
    blockers = []
    live_slo = fleet.get("live_forward_slo") or {}
    if live_slo.get("counts_toward_live_forward_gate") is False or live_slo.get("status") in {"BLOCK", "FAIL"}:
        blockers.append({
            "gate": "live_forward_slo",
            "detail": live_slo.get("reason") or "live-forward SLO does not count",
        })
    loop_summary = (fleet.get("loop_integrity") or {}).get("summary") or {}
    if loop_summary.get("ok") is False:
        blockers.append({
            "gate": "serialization_integrity",
            "detail": f"{loop_summary.get('malformed_lines', 0)} malformed loop line(s)",
        })
    if latest_run.get("exists") and latest_run.get("preflight_status") not in {None, "PASS"}:
        blockers.append({
            "gate": "latest_preflight",
            "detail": f"latest run preflight {latest_run.get('preflight_status')}",
        })
    return blockers


def _model_label(
    decision: dict[str, Any],
    trust: dict[str, Any],
    *,
    min_trust: int,
    max_ece: float,
    market_tol: float,
) -> tuple[str, list[str]]:
    reasons = []
    trust_score = trust.get("trust_score")
    ece = _safe_float(trust.get("model_ece"))
    if trust_score is not None and int(trust_score) < int(min_trust):
        reasons.append(f"trust {trust_score} < {min_trust}")
    if ece is not None and ece > max_ece:
        reasons.append(f"ECE {ece:.4f} > {max_ece:.4f}")
    action = decision.get("action")
    metrics = decision.get("metrics") or {}
    delta_current = _safe_float(metrics.get("delta_vs_current"))
    delta_market = _safe_float(metrics.get("delta_vs_market"))
    if not decision:
        return "shadow", ["no candidate decision for this hub"]
    if action == "BLOCK_CANDIDATE":
        reasons.append(decision.get("reason") or "candidate blocked")
        return "model-blocked", reasons
    if reasons:
        return "model-blocked", reasons
    if action == "PROMOTE_CANDIDATE":
        if delta_current is not None and delta_current > 0:
            return "model-blocked", [f"candidate trails current by {delta_current:+.4f}"]
        if delta_market is not None and delta_market > market_tol:
            return "shadow", [f"candidate market gap {delta_market:+.4f} > {market_tol:+.4f}"]
        return "promote", [decision.get("reason") or "passes promotion pattern"]
    if action == "KEEP_SHADOW":
        return "shadow", [decision.get("reason") or "candidate remains shadow"]
    return "shadow", [decision.get("reason") or "no promotion action"]


def _ops_blockers(
    collection: dict[str, Any],
    source: dict[str, Any],
    live_evidence: dict[str, Any],
    latest_market: dict[str, Any],
    broad_blockers: list[dict[str, Any]],
) -> list[str]:
    blockers = []
    if collection.get("state") not in {None, "CLEAN"}:
        blockers.append(collection.get("reason") or f"collection state {collection.get('state')}")
    if source.get("trading_evidence_allowed") is False:
        blockers.append("source degradation blocks trading evidence")
    if live_evidence.get("live_trade_permission_evidence") == "blocked":
        blockers.append("live trade permission evidence is blocked")
    if latest_market and latest_market.get("status") not in {None, "PASS"}:
        blockers.append(
            latest_market.get("reason_kind")
            or "; ".join(latest_market.get("blocking_reasons") or [])
            or f"latest market status {latest_market.get('status')}"
        )
    if broad_blockers:
        blockers.append("broad live plumbing blocked: " + ", ".join(row["gate"] for row in broad_blockers))
    return [item for item in blockers if item]


def _lesson_ids(
    market_id: str,
    label: str,
    model_label: str,
    ops_blockers: list[str],
    decision: dict[str, Any],
    trust: dict[str, Any],
    quoteability: dict[str, Any],
    source: dict[str, Any],
    *,
    max_ece: float,
) -> list[str]:
    lessons = []
    metrics = decision.get("metrics") or {}
    delta_market = _safe_float(metrics.get("delta_vs_market"))
    ece = _safe_float(trust.get("model_ece"))
    quote_rows = int((quoteability or {}).get("quote_rows") or 0)
    if ops_blockers:
        lessons.append("shared_plumbing_blocker")
    if source.get("status") != "healthy" or source.get("family_count", 0) > 0:
        lessons.append("toronto_source_redundancy")
    if model_label == "promote":
        lessons.append("denver_atlanta_promotion_pattern")
    if market_id == "dallas" or (ece is not None and ece > max_ece):
        lessons.append("dallas_trust_guardrail")
    if quote_rows > 0 and model_label != "promote":
        lessons.append("quoteability_not_edge")
    if market_id in {"miami", "seattle"}:
        lessons.append("quoteability_not_edge")
    if delta_market is not None and delta_market > 0:
        lessons.append("residual_market_gap")
    if not lessons and label != "promote":
        lessons.append("manual_review")
    return sorted(dict.fromkeys(lessons))


def build_cross_hub_readiness(
    fleet: dict[str, Any],
    promotion: dict[str, Any],
    mm_paper: dict[str, Any],
    quoteability: dict[str, Any],
    latest_run: dict[str, Any],
    *,
    min_trust: int = DEFAULT_MIN_TRUST,
    max_ece: float = DEFAULT_MAX_ECE,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> dict[str, Any]:
    collection_by_market = {
        row.get("market_id"): row
        for row in ((fleet.get("collection") or {}).get("markets") or [])
        if row.get("market_id")
    }
    trust_by_market = fleet.get("trust_readiness") or {}
    promotion_by_market = _promotion_by_market(promotion)
    live_evidence = _live_evidence_by_market(mm_paper)
    quote_by_market = quoteability.get("markets") or {}
    latest_by_market = latest_run.get("markets") or {}
    broad_blockers = _broad_live_blockers(fleet, latest_run)
    market_ids = sorted(set(collection_by_market) | set(trust_by_market) | set(promotion_by_market) | set(quote_by_market))
    rows = []
    for market_id in market_ids:
        collection = collection_by_market.get(market_id) or {}
        source = source_redundancy_summary(collection)
        trust = trust_by_market.get(market_id) or {}
        decision = promotion_by_market.get(market_id) or {}
        quote = quote_by_market.get(market_id) or {
            "rows": 0,
            "quote_rows": 0,
            "no_quote_rows": 0,
            "quote_rate": None,
            "top_no_quote_reasons": [],
        }
        evidence = live_evidence.get(market_id) or {}
        latest_market = latest_by_market.get(market_id) or {}
        model_label, model_reasons = _model_label(
            decision,
            trust,
            min_trust=min_trust,
            max_ece=max_ece,
            market_tol=market_tol,
        )
        ops_reasons = _ops_blockers(collection, source, evidence, latest_market, broad_blockers)
        label = "ops-blocked" if ops_reasons else model_label
        metrics = decision.get("metrics") or {}
        lessons = _lesson_ids(
            market_id,
            label,
            model_label,
            ops_reasons,
            decision,
            trust,
            quote,
            source,
            max_ece=max_ece,
        )
        row = {
            "market_id": market_id,
            "city": decision.get("city") or collection.get("city") or market_id,
            "readiness_label": label,
            "model_label": model_label,
            "model_reasons": model_reasons,
            "ops_blockers": ops_reasons,
            "collection": {
                "state": collection.get("state"),
                "snapshots": collection.get("snapshots"),
                "reason": collection.get("reason"),
                "max_gap_minutes": collection.get("max_gap_minutes"),
            },
            "source_redundancy": source,
            "trust": {
                "trust_score": trust.get("trust_score"),
                "grade": trust.get("grade"),
                "settled_days": trust.get("settled_days"),
                "model_ece": trust.get("model_ece"),
                "trust_gate_pass": (trust.get("trust_score") is None or int(trust.get("trust_score") or 0) >= min_trust),
                "ece_gate_pass": (_safe_float(trust.get("model_ece")) is None or _safe_float(trust.get("model_ece")) <= max_ece),
            },
            "candidate_vs_current": {
                "candidate_brier": metrics.get("candidate_brier"),
                "current_brier": metrics.get("current_brier"),
                "delta_vs_current": metrics.get("delta_vs_current"),
            },
            "candidate_vs_market": {
                "candidate_brier": metrics.get("candidate_brier"),
                "market_brier": metrics.get("market_brier"),
                "delta_vs_market": metrics.get("delta_vs_market"),
                "competitive_gate_pass": (
                    _safe_float(metrics.get("delta_vs_market")) is None
                    or _safe_float(metrics.get("delta_vs_market")) <= market_tol
                ),
            },
            "promotion_action": decision.get("action"),
            "promotion_reason": decision.get("reason"),
            "quoteability": quote,
            "live_forward_evidence": {
                "model_review": evidence.get("model_review_evidence"),
                "paper_trading": evidence.get("paper_trading_evidence"),
                "live_trade_permission": evidence.get("live_trade_permission_evidence"),
                "blockers": evidence.get("blockers") or [],
            },
            "latest_run": {
                "status": latest_market.get("status"),
                "reason_kind": latest_market.get("reason_kind"),
                "blocking_reasons": latest_market.get("blocking_reasons") or [],
            },
            "hub_lessons": lessons,
        }
        rows.append(row)
    label_counts = Counter(row["readiness_label"] for row in rows)
    model_label_counts = Counter(row["model_label"] for row in rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "thresholds": {
            "min_trust": min_trust,
            "max_ece": max_ece,
            "market_tolerance": market_tol,
        },
        "broad_live_claim": {
            "allowed": not broad_blockers,
            "blockers": broad_blockers,
        },
        "quoteability_diagnostics": quoteability.get("diagnostics") or {},
        "latest_run": {
            key: value
            for key, value in latest_run.items()
            if key != "markets"
        },
        "markets": rows,
        "summary": {
            "market_count": len(rows),
            "readiness_label_counts": dict(sorted(label_counts.items())),
            "model_label_counts": dict(sorted(model_label_counts.items())),
            "blocked_market_count": sum(1 for row in rows if row["readiness_label"] != "promote"),
        },
    }


def _quote_summary(row: dict[str, Any]) -> str:
    quote = row.get("quoteability") or {}
    reasons = quote.get("top_no_quote_reasons") or []
    top_reason = "-"
    if reasons:
        top_reason = f"{reasons[0].get('reason')}:{reasons[0].get('rows')}"
    rate = quote.get("quote_rate")
    return f"{quote.get('quote_rows', 0)}/{quote.get('rows', 0)} ({fmt_num(rate, 3)}) top {top_reason}"


def _source_summary(row: dict[str, Any]) -> str:
    source = row.get("source_redundancy") or {}
    official = ",".join(source.get("official_or_local_families") or []) or "-"
    freshness = ""
    if source.get("source_count"):
        freshness = f" fresh {source.get('fresh_source_count', 0)}/{source.get('source_count', 0)};"
        if source.get("unknown_source_count"):
            freshness += f" unknown {source.get('unknown_source_count')};"
    return (
        f"{source.get('status')} {source.get('family_count', 0)} families;{freshness} "
        f"fallback {source.get('fallback_source_count', 0)}, failed {source.get('failed_source_count', 0)}; "
        f"official/local {official}"
    )


def _live_summary(row: dict[str, Any]) -> str:
    evidence = row.get("live_forward_evidence") or {}
    return (
        f"model={evidence.get('model_review') or '-'}, "
        f"paper={evidence.get('paper_trading') or '-'}, "
        f"live={evidence.get('live_trade_permission') or '-'}"
    )


def _row_reason(row: dict[str, Any]) -> str:
    if row.get("ops_blockers"):
        return "; ".join(row.get("ops_blockers") or [])
    return "; ".join(row.get("model_reasons") or []) or row.get("promotion_reason") or "-"


def readiness_table_rows(payload: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for row in payload.get("markets") or []:
        trust = row.get("trust") or {}
        rows.append([
            row.get("market_id"),
            row.get("readiness_label"),
            row.get("model_label"),
            f"{(row.get('collection') or {}).get('state')} ({(row.get('collection') or {}).get('snapshots', 0)})",
            _source_summary(row),
            f"{trust.get('trust_score', '-')}/100 {trust.get('grade', '')}; ECE {fmt_num(trust.get('model_ece'))}",
            fmt_signed((row.get("candidate_vs_current") or {}).get("delta_vs_current"), 4),
            fmt_signed((row.get("candidate_vs_market") or {}).get("delta_vs_market"), 4),
            _quote_summary(row),
            _live_summary(row),
            ", ".join(row.get("hub_lessons") or []) or "-",
            _row_reason(row),
        ])
    return rows


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    broad = payload.get("broad_live_claim") or {}
    broad_blockers = broad.get("blockers") or []
    lines = [
        "# Cross-Hub Readiness Transfer And Promotion Guardrails",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Broad live claim allowed: `{broad.get('allowed')}`",
        "",
        "## Per-Market Readiness",
        "",
    ]
    lines += markdown_table(
        [
            "Market",
            "Readiness Label",
            "Model Label",
            "Collection",
            "Source Redundancy",
            "Trust/ECE",
            "Candidate vs Current",
            "Candidate vs Market",
            "Quoteability",
            "Live-Forward Evidence",
            "Hub Lessons",
            "Reason",
        ],
        readiness_table_rows(payload),
    )
    lines += ["", "## Broad Live Blockers", ""]
    if broad_blockers:
        lines += markdown_table(
            ["Gate", "Detail"],
            [[row.get("gate"), row.get("detail")] for row in broad_blockers],
        )
    else:
        lines += ["No broad live blockers."]
    diagnostics = payload.get("quoteability_diagnostics") or {}
    lines += [
        "",
        "## Quote Tape Diagnostics",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [[key, value] for key, value in sorted(diagnostics.items())],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_payload_from_paths(
    fleet_path: str | Path = DEFAULT_FLEET,
    promotion_path: str | Path = DEFAULT_PROMOTION,
    mm_paper_path: str | Path = DEFAULT_MM_PAPER,
    runs_root: str | Path = DEFAULT_MM_RUNS_ROOT,
    *,
    min_trust: int = DEFAULT_MIN_TRUST,
    max_ece: float = DEFAULT_MAX_ECE,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> dict[str, Any]:
    fleet = read_json(fleet_path, default={}) or {}
    promotion = read_json(promotion_path, default={}) or {}
    mm_paper = read_json(mm_paper_path, default={}) or {}
    run_folders = sorted((mm_paper.get("run_configs") or {}).keys()) or None
    quoteability = quoteability_from_runs(runs_root, run_folders=run_folders)
    latest = latest_run_summary(runs_root)
    payload = build_cross_hub_readiness(
        fleet,
        promotion,
        mm_paper,
        quoteability,
        latest,
        min_trust=min_trust,
        max_ece=max_ece,
        market_tol=market_tol,
    )
    payload["inputs"] = {
        "fleet": str(fleet_path),
        "promotion": str(promotion_path),
        "mm_paper": str(mm_paper_path),
        "runs_root": str(runs_root),
    }
    return payload


def run(args: argparse.Namespace) -> tuple[dict[str, Any], Path, Path]:
    payload = build_payload_from_paths(
        args.fleet,
        args.promotion,
        args.mm_paper,
        args.runs_root,
        min_trust=args.min_trust,
        max_ece=args.max_ece,
        market_tol=args.market_tol,
    )
    out = write_json_atomic(args.out, payload, trailing_newline=True)
    report = write_markdown_report(args.report, payload)
    return payload, out, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build cross-hub readiness and transfer guardrail report.")
    parser.add_argument("--fleet", default=str(DEFAULT_FLEET))
    parser.add_argument("--promotion", default=str(DEFAULT_PROMOTION))
    parser.add_argument("--mm-paper", default=str(DEFAULT_MM_PAPER))
    parser.add_argument("--runs-root", default=str(DEFAULT_MM_RUNS_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--min-trust", type=int, default=DEFAULT_MIN_TRUST)
    parser.add_argument("--max-ece", type=float, default=DEFAULT_MAX_ECE)
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

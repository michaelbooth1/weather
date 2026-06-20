"""Daily progress ledger for broad improvement claims."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from weather.io import write_json_atomic
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.reporting.trading_evidence import build_trading_evidence_summary


SCHEMA_VERSION = "daily_progress_ledger_v0.1"
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_JSONL_OUT = DEFAULT_BACKTEST_ROOT / "daily_progress_ledger.jsonl"
DEFAULT_CSV_OUT = DEFAULT_BACKTEST_ROOT / "daily_progress_ledger.csv"
DEFAULT_LATEST_OUT = DEFAULT_BACKTEST_ROOT / "daily_progress_latest.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "daily_progress_ledger_report.md"
BROAD_MIN_POSITIVE_SKILL_DAYS = 3
BROAD_MIN_PROMOTION_GRADE_MARKET_DAYS = 84
DISK_HEADROOM_RE = re.compile(
    r"free_bytes=(?P<free_bytes>\d+).*?required_free_bytes=(?P<required_free_bytes>\d+)"
)


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def json_field(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def maybe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def maybe_int(value):
    number = maybe_float(value)
    if number is None:
        return None
    return int(number)


def _artifact(backtest_root, name):
    return read_json(Path(backtest_root) / name)


def _disk_snapshot(backtest_root):
    usage = shutil.disk_usage(Path(backtest_root))
    return {
        "free_bytes": int(usage.free),
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.used),
    }


def _disk_preflight_from_failed_step(daily_refresh):
    for step in daily_refresh.get("steps") or []:
        if step.get("name") != "promotion_refresh" or step.get("status") != "error":
            continue
        text = " ".join(str(step.get(key) or "") for key in ("error", "traceback", "root_cause_class"))
        if "disk" not in text.lower() and "headroom" not in text.lower():
            continue
        match = DISK_HEADROOM_RE.search(text)
        if not match:
            return {
                "status": "BLOCK",
                "free_bytes": None,
                "required_free_bytes": None,
                "headroom_bytes": None,
                "insufficient_bytes": None,
            }
        free = maybe_int(match.group("free_bytes"))
        required = maybe_int(match.group("required_free_bytes"))
        return {
            "status": "BLOCK",
            "free_bytes": free,
            "required_free_bytes": required,
            "headroom_bytes": free - required if free is not None and required is not None else None,
            "insufficient_bytes": required - free if free is not None and required is not None else None,
        }
    return None


def _disk_preflight(daily_refresh, backtest_root):
    summary = daily_refresh.get("summary") or {}
    preflights = summary.get("disk_preflight") or {}
    promotion = preflights.get("promotion_refresh") or {}
    if promotion:
        free = maybe_int(promotion.get("free_bytes"))
        required = maybe_int(promotion.get("required_free_bytes"))
        return {
            "status": promotion.get("status"),
            "free_bytes": free,
            "required_free_bytes": required,
            "headroom_bytes": free - required if free is not None and required is not None else None,
            "insufficient_bytes": maybe_int(promotion.get("insufficient_bytes")),
        }
    failed_step_preflight = _disk_preflight_from_failed_step(daily_refresh)
    if failed_step_preflight:
        return failed_step_preflight
    disk = _disk_snapshot(backtest_root)
    return {
        "status": "OBSERVED",
        "free_bytes": disk["free_bytes"],
        "required_free_bytes": None,
        "headroom_bytes": None,
        "insufficient_bytes": None,
    }


def _independent_baseline_status(variant):
    if not variant:
        return "MISSING"
    if variant.get("delta_vs_baseline") is not None:
        return "PRESENT"
    evidence_sla = variant.get("evidence_sla") or {}
    reasons = [str(item).lower() for item in evidence_sla.get("reasons") or []]
    no_growth = variant.get("no_growth_reasons") or []
    no_growth_reasons = [str((item or {}).get("reason") or "").lower() for item in no_growth]
    if any("missing baseline" in reason or "no_baseline" in reason for reason in reasons + no_growth_reasons):
        return "MISSING"
    return "PRESENT" if variant.get("baseline") or variant.get("baseline_paths") else "MISSING"


def _quality_counts(daily_refresh):
    return (((daily_refresh.get("summary") or {}).get("labels") or {}).get("quality_counts") or {})


def _daily_refresh_status(daily_refresh):
    if not daily_refresh:
        return "missing"
    return daily_refresh.get("status") or "unknown"


def broad_claim_failures(row):
    failures = []
    if not bool(row.get("model_claim_allowed")):
        failures.append("core_model_trend_claim_not_allowed")
    if (row.get("model_positive_skill_days") or 0) < BROAD_MIN_POSITIVE_SKILL_DAYS:
        failures.append("positive_skill_days_below_3")
    rolling = row.get("model_rolling_daily_first_brier_skill")
    if rolling is None or rolling < 0:
        failures.append("rolling_daily_first_skill_negative")
    if (row.get("evidence_promotion_grade_market_days") or 0) < BROAD_MIN_PROMOTION_GRADE_MARKET_DAYS:
        failures.append("promotion_grade_market_days_below_84")
    if row.get("ops_live_forward_slo_status") != "PASS":
        failures.append("live_forward_slo_not_pass")
    if row.get("evidence_independent_baseline_status") != "PRESENT":
        failures.append("independent_baseline_missing")
    return failures


def build_progress_row(
    *,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    daily_refresh_status=None,
    generated_at_utc=None,
):
    backtest_root = Path(backtest_root)
    daily_refresh = daily_refresh_status or _artifact(backtest_root, "daily_refresh_status.json")
    progress = _artifact(backtest_root, "progress_audit.json")
    promotion = _artifact(backtest_root, "f_family_promotion_refresh.json")
    fleet = _artifact(backtest_root, "fleet_observability.json")
    variant = _artifact(backtest_root, "model_variant_evidence_growth.json")
    snapshot_eval = _artifact(backtest_root, "snapshot_evaluation.json")
    daily_learning = _artifact(backtest_root, "daily_learning.json")
    trading = build_trading_evidence_summary(
        mm_runs_root=backtest_root.parent / "mm_runs",
        taker_runs_root=backtest_root.parent / "taker_runs",
    )
    trend = progress.get("core_model_trend_claim") or {}
    trend_summary = trend.get("summary") or {}
    candidate = (promotion.get("candidate") or {})
    aggregate = candidate.get("aggregate") or {}
    corpus = promotion.get("corpus") or {}
    live_slo = fleet.get("live_forward_slo") or {}
    cadence = live_slo.get("snapshot_cadence_proof") or {}
    cadence_summary = cadence.get("summary") or {}
    source_status_summary = ((((fleet.get("collection") or {}).get("source_status_proof") or {}).get("summary")) or {})
    clob = (fleet.get("clob") or {}).get("loop") or {}
    observation = fleet.get("observation_trigger") or {}
    backup = fleet.get("tape_backup") or {}
    current_soak = fleet.get("current_code_soak") or {}
    disk = _disk_preflight(daily_refresh, backtest_root)
    mm = trading.get("market_making") or {}
    taker = trading.get("taker") or {}
    taker_quality = taker.get("quality_gate") or {}
    label_quality = _quality_counts(daily_refresh)
    row = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "run_date": str(
            daily_refresh.get("generated_at_utc")
            or daily_refresh.get("finished_at_utc")
            or generated_at_utc
            or utc_iso()
        )[:10],
        "daily_refresh_status": _daily_refresh_status(daily_refresh),
        "daily_refresh_duration_seconds": daily_refresh.get("duration_seconds"),
        "daily_refresh_blockers": json_field([
            {
                "step": step.get("name"),
                "status": step.get("status"),
                "error": step.get("error"),
                "root_cause_class": step.get("root_cause_class"),
            }
            for step in daily_refresh.get("steps") or []
            if step.get("status") == "error"
        ]),
        "model_claim_allowed": bool(trend.get("claim_allowed")),
        "model_claim_status": trend.get("status"),
        "model_rolling_daily_first_brier_skill": maybe_float(trend_summary.get("rolling_daily_first_brier_skill")),
        "model_positive_skill_days": maybe_int(trend_summary.get("positive_skill_days")),
        "model_positive_daily_first_days": maybe_int(trend_summary.get("positive_daily_first_days")),
        "model_minus_market_gap_slope_per_day": maybe_float(trend_summary.get("model_minus_market_brier_slope_per_day")),
        "model_brier_skill_slope_per_day": maybe_float(trend_summary.get("brier_skill_slope_per_day")),
        "candidate_delta_vs_current": maybe_float(aggregate.get("delta_vs_current")),
        "candidate_delta_vs_market": maybe_float(aggregate.get("delta_vs_market")),
        "candidate_verdict": candidate.get("verdict"),
        "candidate_cutover_decision": candidate.get("cutover_decision"),
        "evidence_complete_labels": maybe_int(label_quality.get("complete")),
        "evidence_label_total": maybe_int(((daily_refresh.get("summary") or {}).get("labels") or {}).get("total")),
        "evidence_promotion_grade_market_days": maybe_int(trend_summary.get("promotion_grade_market_days")),
        "evidence_corpus_market_days": maybe_int(corpus.get("market_day_count")),
        "evidence_corpus_snapshots": maybe_int(corpus.get("snapshot_count")),
        "evidence_snapshot_inventory_count": maybe_int(((snapshot_eval.get("snapshot_inventory") or {}).get("snapshot_count"))),
        "evidence_independent_baseline_status": _independent_baseline_status(variant),
        "evidence_variant_sla_status": ((variant.get("evidence_sla") or {}).get("status")),
        "ops_fleet_status": fleet.get("status"),
        "ops_live_forward_slo_status": live_slo.get("status"),
        "ops_live_forward_slo_counts": live_slo.get("counts_toward_live_forward_gate"),
        "ops_snapshot_gap_count": maybe_int(cadence_summary.get("total_gap_count")),
        "ops_snapshot_max_gap_minutes": maybe_float(cadence_summary.get("max_gap_minutes")),
        "ops_snapshot_gap_blocked_markets": maybe_int(cadence_summary.get("snapshot_coverage_gap_blocked_market_count")),
        "ops_source_status_blocked_markets": maybe_int(source_status_summary.get("source_status_blocked_market_count")),
        "ops_clob_status": clob.get("state"),
        "ops_observation_trigger_status": observation.get("state"),
        "ops_current_code_soak_status": current_soak.get("status"),
        "ops_backup_status": backup.get("status"),
        "ops_disk_preflight_status": disk.get("status"),
        "ops_disk_free_bytes": disk.get("free_bytes"),
        "ops_disk_required_free_bytes": disk.get("required_free_bytes"),
        "ops_disk_headroom_bytes": disk.get("headroom_bytes"),
        "trading_mm_evidence_mode": mm.get("evidence_mode"),
        "trading_mm_counts_toward_live_forward": mm.get("counts_toward_live_forward_gate"),
        "trading_mm_model_review_countable_markets": ((mm.get("model_review_evidence") or {}).get("countable_market_count")),
        "trading_mm_paper_countable_markets": ((mm.get("paper_trading_evidence") or {}).get("countable_market_count")),
        "trading_mm_live_trade_permission_countable_markets": ((mm.get("live_trade_permission_evidence") or {}).get("countable_market_count")),
        "trading_mm_quote_rows": mm.get("quote_rows"),
        "trading_mm_live_trade_permission_rows": mm.get("live_trade_permission_rows"),
        "trading_taker_fills": taker.get("filled_orders"),
        "trading_taker_net_pnl_usdc": taker.get("net_pnl_usdc"),
        "trading_taker_mark_to_market_pnl_usdc": taker.get("mark_to_market_pnl_usdc"),
        "trading_taker_root_cause": taker.get("root_cause_class"),
        "trading_taker_quality_status": taker_quality.get("status"),
        "daily_learning_status": daily_learning.get("status"),
    }
    failures = broad_claim_failures(row)
    row["broad_improvement_claim_allowed"] = not failures
    row["broad_improvement_claim_failures"] = json_field(failures)
    return row


def ledger_columns(row):
    return list(row.keys())


def append_jsonl(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    run_date = row.get("run_date")
    rows = [
        existing
        for existing in read_jsonl(path)
        if not run_date or existing.get("run_date") != run_date
    ]
    rows.append(row)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for existing in rows:
            handle.write(json.dumps(existing, sort_keys=True, default=str) + "\n")
    return path


def append_csv(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    run_date = row.get("run_date")
    rows = []
    if path.exists() and path.stat().st_size > 0:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = [
                existing
                for existing in csv.DictReader(handle)
                if not run_date or existing.get("run_date") != str(run_date)
            ]
    rows.append(row)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ledger_columns(row), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _avg(rows, key):
    values = [maybe_float(row.get(key)) for row in rows]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def fmt(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_report(rows):
    rows = list(rows or [])
    recent7 = rows[-7:]
    recent14 = rows[-14:]
    latest = rows[-1] if rows else {}
    lines = [
        "# Daily Progress Ledger",
        "",
        f"Rows: `{len(rows)}`",
        "",
        "## Latest Claim Gate",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Run date", latest.get("run_date") or "-"],
            ["Broad improvement claim allowed", latest.get("broad_improvement_claim_allowed")],
            ["Claim failures", latest.get("broad_improvement_claim_failures") or "[]"],
            ["Rolling daily-first skill", fmt(latest.get("model_rolling_daily_first_brier_skill"))],
            ["Positive skill days", latest.get("model_positive_skill_days")],
            ["Promotion-grade market-days", latest.get("evidence_promotion_grade_market_days")],
            ["Live-forward SLO", latest.get("ops_live_forward_slo_status") or "-"],
            ["Snapshot gaps", latest.get("ops_snapshot_gap_count")],
            ["Source-status blocked markets", latest.get("ops_source_status_blocked_markets")],
            ["Current-code soak", latest.get("ops_current_code_soak_status") or "-"],
            ["Disk preflight", latest.get("ops_disk_preflight_status") or "-"],
            ["Disk headroom bytes", latest.get("ops_disk_headroom_bytes")],
            ["Independent baseline", latest.get("evidence_independent_baseline_status") or "-"],
            ["MM evidence mode", latest.get("trading_mm_evidence_mode") or "-"],
            ["Taker quality", latest.get("trading_taker_quality_status") or "-"],
            ["Taker net P&L", fmt(latest.get("trading_taker_net_pnl_usdc"))],
        ],
    )
    lines += ["", "## 7 And 14 Day Rollup", ""]
    lines += markdown_table(
        ["Window", "Rows", "Claim Days", "Avg Rolling Skill", "Avg Snapshot Gaps", "Latest Taker P&L"],
        [
            [
                "7d",
                len(recent7),
                sum(1 for row in recent7 if row.get("broad_improvement_claim_allowed")),
                fmt(_avg(recent7, "model_rolling_daily_first_brier_skill")),
                fmt(_avg(recent7, "ops_snapshot_gap_count")),
                fmt(latest.get("trading_taker_net_pnl_usdc")),
            ],
            [
                "14d",
                len(recent14),
                sum(1 for row in recent14 if row.get("broad_improvement_claim_allowed")),
                fmt(_avg(recent14, "model_rolling_daily_first_brier_skill")),
                fmt(_avg(recent14, "ops_snapshot_gap_count")),
                fmt(latest.get("trading_taker_net_pnl_usdc")),
            ],
        ],
    )
    lines += ["", "## Recent Rows", ""]
    lines += markdown_table(
        [
            "Date", "Claim", "Rolling Skill", "Positive Days", "Promo Days",
            "Live SLO", "Snapshot Gaps", "MM Mode", "Taker P&L",
        ],
        [
            [
                row.get("run_date"),
                row.get("broad_improvement_claim_allowed"),
                fmt(row.get("model_rolling_daily_first_brier_skill")),
                row.get("model_positive_skill_days"),
                row.get("evidence_promotion_grade_market_days"),
                row.get("ops_live_forward_slo_status"),
                row.get("ops_snapshot_gap_count"),
                row.get("trading_mm_evidence_mode"),
                fmt(row.get("trading_taker_net_pnl_usdc")),
            ]
            for row in rows[-14:]
        ],
    )
    lines.append("")
    return "\n".join(lines)


def write_report(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(rows), encoding="utf-8")
    return path


def write_progress_outputs(
    row,
    *,
    jsonl_out=DEFAULT_JSONL_OUT,
    csv_out=DEFAULT_CSV_OUT,
    latest_out=DEFAULT_LATEST_OUT,
    report_out=DEFAULT_REPORT_OUT,
):
    jsonl_path = append_jsonl(jsonl_out, row)
    csv_path = append_csv(csv_out, row)
    latest_path = write_json_atomic(latest_out, row, trailing_newline=True)
    report_path = write_report(report_out, read_jsonl(jsonl_path))
    return {
        "status": "OK",
        "jsonl_out": str(jsonl_path),
        "csv_out": str(csv_path),
        "latest_out": str(latest_path),
        "report_out": str(report_path),
        "broad_improvement_claim_allowed": row.get("broad_improvement_claim_allowed"),
        "broad_improvement_claim_failures": json.loads(row.get("broad_improvement_claim_failures") or "[]"),
    }


def build_parser():
    parser = argparse.ArgumentParser(description="Append one daily progress ledger row.")
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--jsonl-out", default=str(DEFAULT_JSONL_OUT))
    parser.add_argument("--csv-out", default=str(DEFAULT_CSV_OUT))
    parser.add_argument("--latest-out", default=str(DEFAULT_LATEST_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    row = build_progress_row(backtest_root=args.backtest_root, snapshots_root=args.snapshots_root)
    result = write_progress_outputs(
        row,
        jsonl_out=args.jsonl_out,
        csv_out=args.csv_out,
        latest_out=args.latest_out,
        report_out=args.report_out,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

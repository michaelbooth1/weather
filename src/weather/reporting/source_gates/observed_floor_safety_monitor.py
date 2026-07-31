"""Fail-closed settlement monitor for captured served hard floors."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.backtesting.settlement_ledger import DEFAULT_LABELS_CSV
from weather.io import write_json_atomic
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("observed_floor_safety_monitor")
DEFAULT_JSON_OUT = data_path("backtest", "observed_floor_safety_monitor.json")
DEFAULT_REPORT_OUT = data_path("backtest", "observed_floor_safety_monitor.md")
EXPLANATIONS_FILENAME = "snapshot_explanations.jsonl"


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _maybe_int(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not number.is_integer():
        return None
    return int(number)


def _read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _recorded_path(value, *, labels_csv):
    path = Path(str(value or ""))
    if not path.is_absolute():
        path = Path(labels_csv).parent / path
    return path


def _market_ids(value):
    if not value:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    return {part.strip() for part in str(value).split(",") if part.strip()}


def _snapshot_ids(path):
    rows = _read_csv(path)
    return {
        str(row.get("snapshot_id") or "").strip()
        for row in rows
        if str(row.get("snapshot_id") or "").strip()
    }


def _explanation_rows(path):
    rows = []
    issues = []
    path = Path(path)
    if not path.exists():
        return rows, [{"reason": "snapshot_explanations_missing", "path": str(path)}]
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                issues.append({
                    "reason": "snapshot_explanation_invalid_json",
                    "path": str(path),
                    "line": line_number,
                    "error": str(exc),
                })
                continue
            rows.append(payload)
    return rows, issues


def _floor_source(context, floor_bucket):
    effective = _maybe_int(context.get("effective_observed_floor_bucket"))
    validated = _maybe_int(context.get("validated_current_max_floor_bucket"))
    if effective == floor_bucket:
        source = str(context.get("effective_observed_high_source") or "").strip()
        if source:
            return source
    if validated == floor_bucket:
        return "validated_current_max_floor"
    return None


def _build_market_rows(label, *, labels_csv):
    market_id = str(label.get("market_id") or "").strip()
    event_slug = str(label.get("event_slug") or "").strip()
    target_date = str(label.get("target_date") or "")[:10]
    settlement_bucket = _maybe_int(label.get("settlement_bucket"))
    tape = _recorded_path(label.get("snapshot_tape_path"), labels_csv=labels_csv)
    explanation_path = tape.with_name(EXPLANATIONS_FILENAME)
    issues = []
    rows = []
    snapshot_ids = set()
    floorless_count = 0

    if not market_id:
        issues.append({"reason": "market_id_missing", "event_slug": event_slug})
    if settlement_bucket is None:
        issues.append({
            "reason": "settlement_bucket_missing_or_invalid",
            "market_id": market_id,
            "target_date": target_date,
        })
    if not str(label.get("snapshot_tape_path") or "").strip():
        issues.append({
            "reason": "snapshot_tape_path_missing",
            "market_id": market_id,
            "target_date": target_date,
        })
    elif not tape.exists():
        issues.append({
            "reason": "snapshot_tape_missing",
            "market_id": market_id,
            "target_date": target_date,
            "path": str(tape),
        })
    else:
        snapshot_ids = _snapshot_ids(tape)
        if not snapshot_ids:
            issues.append({
                "reason": "snapshot_tape_has_no_snapshot_ids",
                "market_id": market_id,
                "target_date": target_date,
                "path": str(tape),
            })

    explanations, explanation_issues = _explanation_rows(explanation_path)
    for issue in explanation_issues:
        issues.append({
            "market_id": market_id,
            "target_date": target_date,
            **issue,
        })
    by_snapshot = defaultdict(list)
    for payload in explanations:
        payload_target = str(payload.get("target_date") or "")[:10]
        if not payload_target:
            issues.append({
                "reason": "snapshot_explanation_target_date_missing",
                "market_id": market_id,
                "target_date": target_date,
                "snapshot_id": str(payload.get("snapshot_id") or "").strip(),
                "path": str(explanation_path),
            })
            continue
        if payload_target != target_date:
            continue
        snapshot_id = str(payload.get("snapshot_id") or "").strip()
        if snapshot_id:
            by_snapshot[snapshot_id].append(payload)

    for snapshot_id in sorted(snapshot_ids):
        matches = by_snapshot.get(snapshot_id) or []
        if len(matches) != 1:
            issues.append({
                "reason": (
                    "snapshot_explanation_missing"
                    if not matches
                    else "snapshot_explanation_duplicate"
                ),
                "market_id": market_id,
                "target_date": target_date,
                "snapshot_id": snapshot_id,
                "match_count": len(matches),
                "path": str(explanation_path),
            })
            continue
        payload = matches[0]
        payload_market = str(payload.get("market_id") or "").strip()
        if payload_market != market_id:
            issues.append({
                "reason": "snapshot_explanation_market_mismatch",
                "market_id": market_id,
                "observed_market_id": payload_market,
                "target_date": target_date,
                "snapshot_id": snapshot_id,
                "path": str(explanation_path),
            })
            continue
        context = (
            (payload.get("explanations") or {}).get(
                "probability_calibration_context"
            )
            or {}
        )
        if not context:
            issues.append({
                "reason": "probability_calibration_context_missing",
                "market_id": market_id,
                "target_date": target_date,
                "snapshot_id": snapshot_id,
                "path": str(explanation_path),
            })
            continue
        raw_floor = context.get("observed_floor_bucket")
        floor_bucket = _maybe_int(raw_floor)
        if raw_floor not in (None, "") and floor_bucket is None:
            issues.append({
                "reason": "observed_floor_bucket_invalid",
                "market_id": market_id,
                "target_date": target_date,
                "snapshot_id": snapshot_id,
                "value": raw_floor,
            })
            continue
        if floor_bucket is None:
            floorless_count += 1
            continue
        source = _floor_source(context, floor_bucket)
        if not source:
            issues.append({
                "reason": "observed_floor_source_unattributed",
                "market_id": market_id,
                "target_date": target_date,
                "snapshot_id": snapshot_id,
                "floor_bucket": floor_bucket,
            })
            source = "unattributed_hard_floor"
        if settlement_bucket is None:
            continue
        overshoot = floor_bucket - settlement_bucket
        rows.append({
            "market_id": market_id,
            "event_slug": event_slug,
            "target_date": target_date,
            "snapshot_id": snapshot_id,
            "floor_bucket": floor_bucket,
            "settlement_bucket": settlement_bucket,
            "rescue_source": source,
            "overshoot_buckets": overshoot,
            "over_final": overshoot > 0,
        })

    unexpected = sorted(set(by_snapshot) - snapshot_ids)
    if unexpected:
        issues.append({
            "reason": "snapshot_explanation_without_tape_snapshot",
            "market_id": market_id,
            "target_date": target_date,
            "snapshot_ids": unexpected[:25],
            "count": len(unexpected),
            "path": str(explanation_path),
        })
    return rows, issues, len(snapshot_ids), floorless_count


def build_payload(
    *,
    labels_csv=DEFAULT_LABELS_CSV,
    target_date,
    markets=None,
    generated_at_utc=None,
):
    target_date = str(target_date)[:10]
    requested_markets = _market_ids(markets)
    labels = [
        row
        for row in _read_csv(labels_csv)
        if str(row.get("target_date") or "")[:10] == target_date
        and (
            not requested_markets
            or str(row.get("market_id") or "").strip() in requested_markets
        )
    ]
    issues = []
    rows = []
    snapshot_count = 0
    floorless_snapshot_count = 0
    if not Path(labels_csv).exists():
        issues.append({"reason": "settlement_labels_missing", "path": str(labels_csv)})
    elif not labels:
        issues.append({
            "reason": "settlement_labels_missing_for_target_date",
            "target_date": target_date,
            "markets": sorted(requested_markets),
            "path": str(labels_csv),
        })
    found_markets = {
        str(row.get("market_id") or "").strip()
        for row in labels
        if str(row.get("market_id") or "").strip()
    }
    for market_id in sorted(requested_markets - found_markets):
        issues.append({
            "reason": "settlement_label_missing_for_requested_market",
            "market_id": market_id,
            "target_date": target_date,
            "path": str(labels_csv),
        })

    label_keys = Counter(
        (str(row.get("market_id") or ""), str(row.get("event_slug") or ""))
        for row in labels
    )
    for key, count in sorted(label_keys.items()):
        if count > 1:
            issues.append({
                "reason": "duplicate_settlement_label",
                "market_id": key[0],
                "event_slug": key[1],
                "target_date": target_date,
                "count": count,
            })

    for label in labels:
        (
            market_rows,
            market_issues,
            market_snapshot_count,
            market_floorless_count,
        ) = _build_market_rows(
            label,
            labels_csv=labels_csv,
        )
        rows.extend(market_rows)
        issues.extend(market_issues)
        snapshot_count += market_snapshot_count
        floorless_snapshot_count += market_floorless_count

    alerts = [row for row in rows if row.get("over_final")]
    if alerts:
        status = "ALERT"
    elif issues:
        status = "BLOCK"
    else:
        status = "PASS"

    by_market = []
    for market_id in sorted({str(row.get("market_id")) for row in labels}):
        market_rows = [row for row in rows if row.get("market_id") == market_id]
        market_alerts = [row for row in market_rows if row.get("over_final")]
        by_market.append({
            "market_id": market_id,
            "enforced_floor_count": len(market_rows),
            "over_final_count": len(market_alerts),
            "max_overshoot_buckets": max(
                (row.get("overshoot_buckets") or 0 for row in market_alerts),
                default=0,
            ),
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or _utc_iso(),
        "status": status,
        "hard_stop_pipeline": status != "PASS",
        "target_date": target_date,
        "labels_csv": str(labels_csv),
        "summary": {
            "label_count": len(labels),
            "snapshot_count": snapshot_count,
            "enforced_floor_count": len(rows),
            "floorless_snapshot_count": floorless_snapshot_count,
            "over_final_count": len(alerts),
            "evidence_blocker_count": len(issues),
            "rescue_source_counts": dict(sorted(Counter(
                row.get("rescue_source") or "unknown" for row in rows
            ).items())),
        },
        "by_market": by_market,
        "alerts": alerts,
        "evidence_blockers": issues,
        "rows": rows,
    }


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Observed Floor Safety Monitor",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Target date: `{payload.get('target_date')}`",
        f"Status: **{payload.get('status')}**",
        f"Hard stop: **{payload.get('hard_stop_pipeline')}**",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Settlement labels", summary.get("label_count")],
            ["Captured snapshots", summary.get("snapshot_count")],
            ["Enforced floors", summary.get("enforced_floor_count")],
            ["Floorless snapshots", summary.get("floorless_snapshot_count")],
            ["Over-final floors", summary.get("over_final_count")],
            ["Evidence blockers", summary.get("evidence_blocker_count")],
        ],
    )
    lines += ["", "## By Market", ""]
    lines += markdown_table(
        ["Market", "Enforced floors", "Over final", "Max overshoot (buckets)"],
        [
            [
                row.get("market_id"),
                row.get("enforced_floor_count"),
                row.get("over_final_count"),
                row.get("max_overshoot_buckets"),
            ]
            for row in payload.get("by_market") or []
        ],
    )
    alerts = payload.get("alerts") or []
    if alerts:
        lines += ["", "## OVER-FINAL ALERTS", ""]
        lines += markdown_table(
            ["Market", "Date", "Snapshot", "Floor", "Settlement", "Rescue source", "Overshoot"],
            [
                [
                    row.get("market_id"),
                    row.get("target_date"),
                    row.get("snapshot_id"),
                    row.get("floor_bucket"),
                    row.get("settlement_bucket"),
                    row.get("rescue_source"),
                    row.get("overshoot_buckets"),
                ]
                for row in alerts
            ],
        )
    blockers = payload.get("evidence_blockers") or []
    if blockers:
        lines += ["", "## Evidence Blockers", "", "```json"]
        lines.append(json.dumps(blockers, indent=2, sort_keys=True))
        lines += ["```"]
    lines += [
        "",
        "This monitor reads captured snapshot explanations and finalized settlement labels; it does not replay the model.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(payload, *, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT):
    json_path = write_json_atomic(json_out, payload, trailing_newline=True)
    report_path = Path(report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def build_parser():
    parser = argparse.ArgumentParser(
        description="Join captured served hard floors to final settlement and fail closed on any overshoot."
    )
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--markets", default="")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    payload = build_payload(
        labels_csv=args.labels_csv,
        target_date=args.target_date,
        markets=args.markets,
    )
    json_out, report_out = write_outputs(
        payload,
        json_out=args.json_out,
        report_out=args.report_out,
    )
    print(f"Observed floor safety monitor: {payload.get('status')}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return 0 if payload.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

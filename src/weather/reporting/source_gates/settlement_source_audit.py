"""Settlement-source revision and truth-label audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from weather.backtesting.settlement_ledger import (
    DEFAULT_LABELS_CSV,
    DEFAULT_LEDGER_ROOT,
    parse_band_label,
)
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("settlement_source_revision_audit")
DEFAULT_JSON_OUT = data_path("backtest", "settlement_source_revision_audit.json")
DEFAULT_REPORT_OUT = data_path("backtest", "settlement_source_revision_audit.md")
UNCERTAIN_STATUSES = {
    "PROVISIONAL",
    "SOURCE_STALE",
    "SOURCE_REVISION",
    "SOURCE_DISAGREEMENT",
    "MANUAL_OVERRIDE",
    "UNRECONCILED",
}


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl(path):
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


def _ledger_rows(root):
    rows = []
    root = Path(root)
    for path in sorted(root.glob("*/ledger.jsonl")):
        for row in _read_jsonl(path):
            row = dict(row)
            row.setdefault("ledger_path", str(path))
            rows.append(row)
    return rows


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _parse_time(value):
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _maybe_int(value):
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first_present(row, keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _sha256(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _lineage_entry(name, path, missing_reason):
    if path:
        candidate = Path(path)
        if candidate.exists():
            return {
                "source": name,
                "path": str(candidate),
                "sha256": _sha256(candidate),
                "missing_payload_reason": "",
                "status": "HASHED",
            }
        return {
            "source": name,
            "path": str(candidate),
            "sha256": "",
            "missing_payload_reason": "path_not_found",
            "status": "MISSING_WITH_REASON",
        }
    return {
        "source": name,
        "path": "",
        "sha256": "",
        "missing_payload_reason": missing_reason,
        "status": "MISSING_WITH_REASON",
    }


def _lineage(row):
    entries = [
        _lineage_entry(
            "wu_daily_summary",
            row.get("daily_summary_path"),
            "daily_summary_path_not_recorded",
        ),
        _lineage_entry(
            "snapshot_tape",
            row.get("snapshot_tape_path"),
            "snapshot_tape_path_not_recorded",
        ),
        _lineage_entry(
            "canonical_settlement_ledger",
            row.get("ledger_path"),
            "ledger_path_not_recorded",
        ),
        _lineage_entry(
            "weather_com_max_since_7",
            _first_present(row, ("weather_com_raw_payload_path", "weather_com_payload_path")),
            "weather_com_raw_payload_not_recorded",
        ),
        _lineage_entry(
            "market_resolution",
            _first_present(row, ("market_resolution_payload_path", "gamma_event_payload_path")),
            "market_resolution_raw_payload_not_recorded",
        ),
    ]
    return {
        "status": "PASS" if all(entry.get("sha256") or entry.get("missing_payload_reason") for entry in entries) else "BLOCK",
        "entries": entries,
        "hashed_source_count": sum(1 for entry in entries if entry.get("sha256")),
        "missing_with_reason_count": sum(
            1 for entry in entries
            if not entry.get("sha256") and entry.get("missing_payload_reason")
        ),
    }


def _bucket_from_note(note, pattern):
    match = re.search(pattern, str(note or ""), flags=re.IGNORECASE)
    if not match:
        return None
    return _maybe_int(match.group(1))


def _market_resolution_bucket(row):
    label = row.get("polymarket_winning_band") or row.get("market_resolution_label")
    parsed = parse_band_label(label)
    if parsed.get("kind") == "eq" and parsed.get("value") == parsed.get("value_hi"):
        return parsed.get("value")
    return None


def _source_buckets(row):
    note = row.get("note") or ""
    canonical = _maybe_int(row.get("settlement_bucket"))
    wu_final = _maybe_int(_first_present(row, (
        "wu_final_bucket",
        "wu_daily_summary_bucket",
        "daily_summary_bucket",
    )))
    snapshot = _maybe_int(_first_present(row, (
        "snapshot_high_bucket",
        "settlement_normalized_live_high_bucket",
    )))
    weather_com = _maybe_int(_first_present(row, (
        "weather_com_max_since_7_bucket",
        "weather_com_bucket",
    )))
    live_normalized = _maybe_int(_first_present(row, (
        "settlement_current_high",
        "settlement_normalized_live_high",
    )))
    note_daily = _bucket_from_note(note, r"daily_summary\s*=\s*(-?\d+)")
    note_snapshot = _bucket_from_note(note, r"snapshot high\s*=\s*(-?\d+)")
    if wu_final is None and row.get("settlement_source") == "daily_summary":
        wu_final = canonical
    if wu_final is None:
        wu_final = note_daily
    if snapshot is None:
        snapshot = note_snapshot
    market_resolution = _market_resolution_bucket(row)
    buckets = {
        "canonical_ledger": canonical,
        "wu_final": wu_final,
        "weather_com_max_since_7": weather_com,
        "settlement_normalized_live_high": live_normalized,
        "snapshot_high": snapshot,
        "market_resolution": market_resolution,
    }
    return {key: value for key, value in buckets.items() if value is not None}


def _finalization_lag_hours(row):
    finalized = _parse_time(row.get("finalized_at_utc"))
    target_date = row.get("target_date")
    if not finalized or not target_date:
        return None
    tz_name = row.get("resolution_timezone") or "UTC"
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    try:
        date_value = datetime.fromisoformat(str(target_date)).date()
    except ValueError:
        return None
    local_close = datetime.combine(date_value, time(23, 59, 59), tzinfo=zone)
    return round((finalized - local_close.astimezone(timezone.utc)).total_seconds() / 3600.0, 6)


def _classify(row, buckets, disagreement_sources):
    quality = str(row.get("quality_grade") or "").strip().lower()
    source = str(row.get("settlement_source") or "").strip().lower()
    reconciliation = str(row.get("reconciliation_status") or "").strip().lower()
    note = str(row.get("note") or "").lower()
    if buckets.get("canonical_ledger") is None:
        return "UNRECONCILED"
    if quality == "manual_override" or source == "override":
        return "MANUAL_OVERRIDE"
    if quality == "stale_source":
        return "SOURCE_STALE"
    if reconciliation == "mismatch":
        return "SOURCE_DISAGREEMENT"
    if disagreement_sources:
        return "SOURCE_REVISION" if "disagrees" in note or "revision" in note else "SOURCE_DISAGREEMENT"
    if quality and quality != "complete":
        return "PROVISIONAL"
    if reconciliation in {"fetch_error", "unavailable", "not_requested"}:
        return "UNRECONCILED"
    return "FINALIZED"


def _merge_label_and_ledger_rows(label_rows, ledger_rows):
    ledger_by_slug = {row.get("event_slug"): row for row in ledger_rows if row.get("event_slug")}
    labels_by_slug = {row.get("event_slug"): row for row in label_rows if row.get("event_slug")}
    slugs = sorted(set(ledger_by_slug) | set(labels_by_slug))
    rows = []
    for slug in slugs:
        merged = dict(ledger_by_slug.get(slug) or {})
        for key, value in (labels_by_slug.get(slug) or {}).items():
            if value not in (None, ""):
                merged[key] = value
        rows.append(merged)
    return rows


def audit_row(row):
    buckets = _source_buckets(row)
    canonical = buckets.get("canonical_ledger")
    disagreement_sources = [
        source for source, bucket in buckets.items()
        if source != "canonical_ledger" and canonical is not None and bucket != canonical
    ]
    lineage = _lineage(row)
    status = _classify(row, buckets, disagreement_sources)
    alternate_buckets = sorted({
        bucket for source, bucket in buckets.items()
        if source != "canonical_ledger" and canonical is not None and bucket != canonical
    })
    alternate_changes = bool(alternate_buckets)
    proof_grade = status == "FINALIZED" and lineage["status"] == "PASS" and not alternate_changes
    return {
        "event_slug": row.get("event_slug"),
        "market_id": row.get("market_id"),
        "target_date": row.get("target_date"),
        "settlement_source": row.get("settlement_source"),
        "quality_grade": row.get("quality_grade"),
        "status": status,
        "proof_grade_label": proof_grade,
        "promotion_blocker": not proof_grade,
        "promotion_blocker_reason": "" if proof_grade else status.lower(),
        "finalization_lag_hours": _finalization_lag_hours(row),
        "reconciliation_status": row.get("reconciliation_status"),
        "canonical_settlement_bucket": canonical,
        "source_buckets": buckets,
        "disagreement_sources": disagreement_sources,
        "source_disagreement_count": len(disagreement_sources),
        "alternate_buckets": alternate_buckets,
        "alternate_label_sensitivity_status": (
            "CHANGES_RESULT" if alternate_changes else "NO_ALTERNATE_LABEL"
        ),
        "alternate_label_changes_result": alternate_changes,
        "lineage_status": lineage["status"],
        "lineage_hashed_source_count": lineage["hashed_source_count"],
        "lineage_missing_with_reason_count": lineage["missing_with_reason_count"],
        "lineage": lineage["entries"],
        "note": row.get("note") or "",
        "finalized_at_utc": row.get("finalized_at_utc") or "",
    }


def build_settlement_source_audit(
    *,
    labels_csv=DEFAULT_LABELS_CSV,
    ledger_root=DEFAULT_LEDGER_ROOT,
    generated_at_utc=None,
):
    label_rows = _read_csv(labels_csv)
    ledger = _ledger_rows(ledger_root)
    rows = [audit_row(row) for row in _merge_label_and_ledger_rows(label_rows, ledger)]
    status_counts = Counter(row["status"] for row in rows)
    by_market = defaultdict(Counter)
    lag_by_market = defaultdict(list)
    for row in rows:
        market_id = row.get("market_id") or "unknown"
        by_market[market_id][row["status"]] += 1
        if row.get("finalization_lag_hours") is not None:
            lag_by_market[market_id].append(row["finalization_lag_hours"])
    market_rows = []
    for market_id in sorted(by_market):
        lags = lag_by_market.get(market_id) or []
        market_rows.append({
            "market_id": market_id,
            "label_count": sum(by_market[market_id].values()),
            "finalized_count": by_market[market_id].get("FINALIZED", 0),
            "uncertain_count": sum(
                count for status, count in by_market[market_id].items()
                if status in UNCERTAIN_STATUSES
            ),
            "source_disagreement_count": sum(
                1 for row in rows
                if row.get("market_id") == market_id and row.get("source_disagreement_count")
            ),
            "max_finalization_lag_hours": max(lags) if lags else None,
            "status_counts": dict(sorted(by_market[market_id].items())),
        })
    proof_blocked = [row for row in rows if row.get("promotion_blocker")]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or _utc_iso(),
        "labels_csv": str(labels_csv),
        "ledger_root": str(ledger_root),
        "status": "MISSING" if not rows else ("BLOCK" if proof_blocked else "PASS"),
        "summary": {
            "label_count": len(rows),
            "finalized_label_count": status_counts.get("FINALIZED", 0),
            "provisional_label_count": status_counts.get("PROVISIONAL", 0),
            "revised_label_count": status_counts.get("SOURCE_REVISION", 0),
            "source_disagreement_label_count": status_counts.get("SOURCE_DISAGREEMENT", 0),
            "manual_override_label_count": status_counts.get("MANUAL_OVERRIDE", 0),
            "unreconciled_label_count": status_counts.get("UNRECONCILED", 0),
            "source_stale_label_count": status_counts.get("SOURCE_STALE", 0),
            "proof_grade_label_count": sum(1 for row in rows if row.get("proof_grade_label")),
            "promotion_blocked_label_count": len(proof_blocked),
            "alternate_label_changes_result_count": sum(
                1 for row in rows if row.get("alternate_label_changes_result")
            ),
            "lineage_missing_with_reason_count": sum(
                row.get("lineage_missing_with_reason_count") or 0 for row in rows
            ),
            "status_counts": dict(sorted(status_counts.items())),
        },
        "by_market": market_rows,
        "rows": rows,
    }


def settlement_label_gate_for_target_dates(payload, target_dates):
    target_dates = sorted({str(value) for value in (target_dates or []) if value})
    if not target_dates:
        return {
            "status": "SKIP",
            "target_dates": [],
            "blocked_target_dates": [],
            "blockers": [],
            "reason": "no settlement-scored target dates",
        }
    if not payload or not payload.get("rows"):
        return {
            "status": "BLOCK",
            "target_dates": target_dates,
            "blocked_target_dates": target_dates,
            "blockers": ["settlement_source_audit_missing"],
            "reason": "settlement-scored evidence has no truth-label audit rows",
        }
    rows_by_date = defaultdict(list)
    for row in payload.get("rows") or []:
        rows_by_date[str(row.get("target_date") or "")].append(row)
    blockers = []
    blocked_dates = []
    for target_date in target_dates:
        rows = rows_by_date.get(target_date) or []
        if not rows:
            blocked_dates.append(target_date)
            blockers.append(f"{target_date}:missing_audit_row")
            continue
        bad = [row for row in rows if row.get("promotion_blocker")]
        if bad:
            blocked_dates.append(target_date)
            blockers.extend(
                f"{target_date}:{row.get('market_id') or 'unknown'}:{row.get('status')}"
                for row in bad
            )
    return {
        "status": "BLOCK" if blockers else "PASS",
        "target_dates": target_dates,
        "blocked_target_dates": blocked_dates,
        "blockers": blockers,
        "reason": "truth-label uncertainty blocks promotion-grade evidence" if blockers else "truth labels proof-grade",
    }


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Settlement Source Revision Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Labels", summary.get("label_count")],
            ["Finalized", summary.get("finalized_label_count")],
            ["Provisional", summary.get("provisional_label_count")],
            ["Revised", summary.get("revised_label_count")],
            ["Source disagreement", summary.get("source_disagreement_label_count")],
            ["Manual overrides", summary.get("manual_override_label_count")],
            ["Unreconciled", summary.get("unreconciled_label_count")],
            ["Proof-grade", summary.get("proof_grade_label_count")],
            ["Promotion blocked", summary.get("promotion_blocked_label_count")],
            ["Alternate-label changes result", summary.get("alternate_label_changes_result_count")],
        ],
    )
    lines += ["", "## By Market", ""]
    lines += markdown_table(
        ["Market", "Labels", "Finalized", "Uncertain", "Disagreements", "Max Finalization Lag Hours"],
        [
            [
                row.get("market_id"),
                row.get("label_count"),
                row.get("finalized_count"),
                row.get("uncertain_count"),
                row.get("source_disagreement_count"),
                row.get("max_finalization_lag_hours"),
            ]
            for row in payload.get("by_market") or []
        ],
    )
    blockers = [row for row in payload.get("rows") or [] if row.get("promotion_blocker")]
    if blockers:
        lines += ["", "## Promotion Blockers", ""]
        lines += markdown_table(
            ["Date", "Market", "Status", "Canonical", "Disagreement Sources", "Alternate Sensitivity"],
            [
                [
                    row.get("target_date"),
                    row.get("market_id"),
                    row.get("status"),
                    row.get("canonical_settlement_bucket"),
                    ", ".join(row.get("disagreement_sources") or []) or "-",
                    row.get("alternate_label_sensitivity_status"),
                ]
                for row in blockers[:50]
            ],
        )
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT):
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def build_parser():
    parser = argparse.ArgumentParser(description="Build settlement-source revision audit.")
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    payload = build_settlement_source_audit(
        labels_csv=args.labels_csv,
        ledger_root=args.ledger_root,
    )
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Settlement source audit: {payload.get('status')}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Audit large model-vs-market band disagreements against settlement.

The audit is intentionally narrow: it records a durable row when the model
probability and market YES price differ by a configured number of full
percentage points. Once settlement is available, the settled YES/NO outcome is
the fair value used to decide whether the model or market was closer.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.backtesting.settlement_io import (
    load_market_day_label,
    resolve_outcome,
    row_band_value_hi,
)
from weather.backtesting.settlement_ledger import parse_band_label
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug
from weather.paths import data_path
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("model_market_disagreement_audit")
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_LOG_PATH = data_path() / "backtest" / "model_market_disagreement_audit.jsonl"
DEFAULT_GAP_THRESHOLD_POINTS = 50.0
SNAPSHOT_FILENAME = "snapshots_long.csv"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def compact_float(value: Any, digits: int = 6) -> float | None:
    number = safe_float(value)
    if number is None:
        return None
    return round(number, digits)


def clean_label(label: Any) -> str:
    text = str(label or "")
    for bad in ("\u00c2", "\ufffd"):
        text = text.replace(bad, "")
    for degree in ("\u00b0", "\u00ba"):
        text = text.replace(degree, " ")
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()


def normalized_label(label: Any) -> str:
    return " ".join(clean_label(label).casefold().split())


def format_band_value(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return ""
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.6g}"


def first_float(row: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        number = safe_float(row.get(name))
        if number is not None:
            return number
    return None


def band_parts(row: dict[str, Any]) -> tuple[str | None, float | None, float | None]:
    parsed = parse_band_label(clean_label(row.get("range_label")))
    kind = str(row.get("bin_kind") or parsed.get("kind") or "").strip().lower() or None
    value = first_float(row, ("bin_value_c", "bin_value"))
    if value is None:
        value = safe_float(parsed.get("value"))

    value_hi = first_float(row, ("bin_value_hi_c", "bin_value_hi"))
    if value_hi is None:
        try:
            value_hi = safe_float(row_band_value_hi(row))
        except Exception:  # noqa: BLE001 - malformed labels should not kill the audit
            value_hi = None
    if value_hi is None:
        value_hi = safe_float(parsed.get("value_hi"))
    if value_hi is None:
        value_hi = value
    return kind, value, value_hi


def band_key_text(row: dict[str, Any]) -> str:
    kind, value, value_hi = band_parts(row)
    if not kind:
        kind = "unknown"
    value_text = format_band_value(value)
    value_hi_text = format_band_value(value_hi)
    if kind == "eq" and value_hi_text and value_hi_text != value_text:
        return f"{kind}:{value_text}-{value_hi_text}"
    return f"{kind}:{value_text}"


def audit_key_for_row(
    row: dict[str, Any],
    *,
    gap_threshold_points: float = DEFAULT_GAP_THRESHOLD_POINTS,
) -> str:
    parts = [
        str(row.get("event_slug") or ""),
        str(row.get("snapshot_id") or ""),
        band_key_text(row),
        normalized_label(row.get("range_label")),
        f"{float(gap_threshold_points):.6f}",
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"mma_{digest}"


def read_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_snapshot_rows(
    folder: str | Path,
    *,
    latest_only: bool = True,
    range_label: str | None = None,
    snapshot_id: str | None = None,
) -> list[dict[str, Any]]:
    folder = Path(folder)
    rows = read_csv_rows(folder / SNAPSHOT_FILENAME)
    for row in rows:
        row["_folder"] = str(folder)
        if not row.get("event_slug"):
            row["event_slug"] = folder.name

    if snapshot_id:
        rows = [row for row in rows if str(row.get("snapshot_id") or "") == str(snapshot_id)]
    elif latest_only and rows:
        latest_snapshot_id = next(
            (str(row.get("snapshot_id") or "") for row in reversed(rows) if row.get("snapshot_id")),
            "",
        )
        rows = [row for row in rows if str(row.get("snapshot_id") or "") == latest_snapshot_id]

    if range_label:
        wanted = normalized_label(range_label)
        rows = [row for row in rows if normalized_label(row.get("range_label")) == wanted]
    return rows


def selected_folders(
    folders: list[str | Path] | None = None,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    event_slug: str | None = None,
    market_id: str | None = None,
) -> list[Path]:
    if folders:
        candidates = [Path(folder) for folder in folders]
    else:
        root = Path(snapshots_root)
        if event_slug:
            candidates = [root / event_slug]
        elif root.exists():
            candidates = sorted(path for path in root.iterdir() if path.is_dir())
        else:
            candidates = []
    output = []
    for folder in candidates:
        if not (folder / SNAPSHOT_FILENAME).exists():
            continue
        spec = spec_for_slug(folder.name)
        if market_id and (spec.id if spec else None) != market_id:
            continue
        output.append(folder)
    return output


def row_gap_points(row: dict[str, Any]) -> float | None:
    model_probability = safe_float(row.get("model_probability"))
    market_yes = safe_float(row.get("market_yes"))
    if model_probability is None or market_yes is None:
        return None
    return abs(model_probability - market_yes) * 100.0


def triggered_rows(
    folder: str | Path,
    *,
    gap_threshold_points: float = DEFAULT_GAP_THRESHOLD_POINTS,
    latest_only: bool = True,
    range_label: str | None = None,
    snapshot_id: str | None = None,
) -> list[dict[str, Any]]:
    threshold = float(gap_threshold_points)
    rows = read_snapshot_rows(
        folder,
        latest_only=latest_only,
        range_label=range_label,
        snapshot_id=snapshot_id,
    )
    return [
        row for row in rows
        if (row_gap_points(row) is not None and row_gap_points(row) + 1e-9 >= threshold)
    ]


def settlement_outcome_for_row(row: dict[str, Any], settlement_bucket: Any) -> int | None:
    bucket = safe_float(settlement_bucket)
    if bucket is None:
        return None
    kind, value, value_hi = band_parts(row)
    if kind is None or value is None:
        return None
    return resolve_outcome(kind, value, bucket, value_hi=value_hi)


def closer_source(
    *,
    model_probability: float | None,
    market_yes: float | None,
    fair_value_probability: float | None,
) -> tuple[str, float | None, float | None]:
    if fair_value_probability is None or model_probability is None or market_yes is None:
        return "pending_settlement", None, None
    model_distance = abs(model_probability - fair_value_probability) * 100.0
    market_distance = abs(market_yes - fair_value_probability) * 100.0
    if model_distance + 1e-9 < market_distance:
        winner = "model"
    elif market_distance + 1e-9 < model_distance:
        winner = "market"
    else:
        winner = "tie"
    return winner, round(model_distance, 6), round(market_distance, 6)


def build_audit_record(
    row: dict[str, Any],
    *,
    folder: str | Path,
    gap_threshold_points: float = DEFAULT_GAP_THRESHOLD_POINTS,
    run_id: str | None = None,
    audited_at_utc: str | None = None,
) -> dict[str, Any]:
    folder = Path(folder)
    event_slug = str(row.get("event_slug") or folder.name)
    spec = spec_for_slug(event_slug)
    target_date = date_from_event_slug(event_slug)
    model_probability = safe_float(row.get("model_probability"))
    market_yes = safe_float(row.get("market_yes"))
    model_minus_market_points = (
        (model_probability - market_yes) * 100.0
        if model_probability is not None and market_yes is not None
        else None
    )
    label = load_market_day_label(folder)
    settlement_bucket = (label or {}).get("settlement_bucket")
    outcome = settlement_outcome_for_row(row, settlement_bucket)
    fair_value_probability = float(outcome) if outcome is not None else None
    closer, model_distance, market_distance = closer_source(
        model_probability=model_probability,
        market_yes=market_yes,
        fair_value_probability=fair_value_probability,
    )
    kind, value, value_hi = band_parts(row)
    audited_at_utc = audited_at_utc or utc_now_iso()
    run_id = run_id or audited_at_utc

    return {
        "schema_version": SCHEMA_VERSION,
        "audit_key": audit_key_for_row(row, gap_threshold_points=gap_threshold_points),
        "audit_revision": 1,
        "run_id": run_id,
        "audited_at_utc": audited_at_utc,
        "status": "resolved" if outcome is not None else "pending_settlement",
        "trigger_reason": "model_market_gap_points",
        "gap_threshold_points": float(gap_threshold_points),
        "gap_points": compact_float(row_gap_points(row)),
        "model_minus_market_points": compact_float(model_minus_market_points),
        "event_slug": event_slug,
        "market_id": spec.id if spec else row.get("market_id"),
        "city": spec.city_label if spec else None,
        "target_date": target_date.isoformat() if target_date else None,
        "unit": spec.display_unit if spec else None,
        "snapshot_id": row.get("snapshot_id"),
        "captured_at_utc": row.get("captured_at_utc"),
        "captured_at_local": row.get("captured_at_local"),
        "model_version": row.get("model_version"),
        "range_label": clean_label(row.get("range_label")),
        "band_key": band_key_text(row),
        "bin_kind": kind,
        "bin_value": compact_float(value),
        "bin_value_hi": compact_float(value_hi),
        "model_probability": compact_float(model_probability),
        "model_probability_percent": compact_float(
            model_probability * 100.0 if model_probability is not None else None
        ),
        "market_yes": compact_float(market_yes),
        "market_probability_percent": compact_float(
            market_yes * 100.0 if market_yes is not None else None
        ),
        "fair_value_probability": compact_float(fair_value_probability),
        "fair_value_percent": compact_float(
            fair_value_probability * 100.0 if fair_value_probability is not None else None
        ),
        "closer_source": closer,
        "model_distance_points": model_distance,
        "market_distance_points": market_distance,
        "outcome": outcome,
        "settlement_bucket": compact_float(settlement_bucket),
        "settlement_unit": (label or {}).get("settlement_unit"),
        "settlement_source": (label or {}).get("settlement_source"),
        "settlement_quality_grade": (label or {}).get("quality_grade"),
        "winning_band": clean_label((label or {}).get("winning_band")),
        "settlement_label_available": bool(label),
        "snapshot_folder": str(folder),
    }


def build_audit_records(
    folders: list[str | Path] | None = None,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    event_slug: str | None = None,
    market_id: str | None = None,
    range_label: str | None = None,
    snapshot_id: str | None = None,
    gap_threshold_points: float = DEFAULT_GAP_THRESHOLD_POINTS,
    latest_only: bool = True,
    run_id: str | None = None,
    audited_at_utc: str | None = None,
) -> list[dict[str, Any]]:
    audited_at_utc = audited_at_utc or utc_now_iso()
    run_id = run_id or audited_at_utc
    records = []
    for folder in selected_folders(
        folders,
        snapshots_root=snapshots_root,
        event_slug=event_slug,
        market_id=market_id,
    ):
        for row in triggered_rows(
            folder,
            gap_threshold_points=gap_threshold_points,
            latest_only=latest_only,
            range_label=range_label,
            snapshot_id=snapshot_id,
        ):
            records.append(build_audit_record(
                row,
                folder=folder,
                gap_threshold_points=gap_threshold_points,
                run_id=run_id,
                audited_at_utc=audited_at_utc,
            ))
    records.sort(key=lambda row: (-(row.get("gap_points") or 0.0), row.get("event_slug") or ""))
    return records


def read_audit_log(path: str | Path = DEFAULT_LOG_PATH) -> list[dict[str, Any]]:
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


def load_audit_index(path: str | Path = DEFAULT_LOG_PATH) -> dict[str, dict[str, Any]]:
    index = {}
    for row in read_audit_log(path):
        key = row.get("audit_key")
        if key:
            index[key] = row
    return index


def should_append_record(previous: dict[str, Any] | None, record: dict[str, Any]) -> bool:
    if previous is None:
        return True
    previous_resolved = previous.get("fair_value_probability") is not None
    record_resolved = record.get("fair_value_probability") is not None
    if record_resolved and not previous_resolved:
        return True
    fields = ("fair_value_probability", "closer_source", "settlement_bucket", "outcome")
    return any(previous.get(field) != record.get(field) for field in fields)


def append_audit_log(
    records: list[dict[str, Any]],
    path: str | Path = DEFAULT_LOG_PATH,
    *,
    dedupe: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path = Path(path)
    index = load_audit_index(path) if dedupe else {}
    written = []
    skipped = []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            previous = index.get(record.get("audit_key"))
            if dedupe and not should_append_record(previous, record):
                skipped.append(record)
                continue
            output = dict(record)
            if previous:
                output["audit_revision"] = int(previous.get("audit_revision") or 1) + 1
                output["supersedes_audited_at_utc"] = previous.get("audited_at_utc")
            handle.write(json.dumps(output, sort_keys=True) + "\n")
            written.append(output)
            index[output["audit_key"]] = output
    return written, skipped


def ensure_audit_record_saved(
    row: dict[str, Any],
    *,
    folder: str | Path,
    log_path: str | Path = DEFAULT_LOG_PATH,
    gap_threshold_points: float = DEFAULT_GAP_THRESHOLD_POINTS,
    audit_index: dict[str, dict[str, Any]] | None = None,
    run_id: str | None = None,
    audited_at_utc: str | None = None,
) -> dict[str, Any]:
    """Append a log row for one latest snapshot-band when it crosses threshold.

    Returns a small status dict and mutates ``audit_index`` when a caller passes
    one in, so subsequent same-render checks see newly saved records.
    """
    gap = row_gap_points(row)
    if gap is None or gap + 1e-9 < float(gap_threshold_points):
        return {
            "triggered": False,
            "saved": False,
            "written": False,
            "skipped": False,
            "audit_key": audit_key_for_row(row, gap_threshold_points=gap_threshold_points),
            "gap_points": compact_float(gap),
        }

    index = audit_index if audit_index is not None else load_audit_index(log_path)
    record = build_audit_record(
        row,
        folder=folder,
        gap_threshold_points=gap_threshold_points,
        run_id=run_id,
        audited_at_utc=audited_at_utc,
    )
    previous = index.get(record["audit_key"])
    if previous is not None and not should_append_record(previous, record):
        return {
            "triggered": True,
            "saved": True,
            "written": False,
            "skipped": True,
            "audit_key": record["audit_key"],
            "record": previous,
            "gap_points": record.get("gap_points"),
        }

    written, skipped = append_audit_log([record], log_path, dedupe=True)
    saved_record = written[0] if written else (previous or record)
    if audit_index is not None:
        audit_index[saved_record["audit_key"]] = saved_record
    return {
        "triggered": True,
        "saved": bool(written or previous),
        "written": bool(written),
        "skipped": bool(skipped),
        "audit_key": saved_record["audit_key"],
        "record": saved_record,
        "gap_points": saved_record.get("gap_points"),
    }


def audit_saved_for_row(
    row: dict[str, Any],
    *,
    audit_index: dict[str, dict[str, Any]] | None = None,
    log_path: str | Path = DEFAULT_LOG_PATH,
    gap_threshold_points: float = DEFAULT_GAP_THRESHOLD_POINTS,
) -> bool:
    index = audit_index if audit_index is not None else load_audit_index(log_path)
    key = audit_key_for_row(row, gap_threshold_points=gap_threshold_points)
    return key in index


def summarize_run(records: list[dict[str, Any]], written: list[dict[str, Any]], skipped: list[dict[str, Any]], log_path: str | Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "log_path": str(log_path),
        "candidate_count": len(records),
        "written_count": len(written),
        "skipped_duplicate_count": len(skipped),
        "resolved_count": sum(1 for row in records if row.get("fair_value_probability") is not None),
        "pending_settlement_count": sum(1 for row in records if row.get("fair_value_probability") is None),
        "model_closer_count": sum(1 for row in records if row.get("closer_source") == "model"),
        "market_closer_count": sum(1 for row in records if row.get("closer_source") == "market"),
        "tie_count": sum(1 for row in records if row.get("closer_source") == "tie"),
    }


def run_audit(
    folders: list[str | Path] | None = None,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    log_path: str | Path = DEFAULT_LOG_PATH,
    event_slug: str | None = None,
    market_id: str | None = None,
    range_label: str | None = None,
    snapshot_id: str | None = None,
    gap_threshold_points: float = DEFAULT_GAP_THRESHOLD_POINTS,
    latest_only: bool = True,
    dedupe: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    run_id = utc_now_iso()
    records = build_audit_records(
        folders,
        snapshots_root=snapshots_root,
        event_slug=event_slug,
        market_id=market_id,
        range_label=range_label,
        snapshot_id=snapshot_id,
        gap_threshold_points=gap_threshold_points,
        latest_only=latest_only,
        run_id=run_id,
        audited_at_utc=run_id,
    )
    if dry_run:
        written, skipped = [], []
    else:
        written, skipped = append_audit_log(records, log_path, dedupe=dedupe)
    summary = summarize_run(records, written, skipped, log_path)
    summary["run_id"] = run_id
    summary["dry_run"] = dry_run
    summary["records"] = records if dry_run else written
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit model-vs-market band disagreements by full percentage-point gap "
            "and append settlement-scored results to JSONL."
        )
    )
    parser.add_argument("folders", nargs="*", help="Optional snapshot folders to scan.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--event-slug", default="")
    parser.add_argument("--market-id", default="")
    parser.add_argument("--range-label", default="")
    parser.add_argument("--snapshot-id", default="")
    parser.add_argument("--gap-threshold-points", type=float, default=DEFAULT_GAP_THRESHOLD_POINTS)
    parser.add_argument(
        "--all-snapshots",
        dest="latest_only",
        action="store_false",
        help="Scan every snapshot row instead of only the latest snapshot per folder.",
    )
    parser.set_defaults(latest_only=True)
    parser.add_argument("--no-dedupe", dest="dedupe", action="store_false")
    parser.set_defaults(dedupe=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    summary = run_audit(
        args.folders,
        snapshots_root=args.snapshots_root,
        log_path=args.log_path,
        event_slug=args.event_slug or None,
        market_id=args.market_id or None,
        range_label=args.range_label or None,
        snapshot_id=args.snapshot_id or None,
        gap_threshold_points=args.gap_threshold_points,
        latest_only=args.latest_only,
        dedupe=args.dedupe,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

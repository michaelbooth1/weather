"""Pinned promotion corpus manifests.

A promotion corpus is the immutable input contract for model promotion:
settled market-day folders, accepted settlement labels, the exact snapshot IDs
to score, plus hashes of both the market tape rows and replay inputs. Replaying
against a manifest means a later folder append, label refresh, or replay-input
rewrite cannot silently change the gate.
"""
import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import load_market_day_label
from market_config import date_from_event_slug, polymarket_url_for_slug
from market_registry import REGISTRY, spec_for_slug
from replay import index_records_by_snapshot, is_reconstructed, load_replay_records
from settled_days import DEFAULT_SNAPSHOTS_ROOT, discover_settled_folders

PROMOTION_CORPUS_SCHEMA_VERSION = "promotion_corpus_v0.1"
DEFAULT_OUT = Path("data") / "backtest" / "promotion_corpus.json"
DEFAULT_QUALITY_GRADES = ("complete", "manual_override")


def parse_quality_grades(value):
    if value is None:
        return tuple(DEFAULT_QUALITY_GRADES)
    cleaned = [item.strip() for item in str(value).split(",") if item.strip()]
    if not cleaned:
        return tuple(DEFAULT_QUALITY_GRADES)
    if len(cleaned) == 1 and cleaned[0].lower() in {"all", "*"}:
        return None
    return tuple(cleaned)


def _as_of_date(value):
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def _canonical_json(value):
    return json.dumps(
        _clean_for_json(value),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _hash_json(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _clean_for_json(value):
    if isinstance(value, dict):
        return {str(k): _clean_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_for_json(v) for v in value]
    if isinstance(value, tuple):
        return [_clean_for_json(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _safe_int(value):
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return int(float(value))


def _safe_float(value):
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return float(value)


def _folder_sort_key(folder):
    target_date = date_from_event_slug(Path(folder).name)
    spec = spec_for_slug(Path(folder).name)
    return (target_date or date.min, spec.id if spec else "", Path(folder).name)


def _relative_or_string(path, root):
    path = Path(path)
    root = Path(root)
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return str(path)


def _ordered_snapshot_ids(frame):
    if "snapshot_id" not in frame:
        return []
    seen = set()
    ordered = []
    for value in frame["snapshot_id"].dropna().astype(str).tolist():
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _snapshot_tape_hashes(frame, snapshot_ids):
    if "snapshot_id" not in frame:
        return {}
    wanted = {str(item) for item in snapshot_ids}
    work = frame.copy()
    work["_snapshot_id_str"] = work["snapshot_id"].astype(str)
    work = work[work["_snapshot_id_str"].isin(wanted)]
    hashes = {}
    for snapshot_id, group in work.groupby("_snapshot_id_str", sort=False):
        rows = group.drop(columns=["_snapshot_id_str"]).to_dict(orient="records")
        hashes[str(snapshot_id)] = _hash_json(rows)
    return hashes


def _record_hashes(records, snapshot_ids):
    wanted = {str(item) for item in snapshot_ids}
    return {
        str(snapshot_id): _hash_json(record)
        for snapshot_id, record in records.items()
        if str(snapshot_id) in wanted
    }


def _entry_for_folder(
    folder,
    snapshots_root,
    quality_grades,
    include_reconstructed=False,
    min_snapshots=1,
):
    folder = Path(folder)
    tape = folder / "snapshots_long.csv"
    if not tape.exists():
        return None, "missing_tape"
    spec = spec_for_slug(folder.name)
    target_date = date_from_event_slug(folder.name)
    if spec is None or target_date is None:
        return None, "unregistered_market"

    label = load_market_day_label(folder)
    if not label or label.get("settlement_bucket") is None:
        return None, "missing_settlement_label"
    grade = label.get("quality_grade")
    if quality_grades is not None and grade not in set(quality_grades):
        return None, f"quality:{grade or 'missing'}"

    frame = pd.read_csv(tape)
    tape_snapshot_ids = _ordered_snapshot_ids(frame)
    records = index_records_by_snapshot(load_replay_records(folder))
    pinned_snapshot_ids = []
    reconstructed_excluded = 0
    for snapshot_id in tape_snapshot_ids:
        record = records.get(str(snapshot_id))
        if not record:
            continue
        if is_reconstructed(record) and not include_reconstructed:
            reconstructed_excluded += 1
            continue
        pinned_snapshot_ids.append(str(snapshot_id))
    if len(pinned_snapshot_ids) < min_snapshots:
        return None, "too_few_replay_inputs"

    pinned_frame = frame[frame["snapshot_id"].astype(str).isin(set(pinned_snapshot_ids))]
    record_subset = {
        str(snapshot_id): records[str(snapshot_id)]
        for snapshot_id in pinned_snapshot_ids
        if str(snapshot_id) in records
    }
    recorded_versions = sorted({
        str(record.get("model_version"))
        for record in record_subset.values()
        if record.get("model_version")
    })
    identity_record_count = sum(1 for record in record_subset.values() if record.get("model_identity"))
    reconstructed_record_count = sum(1 for record in record_subset.values() if is_reconstructed(record))

    entry = {
        "event_slug": folder.name,
        "market_id": spec.id,
        "city": spec.city_label,
        "target_date": target_date.isoformat(),
        "polymarket_url": label.get("polymarket_url") or polymarket_url_for_slug(folder.name),
        "folder": str(folder),
        "folder_name": folder.name,
        "folder_relative_to_snapshots_root": _relative_or_string(folder, snapshots_root),
        "snapshot_tape_path": str(tape),
        "settlement_bucket": _safe_int(label.get("settlement_bucket")),
        "settlement_high": _safe_float(label.get("settlement_high")),
        "settlement_unit": label.get("settlement_unit") or spec.display_unit,
        "settlement_source": label.get("settlement_source"),
        "winning_band": label.get("winning_band"),
        "winning_band_kind": label.get("winning_band_kind"),
        "winning_band_value": _safe_int(label.get("winning_band_value")),
        "winning_band_value_hi": _safe_int(label.get("winning_band_value_hi")),
        "quality_grade": grade,
        "quality_reason": label.get("quality_reason"),
        "coverage_clean": bool(label.get("coverage_clean")),
        "capture_ratio": _safe_float(label.get("capture_ratio")),
        "max_gap_minutes": _safe_float(label.get("max_gap_minutes")),
        "coverage_reason": label.get("coverage_reason"),
        "snapshot_ids": pinned_snapshot_ids,
        "snapshot_count": len(pinned_snapshot_ids),
        "snapshot_count_in_tape": len(tape_snapshot_ids),
        "missing_replay_input_count": len(tape_snapshot_ids) - len(pinned_snapshot_ids) - reconstructed_excluded,
        "reconstructed_excluded_count": reconstructed_excluded,
        "replay_record_count": len(record_subset),
        "identity_record_count": identity_record_count,
        "reconstructed_record_count": reconstructed_record_count,
        "band_count": int(pinned_frame["range_label"].nunique()) if "range_label" in pinned_frame else 0,
        "row_count": int(len(pinned_frame)),
        "recorded_versions": recorded_versions,
        "replay_record_hashes": _record_hashes(record_subset, pinned_snapshot_ids),
        "tape_row_hashes": _snapshot_tape_hashes(frame, pinned_snapshot_ids),
        "label_hash": _hash_json({
            key: label.get(key)
            for key in (
                "event_slug",
                "market_id",
                "target_date",
                "settlement_bucket",
                "settlement_unit",
                "settlement_source",
                "quality_grade",
                "winning_band",
            )
        }),
    }
    return entry, None


def _hash_entry(entry):
    return {
        "event_slug": entry.get("event_slug"),
        "market_id": entry.get("market_id"),
        "target_date": entry.get("target_date"),
        "settlement_bucket": entry.get("settlement_bucket"),
        "settlement_unit": entry.get("settlement_unit"),
        "settlement_source": entry.get("settlement_source"),
        "quality_grade": entry.get("quality_grade"),
        "snapshot_ids": entry.get("snapshot_ids") or [],
        "replay_record_hashes": entry.get("replay_record_hashes") or {},
        "tape_row_hashes": entry.get("tape_row_hashes") or {},
        "label_hash": entry.get("label_hash"),
    }


def corpus_hash(entries):
    payload = {
        "schema_version": PROMOTION_CORPUS_SCHEMA_VERSION,
        "entries": [_hash_entry(entry) for entry in sorted(entries, key=lambda e: e["event_slug"])],
    }
    return _hash_json(payload)


def summarize_entries(entries):
    by_market = Counter(entry["market_id"] for entry in entries)
    return {
        "market_count": len(by_market),
        "market_day_count": len(entries),
        "snapshot_count": sum(int(entry.get("snapshot_count") or 0) for entry in entries),
        "band_row_count": sum(int(entry.get("row_count") or 0) for entry in entries),
        "identity_record_count": sum(int(entry.get("identity_record_count") or 0) for entry in entries),
        "by_market": dict(sorted(by_market.items())),
    }


def build_promotion_corpus(
    folders=None,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    as_of=None,
    quality_grades=DEFAULT_QUALITY_GRADES,
    include_reconstructed=False,
    allow_unsettled=False,
    market_id=None,
    min_snapshots=1,
):
    snapshots_root = Path(snapshots_root)
    as_of_day = _as_of_date(as_of)
    selected = [Path(folder) for folder in folders] if folders else discover_settled_folders(
        snapshots_root,
        as_of=as_of_day,
        required_file="snapshots_long.csv",
        market_id=market_id,
    )
    entries = []
    skipped = []
    for folder in sorted(selected, key=_folder_sort_key):
        spec = spec_for_slug(Path(folder).name)
        target_date = date_from_event_slug(Path(folder).name)
        if market_id and (not spec or spec.id != market_id):
            skipped.append({"folder": str(folder), "reason": f"market:{spec.id if spec else 'unknown'}"})
            continue
        if target_date and target_date >= as_of_day and not allow_unsettled:
            skipped.append({"folder": str(folder), "reason": "unsettled"})
            continue
        entry, reason = _entry_for_folder(
            folder,
            snapshots_root=snapshots_root,
            quality_grades=quality_grades,
            include_reconstructed=include_reconstructed,
            min_snapshots=min_snapshots,
        )
        if entry:
            entries.append(entry)
        else:
            skipped.append({"folder": str(folder), "reason": reason or "unknown"})

    summary = summarize_entries(entries)
    manifest = {
        "schema_version": PROMOTION_CORPUS_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of_day.isoformat(),
        "snapshots_root": str(snapshots_root),
        "quality_grades": list(quality_grades) if quality_grades is not None else ["all"],
        "include_reconstructed": bool(include_reconstructed),
        "allow_unsettled": bool(allow_unsettled),
        "min_snapshots": int(min_snapshots),
        "market_filter": market_id,
        "entries": entries,
        "summary": summary,
        "skipped": skipped,
    }
    manifest["corpus_hash"] = corpus_hash(entries)
    return manifest


def write_manifest(manifest, path=DEFAULT_OUT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != PROMOTION_CORPUS_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported promotion corpus schema {manifest.get('schema_version')!r}"
        )
    expected = corpus_hash(manifest.get("entries") or [])
    if manifest.get("corpus_hash") != expected:
        raise ValueError(
            f"promotion corpus hash mismatch: manifest={manifest.get('corpus_hash')} computed={expected}"
        )
    manifest["_path"] = str(path)
    return manifest


def entries_by_slug(manifest):
    return {entry["event_slug"]: entry for entry in manifest.get("entries") or []}


def entry_for_folder(manifest, folder):
    return entries_by_slug(manifest).get(Path(folder).name)


def folders_from_manifest(manifest, snapshots_root=None):
    root = Path(snapshots_root or manifest.get("snapshots_root") or DEFAULT_SNAPSHOTS_ROOT)
    folders = []
    for entry in manifest.get("entries") or []:
        candidates = [
            Path(entry.get("folder") or ""),
            root / (entry.get("folder_relative_to_snapshots_root") or entry.get("folder_name") or ""),
            root / (entry.get("folder_name") or ""),
        ]
        folder = next((candidate for candidate in candidates if candidate and candidate.exists()), candidates[-1])
        folders.append(folder)
    return folders


def verify_entry_inputs(entry, folder, frame, records):
    """Return warnings when the live folder no longer matches the manifest pin."""
    warnings = []
    pinned_ids = {str(item) for item in entry.get("snapshot_ids") or []}
    frame_ids = set(frame["snapshot_id"].astype(str)) if "snapshot_id" in frame else set()
    record_ids = set(str(item) for item in records)
    missing_tape = sorted(pinned_ids - frame_ids)
    missing_records = sorted(pinned_ids - record_ids)
    if missing_tape:
        warnings.append(f"{entry['event_slug']}: {len(missing_tape)} pinned snapshot(s) missing from tape")
    if missing_records:
        warnings.append(f"{entry['event_slug']}: {len(missing_records)} pinned replay input(s) missing")

    tape_hashes = _snapshot_tape_hashes(frame, pinned_ids)
    for snapshot_id, expected in (entry.get("tape_row_hashes") or {}).items():
        if snapshot_id in tape_hashes and tape_hashes[snapshot_id] != expected:
            warnings.append(f"{entry['event_slug']}: tape rows changed for snapshot {snapshot_id}")
    record_hashes = _record_hashes(records, pinned_ids)
    for snapshot_id, expected in (entry.get("replay_record_hashes") or {}).items():
        if snapshot_id in record_hashes and record_hashes[snapshot_id] != expected:
            warnings.append(f"{entry['event_slug']}: replay input changed for snapshot {snapshot_id}")
    return warnings


def main():
    parser = argparse.ArgumentParser(description="Build a pinned promotion corpus manifest.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders (default: settled folders under root).")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--as-of", default=None,
                        help="Only include target dates before this date (default: today).")
    parser.add_argument("--market", default=None, choices=sorted(REGISTRY),
                        help="Only include one registered market.")
    parser.add_argument("--quality-grades", default=",".join(DEFAULT_QUALITY_GRADES),
                        help="Comma-separated label grades, or 'all'. Default: complete,manual_override.")
    parser.add_argument("--include-reconstructed", action="store_true",
                        help="Include approximate reconstructed replay inputs in the pinned corpus.")
    parser.add_argument("--allow-unsettled", action="store_true",
                        help="Permit today/future folders. Not recommended for promotion.")
    parser.add_argument("--min-snapshots", type=int, default=1)
    args = parser.parse_args()

    manifest = build_promotion_corpus(
        folders=args.folders,
        snapshots_root=args.snapshots_root,
        as_of=args.as_of,
        quality_grades=parse_quality_grades(args.quality_grades),
        include_reconstructed=args.include_reconstructed,
        allow_unsettled=args.allow_unsettled,
        market_id=args.market,
        min_snapshots=args.min_snapshots,
    )
    path = write_manifest(manifest, args.out)
    summary = manifest["summary"]
    print(
        f"Promotion corpus {manifest['corpus_hash']} written to {path}: "
        f"{summary['market_day_count']} market-days, {summary['snapshot_count']} snapshots, "
        f"{summary['band_row_count']} band-rows."
    )
    if manifest["skipped"]:
        counts = Counter(item["reason"] for item in manifest["skipped"])
        print("Skipped: " + ", ".join(f"{reason}={count}" for reason, count in sorted(counts.items())))


if __name__ == "__main__":
    main()

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
import re
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path

from weather.paths import data_path

import pandas as pd

from weather.backtesting.settlement_io import (
    canonical_winning_band,
    resolve_market_day_label,
)
from weather.backtesting.replay import index_records_by_snapshot, is_reconstructed, load_replay_records
from weather.backtesting.settled_days import DEFAULT_SNAPSHOTS_ROOT, discover_settled_folders
from weather.market.market_config import date_from_event_slug, polymarket_url_for_slug
from weather.market.market_registry import REGISTRY, spec_for_slug
from weather.reporting.data_quality.feature_quality_quarantine import audit_folder_feature_quality

PROMOTION_CORPUS_SCHEMA_VERSION = "promotion_corpus_v0.1"
DEFAULT_OUT = data_path() / "backtest" / "promotion_corpus.json"
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
    admit_promotion_countable=False,
    input_loader=None,
):
    folder = Path(folder)
    tape = folder / "snapshots_long.csv"
    if not tape.exists():
        return None, "missing_tape"
    spec = spec_for_slug(folder.name)
    target_date = date_from_event_slug(folder.name)
    if spec is None or target_date is None:
        return None, "unregistered_market"

    settlement_authority = None
    if input_loader is None:
        resolved_label = resolve_market_day_label(folder)
        label = resolved_label["label"]
        settlement_authority = resolved_label["authority"]
    else:
        loaded = input_loader(folder)
        if isinstance(loaded, Mapping):
            required = {"label", "frame", "records", "feature_quality"}
            missing = sorted(required - set(loaded))
            if missing:
                raise ValueError(
                    "promotion corpus input_loader result is missing required "
                    f"field(s): {', '.join(missing)}"
                )
            label = loaded["label"]
            frame = loaded["frame"]
            records = loaded["records"]
            feature_quality = loaded["feature_quality"]
            settlement_authority = loaded.get("settlement_label_authority")
        elif isinstance(loaded, tuple):
            if len(loaded) != 4:
                raise ValueError(
                    "promotion corpus input_loader tuple must contain exactly "
                    "(label, frame, records, feature_quality)"
                )
            label, frame, records, feature_quality = loaded
        else:
            raise TypeError(
                "promotion corpus input_loader must return a mapping or a "
                "four-item tuple"
            )

        if not isinstance(label, Mapping):
            raise TypeError("promotion corpus input_loader label must be a mapping")
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("promotion corpus input_loader frame must be a pandas DataFrame")
        if not isinstance(records, Mapping):
            raise TypeError("promotion corpus input_loader records must be a mapping")
        if any(not isinstance(record, Mapping) for record in records.values()):
            raise TypeError(
                "promotion corpus input_loader record values must be mappings"
            )
        if not isinstance(feature_quality, Mapping):
            raise TypeError(
                "promotion corpus input_loader feature_quality must be a mapping"
            )
        feature_quality_rows = feature_quality.get("rows", [])
        if not isinstance(feature_quality_rows, (list, tuple)) or any(
            not isinstance(row, Mapping) for row in feature_quality_rows
        ):
            raise TypeError(
                "promotion corpus input_loader feature_quality rows must be a "
                "list or tuple of mappings"
            )
        feature_quality_summary = feature_quality.get("summary", {})
        if not isinstance(feature_quality_summary, Mapping):
            raise TypeError(
                "promotion corpus input_loader feature_quality summary must be a mapping"
            )
    if not isinstance(settlement_authority, Mapping):
        settlement_authority = {
            "status": "prevalidated_input_loader_unreported",
            "ledger_row_exists": None,
            "sidecar_fallback": None,
        }

    if not label or label.get("settlement_bucket") is None:
        return None, "missing_settlement_label"
    grade = label.get("quality_grade")
    grade_admitted = quality_grades is None or grade in set(quality_grades)
    # Item 319: a partial headline grade (any 24h collection gap) does not make
    # a day unscoreable — the ratified promotion gate is material coverage plus
    # settlement reconciliation, recorded on the label as promotion_countable.
    countable_admitted = (
        admit_promotion_countable
        and not grade_admitted
        and bool(label.get("promotion_countable"))
    )
    if not grade_admitted and not countable_admitted:
        return None, f"quality:{grade or 'missing'}"

    if input_loader is None:
        frame = pd.read_csv(tape)
        records = index_records_by_snapshot(load_replay_records(folder))
    tape_snapshot_ids = _ordered_snapshot_ids(frame)
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
    if input_loader is None:
        feature_quality = audit_folder_feature_quality(folder)
    feature_quality_rows = [
        row for row in feature_quality.get("rows") or []
        if row.get("training_excluded") and row.get("snapshot_id")
    ]
    feature_quality_excluded_ids = sorted({
        str(row.get("snapshot_id"))
        for row in feature_quality_rows
        if str(row.get("snapshot_id")) in set(pinned_snapshot_ids)
    })
    if feature_quality_excluded_ids:
        excluded = set(feature_quality_excluded_ids)
        pinned_snapshot_ids = [snapshot_id for snapshot_id in pinned_snapshot_ids if snapshot_id not in excluded]
    if len(pinned_snapshot_ids) < min_snapshots:
        if feature_quality_excluded_ids:
            return None, "feature_quality_quarantine_excluded"
        return None, "too_few_replay_inputs"

    pinned_frame = frame[frame["snapshot_id"].astype(str).isin(set(pinned_snapshot_ids))]
    feature_quality_excluded_frame = frame[frame["snapshot_id"].astype(str).isin(set(feature_quality_excluded_ids))]
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
        "winning_band": canonical_winning_band(label.get("winning_band")),
        "winning_band_kind": label.get("winning_band_kind"),
        "winning_band_value": _safe_int(label.get("winning_band_value")),
        "winning_band_value_hi": _safe_int(label.get("winning_band_value_hi")),
        "quality_grade": grade,
        "quality_reason": label.get("quality_reason"),
        "settlement_label_authority": dict(settlement_authority),
        "admitted_by": "quality_grade" if grade_admitted else "promotion_countable",
        "promotion_countable": bool(label.get("promotion_countable")),
        "promotion_countable_reason": label.get("promotion_countable_reason"),
        "material_coverage_grade": label.get("material_coverage_grade"),
        "coverage_clean": bool(label.get("coverage_clean")),
        "capture_ratio": _safe_float(label.get("capture_ratio")),
        "max_gap_minutes": _safe_float(label.get("max_gap_minutes")),
        "coverage_reason": label.get("coverage_reason"),
        "snapshot_ids": pinned_snapshot_ids,
        "snapshot_count": len(pinned_snapshot_ids),
        "snapshot_count_in_tape": len(tape_snapshot_ids),
        "missing_replay_input_count": (
            len(tape_snapshot_ids)
            - len(pinned_snapshot_ids)
            - reconstructed_excluded
            - len(feature_quality_excluded_ids)
        ),
        "reconstructed_excluded_count": reconstructed_excluded,
        "feature_quality_excluded_snapshot_ids": feature_quality_excluded_ids,
        "feature_quality_excluded_snapshot_count": len(feature_quality_excluded_ids),
        "feature_quality_excluded_band_row_count": int(len(feature_quality_excluded_frame)),
        "feature_quality_quarantine": feature_quality.get("summary") or {},
        "replay_record_count": len(record_subset),
        "identity_record_count": identity_record_count,
        "reconstructed_record_count": reconstructed_record_count,
        "band_count": int(pinned_frame["range_label"].nunique()) if "range_label" in pinned_frame else 0,
        "row_count": int(len(pinned_frame)),
        "recorded_versions": recorded_versions,
        "replay_record_hashes": _record_hashes(record_subset, pinned_snapshot_ids),
        "tape_row_hashes": _snapshot_tape_hashes(frame, pinned_snapshot_ids),
        "label_hash": _hash_json({
            key: (
                canonical_winning_band(label.get(key))
                if key == "winning_band"
                else label.get(key)
            )
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
    admitted_by = Counter(entry.get("admitted_by") or "quality_grade" for entry in entries)
    settlement_authority = Counter(
        str((entry.get("settlement_label_authority") or {}).get("status") or "unreported")
        for entry in entries
    )
    return {
        "market_count": len(by_market),
        "market_day_count": len(entries),
        "admitted_by": dict(sorted(admitted_by.items())),
        "settlement_label_authority": dict(sorted(settlement_authority.items())),
        "snapshot_count": sum(int(entry.get("snapshot_count") or 0) for entry in entries),
        "band_row_count": sum(int(entry.get("row_count") or 0) for entry in entries),
        "feature_quality_excluded_snapshot_count": sum(
            int(entry.get("feature_quality_excluded_snapshot_count") or 0)
            for entry in entries
        ),
        "feature_quality_excluded_band_row_count": sum(
            int(entry.get("feature_quality_excluded_band_row_count") or 0)
            for entry in entries
        ),
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
    admit_promotion_countable=True,
    input_loader=None,
    max_manifest_bytes=None,
):
    if input_loader is not None and not callable(input_loader):
        raise TypeError("promotion corpus input_loader must be callable")
    if max_manifest_bytes is not None and (
        isinstance(max_manifest_bytes, bool)
        or not isinstance(max_manifest_bytes, int)
        or max_manifest_bytes <= 0
    ):
        raise ValueError(
            "promotion corpus max_manifest_bytes must be a positive integer"
        )
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
    accumulated_json_bytes = 0
    if max_manifest_bytes is not None:
        accumulated_json_bytes = len(
            _canonical_json({"entries": entries, "skipped": skipped}).encode("utf-8")
        )
    if (
        max_manifest_bytes is not None
        and accumulated_json_bytes > max_manifest_bytes
    ):
        raise ValueError(
            "promotion corpus in-progress manifest exceeds "
            f"max_manifest_bytes={max_manifest_bytes}"
        )

    def append_bounded(items, item):
        nonlocal accumulated_json_bytes
        if max_manifest_bytes is None:
            items.append(item)
            return
        item_bytes = len(_canonical_json(item).encode("utf-8"))
        next_size = accumulated_json_bytes + item_bytes + (1 if items else 0)
        if max_manifest_bytes is not None and next_size > max_manifest_bytes:
            raise ValueError(
                "promotion corpus in-progress manifest exceeds "
                f"max_manifest_bytes={max_manifest_bytes}"
            )
        items.append(item)
        accumulated_json_bytes = next_size

    for folder in sorted(selected, key=_folder_sort_key):
        spec = spec_for_slug(Path(folder).name)
        target_date = date_from_event_slug(Path(folder).name)
        if market_id and (not spec or spec.id != market_id):
            append_bounded(
                skipped,
                {
                    "folder": str(folder),
                    "reason": f"market:{spec.id if spec else 'unknown'}",
                },
            )
            continue
        if target_date and target_date >= as_of_day and not allow_unsettled:
            append_bounded(
                skipped, {"folder": str(folder), "reason": "unsettled"}
            )
            continue
        entry, reason = _entry_for_folder(
            folder,
            snapshots_root=snapshots_root,
            quality_grades=quality_grades,
            include_reconstructed=include_reconstructed,
            min_snapshots=min_snapshots,
            admit_promotion_countable=admit_promotion_countable,
            input_loader=input_loader,
        )
        if entry:
            append_bounded(entries, entry)
        else:
            append_bounded(
                skipped, {"folder": str(folder), "reason": reason or "unknown"}
            )

    summary = summarize_entries(entries)
    manifest = {
        "schema_version": PROMOTION_CORPUS_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of_day.isoformat(),
        "snapshots_root": str(snapshots_root),
        "quality_grades": list(quality_grades) if quality_grades is not None else ["all"],
        "admit_promotion_countable": bool(admit_promotion_countable),
        "include_reconstructed": bool(include_reconstructed),
        "allow_unsettled": bool(allow_unsettled),
        "min_snapshots": int(min_snapshots),
        "market_filter": market_id,
        "entries": entries,
        "summary": summary,
        "skipped": skipped,
    }
    manifest["corpus_hash"] = corpus_hash(entries)
    if max_manifest_bytes is not None and len(
        _canonical_json(manifest).encode("utf-8")
    ) > max_manifest_bytes:
        raise ValueError(
            "promotion corpus manifest exceeds "
            f"max_manifest_bytes={max_manifest_bytes}"
        )
    return manifest


def write_manifest(manifest, path=DEFAULT_OUT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return path


def manifest_file_sha256(path, *, chunk_bytes=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path, *, max_bytes=None):
    if max_bytes is None:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or max_bytes <= 0
        ):
            raise ValueError(
                "promotion corpus manifest max_bytes must be a positive integer"
            )
        with Path(path).open("rb") as handle:
            raw = handle.read(max_bytes + 1)
        if not raw:
            raise ValueError("promotion corpus manifest is empty")
        if len(raw) > max_bytes:
            raise ValueError(
                f"promotion corpus manifest exceeds max_bytes={max_bytes}"
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("promotion corpus manifest is not valid UTF-8") from exc
        try:
            def reject_duplicate_keys(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError(
                            "promotion corpus manifest contains duplicate JSON "
                            f"key {key!r}"
                        )
                    result[key] = value
                return result

            def reject_non_finite(value):
                raise ValueError(
                    "promotion corpus manifest contains non-finite JSON "
                    f"constant {value!r}"
                )

            manifest = json.loads(
                text,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_non_finite,
            )
        except json.JSONDecodeError as exc:
            raise ValueError("promotion corpus manifest is not valid JSON") from exc
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


def load_manifest_pinned(
    path,
    *,
    expected_sha256,
    expected_corpus_hash,
    max_bytes=None,
):
    """Load one exact corpus generation and detect replacement during parsing."""

    expected_sha256 = str(expected_sha256 or "").strip().lower()
    expected_corpus_hash = str(expected_corpus_hash or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("pinned promotion corpus requires a valid file SHA-256")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_corpus_hash):
        raise ValueError("pinned promotion corpus requires a valid semantic hash")
    before = manifest_file_sha256(path)
    if before != expected_sha256:
        raise ValueError("pinned promotion corpus file identity mismatch")
    manifest = load_manifest(path, max_bytes=max_bytes)
    after = manifest_file_sha256(path)
    if after != before or after != expected_sha256:
        raise ValueError("pinned promotion corpus changed while it was being read")
    if str(manifest.get("corpus_hash") or "").lower() != expected_corpus_hash:
        raise ValueError("pinned promotion corpus semantic identity mismatch")
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
    parser.add_argument("--grade-only-admission", action="store_true",
                        help="Admit only the listed quality grades; do not admit partial days "
                             "whose labels are promotion_countable (item 319 material coverage).")
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
        admit_promotion_countable=not args.grade_only_admission,
    )
    path = write_manifest(manifest, args.out)
    summary = manifest["summary"]
    print(
        f"Promotion corpus {manifest['corpus_hash']} written to {path}: "
        f"{summary['market_day_count']} market-days, {summary['snapshot_count']} snapshots, "
        f"{summary['band_row_count']} band-rows, "
        f"{summary['feature_quality_excluded_snapshot_count']} feature-quality excluded snapshots."
    )
    if manifest["skipped"]:
        counts = Counter(item["reason"] for item in manifest["skipped"])
        print("Skipped: " + ", ".join(f"{reason}={count}" for reason, count in sorted(counts.items())))


if __name__ == "__main__":
    main()

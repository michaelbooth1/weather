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
import os
import re
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path

from weather.execution_identity import atomic_write_json_exclusive
from weather.paths import data_path

import pandas as pd

from weather.backtesting.settlement_io import load_market_day_label
from weather.backtesting.replay import (
    RECONSTRUCTED_FILENAME,
    REPLAY_INPUTS_FILENAME,
    index_records_by_snapshot,
    is_reconstructed,
    load_replay_records,
)
from weather.backtesting.settled_days import DEFAULT_SNAPSHOTS_ROOT, discover_settled_folders
from weather.market.market_config import date_from_event_slug, polymarket_url_for_slug
from weather.market.market_registry import REGISTRY, spec_for_slug
from weather.reporting.data_quality.feature_quality_quarantine import audit_folder_feature_quality

PROMOTION_CORPUS_SCHEMA_VERSION = "promotion_corpus_v0.2"
PROMOTION_CORPUS_LEGACY_SCHEMA_VERSION = "promotion_corpus_v0.1"
ORDINAL_LITERAL_PANEL_SCHEMA_VERSION = "ordinal_smoothing_literal_panel_v0.1"
DEFAULT_OUT = data_path() / "backtest" / "promotion_corpus.json"
DEFAULT_QUALITY_GRADES = ("complete", "manual_override")
GENERATION_DIRECTORY_SUFFIX = "_generations"
MAX_GENERATION_PATH_CHARS = 240
MAX_GENERATION_TOKEN_CHARS = 72
MAX_GENERATION_COLLISIONS = 10_000


def _generation_token(value):
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("promotion corpus generation ID must be non-empty")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("._-")
    if not slug:
        slug = "generation"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    prefix_budget = MAX_GENERATION_TOKEN_CHARS - len(digest) - 1
    return f"{slug[:prefix_budget].rstrip('._-') or 'generation'}-{digest}"


def generation_scoped_manifest_path(path, generation_id):
    """Return one fresh, deterministic immutable-manifest leaf.

    The generation ID is sanitized, bounded, and hash-suffixed so long or
    punctuation-heavy scheduler identities remain collision resistant. If a
    retry reuses an already-published generation ID, the first absent retry
    suffix is selected without deleting or overwriting prior evidence.
    """

    base = Path(path).expanduser().absolute()
    suffix = base.suffix or ".json"
    directory = base.parent / f"{base.stem}{GENERATION_DIRECTORY_SUFFIX}"
    token = _generation_token(generation_id)
    for collision_index in range(MAX_GENERATION_COLLISIONS):
        collision = "" if collision_index == 0 else f"-retry-{collision_index + 1:04d}"
        name_budget = (
            MAX_GENERATION_PATH_CHARS
            - len(str(directory))
            - 1
            - len(collision)
            - len(suffix)
        )
        digest_suffix = token[-13:]
        if name_budget < len(digest_suffix) + 1:
            raise ValueError(
                "promotion corpus generation path exceeds the safe Windows "
                f"path budget ({MAX_GENERATION_PATH_CHARS} characters): {directory}"
            )
        fitted_token = token
        if len(fitted_token) > name_budget:
            prefix_budget = name_budget - len(digest_suffix)
            fitted_prefix = token[:prefix_budget].rstrip("._-") or "g"
            fitted_token = f"{fitted_prefix}{digest_suffix}"
        candidate = directory / f"{fitted_token}{collision}{suffix}"
        if not os.path.lexists(candidate):
            return candidate
    raise ValueError(
        "promotion corpus generation collision budget exhausted: "
        f"base={base}; generation_id={generation_id!r}"
    )


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

    if input_loader is None:
        label = load_market_day_label(folder)
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
        "winning_band": label.get("winning_band"),
        "winning_band_kind": label.get("winning_band_kind"),
        "winning_band_value": _safe_int(label.get("winning_band_value")),
        "winning_band_value_hi": _safe_int(label.get("winning_band_value_hi")),
        "quality_grade": grade,
        "quality_reason": label.get("quality_reason"),
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


def corpus_hash(entries, *, schema_version=PROMOTION_CORPUS_SCHEMA_VERSION):
    payload = {
        "schema_version": str(schema_version),
        "entries": [_hash_entry(entry) for entry in sorted(entries, key=lambda e: e["event_slug"])],
    }
    return _hash_json(payload)


def summarize_entries(entries):
    by_market = Counter(entry["market_id"] for entry in entries)
    admitted_by = Counter(entry.get("admitted_by") or "quality_grade" for entry in entries)
    return {
        "market_count": len(by_market),
        "market_day_count": len(entries),
        "admitted_by": dict(sorted(admitted_by.items())),
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


def _resolved_output_path(path):
    """Resolve an absent output through its existing parent topology."""

    path = Path(path).expanduser().absolute()
    existing_parent = path.parent
    missing_parts = [path.name]
    while not os.path.lexists(existing_parent):
        if existing_parent == existing_parent.parent:
            break
        missing_parts.append(existing_parent.name)
        existing_parent = existing_parent.parent
    resolved = existing_parent.resolve(strict=True)
    for part in reversed(missing_parts):
        resolved /= part
    return resolved


def _is_within(path, root):
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _manifest_source_input_paths(manifest):
    candidates = []
    entries = manifest.get("entries") or []
    skipped = manifest.get("skipped") or []
    for item in [*entries, *skipped]:
        if not isinstance(item, Mapping):
            continue
        tape = item.get("snapshot_tape_path")
        if tape:
            candidates.append(Path(tape))
        folder_text = item.get("folder")
        if not folder_text:
            continue
        folder = Path(folder_text)
        candidates.extend(
            (
                folder / "snapshots_long.csv",
                folder / REPLAY_INPUTS_FILENAME,
                folder / RECONSTRUCTED_FILENAME,
                folder / "settlement.json",
            )
        )
    return candidates


def _validate_manifest_output_path(manifest, path):
    """Fail closed before publishing an operational corpus output."""

    output = _resolved_output_path(path)
    source_inputs = _manifest_source_input_paths(manifest)
    for source in source_inputs:
        resolved_source = source.expanduser().resolve(strict=False)
        if output == resolved_source:
            raise ValueError(
                "promotion corpus output aliases a source tape/replay/label "
                f"input: {output}"
            )
        if os.path.lexists(output) and os.path.lexists(source):
            try:
                aliases_source = output.samefile(source)
            except OSError:
                aliases_source = False
            if aliases_source:
                raise ValueError(
                    "promotion corpus output aliases a source tape/replay/label "
                    f"input: {output}"
                )

    root_text = manifest.get("snapshots_root")
    if root_text:
        root = Path(root_text).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"snapshots_root is not a directory: {root}")
        if _is_within(output, root):
            raise ValueError(
                "promotion corpus output must be outside the supplied "
                f"snapshots/read-only root: output={output}; root={root}"
            )
    if os.path.lexists(output):
        raise ValueError(f"refusing to overwrite promotion corpus output: {output}")
    return output


def write_manifest(manifest, path=DEFAULT_OUT):
    path = _validate_manifest_output_path(manifest, path)
    return atomic_write_json_exclusive(path, manifest)


def load_manifest_bytes(raw, *, path, allow_research_materialization=False):
    """Parse and validate one already-stabilized manifest byte sequence.

    Literal-panel materializations intentionally retain the legacy corpus
    envelope for sealed research replay compatibility.  They are not
    operational promotion corpora and therefore require an explicit research
    opt-in at the only shared loader boundary.
    """

    if not raw:
        raise ValueError("promotion corpus manifest is empty")
    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("promotion corpus manifest is not valid UTF-8") from exc

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

    try:
        manifest = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("promotion corpus manifest is not valid JSON") from exc

    def reject_nested_non_finite(value, location="$"):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(
                "promotion corpus manifest contains non-finite JSON "
                f"number at {location}"
            )
        if isinstance(value, dict):
            for key, nested in value.items():
                reject_nested_non_finite(nested, f"{location}.{key}")
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                reject_nested_non_finite(nested, f"{location}[{index}]")

    reject_nested_non_finite(manifest)
    if not isinstance(manifest, dict):
        raise ValueError("promotion corpus manifest root must be an object")
    observed_schema = manifest.get("schema_version")
    materialization = manifest.get("materialization")
    if observed_schema == PROMOTION_CORPUS_SCHEMA_VERSION:
        if "materialization" in manifest or (
            "research_only" in manifest
            and manifest.get("research_only") is not False
        ):
            raise ValueError(
                "research-derived corpus materialization is not an operational "
                "promotion corpus"
            )
    elif allow_research_materialization and observed_schema in {
        PROMOTION_CORPUS_LEGACY_SCHEMA_VERSION,
        ORDINAL_LITERAL_PANEL_SCHEMA_VERSION,
    }:
        if (
            manifest.get("research_only") is not True
            or manifest.get("serving_or_release_authorization") is not False
            or not isinstance(materialization, dict)
            or materialization.get("schema_version")
            != ORDINAL_LITERAL_PANEL_SCHEMA_VERSION
        ):
            raise ValueError(
                "legacy/research corpus lacks the explicit ordinal literal-panel contract"
            )
    else:
        if observed_schema in {
            PROMOTION_CORPUS_LEGACY_SCHEMA_VERSION,
            ORDINAL_LITERAL_PANEL_SCHEMA_VERSION,
        }:
            raise ValueError(
                "research-derived or legacy corpus is not an operational "
                "promotion corpus"
            )
        raise ValueError(f"unsupported promotion corpus schema {observed_schema!r}")
    expected = corpus_hash(
        manifest.get("entries") or [],
        schema_version=observed_schema,
    )
    if manifest.get("corpus_hash") != expected:
        raise ValueError(
            f"promotion corpus hash mismatch: manifest={manifest.get('corpus_hash')} computed={expected}"
        )
    manifest["_path"] = str(path)
    return manifest


def load_manifest(path, *, max_bytes=None, allow_research_materialization=False):
    path = Path(path)
    if max_bytes is None:
        raw = path.read_bytes()
    else:
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or max_bytes <= 0
        ):
            raise ValueError(
                "promotion corpus manifest max_bytes must be a positive integer"
            )
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError(
                f"promotion corpus manifest exceeds max_bytes={max_bytes}"
            )
    return load_manifest_bytes(
        raw,
        path=path,
        allow_research_materialization=allow_research_materialization,
    )


def entries_by_slug(manifest):
    return {entry["event_slug"]: entry for entry in manifest.get("entries") or []}


def entry_for_folder(manifest, folder):
    return entries_by_slug(manifest).get(Path(folder).name)


def folders_from_manifest(manifest, snapshots_root=None):
    if snapshots_root is not None:
        return folders_from_manifest_strict(manifest, snapshots_root)
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


def folders_from_manifest_strict(manifest, snapshots_root):
    """Resolve every entry under one explicit root and reject path divergence."""

    root = Path(snapshots_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"snapshots_root is not a directory: {root}")
    folders = []
    for index, entry in enumerate(manifest.get("entries") or []):
        if not isinstance(entry, dict):
            raise ValueError(f"manifest entry {index} must be an object")
        relative_text = (
            entry.get("folder_relative_to_snapshots_root")
            or entry.get("folder_name")
            or entry.get("event_slug")
        )
        if not isinstance(relative_text, str) or not relative_text.strip():
            raise ValueError(f"manifest entry {index} lacks a relative folder")
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(
                f"manifest entry {index} has an unsafe relative folder: {relative_text}"
            )
        folder = (root / relative).resolve(strict=False)
        try:
            folder.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"manifest entry {index} escapes snapshots_root: {folder}"
            ) from exc
        embedded_text = entry.get("folder")
        if embedded_text:
            embedded_path = Path(embedded_text).expanduser()
            embedded = embedded_path.resolve(strict=False)
            if embedded_path.is_absolute() and embedded != folder:
                raise ValueError(
                    "manifest absolute folder diverges from the explicit snapshots_root: "
                    f"entry={embedded}; rooted={folder}"
                )
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

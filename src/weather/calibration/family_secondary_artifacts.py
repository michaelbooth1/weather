"""Family-level secondary artifact trainer and trust gate.

Roadmap item 34 moves the Toronto-only calibration stack to the Fahrenheit
family. The existing secondary artifact modules already train one market at a
time; this module orchestrates the family run, records a manifest, and exposes a
small serving gate so unproven markets fall back to empirical probabilities.
"""
import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from weather.paths import data_path

from weather.backtesting.settlement_io import DEFAULT_SNAPSHOTS_ROOT
from weather.reporting.formatting import markdown_table
from weather.calibration import forecast_error_model as forecast_error
from weather.calibration import probability_calibration as probability_calibration
from weather.calibration import settlement_lag_model as settlement_lag
from weather.market.market_registry import all_specs
from weather.market.market_config import date_from_event_slug
from weather.reporting.location_analysis.location_trust import score_all_markets
from weather.sources.forecast_history import daily_path_for
from weather.artifacts import resolve_artifact_path, writable_artifact_path


SCHEMA_VERSION = "family_secondary_artifacts_v0.1"
DEFAULT_FAMILY_UNIT = "F"
DEFAULT_MANIFEST = resolve_artifact_path("f_family_secondary_artifacts.json")
DEFAULT_REPORT = data_path() / "backtest" / "f_family_secondary_artifacts_report.md"
DEFAULT_MIN_TRUST = 25
DEFAULT_MIN_SETTLED_DAYS = 2
DEFAULT_QUALITY_GRADES = "complete,manual_override"

ARTIFACT_KINDS = ("probability_calibration", "forecast_error", "settlement_lag")


def _canonical_json(payload):
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256_json(payload):
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hashed_inventory(entries):
    payload = {
        "entries": list(entries),
        "entry_count": len(entries),
    }
    payload["sha256"] = _sha256_json(payload)
    return payload


def _verify_hashed_inventory(payload, label):
    if not isinstance(payload, dict):
        raise ValueError(f"{label} is missing")
    unhashed = dict(payload)
    actual = str(unhashed.pop("sha256", "") or "")
    if len(actual) != 64 or actual != _sha256_json(unhashed):
        raise ValueError(f"{label} hash is invalid")
    entries = payload.get("entries")
    try:
        entry_count = int(payload.get("entry_count"))
    except (TypeError, ValueError):
        entry_count = -1
    if not isinstance(entries, list) or entry_count != len(entries):
        raise ValueError(f"{label} entry count is invalid")
    return payload


def _verified_preselection(value):
    """Use the pooled trainer's fail-closed verification for production locks."""

    from weather.calibration.pooled_training import (  # lazy: research stays unchanged
        load_production_point_in_time_preselection,
        load_production_point_in_time_preselection_from_payload,
    )

    if isinstance(value, dict):
        return load_production_point_in_time_preselection_from_payload(value)
    return load_production_point_in_time_preselection(value)


def _target_date_text(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return text


def _canonical_date_filter(values, label):
    if values is None:
        return None
    try:
        return frozenset(
            date.fromisoformat(str(value)).isoformat() for value in values
        )
    except (TypeError, ValueError):
        raise ValueError(f"{label} must contain YYYY-MM-DD dates") from None


def _production_date_scope(preselection):
    universe = (preselection or {}).get("selection_universe")
    lock = (preselection or {}).get("window_lock")
    if not isinstance(universe, dict) or not isinstance(lock, dict):
        raise ValueError(
            "production family-secondary preselection date scope is missing"
        )
    universe_sha256 = str(universe.get("sha256") or "")
    universe_dates = list(universe.get("fleet_dates") or ())
    locked_dates = list(lock.get("target_dates") or ())
    try:
        canonical_universe = [
            date.fromisoformat(str(value)).isoformat() for value in universe_dates
        ]
        canonical_locked = [
            date.fromisoformat(str(value)).isoformat() for value in locked_dates
        ]
    except ValueError:
        raise ValueError(
            "production family-secondary preselection dates are invalid"
        ) from None
    if (
        len(universe_sha256) != 64
        or not canonical_universe
        or canonical_universe != universe_dates
        or len(canonical_universe) != len(set(canonical_universe))
        or canonical_locked != locked_dates
        or not set(canonical_locked) <= set(canonical_universe)
    ):
        raise ValueError(
            "production family-secondary preselection date scope is invalid"
        )
    locked = set(canonical_locked)
    training_dates = [
        value for value in canonical_universe if value not in locked
    ]
    if not training_dates:
        raise ValueError(
            "production family-secondary training universe is empty"
        )
    return universe_sha256, canonical_universe, training_dates


def _folder_target_date(folder):
    parsed = date_from_event_slug(Path(folder).name)
    return parsed.isoformat() if parsed is not None else None


def _exclude_locked_folders(
    folders,
    locked_dates,
    included_target_dates=None,
):
    locked = _canonical_date_filter(
        locked_dates,
        "locked secondary-training dates",
    ) or frozenset()
    included = _canonical_date_filter(
        included_target_dates,
        "included secondary-training dates",
    )
    if not locked and included is None:
        return list(folders)
    selected = []
    for folder in folders:
        target_date = _folder_target_date(folder)
        if not target_date:
            raise ValueError(
                f"cannot prove target date for secondary-training folder: {folder}"
            )
        if target_date not in locked and (
            included is None or target_date in included
        ):
            selected.append(folder)
    return selected


def _exclude_locked_rows(
    rows,
    locked_dates,
    included_target_dates=None,
):
    locked = _canonical_date_filter(
        locked_dates,
        "locked secondary-training dates",
    ) or frozenset()
    included = _canonical_date_filter(
        included_target_dates,
        "included secondary-training dates",
    )
    if not locked and included is None:
        return list(rows)
    selected = []
    for row in rows:
        target_date = _target_date_text((row or {}).get("target_date"))
        try:
            target_date = date.fromisoformat(target_date).isoformat()
        except ValueError as exc:
            raise ValueError(
                "cannot prove target_date for secondary-training row"
            ) from exc
        if target_date not in locked and (
            included is None or target_date in included
        ):
            selected.append(row)
    return selected


def _record_source_inventory(
    inventory,
    *,
    artifact_kind,
    fit_scope,
    market_id,
    rows,
    folders,
):
    if inventory is None:
        return
    date_counts = {}
    for row in rows:
        target_date = _target_date_text((row or {}).get("target_date"))
        if target_date:
            date_counts[target_date] = date_counts.get(target_date, 0) + 1
    folder_entries = sorted(
        (
            {
                "path": str(Path(folder)),
                "target_date": _folder_target_date(folder),
            }
            for folder in folders
        ),
        key=lambda row: (str(row.get("target_date") or ""), row["path"]),
    )
    inventory.append(
        {
            "artifact_kind": str(artifact_kind),
            "fit_scope": str(fit_scope),
            "market_id": str(market_id),
            "folder_count": len(folder_entries),
            "folders": folder_entries,
            "row_count": len(rows),
            "row_target_dates": [
                {"target_date": target_date, "row_count": date_counts[target_date]}
                for target_date in sorted(date_counts)
            ],
        }
    )


def _selection_binding(preselection, inventory, output_inventory):
    lock = preselection["window_lock"]
    locked_dates = list(lock["target_dates"])
    universe_sha256, universe_dates, training_dates = (
        _production_date_scope(preselection)
    )
    entries = sorted(
        (dict(row) for row in inventory),
        key=lambda row: (
            row["artifact_kind"],
            row["fit_scope"],
            row["market_id"],
        ),
    )
    locked = set(locked_dates)
    used_dates = {
        row["target_date"]
        for entry in entries
        for row in entry["row_target_dates"]
    } | {
        row["target_date"]
        for entry in entries
        for row in entry["folders"]
        if row.get("target_date")
    }
    overlap = sorted(locked & used_dates)
    if overlap:
        raise ValueError(
            "locked evaluation dates reached family-secondary selection inventory: "
            + ", ".join(overlap)
        )
    outside_universe = sorted(used_dates - set(training_dates))
    if outside_universe:
        raise ValueError(
            "family-secondary selection inventory escaped the immutable "
            "preselection training universe: " + ", ".join(outside_universe)
        )
    inventory_payload = {
        **_hashed_inventory(entries),
        "folder_count": sum(row["folder_count"] for row in entries),
        "row_count": sum(row["row_count"] for row in entries),
    }
    inventory_payload["sha256"] = _sha256_json({
        key: value
        for key, value in inventory_payload.items()
        if key != "sha256"
    })
    inventory_sha256 = inventory_payload["sha256"]
    output_inventory = _verify_hashed_inventory(
        output_inventory,
        "family-secondary output artifact inventory",
    )
    binding = {
        "preselection_hash": preselection["preselection_hash"],
        "window_lock_id": lock["window_lock_id"],
        "selection_universe_sha256": universe_sha256,
        "selection_universe_dates": universe_dates,
        "training_universe_dates": training_dates,
        "training_universe_sha256": _sha256_json(training_dates),
        "locked_dates": locked_dates,
        "used_for_selection": False,
        "trust_as_of_exclusive": locked_dates[0],
        "trust_date_scope": "exact_preselection_training_universe",
        "trust_included_target_dates_sha256": _sha256_json(training_dates),
        "source_folder_date_inventory_sha256": inventory_sha256,
        "source_inventory": inventory_payload,
        "output_artifact_inventory_sha256": output_inventory["sha256"],
        "output_artifacts": output_inventory,
    }
    binding["binding_sha256"] = _sha256_json(binding)
    return binding


def _expected_source_inventory_keys(family_unit, market_ids):
    return {
        (artifact_kind, fit_scope, market_id)
        for artifact_kind in ARTIFACT_KINDS
        for market_id in market_ids
        for fit_scope in ("market", f"family:{family_unit}")
    }


def _verify_source_inventory_coverage(
    inventory,
    *,
    family_unit,
    market_ids,
):
    if not market_ids:
        raise ValueError(
            "production family-secondary selection requires at least one market"
        )
    actual = []
    for entry in inventory or ():
        if not isinstance(entry, dict):
            raise ValueError(
                "production family-secondary source inventory is malformed"
            )
        key = (
            str(entry.get("artifact_kind") or ""),
            str(entry.get("fit_scope") or ""),
            str(entry.get("market_id") or ""),
        )
        try:
            row_count = int(entry.get("row_count"))
            folder_count = int(entry.get("folder_count"))
        except (TypeError, ValueError):
            raise ValueError(
                "production family-secondary source inventory has invalid "
                f"counts: {key}"
            ) from None
        if row_count <= 0:
            raise ValueError(
                "production family-secondary source inventory has an empty "
                f"selection stage: {key}"
            )
        row_dates = entry.get("row_target_dates")
        folders = entry.get("folders")
        if not isinstance(row_dates, list) or not isinstance(folders, list):
            raise ValueError(
                "production family-secondary source inventory has incomplete "
                f"row-date coverage: {key}"
            )
        if folder_count < 0 or folder_count != len(folders):
            raise ValueError(
                "production family-secondary source inventory has incomplete "
                f"folder coverage: {key}"
            )
        covered_rows = 0
        seen_dates = set()
        try:
            for row in row_dates:
                if not isinstance(row, dict):
                    raise ValueError
                target_date = date.fromisoformat(
                    str(row.get("target_date") or "")
                ).isoformat()
                date_rows = int(row.get("row_count"))
                if date_rows <= 0 or target_date in seen_dates:
                    raise ValueError
                seen_dates.add(target_date)
                covered_rows += date_rows
            for folder in folders:
                if not isinstance(folder, dict):
                    raise ValueError
                target_date = folder.get("target_date")
                if target_date is not None:
                    date.fromisoformat(str(target_date))
        except (TypeError, ValueError):
            raise ValueError(
                "production family-secondary source inventory has malformed "
                f"date coverage: {key}"
            ) from None
        if covered_rows != row_count:
            raise ValueError(
                "production family-secondary source inventory has incomplete "
                f"row-date coverage: {key}"
            )
        actual.append(key)
    expected = _expected_source_inventory_keys(family_unit, market_ids)
    if len(actual) != len(set(actual)) or set(actual) != expected:
        missing = sorted(expected - set(actual))
        unexpected = sorted(set(actual) - expected)
        raise ValueError(
            "production family-secondary source inventory coverage is incomplete; "
            f"missing={missing}, unexpected={unexpected}"
        )


def _output_artifact_entry(
    result,
    *,
    artifact_kind,
    fit_scope,
    market_id,
    required,
    require_declared_identity,
):
    if not isinstance(result, dict):
        if required:
            raise ValueError(
                "production family-secondary output is missing: "
                f"{fit_scope}/{market_id or '-'}:{artifact_kind}"
            )
        return None
    status = str(result.get("status") or "")
    if status != "ok":
        if required:
            raise ValueError(
                "production family-secondary output is not usable: "
                f"{fit_scope}/{market_id or '-'}:{artifact_kind} status={status or 'missing'}"
            )
        return None
    path_text = str(result.get("artifact") or "").strip()
    path = Path(path_text)
    if not path_text or path.is_symlink() or not path.is_file():
        raise ValueError(
            "family-secondary output artifact is missing or invalid: "
            f"{fit_scope}/{market_id or '-'}:{artifact_kind}"
        )
    path = path.resolve()
    digest = _sha256_file(path)
    byte_count = path.stat().st_size
    declared_digest = str(result.get("artifact_sha256") or "")
    declared_bytes = result.get("artifact_bytes")
    if require_declared_identity and (
        len(declared_digest) != 64 or declared_bytes is None
    ):
        raise ValueError(
            f"family-secondary output artifact identity is missing: {path}"
        )
    if declared_digest and declared_digest != digest:
        raise ValueError(
            f"family-secondary output artifact hash changed: {path}"
        )
    if declared_bytes is not None:
        try:
            size_matches = int(declared_bytes) == byte_count
        except (TypeError, ValueError):
            size_matches = False
        if not size_matches:
            raise ValueError(
                f"family-secondary output artifact size changed: {path}"
            )
    result["artifact"] = path.as_posix()
    result["artifact_sha256"] = digest
    result["artifact_bytes"] = byte_count
    return {
        "artifact_kind": artifact_kind,
        "fit_scope": fit_scope,
        "market_id": market_id,
        "path": path.as_posix(),
        "sha256": digest,
        "bytes": byte_count,
    }


def _build_output_artifact_inventory(
    family_unit,
    family_artifacts,
    markets,
    *,
    require_complete,
    require_declared_identity=False,
):
    entries = []
    for artifact_kind in ARTIFACT_KINDS:
        entry = _output_artifact_entry(
            (family_artifacts or {}).get(artifact_kind),
            artifact_kind=artifact_kind,
            fit_scope=f"family:{family_unit}",
            market_id="",
            required=require_complete,
            require_declared_identity=require_declared_identity,
        )
        if entry is not None:
            entries.append(entry)
    for market_id, market in sorted((markets or {}).items()):
        artifacts = (market or {}).get("artifacts") or {}
        for artifact_kind in ARTIFACT_KINDS:
            entry = _output_artifact_entry(
                artifacts.get(artifact_kind),
                artifact_kind=artifact_kind,
                fit_scope="market",
                market_id=str(market_id),
                required=require_complete,
                require_declared_identity=require_declared_identity,
            )
            if entry is not None:
                entries.append(entry)
    entries.sort(
        key=lambda row: (
            row["artifact_kind"],
            row["fit_scope"],
            row["market_id"],
        )
    )
    paths = [row["path"] for row in entries]
    if len(paths) != len(set(paths)):
        raise ValueError("family-secondary output artifact paths are duplicated")
    return _hashed_inventory(entries)


def verify_production_family_manifest(manifest, preselection=None):
    """Verify selection coverage and every content-addressed output in place."""

    if not isinstance(manifest, dict):
        raise ValueError("production family-secondary manifest must be an object")
    binding = manifest.get("point_in_time_selection_binding")
    if not isinstance(binding, dict):
        raise ValueError("production family-secondary selection binding is missing")
    unhashed_binding = dict(binding)
    binding_sha256 = str(unhashed_binding.pop("binding_sha256", "") or "")
    if len(binding_sha256) != 64 or binding_sha256 != _sha256_json(
        unhashed_binding
    ):
        raise ValueError("production family-secondary selection binding hash is invalid")
    locked_dates = list(binding.get("locked_dates") or ())
    try:
        canonical_locked_dates = [
            date.fromisoformat(str(value)).isoformat() for value in locked_dates
        ]
    except ValueError:
        raise ValueError(
            "production family-secondary locked dates are invalid"
        ) from None
    training_dates = list(binding.get("training_universe_dates") or ())
    universe_dates = list(binding.get("selection_universe_dates") or ())
    try:
        canonical_universe_dates = [
            date.fromisoformat(str(value)).isoformat()
            for value in universe_dates
        ]
        canonical_training_dates = [
            date.fromisoformat(str(value)).isoformat()
            for value in training_dates
        ]
    except ValueError:
        raise ValueError(
            "production family-secondary training-universe dates are invalid"
        ) from None
    if (
        len(canonical_locked_dates) != 14
        or len(set(canonical_locked_dates)) != 14
        or canonical_locked_dates != locked_dates
        or not canonical_universe_dates
        or canonical_universe_dates != universe_dates
        or len(canonical_universe_dates) != len(set(canonical_universe_dates))
        or not set(canonical_locked_dates) <= set(canonical_universe_dates)
        or not canonical_training_dates
        or canonical_training_dates != training_dates
        or len(canonical_training_dates) != len(set(canonical_training_dates))
        or set(canonical_locked_dates) & set(canonical_training_dates)
        or canonical_training_dates
        != [
            value
            for value in canonical_universe_dates
            if value not in set(canonical_locked_dates)
        ]
        or len(str(binding.get("selection_universe_sha256") or "")) != 64
        or binding.get("training_universe_sha256")
        != _sha256_json(canonical_training_dates)
        or binding.get("used_for_selection") is not False
        or binding.get("trust_as_of_exclusive") != canonical_locked_dates[0]
        or binding.get("trust_date_scope")
        != "exact_preselection_training_universe"
        or binding.get("trust_included_target_dates_sha256")
        != _sha256_json(canonical_training_dates)
    ):
        raise ValueError(
            "production family-secondary selection binding policy is invalid"
        )
    if (
        len(str(binding.get("preselection_hash") or "")) != 64
        or len(str(binding.get("window_lock_id") or "")) != 64
    ):
        raise ValueError(
            "production family-secondary preselection identity is invalid"
        )

    source_inventory = _verify_hashed_inventory(
        binding.get("source_inventory"),
        "family-secondary source inventory",
    )
    if (
        binding.get("source_folder_date_inventory_sha256")
        != source_inventory["sha256"]
    ):
        raise ValueError("family-secondary source inventory binding is invalid")
    markets = manifest.get("markets")
    family_artifacts = manifest.get("family_artifacts")
    if not isinstance(markets, dict) or not isinstance(family_artifacts, dict):
        raise ValueError("production family-secondary artifact scopes are malformed")
    market_ids = sorted(str(value) for value in markets)
    family_unit = str(manifest.get("family_unit") or "")
    if not family_unit:
        raise ValueError("production family-secondary family unit is missing")
    _verify_source_inventory_coverage(
        source_inventory["entries"],
        family_unit=family_unit,
        market_ids=market_ids,
    )
    locked = set(canonical_locked_dates)
    used_dates = {
        str(row.get("target_date") or "")
        for entry in source_inventory["entries"]
        for row in (
            list(entry.get("row_target_dates") or ())
            + list(entry.get("folders") or ())
        )
        if row.get("target_date")
    }
    if locked & used_dates:
        raise ValueError(
            "locked evaluation dates reached family-secondary source inventory"
        )
    outside_universe = sorted(used_dates - set(canonical_training_dates))
    if outside_universe:
        raise ValueError(
            "family-secondary source inventory escaped the immutable "
            "preselection training universe: " + ", ".join(outside_universe)
        )

    rebuilt_outputs = _build_output_artifact_inventory(
        family_unit,
        family_artifacts,
        markets,
        require_complete=True,
        require_declared_identity=True,
    )
    artifact_root_text = str(manifest.get("artifact_root") or "").strip()
    artifact_root = Path(artifact_root_text).resolve() if artifact_root_text else None
    if (
        artifact_root is None
        or artifact_root.is_symlink()
        or any(
            not Path(row["path"]).resolve().is_relative_to(artifact_root)
            for row in rebuilt_outputs["entries"]
        )
    ):
        raise ValueError(
            "production family-secondary outputs are not candidate-root confined"
        )
    stored_outputs = _verify_hashed_inventory(
        manifest.get("output_artifact_inventory"),
        "family-secondary manifest output artifact inventory",
    )
    bound_outputs = _verify_hashed_inventory(
        binding.get("output_artifacts"),
        "family-secondary bound output artifact inventory",
    )
    if (
        rebuilt_outputs != stored_outputs
        or stored_outputs != bound_outputs
        or binding.get("output_artifact_inventory_sha256")
        != stored_outputs["sha256"]
    ):
        raise ValueError("family-secondary output artifact binding is invalid")
    if preselection is not None:
        expected = _verified_preselection(preselection)
        expected_universe_sha256, expected_universe, expected_training_dates = (
            _production_date_scope(expected)
        )
        if (
            binding.get("preselection_hash") != expected["preselection_hash"]
            or binding.get("window_lock_id")
            != expected["window_lock"]["window_lock_id"]
            or binding.get("selection_universe_sha256")
            != expected_universe_sha256
            or list(binding.get("selection_universe_dates") or ())
            != expected_universe
            or list(binding.get("training_universe_dates") or ())
            != expected_training_dates
            or binding.get("training_universe_sha256")
            != _sha256_json(expected_training_dates)
            or list(binding.get("locked_dates") or ())
            != list(expected["window_lock"]["target_dates"])
        ):
            raise ValueError(
                "family-secondary manifest is bound to a different preselection"
            )
    return binding


def family_specs(unit=DEFAULT_FAMILY_UNIT):
    return [spec for spec in all_specs() if spec.display_unit == unit]


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _artifact_output_path(output_root, name):
    if output_root is None:
        return writable_artifact_path(name)
    return Path(output_root).resolve() / "artifacts" / name


def _artifact_report_path(output_root, name):
    if output_root is None:
        return data_path() / "backtest" / name
    return Path(output_root).resolve() / "reports" / name


def artifact_paths(spec, output_root=None):
    return {
        "probability_calibration": {
            "artifact": _artifact_output_path(output_root, f"probability_calibration{spec.artifact_suffix}.json"),
            "report": _artifact_report_path(output_root, f"probability_calibration_report{spec.artifact_suffix}.md"),
        },
        "forecast_error": {
            "artifact": _artifact_output_path(output_root, f"forecast_error_model{spec.artifact_suffix}.json"),
            "report": _artifact_report_path(output_root, f"forecast_error_report{spec.artifact_suffix}.md"),
        },
        "settlement_lag": {
            "artifact": _artifact_output_path(output_root, f"settlement_lag_model{spec.artifact_suffix}.json"),
            "report": _artifact_report_path(output_root, f"settlement_lag_report{spec.artifact_suffix}.md"),
        },
    }


def family_artifact_paths(family_unit, output_root=None):
    suffix = family_unit.lower()
    return {
        "probability_calibration": {
            "artifact": _artifact_output_path(output_root, f"probability_calibration_{suffix}_family.json"),
            "report": _artifact_report_path(output_root, f"probability_calibration_report_{suffix}_family.md"),
        },
        "forecast_error": {
            "artifact": _artifact_output_path(output_root, f"forecast_error_model_{suffix}_family.json"),
            "report": _artifact_report_path(output_root, f"forecast_error_report_{suffix}_family.md"),
        },
        "settlement_lag": {
            "artifact": _artifact_output_path(output_root, f"settlement_lag_model_{suffix}_family.json"),
            "report": _artifact_report_path(output_root, f"settlement_lag_report_{suffix}_family.md"),
        },
    }


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _accepted_quality_grades(value):
    return [grade.strip() for grade in str(value).split(",") if grade.strip()]


def _relative(path):
    return Path(path).as_posix()


def _error_status(exc):
    return {"status": "error", "error": str(exc)}


def probability_training_rows(
    spec,
    snapshots_root,
    quality_grades,
    *,
    locked_dates=None,
    included_target_dates=None,
    selection_inventory=None,
    fit_scope="market",
):
    folders = probability_calibration.discover_default_folders(snapshots_root, market_id=spec.id)
    folders = _exclude_locked_folders(
        folders,
        locked_dates,
        included_target_dates,
    )
    skipped = []
    if quality_grades != ["all"]:
        folders, skipped = probability_calibration.filter_folders_by_quality(folders, quality_grades)
    if not folders:
        _record_source_inventory(
            selection_inventory,
            artifact_kind="probability_calibration",
            fit_scope=fit_scope,
            market_id=spec.id,
            rows=[],
            folders=folders,
        )
        return [], folders, skipped
    rows = probability_calibration.read_scored_rows(
        folders,
        daily_summary_path=spec.data_root / "daily" / "daily_summary.csv",
    )
    rows = _exclude_locked_rows(
        rows,
        locked_dates,
        included_target_dates,
    )
    _record_source_inventory(
        selection_inventory,
        artifact_kind="probability_calibration",
        fit_scope=fit_scope,
        market_id=spec.id,
        rows=rows,
        folders=folders,
    )
    return rows, folders, skipped


def train_probability_artifact(
    spec,
    snapshots_root,
    quality_grades,
    *,
    locked_dates=None,
    included_target_dates=None,
    selection_inventory=None,
    output_root=None,
):
    paths = artifact_paths(spec, output_root=output_root)["probability_calibration"]
    rows, folders, skipped = probability_training_rows(
        spec,
        snapshots_root,
        quality_grades,
        locked_dates=locked_dates,
        included_target_dates=included_target_dates,
        selection_inventory=selection_inventory,
        fit_scope="market",
    )
    if not folders:
        return {
            "status": "skipped",
            "reason": "no folders after quality filter",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": 0,
            "skipped_count": len(skipped),
        }
    if not rows:
        return {
            "status": "skipped",
            "reason": "no scored rows",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": len(folders),
            "skipped_count": len(skipped),
        }
    artifact = probability_calibration.build_artifact(rows, folders)
    artifact["training"]["quality_grades"] = quality_grades
    _write_json(paths["artifact"], artifact)
    probability_calibration.write_report(paths["report"], artifact)
    selected = artifact.get("selected_deployable_candidate") or {}
    return {
        "status": "ok",
        "artifact": _relative(paths["artifact"]),
        "report": _relative(paths["report"]),
        "folder_count": len(folders),
        "skipped_count": len(skipped),
        "row_count": len(rows),
        "baseline_brier": (artifact.get("training") or {}).get("baseline_brier"),
        "artifact_replay_brier": (artifact.get("training") or {}).get("artifact_replay_brier"),
        "selected_method": selected.get("method"),
        "selected_param": selected.get("param"),
    }


def train_family_probability_artifact(
    specs,
    family_unit,
    snapshots_root,
    quality_grades,
    *,
    locked_dates=None,
    included_target_dates=None,
    selection_inventory=None,
    output_root=None,
):
    paths = family_artifact_paths(
        family_unit, output_root=output_root
    )["probability_calibration"]
    rows = []
    folders = []
    market_rows = {}
    skipped_count = 0
    for spec in specs:
        spec_rows, spec_folders, skipped = probability_training_rows(
            spec,
            snapshots_root,
            quality_grades,
            locked_dates=locked_dates,
            included_target_dates=included_target_dates,
            selection_inventory=selection_inventory,
            fit_scope=f"family:{family_unit}",
        )
        rows.extend(spec_rows)
        folders.extend(spec_folders)
        skipped_count += len(skipped)
        market_rows[spec.id] = len(spec_rows)
    if not rows:
        return {
            "status": "skipped",
            "reason": "no family probability rows",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": len(folders),
        }
    artifact = probability_calibration.build_artifact(rows, folders)
    artifact["family_unit"] = family_unit
    artifact["training"]["quality_grades"] = quality_grades
    artifact["training"]["market_rows"] = market_rows
    _write_json(paths["artifact"], artifact)
    probability_calibration.write_report(paths["report"], artifact)
    selected = artifact.get("selected_deployable_candidate") or {}
    return {
        "status": "ok",
        "artifact": _relative(paths["artifact"]),
        "report": _relative(paths["report"]),
        "folder_count": len(folders),
        "skipped_count": skipped_count,
        "row_count": len(rows),
        "market_rows": market_rows,
        "baseline_brier": (artifact.get("training") or {}).get("baseline_brier"),
        "artifact_replay_brier": (artifact.get("training") or {}).get("artifact_replay_brier"),
        "selected_method": selected.get("method"),
        "selected_param": selected.get("param"),
    }


def train_forecast_error_artifact(
    spec,
    snapshots_root,
    *,
    locked_dates=None,
    included_target_dates=None,
    selection_inventory=None,
    output_root=None,
):
    paths = artifact_paths(spec, output_root=output_root)["forecast_error"]
    rows, folders = forecast_error_training_rows(
        spec,
        snapshots_root,
        locked_dates=locked_dates,
        included_target_dates=included_target_dates,
        selection_inventory=selection_inventory,
        fit_scope="market",
    )
    regime_id = forecast_error.regime_for_spec(spec)
    if not rows:
        return {
            "status": "skipped",
            "reason": "no forecast error rows",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": len(folders),
        }
    artifact = forecast_error.build_artifact(
        rows,
        folders,
        market_id=spec.id,
        regime_id=regime_id,
        expected_sources=forecast_error.forecast_component_sources_for_spec(spec),
    )
    _write_json(paths["artifact"], artifact)
    forecast_error.write_report(paths["report"], artifact)
    replay = (artifact.get("evaluation") or {}).get("artifact_replay") or {}
    return {
        "status": "ok",
        "artifact": _relative(paths["artifact"]),
        "report": _relative(paths["report"]),
        "folder_count": len(folders),
        "row_count": len(rows),
        "learned_brier": replay.get("learned_brier"),
        "cap_brier": replay.get("cap_brier"),
    }


def forecast_error_training_rows(
    spec,
    snapshots_root,
    *,
    locked_dates=None,
    included_target_dates=None,
    selection_inventory=None,
    fit_scope="market",
):
    folders = forecast_error.discover_default_folders(snapshots_root, market_id=spec.id)
    folders = _exclude_locked_folders(
        folders,
        locked_dates,
        included_target_dates,
    )
    rows = forecast_error.read_training_rows(
        daily_path_for(spec),
        spec.data_root / "daily" / "daily_summary.csv",
        folders,
        market_id=spec.id,
        regime_id=forecast_error.regime_for_spec(spec),
    )
    rows = _exclude_locked_rows(
        rows,
        locked_dates,
        included_target_dates,
    )
    _record_source_inventory(
        selection_inventory,
        artifact_kind="forecast_error",
        fit_scope=fit_scope,
        market_id=spec.id,
        rows=rows,
        folders=folders,
    )
    return rows, folders


def train_family_forecast_error_artifact(
    specs,
    family_unit,
    snapshots_root,
    *,
    locked_dates=None,
    included_target_dates=None,
    selection_inventory=None,
    output_root=None,
):
    paths = family_artifact_paths(
        family_unit, output_root=output_root
    )["forecast_error"]
    rows = []
    folders = []
    market_rows = {}
    for spec in specs:
        spec_rows, spec_folders = forecast_error_training_rows(
            spec,
            snapshots_root,
            locked_dates=locked_dates,
            included_target_dates=included_target_dates,
            selection_inventory=selection_inventory,
            fit_scope=f"family:{family_unit}",
        )
        rows.extend(spec_rows)
        folders.extend(spec_folders)
        market_rows[spec.id] = len(spec_rows)
    if not rows:
        return {
            "status": "skipped",
            "reason": "no family forecast error rows",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": len(folders),
        }
    artifact = forecast_error.build_artifact(
        rows,
        folders,
        family_unit=family_unit,
        expected_sources=sorted({
            source
            for spec in specs
            for source in forecast_error.forecast_component_sources_for_spec(spec)
        }),
    )
    artifact["family_unit"] = family_unit
    artifact["training"]["market_rows"] = market_rows
    _write_json(paths["artifact"], artifact)
    forecast_error.write_report(paths["report"], artifact)
    replay = (artifact.get("evaluation") or {}).get("artifact_replay") or {}
    return {
        "status": "ok",
        "artifact": _relative(paths["artifact"]),
        "report": _relative(paths["report"]),
        "folder_count": len(folders),
        "row_count": len(rows),
        "market_rows": market_rows,
        "learned_brier": replay.get("learned_brier"),
        "cap_brier": replay.get("cap_brier"),
    }


def train_settlement_lag_artifact(
    spec,
    snapshots_root,
    *,
    locked_dates=None,
    included_target_dates=None,
    selection_inventory=None,
    output_root=None,
):
    paths = artifact_paths(spec, output_root=output_root)["settlement_lag"]
    rows, folders = settlement_lag_training_rows(
        spec,
        snapshots_root,
        locked_dates=locked_dates,
        included_target_dates=included_target_dates,
        selection_inventory=selection_inventory,
        fit_scope="market",
    )
    if not rows:
        return {
            "status": "skipped",
            "reason": "no settlement lag rows",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": len(folders),
        }
    artifact = settlement_lag.build_artifact(rows, folders)
    _write_json(paths["artifact"], artifact)
    settlement_lag.write_report(paths["report"], artifact)
    global_context = (artifact.get("catchup_contexts") or {}).get("global") or {}
    return {
        "status": "ok",
        "artifact": _relative(paths["artifact"]),
        "report": _relative(paths["report"]),
        "folder_count": len(folders),
        "lead_rows": (artifact.get("training") or {}).get("lead_rows"),
        "revision_rows": (artifact.get("training") or {}).get("revision_rows"),
        "global_catchup_rate": global_context.get("catchup_rate"),
    }


def settlement_lag_training_rows(
    spec,
    snapshots_root,
    *,
    locked_dates=None,
    included_target_dates=None,
    selection_inventory=None,
    fit_scope="market",
):
    folders = settlement_lag.discover_default_folders(snapshots_root, market_id=spec.id)
    folders = _exclude_locked_folders(
        folders,
        locked_dates,
        included_target_dates,
    )
    rows = settlement_lag.read_training_rows(
        spec.data_root / "hourly",
        data_path() / "metar" / spec.icao.lower() / "hourly",
        spec.data_root / "daily" / "daily_summary.csv",
        folders,
    )
    rows = _exclude_locked_rows(
        rows,
        locked_dates,
        included_target_dates,
    )
    _record_source_inventory(
        selection_inventory,
        artifact_kind="settlement_lag",
        fit_scope=fit_scope,
        market_id=spec.id,
        rows=rows,
        folders=folders,
    )
    return rows, folders


def train_family_settlement_lag_artifact(
    specs,
    family_unit,
    snapshots_root,
    *,
    locked_dates=None,
    included_target_dates=None,
    selection_inventory=None,
    output_root=None,
):
    paths = family_artifact_paths(
        family_unit, output_root=output_root
    )["settlement_lag"]
    rows = []
    folders = []
    market_rows = {}
    for spec in specs:
        spec_rows, spec_folders = settlement_lag_training_rows(
            spec,
            snapshots_root,
            locked_dates=locked_dates,
            included_target_dates=included_target_dates,
            selection_inventory=selection_inventory,
            fit_scope=f"family:{family_unit}",
        )
        rows.extend(spec_rows)
        folders.extend(spec_folders)
        market_rows[spec.id] = len(spec_rows)
    if not rows:
        return {
            "status": "skipped",
            "reason": "no family settlement lag rows",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": len(folders),
        }
    artifact = settlement_lag.build_artifact(rows, folders)
    artifact["family_unit"] = family_unit
    artifact["training"]["market_rows"] = market_rows
    _write_json(paths["artifact"], artifact)
    settlement_lag.write_report(paths["report"], artifact)
    global_context = (artifact.get("catchup_contexts") or {}).get("global") or {}
    return {
        "status": "ok",
        "artifact": _relative(paths["artifact"]),
        "report": _relative(paths["report"]),
        "folder_count": len(folders),
        "market_rows": market_rows,
        "lead_rows": (artifact.get("training") or {}).get("lead_rows"),
        "revision_rows": (artifact.get("training") or {}).get("revision_rows"),
        "global_catchup_rate": global_context.get("catchup_rate"),
    }


def gate_for_market(trust_row, artifacts, family_artifacts=None, min_trust=DEFAULT_MIN_TRUST,
                    min_settled_days=DEFAULT_MIN_SETTLED_DAYS):
    trust_score = (trust_row or {}).get("trust_score")
    settled_days = (trust_row or {}).get("settled_days", 0)
    reasons = []
    if trust_score is None or int(trust_score) < int(min_trust):
        reasons.append(f"trust {trust_score if trust_score is not None else '-'} < {min_trust}")
    if int(settled_days or 0) < int(min_settled_days):
        reasons.append(f"settled_days {settled_days or 0} < {min_settled_days}")
    missing = [
        kind for kind in ARTIFACT_KINDS
        if (artifacts.get(kind) or {}).get("status") != "ok"
    ]
    if missing:
        reasons.append("missing artifacts: " + ", ".join(missing))
    missing_family = [
        kind for kind in ARTIFACT_KINDS
        if family_artifacts is not None
        and (family_artifacts.get(kind) or {}).get("status") != "ok"
    ]
    if missing_family:
        reasons.append("missing family artifacts: " + ", ".join(missing_family))
    mode = "ml" if not reasons else "empirical"
    return {
        "mode": mode,
        "reason": "; ".join(reasons) if reasons else "trust and artifacts clear",
        "min_trust_score": int(min_trust),
        "min_settled_days": int(min_settled_days),
    }


def build_family_manifest(family_unit=DEFAULT_FAMILY_UNIT, snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
                          quality_grades=DEFAULT_QUALITY_GRADES,
                          min_trust=DEFAULT_MIN_TRUST,
                          min_settled_days=DEFAULT_MIN_SETTLED_DAYS,
                          preselection=None,
                          artifact_root=None):
    verified_preselection = (
        _verified_preselection(preselection) if preselection is not None else None
    )
    locked_dates = (
        list(verified_preselection["window_lock"]["target_dates"])
        if verified_preselection is not None
        else None
    )
    included_target_dates = (
        _production_date_scope(verified_preselection)[2]
        if verified_preselection is not None
        else None
    )
    output_root = Path(artifact_root).resolve() if artifact_root else None
    if verified_preselection is not None and output_root is None:
        raise ValueError(
            "production family-secondary training requires a candidate artifact root"
        )
    selection_inventory = [] if verified_preselection is not None else None
    selection_kwargs = (
        {
            "locked_dates": locked_dates,
            "included_target_dates": included_target_dates,
            "selection_inventory": selection_inventory,
        }
        if verified_preselection is not None
        else {}
    )
    quality = _accepted_quality_grades(quality_grades)
    specs = family_specs(family_unit)
    family_artifacts = {}
    try:
        family_artifacts["probability_calibration"] = train_family_probability_artifact(
            specs,
            family_unit,
            snapshots_root,
            quality,
            output_root=output_root,
            **selection_kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        family_artifacts["probability_calibration"] = _error_status(exc)
    try:
        family_artifacts["forecast_error"] = train_family_forecast_error_artifact(
            specs,
            family_unit,
            snapshots_root,
            output_root=output_root,
            **selection_kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        family_artifacts["forecast_error"] = _error_status(exc)
    try:
        family_artifacts["settlement_lag"] = train_family_settlement_lag_artifact(
            specs,
            family_unit,
            snapshots_root,
            output_root=output_root,
            **selection_kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        family_artifacts["settlement_lag"] = _error_status(exc)
    trust_kwargs = {"root": snapshots_root}
    if locked_dates:
        trust_kwargs["as_of"] = locked_dates[0]
        trust_kwargs["included_target_dates"] = included_target_dates
    trust_rows = {
        row["market"]: row
        for row in score_all_markets(**trust_kwargs)
        if row.get("market")
    }
    markets = {}
    for spec in specs:
        artifacts = {}
        try:
            artifacts["probability_calibration"] = train_probability_artifact(
                spec,
                snapshots_root,
                quality,
                output_root=output_root,
                **selection_kwargs,
            )
        except Exception as exc:  # noqa: BLE001 - one market must not kill the family run
            artifacts["probability_calibration"] = _error_status(exc)
        try:
            artifacts["forecast_error"] = train_forecast_error_artifact(
                spec,
                snapshots_root,
                output_root=output_root,
                **selection_kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            artifacts["forecast_error"] = _error_status(exc)
        try:
            artifacts["settlement_lag"] = train_settlement_lag_artifact(
                spec,
                snapshots_root,
                output_root=output_root,
                **selection_kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            artifacts["settlement_lag"] = _error_status(exc)

        trust = trust_rows.get(spec.id) or {}
        gate = gate_for_market(
            trust,
            artifacts,
            family_artifacts=family_artifacts,
            min_trust=min_trust,
            min_settled_days=min_settled_days,
        )
        markets[spec.id] = {
            "city": spec.city_label,
            "unit": spec.display_unit,
            "artifact_suffix": spec.artifact_suffix,
            "trust": trust,
            "artifacts": artifacts,
            "serving_gate": gate,
        }

    market_ids = sorted(markets)
    if verified_preselection is not None:
        _verify_source_inventory_coverage(
            selection_inventory,
            family_unit=family_unit,
            market_ids=market_ids,
        )
    output_artifact_inventory = None
    if verified_preselection is not None:
        output_artifact_inventory = _build_output_artifact_inventory(
            family_unit,
            family_artifacts,
            markets,
            require_complete=True,
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "family_unit": family_unit,
        "snapshots_root": str(snapshots_root),
        "quality_grades": quality,
        "family_artifacts": family_artifacts,
        "gate": {
            "min_trust_score": int(min_trust),
            "min_settled_days": int(min_settled_days),
            "default_mode": "empirical",
            "policy": "serve feature ML only when trust and all secondary artifacts clear",
        },
        "markets": markets,
    }
    if verified_preselection is not None:
        manifest["artifact_root"] = str(output_root)
        manifest["output_artifact_inventory"] = output_artifact_inventory
        manifest["point_in_time_selection_binding"] = _selection_binding(
            verified_preselection,
            selection_inventory,
            output_artifact_inventory,
        )
        verify_production_family_manifest(
            manifest,
            preselection=verified_preselection,
        )
    return manifest


def load_family_secondary_manifest(path=DEFAULT_MANIFEST):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - serving should fall back cleanly
        print(f"Error loading family secondary artifact manifest: {exc}")
        return None


def market_gate(manifest, market_id):
    if not manifest:
        return {"mode": "ml", "reason": "no family secondary manifest"}
    market = (manifest.get("markets") or {}).get(market_id)
    if not market:
        return {"mode": "ml", "reason": "market not governed by manifest"}
    return market.get("serving_gate") or {"mode": "empirical", "reason": "missing serving gate"}


def feature_model_allowed(manifest, market_id):
    return market_gate(manifest, market_id).get("mode") == "ml"


def _fmt(value, decimals=4):
    if value is None:
        return "-"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def write_report(path, manifest):
    family_rows = []
    for kind, artifact in sorted((manifest.get("family_artifacts") or {}).items()):
        family_rows.append([
            kind,
            artifact.get("status"),
            artifact.get("artifact"),
            artifact.get("row_count") or artifact.get("lead_rows") or "-",
            _fmt(artifact.get("artifact_replay_brier")
                 or artifact.get("learned_brier")
                 or artifact.get("global_catchup_rate")),
        ])
    rows = []
    for market_id, market in sorted((manifest.get("markets") or {}).items()):
        artifacts = market.get("artifacts") or {}
        trust = market.get("trust") or {}
        gate = market.get("serving_gate") or {}
        rows.append([
            market_id,
            market.get("city"),
            trust.get("trust_score"),
            trust.get("settled_days"),
            gate.get("mode"),
            gate.get("reason"),
            (artifacts.get("probability_calibration") or {}).get("status"),
            _fmt((artifacts.get("probability_calibration") or {}).get("artifact_replay_brier")),
            (artifacts.get("forecast_error") or {}).get("status"),
            _fmt((artifacts.get("forecast_error") or {}).get("learned_brier")),
            (artifacts.get("settlement_lag") or {}).get("status"),
            (artifacts.get("settlement_lag") or {}).get("lead_rows"),
        ])
    lines = [
        f"# {manifest.get('family_unit') or DEFAULT_FAMILY_UNIT}-Family Secondary Artifacts",
        "",
        f"Generated: {manifest.get('generated_at_utc')}",
        f"Schema: `{manifest.get('schema_version')}`",
        f"Family unit: `{manifest.get('family_unit')}`",
        "",
        "## Serving Gate",
        "",
        f"- Minimum trust score: `{(manifest.get('gate') or {}).get('min_trust_score')}`",
        f"- Minimum settled days: `{(manifest.get('gate') or {}).get('min_settled_days')}`",
        f"- Default mode: `{(manifest.get('gate') or {}).get('default_mode')}`",
        "",
        "## Family Artifacts",
        "",
    ]
    lines += markdown_table(
        ["Kind", "Status", "Artifact", "Rows/Lead Rows", "Headline Metric"],
        family_rows,
    )
    lines += [
        "",
        "## Markets",
        "",
    ]
    lines += markdown_table(
        [
            "Market", "City", "Trust", "Days", "Mode", "Reason",
            "Probability Cal", "Cal Brier", "Forecast Error", "Forecast Brier",
            "Lag", "Lead Rows",
        ],
        rows,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def cmd_train(args):
    preselection = None
    preselection_path = getattr(args, "point_in_time_preselection_lock", "")
    if preselection_path:
        try:
            preselection = _verified_preselection(
                preselection_path
            )
        except ValueError as exc:
            raise SystemExit(
                f"Invalid production point-in-time preselection lock: {exc}"
            ) from exc
    artifact_root = Path(args.artifact_root).resolve() if args.artifact_root else None
    if args.family_unit == "C":
        if artifact_root is None:
            raise SystemExit(
                "Inactive C-family training requires an explicit candidate --artifact-root"
            )
        if (
            Path(args.out).resolve() == Path(DEFAULT_MANIFEST).resolve()
            or Path(args.report).resolve() == Path(DEFAULT_REPORT).resolve()
        ):
            raise SystemExit(
                "Inactive C-family training requires explicit candidate --out and --report paths"
            )
    if preselection is not None:
        manifest_parent = Path(args.out).resolve().parent
        if (
            artifact_root is None
            or artifact_root == manifest_parent
            or not artifact_root.is_relative_to(manifest_parent)
        ):
            raise SystemExit(
                "Production family-secondary --artifact-root must be a child "
                "of the candidate manifest directory"
            )
    elif args.family_unit == "C":
        manifest_parent = Path(args.out).resolve().parent
        if (
            artifact_root == manifest_parent
            or not artifact_root.is_relative_to(manifest_parent)
        ):
            raise SystemExit(
                "Inactive C-family --artifact-root must be a child of the candidate "
                "manifest directory"
            )
    try:
        manifest = build_family_manifest(
            family_unit=args.family_unit,
            snapshots_root=Path(args.snapshots_root),
            quality_grades=args.quality_grades,
            min_trust=args.min_trust,
            min_settled_days=args.min_settled_days,
            preselection=preselection,
            artifact_root=artifact_root,
        )
    except ValueError as exc:
        if preselection is None:
            raise
        raise SystemExit(
            f"Production family-secondary integrity check failed: {exc}"
        ) from exc
    manifest_path = _write_json(args.out, manifest)
    report_path = write_report(args.report, manifest)
    modes = {}
    for market in (manifest.get("markets") or {}).values():
        mode = (market.get("serving_gate") or {}).get("mode")
        modes[mode] = modes.get(mode, 0) + 1
    print(f"Wrote family secondary manifest to {manifest_path}")
    print(f"Wrote family secondary report to {report_path}")
    print("Serving modes: " + ", ".join(f"{mode}={count}" for mode, count in sorted(modes.items())))


def build_parser():
    parser = argparse.ArgumentParser(description="Train family secondary artifacts and serving gate.")
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument(
        "--family-unit",
        default=DEFAULT_FAMILY_UNIT,
        choices=["F", "C"],
        help="Native-unit family to fit; C is the inactive Toronto candidate lane.",
    )
    train.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    train.add_argument("--quality-grades", default=DEFAULT_QUALITY_GRADES)
    train.add_argument("--min-trust", type=int, default=DEFAULT_MIN_TRUST)
    train.add_argument("--min-settled-days", type=int, default=DEFAULT_MIN_SETTLED_DAYS)
    train.add_argument(
        "--point-in-time-preselection-lock",
        default="",
        help=(
            "Production only: verified preselection JSON whose 14 locked dates "
            "must be excluded from every family-secondary fit."
        ),
    )
    train.add_argument(
        "--artifact-root",
        default="",
        help=(
            "Production only: candidate-owned directory for all fitted family "
            "and market artifacts; must be below the manifest directory."
        ),
    )
    train.add_argument("--out", default=str(DEFAULT_MANIFEST))
    train.add_argument("--report", default=str(DEFAULT_REPORT))
    train.set_defaults(func=cmd_train)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

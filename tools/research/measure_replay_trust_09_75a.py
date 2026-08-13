"""Census and replay the outcome-blind -09-75a incumbent control.

This extends -09-74a without entering its candidate or ceiling path.  It
projects only non-outcome keys from the retained B artifacts, inventories
runtime binding across all replay-supported B feature snapshots, and replays
the full decision stratum under each captured historical runtime.  The four
M4 source-switch rows are retained as a separate diagnostic population.

No settlement, realized band, market probability, provider, candidate, or C
endpoint is read by this harness.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_SEED = SCRIPT_PATH.with_name("measure_replay_trust_09_75a_seed.json")
DEFAULT_RUN_ROOT = DEFAULT_REPO_ROOT / "scratch" / "runs" / "replay-trust-09-75a"
sys.path.insert(0, str(SCRIPT_PATH.parent))
import measure_repair_ceiling_09_74a as parent  # noqa: E402
import measure_high_so_far_population_09_70a as population  # noqa: E402


DECISION_FIELDS = (
    "stratum",
    "market_id",
    "target_date",
    "snapshot_id",
    "captured_at_utc",
    "local_time",
    "minute_of_day",
    "window",
    "native_unit",
    "frozen_mechanism",
)
ROW_KEY_FIELDS = (
    "analysis_population",
    "market_id",
    "target_date",
    "snapshot_id",
    "captured_at_utc",
)
CSV_FIELDS = (
    *DECISION_FIELDS,
    "analysis_population",
    "binding_class",
    "runtime_commit",
    "model_version",
    "model_identity_hash",
    "model_code_hash",
    "model_artifact_hash",
    "replay_basis",
    "replay_attempted",
    "matches",
    "l1",
    "max_abs",
    "recorded_active_model_kind",
    "replayed_active_model_kind",
    "feature_difference_count",
    "first_feature_difference",
    "recorded_feature_source",
    "replayed_feature_source",
)
MODEL_PREFIXES = ("weather.model", "weather.calibration")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_seed(path: Path, repo_root: Path, *, verify_inputs: bool = True) -> dict[str, Any]:
    seed = json.loads(path.read_text(encoding="utf-8"))
    require(seed.get("schema_version") == "replay_trust_seed_v1", "seed schema drifted")
    if verify_inputs:
        for key, value in seed["inputs"].items():
            if not key.endswith("_relative_path"):
                continue
            prefix = key[: -len("_relative_path")]
            expected = seed["inputs"][f"{prefix}_sha256"]
            actual = sha256_file(repo_root / value)
            require(actual == expected, f"{prefix} hash mismatch: {actual}")
    return seed


def projected_rows(path: Path, fields: Iterable[str]) -> Iterable[dict[str, str]]:
    """Yield only named columns without constructing outcome-bearing rows."""

    fields = tuple(fields)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        indexes = {name: header.index(name) for name in fields}
        for raw in reader:
            yield {name: raw[indexes[name]] for name in fields}


def selected_rows(seed: dict[str, Any], repo_root: Path) -> list[dict[str, str]]:
    path = repo_root / seed["inputs"]["decision_csv_relative_path"]
    rows = list(projected_rows(path, DECISION_FIELDS))
    decision_windows = set(seed["population"]["decision_windows"])
    decision = [
        {**row, "analysis_population": "decision_stratum"}
        for row in rows
        if row["stratum"] == "B" and row["window"] in decision_windows
    ]
    mechanisms = Counter(row["frozen_mechanism"] for row in decision)
    require(
        len(decision) == seed["population"]["decision_window_events"],
        f"decision population drifted: {len(decision)}",
    )
    require(
        dict(mechanisms) == seed["population"]["decision_mechanisms"],
        f"decision mechanism census drifted: {dict(mechanisms)}",
    )
    expected_m4 = {tuple(item) for item in seed["population"]["source_switch_diagnostics"]}
    diagnostics = [
        {**row, "analysis_population": "source_switch_diagnostic"}
        for row in rows
        if row["stratum"] == "B"
        and row["frozen_mechanism"] == "M4_source_switch"
        and (row["market_id"], row["target_date"], row["snapshot_id"]) in expected_m4
    ]
    observed_m4 = {
        (row["market_id"], row["target_date"], row["snapshot_id"])
        for row in diagnostics
    }
    require(observed_m4 == expected_m4, f"source-switch diagnostic drifted: {observed_m4}")
    return decision + diagnostics


def projected_b_roster(seed: dict[str, Any], repo_root: Path) -> list[dict[str, str]]:
    path = repo_root / seed["inputs"]["roster_relative_path"]
    rows = [
        row
        for row in projected_rows(path, ("stratum", "market_id", "target_date"))
        if row["stratum"] == "B"
    ]
    require(len(rows) == 204, f"B roster drifted: {len(rows)}")
    return rows


def replay_path(root: Path, market_id: str, target_date: str) -> Path:
    return parent.replay_path(root, market_id, target_date)


def binding_metadata(raw: bytes) -> dict[str, Any]:
    model_version = population.json_value_by_key(raw, "model_version")
    runtime_identity = population.json_value_by_key(raw, "runtime_identity") or {}
    model_identity = population.json_value_by_key(raw, "model_identity") or {}
    runtime_commit = str(runtime_identity.get("git_commit") or "").strip()
    if runtime_commit:
        binding_class = "runtime_commit_bound"
    elif model_identity:
        binding_class = "model_identity_only"
    else:
        binding_class = "neither"
    return {
        "binding_class": binding_class,
        "runtime_commit": runtime_commit,
        "model_version": str(model_version or "missing"),
        "model_identity_hash": str(model_identity.get("identity_hash") or ""),
        "model_code_hash": str(model_identity.get("code_hash") or ""),
        "model_artifact_hash": str(model_identity.get("artifact_hash") or ""),
    }


def summarize_binding(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    classes = Counter(row["binding_class"] for row in rows)
    versions = Counter(row["model_version"] for row in rows)
    commits = Counter(row["runtime_commit"] for row in rows if row["runtime_commit"])
    return {
        "rows": total,
        "binding_classes": {
            key: {
                "count": classes.get(key, 0),
                "share": classes.get(key, 0) / total if total else None,
            }
            for key in ("runtime_commit_bound", "model_identity_only", "neither")
        },
        "runtime_commits": dict(sorted(commits.items())),
        "model_versions": dict(sorted(versions.items())),
    }


def extract(
    seed: dict[str, Any],
    repo_root: Path,
    snapshots_root: Path,
    run_root: Path,
) -> dict[str, Any]:
    selected = selected_rows(seed, repo_root)
    selected_by_key = {
        (row["market_id"], row["target_date"], row["snapshot_id"], row["captured_at_utc"]): row
        for row in selected
    }
    require(len(selected_by_key) == len(selected), "selected replay keys are not unique")
    roster = projected_b_roster(seed, repo_root)
    feature_rows: dict[tuple[str, str, str, str], dict[str, str]] = {}
    census_rows: list[dict[str, Any]] = []
    replay_records: list[dict[str, Any]] = []
    input_receipts: list[dict[str, Any]] = []
    missing_feature_keys = 0
    duplicate_replay_keys = 0

    for roster_row in sorted(roster, key=lambda row: (row["market_id"], row["target_date"])):
        market_id = roster_row["market_id"]
        target_date = roster_row["target_date"]
        replay_file = replay_path(snapshots_root, market_id, target_date)
        features_file = replay_file.with_name("features_long.csv")
        require(features_file.is_file(), f"feature file missing: {features_file}")
        require(replay_file.is_file(), f"replay file missing: {replay_file}")

        admitted: Counter[tuple[str, str]] = Counter()
        feature_digest = hashlib.sha256()
        with features_file.open("rb") as raw_handle:
            header_raw = raw_handle.readline()
            feature_digest.update(header_raw)
            header = next(csv.reader([header_raw.decode("utf-8-sig").rstrip("\r\n")]))
            indexes = {name: header.index(name) for name in ("snapshot_id", "captured_at_utc", "target_date", "high_so_far", "current_temp")}
            for raw_line in raw_handle:
                feature_digest.update(raw_line)
                values = next(csv.reader([raw_line.decode("utf-8").rstrip("\r\n")]))
                require(values[indexes["target_date"]] == target_date, f"target date drift in {features_file}")
                high = population.maybe_float(values[indexes["high_so_far"]])
                current = population.maybe_float(values[indexes["current_temp"]])
                if high is None or current is None:
                    continue
                short_key = (values[indexes["snapshot_id"]], values[indexes["captured_at_utc"]])
                admitted[short_key] += 1
                full_key = (market_id, target_date, *short_key)
                if full_key in selected_by_key:
                    require(full_key not in feature_rows, f"duplicate selected feature row: {full_key}")
                    feature_rows[full_key] = dict(zip(header, values))
        input_receipts.append(
            {
                "kind": "features_long",
                "path": features_file.relative_to(repo_root).as_posix(),
                "bytes": features_file.stat().st_size,
                "sha256": feature_digest.hexdigest(),
            }
        )

        matched: set[tuple[str, str]] = set()
        seen_replay: set[tuple[str, str]] = set()
        replay_digest = hashlib.sha256()
        with replay_file.open("rb") as handle:
            for raw in handle:
                replay_digest.update(raw)
                snapshot_id = population.json_value_by_key(raw, "snapshot_id")
                captured_at_utc = population.json_value_by_key(raw, "captured_at_utc")
                if not isinstance(snapshot_id, str) or not isinstance(captured_at_utc, str):
                    continue
                short_key = (snapshot_id, captured_at_utc)
                if short_key in seen_replay:
                    duplicate_replay_keys += 1
                    continue
                seen_replay.add(short_key)
                if short_key not in admitted:
                    continue
                matched.add(short_key)
                full_key = (market_id, target_date, snapshot_id, captured_at_utc)
                metadata = binding_metadata(raw)
                for feature_duplicate_index in range(admitted[short_key]):
                    census_rows.append(
                        {
                            "market_id": market_id,
                            "target_date": target_date,
                            "snapshot_id": snapshot_id,
                            "captured_at_utc": captured_at_utc,
                            "feature_duplicate_index": feature_duplicate_index,
                            **metadata,
                        }
                    )
                selected_row = selected_by_key.get(full_key)
                if selected_row is not None:
                    record = json.loads(raw)
                    replay_records.append(
                        {
                            "selection": selected_row,
                            "binding": metadata,
                            "recorded_features": feature_rows[full_key],
                            "record": record,
                        }
                    )
        missing_feature_keys += len(set(admitted) - matched)
        input_receipts.append(
            {
                "kind": "replay_inputs",
                "path": replay_file.relative_to(repo_root).as_posix(),
                "bytes": replay_file.stat().st_size,
                "sha256": replay_digest.hexdigest(),
            }
        )

    expected = int(seed["population"]["feature_snapshots_with_replay"])
    require(len(census_rows) == expected, f"B replay-supported census drifted: {len(census_rows)}")
    require(len(replay_records) == len(selected), f"selected replay join drifted: {len(replay_records)}")
    require(len(feature_rows) == len(selected), f"selected feature join drifted: {len(feature_rows)}")

    run_root.mkdir(parents=True, exist_ok=True)
    census_path = run_root / "census-records.jsonl"
    records_path = run_root / "replay-records.jsonl"
    with census_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in census_rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    with records_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in replay_records:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")

    decision_metadata = [
        {**item["selection"], **item["binding"]}
        for item in replay_records
        if item["selection"]["analysis_population"] == "decision_stratum"
    ]
    diagnostic_metadata = [
        {**item["selection"], **item["binding"]}
        for item in replay_records
        if item["selection"]["analysis_population"] == "source_switch_diagnostic"
    ]
    inventory = {
        "schema_version": "replay_trust_inventory_v1",
        "mission": seed["mission"],
        "B_overall": summarize_binding(census_rows),
        "decision_stratum": summarize_binding(decision_metadata),
        "source_switch_diagnostic": summarize_binding(diagnostic_metadata),
        "support": {
            "B_market_days": len(roster),
            "B_feature_snapshots_with_replay": len(census_rows),
            "decision_rows": len(decision_metadata),
            "source_switch_rows": len(diagnostic_metadata),
            "feature_capture_keys_missing_replay": missing_feature_keys,
            "duplicate_replay_capture_key_rows": duplicate_replay_keys,
            "input_files": len(input_receipts),
            "input_bytes": sum(item["bytes"] for item in input_receipts),
            "input_receipts_sha256": canonical_sha256(input_receipts),
        },
        "records": {
            "census_path": str(census_path.resolve()),
            "census_sha256": sha256_file(census_path),
            "replay_path": str(records_path.resolve()),
            "replay_sha256": sha256_file(records_path),
        },
        "outcome_receipts": seed["campaign"],
    }
    inventory_path = run_root / "inventory.json"
    inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return inventory


def row_key(item: dict[str, Any]) -> tuple[str, ...]:
    source = item.get("selection") or item
    return tuple(str(source.get(field) or "") for field in ROW_KEY_FIELDS)


def distribution_error(left: dict[Any, Any], right: dict[Any, Any]) -> tuple[float, float]:
    return parent.distribution_l1(left, right)


def distribution_differences(
    recorded: dict[Any, Any], replayed: dict[Any, Any], tolerance: float
) -> list[dict[str, Any]]:
    left = {int(key): float(value) for key, value in recorded.items()}
    right = {int(key): float(value) for key, value in replayed.items()}
    differences = []
    for band in sorted(set(left) | set(right)):
        recorded_probability = left.get(band, 0.0)
        replayed_probability = right.get(band, 0.0)
        delta = replayed_probability - recorded_probability
        if abs(delta) <= tolerance:
            continue
        differences.append(
            {
                "band": band,
                "recorded_probability": recorded_probability,
                "replayed_probability": replayed_probability,
                "delta": delta,
            }
        )
    return differences


def numeric(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def feature_equal(recorded: Any, replayed: Any, tolerance: float) -> bool:
    if replayed is None:
        return recorded in (None, "")
    if isinstance(replayed, bool):
        return str(recorded).lower() == str(replayed).lower()
    if isinstance(replayed, (int, float)):
        left = numeric(recorded)
        return left is not None and abs(left - float(replayed)) <= tolerance
    return str(recorded) == str(replayed)


def compare_features(
    recorded: dict[str, Any], replayed: dict[str, Any], tolerance: float
) -> list[dict[str, Any]]:
    differences = []
    for field in recorded:
        if field not in replayed:
            continue
        if feature_equal(recorded[field], replayed[field], tolerance):
            continue
        differences.append(
            {"field": field, "recorded": recorded[field], "replayed": replayed[field]}
        )
    return differences


def feature_source_binding(
    model: Any,
    sources: dict[str, Any],
    cutoff_hour: int,
    high_so_far: Any,
    current_temp: Any,
) -> dict[str, Any]:
    history = model.source_data(sources, "wu_history")
    current = model.source_data(sources, "wu_current")
    rows = history.get("rows") or []
    feature_rows = model.source_rows_until_cutoff(rows, cutoff_hour)
    row_temps = [model.row_temp_native(row) for row in feature_rows]
    finite = [value for value in row_temps if value is not None]
    latest = feature_rows[-1] if feature_rows else None
    latest_temp = model.row_temp_native(latest) if latest else None
    current_wu_temp = model.row_temp_native(current)
    current_wu_max = model.row_max_since_7am_native(current)
    high = numeric(high_so_far)
    observed_current = numeric(current_temp)
    current_source = "unresolved"
    if latest_temp is not None and observed_current is not None and abs(latest_temp - observed_current) <= 1e-12:
        current_source = "wu_history"
    elif current_wu_temp is not None and observed_current is not None and abs(current_wu_temp - observed_current) <= 1e-12:
        current_source = "wu_current"
    elif rows and observed_current is not None and model.row_temp_native(rows[-1]) == observed_current:
        current_source = "wu_history_last_fallback"
    high_source = "unresolved"
    history_max = max(finite) if finite else None
    if history_max is not None and high is not None and abs(history_max - high) <= 1e-12:
        high_source = "wu_history"
    elif observed_current is not None and high is not None and abs(observed_current - high) <= 1e-12:
        high_source = current_source
    elif current_wu_max is not None and high is not None and abs(current_wu_max - high) <= 1e-12:
        high_source = "wu_current.max_since_7am"
    return {
        "high_so_far_source": high_source,
        "current_temp_source": current_source,
        "feature_rows": len(feature_rows),
        "feature_history_max": history_max,
        "feature_latest_temp": latest_temp,
        "wu_current_temp": current_wu_temp,
        "wu_current_max_since_7am": current_wu_max,
    }


def inspect_identity_files(
    model_identity: dict[str, Any], runtime_root: Path, *, require_match: bool
) -> dict[str, Any]:
    checked = []
    mismatches = []
    for group in ("code_files", "artifact_files"):
        for item in model_identity.get(group) or []:
            if not item.get("exists"):
                continue
            path = runtime_root / str(item["path"])
            require(path.is_file(), f"captured identity file missing: {path}")
            actual = sha256_file(path)
            if actual != item["sha256"]:
                mismatches.append(
                    {"path": item["path"], "captured_sha256": item["sha256"], "actual_sha256": actual}
                )
            checked.append({"path": item["path"], "sha256": actual, "bytes": path.stat().st_size})
    require(
        not (require_match and mismatches),
        f"captured identity mismatch in diagnostic runtime: {mismatches[:3]}",
    )
    return {
        "files": len(checked),
        "files_sha256": canonical_sha256(checked),
        "captured_identity_matches_runtime_tree": not mismatches,
        "mismatch_count": len(mismatches),
        "mismatch_examples": mismatches[:20],
    }


def resolved_module_files(runtime_root: Path) -> dict[str, str]:
    modules: dict[str, str] = {}
    for name, module in sorted(sys.modules.items()):
        if not (name.startswith(MODEL_PREFIXES) or name in {"weather.artifacts", "weather.paths", "weather.market.market_registry"}):
            continue
        module_file = getattr(module, "__file__", None)
        if module_file:
            modules[name] = str(Path(module_file).resolve())
    intended = str((runtime_root / "src").resolve()).lower()
    escaped = {name: path for name, path in modules.items() if not path.lower().startswith(intended)}
    require(not escaped, f"module escaped intended historical tree: {escaped}")
    return modules


def replay(
    seed: dict[str, Any],
    records_path: Path,
    runtime_root: Path,
    runtime_commit: str,
    scientific_site: Path,
    output: Path,
    identity_hash: str = "",
) -> dict[str, Any]:
    resolved_commit = subprocess.check_output(
        [
            "git",
            "-c",
            f"safe.directory={runtime_root}",
            "-C",
            str(runtime_root),
            "rev-parse",
            "HEAD",
        ],
        text=True,
    ).strip()
    require(
        resolved_commit.startswith(runtime_commit) or runtime_commit.startswith(resolved_commit),
        f"runtime worktree mismatch: {resolved_commit} != {runtime_commit}",
    )
    preloaded = [name for name in sys.modules if name == "weather" or name.startswith("weather.")]
    require(not preloaded, f"weather modules loaded before historical path binding: {preloaded}")
    sys.path.insert(0, str(scientific_site))
    sys.path.insert(0, str(runtime_root / "src"))
    toronto = importlib.import_module("weather.model.toronto_model")

    selected = []
    with records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            binding = item["binding"]
            commit = str(binding.get("runtime_commit") or "")
            exact_runtime = bool(commit) and (
                commit.startswith(runtime_commit) or runtime_commit.startswith(commit)
            )
            diagnostic_identity = bool(identity_hash) and binding.get("model_identity_hash") == identity_hash
            if exact_runtime or diagnostic_identity:
                selected.append((item, "captured_runtime_commit" if exact_runtime else "model_identity_diagnostic"))
    require(selected, f"no rows selected for runtime {runtime_commit}")

    tolerance = float(seed["replay"]["l1_tolerance"])
    feature_tolerance = float(seed["replay"]["feature_tolerance"])
    identity_receipts: dict[str, dict[str, Any]] = {}
    results = []
    for item, replay_basis in selected:
        selection = item["selection"]
        record = item["record"]
        model_identity = record.get("model_identity") or {}
        identity_key = str(model_identity.get("identity_hash") or "missing")
        if identity_key not in identity_receipts:
            identity_receipts[identity_key] = inspect_identity_files(
                model_identity,
                runtime_root,
                require_match=replay_basis == "model_identity_diagnostic",
            )

        model = toronto.TorontoHighTempModel(
            target_date=date.fromisoformat(selection["target_date"]),
            market_id=selection["market_id"],
        )
        now = datetime.fromisoformat(record["built_at"])
        replayed = model.estimate_distribution(record["sources"], now=now)
        l1, max_abs = distribution_error(record.get("recorded_distribution") or {}, replayed)
        band_differences = distribution_differences(
            record.get("recorded_distribution") or {}, replayed, tolerance
        )
        history_rows = model.source_data(record["sources"], "wu_history").get("rows") or []
        cutoff = model.effective_intraday_cutoff_hour(now, history_rows)
        replayed_features = model.live_feature_record(
            record["sources"],
            cutoff,
            captured_at=now,
            model_version=record.get("model_version"),
        )
        differences = compare_features(item["recorded_features"], replayed_features, feature_tolerance)
        recorded_source = feature_source_binding(
            model,
            record["sources"],
            int(float(item["recorded_features"]["cutoff_hour"])),
            item["recorded_features"].get("high_so_far"),
            item["recorded_features"].get("current_temp"),
        )
        replayed_source = feature_source_binding(
            model,
            record["sources"],
            int(replayed_features["cutoff_hour"]),
            replayed_features.get("high_so_far"),
            replayed_features.get("current_temp"),
        )
        results.append(
            {
                **selection,
                **item["binding"],
                "replay_basis": replay_basis,
                "l1": l1,
                "max_abs": max_abs,
                "matches": l1 <= tolerance,
                "recorded_active_model_kind": model_identity.get("active_model_kind"),
                "replayed_active_model_kind": getattr(model, "active_model_kind", None),
                "feature_difference_count": len(differences),
                "first_feature_difference": differences[0] if differences else None,
                "feature_differences_sha256": canonical_sha256(differences),
                "feature_difference_examples": differences[:20] if l1 > tolerance else [],
                "first_distribution_difference": band_differences[0] if band_differences else None,
                "distribution_difference_examples": band_differences[:20],
                "recorded_feature_source": recorded_source,
                "replayed_feature_source": replayed_source,
            }
        )

    modules = resolved_module_files(runtime_root)
    receipt = {
        "schema_version": "replay_trust_runtime_receipt_v1",
        "runtime_commit": runtime_commit,
        "resolved_runtime_commit": resolved_commit,
        "runtime_root": str(runtime_root.resolve()),
        "module_files": modules,
        "identity_receipts": identity_receipts,
        "tolerance": tolerance,
        "rows": len(results),
        "runtime_bound_rows": sum(row["replay_basis"] == "captured_runtime_commit" for row in results),
        "diagnostic_identity_rows": sum(row["replay_basis"] == "model_identity_diagnostic" for row in results),
        "matched_rows": sum(row["matches"] for row in results),
        "failed_rows": sum(not row["matches"] for row in results),
        "max_l1": max((row["l1"] for row in results), default=None),
        "max_abs": max((row["max_abs"] for row in results), default=None),
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def bool_text(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return ""


def grouped_replay(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(field) or "unbound")].append(row)
    result = {}
    for key, items in sorted(grouped.items()):
        replayed = [row for row in items if row.get("replay_attempted")]
        matched = sum(row.get("matches") is True for row in replayed)
        bound = sum(row["binding_class"] == "runtime_commit_bound" for row in items)
        result[key] = {
            "rows": len(items),
            "runtime_bound_rows": bound,
            "runtime_bound_share": bound / len(items) if items else None,
            "replayed_rows": len(replayed),
            "matched_rows": matched,
            "failed_rows": len(replayed) - matched,
            "match_rate_on_replayed": matched / len(replayed) if replayed else None,
            "exact_match_share_of_population": matched / len(items) if items else None,
            "max_l1": max((row["l1"] for row in replayed), default=None),
        }
    return result


def aggregate(
    seed: dict[str, Any],
    inventory_path: Path,
    records_path: Path,
    receipts: list[Path],
    csv_path: Path,
    manifest_path: Path,
    checksums_path: Path,
) -> dict[str, Any]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    base_rows = []
    with records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            base_rows.append(
                {
                    **item["selection"],
                    **item["binding"],
                    "replay_basis": "",
                    "replay_attempted": False,
                    "matches": None,
                    "l1": None,
                    "max_abs": None,
                    "recorded_active_model_kind": (item["record"].get("model_identity") or {}).get("active_model_kind"),
                    "replayed_active_model_kind": None,
                    "feature_difference_count": None,
                    "first_feature_difference": None,
                    "first_distribution_difference": None,
                    "recorded_feature_source": None,
                    "replayed_feature_source": None,
                }
            )
    indexed = {row_key(row): row for row in base_rows}
    receipt_payloads = []
    for path in receipts:
        payload = json.loads(path.read_text(encoding="utf-8"))
        receipt_payloads.append((path, payload))
        for result in payload["results"]:
            key = row_key(result)
            require(key in indexed, f"receipt row outside selected population: {key}")
            target = indexed[key]
            require(not target["replay_attempted"], f"row replayed more than once: {key}")
            for field in (
                "replay_basis",
                "l1",
                "max_abs",
                "matches",
                "recorded_active_model_kind",
                "replayed_active_model_kind",
                "feature_difference_count",
                "first_feature_difference",
                "recorded_feature_source",
                "replayed_feature_source",
                "feature_differences_sha256",
                "feature_difference_examples",
                "first_distribution_difference",
                "distribution_difference_examples",
            ):
                target[field] = result.get(field)
            target["replay_attempted"] = True

    decision = [row for row in indexed.values() if row["analysis_population"] == "decision_stratum"]
    diagnostics = [row for row in indexed.values() if row["analysis_population"] == "source_switch_diagnostic"]
    bound_decision = [row for row in decision if row["binding_class"] == "runtime_commit_bound"]
    require(
        all(row["replay_attempted"] for row in bound_decision),
        "not every runtime-bound decision row was replayed",
    )
    decision_failures = [row for row in bound_decision if row["matches"] is False]
    identity_audits = {
        (payload["runtime_commit"], identity_hash): audit
        for _, payload in receipt_payloads
        for identity_hash, audit in payload["identity_receipts"].items()
    }
    decision_identity_audits = [
        identity_audits.get((row["runtime_commit"], row["model_identity_hash"]))
        for row in bound_decision
    ]
    require(all(decision_identity_audits), "missing model-identity audit for a bound decision row")
    identity_keys = {
        (row["runtime_commit"], row["model_identity_hash"]) for row in bound_decision
    }
    if decision_failures:
        verdict = "REPLAY_DIVERGES_ON_THE_DECISION_STRATUM"
    elif not bound_decision:
        verdict = "REPLAY_COVERAGE_TOO_THIN"
    else:
        verdict = "REPLAY_SOUND_ON_THE_DECISION_STRATUM"

    exact_m4 = [row for row in diagnostics if row["binding_class"] == "runtime_commit_bound"]
    all_four_replayed = len(diagnostics) == 4 and all(row["replay_attempted"] for row in diagnostics)
    all_four_failed = all_four_replayed and all(row["matches"] is False for row in diagnostics)
    if not all_four_replayed:
        source_switch_hypothesis = "ABANDONED_NOT_ALL_FOUR_REPLAYABLE"
    elif all_four_failed:
        source_switch_hypothesis = "SUPPORTED"
    else:
        source_switch_hypothesis = "ABANDONED_NOT_ALL_FOUR_FAILED"

    confound = {}
    for m4 in exact_m4:
        commit = m4["runtime_commit"]
        same_runtime = [row for row in decision if row["runtime_commit"] == commit]
        confound[commit] = {
            "M4_source_switch": grouped_replay([m4], "analysis_population")["source_switch_diagnostic"],
            "non_M4_toronto": grouped_replay(
                [row for row in same_runtime if row["market_id"] == "toronto"],
                "market_id",
            ).get("toronto", {"rows": 0}),
            "non_toronto": grouped_replay(
                [row for row in same_runtime if row["market_id"] != "toronto"],
                "runtime_commit",
            ).get(commit, {"rows": 0}),
        }

    failing_trace = next(
        (row for row in diagnostics if row.get("matches") is False),
        next((row for row in decision if row.get("matches") is False), None),
    )
    ordered = sorted(indexed.values(), key=row_key)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in ordered:
            rendered = dict(row)
            rendered["replay_attempted"] = bool_text(row["replay_attempted"])
            rendered["matches"] = bool_text(row["matches"])
            for field in ("first_feature_difference", "recorded_feature_source", "replayed_feature_source"):
                rendered[field] = json.dumps(row.get(field), sort_keys=True, separators=(",", ":")) if row.get(field) is not None else ""
            writer.writerow({field: rendered.get(field, "") for field in CSV_FIELDS})

    manifest = {
        "schema_version": "replay_trust_manifest_v1",
        "mission": seed["mission"],
        "verdict": verdict,
        "source_switch_hypothesis": source_switch_hypothesis,
        "binding_census": {
            "B_overall": inventory["B_overall"],
            "decision_stratum": inventory["decision_stratum"],
        },
        "decision_replay": {
            "tolerance": seed["replay"]["l1_tolerance"],
            "rows": len(decision),
            "runtime_bound_rows": len(bound_decision),
            "runtime_bound_share": len(bound_decision) / len(decision),
            "matched_rows": sum(row["matches"] is True for row in bound_decision),
            "failed_rows": len(decision_failures),
            "match_rate_on_bound_rows": (
                sum(row["matches"] is True for row in bound_decision) / len(bound_decision)
                if bound_decision
                else None
            ),
            "max_l1": max((row["l1"] for row in bound_decision), default=None),
            "runtime_binding_fidelity": {
                "captured_runtime_commit_rows": len(bound_decision),
                "captured_model_identity_matches_commit_tree_rows": sum(
                    audit["captured_identity_matches_runtime_tree"]
                    for audit in decision_identity_audits
                ),
                "captured_model_identity_differs_from_commit_tree_rows": sum(
                    not audit["captured_identity_matches_runtime_tree"]
                    for audit in decision_identity_audits
                ),
                "runtime_commit_model_identity_pairs": len(identity_keys),
                "matching_runtime_commit_model_identity_pairs": sum(
                    identity_audits[key]["captured_identity_matches_runtime_tree"]
                    for key in identity_keys
                ),
            },
            "by_runtime_commit": grouped_replay(decision, "runtime_commit"),
            "by_model_version": grouped_replay(decision, "model_version"),
            "by_market": grouped_replay(decision, "market_id"),
            "by_window": grouped_replay(decision, "window"),
        },
        "source_switch_diagnostics": {
            "rows": len(diagnostics),
            "runtime_bound_rows": len(exact_m4),
            "all_four_replayed": all_four_replayed,
            "all_four_failed": all_four_failed,
            "rows_detail": diagnostics,
            "confound_break": confound,
        },
        "failing_trace": failing_trace,
        "support": inventory["support"],
        "receipt_files": [
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "runtime_commit": payload["runtime_commit"],
                "rows": payload["rows"],
                "matched_rows": payload["matched_rows"],
                "failed_rows": payload["failed_rows"],
                "module_files": payload["module_files"],
                "identity_receipts": payload["identity_receipts"],
            }
            for path, payload in receipt_payloads
        ],
        "artifact": {
            "csv_relative_path": csv_path.relative_to(DEFAULT_REPO_ROOT).as_posix(),
            "csv_rows": len(ordered),
            "csv_sha256": sha256_file(csv_path),
        },
        "campaign": seed["campaign"],
        "explicitly_not_done": [
            "no alpha allocation, candidate probability, displacement, ceiling, realized outcome, settlement score, market comparison, or C endpoint",
            "no provider or exchange call and no write under production data",
            "no model, feature, calibration, floor, collection, producer, replay, scoring, serving, release, schedule, or trading change",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksums_path.write_text(
        f"{sha256_file(csv_path)}  {csv_path.name}\n"
        f"{sha256_file(manifest_path)}  {manifest_path.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    extract_parser = sub.add_parser("extract")
    extract_parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    extract_parser.add_argument("--snapshots-root", type=Path, required=True)
    extract_parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    replay_parser = sub.add_parser("replay")
    replay_parser.add_argument("--records", type=Path, required=True)
    replay_parser.add_argument("--runtime-root", type=Path, required=True)
    replay_parser.add_argument("--runtime-commit", required=True)
    replay_parser.add_argument("--identity-hash", default="")
    replay_parser.add_argument("--scientific-site", type=Path, required=True)
    replay_parser.add_argument("--output", type=Path, required=True)
    aggregate_parser = sub.add_parser("aggregate")
    aggregate_parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    aggregate_parser.add_argument("--inventory", type=Path, required=True)
    aggregate_parser.add_argument("--records", type=Path, required=True)
    aggregate_parser.add_argument("--receipts", type=Path, nargs="+", required=True)
    aggregate_parser.add_argument("--csv-output", type=Path)
    aggregate_parser.add_argument("--manifest-output", type=Path)
    aggregate_parser.add_argument("--checksums-output", type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    repo_root = getattr(args, "repo_root", DEFAULT_REPO_ROOT).resolve()
    seed = load_seed(DEFAULT_SEED, repo_root, verify_inputs=args.command != "replay")
    if args.command == "extract":
        inventory = extract(seed, repo_root, args.snapshots_root.resolve(), args.run_root.resolve())
        print(json.dumps(inventory, indent=2, sort_keys=True))
        return 0
    if args.command == "replay":
        receipt = replay(
            seed,
            args.records.resolve(),
            args.runtime_root.resolve(),
            args.runtime_commit,
            args.scientific_site.resolve(),
            args.output.resolve(),
            args.identity_hash,
        )
        print(
            json.dumps(
                {
                    key: receipt[key]
                    for key in (
                        "runtime_commit",
                        "rows",
                        "runtime_bound_rows",
                        "diagnostic_identity_rows",
                        "matched_rows",
                        "failed_rows",
                        "max_l1",
                        "module_files",
                    )
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    artifacts = seed["artifacts"]
    csv_path = (args.csv_output or repo_root / artifacts["csv_relative_path"]).resolve()
    manifest_path = (args.manifest_output or repo_root / artifacts["manifest_relative_path"]).resolve()
    checksums_path = (args.checksums_output or repo_root / artifacts["checksums_relative_path"]).resolve()
    manifest = aggregate(
        seed,
        args.inventory.resolve(),
        args.records.resolve(),
        [path.resolve() for path in args.receipts],
        csv_path,
        manifest_path,
        checksums_path,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

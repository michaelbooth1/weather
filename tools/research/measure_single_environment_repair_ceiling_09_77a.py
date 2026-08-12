"""Measure the -09-77a repair ceiling inside one current environment.

The harness reads only captured source payloads from the frozen B decision
stratum.  It runs the incumbent and the payload-observable WU tail-recovery
candidate through the same imported pipeline, computes the outcome-free bound
specified by the handoff, and uses the repository crossed date x market
bootstrap convention.  It never reads a realized band, settlement value,
market probability, or C endpoint.

After model import and execution it records every loaded repository
``weather.*`` module from ``sys.modules`` and every repository artifact/config
file actually opened by the runtime.  Those exact bytes are emitted as a
deterministic, content-addressed ZIP bundle without changing model_identity.py.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_SEED = SCRIPT_PATH.with_name(
    "measure_single_environment_repair_ceiling_09_77a_seed.json"
)
DEFAULT_RUN_ROOT = (
    DEFAULT_REPO_ROOT / "scratch" / "runs" / "repair-ceiling-single-environment-09-77a"
)
DEFAULT_ARTIFACT_ROOT = DEFAULT_REPO_ROOT / "docs" / "roadmap"
sys.path.insert(0, str(SCRIPT_PATH.parent))
import measure_high_so_far_population_09_70a as stream  # noqa: E402


SELECTION_FIELDS = (
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
    "observable_recovered_rows",
)
CSV_FIELDS = (
    *SELECTION_FIELDS,
    "incumbent_status",
    "candidate_status",
    "incumbent_active_model_kind",
    "candidate_active_model_kind",
    "band_keys",
    "incumbent_probs_q",
    "candidate_probs_p",
    "incumbent_mass",
    "candidate_mass",
    "l1_displacement",
    "max_abs_displacement",
    "argmax_changed",
    "ceiling_delta_brier",
    "strict_prior_receipt",
    "replay_line_sha256",
)
RELEVANT_MODULE_PREFIXES = (
    "weather.model",
    "weather.calibration",
    "weather.market",
    "weather.features",
)
MASS_TOLERANCE = 1e-10
STATE_TOLERANCE = 1e-12


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def relative_or_absolute(path: Path, root: Path) -> str:
    path = path.resolve()
    try:
        return path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def is_within(path: Path, root: Path) -> bool:
    path = path.resolve()
    root = root.resolve()
    return path == root or root in path.parents


def git(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo_root), *args], text=True
    ).strip()


def load_seed(path: Path, repo_root: Path) -> dict[str, Any]:
    seed = json.loads(path.read_text(encoding="utf-8"))
    require(
        seed.get("schema_version") == "single_environment_repair_ceiling_seed_v1",
        "single-environment seed schema drifted",
    )
    for key, value in seed["inputs"].items():
        if not key.endswith("_relative_path"):
            continue
        prefix = key[: -len("_relative_path")]
        path_to_check = repo_root / value
        require(path_to_check.is_file(), f"frozen input missing: {path_to_check}")
        actual = sha256_file(path_to_check)
        require(
            actual == seed["inputs"][f"{prefix}_sha256"],
            f"{prefix} hash drifted: {actual}",
        )
    prereg = json.loads(
        (repo_root / seed["inputs"]["candidate_preregistration_relative_path"]).read_text(
            encoding="utf-8"
        )
    )
    require(
        prereg["candidate_definition"]["name"] == seed["candidate"]["name"],
        "candidate name drifted",
    )
    require(prereg["outcome_scoring_authorized"] is False, "prior alpha boundary drifted")
    return seed


def projected_rows(path: Path, fields: Iterable[str]) -> Iterable[dict[str, str]]:
    """Project named columns only; outcome-bearing columns are never materialized."""

    fields = tuple(fields)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        indexes = {name: header.index(name) for name in fields}
        for raw in reader:
            yield {name: raw[indexes[name]] for name in fields}


def selected_rows(seed: dict[str, Any], repo_root: Path) -> list[dict[str, str]]:
    path = repo_root / seed["inputs"]["candidate_csv_relative_path"]
    windows = set(seed["population"]["decision_windows"])
    rows = [
        row
        for row in projected_rows(path, SELECTION_FIELDS)
        if row["stratum"] == seed["population"]["stratum"]
        and row["window"] in windows
    ]
    require(len(rows) == seed["population"]["decision_rows"], "decision population drifted")
    require(
        sum(int(row["observable_recovered_rows"]) > 0 for row in rows)
        == seed["population"]["repaired_rows"],
        "decision repaired count drifted",
    )
    require(
        len({row["target_date"] for row in rows}) == seed["population"]["date_clusters"],
        "date-cluster count drifted",
    )
    require(
        len({row["market_id"] for row in rows}) == seed["population"]["market_clusters"],
        "market-cluster count drifted",
    )
    require(
        len({(row["target_date"], row["market_id"]) for row in rows})
        == seed["population"]["market_days"],
        "market-day count drifted",
    )
    boundary = seed["population"]["regime_boundary"]
    require(all(row["target_date"] < boundary for row in rows), "regime boundary crossed")
    return rows


def replay_path(root: Path, market_id: str, target_date: str) -> Path:
    target = date.fromisoformat(target_date)
    folder = (
        f"highest-temperature-in-{market_id}-on-"
        f"{target.strftime('%B').lower()}-{target.day}-{target.year}"
    )
    return root / folder / "replay_inputs.jsonl"


def history_data(sources: dict[str, Any]) -> dict[str, Any]:
    wrapper = sources.get("wu_history") or {}
    require(isinstance(wrapper, dict), "WU history wrapper is not a mapping")
    data = wrapper.get("data")
    return data if isinstance(data, dict) else wrapper


def history_rows(sources: dict[str, Any]) -> list[dict[str, Any]]:
    rows = history_data(sources).get("rows") or []
    require(isinstance(rows, list), "WU history rows are not a list")
    require(all(isinstance(row, dict) for row in rows), "WU history contains a non-row")
    return rows


def set_history_rows(sources: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    history_data(sources)["rows"] = rows


def row_minute(row: dict[str, Any], target_date: str) -> int | None:
    timestamp = str(
        row.get("datetime") or row.get("valid_time_local") or row.get("local_time") or ""
    )
    if len(timestamp) >= 10 and timestamp[4:5] == "-" and timestamp[7:8] == "-":
        if timestamp[:10] != target_date:
            return None
    minute = stream.minute_of_day(row.get("time") or row.get("datetime"))
    temperature = stream.row_temperature(row)
    return minute if minute is not None and temperature is not None else None


def ordered_candidate_rows(
    current_rows: list[dict[str, Any]],
    recovered: dict[int, dict[str, Any]],
    target_date: str,
) -> list[dict[str, Any]]:
    entries: list[tuple[tuple[str, int], int, dict[str, Any]]] = []
    for index, row in enumerate(current_rows):
        timestamp = str(
            row.get("datetime") or row.get("valid_time_local") or row.get("local_time") or ""
        )
        minute = stream.minute_of_day(row.get("time") or row.get("datetime"))
        day_key = timestamp[:10] if len(timestamp) >= 10 else target_date
        minute_key = minute if minute is not None else 10**9
        entries.append(((day_key, minute_key), index, copy.deepcopy(row)))
    base_index = len(current_rows)
    for offset, (minute, row) in enumerate(sorted(recovered.items())):
        entries.append(((target_date, minute), base_index + offset, copy.deepcopy(row)))
    entries.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in entries]


def parse_capture(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def extract_paired_inputs(
    seed: dict[str, Any],
    repo_root: Path,
    snapshots_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    selected = selected_rows(seed, repo_root)
    selected_by_day: dict[tuple[str, str], dict[tuple[str, str], dict[str, str]]] = defaultdict(dict)
    for row in selected:
        day = (row["market_id"], row["target_date"])
        key = (row["snapshot_id"], row["captured_at_utc"])
        require(key not in selected_by_day[day], f"duplicate selected key: {day} {key}")
        selected_by_day[day][key] = row

    paired: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    support = Counter()
    strict_prior_failures = 0
    for day_index, day in enumerate(sorted(selected_by_day), start=1):
        market_id, target_date = day
        path = replay_path(snapshots_root, market_id, target_date)
        require(path.is_file(), f"captured input missing: {path}")
        digest = hashlib.sha256()
        captured_records: list[tuple[datetime, int, str, str, bytes]] = []
        with path.open("rb") as handle:
            for file_index, raw in enumerate(handle):
                digest.update(raw)
                support["replay_rows_scanned"] += 1
                support["replay_bytes_scanned"] += len(raw)
                snapshot_id = stream.json_value_by_key(raw, "snapshot_id")
                captured_at_utc = stream.json_value_by_key(raw, "captured_at_utc")
                if not isinstance(snapshot_id, str) or not isinstance(captured_at_utc, str):
                    continue
                captured_records.append(
                    (parse_capture(captured_at_utc), file_index, snapshot_id, captured_at_utc, raw)
                )
        captured_records.sort(key=lambda item: (item[0], item[1]))

        last_rows: dict[int, dict[str, Any]] = {}
        last_sources: dict[int, str] = {}
        seen_keys: set[tuple[str, str]] = set()
        matched: set[tuple[str, str]] = set()
        for captured_at, _file_index, snapshot_id, captured_at_utc, raw in captured_records:
            key = (snapshot_id, captured_at_utc)
            if key in seen_keys:
                support["duplicate_replay_capture_key_rows"] += 1
                continue
            seen_keys.add(key)
            sources_start = raw.find(b'"sources"')
            require(sources_start >= 0, f"sources missing: {day} {key}")
            sources = stream.json_value_by_key(raw, "sources", sources_start)
            require(isinstance(sources, dict), f"sources are not a mapping: {day} {key}")
            current_rows = history_rows(sources)
            current_last: dict[int, dict[str, Any]] = {}
            for source_row in current_rows:
                minute = row_minute(source_row, target_date)
                if minute is not None:
                    current_last[minute] = source_row
            for minute, source_row in current_last.items():
                last_rows[minute] = copy.deepcopy(source_row)
                last_sources[minute] = captured_at_utc

            selected_row = selected_by_day[day].get(key)
            if selected_row is None:
                continue
            matched.add(key)
            current_latest = max(current_last) if current_last else None
            recovered = {
                minute: source_row
                for minute, source_row in last_rows.items()
                if minute not in current_last
                and (current_latest is None or current_latest < minute)
            }
            recovered_sources = [last_sources[minute] for minute in recovered]
            for source_time in recovered_sources:
                if parse_capture(source_time) >= captured_at:
                    strict_prior_failures += 1
            expected_recovered = int(selected_row["observable_recovered_rows"])
            require(
                len(recovered) == expected_recovered,
                f"candidate recovery drifted at {day} {key}: {len(recovered)} != {expected_recovered}",
            )
            candidate_sources = copy.deepcopy(sources)
            set_history_rows(
                candidate_sources,
                ordered_candidate_rows(current_rows, recovered, target_date),
            )
            built_at = stream.json_value_by_key(raw, "built_at")
            require(isinstance(built_at, str) and built_at, f"built_at missing: {day} {key}")
            paired.append(
                {
                    "selection": selected_row,
                    "built_at": built_at,
                    "incumbent_sources": sources,
                    "candidate_sources": candidate_sources,
                    "strict_prior_receipt": {
                        "current_captured_at_utc": captured_at_utc,
                        "recovered_source_captured_at_utc": sorted(recovered_sources),
                        "all_recovered_sources_strict_prior": all(
                            parse_capture(value) < captured_at for value in recovered_sources
                        ),
                    },
                    "replay_line_sha256": sha256_bytes(raw),
                }
            )
        missing = set(selected_by_day[day]) - matched
        require(not missing, f"selected raw inputs missing for {day}: {sorted(missing)[:3]}")
        receipts.append(
            {
                "kind": "captured_replay_inputs",
                "path": relative_or_absolute(path, repo_root),
                "bytes": path.stat().st_size,
                "sha256": digest.hexdigest(),
                "selected_rows": len(matched),
            }
        )
        if day_index % 10 == 0 or day_index == len(selected_by_day):
            print(
                f"scanned {day_index}/{len(selected_by_day)} market-days; selected={len(paired)}",
                file=sys.stderr,
                flush=True,
            )

    require(len(paired) == seed["population"]["decision_rows"], "paired input count drifted")
    require(strict_prior_failures == 0, "strict-prior candidate receipt failed")
    paired.sort(
        key=lambda item: (
            item["selection"]["target_date"],
            item["selection"]["market_id"],
            item["selection"]["captured_at_utc"],
            item["selection"]["snapshot_id"],
        )
    )
    support["market_days_scanned"] = len(selected_by_day)
    support["selected_rows"] = len(paired)
    support["input_files"] = len(receipts)
    support["strict_prior_failures"] = strict_prior_failures
    support["future_snapshots_consumed"] = 0
    support["input_receipts_sha256"] = canonical_sha256(receipts)
    return paired, receipts, dict(support)


class RuntimeOpenRecorder:
    """Record exact runtime artifact/config files opened after import begins."""

    def __init__(self, runtime_root: Path):
        self.runtime_root = runtime_root.resolve()
        self.paths: set[Path] = set()

    def hook(self, event: str, args: tuple[Any, ...]) -> None:
        if event != "open" or not args:
            return
        raw_path = args[0]
        if not isinstance(raw_path, (str, bytes, os.PathLike)):
            return
        try:
            path = Path(raw_path).resolve()
        except (OSError, TypeError, ValueError):
            return
        if not is_within(path, self.runtime_root) or not path.is_file():
            return
        relative = path.relative_to(self.runtime_root)
        if relative.parts and relative.parts[0] in {"artifacts", "config"}:
            self.paths.add(path)


def normalized_distribution(value: Any) -> dict[int, float]:
    require(isinstance(value, dict), "distribution is not a mapping")
    result = {int(key): float(probability) for key, probability in value.items()}
    require(result, "distribution is empty")
    require(all(math.isfinite(probability) for probability in result.values()), "non-finite probability")
    require(all(probability >= 0.0 for probability in result.values()), "negative probability")
    mass = sum(result.values())
    require(abs(mass - 1.0) <= MASS_TOLERANCE, f"probability mass drifted: {mass}")
    return result


def distribution_l1(left: dict[int, float], right: dict[int, float]) -> tuple[float, float]:
    keys = set(left) | set(right)
    deltas = [abs(left.get(key, 0.0) - right.get(key, 0.0)) for key in keys]
    return sum(deltas), max(deltas, default=0.0)


def ceiling_delta(candidate: dict[int, float], incumbent: dict[int, float]) -> float:
    keys = set(candidate) | set(incumbent)
    squared = sum(candidate.get(key, 0.0) ** 2 for key in keys) - sum(
        incumbent.get(key, 0.0) ** 2 for key in keys
    )
    return squared + 2.0 * max(
        incumbent.get(key, 0.0) - candidate.get(key, 0.0) for key in keys
    )


def run_arms(
    paired: list[dict[str, Any]],
    runtime_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], RuntimeOpenRecorder]:
    preloaded = [name for name in sys.modules if name == "weather" or name.startswith("weather.")]
    require(not preloaded, f"weather modules loaded before runtime binding: {preloaded}")
    runtime_root = runtime_root.resolve()
    runtime_src = runtime_root / "src"
    require(runtime_src.is_dir(), f"runtime src missing: {runtime_src}")
    sys.path.insert(0, str(runtime_src))
    os.chdir(runtime_root)
    recorder = RuntimeOpenRecorder(runtime_root)
    sys.addaudithook(recorder.hook)
    toronto = importlib.import_module("weather.model.toronto_model")
    entrypoint = Path(str(toronto.__file__)).resolve()
    require(is_within(entrypoint, runtime_src), f"model entrypoint escaped runtime: {entrypoint}")

    models: dict[str, Any] = {}
    results: list[dict[str, Any]] = []
    undefined_reasons: Counter[str] = Counter()
    state_control_failures = 0
    for index, item in enumerate(paired, start=1):
        selection = item["selection"]
        market_id = selection["market_id"]
        target = date.fromisoformat(selection["target_date"])
        model = models.get(market_id)
        if model is None:
            model = toronto.TorontoHighTempModel(target_date=target, market_id=market_id)
            models[market_id] = model
        else:
            model.set_target_date(target)
        now = datetime.fromisoformat(item["built_at"])
        incumbent: dict[int, float] | None = None
        candidate: dict[int, float] | None = None
        incumbent_status = "DEFINED"
        candidate_status = "DEFINED"
        incumbent_kind = ""
        candidate_kind = ""
        try:
            incumbent = normalized_distribution(
                model.estimate_distribution(copy.deepcopy(item["incumbent_sources"]), now=now)
            )
            incumbent_kind = str(getattr(model, "active_model_kind", ""))
        except Exception as exc:  # noqa: BLE001 - undefined arms must be retained and explained
            incumbent_status = f"UNDEFINED_{type(exc).__name__}: {exc}"
            undefined_reasons[f"incumbent:{type(exc).__name__}"] += 1
        model.set_target_date(target)
        try:
            candidate = normalized_distribution(
                model.estimate_distribution(copy.deepcopy(item["candidate_sources"]), now=now)
            )
            candidate_kind = str(getattr(model, "active_model_kind", ""))
        except Exception as exc:  # noqa: BLE001
            candidate_status = f"UNDEFINED_{type(exc).__name__}: {exc}"
            undefined_reasons[f"candidate:{type(exc).__name__}"] += 1

        if incumbent is not None:
            model.set_target_date(target)
            incumbent_again = normalized_distribution(
                model.estimate_distribution(copy.deepcopy(item["incumbent_sources"]), now=now)
            )
            repeat_l1, _repeat_max = distribution_l1(incumbent, incumbent_again)
            if repeat_l1 > STATE_TOLERANCE:
                state_control_failures += 1
        row: dict[str, Any] = {
            **selection,
            "incumbent_status": incumbent_status,
            "candidate_status": candidate_status,
            "incumbent_active_model_kind": incumbent_kind,
            "candidate_active_model_kind": candidate_kind,
            "band_keys": "",
            "incumbent_probs_q": "",
            "candidate_probs_p": "",
            "incumbent_mass": None,
            "candidate_mass": None,
            "l1_displacement": None,
            "max_abs_displacement": None,
            "argmax_changed": None,
            "ceiling_delta_brier": None,
            "strict_prior_receipt": json.dumps(
                item["strict_prior_receipt"], sort_keys=True, separators=(",", ":")
            ),
            "replay_line_sha256": item["replay_line_sha256"],
        }
        if incumbent is not None and candidate is not None:
            keys = sorted(set(incumbent) | set(candidate))
            q = [incumbent.get(key, 0.0) for key in keys]
            p = [candidate.get(key, 0.0) for key in keys]
            l1, max_abs = distribution_l1(incumbent, candidate)
            row.update(
                {
                    "band_keys": json.dumps(keys, separators=(",", ":")),
                    "incumbent_probs_q": json.dumps(q, separators=(",", ":")),
                    "candidate_probs_p": json.dumps(p, separators=(",", ":")),
                    "incumbent_mass": sum(q),
                    "candidate_mass": sum(p),
                    "l1_displacement": l1,
                    "max_abs_displacement": max_abs,
                    "argmax_changed": max(incumbent, key=incumbent.get)
                    != max(candidate, key=candidate.get),
                    "ceiling_delta_brier": ceiling_delta(candidate, incumbent),
                }
            )
        results.append(row)
        if index % 50 == 0 or index == len(paired):
            print(
                f"replayed {index}/{len(paired)} paired rows; markets_loaded={len(models)}",
                file=sys.stderr,
                flush=True,
            )

    require(state_control_failures == 0, "same-model arm-order state control failed")
    zero_recovery = [row for row in results if int(row["observable_recovered_rows"]) == 0]
    require(len(zero_recovery) == 2, "zero-recovery control population drifted")
    require(
        all(float(row["l1_displacement"] or 0.0) <= STATE_TOLERANCE for row in zero_recovery),
        "zero-recovery candidate changed a distribution",
    )
    runtime = {
        "models_loaded": len(models),
        "state_control_failures": state_control_failures,
        "undefined_reasons": dict(sorted(undefined_reasons.items())),
    }
    return results, runtime, recorder


def loaded_module_files(runtime_root: Path) -> dict[str, Any]:
    runtime_root = runtime_root.resolve()
    all_weather: dict[str, str] = {}
    relevant: dict[str, str] = {}
    escapes: dict[str, str] = {}
    for name, module in sorted(sys.modules.items()):
        if not (name == "weather" or name.startswith("weather.")):
            continue
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        resolved = Path(str(module_file)).resolve()
        if is_within(resolved, runtime_root):
            relative = resolved.relative_to(runtime_root).as_posix()
            all_weather[name] = relative
            if name.startswith(RELEVANT_MODULE_PREFIXES) or "feature" in name:
                relevant[name] = relative
        else:
            escapes[name] = str(resolved)
    require(all_weather, "no loaded repository weather modules recorded")
    require(not escapes, f"weather modules escaped runtime tree: {escapes}")
    return {
        "all_weather_module_files": all_weather,
        "relevant_model_calibration_feature_market_module_files": relevant,
        "module_paths": len(all_weather),
        "relevant_module_paths": len(relevant),
        "escaped_weather_modules": escapes,
    }


def dependency_versions() -> dict[str, str]:
    result = {}
    for name in ("numpy", "scipy", "scikit-learn", "pandas", "joblib"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "not-installed"
    return result


def bundle_manifest(
    runtime_root: Path,
    modules: dict[str, Any],
    opened_paths: set[Path],
) -> tuple[dict[str, Any], list[tuple[str, Path]]]:
    runtime_root = runtime_root.resolve()
    roles: dict[str, set[str]] = defaultdict(set)
    for module_name, relative in modules["all_weather_module_files"].items():
        roles[relative].add(f"loaded_module:{module_name}")
    for path in opened_paths:
        relative = path.resolve().relative_to(runtime_root).as_posix()
        roles[relative].add("runtime_open:artifact_or_config")
    files = []
    payload_files: list[tuple[str, Path]] = []
    for relative in sorted(roles):
        path = runtime_root / relative
        require(path.is_file(), f"bundle source disappeared: {path}")
        receipt = {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "roles": sorted(roles[relative]),
        }
        files.append(receipt)
        payload_files.append((relative, path))
    manifest = {
        "schema_version": "loaded_runtime_content_bundle_v1",
        "capture_rule": "module paths enumerated from sys.modules after import and execution; artifact/config paths recorded from Python open audit events",
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "dependencies": dependency_versions(),
        "module_files": modules,
        "files": files,
        "source_module_files": sum(
            any(role.startswith("loaded_module:") for role in item["roles"]) for item in files
        ),
        "runtime_open_artifact_or_config_files": sum(
            "runtime_open:artifact_or_config" in item["roles"] for item in files
        ),
        "total_files": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
    }
    manifest["environment_content_id"] = canonical_sha256(manifest)
    return manifest, payload_files


def zip_write(zipped: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    zipped.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def emit_bundle(
    runtime_root: Path,
    modules: dict[str, Any],
    opened_paths: set[Path],
    run_root: Path,
    artifact_root: Path,
    prefix: str,
) -> dict[str, Any]:
    manifest, payload_files = bundle_manifest(runtime_root, modules, opened_paths)
    run_root.mkdir(parents=True, exist_ok=True)
    artifact_root.mkdir(parents=True, exist_ok=True)
    temporary = run_root / f"{prefix}.zip"
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", allowZip64=True) as zipped:
        zip_write(zipped, "bundle-manifest.json", canonical_json(manifest) + b"\n")
        for relative, path in payload_files:
            zip_write(zipped, relative, path.read_bytes())
    bundle_hash = sha256_file(temporary)
    destination = artifact_root / f"{prefix}-{bundle_hash[:16]}.zip"
    if destination.exists():
        require(sha256_file(destination) == bundle_hash, "content-addressed bundle collision")
        temporary.unlink()
    else:
        temporary.replace(destination)
    return {
        "path": str(destination.resolve()),
        "bytes": destination.stat().st_size,
        "sha256": bundle_hash,
        "environment_content_id": manifest["environment_content_id"],
        "manifest": manifest,
    }


def crossed_bootstrap(
    rows: list[dict[str, Any]], replicates: int, seed: int
) -> tuple[float, list[float]]:
    dates = sorted({row["target_date"] for row in rows})
    markets = sorted({row["market_id"] for row in rows})
    point = statistics.fmean(float(row["ceiling_delta_brier"]) for row in rows)
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(replicates):
        date_weights = Counter(rng.choices(dates, k=len(dates)))
        market_weights = Counter(rng.choices(markets, k=len(markets)))
        numerator = 0.0
        denominator = 0.0
        for row in rows:
            weight = date_weights[row["target_date"]] * market_weights[row["market_id"]]
            numerator += weight * float(row["ceiling_delta_brier"])
            denominator += weight
        require(denominator > 0.0, "crossed bootstrap produced an empty product draw")
        draws.append(numerator / denominator)
    return point, draws


def grouped_summary(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    result = {}
    for value, items in sorted(groups.items()):
        ceilings = [float(item["ceiling_delta_brier"]) for item in items]
        result[value] = {
            "rows": len(items),
            "mean_ceiling_delta_brier": statistics.fmean(ceilings),
            "min_ceiling_delta_brier": min(ceilings),
            "max_ceiling_delta_brier": max(ceilings),
            "mean_l1_displacement": statistics.fmean(
                float(item["l1_displacement"]) for item in items
            ),
        }
    return result


def inference(seed: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    defined = [
        row
        for row in rows
        if row["incumbent_status"] == "DEFINED"
        and row["candidate_status"] == "DEFINED"
        and row["ceiling_delta_brier"] is not None
    ]
    undefined = len(rows) - len(defined)
    require(defined, "neither arm produced a paired distribution")
    bootstrap = seed["bootstrap"]
    point, draws = crossed_bootstrap(
        defined, int(bootstrap["replicates"]), int(bootstrap["seed"])
    )
    se = statistics.stdev(draws)
    q = float(bootstrap["uniform_q"])
    lower = point - q * se
    upper = point + q * se

    detectability = seed["detectability"]
    z_power = float(detectability["z_power"])
    reference_q = float(detectability["reference_normal_q"])
    floor_fraction = float(detectability["reference_twelve_market_floor_fraction"])
    multiplier = (q + z_power) / (reference_q + z_power)
    corrected_floor = floor_fraction * multiplier
    candidate_field_mde = (q + z_power) * se
    smallest_detectable = max(corrected_floor, candidate_field_mde)
    if upper < smallest_detectable:
        verdict = "CEILING_BELOW_DETECTABLE_FLOOR_CLOSE_WITHOUT_ALPHA"
    elif lower > smallest_detectable:
        verdict = "CEILING_ABOVE_DETECTABLE_FLOOR_DRAFT_PREREGISTRATION"
    else:
        verdict = "CEILING_INTERVAL_STRADDLES_DETECTABLE_FLOOR"
    return {
        "estimand": "outcome-free declared ceiling statistic with p=candidate and q=incumbent",
        "formula": "sum(p_k^2)-sum(q_k^2)+2*max_k(q_k-p_k)",
        "support": {
            "population_rows": len(rows),
            "defined_paired_rows": len(defined),
            "undefined_rows": undefined,
            "date_clusters": len({row["target_date"] for row in defined}),
            "market_clusters": len({row["market_id"] for row in defined}),
            "market_days": len({(row["target_date"], row["market_id"]) for row in defined}),
        },
        "crossed_bootstrap": {
            "point_mean": point,
            "standard_error": se,
            "q": q,
            "lower_mean_minus_q_se": lower,
            "upper_mean_plus_q_se": upper,
            "replicates": len(draws),
            "seed": int(bootstrap["seed"]),
            "percentile_interval_used": False,
            "pointwise_domination_transfers_to_interval_bound": False,
        },
        "smallest_effect_detectable": {
            "power": float(detectability["power"]),
            "z_power": z_power,
            "reference_twelve_market_floor_fraction": floor_fraction,
            "ledger_q_multiplier": multiplier,
            "corrected_twelve_market_floor_fraction": corrected_floor,
            "candidate_field_mde_from_crossed_se": candidate_field_mde,
            "binding_smallest_detectable_effect": smallest_detectable,
            "arithmetic": (
                f"max(0.032 * (({q} + {z_power}) / ({reference_q} + {z_power})), "
                f"({q} + {z_power}) * {se})"
            ),
            "dates_cannot_remove_market_floor": True,
        },
        "verdict": verdict,
        "per_market": grouped_summary(defined, "market_id"),
        "per_target_date": grouped_summary(defined, "target_date"),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_checksums(path: Path, repo_root: Path, files: list[Path]) -> None:
    lines = [
        f"{sha256_file(item)}  {relative_or_absolute(item, repo_root)}"
        for item in files
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def execute(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    runtime_root = args.runtime_root.resolve()
    snapshots_root = args.snapshots_root.resolve()
    run_root = args.run_root.resolve()
    artifact_root = args.artifact_root.resolve()
    seed_path = args.seed.resolve()
    seed = load_seed(seed_path, repo_root)
    paired, input_receipts, input_support = extract_paired_inputs(
        seed, repo_root, snapshots_root
    )
    rows, runtime_summary, recorder = run_arms(paired, runtime_root)
    modules = loaded_module_files(runtime_root)
    bundle = emit_bundle(
        runtime_root,
        modules,
        recorder.paths,
        run_root,
        artifact_root,
        seed["outputs"]["bundle_prefix"],
    )
    inference_result = inference(seed, rows)

    csv_path = artifact_root / seed["outputs"]["csv"]
    manifest_path = artifact_root / seed["outputs"]["manifest"]
    checksums_path = artifact_root / seed["outputs"]["checksums"]
    write_csv(csv_path, rows)
    manifest = {
        "schema_version": "single_environment_repair_ceiling_manifest_v1",
        "mission": seed["mission"],
        "question_answered": "what the repair can buy under today's single environment",
        "question_not_answered": "what we would have served historically",
        "environment": {
            "source_base_commit": seed["source_base_commit"],
            "working_tree_head_at_measurement": git(repo_root, "rev-parse", "HEAD"),
            "runtime_bundle_path": relative_or_absolute(Path(bundle["path"]), repo_root),
            "runtime_bundle_bytes": bundle["bytes"],
            "runtime_bundle_sha256": bundle["sha256"],
            "environment_content_id": bundle["environment_content_id"],
            "loaded_module_files": modules,
            "bundle_manifest": bundle["manifest"],
        },
        "inputs": {
            "captured_raw_payloads": True,
            "input_support": input_support,
            "input_receipts": input_receipts,
        },
        "arms": {
            "incumbent_q": "current pipeline as-is",
            "candidate_p": seed["candidate"],
            "incumbent_defined_rows": sum(row["incumbent_status"] == "DEFINED" for row in rows),
            "candidate_defined_rows": sum(row["candidate_status"] == "DEFINED" for row in rows),
            "paired_defined_rows": sum(
                row["incumbent_status"] == "DEFINED"
                and row["candidate_status"] == "DEFINED"
                for row in rows
            ),
            "undefined_reasons": runtime_summary["undefined_reasons"],
            "same_model_state_control_failures": runtime_summary["state_control_failures"],
            "zero_recovery_control_rows": sum(
                int(row["observable_recovered_rows"]) == 0 for row in rows
            ),
        },
        "displacement": {
            "rows": len(rows),
            "changed_rows": sum(float(row["l1_displacement"] or 0.0) > STATE_TOLERANCE for row in rows),
            "mean_l1": statistics.fmean(float(row["l1_displacement"] or 0.0) for row in rows),
            "max_l1": max(float(row["l1_displacement"] or 0.0) for row in rows),
            "argmax_changed_rows": sum(row["argmax_changed"] is True for row in rows),
            "no_band_moves_over_0_005": sum(
                float(row["max_abs_displacement"] or 0.0) <= 0.005 for row in rows
            ),
        },
        "inference": inference_result,
        "receipts": {
            **seed["campaign"],
            "delta_i_computed": False,
            "commit_binding_attempted": False,
            "identity_binding_attempted": False,
            "synthetic_historical_tree_created": False,
            "whole_B_computed": False,
        },
        "artifacts": {
            "csv_path": relative_or_absolute(csv_path, repo_root),
            "csv_rows": len(rows),
            "csv_sha256": sha256_file(csv_path),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    write_checksums(
        checksums_path,
        repo_root,
        [
            csv_path,
            manifest_path,
            Path(bundle["path"]),
            SCRIPT_PATH,
            seed_path,
        ],
    )
    result = {
        "verdict": inference_result["verdict"],
        "csv": relative_or_absolute(csv_path, repo_root),
        "manifest": relative_or_absolute(manifest_path, repo_root),
        "checksums": relative_or_absolute(checksums_path, repo_root),
        "bundle": relative_or_absolute(Path(bundle["path"]), repo_root),
        "module_files": modules["all_weather_module_files"],
        "escaped_weather_modules": modules["escaped_weather_modules"],
        "inference": inference_result,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def verify_bundle(path: Path) -> dict[str, Any]:
    path = path.resolve()
    require(path.is_file(), f"bundle missing: {path}")
    with zipfile.ZipFile(path, "r") as zipped:
        manifest = json.loads(zipped.read("bundle-manifest.json"))
        for item in manifest["files"]:
            data = zipped.read(item["path"])
            require(len(data) == item["bytes"], f"bundle size mismatch: {item['path']}")
            require(sha256_bytes(data) == item["sha256"], f"bundle hash mismatch: {item['path']}")
    result = {
        "status": "PASS",
        "path": str(path),
        "sha256": sha256_file(path),
        "environment_content_id": manifest["environment_content_id"],
        "files": manifest["total_files"],
        "bytes": manifest["total_bytes"],
        "module_paths": manifest["module_files"]["module_paths"],
        "escaped_weather_modules": manifest["module_files"]["escaped_weather_modules"],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def self_test() -> None:
    incumbent = {0: 0.2, 1: 0.8}
    candidate = {0: 0.4, 1: 0.6}
    expected = sum(value * value for value in candidate.values()) - sum(
        value * value for value in incumbent.values()
    ) + 2.0 * max(incumbent[key] - candidate[key] for key in incumbent)
    require(abs(ceiling_delta(candidate, incumbent) - expected) <= 1e-15, "ceiling algebra failed")
    rows = [
        {"datetime": "2026-06-01T10:00:00-04:00", "time": "10:00", "temp_c": 70.0},
        {"datetime": "2026-06-01T11:00:00-04:00", "time": "11:00", "temp_c": 72.0},
    ]
    recovered = {
        720: {"datetime": "2026-06-01T12:00:00-04:00", "time": "12:00", "temp_c": 73.0}
    }
    merged = ordered_candidate_rows(rows, recovered, "2026-06-01")
    require([row["time"] for row in merged] == ["10:00", "11:00", "12:00"], "row merge failed")
    print("PASS")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    run = sub.add_parser("execute")
    run.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    run.add_argument("--runtime-root", type=Path, default=DEFAULT_REPO_ROOT)
    run.add_argument("--snapshots-root", type=Path, required=True)
    run.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    run.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    run.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    verify = sub.add_parser("verify-bundle")
    verify.add_argument("--bundle", type=Path, required=True)
    sub.add_parser("self-test")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    if args.command == "verify-bundle":
        verify_bundle(args.bundle)
        return 0
    result = execute(args)
    return 0 if result["verdict"] != "INVALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())

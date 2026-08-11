"""Run the outcome-blind -09-74a repair-ceiling preflight.

This extends -09-73a by selecting its B rows on which the frozen repair makes
no input change, then replaying recorded distributions only when the captured
runtime commit binds the code.  The mandatory control fails closed unless
every selected row is bound and reproduces within the frozen L1 tolerance.
Only after that gate may a future invocation enter the ceiling path.

No settlement, realized band, market probability, provider, or C endpoint is
read by this harness.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_SEED = SCRIPT_PATH.with_name("measure_repair_ceiling_09_74a_seed.json")
DEFAULT_RUN_ROOT = DEFAULT_REPO_ROOT / "scratch" / "runs" / "repair-ceiling-09-74a"
sys.path.insert(0, str(SCRIPT_PATH.parent))
import measure_safe_observation_recovery_09_73a as prior  # noqa: E402


CONTROL_FIELDS = (
    "stratum",
    "market_id",
    "target_date",
    "snapshot_id",
    "captured_at_utc",
    "window",
    "native_unit",
    "observable_recovered_rows",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_seed(path: Path, repo_root: Path) -> dict[str, Any]:
    seed = json.loads(path.read_text(encoding="utf-8"))
    for label, rel_key, sha_key in (
        ("harness", "harness_relative_path", "harness_sha256"),
        ("seed", "seed_relative_path", "seed_sha256"),
        ("csv", "csv_relative_path", "csv_sha256"),
        ("manifest", "manifest_relative_path", "manifest_sha256"),
        ("preregistration", "preregistration_relative_path", "preregistration_sha256"),
    ):
        item = seed["prior"]
        path_to_check = repo_root / item[rel_key]
        actual = sha256_file(path_to_check)
        if actual != item[sha_key]:
            raise RuntimeError(f"{label} hash mismatch: {actual}")
    return seed


def projected_control_rows(path: Path) -> list[dict[str, str]]:
    """Project only non-outcome -09-73a columns; never materialize settlement."""

    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        indexes = {name: header.index(name) for name in CONTROL_FIELDS}
        for raw in reader:
            row = {name: raw[index] for name, index in indexes.items()}
            if (
                row["stratum"] == "B"
                and row["observable_recovered_rows"] == "0"
            ):
                rows.append(row)
    return rows


def replay_path(root: Path, market_id: str, target_date: str) -> Path:
    target = date.fromisoformat(target_date)
    folder = (
        f"highest-temperature-in-{market_id}-on-"
        f"{target.strftime('%B').lower()}-{target.day}-{target.year}"
    )
    return root / folder / "replay_inputs.jsonl"


def extract_controls(
    rows: list[dict[str, str]], snapshots_root: Path, output: Path
) -> dict[str, Any]:
    wanted = {
        (row["market_id"], row["target_date"], row["snapshot_id"], row["captured_at_utc"]): row
        for row in rows
    }
    records: list[dict[str, Any]] = []
    for market_id, target_date in sorted({key[:2] for key in wanted}):
        path = replay_path(snapshots_root, market_id, target_date)
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                key = (
                    market_id,
                    target_date,
                    str(record.get("snapshot_id") or ""),
                    str(record.get("captured_at_utc") or ""),
                )
                control = wanted.get(key)
                if control is None:
                    continue
                records.append({"control": control, "record": record})
    if len(records) != len(rows):
        raise RuntimeError(f"control join mismatch: {len(records)} != {len(rows)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for item in records:
            handle.write(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n")

    runtime_bound = 0
    identity_only = 0
    missing_identity = 0
    versions: Counter[str] = Counter()
    commits: Counter[str] = Counter()
    for item in records:
        record = item["record"]
        versions[str(record.get("model_version") or "missing")] += 1
        identity = record.get("model_identity") or {}
        commit = str(((record.get("runtime_identity") or {}).get("git_commit") or "")).strip()
        if commit:
            runtime_bound += 1
            commits[commit] += 1
        elif identity:
            identity_only += 1
        else:
            missing_identity += 1
    return {
        "control_rows": len(records),
        "runtime_bound_rows": runtime_bound,
        "identity_only_rows": identity_only,
        "missing_identity_rows": missing_identity,
        "model_versions": dict(sorted(versions.items())),
        "runtime_commits": dict(sorted(commits.items())),
        "records_sha256": sha256_file(output),
    }


def distribution_l1(left: dict[Any, Any], right: dict[Any, Any]) -> tuple[float, float]:
    a = {int(key): float(value) for key, value in left.items()}
    b = {int(key): float(value) for key, value in right.items()}
    keys = set(a) | set(b)
    deltas = [abs(a.get(key, 0.0) - b.get(key, 0.0)) for key in keys]
    return sum(deltas), max(deltas, default=0.0)


def replay_bound_commit(
    records_path: Path,
    runtime_root: Path,
    runtime_commit: str,
    scientific_site: Path,
    tolerance: float,
    output: Path,
) -> dict[str, Any]:
    sys.path.insert(0, str(scientific_site))
    sys.path.insert(0, str(runtime_root / "src"))
    toronto = importlib.import_module("weather.model.toronto_model")
    modules = {
        name: str(Path(importlib.import_module(name).__file__).resolve())
        for name in (
            "weather.model.toronto_model",
            "weather.model.model_base",
            "weather.model.model_climatology",
            "weather.model.model_constants",
            "weather.model.model_distribution",
            "weather.model.model_features",
            "weather.model.feature_store",
            "weather.calibration.forecast_error_model",
            "weather.calibration.family_secondary_artifacts",
            "weather.calibration.probability_calibration",
            "weather.calibration.settlement_lag_model",
            "weather.market.market_registry",
        )
    }
    intended = str((runtime_root / "src").resolve()).lower()
    if any(not path.lower().startswith(intended) for path in modules.values()):
        raise RuntimeError(f"module escaped intended tree: {modules}")

    selected: list[dict[str, Any]] = []
    with records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            commit = str(
                ((item["record"].get("runtime_identity") or {}).get("git_commit") or "")
            ).strip()
            if commit and (
                commit.startswith(runtime_commit) or runtime_commit.startswith(commit)
            ):
                selected.append(item)
    results = []
    models: dict[tuple[str, str], Any] = {}
    for item in selected:
        control = item["control"]
        record = item["record"]
        key = (control["market_id"], control["target_date"])
        model = models.get(key)
        if model is None:
            model = toronto.TorontoHighTempModel(
                target_date=date.fromisoformat(control["target_date"]),
                market_id=control["market_id"],
            )
            models[key] = model
        replayed = model.estimate_distribution(
            record["sources"], now=datetime.fromisoformat(record["built_at"])
        )
        l1, max_abs = distribution_l1(record.get("recorded_distribution") or {}, replayed)
        results.append(
            {
                **control,
                "l1": l1,
                "max_abs": max_abs,
                "matches": l1 <= tolerance,
                "recorded_active_model_kind": (record.get("model_identity") or {}).get("active_model_kind"),
                "replayed_active_model_kind": getattr(model, "active_model_kind", None),
            }
        )
    receipt = {
        "schema_version": "repair_ceiling_runtime_control_v1",
        "runtime_commit": runtime_commit,
        "runtime_root": str(runtime_root.resolve()),
        "module_files": modules,
        "tolerance": tolerance,
        "rows": len(results),
        "matched_rows": sum(row["matches"] for row in results),
        "max_l1": max((row["l1"] for row in results), default=None),
        "max_abs": max((row["max_abs"] for row in results), default=None),
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def aggregate(
    seed: dict[str, Any], inventory_path: Path, receipts: list[Path], output: Path
) -> dict[str, Any]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in receipts]
    matched = sum(int(item["matched_rows"]) for item in payloads)
    replayed = sum(int(item["rows"]) for item in payloads)
    total = int(inventory["control_rows"])
    control_pass = matched == total and replayed == total
    manifest = {
        "schema_version": "repair_ceiling_control_manifest_v1",
        "mission": seed["mission"],
        "status": "PASS" if control_pass else "BLOCK_STOP_BEFORE_CANDIDATE",
        "control": {
            **inventory,
            "tolerance": seed["control"]["l1_tolerance"],
            "replayed_rows": replayed,
            "matched_rows": matched,
            "population_match_rate": matched / total if total else None,
            "replayed_match_rate": matched / replayed if replayed else None,
            "required_match_rate": seed["control"]["required_match_rate"],
        },
        "receipts": [
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "runtime_commit": item["runtime_commit"],
                "rows": item["rows"],
                "matched_rows": item["matched_rows"],
                "max_l1": item["max_l1"],
                "module_files": item["module_files"],
            }
            for path, item in zip(receipts, payloads)
        ],
        "ceiling_path": {
            "entered": False,
            "reason": None if control_pass else "mandatory incumbent reproduction control did not cover and match every row",
            "realized_band_read": False,
            "settlement_consulted_for_ceiling": False,
        },
        "campaign": seed["campaign"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract")
    extract.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    extract.add_argument("--snapshots-root", type=Path, required=True)
    extract.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    replay = sub.add_parser("replay")
    replay.add_argument("--records", type=Path, required=True)
    replay.add_argument("--runtime-root", type=Path, required=True)
    replay.add_argument("--runtime-commit", required=True)
    replay.add_argument("--scientific-site", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)
    final = sub.add_parser("aggregate")
    final.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    final.add_argument("--inventory", type=Path, required=True)
    final.add_argument("--receipts", type=Path, nargs="*", default=[])
    final.add_argument("--output", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "extract":
        seed = load_seed(DEFAULT_SEED, args.repo_root.resolve())
        csv_path = args.repo_root / seed["prior"]["csv_relative_path"]
        controls = projected_control_rows(csv_path)
        run_root = args.run_root.resolve()
        inventory = extract_controls(controls, args.snapshots_root.resolve(), run_root / "control-records.jsonl")
        (run_root / "inventory.json").write_text(
            json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(inventory, indent=2, sort_keys=True))
        return 0
    if args.command == "replay":
        seed = json.loads(DEFAULT_SEED.read_text(encoding="utf-8"))
        receipt = replay_bound_commit(
            args.records.resolve(),
            args.runtime_root.resolve(),
            args.runtime_commit,
            args.scientific_site.resolve(),
            float(seed["control"]["l1_tolerance"]),
            args.output.resolve(),
        )
        print(json.dumps({key: receipt[key] for key in ("runtime_commit", "rows", "matched_rows", "max_l1", "module_files")}, indent=2))
        return 0 if receipt["matched_rows"] == receipt["rows"] else 2
    seed = load_seed(DEFAULT_SEED, args.repo_root.resolve())
    manifest = aggregate(seed, args.inventory.resolve(), [path.resolve() for path in args.receipts], args.output.resolve())
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

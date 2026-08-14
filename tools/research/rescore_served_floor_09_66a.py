"""Re-score the sealed B/C panel with the floor that production actually served.

This is a one-off diagnostic harness. It fits no parameter, constructs no
candidate, changes no repository model/scoring code, and has no accept rule.
The retained replay method is compiled in memory with exactly one AST change:
the local ``hard_floor_bucket`` assignment reads the supplied per-snapshot
``served_floor_bucket``. Every other AST node remains the pinned method.

C is processed first and every projected band probability must have the same
IEEE-754 binary64 bytes as the retained repaired panel. Any mismatch is written
as a fail-closed control result and B is not read or scored.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import inspect
import json
import math
import pickle
import re
import struct
import sys
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np


REPO = Path(__file__).resolve().parents[2]
DEFAULT_SEED = Path(__file__).with_name("rescore_served_floor_09_66a_seed.json")
DEFAULT_OUTPUT = REPO / "scratch" / "runs" / "served-floor-rescore-2026-09-66a"

sys.path.insert(0, str(REPO / "src"))
# The removed 3.11 venv still retains pure-Python HTTP import dependencies.
# Append (never prepend) it so the bundled 3.12 runtime keeps its own compiled
# NumPy/pandas/scikit stack while dormant request helpers can import.
LEGACY_PURE_PYTHON_SITE = REPO / "venv" / "Lib" / "site-packages"
if LEGACY_PURE_PYTHON_SITE.is_dir():
    sys.path.append(str(LEGACY_PURE_PYTHON_SITE))
import weather.paths as weather_paths  # noqa: E402

# Match the retained measurement: no ambient mutable model data may participate.
weather_paths.DATA_ROOT = DEFAULT_OUTPUT / "ambient-model-data-access-disabled"

from weather.model import model_distribution as model_distribution_module  # noqa: E402
from weather.model.model_distribution import DistributionMixin  # noqa: E402
from weather.model.model_constants import TORONTO_TZ  # noqa: E402
from weather.model.toronto_model import TorontoHighTempModel  # noqa: E402
from weather.release_serving import (  # noqa: E402
    STATUS_RESEARCH_UNBOUND,
    VerifiedServingBundle,
)


PAIRED_HEADER = (
    "snapshot_id",
    "record_hash",
    "target_date",
    "stratum",
    "market_id",
    "capture_hour",
    "effective_cutoff_hour",
    "band_index",
    "outcome",
    "market_probability",
    "market_squared_error",
    "control_probability",
    "repair_probability",
    "control_squared_error",
    "repair_squared_error",
    "probability_delta",
    "squared_error_delta",
)
BAND_IDENTITY_REQUIRED = {
    "snapshot_id",
    "record_hash",
    "target_date",
    "stratum",
    "market_id",
    "capture_hour",
    "effective_cutoff_hour",
    "band_index",
    "range_label",
    "bin_kind",
    "bin_value",
    "bin_value_hi",
    "outcome",
}
SERVED_FLOOR_HEADER = (
    "stratum",
    "market_id",
    "target_date",
    "snapshot_id",
    "served_floor_bucket",
    "served_high_so_far",
    "raw_wu_max_since_7am",
    "raw_station_max_since_7am",
)


class IntegrityFailure(RuntimeError):
    """A pinned input, source, or control contract failed."""


@dataclass(frozen=True)
class BandRow:
    index: int
    outcome: int
    market_probability: float
    original_probability: float
    band: dict[str, str]


@dataclass(frozen=True)
class Snapshot:
    key: tuple[str, str, str, str]
    record_hash: str
    capture_hour: int
    effective_cutoff_hour: int
    served_floor_bucket: int | None
    bands: tuple[BandRow, ...]

    @property
    def stratum(self) -> str:
        return self.key[0]

    @property
    def market_id(self) -> str:
        return self.key[1]

    @property
    def target_date(self) -> str:
        return self.key[2]

    @property
    def snapshot_id(self) -> str:
        return self.key[3]


class PortableSklearnState:
    """State-only target for sklearn objects not used during prediction."""

    def __new__(cls, *_args, **_kwargs):
        return object.__new__(cls)

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __setstate__(self, state: Any) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)
        elif isinstance(state, tuple) and len(state) == 2 and isinstance(state[1], dict):
            self.__dict__.update(state[1])
        else:
            self._portable_state = state


class PortableSimpleImputer(PortableSklearnState):
    def transform(self, frame: Any) -> np.ndarray:
        values = frame.to_numpy(dtype=float).copy()
        statistics = np.asarray(self.statistics_, dtype=float)
        require(values.shape[1] == len(statistics), "portable imputer width drifted")
        missing_rows, missing_columns = np.where(np.isnan(values))
        values[missing_rows, missing_columns] = statistics[missing_columns]
        return values


def portable_tree_predict(tree: Any, values: np.ndarray) -> np.ndarray:
    nodes = tree.nodes
    require(not bool(np.any(nodes["is_categorical"])), "portable HGB encountered categorical split")
    predictions = np.empty(values.shape[0], dtype=float)
    for row_index, row in enumerate(values):
        node_index = 0
        while not bool(nodes[node_index]["is_leaf"]):
            node = nodes[node_index]
            value = row[int(node["feature_idx"])]
            go_left = (
                bool(node["missing_go_to_left"])
                if math.isnan(float(value))
                else float(value) <= float(node["num_threshold"])
            )
            node_index = int(node["left"] if go_left else node["right"])
        predictions[row_index] = float(nodes[node_index]["value"])
    return predictions


class PortableHistGradientBoostingClassifier(PortableSklearnState):
    """Evaluate frozen sklearn HGB trees with NumPy under bundled Python 3.12."""

    def predict_proba(self, values: Any) -> np.ndarray:
        matrix = np.asarray(values, dtype=float)
        cache = getattr(self, "_portable_prediction_cache", None)
        if cache is None:
            cache = {}
            self._portable_prediction_cache = cache
        cache_key = (matrix.shape, matrix.tobytes())
        if cache_key in cache:
            return cache[cache_key].copy()
        raw = np.tile(np.asarray(self._baseline_prediction, dtype=float), (len(matrix), 1))
        require(raw.shape[1] == int(self.n_trees_per_iteration_), "portable HGB class width drifted")
        for iteration in self._predictors:
            require(len(iteration) == raw.shape[1], "portable HGB tree iteration width drifted")
            for class_index, tree in enumerate(iteration):
                # HistGradientBoosting stores shrinkage in each leaf value.
                raw[:, class_index] += portable_tree_predict(tree, matrix)
        shifted = raw - raw.max(axis=1, keepdims=True)
        probabilities = np.exp(shifted)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        cache[cache_key] = probabilities.copy()
        return probabilities


_PORTABLE_SKLEARN_CLASSES: dict[tuple[str, str], type[PortableSklearnState]] = {}


def portable_sklearn_factory(*_args) -> PortableSklearnState:
    return PortableSklearnState()


class PortableArtifactUnpickler(pickle.Unpickler):
    """Load frozen sklearn state without importing incompatible 3.11 binaries."""

    def find_class(self, module: str, name: str):
        if module.startswith("sklearn.") or module == "_loss":
            if name.startswith("__pyx_unpickle_"):
                return portable_sklearn_factory
            if name == "HistGradientBoostingClassifier":
                return PortableHistGradientBoostingClassifier
            if name == "SimpleImputer":
                return PortableSimpleImputer
            key = (module, name)
            if key not in _PORTABLE_SKLEARN_CLASSES:
                _PORTABLE_SKLEARN_CLASSES[key] = type(
                    name,
                    (PortableSklearnState,),
                    {"__module__": __name__},
                )
            return _PORTABLE_SKLEARN_CLASSES[key]
        return super().find_class(module, name)


_PORTABLE_HGB_CACHE: dict[Path, dict[str, Any]] = {}


def load_portable_hgb(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved not in _PORTABLE_HGB_CACHE:
        with resolved.open("rb") as handle:
            payload = PortableArtifactUnpickler(handle).load()
        require(isinstance(payload, dict), f"portable HGB artifact is not a dict: {resolved}")
        _PORTABLE_HGB_CACHE[resolved] = payload
    return _PORTABLE_HGB_CACHE[resolved]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrityFailure(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def float_bytes(value: float) -> bytes:
    return struct.pack(">d", float(value))


def parse_optional_bucket(value: str) -> int | None:
    if value.strip() == "":
        return None
    number = float(value)
    require(math.isfinite(number), f"non-finite floor bucket: {value!r}")
    rounded = int(round(number))
    require(abs(number - rounded) <= 1e-12, f"non-integral floor bucket: {value!r}")
    return rounded


def parse_built_at(record: dict[str, Any]) -> datetime | None:
    """Pinned local copy of the pure replay timestamp parser."""
    value = record.get("built_at") or record.get("captured_at_local")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TORONTO_TZ)
    return parsed


def numeric_band_value(value: Any) -> int | float | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    if abs(numeric - round(numeric)) < 1e-9:
        return int(round(numeric))
    return numeric


def band_value_hi(band: dict[str, Any]) -> int | float | None:
    explicit = numeric_band_value(
        band.get("bin_value_hi_c")
        if band.get("bin_value_hi_c") not in (None, "")
        else band.get("bin_value_hi")
    )
    if explicit is not None:
        return explicit
    value = numeric_band_value(band.get("bin_value_c") or band.get("bin_value"))
    numbers = re.findall(r"\d+", str(band.get("range_label") or ""))
    return int(numbers[-1]) if len(numbers) >= 2 else value


def band_model_probability(
    model: TorontoHighTempModel,
    distribution: dict[Any, Any],
    band: dict[str, Any],
) -> float:
    """Pinned local copy of production's replay band projection."""
    value = numeric_band_value(band.get("bin_value_c") or band.get("bin_value"))
    return float(
        model.bin_probability(
            distribution,
            {
                "kind": band.get("bin_kind"),
                "value": value,
                "value_hi": band_value_hi(band),
                "label": band.get("range_label"),
                "market_yes": band.get("market_yes"),
                "market_no": band.get("market_no"),
            },
        )
    )


def replay_distribution(
    model: TorontoHighTempModel,
    record: dict[str, Any],
) -> dict[Any, Any]:
    """Replay one captured record without importing network-adjacent helpers."""
    return model.estimate_distribution(record.get("sources") or {}, now=parse_built_at(record))


def resolve(seed: dict[str, Any], name: str) -> Path:
    return REPO / seed["inputs"][name]["relative_path"]


def verify_seeded_files(seed: dict[str, Any]) -> dict[str, str]:
    receipts: dict[str, str] = {}
    for name, expected in seed["inputs"].items():
        path = REPO / expected["relative_path"]
        require(path.is_file(), f"missing seeded input: {path}")
        actual = sha256(path)
        require(actual == expected["sha256"], f"{name} SHA-256 drifted: {actual}")
        if "bytes" in expected:
            require(path.stat().st_size == int(expected["bytes"]), f"{name} byte size drifted")
        receipts[name] = actual
    for relative, expected_hash in seed["source_sha256"].items():
        path = REPO / relative
        require(path.is_file(), f"missing pinned source: {relative}")
        actual = sha256(path)
        require(actual == expected_hash, f"source SHA-256 drifted: {relative}: {actual}")
        receipts[relative] = actual
    return receipts


class HardFloorAssignmentRewriter(ast.NodeTransformer):
    def __init__(self) -> None:
        self.replacements = 0

    def visit_Assign(self, node: ast.Assign) -> ast.AST:  # noqa: N802
        node = self.generic_visit(node)
        if any(isinstance(target, ast.Name) and target.id == "hard_floor_bucket" for target in node.targets):
            require(self.replacements == 0, "multiple hard_floor_bucket assignments found")
            original_value = node.value
            override = ast.Attribute(
                value=ast.Name(id="self", ctx=ast.Load()),
                attr="_diagnostic_served_floor_bucket",
                ctx=ast.Load(),
            )
            node.value = ast.copy_location(
                ast.IfExp(
                    test=ast.Compare(
                        left=override,
                        ops=[ast.IsNot()],
                        comparators=[ast.Constant(value=None)],
                    ),
                    body=ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()),
                        attr="_diagnostic_served_floor_bucket",
                        ctx=ast.Load(),
                    ),
                    orelse=original_value,
                ),
                original_value,
            )
            self.replacements += 1
        return node


def compile_diagnostic_method(seed: dict[str, Any]):
    original = DistributionMixin._estimate_distribution_result
    source = textwrap.dedent(inspect.getsource(original))
    before = ast.parse(source)
    after = ast.parse(source)
    rewriter = HardFloorAssignmentRewriter()
    after = rewriter.visit(after)
    ast.fix_missing_locations(after)
    expected = int(seed["intervention"]["expected_replacements"])
    require(rewriter.replacements == expected, f"AST replacement count {rewriter.replacements} != {expected}")

    # Prove structurally that replacing the assigned expression is the sole change.
    original_rewriter = HardFloorAssignmentRewriter()
    normalized_before = original_rewriter.visit(before)
    ast.fix_missing_locations(normalized_before)
    require(
        ast.dump(normalized_before, include_attributes=False)
        == ast.dump(after, include_attributes=False),
        "AST changed outside the hard_floor_bucket assignment",
    )

    local_namespace: dict[str, Any] = {}
    exec(
        compile(after, filename=str(inspect.getsourcefile(original)), mode="exec"),
        model_distribution_module.__dict__,
        local_namespace,
    )
    method = local_namespace[original.__name__]
    return method, {
        "method": f"{DistributionMixin.__name__}.{original.__name__}",
        "replacements": rewriter.replacements,
        "original_ast_sha256": hashlib.sha256(
            ast.dump(ast.parse(source), include_attributes=False).encode("utf-8")
        ).hexdigest(),
        "rewritten_ast_sha256": hashlib.sha256(
            ast.dump(after, include_attributes=False).encode("utf-8")
        ).hexdigest(),
    }


class ServedFloorDiagnosticModel(TorontoHighTempModel):
    """The pinned incumbent with only the local hard-floor assignment replaced."""

    _diagnostic_served_floor_bucket: int | None = None

    def _read_feature_model_hgb(self):
        suffix = self.spec.artifact_suffix
        path = REPO / "artifacts" / "models" / "hgb" / f"feature_model_hgb{suffix}.pkl"
        require(path.is_file(), f"missing frozen HGB artifact: {path}")
        return load_portable_hgb(path)


def identity_key(row: dict[str, str]) -> tuple[str, ...]:
    return (
        row["snapshot_id"],
        row["record_hash"],
        row["target_date"],
        row["stratum"],
        row["market_id"],
        str(int(row["capture_hour"])),
        str(int(row["effective_cutoff_hour"])),
        str(int(row["band_index"])),
        str(int(row["outcome"])),
    )


def load_band_identities(path: Path, expected_rows: int) -> dict[tuple[str, ...], dict[str, str]]:
    identities: dict[tuple[str, ...], dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames is not None, "band identity input has no header")
        require(BAND_IDENTITY_REQUIRED <= set(reader.fieldnames), "band identity columns drifted")
        for row in reader:
            key = identity_key(row)
            require(key not in identities, f"duplicate band identity key: {key}")
            identities[key] = {
                "range_label": row["range_label"],
                "bin_kind": row["bin_kind"],
                "bin_value_c": row["bin_value"],
                "bin_value_hi_c": row["bin_value_hi"],
            }
    require(len(identities) == expected_rows, f"band identity rows {len(identities)} != {expected_rows}")
    return identities


def load_floors(path: Path, expected_rows: int) -> dict[tuple[str, str, str, str], int | None]:
    floors: dict[tuple[str, str, str, str], int | None] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        require(tuple(reader.fieldnames or ()) == SERVED_FLOOR_HEADER, "served-floor header drifted")
        for row in reader:
            key = (row["stratum"], row["market_id"], row["target_date"], row["snapshot_id"])
            require(key not in floors, f"duplicate served-floor key: {key}")
            floors[key] = parse_optional_bucket(row["served_floor_bucket"])
    require(len(floors) == expected_rows, f"served-floor rows {len(floors)} != {expected_rows}")
    return floors


def load_panel(seed: dict[str, Any]) -> tuple[dict[tuple[str, str, str, str], Snapshot], dict[str, Any]]:
    paired_cfg = seed["inputs"]["paired_panel"]
    identity_cfg = seed["inputs"]["band_identity"]
    identities = load_band_identities(resolve(seed, "band_identity"), int(identity_cfg["band_rows"]))
    floors = load_floors(resolve(seed, "served_floor"), int(seed["inputs"]["served_floor"]["snapshot_rows"]))
    grouped: dict[tuple[str, str, str, str], list[BandRow]] = defaultdict(list)
    metadata: dict[tuple[str, str, str, str], tuple[str, int, int]] = {}
    paired_rows = 0
    with resolve(seed, "paired_panel").open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        require(tuple(reader.fieldnames or ()) == PAIRED_HEADER, "paired panel header drifted")
        for row in reader:
            paired_rows += 1
            require(row["target_date"] < seed["regime_boundary"], "panel crossed 2026-07-31")
            snapshot_key = (row["stratum"], row["market_id"], row["target_date"], row["snapshot_id"])
            band_key = identity_key(row)
            require(band_key in identities, f"missing band identity: {band_key}")
            outcome = int(row["outcome"])
            require(outcome in (0, 1), f"invalid outcome: {band_key}")
            grouped[snapshot_key].append(
                BandRow(
                    index=int(row["band_index"]),
                    outcome=outcome,
                    market_probability=float(row["market_probability"]),
                    original_probability=float(row["repair_probability"]),
                    band=identities.pop(band_key),
                )
            )
            current_metadata = (
                row["record_hash"],
                int(row["capture_hour"]),
                int(row["effective_cutoff_hour"]),
            )
            prior_metadata = metadata.setdefault(snapshot_key, current_metadata)
            require(prior_metadata == current_metadata, f"snapshot metadata differs: {snapshot_key}")
    require(paired_rows == int(paired_cfg["band_rows"]), f"paired rows {paired_rows} drifted")
    require(not identities, f"unused band identity rows: {len(identities)}")
    require(set(grouped) == set(floors), "served-floor keys do not exactly match panel keys")

    snapshots: dict[tuple[str, str, str, str], Snapshot] = {}
    for key, rows in grouped.items():
        rows.sort(key=lambda row: row.index)
        require([row.index for row in rows] == list(range(11)), f"non-contiguous 11 bands: {key}")
        require(sum(row.outcome for row in rows) == 1, f"snapshot is not one-hot: {key}")
        record_hash, capture_hour, effective_cutoff_hour = metadata[key]
        snapshots[key] = Snapshot(
            key=key,
            record_hash=record_hash,
            capture_hour=capture_hour,
            effective_cutoff_hour=effective_cutoff_hour,
            served_floor_bucket=floors[key],
            bands=tuple(rows),
        )
    require(len(snapshots) == int(paired_cfg["snapshot_rows"]), "snapshot count drifted")

    support: dict[str, Any] = {}
    for stratum in ("B", "C"):
        scoped = [snapshot for snapshot in snapshots.values() if snapshot.stratum == stratum]
        observed = {
            "date_clusters": len({snapshot.target_date for snapshot in scoped}),
            "market_clusters": len({snapshot.market_id for snapshot in scoped}),
            "market_days": len({(snapshot.target_date, snapshot.market_id) for snapshot in scoped}),
            "snapshot_rows": len(scoped),
            "band_rows": sum(len(snapshot.bands) for snapshot in scoped),
            "original_realized_band_zeros": sum(
                band.original_probability == 0.0
                for snapshot in scoped
                for band in snapshot.bands
                if band.outcome == 1
            ),
        }
        require(observed == seed["expected_support"][stratum], f"{stratum} support drifted: {observed}")
        support[stratum] = observed
    return snapshots, support


def load_receipts(seed: dict[str, Any], snapshots: dict[tuple[str, str, str, str], Snapshot]):
    manifest = json.loads(resolve(seed, "retained_measurement_manifest").read_text(encoding="utf-8"))
    require(
        int(manifest.get("selected_hour_rows", -1))
        == int(seed["inputs"]["retained_measurement_manifest"]["selected_snapshot_rows"]),
        "retained manifest selected row count drifted",
    )
    cells = {(snapshot.market_id, snapshot.target_date) for snapshot in snapshots.values()}
    receipts: dict[tuple[str, str], dict[str, Any]] = {}
    for receipt in manifest["cell_receipts"]:
        if receipt.get("status") != "admitted":
            continue
        key = (str(receipt["market_id"]), str(receipt["target_date"]))
        require(key not in receipts, f"duplicate admitted cell receipt: {key}")
        receipts[key] = receipt
    require(set(receipts) == cells, "retained manifest market-day roster differs from panel")
    return receipts


def make_models(method) -> dict[str, ServedFloorDiagnosticModel]:
    class BoundDiagnosticModel(ServedFloorDiagnosticModel):
        pass

    BoundDiagnosticModel._estimate_distribution_result = method
    bundle = VerifiedServingBundle(
        status=STATUS_RESEARCH_UNBOUND,
        reason="read-only served-floor diagnostic re-score",
        pointer_present=False,
    )
    return {
        market: BoundDiagnosticModel(market_id=market, serving_bundle=bundle)
        for market in sorted({
            "atlanta", "austin", "chicago", "dallas", "denver", "houston",
            "los-angeles", "miami", "nyc", "san-francisco", "seattle", "toronto",
        })
    }


def replay_records_for_cell(
    receipt: dict[str, Any],
    wanted: dict[str, Snapshot],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    path = REPO / "data" / "snapshots" / str(receipt["event_slug"]) / "replay_inputs.jsonl"
    require(path.is_file(), f"missing retained replay input: {path}")
    expected = receipt["replay_inputs"]
    require(path.stat().st_size == int(expected["bytes"]), f"replay input bytes drifted: {path}")
    actual_hash = sha256(path)
    require(actual_hash == expected["sha256"], f"replay input SHA-256 drifted: {path}: {actual_hash}")
    matches: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            snapshot_id = str(record.get("snapshot_id") or "")
            snapshot = wanted.get(snapshot_id)
            if snapshot is None:
                continue
            if canonical_hash(record) != snapshot.record_hash:
                continue
            require(snapshot_id not in matches, f"duplicate exact replay record: {snapshot_id}")
            matches[snapshot_id] = record
    require(set(matches) == set(wanted), f"exact replay record coverage failed: {receipt['event_slug']}")
    return matches, {"path": str(path), "sha256": actual_hash, "bytes": path.stat().st_size}


def process_stratum(
    stratum: str,
    snapshots: dict[tuple[str, str, str, str], Snapshot],
    receipts: dict[tuple[str, str], dict[str, Any]],
    method,
    seed: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    baseline_models = make_models(DistributionMixin._estimate_distribution_result)
    models = make_models(method)
    scoped = [snapshot for snapshot in snapshots.values() if snapshot.stratum == stratum]
    by_cell: dict[tuple[str, str], dict[str, Snapshot]] = defaultdict(dict)
    for snapshot in scoped:
        by_cell[(snapshot.market_id, snapshot.target_date)][snapshot.snapshot_id] = snapshot

    total_original_sse = 0.0
    total_baseline_sse = 0.0
    total_rescored_sse = 0.0
    total_market_sse = 0.0
    original_zeros = 0
    rescored_zeros = 0
    surviving_original_zeros = 0
    changed_band_rows = 0
    changed_snapshots = 0
    max_absolute_probability_change = 0.0
    max_baseline_probability_difference_from_retained = 0.0
    rescored_rows: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []
    model_identities: dict[str, Any] = {}
    input_receipts: dict[str, Any] = {}
    processed = 0

    for cell in sorted(by_cell):
        market_id, target_date = cell
        records, replay_receipt = replay_records_for_cell(receipts[cell], by_cell[cell])
        input_receipts[f"{market_id}:{target_date}"] = replay_receipt
        baseline_model = baseline_models[market_id]
        model = models[market_id]
        baseline_model.set_target_date(date.fromisoformat(target_date))
        model.set_target_date(date.fromisoformat(target_date))
        for snapshot_id in sorted(by_cell[cell]):
            snapshot = by_cell[cell][snapshot_id]
            record = records[snapshot_id]
            require(str(record.get("target_date") or "") == target_date, f"record target drifted: {snapshot.key}")

            baseline_model._diagnostic_served_floor_bucket = None
            baseline_distribution = replay_distribution(baseline_model, record)
            require(baseline_distribution, f"empty baseline distribution: {snapshot.key}")
            baseline_pipeline = baseline_model._last_distribution_pipeline_state
            require(baseline_pipeline is not None, f"missing baseline pipeline: {snapshot.key}")
            baseline_floor = baseline_pipeline.metadata.get("observed_floor_bucket")

            model._diagnostic_served_floor_bucket = snapshot.served_floor_bucket
            distribution = replay_distribution(model, record)
            require(distribution, f"empty diagnostic distribution: {snapshot.key}")
            pipeline = model._last_distribution_pipeline_state
            require(pipeline is not None, f"missing pipeline state: {snapshot.key}")
            observed_floor = pipeline.metadata.get("observed_floor_bucket")
            expected_floor = (
                snapshot.served_floor_bucket
                if snapshot.served_floor_bucket is not None
                else baseline_floor
            )
            require(observed_floor == expected_floor, f"floor override did not bind: {snapshot.key}")
            require(
                int(baseline_pipeline.metadata["cutoff_hour"]) == snapshot.effective_cutoff_hour,
                f"baseline cutoff drifted: {snapshot.key}",
            )
            require(int(pipeline.metadata["cutoff_hour"]) == snapshot.effective_cutoff_hour, f"cutoff drifted: {snapshot.key}")
            if market_id not in model_identities:
                model_identities[market_id] = {
                    "baseline_active_model_kind": baseline_model.active_model_kind,
                    "diagnostic_active_model_kind": model.active_model_kind,
                    "model_version": model.get_model_version_string(),
                }

            baseline_probabilities = [
                float(band_model_probability(baseline_model, baseline_distribution, band.band))
                for band in snapshot.bands
            ]
            probabilities = [float(band_model_probability(model, distribution, band.band)) for band in snapshot.bands]
            require(
                all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in baseline_probabilities),
                f"invalid baseline probability: {snapshot.key}",
            )
            require(all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in probabilities), f"invalid probability: {snapshot.key}")
            require(abs(sum(baseline_probabilities) - 1.0) <= float(seed["comparison"]["mass_tolerance"]), f"baseline mass failed: {snapshot.key}")
            require(abs(sum(probabilities) - 1.0) <= float(seed["comparison"]["mass_tolerance"]), f"mass failed: {snapshot.key}")
            snapshot_changed = False
            original_snapshot_sse = 0.0
            baseline_snapshot_sse = 0.0
            rescored_snapshot_sse = 0.0
            market_snapshot_sse = 0.0
            original_winner_probability = None
            baseline_winner_probability = None
            rescored_winner_probability = None
            for band, baseline_probability, rescored_probability in zip(
                snapshot.bands,
                baseline_probabilities,
                probabilities,
                strict=True,
            ):
                baseline_difference = abs(baseline_probability - band.original_probability)
                max_baseline_probability_difference_from_retained = max(
                    max_baseline_probability_difference_from_retained,
                    baseline_difference,
                )
                changed = float_bytes(baseline_probability) != float_bytes(rescored_probability)
                snapshot_changed = snapshot_changed or changed
                changed_band_rows += int(changed)
                max_absolute_probability_change = max(
                    max_absolute_probability_change,
                    abs(rescored_probability - baseline_probability),
                )
                original_error = (band.original_probability - band.outcome) ** 2
                baseline_error = (baseline_probability - band.outcome) ** 2
                rescored_error = (rescored_probability - band.outcome) ** 2
                market_error = (band.market_probability - band.outcome) ** 2
                total_original_sse += original_error
                total_baseline_sse += baseline_error
                total_rescored_sse += rescored_error
                total_market_sse += market_error
                original_snapshot_sse += original_error
                baseline_snapshot_sse += baseline_error
                rescored_snapshot_sse += rescored_error
                market_snapshot_sse += market_error
                if band.outcome == 1:
                    original_winner_probability = band.original_probability
                    baseline_winner_probability = baseline_probability
                    rescored_winner_probability = rescored_probability
                rescored_rows.append(
                    {
                        "stratum": stratum,
                        "market_id": market_id,
                        "target_date": target_date,
                        "snapshot_id": snapshot_id,
                        "record_hash": snapshot.record_hash,
                        "band_index": band.index,
                        "outcome": band.outcome,
                        "market_probability": format(band.market_probability, ".17g"),
                        "original_probability": format(band.original_probability, ".17g"),
                        "portable_baseline_probability": format(baseline_probability, ".17g"),
                        "served_floor_probability": format(rescored_probability, ".17g"),
                        "probability_changed_binary64": str(changed).lower(),
                        "served_floor_bucket": "" if snapshot.served_floor_bucket is None else snapshot.served_floor_bucket,
                    }
                )
            require(original_winner_probability is not None, f"winner missing: {snapshot.key}")
            require(baseline_winner_probability is not None, f"baseline winner missing: {snapshot.key}")
            require(rescored_winner_probability is not None, f"rescored winner missing: {snapshot.key}")
            original_zero = original_winner_probability == 0.0
            baseline_zero = baseline_winner_probability == 0.0
            rescored_zero = rescored_winner_probability == 0.0
            require(baseline_zero == original_zero, f"portable baseline changed realized zero: {snapshot.key}")
            original_zeros += int(original_zero)
            rescored_zeros += int(rescored_zero)
            surviving_original_zeros += int(original_zero and rescored_zero)
            changed_snapshots += int(snapshot_changed)
            snapshot_rows.append(
                {
                    "stratum": stratum,
                    "market_id": market_id,
                    "target_date": target_date,
                    "snapshot_id": snapshot_id,
                    "record_hash": snapshot.record_hash,
                    "served_floor_bucket": "" if snapshot.served_floor_bucket is None else snapshot.served_floor_bucket,
                    "probability_changed_at_all_binary64": str(snapshot_changed).lower(),
                    "original_realized_probability": format(original_winner_probability, ".17g"),
                    "portable_baseline_realized_probability": format(baseline_winner_probability, ".17g"),
                    "served_floor_realized_probability": format(rescored_winner_probability, ".17g"),
                    "original_realized_zero": str(original_zero).lower(),
                    "served_floor_realized_zero": str(rescored_zero).lower(),
                    "original_brier_sum": format(original_snapshot_sse, ".17g"),
                    "portable_baseline_brier_sum": format(baseline_snapshot_sse, ".17g"),
                    "served_floor_brier_sum": format(rescored_snapshot_sse, ".17g"),
                    "market_brier_sum": format(market_snapshot_sse, ".17g"),
                }
            )
            processed += 1
        if processed % 500 < len(by_cell[cell]):
            print(json.dumps({"phase": f"rescore_{stratum}", "snapshots": processed, "total": len(scoped)}), flush=True)

    band_rows = sum(len(snapshot.bands) for snapshot in scoped)
    original_brier = total_original_sse / band_rows
    baseline_brier = total_baseline_sse / band_rows
    direct_rescored_brier = total_rescored_sse / band_rows
    market_brier = total_market_sse / band_rows
    tolerance = float(seed["comparison"]["reference_tolerance"])
    reference = seed["references"][stratum]
    require(abs(original_brier - float(reference["incumbent_brier"])) <= tolerance, f"{stratum} incumbent reference drifted")
    require(abs(market_brier - float(reference["market_brier"])) <= tolerance, f"{stratum} market reference drifted")
    portable_tolerance = float(seed["comparison"]["portable_reference_probability_tolerance"])
    require(
        max_baseline_probability_difference_from_retained <= portable_tolerance,
        f"{stratum} portable baseline probability drifted by "
        f"{max_baseline_probability_difference_from_retained:.17g}",
    )
    require(original_zeros == int(seed["expected_support"][stratum]["original_realized_band_zeros"]), f"{stratum} original zero count drifted")
    paired_brier_delta = (total_rescored_sse - total_baseline_sse) / band_rows
    reference_incumbent_brier = float(reference["incumbent_brier"])
    reference_market_brier = float(reference["market_brier"])
    reference_gap = float(reference["gap"])
    rescored_brier = reference_incumbent_brier + paired_brier_delta
    rescored_gap = reference_gap + paired_brier_delta
    result = {
        "support": seed["expected_support"][stratum],
        "original": {
            "incumbent_brier": reference_incumbent_brier,
            "market_brier": reference_market_brier,
            "gap": reference_gap,
            "realized_band_zeros": original_zeros,
        },
        "served_floor": {
            "incumbent_brier": rescored_brier,
            "market_brier": reference_market_brier,
            "gap": rescored_gap,
            "realized_band_zeros": rescored_zeros,
            "original_zeros_surviving": surviving_original_zeros,
        },
        "change": {
            "incumbent_brier": paired_brier_delta,
            "gap": paired_brier_delta,
            "direction": "BETTER" if paired_brier_delta < 0.0 else ("WORSE" if paired_brier_delta > 0.0 else "IDENTICAL"),
            "snapshot_rows_changed_at_all_binary64": changed_snapshots,
            "band_rows_changed_at_all_binary64": changed_band_rows,
            "max_absolute_probability_change": max_absolute_probability_change,
        },
        "control": {
            "binary64_identical": changed_band_rows == 0,
            "comparison": seed["comparison"]["probability_identity"],
            "portable_baseline_max_absolute_probability_difference_from_retained": (
                max_baseline_probability_difference_from_retained
            ),
            "portable_baseline_probability_tolerance": portable_tolerance,
        },
        "portable_numeric_diagnostics": {
            "retained_incumbent_brier_recomputed": original_brier,
            "portable_baseline_brier": baseline_brier,
            "portable_served_floor_brier_direct": direct_rescored_brier,
            "paired_delta_applied_to_retained_reference": paired_brier_delta,
        },
    }
    return result, rescored_rows, snapshot_rows, {
        "model_identities": model_identities,
        "replay_input_receipts": input_receipts,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    require(rows, f"refusing to write empty CSV: {path}")
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed_path = args.seed.resolve()
    output_dir = args.output_dir.resolve()
    require(seed_path.is_file(), f"missing seed: {seed_path}")
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    require(seed.get("schema_version") == "served_floor_rescore_seed_v1", "seed schema drifted")
    require(not output_dir.exists(), f"refusing to overwrite evidence directory: {output_dir}")
    output_dir.mkdir(parents=True)
    receipts = verify_seeded_files(seed)
    method, transform = compile_diagnostic_method(seed)
    snapshots, support = load_panel(seed)
    cell_receipts = load_receipts(seed, snapshots)

    # C is the fail-fast control. B is not processed unless every C probability is byte-identical.
    c_result, c_bands, c_snapshots, c_provenance = process_stratum(
        "C", snapshots, cell_receipts, method, seed
    )
    if not c_result["control"]["binary64_identical"]:
        failure = {
            "schema_version": "served_floor_rescore_result_v1",
            "status": "STOP_C_CONTROL_MOVED",
            "mission": seed["mission"],
            "C": c_result,
            "B": "NOT_READ_OR_SCORED",
            "support": support,
            "transform": transform,
            "campaign": seed["campaign"],
        }
        write_json(output_dir / "control-failure.json", failure)
        print(json.dumps(failure, indent=2, sort_keys=True))
        return 2

    b_result, b_bands, b_snapshots, b_provenance = process_stratum(
        "B", snapshots, cell_receipts, method, seed
    )
    band_path = output_dir / "rescored-band-rows.csv"
    snapshot_path = output_dir / "rescored-snapshot-rows.csv"
    write_csv(band_path, b_bands + c_bands)
    write_csv(snapshot_path, b_snapshots + c_snapshots)
    result = {
        "schema_version": "served_floor_rescore_result_v1",
        "status": "PASS",
        "mission": seed["mission"],
        "interpretation": {
            "kind": "diagnostic_rescore_not_candidate_or_correction",
            "fitted_parameter": False,
            "accept_rule": False,
            "promotion_or_redecision_licensed": False,
            "C_access": "control re-score only; no candidate, fitted parameter, or accept rule",
            "pooled_across_2026_07_31": False,
        },
        "campaign": seed["campaign"],
        "support": support,
        "C": c_result,
        "B": b_result,
        "transform": transform,
        "provenance": {
            "seed_path": str(seed_path),
            "seed_sha256": sha256(seed_path),
            "pinned_receipts": receipts,
            "C": c_provenance,
            "B": b_provenance,
        },
        "outputs": {
            "rescored_band_rows": {
                "path": str(band_path),
                "sha256": sha256(band_path),
                "rows": len(b_bands) + len(c_bands),
            },
            "rescored_snapshot_rows": {
                "path": str(snapshot_path),
                "sha256": sha256(snapshot_path),
                "rows": len(b_snapshots) + len(c_snapshots),
            },
        },
        "explicitly_not_done": [
            "no candidate, fitted parameter, accept rule, alpha allocation, promotion, or re-decision",
            "no replay, floor, model, calibration, serving, or scoring source file changed",
            "no production write, registration, restart, merge, provider call, or exchange action",
            "serving floor was not weakened",
        ],
    }
    summary_path = output_dir / "summary.json"
    write_json(summary_path, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except IntegrityFailure as exc:
        print(json.dumps({"status": "INTEGRITY_FAILURE", "error": str(exc)}, indent=2))
        raise SystemExit(3) from exc

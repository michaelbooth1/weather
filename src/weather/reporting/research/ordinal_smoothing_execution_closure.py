"""Execution closure and research-only model factory for physical H1 replay."""

from __future__ import annotations

import hashlib
import json
import time
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from weather.execution_identity import (
    ClosureSpec,
    EnvironmentSpec,
    ExecutionIdentityError,
    ExecutionIdentityManifest,
    InvocationSpec,
    PathBinding,
    TreeBinding,
)
from weather.reporting.research.ordinal_smoothing_physical_refinement import (
    FIXED_BLEND_WEIGHT,
    native_sigma,
)
from weather.reporting.research.ordinal_smoothing_physical_replay import (
    UNITS,
    compact_scoring_row,
)


RESEARCH_GRAPH_KIND = "RESEARCH_UNBOUND"
CURRENT_POINTER_PATHS = (
    Path("artifacts/releases/current_release.json"),
    Path("artifacts/immutable/releases/current_release.json"),
)
DEFAULT_IMPORT_NAMES = (
    "numpy",
    "pandas",
    "scipy",
    "sklearn",
    "weather",
    "weather.backtesting.replay",
    "weather.backtesting.replay_backtest",
    "weather.execution_identity",
    "weather.model.toronto_model",
    "weather.reporting.research.ordinal_smoothing_execution_closure",
    "weather.reporting.research.ordinal_smoothing_physical_refinement",
    "weather.reporting.research.ordinal_smoothing_physical_replay",
)


class ClosureConfigurationError(ValueError):
    """Raised when the exact replay-input closure cannot be constructed."""


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def research_smoothing_config(
    physical_c_sigma_by_family: Mapping[str, float] | None, unit: str
) -> dict[str, Any]:
    normalized = str(unit).upper()
    if normalized not in UNITS:
        raise ClosureConfigurationError(f"unsupported settlement unit: {unit!r}")
    if physical_c_sigma_by_family is None:
        return {
            "enabled": False,
            "sigma": 0.0,
            "blend_weight": 0.0,
            "source": "research_explicit_w0",
            "model_graph": RESEARCH_GRAPH_KIND,
        }
    if set(physical_c_sigma_by_family) != set(UNITS):
        raise ClosureConfigurationError("candidate sigma mapping must contain exactly C and F")
    physical = float(physical_c_sigma_by_family[normalized])
    if physical <= 0.0:
        raise ClosureConfigurationError("physical-C sigma must be positive")
    return {
        "enabled": True,
        "sigma": native_sigma(physical, normalized),
        "blend_weight": FIXED_BLEND_WEIGHT,
        "source": "research_physical_sigma_closure_bound",
        "model_graph": RESEARCH_GRAPH_KIND,
        "physical_c_sigma": physical,
        "native_unit": normalized,
    }


def research_replay_model_version(
    base_version: str,
    physical_c_sigma_by_family: Mapping[str, float] | None,
) -> str:
    """Give an intentional candidate transform a distinct replay identity."""

    if physical_c_sigma_by_family is None:
        return str(base_version)
    if set(physical_c_sigma_by_family) != set(UNITS):
        raise ClosureConfigurationError("candidate sigma mapping must contain exactly C and F")
    identity = {
        "model_graph": RESEARCH_GRAPH_KIND,
        "physical_c_sigma_by_family": {
            unit: float(physical_c_sigma_by_family[unit]) for unit in UNITS
        },
        "native_sigma_by_family": {
            unit: native_sigma(float(physical_c_sigma_by_family[unit]), unit)
            for unit in UNITS
        },
        "blend_weight": FIXED_BLEND_WEIGHT,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"{base_version}+research-h1-physical-{digest}"


def make_research_model_factory(
    physical_c_sigma_by_family: Mapping[str, float] | None,
) -> Callable[[str], Any]:
    from weather.market.market_registry import spec_for_id
    from weather.model.toronto_model import TorontoHighTempModel
    from weather.release_serving import STATUS_RESEARCH_UNBOUND, VerifiedServingBundle

    frozen_mapping = (
        None
        if physical_c_sigma_by_family is None
        else {unit: float(physical_c_sigma_by_family[unit]) for unit in UNITS}
    )

    class ResearchClosureBoundModel(TorontoHighTempModel):
        def feature_ordinal_smoothing_config(self, cutoff_hour):
            del cutoff_hour
            unit = str(spec_for_id(self.market_id).display_unit).upper()
            return research_smoothing_config(frozen_mapping, unit)

        def get_model_version_string(self):
            return research_replay_model_version(
                super().get_model_version_string(), frozen_mapping
            )

    research_bundle = VerifiedServingBundle(
        status=STATUS_RESEARCH_UNBOUND,
        reason="execution-closure-bound ordinal smoothing research",
        pointer_present=False,
    )
    return lambda market_id: ResearchClosureBoundModel(
        market_id=market_id,
        serving_bundle=research_bundle,
    )


def _finite_json_value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {str(key): _finite_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json_value(item) for item in value]
    return value


def _daily_summary_path(staged_data_root: Path, market_id: str) -> Path:
    from weather.market.market_registry import spec_for_id

    spec = spec_for_id(market_id)
    return staged_data_root / "wunderground" / spec.icao.lower() / "daily" / "daily_summary.csv"


def _unit_for_market(market_id: str) -> str:
    from weather.market.market_registry import spec_for_id

    return str(spec_for_id(market_id).display_unit).upper()


def run_partition_arm(
    *,
    partition: str,
    arm_name: str,
    folders: Sequence[Path],
    corpus_manifest: Mapping[str, Any],
    staged_data_root: Path,
    scratch_output_root: Path,
    physical_c_sigma_by_family: Mapping[str, float] | None,
) -> dict[str, Any]:
    from weather.backtesting.replay_backtest import (
        FIDELITY_FAITHFUL_L1,
        run_replay_backtest,
    )

    started = time.perf_counter()
    results = run_replay_backtest(
        [str(folder) for folder in folders],
        daily_summary_path=None,
        overrides={},
        out_path=str(scratch_output_root / f"unused-{arm_name}.md"),
        include_reconstructed=False,
        write=False,
        corpus_manifest=corpus_manifest,
        model_factory=make_research_model_factory(physical_c_sigma_by_family),
        daily_summary_resolver=lambda market_id: _daily_summary_path(
            staged_data_root, market_id
        ),
        include_distribution_rows=True,
    )
    blockers = []
    if not results.get("snaps_scored"):
        blockers.append("no snapshots scored")
    if results.get("snaps_scored") != results.get("snaps_in_corpus"):
        blockers.append(
            "not every admitted snapshot produced a distribution "
            f"({results.get('snaps_scored')}/{results.get('snaps_in_corpus')})"
        )
    blockers.extend(
        f"corpus warning: {warning}" for warning in (results.get("corpus_warnings") or [])
    )
    fidelity = dict(results.get("fidelity") or {})
    intentional_candidate = physical_c_sigma_by_family is not None
    fidelity_semantics = {
        "role": (
            "intentional_candidate_transform"
            if intentional_candidate
            else "captured_identity_baseline_canary"
        ),
        "same_identity_required": not intentional_candidate,
        "same_identity_forbidden": intentional_candidate,
        "faithful_mean_l1_threshold": FIDELITY_FAITHFUL_L1,
        "observed_same_identity_n": fidelity.get("same_identity_n"),
        "observed_same_identity_mean_l1": fidelity.get("same_identity_mean_l1"),
        "observed_same_identity_max_l1": fidelity.get("same_identity_max_l1"),
    }
    if intentional_candidate and fidelity.get("same_identity_n"):
        blockers.append(
            "intentional candidate transform retained captured replay identity"
        )
    elif (
        not intentional_candidate
        and fidelity.get("same_identity_n")
        and not fidelity.get("same_identity_faithful")
    ):
        blockers.append("same-identity replay fidelity canary failed")
    rows = []
    for source in results.get("all_rows") or []:
        row = dict(source)
        row["unit"] = _unit_for_market(str(row.get("market_id") or ""))
        rows.append(_finite_json_value(compact_scoring_row(row)))
    distributions = []
    for source in results.get("distribution_rows") or []:
        row = dict(source)
        row["unit"] = _unit_for_market(str(row.get("market_id") or ""))
        distributions.append(_finite_json_value(row))
    physical = (
        {}
        if physical_c_sigma_by_family is None
        else {unit: float(physical_c_sigma_by_family[unit]) for unit in UNITS}
    )
    native = {
        unit: native_sigma(physical[unit], unit) for unit in UNITS if unit in physical
    }
    return {
        "partition": partition,
        "arm_name": arm_name,
        "model_graph": RESEARCH_GRAPH_KIND,
        "physical_c_sigma_by_family": physical,
        "native_sigma_by_family": native,
        "blend_weight": 0.0 if physical_c_sigma_by_family is None else FIXED_BLEND_WEIGHT,
        "rows": rows,
        "distribution_rows": distributions,
        "replay": {
            "snaps_in_corpus": results.get("snaps_in_corpus"),
            "snaps_scored": results.get("snaps_scored"),
            "total_rows": results.get("total_rows"),
            "runtime_seconds": time.perf_counter() - started,
            "replayed_versions": results.get("replayed_versions") or [],
            "fidelity": fidelity,
            "fidelity_semantics": fidelity_semantics,
            "band_semantics": results.get("band_semantics") or {},
            "corpus_warnings": results.get("corpus_warnings") or [],
            "blockers": blockers,
        },
    }


def _entry_key(entry: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry.get("market_id") or ""),
        str(entry.get("target_date") or ""),
        str(entry.get("event_slug") or ""),
    )


def build_replay_closure_spec(
    *,
    name: str,
    repo_root: Path,
    staged_data_root: Path,
    snapshots_root: Path,
    corpus_path: Path,
    entries: Sequence[Mapping[str, Any]],
    invocation: InvocationSpec,
    required_contract_files: Iterable[tuple[str, Path]] = (),
    environment: EnvironmentSpec | None = None,
) -> ClosureSpec:
    repo_root = Path(repo_root).resolve(strict=True)
    staged_data_root = Path(staged_data_root).resolve(strict=True)
    snapshots_root = Path(snapshots_root).resolve(strict=True)
    corpus_path = Path(corpus_path).resolve(strict=True)
    if not _is_within(snapshots_root, staged_data_root):
        raise ClosureConfigurationError("snapshots root must remain below staged data root")
    if not entries:
        raise ClosureConfigurationError("execution closure requires nonempty corpus entries")
    keys = [_entry_key(entry) for entry in entries]
    if any(not all(key) for key in keys) or len(keys) != len(set(keys)):
        raise ClosureConfigurationError("corpus entries need unique market/date/slug identity")
    entries_by_key = {_entry_key(entry): entry for entry in entries}

    path_bindings = [
        PathBinding("partition_corpus", corpus_path, "required_file"),
        *(
            PathBinding(f"contract:{label}", Path(path), "required_file")
            for label, path in required_contract_files
        ),
        *(
            PathBinding(f"release_pointer_absent:{index}", repo_root / relative, "absent")
            for index, relative in enumerate(CURRENT_POINTER_PATHS, start=1)
        ),
    ]
    tree_bindings = [
        TreeBinding(
            "canonical_source",
            repo_root / "src" / "weather",
            ("**/*",),
            ("**/__pycache__/**", "**/*.pyc"),
        ),
        TreeBinding("artifact_graph", repo_root / "artifacts"),
        TreeBinding("configuration_graph", repo_root / "config"),
    ]
    for market_id, target_date, event_slug in sorted(keys):
        entry = entries_by_key[(market_id, target_date, event_slug)]
        relative = str(entry.get("folder_relative_to_snapshots_root") or "")
        if not relative:
            raise ClosureConfigurationError(f"entry has no relative snapshot folder: {event_slug}")
        declared_folder = (snapshots_root / relative).resolve(strict=True)
        if not _is_within(declared_folder, snapshots_root):
            raise ClosureConfigurationError(
                f"snapshot folder escapes root: {declared_folder}"
            )
        if relative != event_slug:
            raise ClosureConfigurationError(
                f"entry folder identity differs from replay event slug: {event_slug}"
            )
        folder = (snapshots_root / event_slug).resolve(strict=True)
        if not _is_within(folder, snapshots_root):
            raise ClosureConfigurationError(f"snapshot folder escapes root: {folder}")
        label = f"{target_date}:{market_id}:{event_slug}"
        tree_bindings.append(TreeBinding(f"snapshot_tree:{label}", folder))
        path_bindings.extend(
            (
                PathBinding(
                    f"captured_replay:{label}",
                    folder / "replay_inputs.jsonl",
                    "required_file",
                ),
                PathBinding(
                    f"reconstructed_replay:{label}",
                    folder / "replay_inputs_reconstructed.jsonl",
                    "file_or_absent",
                ),
                PathBinding(
                    f"snapshot_tape_jsonl:{label}",
                    folder / "snapshots.jsonl",
                    "required_file",
                ),
                PathBinding(
                    f"snapshot_tape_long:{label}",
                    folder / "snapshots_long.csv",
                    "required_file",
                ),
            )
        )

    from weather.market.market_registry import spec_for_id

    for market_id in sorted({key[0] for key in keys}):
        spec = spec_for_id(market_id)
        wu_root = staged_data_root / "wunderground" / spec.icao.lower()
        path_bindings.append(
            PathBinding(
                f"wu_daily:{market_id}",
                wu_root / "daily" / "daily_summary.csv",
                "required_file",
            )
        )
        tree_bindings.append(
            TreeBinding(
                f"wu_hourly:{market_id}",
                wu_root / "hourly",
                ("year=*/month=*/observations.jsonl",),
            )
        )
    selected_environment = environment or EnvironmentSpec(
        import_names=DEFAULT_IMPORT_NAMES,
        env_prefixes=("WEATHER_",),
        include_packages=True,
    )
    return ClosureSpec(
        name=name,
        base_root=repo_root,
        invocation=invocation,
        path_bindings=tuple(path_bindings),
        tree_bindings=tuple(tree_bindings),
        environment=selected_environment,
    )


def execution_lineage(manifest: ExecutionIdentityManifest) -> dict[str, Any]:
    bindings = {row["label"]: row for row in manifest.identity["bindings"]}
    pointer_rows = [
        row for label, row in bindings.items() if label.startswith("release_pointer_absent:")
    ]
    return {
        "model_graph": RESEARCH_GRAPH_KIND,
        "execution_identity_digest": manifest.identity_digest,
        "source_digest": bindings["canonical_source"]["tree_digest"],
        "artifact_digest": bindings["artifact_graph"]["tree_digest"],
        "configuration_digest": bindings["configuration_graph"]["tree_digest"],
        "current_release_pointers": [
            {"path": row["path"], "state": row["state"]} for row in pointer_rows
        ],
        "active_or_current_production_claimed": False,
    }


__all__ = [
    "ClosureConfigurationError",
    "CURRENT_POINTER_PATHS",
    "DEFAULT_IMPORT_NAMES",
    "RESEARCH_GRAPH_KIND",
    "build_replay_closure_spec",
    "execution_lineage",
    "make_research_model_factory",
    "research_smoothing_config",
    "run_partition_arm",
]

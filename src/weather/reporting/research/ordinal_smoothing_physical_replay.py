"""Research-only tune replay for physically comparable ordinal bandwidths.

The implementation is deliberately separate from the finalized H1 sweep.  An
opt-in model subclass overrides only the existing smoothing-config hook for the
replay process: C markets use the preregistered physical-C sigma and F markets
use 1.8 times that value.  Production defaults and artifacts are never edited.
Only the original H1 tune folders are passed to replay; no holdout/fresh cache,
folder, or outcome is a command input.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.research.current_replay_time_frontier import (
    iter_cache_array,
    read_cache_metadata,
    sha256_stable_file,
)
from weather.reporting.research.ordinal_smoothing_physical_refinement import (
    FIXED_BLEND_WEIGHT,
    PHYSICAL_C_SIGMA_ANCHORS,
    native_sigma,
    select_family_sigmas,
)
from weather.reporting.research.ordinal_smoothing_sweep import (
    alignment_gate,
    analyze_weight_zero_control,
    folders_for_entries,
    mass_gate,
    paired_fleet_date_rows,
    paired_summary,
    scope_effect_audit,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("ordinal_smoothing_physical_replay")
H1_SCHEMA_VERSION = schema_version("ordinal_smoothing_sweep")
UNITS = ("C", "F")
DETERMINISM_CANARY_DATE = "2026-06-21"
MAX_RESULT_BYTES = 100 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_COMPACT_CACHE_BYTES = 1024 * 1024 * 1024
MAX_PROJECTED_MINUTES = 240.0
MAX_PROJECTED_BYTES = 25 * 1024**3
MEASURED_MINUTES_PER_ARM = 25.0
# Conservative per-arm cap for scoring projections plus final distributions.
PROJECTED_COMPACT_BYTES_PER_ARM = MAX_COMPACT_CACHE_BYTES


class ExperimentConfigurationError(ValueError):
    """Raised when the tune-only replay cannot satisfy a safety/evidence gate."""


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def validate_paths(
    *,
    mirror_data_root: str | Path,
    staged_data_root: str | Path,
    snapshots_root: str | Path,
    corpus_path: str | Path,
    h1_result_path: str | Path,
    tune_dates_path: str | Path,
    baseline_cache_path: str | Path,
    determinism_cache_path: str | Path,
    output_root: str | Path,
    cache_root: str | Path,
    json_out: str | Path,
    report_out: str | Path,
    lock_path: str | Path,
) -> dict[str, Path]:
    paths = {
        name: _resolved(value)
        for name, value in {
            "mirror_data_root": mirror_data_root,
            "staged_data_root": staged_data_root,
            "snapshots_root": snapshots_root,
            "corpus_path": corpus_path,
            "h1_result_path": h1_result_path,
            "tune_dates_path": tune_dates_path,
            "baseline_cache_path": baseline_cache_path,
            "determinism_cache_path": determinism_cache_path,
            "output_root": output_root,
            "cache_root": cache_root,
            "json_out": json_out,
            "report_out": report_out,
            "lock_path": lock_path,
        }.items()
    }
    for name in ("mirror_data_root", "staged_data_root", "snapshots_root"):
        if not paths[name].is_dir():
            raise ExperimentConfigurationError(f"required input directory is missing: {paths[name]}")
    if not _is_within(paths["snapshots_root"], paths["mirror_data_root"]):
        raise ExperimentConfigurationError("snapshots_root must remain below mirror_data_root")
    for name in (
        "corpus_path",
        "h1_result_path",
        "tune_dates_path",
        "baseline_cache_path",
        "determinism_cache_path",
    ):
        if not paths[name].is_file():
            raise ExperimentConfigurationError(f"required input file is missing: {paths[name]}")
    outputs = (paths["cache_root"], paths["json_out"], paths["report_out"], paths["lock_path"])
    if len(set(outputs)) != len(outputs):
        raise ExperimentConfigurationError("cache, JSON, report, and lock paths must be distinct")
    for path in outputs:
        if not _is_within(path, paths["output_root"]):
            raise ExperimentConfigurationError(f"output escapes explicit output_root: {path}")
        if _is_within(path, paths["mirror_data_root"]) or _is_within(
            path, paths["staged_data_root"]
        ):
            raise ExperimentConfigurationError(f"research output aliases read-only data: {path}")
    projected_minutes = len(PHYSICAL_C_SIGMA_ANCHORS) * MEASURED_MINUTES_PER_ARM
    projected_bytes = len(PHYSICAL_C_SIGMA_ANCHORS) * PROJECTED_COMPACT_BYTES_PER_ARM
    if projected_minutes > MAX_PROJECTED_MINUTES or projected_bytes > MAX_PROJECTED_BYTES:
        raise ExperimentConfigurationError("preregistered replay exceeds the explicit time/disk envelope")
    return paths


def read_dates(path: str | Path) -> tuple[str, ...]:
    values = tuple(
        line.strip()
        for line in _resolved(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if not values or len(values) != len(set(values)) or tuple(sorted(values)) != values:
        raise ExperimentConfigurationError("tune dates must be nonempty, unique, and sorted")
    for value in values:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ExperimentConfigurationError(f"invalid tune date: {value!r}") from exc
    return values


def family_smoothing_config(physical_c_sigma: float, market_id: str) -> dict[str, Any]:
    from weather.market.market_registry import spec_for_id

    unit = str(spec_for_id(market_id).display_unit).upper()
    return {
        "enabled": True,
        "sigma": native_sigma(physical_c_sigma, unit),
        "blend_weight": FIXED_BLEND_WEIGHT,
        "source": "research_physical_sigma_tune_only",
        "physical_c_sigma": float(physical_c_sigma),
        "native_unit": unit,
    }


def make_family_model_factory(physical_c_sigma: float) -> Callable[[str], Any]:
    # Validate the preregistration before lazy model import or data access.
    if physical_c_sigma not in PHYSICAL_C_SIGMA_ANCHORS:
        raise ExperimentConfigurationError(
            f"physical sigma is outside the preregistered grid: {physical_c_sigma}"
        )
    from weather.model.toronto_model import TorontoHighTempModel

    class ResearchPhysicalSigmaModel(TorontoHighTempModel):
        def feature_ordinal_smoothing_config(self, cutoff_hour):
            del cutoff_hour
            return family_smoothing_config(physical_c_sigma, self.market_id)

    return lambda market_id: ResearchPhysicalSigmaModel(market_id=market_id)


def _daily_summary_path(staged_data_root: Path, market_id: str) -> Path:
    from weather.market.market_registry import spec_for_id

    spec = spec_for_id(market_id)
    return staged_data_root / "wunderground" / spec.icao.lower() / "daily" / "daily_summary.csv"


def _unit_for_market(market_id: str) -> str:
    from weather.market.market_registry import spec_for_id

    return str(spec_for_id(market_id).display_unit).upper()


def configure_staged_data_root(staged_data_root: Path) -> None:
    import weather.paths as weather_paths

    weather_paths.DATA_ROOT = staged_data_root
    from weather.model.toronto_model import TorontoHighTempModel

    TorontoHighTempModel._historical_target_cache.clear()


def validate_staged_daily_inputs(
    entries: Iterable[Mapping[str, Any]], staged_data_root: Path
) -> None:
    market_ids = sorted({str(entry.get("market_id") or "") for entry in entries})
    if not market_ids or any(not value for value in market_ids):
        raise ExperimentConfigurationError("tune entries must declare market_id")
    for market_id in market_ids:
        daily = _daily_summary_path(staged_data_root, market_id).resolve(strict=True)
        if not _is_within(daily, staged_data_root):
            raise ExperimentConfigurationError(f"daily summary escapes staged root: {daily}")
        with daily.open("rb") as handle:
            handle.read(1)
        hourly_root = daily.parents[1] / "hourly"
        hourly = next(hourly_root.glob("year=*/month=*/observations.jsonl"), None)
        if hourly is None or not hourly.is_file():
            raise ExperimentConfigurationError(f"historical target input is missing: {hourly_root}")
        with hourly.open("rb") as handle:
            handle.read(1)


def load_tune_manifest(
    corpus_path: Path, tune_dates: Sequence[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if corpus_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ExperimentConfigurationError("corpus manifest exceeds safety bound")
    from weather.reporting.promotion.promotion_corpus import load_manifest

    manifest = load_manifest(corpus_path)
    tune_set = set(tune_dates)
    tune_entries = [
        dict(entry)
        for entry in (manifest.get("entries") or [])
        if str(entry.get("target_date")) in tune_set
    ]
    observed = {str(entry.get("target_date")) for entry in tune_entries}
    if observed != tune_set or not tune_entries:
        raise ExperimentConfigurationError("manifest does not exactly cover every tune date")
    keys = [
        (entry.get("market_id"), entry.get("target_date"), entry.get("event_slug"))
        for entry in tune_entries
    ]
    if len(keys) != len(set(keys)):
        raise ExperimentConfigurationError("tune manifest contains duplicate market-date slugs")
    # Replay receives only this object; non-tune settlement labels are unavailable.
    tune_manifest = {
        key: value for key, value in manifest.items() if key not in {"entries", "skipped"}
    }
    tune_manifest["entries"] = tune_entries
    tune_manifest["skipped"] = []
    tune_manifest["source_corpus_hash"] = manifest.get("corpus_hash")
    return tune_manifest, tune_entries


def compact_scoring_row(row: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "market_id", "target_date", "snapshot_id", "captured_at_local",
        "band", "bin_type", "bin_value_c", "bin_value_hi", "replayed_p",
        "outcome", "market_yes", "unit",
    )
    return {field: row.get(field) for field in fields}


def load_compact_h1_arm(path: Path, *, expected_split: str, expected_weight: float) -> dict[str, Any]:
    metadata = read_cache_metadata(path)
    if metadata.split != expected_split or metadata.weight != expected_weight:
        raise ExperimentConfigurationError(
            f"unexpected H1 cache metadata: split={metadata.split}, weight={metadata.weight}"
        )
    distributions = list(iter_cache_array(path, "distribution_rows"))
    rows = []
    for source in iter_cache_array(path, "rows"):
        row = compact_scoring_row(source)
        row["unit"] = str(row.get("unit") or "").upper()
        rows.append(row)
    return {
        "split": expected_split,
        "weight": expected_weight,
        "rows": rows,
        "distribution_rows": distributions,
        "metadata": metadata.as_dict(),
    }


def streaming_determinism_gate(
    baseline_path: Path, control_path: Path
) -> dict[str, Any]:
    baseline = {"rows": [], "distribution_rows": [], "replay": {"blockers": []}}
    control = {"rows": [], "distribution_rows": [], "replay": {"blockers": []}}
    for source in iter_cache_array(baseline_path, "distribution_rows"):
        if str(source.get("target_date")) == DETERMINISM_CANARY_DATE:
            baseline["distribution_rows"].append(source)
    for source in iter_cache_array(control_path, "distribution_rows"):
        if str(source.get("target_date")) != DETERMINISM_CANARY_DATE:
            raise ExperimentConfigurationError("determinism cache contains a non-canary date")
        control["distribution_rows"].append(source)
    for source in iter_cache_array(baseline_path, "rows"):
        if str(source.get("target_date")) == DETERMINISM_CANARY_DATE:
            baseline["rows"].append(compact_scoring_row(source))
    for source in iter_cache_array(control_path, "rows"):
        if str(source.get("target_date")) != DETERMINISM_CANARY_DATE:
            raise ExperimentConfigurationError("determinism cache contains a non-canary date")
        control["rows"].append(compact_scoring_row(source))
    gate = analyze_weight_zero_control(baseline, control)
    if gate.get("blockers"):
        raise ExperimentConfigurationError(
            "W0 determinism gate failed: " + "; ".join(gate["blockers"])
        )
    return dict(gate.get("evidence") or {})


def run_physical_arm(
    *,
    physical_c_sigma: float,
    folders: Sequence[Path],
    tune_manifest: Mapping[str, Any],
    staged_data_root: Path,
    cache_root: Path,
) -> dict[str, Any]:
    from weather.backtesting.replay_backtest import run_replay_backtest

    started = time.perf_counter()
    results = run_replay_backtest(
        [str(folder) for folder in folders],
        daily_summary_path=None,
        overrides={},
        out_path=str(cache_root / f"unused-physical-{physical_c_sigma}.md"),
        include_reconstructed=False,
        write=False,
        corpus_manifest=tune_manifest,
        model_factory=make_family_model_factory(physical_c_sigma),
        daily_summary_resolver=lambda market_id: _daily_summary_path(
            staged_data_root, market_id
        ),
        include_distribution_rows=True,
    )
    replay_blockers = []
    if not results.get("snaps_scored"):
        replay_blockers.append("no snapshots scored")
    if results.get("snaps_scored") != results.get("snaps_in_corpus"):
        replay_blockers.append(
            "not every admitted snapshot produced a distribution "
            f"({results.get('snaps_scored')}/{results.get('snaps_in_corpus')})"
        )
    replay_blockers.extend(
        f"corpus warning: {warning}" for warning in (results.get("corpus_warnings") or [])
    )
    fidelity = results.get("fidelity") or {}
    if fidelity.get("same_identity_n") and not fidelity.get("same_identity_faithful"):
        replay_blockers.append("same-identity replay fidelity canary failed")
    rows = []
    for source in results.get("all_rows") or []:
        row = dict(source)
        row["unit"] = _unit_for_market(str(row.get("market_id") or ""))
        rows.append(compact_scoring_row(row))
    distributions = []
    for source in results.get("distribution_rows") or []:
        row = dict(source)
        row["unit"] = _unit_for_market(str(row.get("market_id") or ""))
        distributions.append(row)
    return {
        "split": "tune",
        "physical_c_sigma": float(physical_c_sigma),
        "native_sigma_by_family": {
            unit: native_sigma(physical_c_sigma, unit) for unit in UNITS
        },
        "blend_weight": FIXED_BLEND_WEIGHT,
        "rows": rows,
        "distribution_rows": distributions,
        "replay": {
            "snaps_in_corpus": results.get("snaps_in_corpus"),
            "snaps_scored": results.get("snaps_scored"),
            "total_rows": results.get("total_rows"),
            "runtime_seconds": time.perf_counter() - started,
            "replayed_versions": results.get("replayed_versions") or [],
            "fidelity": fidelity,
            "band_semantics": results.get("band_semantics") or {},
            "corpus_warnings": results.get("corpus_warnings") or [],
            "blockers": replay_blockers,
        },
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def code_digest_paths() -> tuple[Path, ...]:
    """Return a conservative closure of canonical code that can affect replay.

    The replay stack has broad and evolving transitive imports.  A hand-maintained
    dependency list risks silently accepting a cache produced by different code,
    so this bounded research job intentionally over-invalidates on *any* change
    below ``src/weather``.  Paths are ordered by repository-relative name.
    """
    repository_root = _repository_root()
    weather_source_root = repository_root / "src" / "weather"
    paths = tuple(path.resolve() for path in weather_source_root.rglob("*.py"))
    if not paths:
        raise ExperimentConfigurationError(
            f"canonical weather source closure is empty: {weather_source_root}"
        )
    return tuple(sorted(paths, key=lambda path: path.relative_to(repository_root).as_posix()))


def digest_files(paths: Iterable[Path], *, relative_to: Path | None = None) -> str:
    base = Path(relative_to).resolve(strict=True) if relative_to is not None else None
    labeled_paths = []
    for item in paths:
        path = Path(item).resolve(strict=True)
        label = path.relative_to(base).as_posix() if base is not None else path.as_posix()
        labeled_paths.append((label, path))
    digest = hashlib.sha256()
    for label, path in sorted(labeled_paths):
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def code_digest() -> str:
    return digest_files(code_digest_paths(), relative_to=_repository_root())


def require_unchanged_code_digest(expected: str) -> str:
    observed = code_digest()
    if observed != expected:
        raise ExperimentConfigurationError(
            "canonical src/weather code changed while physical replay was active; "
            "discard this mixed-code attempt and rerun with the new digest"
        )
    return observed


def cache_fingerprint(
    *,
    physical_c_sigma: float,
    tune_manifest: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    code_hash: str,
    baseline_sha256: str,
) -> str:
    contract = {
        "schema_version": SCHEMA_VERSION,
        "physical_c_sigma": physical_c_sigma,
        "native_sigma_by_family": {
            unit: native_sigma(physical_c_sigma, unit) for unit in UNITS
        },
        "blend_weight": FIXED_BLEND_WEIGHT,
        "source_corpus_hash": tune_manifest.get("source_corpus_hash"),
        "entries": [
            {
                "event_slug": entry.get("event_slug"),
                "target_date": entry.get("target_date"),
                "market_id": entry.get("market_id"),
                "snapshot_ids": entry.get("snapshot_ids") or [],
            }
            for entry in entries
        ],
        "code_digest": code_hash,
        "baseline_sha256": baseline_sha256,
    }
    return hashlib.sha256(_canonical_json(contract).encode("utf-8")).hexdigest()


def _sigma_token(value: float) -> str:
    return f"{float(value):.2f}".replace(".", "p")


def _atomic_json(path: Path, payload: Mapping[str, Any], *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            separators=(",", ":") if compact else None,
            indent=None if compact else 2,
            sort_keys=True,
        )
        handle.write("\n")
    os.replace(temporary, path)


def load_or_run_arm(
    *,
    physical_c_sigma: float,
    folders: Sequence[Path],
    tune_manifest: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    staged_data_root: Path,
    cache_root: Path,
    code_hash: str,
    baseline_sha256: str,
    resume: bool,
) -> tuple[dict[str, Any], Path, str]:
    path = cache_root / f"tune-physical-c-sigma-{_sigma_token(physical_c_sigma)}.json"
    fingerprint = cache_fingerprint(
        physical_c_sigma=physical_c_sigma,
        tune_manifest=tune_manifest,
        entries=entries,
        code_hash=code_hash,
        baseline_sha256=baseline_sha256,
    )
    if path.exists():
        if not resume:
            raise ExperimentConfigurationError(f"candidate cache exists without --resume: {path}")
        if path.stat().st_size > MAX_COMPACT_CACHE_BYTES:
            raise ExperimentConfigurationError(f"candidate cache exceeds compact cap: {path}")
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if envelope.get("schema_version") != SCHEMA_VERSION:
            raise ExperimentConfigurationError(f"candidate cache schema mismatch: {path}")
        if envelope.get("fingerprint") != fingerprint:
            raise ExperimentConfigurationError(f"candidate cache fingerprint mismatch: {path}")
        return dict(envelope.get("arm") or {}), path, fingerprint
    arm = run_physical_arm(
        physical_c_sigma=physical_c_sigma,
        folders=folders,
        tune_manifest=tune_manifest,
        staged_data_root=staged_data_root,
        cache_root=cache_root,
    )
    _atomic_json(
        path,
        {"schema_version": SCHEMA_VERSION, "fingerprint": fingerprint, "arm": arm},
        compact=True,
    )
    if path.stat().st_size > MAX_COMPACT_CACHE_BYTES:
        raise ExperimentConfigurationError(f"candidate cache exceeds compact cap: {path}")
    return arm, path, fingerprint


def analyze_candidate(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any], physical_c_sigma: float
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    blockers = list((candidate.get("replay") or {}).get("blockers") or [])
    mass = mass_gate(candidate.get("distribution_rows") or [])
    alignment = alignment_gate(
        baseline.get("rows") or [], candidate.get("rows") or []
    )
    effect = scope_effect_audit(
        baseline.get("distribution_rows") or [],
        candidate.get("distribution_rows") or [],
    )
    blockers.extend(mass.get("blockers") or [])
    blockers.extend(alignment.get("blockers") or [])
    blockers.extend(effect.get("blockers") or [])
    if blockers:
        raise ExperimentConfigurationError(
            f"physical sigma {physical_c_sigma} gate failed: " + "; ".join(blockers)
        )
    summaries = {}
    for unit in UNITS:
        daily = paired_fleet_date_rows(
            baseline.get("rows") or [], candidate.get("rows") or [], unit
        )
        raw = paired_summary(
            daily, split="physical-tune", unit=unit, weight=physical_c_sigma
        )
        summary = dict(raw)
        summary["physical_c_sigma"] = float(physical_c_sigma)
        summary["native_sigma"] = native_sigma(physical_c_sigma, unit)
        summary["blend_weight"] = FIXED_BLEND_WEIGHT
        summary["mean_brier_delta_vs_w0"] = summary.pop("mean_brier_delta")
        summary["mean_logloss_delta_vs_w0"] = summary.pop("mean_logloss_delta")
        summaries[unit] = summary
    return {
        "status": "PASS",
        "mass": mass,
        "alignment": alignment,
        "scope_effect": effect,
        "replay": candidate.get("replay") or {},
        "blockers": [],
    }, summaries


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ExperimentConfigurationError(f"research lock already exists: {path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "pid": os.getpid(),
                    "started_at_utc": datetime.now(timezone.utc).isoformat(),
                    "schema_version": SCHEMA_VERSION,
                },
                handle,
                sort_keys=True,
            )
            handle.write("\n")
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def render_report(payload: Mapping[str, Any]) -> str:
    frozen = payload.get("frozen_candidate") or {}
    rows = []
    for unit in UNITS:
        selected = (payload.get("selected_physical_c_sigmas") or {}).get(unit)
        for summary in (payload.get("summaries") or {}).get(unit) or []:
            ci_brier = summary.get("brier_cluster_bootstrap_95ci") or {}
            ci_log = summary.get("logloss_cluster_bootstrap_95ci") or {}
            rows.append(
                [
                    unit,
                    summary.get("physical_c_sigma"),
                    summary.get("native_sigma"),
                    summary.get("fleet_dates"),
                    fmt_signed(summary.get("mean_brier_delta_vs_w0")),
                    f"[{fmt_signed(ci_brier.get('low'))}, {fmt_signed(ci_brier.get('high'))}]",
                    fmt_signed(summary.get("mean_logloss_delta_vs_w0")),
                    f"[{fmt_signed(ci_log.get('low'))}, {fmt_signed(ci_log.get('high'))}]",
                    fmt_signed(summary.get("mean_candidate_brier_delta_vs_market")),
                    "yes" if summary.get("physical_c_sigma") == selected else "",
                ]
            )
    lines = [
        "# H1 Physical-Bandwidth Tune Replay",
        "",
        "## Outcome",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Status", payload.get("status")],
                ["Disposition", payload.get("disposition")],
                ["Tune dates", len((payload.get("experiment") or {}).get("tune_dates") or [])],
                ["Candidate arms", len(PHYSICAL_C_SIGMA_ANCHORS)],
                ["Frozen C native sigma", (frozen.get("native_sigma_by_family") or {}).get("C")],
                ["Frozen F native sigma", (frozen.get("native_sigma_by_family") or {}).get("F")],
                ["Blend weight", frozen.get("blend_weight")],
                ["Holdout opened", payload.get("holdout_opened")],
                ["Fresh panel opened", payload.get("fresh_panel_opened")],
                ["Serving changed", payload.get("serving_changed")],
            ],
        ),
        "",
        "Physical-C anchors were preregistered before replay as "
        f"{', '.join(map(str, PHYSICAL_C_SIGMA_ANCHORS))}. Each arm fixed weight=1.0, "
        "used sigma_C=x and sigma_F=1.8*x, and replayed only the original H1 tune dates.",
        "",
        "## Tune Metrics",
        "",
        *markdown_table(
            [
                "Unit",
                "Physical C sigma",
                "Native sigma",
                "Dates",
                "Brier vs W0",
                "Brier 95% CI",
                "Log-loss vs W0",
                "Log-loss 95% CI",
                "Brier vs market",
                "Frozen",
            ],
            rows,
        ),
        "",
        "## Safety Boundary",
        "",
        "The model change existed only in an opt-in replay subclass overriding the "
        "existing smoothing-config hook. No serving default or model artifact changed. "
        "W0 determinism, simplex mass, row alignment, replay admission, and treatment "
        "effect gates passed before selection.",
        "",
        "This is tune evidence only. The frozen pair is at most a candidate for one "
        "future new-panel confirmation; it is not holdout support, market-edge evidence, "
        "a release, or promotion authority.",
        "",
    ]
    return "\n".join(lines)


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    paths = validate_paths(
        mirror_data_root=args.mirror_data_root,
        staged_data_root=args.staged_data_root,
        snapshots_root=args.snapshots_root,
        corpus_path=args.corpus,
        h1_result_path=args.h1_result,
        tune_dates_path=args.tune_dates_file,
        baseline_cache_path=args.baseline_cache,
        determinism_cache_path=args.determinism_cache,
        output_root=args.output_root,
        cache_root=args.cache_root,
        json_out=args.json_out,
        report_out=args.report_out,
        lock_path=args.lock_path,
    )
    for path in (paths["json_out"], paths["report_out"]):
        if path.exists():
            raise ExperimentConfigurationError(f"refusing to overwrite output: {path}")
    tune_dates = read_dates(paths["tune_dates_path"])
    if paths["h1_result_path"].stat().st_size > MAX_RESULT_BYTES:
        raise ExperimentConfigurationError("H1 result exceeds safety bound")
    h1_result = json.loads(paths["h1_result_path"].read_text(encoding="utf-8"))
    if (
        h1_result.get("schema_version") != H1_SCHEMA_VERSION
        or h1_result.get("status") != "COMPLETE"
        or (h1_result.get("tune") or {}).get("status") != "PASS"
        or tuple((h1_result.get("split") or {}).get("tune_dates") or ()) != tune_dates
    ):
        raise ExperimentConfigurationError("H1 result does not validate the exact tune partition")
    tune_manifest, entries = load_tune_manifest(paths["corpus_path"], tune_dates)
    folders = folders_for_entries(entries, paths["snapshots_root"])
    validate_staged_daily_inputs(entries, paths["staged_data_root"])
    configure_staged_data_root(paths["staged_data_root"])
    paths["cache_root"].mkdir(parents=True, exist_ok=True)

    baseline_stat = paths["baseline_cache_path"].stat()
    baseline_sha = sha256_stable_file(
        paths["baseline_cache_path"],
        expected_size_bytes=baseline_stat.st_size,
        expected_mtime_ns=baseline_stat.st_mtime_ns,
    )
    control_stat = paths["determinism_cache_path"].stat()
    control_sha = sha256_stable_file(
        paths["determinism_cache_path"],
        expected_size_bytes=control_stat.st_size,
        expected_mtime_ns=control_stat.st_mtime_ns,
    )
    code_hash = code_digest()
    with exclusive_lock(paths["lock_path"]):
        print("physical replay: W0 determinism canary", flush=True)
        determinism = streaming_determinism_gate(
            paths["baseline_cache_path"], paths["determinism_cache_path"]
        )
        print("physical replay: compacting immutable W0 tune baseline", flush=True)
        baseline = load_compact_h1_arm(
            paths["baseline_cache_path"], expected_split="tune", expected_weight=0.0
        )
        baseline["replay"] = dict(
            (((h1_result.get("tune") or {}).get("arm_gates") or {}).get("0.0") or {}).get("replay")
            or {}
        )
        baseline_mass = mass_gate(baseline["distribution_rows"])
        baseline_alignment = alignment_gate(baseline["rows"], baseline["rows"])
        baseline_dates = {str(row.get("target_date")) for row in baseline["rows"]}
        baseline_blockers = (
            list((baseline.get("replay") or {}).get("blockers") or [])
            + list(baseline_mass.get("blockers") or [])
            + list(baseline_alignment.get("blockers") or [])
        )
        if baseline_dates != set(tune_dates):
            baseline_blockers.append("W0 scoring rows do not exactly cover tune dates")
        if baseline_blockers:
            raise ExperimentConfigurationError("W0 gate failed: " + "; ".join(baseline_blockers))

        summaries = {unit: [] for unit in UNITS}
        arm_gates = {}
        cache_records = []
        total_started = time.perf_counter()
        for index, anchor in enumerate(PHYSICAL_C_SIGMA_ANCHORS, start=1):
            print(
                f"physical replay: arm {index}/{len(PHYSICAL_C_SIGMA_ANCHORS)} "
                f"physical_C_sigma={anchor:.2f} C_sigma={anchor:.2f} "
                f"F_sigma={native_sigma(anchor, 'F'):.2f}",
                flush=True,
            )
            arm, cache_path, fingerprint = load_or_run_arm(
                physical_c_sigma=anchor,
                folders=folders,
                tune_manifest=tune_manifest,
                entries=entries,
                staged_data_root=paths["staged_data_root"],
                cache_root=paths["cache_root"],
                code_hash=code_hash,
                baseline_sha256=baseline_sha,
                resume=bool(args.resume),
            )
            gate, arm_summaries = analyze_candidate(baseline, arm, anchor)
            arm_gates[str(anchor)] = gate
            for unit in UNITS:
                summaries[unit].append(arm_summaries[unit])
            cache_stat = cache_path.stat()
            cache_records.append(
                {
                    "path": str(cache_path),
                    "size_bytes": cache_stat.st_size,
                    "mtime_ns": cache_stat.st_mtime_ns,
                    "sha256": sha256_stable_file(
                        cache_path,
                        expected_size_bytes=cache_stat.st_size,
                        expected_mtime_ns=cache_stat.st_mtime_ns,
                    ),
                    "fingerprint": fingerprint,
                }
            )
            arm = None
            gc.collect()
        completion_code_hash = require_unchanged_code_digest(code_hash)
        selected, selection = select_family_sigmas(summaries)
        if set(selected) != set(UNITS):
            raise ExperimentConfigurationError("no eligible physical sigma for at least one family")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "COMPLETE",
            "disposition": "FROZEN_TUNE_ONLY_FOR_FUTURE_NEW_PANEL",
            "research_only": True,
            "promotion_authorized": False,
            "holdout_opened": False,
            "fresh_panel_opened": False,
            "serving_changed": False,
            "experiment": {
                "physical_c_sigma_anchors": list(PHYSICAL_C_SIGMA_ANCHORS),
                "native_mapping": {"C": "x", "F": "1.8*x"},
                "blend_weight": FIXED_BLEND_WEIGHT,
                "tune_dates": list(tune_dates),
                "selection_uses_tune_only": True,
                "runtime_seconds": time.perf_counter() - total_started,
                "selection_rule": (
                    "require negative tune mean paired Brier and log-loss deltas vs W0; "
                    "rank by Brier, log-loss, then smaller physical-C sigma"
                ),
            },
            "inputs": {
                "source_corpus_hash": tune_manifest.get("source_corpus_hash"),
                "tune_market_days": len(entries),
                "tune_folders": len(folders),
                "baseline_cache": {
                    "path": str(paths["baseline_cache_path"]),
                    "size_bytes": baseline_stat.st_size,
                    "sha256": baseline_sha,
                },
                "determinism_cache": {
                    "path": str(paths["determinism_cache_path"]),
                    "size_bytes": control_stat.st_size,
                    "sha256": control_sha,
                },
                "code_digest": code_hash,
                "completion_code_digest": completion_code_hash,
            },
            "baseline_gate": {
                "status": "PASS",
                "mass": baseline_mass,
                "alignment": baseline_alignment,
                "determinism": determinism,
                "blockers": [],
            },
            "arm_gates": arm_gates,
            "summaries": summaries,
            "selection": selection,
            "selected_physical_c_sigmas": selected,
            "frozen_candidate": {
                "status": "FROZEN_FOR_FUTURE_NEW_PANEL",
                "physical_c_sigma_by_family": selected,
                "native_sigma_by_family": {
                    unit: native_sigma(selected[unit], unit) for unit in UNITS
                },
                "blend_weight": FIXED_BLEND_WEIGHT,
                "selection_uses_tune_only": True,
                "confirmation_run": False,
                "promotion_authorized": False,
            },
            "cache_records": cache_records,
            "technical_blockers": [],
        }
        _atomic_json(paths["json_out"], payload)
        temporary = paths["report_out"].with_name(
            paths["report_out"].name + f".tmp-{os.getpid()}"
        )
        temporary.write_text(render_report(payload), encoding="utf-8")
        os.replace(temporary, paths["report_out"])
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror-data-root", required=True)
    parser.add_argument("--staged-data-root", required=True)
    parser.add_argument("--snapshots-root", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--h1-result", required=True)
    parser.add_argument("--tune-dates-file", required=True)
    parser.add_argument("--baseline-cache", required=True)
    parser.add_argument("--determinism-cache", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--report-out", required=True)
    parser.add_argument("--lock-path", required=True)
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        payload = run_experiment(build_parser().parse_args(argv))
    except ExperimentConfigurationError as exc:
        print(f"physical sigma replay blocked: {exc}", file=sys.stderr)
        return 2
    frozen = payload.get("frozen_candidate") or {}
    print(
        "physical sigma replay complete: "
        f"C={((frozen.get('native_sigma_by_family') or {}).get('C'))} "
        f"F={((frozen.get('native_sigma_by_family') or {}).get('F'))}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

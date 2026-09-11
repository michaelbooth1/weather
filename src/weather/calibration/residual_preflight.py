"""Hash-bound frozen residual reproduction and synthetic power preflight.

Run only through the adopted workstation-heavy declaration and exact wrapper.
This command cannot fit, evaluate new outcomes, promote, or place orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import sys
import time

from weather.calibration.residual_preflight_io import (
    PreflightError, digest, json_bytes, mutation_refused, read_bound,
    regular_path, verify_dependencies, write_new_json,
)
from weather.paths import repo_path
from weather.schema_registry import schema_version

FROZEN_SOURCES = {
    "src/weather/calibration/multiyear_nwp_residual.py": "8b513188aa5a123f29c3225d2a8efa435a56b46a07c1bcc0f8a96e756641e27f",
    "src/weather/sources/previous_runs_research_collection.py": "f5ea08a8f6b5927dd533d1e9af88a78c61aa2fe4993fbf34f3370b4705d77d5e",
    "src/weather/sources/daily_summary.py": "7def2ba0eb3bc281fd783a516514750885122af668becec3ac94d401ae36f913",
    "src/weather/paths.py": "666fd881baf35b9c3d4c594ef9559bba1e1b38aa5c33ccae0fa62901c534b947",
}
PRODUCER_FILES = {
    "src/weather/calibration/residual_preflight.py",
    "src/weather/calibration/residual_preflight_io.py",
    "src/weather/calibration/residual_preflight_inputs.py",
    "src/weather/calibration/residual_preflight_simulation.py",
    "src/weather/schema_registry_recent_data.py",
    "src/weather/operations/windows_process_metrics.py",
}


def verify_source_bindings(root, producer_records):
    if (not isinstance(producer_records, list) or len(producer_records) != len(PRODUCER_FILES)
            or {row.get("relative_path") for row in producer_records} != PRODUCER_FILES):
        raise PreflightError("source:producer_scope")
    records = []
    for relative, expected in FROZEN_SOURCES.items():
        path = regular_path(root / relative)
        record = {"relative_path": relative, "path": str(path), "bytes": path.stat().st_size, "sha256": expected}
        body = read_bound(record)
        mutation_refused(body, record)
        records.append(record)
    for item in producer_records:
        record = {**item, "path": str(root / item["relative_path"])}
        read_bound(record)
        records.append(record)
    return records


def imported_source_witness(root):
    names = (
        "weather.calibration.multiyear_nwp_residual",
        "weather.sources.previous_runs_research_collection",
        "weather.sources.daily_summary", "weather.paths",
        "weather.calibration.residual_preflight_io",
        "weather.calibration.residual_preflight_inputs",
        "weather.calibration.residual_preflight_simulation",
        "weather.operations.windows_process_metrics",
    )
    output = []
    for name in names:
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        expected = root / "src" / Path(*name.split(".")).with_suffix(".py")
        if path != expected:
            raise PreflightError("source:wrong_imported_checkout:" + name)
        output.append({"module": name, "path": str(path), "sha256": digest(path.read_bytes())})
    return output


def process_peaks():
    """Query this process using the repository's existing Win32 sampler types."""
    if os.name == "nt":
        from weather.operations.windows_process_metrics import _WINDOWS_PROCESS_MEMORY_API

        if _WINDOWS_PROCESS_MEMORY_API is None:
            raise PreflightError("resource:windows_api_missing")
        ctypes, kernel32, psapi, counter_type, _ = _WINDOWS_PROCESS_MEMORY_API
        handle = kernel32.OpenProcess(0x1000 | 0x0010, False, os.getpid())
        if not handle:
            raise PreflightError("resource:current_process_handle")
        try:
            counters = counter_type()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                raise PreflightError("resource:memory_query")
            return {"peak_working_set_bytes": int(counters.PeakWorkingSetSize),
                    "peak_commit_bytes": int(counters.PeakPagefileUsage), "scope": "current process"}
        finally:
            kernel32.CloseHandle(handle)
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"peak_working_set_bytes": int(peak if sys.platform == "darwin" else peak * 1024),
            "peak_commit_bytes": None, "scope": "current process"}


def run_preflight(manifest, *, progress=None):
    root = repo_path().resolve()
    if (manifest.get("schema_version") != schema_version("residual_preflight_manifest")
            or manifest.get("mode") != "frozen_2025_reproduction_and_synthetic_planning"
            or manifest.get("new_outcome_access") is not False
            or manifest.get("fitting_authorized") is not False):
        raise PreflightError("manifest:scope")
    progress = progress or (lambda _: None)
    started = time.perf_counter()
    progress("source_bindings")
    sources = verify_source_bindings(root, manifest["producer_files"])
    if "weather.calibration.multiyear_nwp_residual" in sys.modules:
        raise PreflightError("source:frozen_harness_imported_before_validation")
    if any(name in sys.modules for name in ("numpy", "scipy", "pandas", "sklearn")):
        raise PreflightError("dependency:scientific_import_before_binding")
    progress("dependency_bindings")
    dependencies = verify_dependencies(manifest["dependencies"])
    # This is a fresh offline process; keep native prediction threads bounded.
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    from weather.calibration import multiyear_nwp_residual as harness
    from weather.calibration.residual_preflight_inputs import reproduce
    from weather.calibration.residual_preflight_simulation import run_grid
    from weather.sources.previous_runs_research_collection import EXPECTED_UNITS

    witness = imported_source_witness(root)
    progress("frozen_reproduction")
    reproduction = reproduce(manifest, harness, EXPECTED_UNITS)
    progress("synthetic_coverage_and_power")
    simulation = run_grid(manifest["simulation"])
    # Re-hash producer/frozen sources after execution; changed code cannot PASS.
    if verify_source_bindings(root, manifest["producer_files"]) != sources:
        raise PreflightError("source:changed_during_run")
    return {
        "schema_version": schema_version("residual_preflight"),
        "status": "PREFLIGHT_COMPLETE_PROTOCOL_NOT_READY" if reproduction["status"] == "REPRODUCED" else "REPRODUCTION_BLOCKED",
        "reproduction": reproduction, "synthetic_planning": simulation,
        "source_bindings": sources, "import_witness": witness, "dependency_bindings": dependencies,
        "source_substitution_negative_controls": "PASS before frozen imports",
        "prospective_protocol_status": "NOT_READY_TO_FREEZE",
        "prospective_blockers": ["SOURCE_TIMING_UNQUALIFIED", "SEASON_EXTENSION_UNJUSTIFIED"],
        "prospective_scope_note": "This tool establishes no newly qualified unseen population or out-of-season validity. Previously evaluated cohorts remain exposed.",
        "new_outcome_access": False, "models_fitted": 0, "alpha_spent": 0,
        "promotion_authority": False, "live_order_authority": False,
        "elapsed_seconds": time.perf_counter() - started, "resources": process_peaks(),
    }


def render_markdown(result):
    lines = ["# Frozen residual preflight", "", "**" + result["status"] + ".**", ""]
    if "reproduction" not in result:
        return "\n".join(lines + ["Phase: " + result.get("failed_phase", "unknown"), "Reason: " + result.get("error", "unavailable"), ""])
    reproduction = result["reproduction"]
    lines += [
        "Numerical reproduction used 24 already-evaluated market-days across 12 markets and three dates.",
        "Maximum absolute native prediction difference: " + str(reproduction["maximum_absolute_difference_native"]) + ".",
        "Predeclared absolute tolerance: 1e-10; relative tolerance: zero. Clone difference: " + str(reproduction["clone_maximum_difference"]) + ".",
        "No fitting, new-outcome evaluation, alpha spending, promotion or trading occurred.", "",
        "Prospective protocol: **NOT_READY_TO_FREEZE**. Source timing and season-extension support remain unqualified.", "",
        "## Synthetic uncertainty checks", "",
        "Every process variance below is assumed. These are planning diagnostics, not estimates of model skill or a required real sample size.", "",
        "| Scenario | Dates | Markets | Method | Null false-positive rate | 95% coverage | Invalid variance |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for row in result["synthetic_planning"]["rows"]:
        lines.append("| " + " | ".join((
            row["scenario"]["name"], str(row["date_clusters"]), str(row["market_clusters"]), row["method"],
            f'{row["null_one_sided_false_positive"]["rate"]:.3f}',
            f'{row["null_two_sided_95_coverage"]["rate"]:.3f}',
            f'{row["invalid_variance"]["rate"]:.3f}',
        )) + " |")
    lines += [
        "", "The JSON retains Wilson Monte Carlo intervals, effects 0/0.10/0.25/0.50 C-equivalent squared,",
        "positive and practical lower-bound probabilities, and the exact known-covariance benchmark.",
        "Nonpositive variance refuses inference. The HAC hybrid remains experimental.",
        "More dates cannot remove persistent market uncertainty; eight-market support does not justify a twelve-market conclusion.",
        "", "## Provenance and limits", "",
        "Current package metadata, RECORD and recorded runtime files were bound before imports. This does not reconstruct an unrecorded original training environment.",
        "Source and input byte substitutions were rejected before use. The record sample and tolerance were fixed before examining selected predictions.",
        "Elapsed seconds: " + str(result["elapsed_seconds"]) + ". Resource receipt: " + json.dumps(result["resources"], sort_keys=True) + ".",
        "", "[Multiway clustering paper](https://cameron.econ.ucdavis.edu/research/JBESpaper2009version.pdf); "
        "[two-group covariance reference](https://www.statsmodels.org/dev/generated/statsmodels.stats.sandwich_covariance.cov_cluster_2groups.html); "
        "[Bartlett HAC reference](https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_hac.html).", "",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") != "1":
        parser.error("canonical workstation-heavy wrapper required; this flag is not independent authority")
    manifest_path = regular_path(args.manifest)
    bound = {"path": str(manifest_path), "bytes": manifest_path.stat().st_size, "sha256": args.manifest_sha256}
    manifest = json_bytes(read_bound(bound))
    output = args.output_root
    if not output.is_absolute():
        parser.error("output root must be absolute")
    output = output.resolve()
    try:
        output.relative_to(repo_path("scratch", "residual_preflight").resolve())
    except ValueError:
        parser.error("output must be in this checkout's scratch/residual_preflight")
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    write_new_json(output / "attempt-start.json", {"started_at_utc": started, "manifest": bound, "pid": os.getpid()})
    phase = "start"

    def progress(value):
        nonlocal phase
        phase = value
        print(json.dumps({"phase": phase}), flush=True)

    try:
        result = run_preflight(manifest, progress=progress)
        code = 0 if result["status"] == "PREFLIGHT_COMPLETE_PROTOCOL_NOT_READY" else 2
    except Exception as exc:
        result = {"schema_version": schema_version("residual_preflight"), "status": "REPRODUCTION_BLOCKED",
                  "failed_phase": phase, "error": type(exc).__name__ + ":" + str(exc)[:600],
                  "new_outcome_access": False, "promotion_authority": False, "live_order_authority": False}
        code = 2
    result.update({"manifest": bound, "started_at_utc": started, "finished_at_utc": datetime.now(timezone.utc).isoformat()})
    write_new_json(output / "model-preflight.json", result)
    with (output / "model-preflight.md").open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(render_markdown(result))
    print(json.dumps({"status": result["status"], "output_root": str(output)}), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

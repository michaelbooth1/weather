"""Bounded forensic audit for Item 35 density live/replay parity.

This command intentionally reads only a declared number of captured snapshots
and tape lines.  It does not invoke the corpus replay, training, or capture
pipelines.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from weather.collection.live_variant_predictions import (
    _density_probabilities,
    band_key,
)
from weather.io import write_json_atomic
from weather.market.market_registry import spec_for_slug
from weather.model.variant_prediction_runtime import (
    apply_continuous_density_calibration,
    apply_density_band_postprocessing,
    band_prediction_record,
    canonical_density_record,
    density_band_probability_from_distribution,
    density_projection_index,
    density_projection_probability,
    feature_frame,
    predict_density_rows_for_bundle,
)
from weather.paths import REPO_ROOT, data_path
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("density_live_replay_parity")
DEFAULT_VARIANT_ID = "pooled_continuous_density_hgb_v0_1"
DEFAULT_ARTIFACT = REPO_ROOT / "artifacts" / "models" / "hgb" / "item35_density_full_candidate.pkl"
DEFAULT_JSON_OUT = data_path("backtest", "item35_density_live_replay_parity_diagnostic.json")
DEFAULT_MD_OUT = data_path("backtest", "item35_density_live_replay_parity_diagnostic.md")
DEFAULT_EVENT_FOLDERS = (
    data_path("snapshots", "highest-temperature-in-toronto-on-july-10-2026"),
    data_path("snapshots", "highest-temperature-in-atlanta-on-july-10-2026"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _display_path(path: str | Path) -> str:
    path = Path(path)
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path.resolve())


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_artifact(path: str | Path) -> dict[str, Any]:
    with Path(path).open("rb") as handle:
        artifact = pickle.load(handle)
    if not isinstance(artifact, dict):
        raise ValueError("density artifact must deserialize to a dictionary")
    if artifact.get("prediction_mode") != "continuous_density_f":
        raise ValueError(
            "expected continuous_density_f artifact, got "
            f"{artifact.get('prediction_mode')!r}"
        )
    return artifact


def _read_jsonl_prefix(path: Path, limit: int) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    lines_read = 0
    if not path.exists():
        return rows, lines_read
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if lines_read >= limit:
                break
            lines_read += 1
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows, lines_read


def _read_variant_rows(
    path: Path,
    *,
    variant_id: str,
    expected_bands: dict[str, int],
    max_lines: int,
) -> tuple[dict[str, list[dict[str, Any]]], int, bool]:
    selected = {snapshot_id: [] for snapshot_id in expected_bands}
    lines_read = 0
    if not path.exists():
        return selected, lines_read, False
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if lines_read >= max_lines:
                break
            lines_read += 1
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            snapshot_id = str(row.get("snapshot_id") or "")
            if snapshot_id not in selected or row.get("variant_id") != variant_id:
                continue
            selected[snapshot_id].append(row)
            if all(len(selected[key]) >= count for key, count in expected_bands.items()):
                return selected, lines_read, True
    complete = all(len(selected[key]) >= count for key, count in expected_bands.items())
    return selected, lines_read, complete


def _normalize_partition(probabilities: dict[str, float], gamma: float) -> dict[str, float]:
    weights = {
        key: max(1e-12, float(value)) ** max(0.1, float(gamma or 1.0))
        for key, value in probabilities.items()
    }
    total = sum(weights.values())
    if total <= 0:
        return probabilities
    return {key: value / total for key, value in weights.items()}


def _legacy_live_probabilities(
    artifact: dict[str, Any],
    feature_vector: dict[str, Any],
    bands: list[dict[str, Any]],
) -> tuple[dict[str, float], dict[str, Any]]:
    """Reproduce the pre-fix live route for comparison with historical tape."""
    payloads = predict_density_rows_for_bundle(artifact, [feature_vector])
    payload = payloads[0] if payloads else None
    if not payload:
        return {}, {}
    postprocess = artifact.get("density_postprocess") or {}
    projection_unit = str(
        feature_vector.get("display_unit") or feature_vector.get("unit") or "F"
    ).upper()
    if postprocess.get("enabled"):
        payload = apply_continuous_density_calibration(
            payload,
            artifact,
            floor_bucket=feature_vector.get("observed_floor_bucket"),
            unit=projection_unit,
            resolution_weight=feature_vector.get("late_lockin_strength", 0.0),
            cutoff_hour=feature_vector.get("cutoff_hour"),
        )
    index = density_projection_index(payload)
    spec = SimpleNamespace(display_unit=projection_unit, unit=projection_unit)
    probabilities: dict[str, float] = {}
    for band in bands:
        kind = band.get("bin_kind")
        value = band.get("bin_value_c")
        value_hi = band.get("bin_value_hi_c")
        probability = density_projection_probability(
            index,
            projection_unit,
            kind,
            value,
            value_hi=value_hi,
        )
        if probability is None:
            probability = density_band_probability_from_distribution(
                payload,
                spec,
                {"kind": kind, "value": value, "value_hi": value_hi, "unit": projection_unit},
            )
        if probability is not None and math.isfinite(float(probability)):
            probabilities[band_key(band)] = max(0.0, min(1.0, float(probability)))
    if postprocess.get("enabled") and postprocess.get("partition_normalization_enabled", False):
        probabilities = _normalize_partition(
            probabilities,
            float(postprocess.get("partition_normalization_gamma", 1.25)),
        )
    return probabilities, {
        "projection_unit": projection_unit,
        "density_mean_f": payload.get("mean_f"),
        "density_sigma_f": payload.get("sigma_f"),
    }


def _canonical_replay_probabilities(
    artifact: dict[str, Any],
    feature_vector: dict[str, Any],
    bands: list[dict[str, Any]],
    *,
    market_id: str,
    display_unit: str,
) -> tuple[dict[str, float], dict[str, Any]]:
    runtime_features = dict(feature_vector)
    runtime_features.update(
        market_id=market_id,
        display_unit=display_unit,
        unit=display_unit,
    )
    payloads = predict_density_rows_for_bundle(artifact, [runtime_features])
    payload = payloads[0] if payloads else None
    if not payload or not bands:
        return {}, {}
    records = [
        band_prediction_record(
            runtime_features,
            band.get("bin_kind"),
            band.get("bin_value_c"),
            value_hi=band.get("bin_value_hi_c"),
        )
        for band in bands
    ]
    context = records[0]
    payload = apply_continuous_density_calibration(
        payload,
        artifact,
        floor_bucket=context.get("observed_floor_bucket"),
        unit=display_unit,
        resolution_weight=context.get("late_lockin_strength", 0.0),
        cutoff_hour=runtime_features.get("cutoff_hour"),
    )
    index = density_projection_index(payload)
    spec = SimpleNamespace(display_unit=display_unit, unit=display_unit)
    postprocess = artifact.get("density_postprocess") or {}
    probabilities: dict[str, float] = {}
    for band, record in zip(bands, records):
        kind = band.get("bin_kind")
        value = band.get("bin_value_c")
        value_hi = band.get("bin_value_hi_c")
        probability = density_projection_probability(
            index,
            display_unit,
            kind,
            value,
            value_hi=value_hi,
        )
        if probability is None:
            probability = density_band_probability_from_distribution(
                payload,
                spec,
                {"kind": kind, "value": value, "value_hi": value_hi, "unit": display_unit},
            )
        if probability is not None and math.isfinite(float(probability)):
            probability = apply_density_band_postprocessing(
                probability,
                record,
                config=postprocess,
            )
            probabilities[band_key(band)] = max(0.0, min(1.0, float(probability)))
    if postprocess.get("enabled") and postprocess.get("partition_normalization_enabled", False):
        probabilities = _normalize_partition(
            probabilities,
            float(postprocess.get("partition_normalization_gamma", 1.25)),
        )
    return probabilities, {
        "projection_unit": display_unit,
        "density_mean_f": payload.get("mean_f"),
        "density_sigma_f": payload.get("sigma_f"),
        "derived_floor_bucket": context.get("observed_floor_bucket"),
        "derived_lockin_strength": context.get("late_lockin_strength"),
    }


def _probability_comparison(
    left: dict[str, float],
    right: dict[str, float],
) -> dict[str, Any]:
    keys = sorted(set(left) | set(right))
    deltas = [abs(float(left[key]) - float(right[key])) for key in keys if key in left and key in right]
    missing_left = [key for key in keys if key not in left]
    missing_right = [key for key in keys if key not in right]
    return {
        "compared_band_count": len(deltas),
        "missing_left": missing_left,
        "missing_right": missing_right,
        "max_abs_delta": max(deltas) if deltas else None,
        "mean_abs_delta": (sum(deltas) / len(deltas)) if deltas else None,
    }


def _top_band(probabilities: dict[str, float]) -> dict[str, Any] | None:
    if not probabilities:
        return None
    key, probability = max(probabilities.items(), key=lambda item: (item[1], item[0]))
    return {"band_key": key, "probability": probability}


def _feature_diagnostics(
    artifact: dict[str, Any],
    feature_vector: dict[str, Any],
    *,
    market_id: str,
    display_unit: str,
) -> dict[str, Any]:
    hour = str(feature_vector.get("cutoff_hour") or "")
    bundle = (artifact.get("models") or {}).get(hour) or {}
    feature_names = list(bundle.get("feature_names") or [])
    runtime_features = dict(feature_vector)
    runtime_features.update(market_id=market_id, display_unit=display_unit, unit=display_unit)
    canonical = canonical_density_record(runtime_features)
    frame = feature_frame([canonical], feature_names=feature_names) if feature_names else None
    missing_count = int(frame.isna().sum(axis=1).iloc[0]) if frame is not None else None
    return {
        "cutoff_hour": hour,
        "artifact_hour_bundle_present": bool(bundle),
        "artifact_feature_name_count": len(feature_names),
        "artifact_feature_names_unique": len(feature_names) == len(set(feature_names)),
        "artifact_feature_order_sha256": hashlib.sha256(
            json.dumps(feature_names, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "captured_feature_count": len(feature_vector),
        "captured_feature_schema_version": feature_vector.get("feature_schema_version"),
        "captured_market_id": feature_vector.get("market_id"),
        "captured_display_unit": feature_vector.get("display_unit"),
        "captured_unit": feature_vector.get("unit"),
        "injected_market_id": market_id,
        "injected_display_unit": display_unit,
        "model_frame_missing_value_count": missing_count,
    }


def _recorded_probabilities(rows: list[dict[str, Any]]) -> dict[str, float]:
    output = {}
    for row in rows:
        if row.get("prediction_status") != "predicted":
            continue
        try:
            value = float(row.get("variant_probability"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            output[str(row.get("band_key"))] = value
    return output


def build_diagnostic(
    *,
    event_folders: list[str | Path],
    artifact_path: str | Path = DEFAULT_ARTIFACT,
    variant_id: str = DEFAULT_VARIANT_ID,
    max_snapshots_per_event: int = 1,
    max_variant_lines_per_event: int = 5000,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    artifact_path = Path(artifact_path)
    artifact = _load_artifact(artifact_path)
    artifact_sha256 = _sha256_file(artifact_path)
    samples = []
    input_files = []
    total_snapshot_lines = 0
    total_variant_lines = 0

    for raw_folder in event_folders:
        folder = Path(raw_folder)
        spec = spec_for_slug(folder.name)
        if spec is None:
            raise ValueError(f"event folder does not map to a registered market: {folder}")
        snapshot_path = folder / "snapshots.jsonl"
        tape_path = folder / "variant_predictions.jsonl"
        replay_path = folder / "replay_inputs.jsonl"
        snapshots, snapshot_lines = _read_jsonl_prefix(snapshot_path, max_snapshots_per_event)
        total_snapshot_lines += snapshot_lines
        expected_bands = {
            str(snapshot.get("snapshot_id")): len(snapshot.get("bands") or [])
            for snapshot in snapshots
        }
        tape_by_snapshot, tape_lines, tape_complete = _read_variant_rows(
            tape_path,
            variant_id=variant_id,
            expected_bands=expected_bands,
            max_lines=max_variant_lines_per_event,
        )
        total_variant_lines += tape_lines
        replay_rows, replay_lines = _read_jsonl_prefix(replay_path, max_snapshots_per_event)
        replay_by_snapshot = {str(row.get("snapshot_id")): row for row in replay_rows}
        for path in (snapshot_path, tape_path, replay_path):
            input_files.append({
                "path": _display_path(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else None,
            })

        for snapshot in snapshots:
            snapshot_id = str(snapshot.get("snapshot_id") or "")
            feature_vector = dict(snapshot.get("feature_vector") or {})
            bands = list(snapshot.get("bands") or [])
            tape_rows = tape_by_snapshot.get(snapshot_id) or []
            recorded = _recorded_probabilities(tape_rows)
            legacy, legacy_context = _legacy_live_probabilities(artifact, feature_vector, bands)
            fixed = _density_probabilities(
                artifact,
                feature_vector,
                bands,
                market_id=spec.id,
            )
            replay, replay_context = _canonical_replay_probabilities(
                artifact,
                feature_vector,
                bands,
                market_id=spec.id,
                display_unit=spec.display_unit,
            )
            first_tape = tape_rows[0] if tape_rows else {}
            replay_input = replay_by_snapshot.get(snapshot_id) or {}
            comparisons = {
                "recorded_vs_legacy": _probability_comparison(recorded, legacy),
                "recorded_vs_canonical_replay": _probability_comparison(recorded, replay),
                "repaired_live_vs_canonical_replay": _probability_comparison(fixed, replay),
            }
            samples.append({
                "event_folder": _display_path(folder),
                "event_slug": snapshot.get("event_slug") or folder.name,
                "market_id": spec.id,
                "display_unit": spec.display_unit,
                "snapshot_id": snapshot_id,
                "captured_at_utc": snapshot.get("captured_at_utc"),
                "snapshot_feature_schema_version": snapshot.get("feature_schema_version"),
                "band_count": len(bands),
                "tape_row_count": len(tape_rows),
                "tape_scan_complete": tape_complete,
                "tape_prediction_statuses": sorted({str(row.get("prediction_status")) for row in tape_rows}),
                "tape_live_runtimes": sorted({str(row.get("live_runtime")) for row in tape_rows}),
                "tape_artifact_hashes": sorted({str(row.get("artifact_hash")) for row in tape_rows}),
                "tape_artifact_matches": bool(tape_rows) and all(
                    str(row.get("artifact_hash")) == artifact_sha256 for row in tape_rows
                ),
                "tape_postprocess_config_hashes": sorted({
                    str(row.get("postprocess_config_hash")) for row in tape_rows
                }),
                "tape_schema_versions": sorted({str(row.get("schema_version")) for row in tape_rows}),
                "tape_release_ids": sorted({str(row.get("release_id") or "") for row in tape_rows}),
                "tape_captured_input_hashes": sorted({
                    str(row.get("captured_input_hash") or "") for row in tape_rows
                }),
                "replay_input_present": bool(replay_input),
                "replay_input_schema_version": replay_input.get("schema_version"),
                "replay_input_release_id": replay_input.get("release_id"),
                "replay_input_captured_input_hash": replay_input.get("captured_input_hash"),
                "feature_diagnostics": _feature_diagnostics(
                    artifact,
                    feature_vector,
                    market_id=spec.id,
                    display_unit=spec.display_unit,
                ),
                "legacy_context": legacy_context,
                "canonical_context": replay_context,
                "probability_sums": {
                    "recorded": sum(recorded.values()),
                    "legacy": sum(legacy.values()),
                    "repaired_live": sum(fixed.values()),
                    "canonical_replay": sum(replay.values()),
                },
                "top_bands": {
                    "recorded": _top_band(recorded),
                    "legacy": _top_band(legacy),
                    "repaired_live": _top_band(fixed),
                    "canonical_replay": _top_band(replay),
                },
                "comparisons": comparisons,
                "runtime_identity": {
                    "git_commit": first_tape.get("runtime_git_commit"),
                    "git_dirty": first_tape.get("runtime_git_dirty"),
                    "source_fingerprint": first_tape.get("runtime_source_fingerprint"),
                },
            })

    historical_failures = [
        sample for sample in samples
        if (
            sample["comparisons"]["recorded_vs_canonical_replay"]["max_abs_delta"] is None
            or sample["comparisons"]["recorded_vs_canonical_replay"]["max_abs_delta"] > tolerance
            or sample["comparisons"]["recorded_vs_canonical_replay"]["missing_left"]
            or sample["comparisons"]["recorded_vs_canonical_replay"]["missing_right"]
        )
    ]
    repaired_failures = [
        sample for sample in samples
        if (
            sample["comparisons"]["repaired_live_vs_canonical_replay"]["max_abs_delta"] is None
            or sample["comparisons"]["repaired_live_vs_canonical_replay"]["max_abs_delta"] > tolerance
            or sample["comparisons"]["repaired_live_vs_canonical_replay"]["missing_left"]
            or sample["comparisons"]["repaired_live_vs_canonical_replay"]["missing_right"]
        )
    ]
    legacy_tape = any(
        not any(value for value in sample["tape_captured_input_hashes"])
        or not sample["replay_input_captured_input_hash"]
        for sample in samples
    )
    blockers = []
    if historical_failures:
        blockers.append("historical_live_tape_diverges_from_canonical_captured_snapshot_replay")
    if repaired_failures:
        blockers.append("repaired_live_route_does_not_match_canonical_replay")
    if legacy_tape:
        blockers.append("legacy_tape_lacks_strict_release_and_captured_input_hash")
    blockers.append("fresh_post_fix_live_tape_not_yet_available")

    postprocess = artifact.get("density_postprocess") or {}
    max_historical_delta = max(
        (
            sample["comparisons"]["recorded_vs_canonical_replay"]["max_abs_delta"]
            for sample in samples
            if sample["comparisons"]["recorded_vs_canonical_replay"]["max_abs_delta"] is not None
        ),
        default=None,
    )
    max_legacy_delta = max(
        (
            sample["comparisons"]["recorded_vs_legacy"]["max_abs_delta"]
            for sample in samples
            if sample["comparisons"]["recorded_vs_legacy"]["max_abs_delta"] is not None
        ),
        default=None,
    )
    max_repaired_delta = max(
        (
            sample["comparisons"]["repaired_live_vs_canonical_replay"]["max_abs_delta"]
            for sample in samples
            if sample["comparisons"]["repaired_live_vs_canonical_replay"]["max_abs_delta"] is not None
        ),
        default=None,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "status": "BLOCK",
        "decision": "QUARANTINE_NON_HEADLINE_NON_PROMOTION",
        "variant_id": variant_id,
        "artifact": {
            "path": _display_path(artifact_path),
            "sha256": artifact_sha256,
            "schema_version": artifact.get("schema_version"),
            "feature_schema_version": artifact.get("feature_schema_version"),
            "prediction_mode": artifact.get("prediction_mode"),
            "density_postprocess": {
                "schema_version": postprocess.get("schema_version"),
                "enabled": bool(postprocess.get("enabled")),
                "policy_id": postprocess.get("policy_id"),
                "adjacent_calibration_enabled": bool(
                    postprocess.get("adjacent_calibration_enabled")
                ),
                "exact_winner_catchup_enabled": bool(
                    postprocess.get("exact_winner_catchup_enabled")
                ),
                "forecast_relative_calibration_enabled": bool(
                    postprocess.get("forecast_relative_calibration_enabled")
                ),
                "partition_normalization_enabled": bool(
                    postprocess.get("partition_normalization_enabled")
                ),
            },
        },
        "execution_bounds": {
            "mode": "bounded_existing_tape_forensic_no_corpus_replay",
            "max_snapshots_per_event": max_snapshots_per_event,
            "max_variant_lines_per_event": max_variant_lines_per_event,
            "event_folder_count": len(event_folders),
            "snapshot_lines_read": total_snapshot_lines,
            "variant_lines_read": total_variant_lines,
            "capture_or_training_invoked": False,
        },
        "summary": {
            "sample_count": len(samples),
            "legacy_route_reproduction_status": (
                "PASS" if max_legacy_delta is not None and max_legacy_delta <= tolerance else "FAIL"
            ),
            "max_recorded_vs_legacy_abs_delta": max_legacy_delta,
            "historical_live_parity_status": "FAIL" if historical_failures else "PASS",
            "repaired_code_parity_status": "FAIL" if repaired_failures else "PASS",
            "max_recorded_vs_canonical_abs_delta": max_historical_delta,
            "max_repaired_live_vs_canonical_abs_delta": max_repaired_delta,
            "tolerance": tolerance,
        },
        "proven_root_causes": [
            {
                "id": "missing_explicit_projection_unit",
                "detail": (
                    "Captured feature vectors omitted display_unit/unit; legacy live projection defaulted to F, "
                    "so Toronto C bands were integrated as F."
                ),
            },
            {
                "id": "missing_explicit_market_identity_for_feature_canonicalization",
                "detail": (
                    "Captured feature vectors omitted market_id; record_unit silently selected the Toronto default, "
                    "so F-market native feature values were canonicalized as C before model inference."
                ),
            },
            {
                "id": "live_calibration_context_drift",
                "detail": (
                    "Legacy live applied continuous calibration only when density_postprocess.enabled and read floor/"
                    "lock-in fields directly; replay always calibrated with floor context derived from the band record."
                ),
            },
            {
                "id": "live_band_postprocess_drift",
                "detail": (
                    "Legacy live omitted replay's density adjacent, exact-winner, and forecast-relative band "
                    "postprocessors. The registered v0.1 artifact has no enabled density postprocess, but the route "
                    "contract was divergent for any future enabled artifact."
                ),
            },
        ],
        "blockers": blockers,
        "next_required_evidence": [
            "Keep the registered density lane non-headline and non-countable for promotion.",
            "Collect fresh v0.2 live tape with verified release identity and captured_input_hash.",
            "Replay the same captured input under the same immutable release and require deterministic partition parity.",
            "Only then requalify on untouched fleet-date-blocked evidence or retire the lane.",
        ],
        "inputs": input_files,
        "samples": samples,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Item 35 Density Live/Replay Parity Diagnostic",
        "",
        f"Status: **{payload['status']}** — `{payload['decision']}`",
        "",
        "This is a bounded forensic recomputation over existing captured snapshots and live variant tape. "
        "It did not run corpus replay, training, or capture.",
        "",
        "## Result",
        "",
        "| Check | Result |",
        "| --- | --- |",
        f"| Recorded tape vs reproduced legacy route | {summary['legacy_route_reproduction_status']} |",
        f"| Max recorded-vs-legacy absolute delta | {summary['max_recorded_vs_legacy_abs_delta']} |",
        f"| Historical recorded live vs canonical replay | {summary['historical_live_parity_status']} |",
        f"| Repaired live code vs canonical replay | {summary['repaired_code_parity_status']} |",
        f"| Max historical absolute delta | {summary['max_recorded_vs_canonical_abs_delta']} |",
        f"| Max repaired-code absolute delta | {summary['max_repaired_live_vs_canonical_abs_delta']} |",
        f"| Declared tolerance | {summary['tolerance']} |",
        "",
        "## Bounded samples",
        "",
        "| Market | Unit | Snapshot | Recorded top | Canonical top | Historical max delta | Repaired max delta |",
        "| --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for sample in payload.get("samples") or []:
        recorded_top = (sample["top_bands"].get("recorded") or {}).get("band_key") or "-"
        canonical_top = (sample["top_bands"].get("canonical_replay") or {}).get("band_key") or "-"
        historical = sample["comparisons"]["recorded_vs_canonical_replay"]["max_abs_delta"]
        repaired = sample["comparisons"]["repaired_live_vs_canonical_replay"]["max_abs_delta"]
        lines.append(
            f"| {sample['market_id']} | {sample['display_unit']} | `{sample['snapshot_id']}` | "
            f"`{recorded_top}` | `{canonical_top}` | {historical} | {repaired} |"
        )
    lines.extend([
        "",
        "## Proven causes",
        "",
    ])
    for cause in payload.get("proven_root_causes") or []:
        lines.append(f"- `{cause['id']}`: {cause['detail']}")
    lines.extend([
        "",
        "## Promotion blockers",
        "",
    ])
    for blocker in payload.get("blockers") or []:
        lines.append(f"- `{blocker}`")
    lines.extend([
        "",
        "## Disposition",
        "",
    ])
    for item in payload.get("next_required_evidence") or []:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## Execution bounds",
        "",
        f"- Snapshot lines read: {payload['execution_bounds']['snapshot_lines_read']}",
        f"- Variant lines read: {payload['execution_bounds']['variant_lines_read']}",
        f"- Capture or training invoked: {payload['execution_bounds']['capture_or_training_invoked']}",
        "",
    ])
    return "\n".join(lines)


def _write_text_atomic(path: str | Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-folder", action="append", default=[])
    parser.add_argument("--artifact", default=str(DEFAULT_ARTIFACT))
    parser.add_argument("--variant-id", default=DEFAULT_VARIANT_ID)
    parser.add_argument("--max-snapshots-per-event", type=int, default=1)
    parser.add_argument("--max-variant-lines-per-event", type=int, default=5000)
    parser.add_argument("--tolerance", type=float, default=1e-9)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--md-out", default=str(DEFAULT_MD_OUT))
    parser.add_argument("--no-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    event_folders = args.event_folder or [str(path) for path in DEFAULT_EVENT_FOLDERS]
    payload = build_diagnostic(
        event_folders=event_folders,
        artifact_path=args.artifact,
        variant_id=args.variant_id,
        max_snapshots_per_event=max(1, args.max_snapshots_per_event),
        max_variant_lines_per_event=max(1, args.max_variant_lines_per_event),
        tolerance=max(0.0, args.tolerance),
    )
    if args.no_write:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    write_json_atomic(args.json_out, payload, trailing_newline=True)
    _write_text_atomic(args.md_out, render_markdown(payload))
    print(
        f"density parity status={payload['status']} "
        f"historical={payload['summary']['historical_live_parity_status']} "
        f"repaired={payload['summary']['repaired_code_parity_status']} "
        f"json={args.json_out} md={args.md_out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

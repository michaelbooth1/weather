"""Band-level reanalysis sidecar ablation for the physical-family ratchet.

The generic source-family ablation knocks out live source payloads. Reanalysis
sidecars are artifact feature rows, so this report compares the same pooled
candidate artifact with its reanalysis feature family intact and then masked
through the production reanalysis lane hook.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import pickle
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from weather.execution_identity import (
    atomic_write_json_exclusive,
    atomic_write_text_exclusive,
)

from weather.backtesting.replay_ablation import (
    EVIDENCE_MODE_OPERATIONAL,
    EVIDENCE_MODE_RESEARCH,
    _load_manifest_with_receipt,
    build_payload,
    paired_day_inference,
    paired_inference_sensitivities,
    paired_market_inference,
    read_date_manifest_with_receipt,
    summarize,
    summarize_slice_effects,
)
from weather.backtesting.replay_backtest import run_replay_backtest
from weather.backtesting.settled_days import DEFAULT_SNAPSHOTS_ROOT
from weather.calibration.pooled_candidate_replay import (
    attach_band_candidate_probabilities,
    build_candidate_features,
    build_clob_feature_index,
    build_source_freshness_index,
    cutoff_regime,
)
from weather.calibration.pooled_candidate_scoring import _valid_probability
from weather.calibration.pooled_feature_model import DEFAULT_BAND_ARTIFACT
from weather.calibration.pooled_feature_assembly import (
    apply_reanalysis_promotion_lane_to_record,
)
from weather.market.market_microstructure_features import snapshot_band_key
from weather.market.market_registry import REGISTRY
from weather.paths import data_path, repo_path
from weather.reporting.formatting import fmt_signed, markdown_table
from weather.reporting.promotion.promotion_corpus import (
    DEFAULT_OUT as DEFAULT_CORPUS,
    folders_from_manifest_strict,
    load_manifest,
)
from weather.reporting.source_gates.source_family_contracts import (
    source_ablation_operational_contract,
)
from weather.reporting.source_gates.source_artifact_binding import (
    receipt_shape_contract,
    stable_json_artifact,
)


DEFAULT_JSON_OUT = (
    repo_path("scratch")
    / "research-output"
    / "reanalysis-synoptic-band-ablation.json"
)
DEFAULT_REPORT_OUT = (
    repo_path("scratch")
    / "research-output"
    / "reanalysis-synoptic-band-ablation.md"
)
DEFAULT_SOURCE_FAMILY_ABLATION = data_path("backtest") / "source_family_ablation.json"
VARIANT = "reanalysis_synoptic"
EVIDENCE_SOURCE = "candidate_artifact_band_ablation"


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _load_bound_artifact(path, *, expected_sha256):
    """Verify stable bytes, then fail closed without an independent trust root."""

    expected_sha256 = str(expected_sha256 or "").strip().lower()
    if (
        len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise ValueError(
            "candidate artifact requires a caller-supplied SHA-256 integrity "
            "digest; this retired lane has no independent authorization anchor"
        )

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError(f"candidate artifact must not be a symlink: {requested}")
    try:
        parent = requested.parent.resolve(strict=True)
        parent_before = parent.stat()
        resolved = requested.resolve(strict=True)
        with resolved.open("rb") as handle:
            before = os.fstat(handle.fileno())
            raw = handle.read()
            after = os.fstat(handle.fileno())
        resolved_after = requested.resolve(strict=True)
        parent_after = parent.stat()
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            f"candidate artifact could not be read from a stable path: {requested}: {exc}"
        ) from exc

    def identity(stat_result):
        return (
            getattr(stat_result, "st_dev", 0),
            getattr(stat_result, "st_ino", 0),
            stat_result.st_size,
            stat_result.st_mtime_ns,
            getattr(stat_result, "st_ctime_ns", 0),
        )

    parent_identity_before = (
        getattr(parent_before, "st_dev", 0),
        getattr(parent_before, "st_ino", 0),
        parent_before.st_mtime_ns,
        getattr(parent_before, "st_ctime_ns", 0),
    )
    parent_identity_after = (
        getattr(parent_after, "st_dev", 0),
        getattr(parent_after, "st_ino", 0),
        parent_after.st_mtime_ns,
        getattr(parent_after, "st_ctime_ns", 0),
    )
    if (
        identity(before) != identity(after)
        or len(raw) != after.st_size
        or resolved_after != resolved
        or parent_identity_before != parent_identity_after
    ):
        raise ValueError(f"candidate artifact changed during stable read: {resolved}")
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    if observed_sha256 != expected_sha256:
        raise ValueError(
            "candidate artifact SHA-256 differs from the caller-supplied "
            "integrity digest: "
            f"expected={expected_sha256}; observed={observed_sha256}"
        )
    raise ValueError(
        "candidate-artifact pickle deserialization is disabled until an "
        "independently anchored operational candidate-evidence trust root is "
        "implemented; a caller-supplied SHA-256 is integrity evidence, not an "
        "independent authorization anchor"
    )


def masked_reanalysis_artifact(artifact):
    masked = copy.deepcopy(artifact)
    lane = {
        "status": "ARTIFACT_FEATURE_FAMILY_ABLATION",
        "blocked_feature_prefixes": ["reanalysis_"],
        "description": "Mask all reanalysis sidecar features for source-family value measurement.",
    }
    lanes = dict(masked.get("source_family_lanes") or {})
    lanes[VARIANT] = lane
    masked["source_family_lanes"] = lanes
    masked["reanalysis_promotion_lane"] = lane
    return masked


def _runtime_manifest_bound_to_folders(manifest, folders, snapshots_root):
    """Return a reader view whose folder fields cannot escape the strict root."""

    entries = list(manifest.get("entries") or [])
    if len(entries) != len(folders):
        raise ValueError("strict corpus folder expansion is not one-to-one")
    rooted = copy.deepcopy(manifest)
    rooted_entries = list(rooted.get("entries") or [])
    root = Path(snapshots_root).expanduser().resolve(strict=True)
    for entry, folder in zip(rooted_entries, folders):
        resolved_folder = Path(folder).expanduser().resolve(strict=False)
        try:
            relative = resolved_folder.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"strict runtime folder escapes snapshots root: {resolved_folder}"
            ) from exc
        entry["folder"] = str(resolved_folder)
        entry["folder_relative_to_snapshots_root"] = str(relative)
        entry["folder_name"] = resolved_folder.name
    rooted["snapshots_root"] = str(root)
    return rooted


def _capture_candidate_inputs(
    manifest,
    snapshots_root,
    artifact,
    *,
    clob_max_age_seconds=180.0,
):
    """Read every mutable candidate input once for both experiment arms."""

    prediction_mode = artifact.get("prediction_mode") or "bucket_distribution"
    if prediction_mode != "band_binary":
        raise ValueError(
            "reanalysis band ablation currently requires a band_binary pooled artifact; "
            f"got {prediction_mode!r}"
        )
    family_unit = artifact.get("family_unit") or "F"
    feature_rows, diagnostics = build_candidate_features(
        manifest,
        snapshots_root,
        family_unit,
        artifact=artifact,
    )
    clob_features, clob_diagnostics = build_clob_feature_index(
        manifest,
        snapshots_root,
        family_unit,
        max_age_seconds=clob_max_age_seconds,
    )
    source_freshness, source_freshness_diagnostics = build_source_freshness_index(
        manifest,
        snapshots_root,
        family_unit,
    )
    diagnostics.update(clob_diagnostics)
    diagnostics.update(source_freshness_diagnostics)
    return {
        "family_unit": family_unit,
        "feature_rows": feature_rows,
        "clob_features": clob_features,
        "source_freshness": source_freshness,
        "diagnostics": diagnostics,
    }


def _candidate_rows_from_captured(
    captured_inputs,
    artifact,
    replay_results,
    *,
    reanalysis_lane=None,
):
    family_unit = captured_inputs["family_unit"]
    artifact_family_unit = artifact.get("family_unit") or "F"
    if artifact_family_unit != family_unit:
        raise ValueError("base and masked artifacts do not share a family unit")
    feature_rows = copy.deepcopy(captured_inputs["feature_rows"])
    if reanalysis_lane:
        for feature_row in feature_rows.values():
            apply_reanalysis_promotion_lane_to_record(
                feature_row,
                reanalysis_lane,
            )
    rows, coverage = attach_band_candidate_probabilities(
        replay_results,
        feature_rows,
        artifact,
        family_unit,
        clob_features=copy.deepcopy(captured_inputs["clob_features"]),
        source_freshness=copy.deepcopy(captured_inputs["source_freshness"]),
    )
    for row in rows:
        row["candidate_cutoff_regime"] = cutoff_regime(row.get("candidate_cutoff_hour"))
    diagnostics = copy.deepcopy(captured_inputs["diagnostics"])
    diagnostics["captured_input_generation_shared"] = True
    diagnostics["reanalysis_lane_applied_after_capture"] = bool(reanalysis_lane)
    return rows, {
        "feature_rows": len(feature_rows),
        "coverage": coverage,
        "diagnostics": diagnostics,
    }


def _score_captured_ablation_arms(
    captured_inputs,
    pristine_artifact,
    replay_results,
):
    """Clone both scoring arms before either mutable estimator is invoked."""

    base_artifact = copy.deepcopy(pristine_artifact)
    masked_artifact = masked_reanalysis_artifact(pristine_artifact)
    masked_lane = masked_artifact["reanalysis_promotion_lane"]
    base_rows, base_diagnostics = _candidate_rows_from_captured(
        captured_inputs,
        base_artifact,
        replay_results,
    )
    masked_rows, masked_diagnostics = _candidate_rows_from_captured(
        captured_inputs,
        masked_artifact,
        replay_results,
        reanalysis_lane=masked_lane,
    )
    return base_rows, base_diagnostics, masked_rows, masked_diagnostics


def _candidate_rows(
    manifest,
    snapshots_root,
    artifact,
    replay_results,
    clob_max_age_seconds=180.0,
):
    """Compatibility wrapper for one-arm research callers."""

    captured = _capture_candidate_inputs(
        manifest,
        snapshots_root,
        artifact,
        clob_max_age_seconds=clob_max_age_seconds,
    )
    return _candidate_rows_from_captured(captured, artifact, replay_results)


def _row_key(row):
    kind, value, value_hi = snapshot_band_key(row)
    return (
        row.get("market_id"),
        str(row.get("snapshot_id")),
        kind,
        value,
        value_hi,
    )


def _settlement_distance_bucket(value):
    text = str(value or "").strip().lower()
    if text in {"0", "0.0", "exact"}:
        return "exact"
    if text in {"1", "1.0", "adjacent"}:
        return "adjacent"
    if text in {"", "none", "nan", "unknown"}:
        return "unknown"
    return "far"


def paired_ablation_rows(base_rows, masked_rows):
    if not isinstance(base_rows, list) or not isinstance(masked_rows, list):
        raise ValueError("base and masked candidate rows must be lists")

    def indexed(rows, label):
        output = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"{label}[{index}] must be an object")
            key = _row_key(row)
            if (
                any(value in (None, "") for value in key[:3])
                or key[3] is None
                or key[4] is None
            ):
                raise ValueError(f"{label}[{index}] has an invalid pairing key: {key!r}")
            if key in output:
                raise ValueError(f"{label} contains duplicate pairing key: {key!r}")
            if not _valid_probability(row.get("candidate_p")):
                raise ValueError(f"{label}[{index}] has an invalid candidate probability")
            try:
                outcome = float(row.get("outcome"))
            except (TypeError, ValueError):
                outcome = float("nan")
            if not math.isfinite(outcome) or outcome not in {0.0, 1.0}:
                raise ValueError(
                    f"{label}[{index}] outcome must be finite binary 0/1"
                )
            output[key] = row
        return output

    base_by_key = indexed(base_rows, "base_rows")
    masked_by_key = indexed(masked_rows, "masked_rows")
    if set(base_by_key) != set(masked_by_key):
        missing_masked = sorted(set(base_by_key) - set(masked_by_key), key=repr)
        missing_base = sorted(set(masked_by_key) - set(base_by_key), key=repr)
        raise ValueError(
            "base and masked candidate row keys differ; "
            f"missing_masked={missing_masked!r}; missing_base={missing_base!r}"
        )

    paired_identity_fields = (
        "market_id",
        "snapshot_id",
        "target_date",
        "bin_type",
        "bin_value",
        "bin_value_hi",
        "outcome",
        "settlement_source",
        "market_yes",
        "candidate_cutoff_hour",
        "cutoff_hour",
        "candidate_cutoff_regime",
        "cutoff_regime",
        "settlement_distance_bucket",
        "settlement_distance",
    )
    output = []
    for key in sorted(base_by_key, key=repr):
        base = base_by_key[key]
        masked = masked_by_key[key]
        mismatched = [
            field
            for field in paired_identity_fields
            if base.get(field) != masked.get(field)
        ]
        if mismatched:
            raise ValueError(
                "base and masked row labels/provenance differ for "
                f"{key!r}: {','.join(mismatched)}"
            )
        base_p = base.get("candidate_p")
        variant_p = masked.get("candidate_p")
        market_id = base.get("market_id") or ""
        family = "toronto" if market_id == "toronto" else "us_f"
        target_date = base.get("target_date") or ""
        output.append(
            {
                "variant": VARIANT,
                "day": f"{market_id} {target_date}".strip(),
                "family": family,
                "hour": base.get("candidate_cutoff_hour") or base.get("cutoff_hour"),
                "cutoff_regime": (
                    base.get("candidate_cutoff_regime")
                    or base.get("cutoff_regime")
                    or cutoff_regime(base.get("candidate_cutoff_hour") or base.get("cutoff_hour"))
                ),
                "settlement_distance": _settlement_distance_bucket(
                    base.get("settlement_distance_bucket") or base.get("settlement_distance")
                ),
                "settlement_source": base.get("settlement_source"),
                "y": int(float(base.get("outcome"))),
                "base_p": float(base_p),
                "variant_p": float(variant_p),
                "market_yes": base.get("market_yes"),
            }
        )
    return output


def _same_output_target(left, right):
    left = Path(left)
    right = Path(right)
    left_resolved = left.resolve(strict=False)
    right_resolved = right.resolve(strict=False)
    if left_resolved == right_resolved:
        return True
    if left.exists() and right.exists():
        try:
            return left.samefile(right)
        except OSError:
            return True
    return False


def _preflight_output_paths(
    json_out,
    report_out,
    merged_out=None,
    *,
    input_paths=None,
    protected_input_roots=None,
):
    """Reject mirrored/runtime targets and aliases before any input is read."""

    outputs = {
        "json_out": Path(json_out),
        "report_out": Path(report_out),
    }
    if merged_out is not None:
        outputs["merged_source_family_ablation_out"] = Path(merged_out)
    data_root = data_path().resolve(strict=False)
    resolved = {}
    for label, path in outputs.items():
        target = path.resolve(strict=False)
        resolved[label] = target
        try:
            target.relative_to(data_root)
        except ValueError:
            pass
        else:
            raise ValueError(
                f"{label} must stay outside the mirrored/read-only data tree: {target}"
            )
    labels = list(outputs)
    for index, left_label in enumerate(labels):
        for right_label in labels[index + 1 :]:
            if _same_output_target(outputs[left_label], outputs[right_label]):
                raise ValueError(
                    f"output paths alias one another: {left_label} and {right_label}"
                )
    for input_label, input_path in (input_paths or {}).items():
        if input_path in (None, ""):
            continue
        for output_label, output_path in outputs.items():
            if _same_output_target(output_path, input_path):
                raise ValueError(
                    f"{output_label} aliases input {input_label}"
                )
    for root_label, input_root in (protected_input_roots or {}).items():
        if input_root in (None, ""):
            continue
        input_root = Path(input_root).resolve(strict=False)
        for output_label, output_path in resolved.items():
            try:
                output_path.relative_to(input_root)
            except ValueError:
                continue
            raise ValueError(
                f"{output_label} must not write inside input root {root_label}"
            )
    for label, target in resolved.items():
        if target.exists():
            raise ValueError(
                f"{label} already exists; research generations refuse overwrite: {target}"
            )
    return resolved


def build_ablation_payload(
    rows,
    *,
    artifact_path=None,
    artifact_hash=None,
    artifact_receipt=None,
    corpus_manifest=None,
    split_dates=None,
    input_receipts=None,
    evidence_mode=EVIDENCE_MODE_RESEARCH,
    generated_at_utc=None,
):
    if evidence_mode == EVIDENCE_MODE_OPERATIONAL:
        raise ValueError(
            "operational reanalysis evidence is disabled until base and masked "
            "arms consume one sealed captured-input generation"
        )
    frame = pd.DataFrame(rows)
    summaries, day_tables = summarize(frame)
    day_meta_by_id = {}
    for row in rows:
        market_day = str(row.get("day") or "")
        if not market_day:
            continue
        source = row.get("settlement_source")
        previous = day_meta_by_id.get(market_day)
        if previous is not None and previous.get("settlement_source") != source:
            raise ValueError(
                f"inconsistent settlement provenance for market-day {market_day}"
            )
        day_meta_by_id[market_day] = {
            "market_day": market_day,
            "settlement_source": source,
        }
    day_meta = [day_meta_by_id[key] for key in sorted(day_meta_by_id)]
    split_dates = split_dates or {}
    paired_inference = paired_day_inference(day_tables, split_dates)
    robustness_inference = paired_inference_sensitivities(
        day_tables,
        day_meta,
        split_dates=split_dates,
        required_market_ids=tuple(sorted(REGISTRY)),
    )
    market_inference = paired_market_inference(
        day_tables,
        split_dates,
        day_meta=day_meta,
    )
    receipt = dict(artifact_receipt or {})
    if artifact_hash and receipt and artifact_hash != receipt.get("sha256"):
        raise ValueError("claimed candidate artifact hash differs from stable file receipt")
    effective_hash = receipt.get("sha256") or artifact_hash
    if evidence_mode == EVIDENCE_MODE_OPERATIONAL:
        receipt_contract = receipt_shape_contract(
            receipt,
            label="candidate artifact",
        )
        if receipt_contract["status"] != "PASS":
            raise ValueError(
                "operational reanalysis evidence requires a stable candidate artifact receipt: "
                + "; ".join(receipt_contract["blockers"])
            )
    model_binding = {
        "status": (
            "BOUND_CANDIDATE_ARTIFACT"
            if evidence_mode == EVIDENCE_MODE_OPERATIONAL
            else "RESEARCH_UNBOUND"
        ),
        "binding_kind": "candidate_artifact",
        "promotion_evidence_binding": evidence_mode == EVIDENCE_MODE_OPERATIONAL,
        "artifact_path": receipt.get("path") or (
            str(Path(artifact_path).resolve()) if artifact_path else None
        ),
        "artifact_sha256": effective_hash,
        "prediction_mode": "band_binary",
        "serving_or_release_authorization": False,
    }
    receipts = dict(input_receipts or {})
    if receipt:
        receipts["artifact"] = receipt
    payload = build_payload(
        summaries,
        day_tables,
        day_meta,
        [VARIANT],
        False,
        summarize_slice_effects(frame),
        corpus_manifest,
        paired_inference,
        robustness_inference,
        market_inference,
        split_dates,
        model_binding=model_binding,
        input_receipts=receipts,
        evidence_mode=evidence_mode,
    )
    payload["generated_at_utc"] = generated_at_utc or _utc_iso()
    payload["evidence_source"] = EVIDENCE_SOURCE
    payload["artifact"] = {
        "path": model_binding["artifact_path"],
        "sha256": effective_hash,
        "size_bytes": receipt.get("size_bytes"),
        "prediction_mode": model_binding["prediction_mode"],
    }
    for variant in payload.get("variants") or []:
        if variant.get("variant") == VARIANT:
            variant["evidence_source"] = EVIDENCE_SOURCE
            variant["base_model"] = "pooled_candidate_artifact_full_reanalysis"
            variant["variant_model"] = "pooled_candidate_artifact_reanalysis_masked"
    for row in payload.get("slice_effects") or []:
        if row.get("variant") == VARIANT:
            row["evidence_source"] = EVIDENCE_SOURCE
    return payload


def _variant_names(payload):
    return {
        row.get("variant")
        for row in payload.get("variants") or []
        if row.get("variant")
    }


def merge_source_family_ablation(base_payload, supplemental_payload):
    """Fail closed until both replay arms have a sealed execution closure."""

    del base_payload, supplemental_payload
    raise ValueError(
        "candidate-bound reanalysis publication is disabled until a sealed "
        "captured-input generation binds both ablation arms"
    )


def render_report(payload):
    variants = payload.get("variants") or []
    slices = payload.get("slice_effects") or []
    summary = payload.get("summary") or {}
    lines = [
        "# Reanalysis Synoptic Band Ablation",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Evidence source: `{payload.get('evidence_source')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Rows scored", summary.get("rows_scored")],
            ["Variants", summary.get("variant_count")],
            ["Slice rows", summary.get("slice_effect_count")],
            ["Artifact", (payload.get("artifact") or {}).get("path") or "-"],
        ],
    )
    lines += ["", "## Variant", ""]
    lines += markdown_table(
        ["Variant", "Rows", "Days", "Delta", "Days helped", "Days hurt"],
        [
            [
                row.get("variant"),
                row.get("n"),
                row.get("days"),
                fmt_signed(row.get("delta"), 4),
                row.get("days_source_helped"),
                row.get("days_source_hurt"),
            ]
            for row in variants
        ],
    )
    lines += ["", "## Slices", ""]
    lines += markdown_table(
        ["Slice", "Market", "Regime", "Distance", "Rows", "Delta"],
        [
            [
                row.get("slice"),
                row.get("market_id") or "-",
                row.get("cutoff_regime") or "-",
                row.get("settlement_distance") or "-",
                row.get("n"),
                fmt_signed(row.get("delta"), 4),
            ]
            for row in slices[:80]
        ],
    )
    return "\n".join(lines) + "\n"


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json_exclusive(path, payload)
    return path


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text_exclusive(path, render_report(payload))
    return path


def run_report(
    *,
    corpus=DEFAULT_CORPUS,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    artifact=DEFAULT_BAND_ARTIFACT,
    artifact_sha256=None,
    json_out=DEFAULT_JSON_OUT,
    report_out=DEFAULT_REPORT_OUT,
    merged_source_family_ablation_out=None,
    clob_max_age_seconds=180.0,
    operational_evidence=False,
    tune_dates_file=None,
    holdout_dates_file=None,
):
    _preflight_output_paths(
        json_out,
        report_out,
        merged_source_family_ablation_out,
        input_paths={
            "corpus": corpus,
            "artifact": artifact,
            "tune_dates_file": tune_dates_file,
            "holdout_dates_file": holdout_dates_file,
        },
        protected_input_roots={"snapshots_root": snapshots_root},
    )
    if operational_evidence:
        raise ValueError(
            "operational reanalysis evidence is disabled until base and masked "
            "arms consume one sealed captured-input generation"
        )
    if merged_source_family_ablation_out:
        raise ValueError(
            "candidate-bound reanalysis publication is disabled until a sealed "
            "captured-input generation binds both ablation arms"
        )
    input_receipts = {}
    split_dates = {}
    if operational_evidence:
        manifest, input_receipts["corpus"] = _load_manifest_with_receipt(corpus)
        split_dates["tune"], input_receipts["tune_dates"] = (
            read_date_manifest_with_receipt(tune_dates_file)
        )
        split_dates["holdout"], input_receipts["holdout_dates"] = (
            read_date_manifest_with_receipt(holdout_dates_file)
        )
    else:
        manifest = load_manifest(corpus)
    artifact_path = Path(artifact)
    loaded_artifact, artifact_receipt = _load_bound_artifact(
        artifact_path,
        expected_sha256=artifact_sha256,
    )
    folders = [
        str(folder)
        for folder in folders_from_manifest_strict(manifest, snapshots_root)
    ]
    runtime_manifest = _runtime_manifest_bound_to_folders(
        manifest,
        folders,
        snapshots_root,
    )
    replay_results = run_replay_backtest(
        folders,
        daily_summary_path=None,
        overrides={},
        out_path=None,
        include_reconstructed=manifest.get("include_reconstructed", False),
        write=False,
        corpus_manifest=manifest,
    )
    corpus_warnings = replay_results.get("corpus_warnings") or []
    if corpus_warnings:
        raise ValueError(
            "reanalysis replay input verification produced corpus warnings: "
            + "; ".join(str(value) for value in corpus_warnings)
        )
    pristine_artifact = copy.deepcopy(loaded_artifact)
    captured_inputs = _capture_candidate_inputs(
        runtime_manifest,
        snapshots_root,
        copy.deepcopy(pristine_artifact),
        clob_max_age_seconds=clob_max_age_seconds,
    )
    (
        base_rows,
        base_diagnostics,
        masked_rows,
        masked_diagnostics,
    ) = _score_captured_ablation_arms(
        captured_inputs,
        pristine_artifact,
        replay_results,
    )
    rows = paired_ablation_rows(base_rows, masked_rows)
    payload = build_ablation_payload(
        rows,
        artifact_path=artifact_path,
        artifact_hash=artifact_receipt["sha256"],
        artifact_receipt=artifact_receipt,
        corpus_manifest=manifest,
        split_dates=split_dates,
        input_receipts=input_receipts,
        evidence_mode=(
            EVIDENCE_MODE_OPERATIONAL
            if operational_evidence
            else EVIDENCE_MODE_RESEARCH
        ),
    )
    payload["diagnostics"] = {
        "base": base_diagnostics,
        "masked": masked_diagnostics,
        "paired_rows": len(rows),
    }
    rendered_report = render_report(payload)
    json.dumps(payload, sort_keys=True, allow_nan=False)
    Path(report_out).parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text_exclusive(report_out, rendered_report)
    # The primary JSON is the completion leaf and must appear only after every
    # companion leaf has been published atomically.
    write_json(json_out, payload)
    if merged_source_family_ablation_out:
        base_path = Path(merged_source_family_ablation_out)
        if base_path.exists():
            base_payload, base_receipt = stable_json_artifact(base_path)
            if base_receipt["status"] != "PASS":
                raise ValueError(
                    "base source-family ablation could not be read stably: "
                    + "; ".join(base_receipt.get("blockers") or [])
                )
        else:
            base_payload = {}
        published = merge_source_family_ablation(base_payload, payload)
        write_json(base_path, published)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build band-level reanalysis sidecar ablation evidence.")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--artifact", default=str(DEFAULT_BAND_ARTIFACT))
    parser.add_argument(
        "--artifact-sha256",
        required=True,
        help=(
            "Caller-supplied integrity digest for the retired candidate lane. "
            "It is checked, but cannot authorize pickle deserialization "
            "without an independent trust anchor."
        ),
    )
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument(
        "--merged-source-family-ablation-out",
        default="",
        help=(
            "Retired and blocked: candidate-bound reanalysis cannot be merged "
            "into operational source-family evidence."
        ),
    )
    parser.add_argument("--clob-max-age-seconds", type=float, default=180.0)
    parser.add_argument(
        "--operational-evidence",
        action="store_true",
        help=(
            "Retired and blocked: this lane cannot emit operational or "
            "promotion-authorizing evidence."
        ),
    )
    parser.add_argument("--tune-dates-file", default=None)
    parser.add_argument("--holdout-dates-file", default=None)
    args = parser.parse_args(argv)
    payload = run_report(
        corpus=args.corpus,
        snapshots_root=args.snapshots_root,
        artifact=args.artifact,
        artifact_sha256=args.artifact_sha256,
        json_out=args.json_out,
        report_out=args.report_out,
        merged_source_family_ablation_out=args.merged_source_family_ablation_out or None,
        clob_max_age_seconds=args.clob_max_age_seconds,
        operational_evidence=args.operational_evidence,
        tune_dates_file=args.tune_dates_file,
        holdout_dates_file=args.holdout_dates_file,
    )
    print(f"Reanalysis synoptic band ablation: {payload.get('summary', {}).get('rows_scored', 0)} rows")
    print(f"JSON written to {args.json_out}")
    print(f"Report written to {args.report_out}")
    if args.merged_source_family_ablation_out:
        print(
            "Standalone source-family ablation written to "
            f"{args.merged_source_family_ablation_out}"
        )
    return payload


if __name__ == "__main__":
    main()

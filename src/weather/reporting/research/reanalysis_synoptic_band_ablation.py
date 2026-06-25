"""Band-level reanalysis sidecar ablation for the physical-family ratchet.

The generic source-family ablation knocks out live source payloads. Reanalysis
sidecars are artifact feature rows, so this report compares the same pooled
candidate artifact with its reanalysis feature family intact and then masked
through the production reanalysis lane hook.
"""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from weather.backtesting.replay_ablation import (
    build_payload,
    summarize,
    summarize_slice_effects,
)
from weather.artifacts import sha256_file
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
from weather.market.market_microstructure_features import snapshot_band_key
from weather.market.market_registry import REGISTRY
from weather.paths import data_path
from weather.reporting.formatting import fmt_signed, markdown_table
from weather.reporting.promotion.promotion_corpus import (
    DEFAULT_OUT as DEFAULT_CORPUS,
    folders_from_manifest,
    load_manifest,
)
from weather.calibration.pooled_candidate_scoring import load_artifact


DEFAULT_JSON_OUT = data_path("backtest") / "reanalysis_synoptic_band_ablation.json"
DEFAULT_REPORT_OUT = data_path("backtest") / "reanalysis_synoptic_band_ablation.md"
DEFAULT_SOURCE_FAMILY_ABLATION = data_path("backtest") / "source_family_ablation.json"
VARIANT = "reanalysis_synoptic"
EVIDENCE_SOURCE = "candidate_artifact_band_ablation"


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


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


def _candidate_rows(manifest, snapshots_root, artifact, replay_results, clob_max_age_seconds=180.0):
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
    rows, coverage = attach_band_candidate_probabilities(
        replay_results,
        feature_rows,
        artifact,
        family_unit,
        clob_features=clob_features,
        source_freshness=source_freshness,
    )
    for row in rows:
        row["candidate_cutoff_regime"] = cutoff_regime(row.get("candidate_cutoff_hour"))
    diagnostics.update(clob_diagnostics)
    diagnostics.update(source_freshness_diagnostics)
    return rows, {
        "feature_rows": len(feature_rows),
        "coverage": coverage,
        "diagnostics": diagnostics,
    }


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
    masked_by_key = {_row_key(row): row for row in masked_rows}
    output = []
    for base in base_rows:
        masked = masked_by_key.get(_row_key(base))
        if not masked:
            continue
        base_p = base.get("candidate_p")
        variant_p = masked.get("candidate_p")
        if not _valid_probability(base_p) or not _valid_probability(variant_p):
            continue
        if base.get("outcome") in (None, ""):
            continue
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
                "y": int(float(base.get("outcome"))),
                "base_p": float(base_p),
                "variant_p": float(variant_p),
                "market_yes": base.get("market_yes"),
            }
        )
    return output


def build_ablation_payload(rows, *, artifact_path=None, artifact_hash=None, generated_at_utc=None):
    frame = pd.DataFrame(rows)
    summaries, day_tables = summarize(frame)
    payload = build_payload(
        summaries,
        day_tables,
        [{"day": row["day"]} for row in rows],
        [VARIANT],
        False,
        summarize_slice_effects(frame),
    )
    payload["generated_at_utc"] = generated_at_utc or _utc_iso()
    payload["evidence_source"] = EVIDENCE_SOURCE
    payload["artifact"] = {
        "path": str(artifact_path) if artifact_path else None,
        "artifact_hash": artifact_hash,
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
    variants_to_replace = _variant_names(supplemental_payload)
    variants = [
        row for row in (base_payload.get("variants") or [])
        if row.get("variant") not in variants_to_replace
    ] + list(supplemental_payload.get("variants") or [])
    day_effects = {
        key: value
        for key, value in (base_payload.get("day_effects") or {}).items()
        if key not in variants_to_replace
    }
    day_effects.update(supplemental_payload.get("day_effects") or {})
    slice_effects = [
        row for row in (base_payload.get("slice_effects") or [])
        if row.get("variant") not in variants_to_replace
    ] + list(supplemental_payload.get("slice_effects") or [])
    requested = []
    for value in list(base_payload.get("requested_variants") or []) + list(
        supplemental_payload.get("requested_variants") or []
    ):
        if value not in requested:
            requested.append(value)
    merged = {
        **base_payload,
        "generated_at_utc": _utc_iso(),
        "requested_variants": requested,
        "variants": variants,
        "day_effects": day_effects,
        "slice_effects": slice_effects,
    }
    merged["summary"] = {
        **(base_payload.get("summary") or {}),
        "variant_count": len(variants),
        "rows_scored": int(sum(row.get("n") or row.get("rows") or 0 for row in variants)),
        "slice_effect_count": len(slice_effects),
    }
    return merged


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
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def run_report(
    *,
    corpus=DEFAULT_CORPUS,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    artifact=DEFAULT_BAND_ARTIFACT,
    json_out=DEFAULT_JSON_OUT,
    report_out=DEFAULT_REPORT_OUT,
    merged_source_family_ablation_out=None,
    clob_max_age_seconds=180.0,
):
    manifest = load_manifest(corpus)
    artifact_path = Path(artifact)
    loaded_artifact = load_artifact(artifact_path)
    folders = [str(folder) for folder in folders_from_manifest(manifest, snapshots_root)]
    replay_results = run_replay_backtest(
        folders,
        daily_summary_path=None,
        overrides={},
        out_path=None,
        include_reconstructed=manifest.get("include_reconstructed", False),
        write=False,
        corpus_manifest=manifest,
    )
    base_rows, base_diagnostics = _candidate_rows(
        manifest,
        snapshots_root,
        loaded_artifact,
        replay_results,
        clob_max_age_seconds=clob_max_age_seconds,
    )
    masked_rows, masked_diagnostics = _candidate_rows(
        manifest,
        snapshots_root,
        masked_reanalysis_artifact(loaded_artifact),
        replay_results,
        clob_max_age_seconds=clob_max_age_seconds,
    )
    rows = paired_ablation_rows(base_rows, masked_rows)
    payload = build_ablation_payload(
        rows,
        artifact_path=artifact_path,
        artifact_hash=loaded_artifact.get("artifact_hash") or sha256_file(artifact_path),
    )
    payload["diagnostics"] = {
        "base": base_diagnostics,
        "masked": masked_diagnostics,
        "paired_rows": len(rows),
    }
    write_json(json_out, payload)
    write_report(report_out, payload)
    if merged_source_family_ablation_out:
        base_path = Path(merged_source_family_ablation_out)
        base_payload = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {}
        merged = merge_source_family_ablation(base_payload, payload)
        write_json(base_path, merged)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build band-level reanalysis sidecar ablation evidence.")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--artifact", default=str(DEFAULT_BAND_ARTIFACT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument(
        "--merged-source-family-ablation-out",
        default="",
        help="Optional source_family_ablation.json path to update with this reanalysis variant.",
    )
    parser.add_argument("--clob-max-age-seconds", type=float, default=180.0)
    args = parser.parse_args(argv)
    payload = run_report(
        corpus=args.corpus,
        snapshots_root=args.snapshots_root,
        artifact=args.artifact,
        json_out=args.json_out,
        report_out=args.report_out,
        merged_source_family_ablation_out=args.merged_source_family_ablation_out or None,
        clob_max_age_seconds=args.clob_max_age_seconds,
    )
    print(f"Reanalysis synoptic band ablation: {payload.get('summary', {}).get('rows_scored', 0)} rows")
    print(f"JSON written to {args.json_out}")
    print(f"Report written to {args.report_out}")
    if args.merged_source_family_ablation_out:
        print(f"Merged source-family ablation written to {args.merged_source_family_ablation_out}")
    return payload


if __name__ == "__main__":
    main()

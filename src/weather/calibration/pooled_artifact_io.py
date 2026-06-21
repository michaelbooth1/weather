"""Implementation slice extracted from src/weather/calibration/pooled_feature_model.py."""

from weather.calibration.pooled_training import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def write_artifact(artifact, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(artifact, handle)
    return path


def load_artifact(path):
    with Path(path).open("rb") as handle:
        return pickle.load(handle)


MERGE_COMPATIBILITY_KEYS = (
    "schema_version",
    "feature_schema_version",
    "family_unit",
    "prediction_mode",
    "objective",
    "feature_subset",
    "feature_subset_contract",
    "dynamic_source_state_enabled",
    "dynamic_source_state_columns",
    "source_family_lanes",
    "reanalysis_promotion_lane",
    "support",
)


def _merge_signature(artifact):
    return {
        key: artifact.get(key)
        for key in MERGE_COMPATIBILITY_KEYS
    }


def _artifact_model_hours(artifact):
    return sorted(int(hour) for hour in (artifact.get("models") or {}))


def _validate_band_merge_payload(artifact, label):
    payload = artifact.get(BAND_MERGE_PAYLOAD_KEY) or {}
    rows = payload.get("rows") or []
    probabilities = payload.get("probabilities") or []
    if not rows or not probabilities:
        raise ValueError(f"{label} is missing {BAND_MERGE_PAYLOAD_KEY}; retrain shard with --write-merge-payload")
    if len(rows) != len(probabilities):
        raise ValueError(
            f"{label} merge payload has mismatched rows/probabilities "
            f"({len(rows)} != {len(probabilities)})"
        )
    return payload


def merge_band_postprocess(rows, probabilities, base_postprocess):
    postprocess = dict(base_postprocess or {})
    adjacent = fit_adjacent_calibration(rows, probabilities)
    postprocess["adjacent_calibration"] = adjacent
    adjacent_probabilities = [
        apply_adjacent_calibration(probability, row, config=postprocess)
        for row, probability in zip(rows, probabilities)
    ]
    calibrated_probabilities = adjacent_probabilities
    if postprocess.get("exact_winner_catchup_enabled", False):
        exact = fit_exact_winner_catchup(
            rows,
            adjacent_probabilities,
            guardrail_rows=rows,
            guardrail_probabilities=adjacent_probabilities,
            normalization_gamma=postprocess.get("partition_normalization_gamma", 1.25),
        )
        postprocess["exact_winner_catchup"] = exact
        calibrated_probabilities = [
            apply_exact_winner_catchup(probability, row, config=postprocess)
            for row, probability in zip(rows, adjacent_probabilities)
        ]
    market_bias = fit_market_bias_calibration(rows, calibrated_probabilities)
    postprocess["market_bias_calibration"] = market_bias
    postprocess["market_bias_calibration_enabled"] = bool(market_bias.get("enabled"))
    return postprocess


def merge_pooled_band_artifacts(artifacts, required_hours=None, shard_paths=None):
    artifacts = list(artifacts or [])
    shard_paths = [str(path) for path in (shard_paths or [])]
    if not artifacts:
        raise ValueError("At least one band artifact shard is required.")
    base_signature = _merge_signature(artifacts[0])
    if base_signature.get("prediction_mode") != "band_binary":
        raise ValueError("Only band_binary artifacts can be merged.")

    merged = {
        key: value
        for key, value in artifacts[0].items()
        if key not in {"models", BAND_MERGE_PAYLOAD_KEY}
    }
    merged["models"] = {}
    merged_hours = set()
    merge_rows = []
    merge_probabilities = []
    shard_summaries = []
    for index, artifact in enumerate(artifacts):
        label = shard_paths[index] if index < len(shard_paths) else f"shard {index + 1}"
        signature = _merge_signature(artifact)
        if signature != base_signature:
            raise ValueError(f"{label} is incompatible with the first shard.")
        payload = _validate_band_merge_payload(artifact, label)
        hours = _artifact_model_hours(artifact)
        duplicates = sorted(set(hours) & merged_hours)
        if duplicates:
            raise ValueError(f"{label} duplicates already-merged hour(s): {duplicates}")
        merged_hours.update(hours)
        merged["models"].update(artifact.get("models") or {})
        merge_rows.extend(payload.get("rows") or [])
        merge_probabilities.extend(payload.get("probabilities") or [])
        shard_summaries.append({
            "path": label,
            "hours": hours,
            "merge_rows": len(payload.get("rows") or []),
        })

    required = set(int(hour) for hour in (required_hours or []))
    missing = sorted(required - merged_hours)
    if missing:
        raise ValueError(f"Merged artifact is missing required hour(s): {missing}")

    merged["postprocess"] = merge_band_postprocess(
        merge_rows,
        merge_probabilities,
        artifacts[0].get("postprocess") or {},
    )
    for bundle in merged["models"].values():
        if isinstance(bundle, dict):
            bundle["postprocess"] = dict(merged["postprocess"])
    model_feature_names = sorted({
        feature
        for bundle in merged["models"].values()
        for feature in (bundle.get("feature_names") or [])
    })
    merged["weak_input_family_preflight"] = weak_input_training_preflight(
        model_feature_names,
        None,
    )
    merged["trained_at"] = datetime.now().isoformat()
    merged["training_shards"] = {
        "shard_count": len(artifacts),
        "hours": sorted(merged_hours),
        "required_hours": sorted(required),
        "postprocess_fit_rows": len(merge_rows),
        "shards": shard_summaries,
    }
    return merged


def merge_pooled_band_artifact_shards(paths, required_hours=None):
    paths = [Path(path) for path in (paths or [])]
    artifacts = [load_artifact(path) for path in paths]
    return merge_pooled_band_artifacts(
        artifacts,
        required_hours=required_hours,
        shard_paths=paths,
    )


def write_band_shard_merge_report(path, artifact, artifact_path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    shards = artifact.get("training_shards") or {}
    postprocess = artifact.get("postprocess") or {}
    market_bias = postprocess.get("market_bias_calibration") or {}
    lines = [
        "# F-Family Pooled Band Shard Merge",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Artifact: `{artifact_path}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Schema", artifact.get("schema_version")],
            ["Feature schema", artifact.get("feature_schema_version")],
            ["Objective", artifact.get("objective")],
            ["Family unit", artifact.get("family_unit")],
            ["Merged hours", ", ".join(str(hour) for hour in shards.get("hours") or [])],
            ["Required hours", ", ".join(str(hour) for hour in shards.get("required_hours") or [])],
            ["Shard count", shards.get("shard_count")],
            ["Postprocess fit rows", shards.get("postprocess_fit_rows")],
            ["Adjacent contexts", (postprocess.get("adjacent_calibration") or {}).get("context_count", 0)],
            ["Market bias enabled", bool(market_bias.get("enabled"))],
            ["Market bias contexts", market_bias.get("context_count", 0)],
        ],
    )
    rows = []
    for shard in shards.get("shards") or []:
        rows.append([
            shard.get("path"),
            ", ".join(str(hour) for hour in shard.get("hours") or []),
            shard.get("merge_rows"),
        ])
    if rows:
        lines += [
            "",
            "## Shards",
            "",
        ]
        lines += markdown_table(["Path", "Hours", "Merge Rows"], rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]

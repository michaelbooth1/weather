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
    "postprocess",
    "postprocess_fit_contract",
)

IDENTITY_POSTPROCESS_POLICY = "identity_until_nested_inner_oof"
IDENTITY_SERVED_PARAMETERS = {
    "temperature": 1.0,
    "adjacent_calibration": "identity_disabled",
    "exact_winner_catchup": "identity_disabled",
    "market_bias_calibration": "identity_disabled",
}


def _merge_signature(artifact):
    return {
        key: artifact.get(key)
        for key in MERGE_COMPATIBILITY_KEYS
    }


def _artifact_model_hours(artifact):
    return sorted(int(hour) for hour in (artifact.get("models") or {}))


def _outer_holdout_payload_row_count(artifact, label):
    payload = artifact.get(BAND_MERGE_PAYLOAD_KEY) or {}
    rows = payload.get("rows") or []
    probabilities = payload.get("probabilities") or []
    if len(rows) != len(probabilities):
        raise ValueError(
            f"{label} merge payload has mismatched rows/probabilities "
            f"({len(rows)} != {len(probabilities)})"
        )
    return len(rows)


def _validate_identity_band_shard(artifact, label):
    contract = artifact.get("postprocess_fit_contract")
    if not isinstance(contract, dict):
        raise ValueError(
            f"{label} is a legacy band shard without postprocess_fit_contract"
        )
    contract_checks = {
        "schema_version": contract.get("schema_version")
        == "legacy_pooled_postprocess_fit_contract_v1",
        "status": contract.get("status") == "PASS",
        "policy": contract.get("policy") == IDENTITY_POSTPROCESS_POLICY,
        "outer_holdout_used_for_parameter_fit": contract.get(
            "outer_holdout_used_for_parameter_fit"
        ) is False,
        "outer_holdout_fit_rows": (
            isinstance(contract.get("outer_holdout_fit_rows"), int)
            and not isinstance(contract.get("outer_holdout_fit_rows"), bool)
            and contract.get("outer_holdout_fit_rows") == 0
        ),
        "served_parameters": contract.get("served_parameters")
        == IDENTITY_SERVED_PARAMETERS,
        "promotion_permission": contract.get("promotion_permission")
        == "forbidden_without_nested_inner_oof_receipts",
    }
    failed_contract = sorted(
        key for key, passed in contract_checks.items() if not passed
    )
    if failed_contract:
        raise ValueError(
            f"{label} has non-identity postprocess_fit_contract: "
            + ", ".join(failed_contract)
        )

    postprocess = artifact.get("postprocess")
    if not isinstance(postprocess, dict):
        raise ValueError(f"{label} is missing postprocess configuration")
    disabled_flags = (
        "adjacent_calibration_enabled",
        "exact_winner_catchup_enabled",
        "market_bias_calibration_enabled",
    )
    empty_parameters = (
        "adjacent_calibration",
        "exact_winner_catchup",
        "market_bias_calibration",
    )
    failed_postprocess = sorted([
        key for key in disabled_flags if postprocess.get(key) is not False
    ] + [
        key for key in empty_parameters if postprocess.get(key) != {}
    ])
    if failed_postprocess:
        raise ValueError(
            f"{label} has learned/non-identity postprocess parameters: "
            + ", ".join(failed_postprocess)
        )

    models = artifact.get("models") or {}
    if not isinstance(models, dict) or not models:
        raise ValueError(f"{label} has no band models")
    for hour, bundle in models.items():
        if not isinstance(bundle, dict):
            raise ValueError(f"{label} model hour {hour} is invalid")
        raw_temperature = bundle.get("temperature")
        if isinstance(raw_temperature, bool) or not isinstance(
            raw_temperature, (int, float)
        ):
            raise ValueError(f"{label} model hour {hour} has invalid temperature")
        temperature = float(raw_temperature)
        if temperature != 1.0:
            raise ValueError(
                f"{label} model hour {hour} has non-identity temperature"
            )
        if bundle.get("postprocess") != postprocess:
            raise ValueError(
                f"{label} model hour {hour} postprocess differs from its shard"
            )


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
    ignored_outer_holdout_rows = 0
    shard_summaries = []
    for index, artifact in enumerate(artifacts):
        label = shard_paths[index] if index < len(shard_paths) else f"shard {index + 1}"
        _validate_identity_band_shard(artifact, label)
        signature = _merge_signature(artifact)
        if signature != base_signature:
            raise ValueError(f"{label} is incompatible with the first shard.")
        payload_rows = _outer_holdout_payload_row_count(artifact, label)
        hours = _artifact_model_hours(artifact)
        duplicates = sorted(set(hours) & merged_hours)
        if duplicates:
            raise ValueError(f"{label} duplicates already-merged hour(s): {duplicates}")
        merged_hours.update(hours)
        merged["models"].update(artifact.get("models") or {})
        ignored_outer_holdout_rows += payload_rows
        shard_summaries.append({
            "path": label,
            "hours": hours,
            "outer_holdout_payload_rows_ignored": payload_rows,
        })

    required = set(int(hour) for hour in (required_hours or []))
    missing = sorted(required - merged_hours)
    if missing:
        raise ValueError(f"Merged artifact is missing required hour(s): {missing}")

    # Never fit a served transform on shard outer-holdout payloads.  The
    # validated, identity-only postprocess is copied exactly from compatible
    # shards; nested inner-OOF receipts are required before any learned stage.
    merged["postprocess"] = dict(artifacts[0]["postprocess"])
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
        "postprocess_fit_rows": 0,
        "outer_holdout_payload_rows_ignored": ignored_outer_holdout_rows,
        "postprocess_policy": IDENTITY_POSTPROCESS_POLICY,
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
            [
                "Outer-holdout payload rows ignored",
                shards.get("outer_holdout_payload_rows_ignored"),
            ],
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
            shard.get("outer_holdout_payload_rows_ignored"),
        ])
    if rows:
        lines += [
            "",
            "## Shards",
            "",
        ]
        lines += markdown_table(
            ["Path", "Hours", "Outer-Holdout Rows Ignored"],
            rows,
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]

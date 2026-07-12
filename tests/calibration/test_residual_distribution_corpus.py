from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.calibration.residual_distribution_corpus import (
    ResidualCorpusError,
    captured_comparator_probabilities,
    collapse_to_predeclared_checkpoints,
    materialize_residual_training_corpus,
    validate_residual_training_row,
    verify_residual_corpus_manifest,
)
from weather.operations.event_day_manifest import (
    manifest_content_hash,
    write_event_day_manifest,
)


def _replay(snapshot_id: str, local_time: str, *, target_date: str = "2026-07-01"):
    return {
        "schema_version": "toronto_replay_inputs_v0.1",
        "snapshot_id": snapshot_id,
        "target_date": target_date,
        "captured_at_local": local_time,
        "captured_at_utc": datetime.fromisoformat(local_time).astimezone(timezone.utc).isoformat(),
        "built_at": local_time,
        "sources": {
            "open_meteo": {
                "status": "fresh",
                "ok": True,
                "stale": False,
                "source_family": "open_meteo",
                "fetched_at": local_time,
            }
        },
    }


def test_checkpoint_selection_is_first_nonnegative_and_never_substitutes():
    rows = [
        _replay("before", "2026-07-01T07:59:00-04:00"),
        _replay("chosen", "2026-07-01T08:03:00-04:00"),
        _replay("later", "2026-07-01T08:09:00-04:00"),
    ]
    selected, excluded = collapse_to_predeclared_checkpoints(
        rows,
        target_date="2026-07-01",
        cutoff_hours=(8, 9),
        max_lateness_minutes=10,
    )
    assert [row["snapshot_id"] for row in selected] == ["chosen"]
    assert selected[0]["checkpoint_lateness_minutes"] == 3.0
    assert excluded[0]["cutoff_hour"] == 9
    assert excluded[0]["reason"] == "checkpoint_missing"


def _write_market_day(folder: Path) -> None:
    folder.mkdir(parents=True)
    settlement = {
        "market_id": "atlanta",
        "target_date": "2026-07-01",
        "settlement_unit": "F",
        "settlement_high": 95.0,
        "promotion_countable": True,
        "quality_grade": "complete",
        "winning_band_kind": "gte",
        "winning_band_value": 94,
        "winning_band_value_hi": 94,
    }
    (folder / "settlement.json").write_text(json.dumps(settlement), encoding="utf-8")
    replay_rows = [
        _replay("s1", "2026-07-01T08:02:00-04:00"),
        _replay("s2", "2026-07-01T08:08:00-04:00"),
    ]
    (folder / "replay_inputs.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in replay_rows),
        encoding="utf-8",
    )
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "snapshot_id",
                "bin_kind",
                "bin_value_c",
                "bin_value_hi_c",
                "range_label",
            ),
        )
        writer.writeheader()
        writer.writerows([
            {
                "snapshot_id": "s1",
                "bin_kind": "lte",
                "bin_value_c": 90,
                "bin_value_hi_c": 90,
                "range_label": "90 or below",
            },
            {
                "snapshot_id": "s1",
                "bin_kind": "gte",
                "bin_value_c": 91,
                "bin_value_hi_c": 91,
                "range_label": "91 or above",
            },
            {
                "snapshot_id": "s2",
                "bin_kind": "lte",
                "bin_value_c": 90,
                "bin_value_hi_c": 90,
                "range_label": "90 or below",
            },
        ])


def _write_proof_market_day(folder: Path, *, include_config_hash: bool = True) -> None:
    _write_market_day(folder)
    release_id = "release-2026-07-01-a"
    release_manifest_sha256 = "a" * 64
    configuration_sha256 = "b" * 64
    runtime_identity = {
        "schema_version": "runtime_identity_v0.1",
        "git_branch": "test",
        "git_commit": "c" * 40,
        "source_fingerprint": "source-test-v1",
        "python_version": "3.12",
    }
    replay_rows = []
    for snapshot_id, local_time in (
        ("s1", "2026-07-01T08:02:00-04:00"),
        ("s2", "2026-07-01T08:08:00-04:00"),
    ):
        row = {
            **_replay(snapshot_id, local_time),
            "release_id": release_id,
            "release_manifest_sha256": release_manifest_sha256,
            "release_identity_status": "verified_serving_binding",
            "base_model_release_bound": True,
            "runtime_identity": runtime_identity,
            "runtime_guard": {"state": "current", "ok": True},
            "model_identity": {"release_id": release_id},
        }
        if include_config_hash:
            row["configuration_sha256"] = configuration_sha256
            row["runtime_guard"]["config_sha256"] = configuration_sha256
        replay_rows.append(row)
    (folder / "replay_inputs.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in replay_rows),
        encoding="utf-8",
    )
    proof_identity = {
        "release_id": release_id,
        "release_manifest_sha256": release_manifest_sha256,
        "runtime_identity": runtime_identity,
    }
    if include_config_hash:
        proof_identity["configuration_sha256"] = configuration_sha256
    (folder / "snapshots.jsonl").write_text(
        json.dumps({
            "schema_version": "snapshot_tape_v0.1",
            "snapshot_id": "s1",
            **proof_identity,
        }) + "\n",
        encoding="utf-8",
    )
    def write_payload_blob(prefix: str, payload: dict) -> tuple[str, str]:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        relative_path = f"{prefix}/sha256/{digest[:2]}/{digest}.json"
        path = folder / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical.encode("utf-8") + b"\n")
        return digest, relative_path

    forecast_hash, forecast_path = write_payload_blob(
        "forecast_payloads",
        {"model": "nbm", "forecast_high": 95},
    )
    (folder / "forecast_payloads.jsonl").write_text(
        json.dumps({
            "schema_version": "forecast_payload_v0.1",
            "snapshot_id": "s1",
            "source": "nbm",
            "payload_hash": forecast_hash,
            "raw_payload_path": forecast_path,
        }) + "\n",
        encoding="utf-8",
    )
    (folder / "source_status.jsonl").write_text(
        json.dumps({
            "schema_version": "source_status_v0.1",
            "snapshot_id": "s1",
            "source": "nbm",
            "status": "fresh",
        }) + "\n",
        encoding="utf-8",
    )
    observation_hash, observation_path = write_payload_blob(
        "observation_payloads",
        {"station_id": "KATL", "temperature": 95},
    )
    (folder / "observation_payloads.jsonl").write_text(
        json.dumps({
            "schema_version": "observation_payload_v0.1",
            "snapshot_id": "s1",
            "source": "metar",
            "payload_hash": observation_hash,
            "raw_payload_path": observation_path,
        }) + "\n",
        encoding="utf-8",
    )
    (folder / "clob_capture_status.jsonl").write_text(
        json.dumps({
            "schema_version": "clob_capture_status_v0.1",
            "snapshot_id": "s1",
            "status": "OK",
        }) + "\n",
        encoding="utf-8",
    )
    (folder / "variant_predictions.jsonl").write_text(
        json.dumps({
            "schema_version": "live_variant_prediction_v0.1",
            "snapshot_id": "not-selected",
            "prediction_status": "skipped",
        }) + "\n",
        encoding="utf-8",
    )
    write_event_day_manifest(folder, snapshots_root=folder.parent)


def test_materializer_hashes_corpus_and_joins_label_after_features(tmp_path):
    folder = tmp_path / "day"
    _write_market_day(folder)

    def feature_builder(_row, **_context):
        return {
            "forecast_high_f": 93.0,
            "forecast_disagreement_f": 2.0,
            "source_failed_count": 0.0,
        }

    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=feature_builder,
        generated_at_utc="2026-07-12T12:00:00+00:00",
    )
    assert len(rows) == 1
    assert rows[0]["snapshot_id"] == "s1"
    assert rows[0]["residual_target_f"] == 2.0
    assert "settlement_high_f" not in rows[0]["features"]
    assert manifest["counts"]["accepted_rows"] == 1
    assert manifest["selection_policy"]["substitution_allowed"] is False
    assert rows[0]["training_evidence_class"] == "research_only"
    assert rows[0]["promotion_training_countable"] is False
    assert manifest["qualification_input_contract"]["status"] == "BLOCK"
    assert verify_residual_corpus_manifest(rows, manifest)["manifest_sha256"]


def test_semantic_event_manifest_and_complete_identity_make_row_countable(tmp_path):
    folder = (
        tmp_path
        / "snapshots"
        / "highest-temperature-in-atlanta-on-july-1-2026"
    )
    _write_proof_market_day(folder)

    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=lambda _row, **_kwargs: {"forecast_high_f": 93.0},
        generated_at_utc="2026-07-12T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["training_evidence_class"] == "release_bound"
    assert rows[0]["promotion_training_countable"] is True
    assert rows[0]["release_identity_proof"]["status"] == "PASS"
    assert manifest["inputs"][0]["semantic_event_day_manifest"]["status"] == "PASS"
    assert manifest["qualification_input_contract"]["status"] == "PASS"
    assert manifest["qualification_input_contract"][
        "per_input_folder_semantic_verification_required"
    ] is True
    assert verify_residual_corpus_manifest(rows, manifest)["manifest_sha256"]


def test_post_manifest_input_tamper_forces_research_only(tmp_path):
    folder = (
        tmp_path
        / "snapshots"
        / "highest-temperature-in-atlanta-on-july-1-2026"
    )
    _write_proof_market_day(folder)
    with (folder / "replay_inputs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n")

    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=lambda _row, **_kwargs: {"forecast_high_f": 93.0},
    )

    assert rows[0]["training_evidence_class"] == "research_only"
    assert rows[0]["promotion_training_countable"] is False
    semantic = manifest["inputs"][0]["semantic_event_day_manifest"]
    assert semantic["status"] == "BLOCK"
    assert "file_size" in semantic["operational_validation_blockers"]
    assert semantic["exact_file_proofs"]["replay_inputs.jsonl"]["status"] == "BLOCK"


def test_self_hashed_forged_release_summary_fails_semantic_validation(tmp_path):
    folder = (
        tmp_path
        / "snapshots"
        / "highest-temperature-in-atlanta-on-july-1-2026"
    )
    _write_proof_market_day(folder)
    path = folder / "event_day_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["release_runtime_identity"]["release_identities"][0][
        "release_id"
    ] = "forged-release"
    payload["manifest_hash"] = manifest_content_hash(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=lambda _row, **_kwargs: {"forecast_high_f": 93.0},
    )

    semantic = manifest["inputs"][0]["semantic_event_day_manifest"]
    assert semantic["criteria"]["manifest_self_hash_valid"] is True
    assert semantic["status"] == "BLOCK"
    assert "release_runtime_identity_summary" in semantic[
        "operational_validation_blockers"
    ]
    assert rows[0]["training_evidence_class"] == "research_only"


def test_semantic_manifest_cannot_replace_missing_config_identity(tmp_path):
    folder = (
        tmp_path
        / "snapshots"
        / "highest-temperature-in-atlanta-on-july-1-2026"
    )
    _write_proof_market_day(folder, include_config_hash=False)

    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=lambda _row, **_kwargs: {"forecast_high_f": 93.0},
    )

    assert manifest["inputs"][0]["semantic_event_day_manifest"]["status"] == "PASS"
    assert rows[0]["release_identity_proof"]["criteria"][
        "configuration_sha256_singular_and_valid"
    ] is False
    assert rows[0]["training_evidence_class"] == "research_only"
    assert rows[0]["promotion_training_countable"] is False


@pytest.mark.parametrize(
    ("field", "replacement", "criterion"),
    (
        (
            "release_manifest_sha256",
            "d" * 64,
            "release_manifest_sha256_matches_manifest_bound_identity",
        ),
        (
            "configuration_sha256",
            "e" * 64,
            "configuration_sha256_matches_manifest_bound_identity",
        ),
    ),
)
def test_selected_hash_cannot_disagree_with_manifest_bound_identity(
    tmp_path,
    field,
    replacement,
    criterion,
):
    folder = (
        tmp_path
        / "snapshots"
        / "highest-temperature-in-atlanta-on-july-1-2026"
    )
    _write_proof_market_day(folder)
    replay_path = folder / "replay_inputs.jsonl"
    replay_rows = [json.loads(line) for line in replay_path.read_text(encoding="utf-8").splitlines()]
    for replay_row in replay_rows:
        replay_row[field] = replacement
        if field == "configuration_sha256":
            replay_row["runtime_guard"]["config_sha256"] = replacement
    replay_path.write_text(
        "".join(json.dumps(row) + "\n" for row in replay_rows),
        encoding="utf-8",
    )
    write_event_day_manifest(folder, snapshots_root=folder.parent)

    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=lambda _row, **_kwargs: {"forecast_high_f": 93.0},
    )

    assert manifest["inputs"][0]["semantic_event_day_manifest"]["status"] == "PASS"
    proof = rows[0]["release_identity_proof"]
    assert proof["criteria"][criterion] is False
    assert proof["status"] == "BLOCK"
    assert rows[0]["training_evidence_class"] == "research_only"
    assert rows[0]["promotion_training_countable"] is False


def test_manifest_verifier_rechecks_input_folder_semantics(tmp_path):
    folder = (
        tmp_path
        / "snapshots"
        / "highest-temperature-in-atlanta-on-july-1-2026"
    )
    _write_proof_market_day(folder)
    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=lambda _row, **_kwargs: {"forecast_high_f": 93.0},
    )
    with (folder / "forecast_payloads.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{}\n")

    with pytest.raises(ResidualCorpusError, match="no longer matches semantic"):
        verify_residual_corpus_manifest(rows, manifest)


def test_outcome_or_market_fields_are_forbidden_from_features(tmp_path):
    folder = tmp_path / "day"
    _write_market_day(folder)

    def leaking_builder(_row, **_context):
        return {"forecast_high_f": 93.0, "settlement_distance": 2.0}

    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=leaking_builder,
    )
    assert rows == []
    assert manifest["counts"]["excluded_rows"] == 1
    assert "outcome/market-derived" in manifest["exclusions"][0]["detail"]


def test_model_nan_sentinels_are_serialized_as_explicit_null(tmp_path):
    folder = tmp_path / "day"
    _write_market_day(folder)
    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=lambda _row, **_kwargs: {
            "forecast_high_f": 93.0,
            "optional_context": float("nan"),
            "optional_context_missing": 1.0,
        },
    )
    assert rows[0]["features"]["optional_context"] is None
    assert manifest["counts"]["accepted_rows"] == 1


def test_feature_hash_tampering_fails(tmp_path):
    folder = tmp_path / "day"
    _write_market_day(folder)
    rows, _manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=lambda _row, **_kwargs: {"forecast_high_f": 93.0},
    )
    rows[0]["features"]["forecast_high_f"] = 99.0
    with pytest.raises(ResidualCorpusError, match="feature_sha256"):
        validate_residual_training_row(rows[0])


def test_exact_captured_comparator_simplexes_are_joined(tmp_path):
    path = tmp_path / "variant_predictions.jsonl"
    bands = [
        {"kind": "lte", "value": 90, "value_hi": 90},
        {"kind": "gte", "value": 91, "value_hi": 91},
    ]
    rows = []
    for band_key, current, item50, dynamic in (
        ("lte_90c", 0.4, 0.3, 0.2),
        ("gte_91c", 0.6, 0.7, 0.8),
    ):
        for variant_id, probability in (
            ("item50_pooled_forecast_v3_candidate", item50),
            ("pooled_f_dynamic_source_state_v0_1", dynamic),
        ):
            rows.append({
                "snapshot_id": "s1",
                "prediction_status": "predicted",
                "band_key": band_key,
                "variant_id": variant_id,
                "variant_probability": probability,
                "serving_model_probability": current,
            })
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    payload = captured_comparator_probabilities(
        path,
        snapshot_ids=("s1",),
        bands=bands,
    )
    assert payload["s1"]["frozen_current_release"] == {
        "lte_90c": 0.4,
        "gte_91c": 0.6,
    }
    assert payload["s1"]["item50"]["gte_91c"] == 0.7
    assert payload["s1"]["dynamic_source"]["gte_91c"] == 0.8


def test_materializer_rejects_noncontiguous_range_without_upper_endpoint(tmp_path):
    folder = tmp_path / "day"
    _write_market_day(folder)
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("snapshot_id", "bin_kind", "bin_value_c", "bin_value_hi_c", "range_label"),
        )
        writer.writeheader()
        writer.writerows([
            {
                "snapshot_id": "s1",
                "bin_kind": "lte",
                "bin_value_c": 71,
                "bin_value_hi_c": 71,
                "range_label": "71 or below",
            },
            {
                "snapshot_id": "s1",
                "bin_kind": "eq",
                "bin_value_c": 72,
                "bin_value_hi_c": 72,
                "range_label": "72-73",
            },
            {
                "snapshot_id": "s1",
                "bin_kind": "gte",
                "bin_value_c": 74,
                "bin_value_hi_c": 74,
                "range_label": "74 or above",
            },
        ])
    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=lambda _row, **_kwargs: {"forecast_high_f": 73.0},
    )
    assert rows == []
    assert manifest["exclusions"][0]["reason"] == "invalid_market_band_partition"

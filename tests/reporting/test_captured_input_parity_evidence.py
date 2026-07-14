from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.test_release_serving import _active_fixture, _load
from weather.collection.live_variant_predictions import (
    build_live_variant_prediction_rows,
)
from weather.experiment_contract import finalize_self_hash, verify_self_hash
from weather.io import write_json_atomic
from weather.market.market_config import config_for_date
from weather.model.model_contracts import DistributionResult
from weather.release_artifacts import (
    ReleaseArtifactVerificationError,
    canonical_payload_sha256,
)
from weather.release_serving import (
    STATUS_BOUND,
    STATUS_RESEARCH_UNBOUND,
    VerifiedServingBundle,
)
from weather.reporting.scorecards.captured_input_parity_evidence import (
    CAPTURED_INPUT_HASH_ALGORITHM,
    EVIDENCE_HASH_FIELD,
    REPLAY_INPUT_SCHEMA_VERSION,
    CapturedInputParityEvidenceError,
    generate_captured_input_parity_evidence,
)
from weather.reporting.scorecards.live_variant_settlement_scorecard import (
    persist_captured_input_replay_parity,
)


class CapturedReplayModel:
    """Small deterministic base-model adapter; candidate inference stays real."""

    def __init__(self, *, target_date, market_id, serving_bundle):
        self.target_date = target_date
        self.market_id = market_id
        self.serving_bundle = serving_bundle

    def estimate_distribution_result(self, sources, now=None):
        assert sources and now is not None
        return DistributionResult(
            distribution={78: 0.2, 80: 0.6, 82: 0.2},
            active_model_kind="hgb",
        )

    @staticmethod
    def source_data(sources, name):
        item = sources.get(name) or {}
        return item.get("data") or {}

    @staticmethod
    def effective_intraday_cutoff_hour(now, rows):
        assert now.tzinfo is not None
        del rows
        return 12

    def live_feature_record(self, sources, cutoff_hour, captured_at=None, model_version=None):
        assert sources and captured_at is not None and model_version
        return {
            "cutoff_hour": cutoff_hour,
            "forecast_high": 80.0,
            "high_so_far": 79.0,
            "current_temp": 79.0,
            "market_id": self.market_id,
            "display_unit": "F",
            "unit": "F",
        }

    @staticmethod
    def source_diagnostics(sources):
        assert sources
        return []

    @staticmethod
    def get_model_version_string():
        return "fixture-base-v1"

    @staticmethod
    def bin_probability(distribution, bin_data, calibration_context=None):
        del calibration_context
        kind = bin_data["kind"]
        value = int(bin_data["value"])
        value_hi = int(bin_data.get("value_hi") or value)
        values = {int(bucket): float(probability) for bucket, probability in distribution.items()}
        if kind == "lte":
            return sum(probability for bucket, probability in values.items() if bucket <= value)
        if kind == "gte":
            return sum(probability for bucket, probability in values.items() if bucket >= value)
        return sum(
            probability
            for bucket, probability in values.items()
            if value <= bucket <= value_hi
        )


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _bands():
    return [
        {
            "range_label": "78 F or below",
            "bin_kind": "lte",
            "bin_value_c": 78,
            "bin_value_hi_c": 78,
            "model_probability": 0.2,
            "market_yes": 0.19,
            "market_no": 0.81,
        },
        {
            "range_label": "80 F",
            "bin_kind": "eq",
            "bin_value_c": 80,
            "bin_value_hi_c": 80,
            "model_probability": 0.6,
            "market_yes": 0.58,
            "market_no": 0.42,
        },
        {
            "range_label": "82 F or higher",
            "bin_kind": "gte",
            "bin_value_c": 82,
            "bin_value_hi_c": 82,
            "model_probability": 0.2,
            "market_yes": 0.23,
            "market_no": 0.77,
        },
    ]


def _captured_record(bundle, *, now, event_slug, target_date, snapshot_id="snapshot-1"):
    built_at = now - timedelta(minutes=3)
    record = {
        "schema_version": REPLAY_INPUT_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "captured_at_utc": now.astimezone(timezone.utc).isoformat(),
        "captured_at_local": now.isoformat(),
        "event_slug": event_slug,
        "target_date": target_date.isoformat(),
        "model_version": "fixture-base-v1",
        "release_id": bundle.release_id,
        "release_manifest_sha256": bundle.manifest_sha256,
        "release_pointer_sha256": bundle.pointer_sha256,
        "release_sequence": bundle.sequence,
        "release_identity_status": "verified_variant_serving_bundle",
        "release_identity_reason": bundle.reason,
        "base_model_release_bound": True,
        "base_model_binding_reason": bundle.base_model_binding_reason,
        "captured_input_hash_algorithm": CAPTURED_INPUT_HASH_ALGORITHM,
        "model_identity": {"model_version": "fixture-base-v1"},
        "runtime_identity": {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "fixture-branch",
            "git_commit": "a" * 40,
            "git_dirty": False,
            "dirty_fingerprint": "fixture-dirty-fingerprint",
            "source_fingerprint": "fixture-source",
            # SnapshotStore derives runtime_code_state from runtime_guard.state,
            # never from an ambient field on the process identity.
            "code_state": "stale_code",
        },
        "runtime_guard": {"ok": True, "state": "current"},
        "snapshot_cadence": "triggered",
        "snapshot_cadence_quality": {
            "snapshot_cadence": "triggered",
            "snapshot_cadence_quality_state": "triggered",
            "snapshot_cadence_gap_count": 0,
            "snapshot_cadence_max_gap_seconds": None,
            "snapshot_cadence_last_model_age_seconds": 0.0,
            "snapshot_cadence_confidence_multiplier": 1.0,
            "snapshot_cadence_permission": "allow",
            "snapshot_cadence_quote_size_multiplier": 1.0,
            "snapshot_cadence_quote_widen_buffer": 0.0,
            "snapshot_cadence_reason": "fixture triggered capture",
        },
        "trigger_context": {
            "reason": "observation_value_changed",
            "source": "fallback-source",
            "previous_value": 77,
            "current_value": 79,
            "observed_at": "2026-07-14T01:02:03+00:00",
            "primary_trigger": {
                "source": "primary-source",
                "previous_value": None,
                "current_value": 0,
                "observed_at": None,
            },
        },
        "built_at": built_at.isoformat(),
        "recorded_distribution": {78: 0.2, 80: 0.6, 82: 0.2},
        "sources": {
            "wu_history": {
                "ok": True,
                "stale": False,
                "data": {"rows": []},
            }
        },
    }
    record["captured_input_hash"] = canonical_payload_sha256(record)
    return record


def _write_honest_market_day(root: Path, bundle, *, now, target_date):
    config = config_for_date(target_date, "nyc")
    folder = root / config.event_slug
    captured = _captured_record(
        bundle,
        now=now,
        event_slug=config.event_slug,
        target_date=target_date,
    )
    bands = _bands()
    snapshot = {
        "snapshot_id": captured["snapshot_id"],
        "captured_at_utc": captured["captured_at_utc"],
        "captured_at_local": captured["captured_at_local"],
        "event_slug": config.event_slug,
        "event_updated_at": "fixture-event-update",
        "feature_vector": {
            "cutoff_hour": 12,
            "forecast_high": 80.0,
            "high_so_far": 79.0,
            "market_id": "nyc",
        },
        "bands": bands,
    }
    client = CapturedReplayModel(
        target_date=target_date,
        market_id="nyc",
        serving_bundle=bundle,
    )
    expected_metadata = {
        "runtime_identity_schema_version": "runtime_identity_v0.1",
        "runtime_git_branch": "fixture-branch",
        "runtime_git_commit": "a" * 40,
        "runtime_git_dirty": False,
        "runtime_dirty_fingerprint": "fixture-dirty-fingerprint",
        "runtime_source_fingerprint": "fixture-source",
        "runtime_code_state": "current",
        "snapshot_cadence": "triggered",
        "snapshot_cadence_quality_state": "triggered",
        "snapshot_cadence_gap_count": 0,
        "snapshot_cadence_max_gap_seconds": None,
        "snapshot_cadence_last_model_age_seconds": 0.0,
        "snapshot_cadence_confidence_multiplier": 1.0,
        "snapshot_cadence_permission": "allow",
        "snapshot_cadence_quote_size_multiplier": 1.0,
        "snapshot_cadence_quote_widen_buffer": 0.0,
        "snapshot_cadence_reason": "fixture triggered capture",
        "trigger_reason": "observation_value_changed",
        "trigger_source": "primary-source",
        "trigger_previous_value": 77,
        "trigger_current_value": 0,
        "trigger_observed_at": "2026-07-14T01:02:03+00:00",
    }
    served_rows = build_live_variant_prediction_rows(
        snapshot_id=captured["snapshot_id"],
        captured_at=now,
        event={"updatedAt": snapshot["event_updated_at"]},
        model={
            "feature_vector": client.live_feature_record(
                captured["sources"],
                12,
                captured_at=datetime.fromisoformat(captured["built_at"]),
                model_version="fixture-base-v1",
            ),
            "source_diagnostics": [],
        },
        model_client=client,
        band_rows=bands,
        event_slug=config.event_slug,
        market_id="nyc",
        target_date=target_date,
        serving_model_version="fixture-base-v1",
        captured_input_hash=captured["captured_input_hash"],
        runtime_fields={
            key: expected_metadata[key]
            for key in (
                "runtime_identity_schema_version",
                "runtime_git_branch",
                "runtime_git_commit",
                "runtime_git_dirty",
                "runtime_dirty_fingerprint",
                "runtime_source_fingerprint",
                "runtime_code_state",
            )
        },
        snapshot_cadence=captured["snapshot_cadence"],
        cadence_quality=captured["snapshot_cadence_quality"],
        trigger_summary={
            key: expected_metadata[key]
            for key in (
                "trigger_reason",
                "trigger_source",
                "trigger_previous_value",
                "trigger_current_value",
                "trigger_observed_at",
            )
        },
        serving_bundle=bundle,
    )
    assert served_rows and {row["prediction_status"] for row in served_rows} == {"predicted"}
    paths = {
        "captured": folder / "replay_inputs.jsonl",
        "snapshots": folder / "snapshots.jsonl",
        "served": folder / "variant_predictions.jsonl",
    }
    _write_jsonl(paths["captured"], [captured])
    _write_jsonl(paths["snapshots"], [snapshot])
    _write_jsonl(paths["served"], served_rows)
    return paths, expected_metadata


def _manual_bundle(tmp_path: Path) -> VerifiedServingBundle:
    release_dir = tmp_path / "releases" / "release-1"
    model_path = release_dir / "candidate.pkl"
    return VerifiedServingBundle(
        status=STATUS_BOUND,
        reason="synthetic verified bundle",
        pointer_present=True,
        release_id="release-1",
        manifest_sha256="a" * 64,
        pointer_sha256="b" * 64,
        sequence=1,
        release_dir=str(release_dir),
        route={
            "markets": {
                "nyc": {
                    "decision": "promote",
                    "candidate_variant_id": "candidate-1",
                    "base_model_market_id": "nyc",
                }
            }
        },
        artifact_paths={"pooled_band_model": str(model_path)},
        artifact_hashes={"pooled_band_model": "c" * 64},
        base_model_bound=True,
        base_model_binding_reason="synthetic complete base graph",
    )


def _manual_resolver(bundle):
    def resolve(**_kwargs):
        return {
            "release_id": bundle.release_id,
            "manifest_sha256": bundle.manifest_sha256,
            "served_binding_sha256": "d" * 64,
        }

    return resolve


def _manual_kwargs(tmp_path: Path, bundle, *, now):
    return {
        "market_id": "nyc",
        "target_date": now.date(),
        "captured_inputs_path": tmp_path / "replay_inputs.jsonl",
        "snapshot_tape_path": tmp_path / "snapshots.jsonl",
        "served_tape_path": tmp_path / "variant_predictions.jsonl",
        "served_out": tmp_path / "out" / "served.json",
        "replay_out": tmp_path / "out" / "replay.json",
        "pointer_path": tmp_path / "current_release.json",
        "releases_root": tmp_path / "releases",
        "repo_root": tmp_path,
        "check_runtime": False,
        "now": now,
        "bundle_loader": lambda **_kwargs: bundle,
        "binding_resolver": _manual_resolver(bundle),
        "model_factory": CapturedReplayModel,
    }


def _resign_envelope_pair(served_envelope, replay_envelope):
    served = deepcopy(served_envelope)
    replay = deepcopy(replay_envelope)
    served["row_set_sha256"] = canonical_payload_sha256({"rows": served["rows"]})
    replay["row_set_sha256"] = canonical_payload_sha256({"rows": replay["rows"]})
    pair_sha256 = canonical_payload_sha256(
        {
            "release_id": served["release_id"],
            "release_manifest_sha256": served["release_manifest_sha256"],
            "serving_bundle_fingerprint_sha256": served[
                "serving_bundle_fingerprint_sha256"
            ],
            "market_id": served["market_id"],
            "target_date": served["target_date"],
            "served_row_set_sha256": served["row_set_sha256"],
            "replay_row_set_sha256": replay["row_set_sha256"],
        }
    )
    served.update(
        pair_sha256=pair_sha256,
        peer_row_set_sha256=replay["row_set_sha256"],
    )
    replay.update(
        pair_sha256=pair_sha256,
        peer_row_set_sha256=served["row_set_sha256"],
    )
    return (
        finalize_self_hash(served, hash_field=EVIDENCE_HASH_FIELD),
        finalize_self_hash(replay, hash_field=EVIDENCE_HASH_FIELD),
    )


def test_honest_generation_is_self_hashed_and_comparator_passes_then_blocks_tamper(tmp_path):
    paths, _frozen, _release, releases, pointer = _active_fixture(
        tmp_path / "release-fixture",
        functional=True,
    )
    bundle = _load(pointer, releases, paths["repo"])
    now = datetime.now(timezone.utc).replace(microsecond=0)
    target_date = now.date()
    source_paths, expected_metadata = _write_honest_market_day(
        tmp_path / "snapshots",
        bundle,
        now=now,
        target_date=target_date,
    )
    served_out = tmp_path / "evidence" / "served_rows.json"
    replay_out = tmp_path / "evidence" / "replay_rows.json"

    result = generate_captured_input_parity_evidence(
        market_id="nyc",
        target_date=target_date,
        captured_inputs_path=source_paths["captured"],
        snapshot_tape_path=source_paths["snapshots"],
        served_tape_path=source_paths["served"],
        served_out=served_out,
        replay_out=replay_out,
        pointer_path=pointer,
        releases_root=releases,
        repo_root=paths["repo"],
        check_runtime=False,
        now=now,
        model_factory=CapturedReplayModel,
    )
    served_envelope = json.loads(served_out.read_text(encoding="utf-8"))
    replay_envelope = json.loads(replay_out.read_text(encoding="utf-8"))
    verify_self_hash(served_envelope, hash_field=EVIDENCE_HASH_FIELD)
    verify_self_hash(replay_envelope, hash_field=EVIDENCE_HASH_FIELD)

    passed, _, _ = persist_captured_input_replay_parity(
        served_out,
        replay_out,
        json_out=tmp_path / "parity-pass.json",
        report_out=tmp_path / "parity-pass.md",
        expected_release_id=bundle.release_id,
        expected_manifest_sha256=bundle.manifest_sha256,
        now=now + timedelta(seconds=1),
    )

    second_served = deepcopy(served_envelope)
    second_replay = deepcopy(replay_envelope)
    second_market = "toronto"
    second_coverage = finalize_self_hash(
        {
            "candidate_id": second_served["candidate_id"],
            "expected_market_ids": [second_market],
            "expected_branch_scenarios": ["captured_market_day"],
            "expected_band_count_by_market": {second_market: 3},
        },
        hash_field="coverage_contract_sha256",
    )
    for envelope in (second_served, second_replay):
        envelope["market_id"] = second_market
        envelope["coverage_contract"] = second_coverage
        for row in envelope["rows"]:
            row["market_id"] = second_market
            row["parity_coverage_contract"] = second_coverage
        envelope["row_set_sha256"] = canonical_payload_sha256(
            {"rows": envelope["rows"]}
        )
    second_pair_sha256 = canonical_payload_sha256(
        {
            "release_id": bundle.release_id,
            "release_manifest_sha256": bundle.manifest_sha256,
            "serving_bundle_fingerprint_sha256": second_served[
                "serving_bundle_fingerprint_sha256"
            ],
            "market_id": second_market,
            "target_date": target_date.isoformat(),
            "served_row_set_sha256": second_served["row_set_sha256"],
            "replay_row_set_sha256": second_replay["row_set_sha256"],
        }
    )
    second_served.update(
        pair_sha256=second_pair_sha256,
        peer_row_set_sha256=second_replay["row_set_sha256"],
    )
    second_replay.update(
        pair_sha256=second_pair_sha256,
        peer_row_set_sha256=second_served["row_set_sha256"],
    )
    second_served = finalize_self_hash(second_served, hash_field=EVIDENCE_HASH_FIELD)
    second_replay = finalize_self_hash(second_replay, hash_field=EVIDENCE_HASH_FIELD)
    second_served_out = tmp_path / "evidence" / "toronto" / "served_rows.json"
    second_replay_out = tmp_path / "evidence" / "toronto" / "replay_rows.json"
    write_json_atomic(second_served_out, second_served, trailing_newline=True)
    write_json_atomic(second_replay_out, second_replay, trailing_newline=True)
    multi_market, _, _ = persist_captured_input_replay_parity(
        [served_out, second_served_out],
        [replay_out, second_replay_out],
        json_out=tmp_path / "parity-multi-market.json",
        report_out=tmp_path / "parity-multi-market.md",
        expected_release_id=bundle.release_id,
        expected_manifest_sha256=bundle.manifest_sha256,
        now=now + timedelta(seconds=1),
    )

    coordinated_served = deepcopy(served_envelope)
    coordinated_replay = deepcopy(replay_envelope)
    coordinated_served["rows"][0]["variant_probability"] = 0.01
    coordinated_replay["rows"][0]["variant_probability"] = 0.01
    write_json_atomic(served_out, coordinated_served, trailing_newline=True)
    write_json_atomic(replay_out, coordinated_replay, trailing_newline=True)
    coordinated_block, _, _ = persist_captured_input_replay_parity(
        served_out,
        replay_out,
        json_out=tmp_path / "parity-coordinated-block.json",
        report_out=tmp_path / "parity-coordinated-block.md",
        expected_release_id=bundle.release_id,
        expected_manifest_sha256=bundle.manifest_sha256,
        now=now + timedelta(seconds=1),
    )
    write_json_atomic(served_out, served_envelope, trailing_newline=True)
    write_json_atomic(replay_out, replay_envelope, trailing_newline=True)

    # Re-sign both envelopes consistently while changing only the replay
    # probability.  Pair authentication therefore passes and the comparator
    # must independently detect the semantic row mismatch.
    tampered_served = deepcopy(served_envelope)
    tampered_replay = deepcopy(replay_envelope)
    tampered_replay["rows"][0]["variant_probability"] = 0.01
    tampered_replay["row_set_sha256"] = canonical_payload_sha256(
        {"rows": tampered_replay["rows"]}
    )
    tampered_pair_sha256 = canonical_payload_sha256(
        {
            "release_id": bundle.release_id,
            "release_manifest_sha256": bundle.manifest_sha256,
            "serving_bundle_fingerprint_sha256": tampered_served[
                "serving_bundle_fingerprint_sha256"
            ],
            "market_id": "nyc",
            "target_date": target_date.isoformat(),
            "served_row_set_sha256": tampered_served["row_set_sha256"],
            "replay_row_set_sha256": tampered_replay["row_set_sha256"],
        }
    )
    tampered_served.update(
        pair_sha256=tampered_pair_sha256,
        peer_row_set_sha256=tampered_replay["row_set_sha256"],
    )
    tampered_replay.update(
        pair_sha256=tampered_pair_sha256,
        peer_row_set_sha256=tampered_served["row_set_sha256"],
    )
    tampered_served = finalize_self_hash(
        tampered_served,
        hash_field=EVIDENCE_HASH_FIELD,
    )
    tampered_replay = finalize_self_hash(
        tampered_replay,
        hash_field=EVIDENCE_HASH_FIELD,
    )
    write_json_atomic(served_out, tampered_served, trailing_newline=True)
    write_json_atomic(replay_out, tampered_replay, trailing_newline=True)
    blocked, _, _ = persist_captured_input_replay_parity(
        served_out,
        replay_out,
        json_out=tmp_path / "parity-block.json",
        report_out=tmp_path / "parity-block.md",
        expected_release_id=bundle.release_id,
        expected_manifest_sha256=bundle.manifest_sha256,
        now=now + timedelta(seconds=2),
    )

    # A caller who can rewrite and consistently re-sign both envelopes must
    # still be unable to alter one side's release/runtime fidelity metadata.
    metadata_served = deepcopy(served_envelope)
    metadata_replay = deepcopy(replay_envelope)
    metadata_replay["rows"][0]["runtime_git_commit"] = "b" * 40
    metadata_served, metadata_replay = _resign_envelope_pair(
        metadata_served,
        metadata_replay,
    )
    write_json_atomic(served_out, metadata_served, trailing_newline=True)
    write_json_atomic(replay_out, metadata_replay, trailing_newline=True)
    metadata_blocked, _, _ = persist_captured_input_replay_parity(
        served_out,
        replay_out,
        json_out=tmp_path / "parity-metadata-block.json",
        report_out=tmp_path / "parity-metadata-block.md",
        expected_release_id=bundle.release_id,
        expected_manifest_sha256=bundle.manifest_sha256,
        now=now + timedelta(seconds=3),
    )

    assert result["status"] == "PASS"
    assert result["served_row_count"] == result["replay_row_count"] == 3
    assert served_envelope["release_id"] == replay_envelope["release_id"] == bundle.release_id
    assert served_envelope["release_manifest_sha256"] == bundle.manifest_sha256
    assert replay_envelope["release_manifest_sha256"] == bundle.manifest_sha256
    served_metadata = [
        {field: row.get(field) for field in expected_metadata}
        for row in served_envelope["rows"]
    ]
    replay_metadata = [
        {field: row.get(field) for field in expected_metadata}
        for row in replay_envelope["rows"]
    ]
    assert served_metadata == replay_metadata == [expected_metadata] * 3
    assert {
        row["captured_at_utc"] for row in replay_envelope["rows"]
    } == {now.astimezone(timezone.utc).isoformat()}
    assert all(
        row["captured_at_utc"]
        != (now - timedelta(minutes=3)).astimezone(timezone.utc).isoformat()
        for row in replay_envelope["rows"]
    )
    assert passed["status"] == "PASS"
    assert passed["coverage_contract"]["contract_source"] == "self_hashed_rows"
    assert multi_market["status"] == "PASS"
    assert multi_market["coverage_contract"]["expected_market_ids"] == [
        "nyc",
        "toronto",
    ]
    assert coordinated_block["status"] == "BLOCK"
    assert {
        row["code"] for row in coordinated_block["mismatches"]
    } >= {"served_parity_input_unreadable", "replay_parity_input_unreadable"}
    assert blocked["status"] == "BLOCK"
    mismatch_codes = {row["code"] for row in blocked["mismatches"]}
    assert "probability_mismatch" in mismatch_codes
    assert "parity_envelope_pair_mismatch" not in mismatch_codes
    assert metadata_blocked["status"] == "BLOCK"
    metadata_mismatches = {
        row["code"] for row in metadata_blocked["mismatches"]
    }
    assert "authenticated_parity_row_fidelity_mismatch" in metadata_mismatches
    assert "parity_envelope_pair_mismatch" not in metadata_mismatches


def test_generator_does_not_publish_pair_that_exact_persisted_comparator_blocks(
    tmp_path,
):
    paths, _frozen, _release, releases, pointer = _active_fixture(
        tmp_path / "release-fixture",
        functional=True,
    )
    bundle = _load(pointer, releases, paths["repo"])
    now = datetime.now(timezone.utc).replace(microsecond=0)
    source_paths, _expected_metadata = _write_honest_market_day(
        tmp_path / "snapshots",
        bundle,
        now=now,
        target_date=now.date(),
    )
    served_rows = [
        json.loads(line)
        for line in source_paths["served"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    served_rows[0]["runtime_git_commit"] = "b" * 40
    _write_jsonl(source_paths["served"], served_rows)
    served_out = tmp_path / "evidence" / "served_rows.json"
    replay_out = tmp_path / "evidence" / "replay_rows.json"

    with pytest.raises(CapturedInputParityEvidenceError) as raised:
        generate_captured_input_parity_evidence(
            market_id="nyc",
            target_date=now.date(),
            captured_inputs_path=source_paths["captured"],
            snapshot_tape_path=source_paths["snapshots"],
            served_tape_path=source_paths["served"],
            served_out=served_out,
            replay_out=replay_out,
            pointer_path=pointer,
            releases_root=releases,
            repo_root=paths["repo"],
            check_runtime=False,
            now=now,
            model_factory=CapturedReplayModel,
        )

    assert raised.value.code == "generated_authenticated_parity_blocked"
    assert raised.value.context["parity_first_mismatch"]["code"] == (
        "authenticated_parity_row_fidelity_mismatch"
    )
    assert not served_out.exists()
    assert not replay_out.exists()


def test_authenticated_generation_time_is_primary_freshness_and_must_match(
    tmp_path,
):
    paths, _frozen, _release, releases, pointer = _active_fixture(
        tmp_path / "release-fixture",
        functional=True,
    )
    bundle = _load(pointer, releases, paths["repo"])
    now = datetime.now(timezone.utc).replace(microsecond=0)
    source_paths, _expected_metadata = _write_honest_market_day(
        tmp_path / "snapshots",
        bundle,
        now=now,
        target_date=now.date(),
    )
    served_out = tmp_path / "evidence" / "served_rows.json"
    replay_out = tmp_path / "evidence" / "replay_rows.json"
    generate_captured_input_parity_evidence(
        market_id="nyc",
        target_date=now.date(),
        captured_inputs_path=source_paths["captured"],
        snapshot_tape_path=source_paths["snapshots"],
        served_tape_path=source_paths["served"],
        served_out=served_out,
        replay_out=replay_out,
        pointer_path=pointer,
        releases_root=releases,
        repo_root=paths["repo"],
        check_runtime=False,
        now=now,
        model_factory=CapturedReplayModel,
    )
    served = json.loads(served_out.read_text(encoding="utf-8"))
    replay = json.loads(replay_out.read_text(encoding="utf-8"))

    old_time = (now - timedelta(hours=49)).isoformat()
    for envelope in (served, replay):
        envelope["generated_at_utc"] = old_time
    stale_served = finalize_self_hash(served, hash_field=EVIDENCE_HASH_FIELD)
    stale_replay = finalize_self_hash(replay, hash_field=EVIDENCE_HASH_FIELD)
    stale_served_path = tmp_path / "stale" / "served.json"
    stale_replay_path = tmp_path / "stale" / "replay.json"
    write_json_atomic(stale_served_path, stale_served, trailing_newline=True)
    write_json_atomic(stale_replay_path, stale_replay, trailing_newline=True)
    stale, _, _ = persist_captured_input_replay_parity(
        stale_served_path,
        stale_replay_path,
        json_out=tmp_path / "stale-parity.json",
        report_out=tmp_path / "stale-parity.md",
        expected_release_id=bundle.release_id,
        expected_manifest_sha256=bundle.manifest_sha256,
        now=now,
    )
    stale_codes = {row["code"] for row in stale["mismatches"]}
    assert "served_parity_authenticated_generated_at_stale" in stale_codes
    assert "replay_parity_authenticated_generated_at_stale" in stale_codes

    served["generated_at_utc"] = now.isoformat()
    replay["generated_at_utc"] = (now - timedelta(seconds=1)).isoformat()
    mismatched_served = finalize_self_hash(served, hash_field=EVIDENCE_HASH_FIELD)
    mismatched_replay = finalize_self_hash(replay, hash_field=EVIDENCE_HASH_FIELD)
    mismatch_served_path = tmp_path / "mismatch" / "served.json"
    mismatch_replay_path = tmp_path / "mismatch" / "replay.json"
    write_json_atomic(
        mismatch_served_path,
        mismatched_served,
        trailing_newline=True,
    )
    write_json_atomic(
        mismatch_replay_path,
        mismatched_replay,
        trailing_newline=True,
    )
    mismatched, _, _ = persist_captured_input_replay_parity(
        mismatch_served_path,
        mismatch_replay_path,
        json_out=tmp_path / "mismatch-parity.json",
        report_out=tmp_path / "mismatch-parity.md",
        expected_release_id=bundle.release_id,
        expected_manifest_sha256=bundle.manifest_sha256,
        now=now,
    )
    assert mismatched["status"] == "BLOCK"
    assert "parity_envelope_pair_mismatch" in {
        row["code"] for row in mismatched["mismatches"]
    }


def test_output_paths_cannot_alias_custom_active_pointer(tmp_path):
    paths, _frozen, _release, releases, pointer = _active_fixture(
        tmp_path / "release-fixture",
        functional=True,
    )
    bundle = _load(pointer, releases, paths["repo"])
    now = datetime.now(timezone.utc).replace(microsecond=0)
    source_paths, _expected_metadata = _write_honest_market_day(
        tmp_path / "snapshots",
        bundle,
        now=now,
        target_date=now.date(),
    )
    custom_pointer = tmp_path / "active-pointer-outside-release-root.json"
    original_pointer_bytes = pointer.read_bytes()
    custom_pointer.write_bytes(original_pointer_bytes)

    with pytest.raises(CapturedInputParityEvidenceError) as raised:
        generate_captured_input_parity_evidence(
            market_id="nyc",
            target_date=now.date(),
            captured_inputs_path=source_paths["captured"],
            snapshot_tape_path=source_paths["snapshots"],
            served_tape_path=source_paths["served"],
            served_out=custom_pointer,
            replay_out=tmp_path / "evidence" / "replay.json",
            pointer_path=custom_pointer,
            releases_root=releases,
            repo_root=paths["repo"],
            check_runtime=False,
            now=now,
            bundle_loader=lambda **_kwargs: bundle,
            binding_resolver=_manual_resolver(bundle),
            model_factory=CapturedReplayModel,
        )

    assert raised.value.code == "evidence_output_collision"
    assert custom_pointer.read_bytes() == original_pointer_bytes

    release_store_output = releases / "parity-must-not-write-here.json"
    with pytest.raises(CapturedInputParityEvidenceError) as release_store_raised:
        generate_captured_input_parity_evidence(
            market_id="nyc",
            target_date=now.date(),
            captured_inputs_path=source_paths["captured"],
            snapshot_tape_path=source_paths["snapshots"],
            served_tape_path=source_paths["served"],
            served_out=release_store_output,
            replay_out=tmp_path / "evidence" / "replay.json",
            pointer_path=custom_pointer,
            releases_root=releases,
            repo_root=paths["repo"],
            check_runtime=False,
            now=now,
            bundle_loader=lambda **_kwargs: bundle,
            binding_resolver=_manual_resolver(bundle),
            model_factory=CapturedReplayModel,
        )
    assert release_store_raised.value.code == "serving_artifact_output_forbidden"
    assert not release_store_output.exists()


def test_fails_closed_without_active_release_pointer(tmp_path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    bundle = VerifiedServingBundle(
        status=STATUS_RESEARCH_UNBOUND,
        reason="no active release pointer",
        pointer_present=False,
    )
    kwargs = _manual_kwargs(tmp_path, bundle, now=now)

    with pytest.raises(CapturedInputParityEvidenceError) as raised:
        generate_captured_input_parity_evidence(**kwargs)

    assert raised.value.code == "no_active_release_pointer"
    assert "promote a reviewed release" in raised.value.next_action


def test_fails_closed_when_release_verification_raises(tmp_path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    bundle = _manual_bundle(tmp_path)
    kwargs = _manual_kwargs(tmp_path, bundle, now=now)

    def fail_verification(**_kwargs):
        raise ReleaseArtifactVerificationError("synthetic manifest hash mismatch")

    kwargs["bundle_loader"] = fail_verification
    with pytest.raises(CapturedInputParityEvidenceError) as raised:
        generate_captured_input_parity_evidence(**kwargs)

    assert raised.value.code == "active_release_verification_failed"
    assert "manifest hash mismatch" in raised.value.detail


def test_fails_closed_when_captured_inputs_are_missing_or_stale(tmp_path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    bundle = _manual_bundle(tmp_path)
    missing_kwargs = _manual_kwargs(tmp_path / "missing", bundle, now=now)

    with pytest.raises(CapturedInputParityEvidenceError) as missing:
        generate_captured_input_parity_evidence(**missing_kwargs)

    stale_root = tmp_path / "stale"
    stale_kwargs = _manual_kwargs(stale_root, bundle, now=now)
    captured_path = Path(stale_kwargs["captured_inputs_path"])
    _write_jsonl(captured_path, [{"captured_at_utc": (now - timedelta(hours=49)).isoformat()}])
    old = (now - timedelta(hours=49)).timestamp()
    os.utime(captured_path, (old, old))
    with pytest.raises(CapturedInputParityEvidenceError) as stale:
        generate_captured_input_parity_evidence(**stale_kwargs)

    assert missing.value.code == "captured_inputs_missing"
    assert stale.value.code == "captured_inputs_stale"
    assert stale.value.context["max_age_hours"] == 48.0


def test_fails_closed_on_captured_serving_bundle_fingerprint_mismatch(tmp_path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    bundle = _manual_bundle(tmp_path)
    kwargs = _manual_kwargs(tmp_path, bundle, now=now)
    event_slug = config_for_date(now.date(), "nyc").event_slug
    record = _captured_record(
        bundle,
        now=now,
        event_slug=event_slug,
        target_date=now.date(),
    )
    record["serving_bundle_fingerprint_sha256"] = "e" * 64
    record["captured_input_hash"] = canonical_payload_sha256(
        record,
        omit=("captured_input_hash",),
    )
    _write_jsonl(Path(kwargs["captured_inputs_path"]), [record])
    _write_jsonl(Path(kwargs["snapshot_tape_path"]), [])
    _write_jsonl(Path(kwargs["served_tape_path"]), [])

    with pytest.raises(CapturedInputParityEvidenceError) as raised:
        generate_captured_input_parity_evidence(**kwargs)

    assert raised.value.code == "serving_bundle_fingerprint_mismatch"
    assert "serving_bundle_fingerprint_sha256" in raised.value.context["failed_checks"]
    assert "collect fresh inputs" in raised.value.next_action

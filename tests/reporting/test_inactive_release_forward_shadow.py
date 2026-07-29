from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather.release_artifacts import canonical_payload_sha256
from weather.release_serving import (
    STATUS_INACTIVE_SHADOW_BOUND,
    VerifiedServingBundle,
)
from weather.reporting.scorecards.inactive_release_forward_shadow import (
    CAPTURED_INPUT_HASH_ALGORITHM,
    CANDIDATE_STAGE_ORDER,
    InactiveReleaseForwardShadowError,
    generate_inactive_release_forward_shadow,
)
from weather.schema_registry import schema_version


SNAPSHOT_ID = "20260729T000000000000-0500"
CAPTURED_AT = "2026-07-29T05:00:00+00:00"


class FakeModel:
    market_id = "austin"

    def estimate_distribution_result(self, _sources, *, now):
        assert now.isoformat() == "2026-07-29T00:00:00-05:00"
        distribution = {1: 0.4, 2: 0.6}
        return SimpleNamespace(
            distribution=distribution,
            component_payload={
                "schema_version": "components_v1",
                "components": {
                    "climatology_prior": distribution,
                    "final_model": distribution,
                },
            },
            calibration_context={},
        )

    def source_data(self, _sources, _name):
        return {}

    def effective_intraday_cutoff_hour(self, _built_at, _rows):
        return 7

    def get_model_version_string(self):
        return "fake-model"

    def live_feature_record(
        self,
        _sources,
        cutoff_hour,
        *,
        captured_at,
        model_version,
    ):
        assert cutoff_hour == 7
        assert model_version == "fake-model"
        return {
            "market_id": "austin",
            "cutoff_hour": 7,
            "captured_at_local": "2026-07-29T00:00:00-05:00",
        }

    def bin_probability(self, distribution, bin_data, *, calibration_context):
        assert calibration_context == {}
        return float(distribution[int(bin_data["value"])])

    def source_diagnostics(self, _sources):
        return []


def _bundle() -> VerifiedServingBundle:
    return VerifiedServingBundle(
        status=STATUS_INACTIVE_SHADOW_BOUND,
        reason="test inactive release",
        pointer_present=False,
        release_id="release-r1",
        manifest_sha256="a" * 64,
        production_capable=True,
        base_model_bound=True,
        route={
            "markets": {
                "austin": {
                    "decision": "shadow",
                    "candidate_variant_id": "release-r1.pooled_band",
                }
            }
        },
        model_bundle={"prediction_mode": "band_binary"},
        artifact_hashes={
            "pooled_band_model": "b" * 64,
            "pooled_postprocessor_metadata": "c" * 64,
        },
    )


def _write_sources(tmp_path: Path) -> tuple[Path, Path]:
    captured = {
        "schema_version": "replay_inputs_v0.2",
        "snapshot_id": SNAPSHOT_ID,
        "captured_at_utc": CAPTURED_AT,
        "captured_at_local": "2026-07-29T00:00:00-05:00",
        "built_at": "2026-07-29T00:00:00-05:00",
        "event_slug": "highest-temperature-in-austin-on-july-29-2026",
        "target_date": "2026-07-29",
        "sources": {"wu_history": {"rows": []}},
        "recorded_distribution": {"1": 0.4, "2": 0.6},
        "model_version": "recorded-model",
        "model_identity": {"name": "recorded-production"},
        "release_id": "",
        "release_manifest_sha256": "",
        "release_pointer_sha256": "",
        "release_identity_status": "research_unbound_non_countable",
        "runtime_identity": {"source_fingerprint": "recorded-runtime"},
        "captured_input_hash_algorithm": CAPTURED_INPUT_HASH_ALGORITHM,
    }
    captured["captured_input_hash"] = canonical_payload_sha256(
        captured,
        omit=("captured_input_hash",),
    )
    snapshot = {
        "snapshot_id": SNAPSHOT_ID,
        "captured_at_utc": CAPTURED_AT,
        "event_slug": "highest-temperature-in-austin-on-july-29-2026",
        "model_version": "recorded-model",
        "feature_vector": {
            "market_id": "austin",
            "cutoff_hour": 7,
            "captured_at_local": "2026-07-29T00:00:00-05:00",
        },
        "distribution": {"1": 0.4, "2": 0.6},
        "distribution_components": {
            "schema_version": "components_v1",
            "components": {
                "climatology_prior": {"1": 0.4, "2": 0.6},
                "final_model": {"1": 0.4, "2": 0.6},
            },
        },
        "bands": [
            {
                "bin_kind": "eq",
                "bin_value_c": 1,
                "bin_value_hi_c": 1,
                "range_label": "1",
                "model_probability": 0.4,
            },
            {
                "bin_kind": "eq",
                "bin_value_c": 2,
                "bin_value_hi_c": 2,
                "range_label": "2",
                "model_probability": 0.6,
            },
        ],
    }
    captured_path = tmp_path / "replay_inputs.jsonl"
    snapshot_path = tmp_path / "snapshots.jsonl"
    captured_path.write_text(json.dumps(captured) + "\n", encoding="utf-8")
    snapshot_path.write_text(json.dumps(snapshot) + "\n", encoding="utf-8")
    return captured_path, snapshot_path


def _trace(probabilities: dict[str, float]):
    def run(_artifact, _features, _bands, _context):
        return {
            "probabilities": probabilities,
            "stages": {
                stage: dict(probabilities) for stage in CANDIDATE_STAGE_ORDER
            },
        }

    return run


def _generate(
    tmp_path: Path,
    *,
    trace_runner,
    model_factory=None,
):
    captured_path, snapshot_path = _write_sources(tmp_path)
    return generate_inactive_release_forward_shadow(
        release_dir=tmp_path / "releases" / "release-r1",
        expected_manifest_sha256="a" * 64,
        market_id="austin",
        target_date=date(2026, 7, 29),
        captured_inputs_path=captured_path,
        snapshot_tape_path=snapshot_path,
        window_start="2026-07-29T05:00:00+00:00",
        window_end="2026-07-29T05:01:00+00:00",
        active_pointer_path=tmp_path / "releases" / "current_release.json",
        repo_root=tmp_path,
        check_runtime=False,
        bundle_loader=lambda *_args, **_kwargs: _bundle(),
        model_factory=model_factory or (lambda **_kwargs: FakeModel()),
        trace_runner=trace_runner,
    )


def test_forward_shadow_records_exact_matching_instant(tmp_path: Path):
    probabilities = {"eq_1c": 0.4, "eq_2c": 0.6}
    payload = _generate(tmp_path, trace_runner=_trace(probabilities))

    assert payload["schema_version"] == schema_version(
        "inactive_release_forward_shadow"
    )
    assert payload["status"] == "PASS"
    assert payload["comparison_status"] == "MATCH"
    assert payload["active_pointer_authority_used"] is False
    assert payload["summary"]["snapshot_count"] == 1
    assert payload["summary"]["band_row_count"] == 2
    assert payload["summary"]["first_pipeline_divergence"] is None
    assert payload["summary"]["strict_whole_partition_matches"] == {
        "inactive_incumbent": 1,
        **{stage: 1 for stage in CANDIDATE_STAGE_ORDER},
    }
    instant = payload["instants"][0]
    assert instant["captured_input_hash"]
    assert instant["inactive_release_identity"]["release_id"] == "release-r1"
    assert instant["first_pipeline_divergence"] is None
    assert payload["evidence_sha256"] == canonical_payload_sha256(
        payload,
        omit=("evidence_sha256",),
    )


def test_forward_shadow_localizes_first_candidate_stage_divergence(
    tmp_path: Path,
):
    matching = {"eq_1c": 0.4, "eq_2c": 0.6}
    changed = {"eq_1c": 0.5, "eq_2c": 0.5}

    def trace(_artifact, _features, _bands, _context):
        return {
            "probabilities": changed,
            "stages": {
                "candidate_raw": matching,
                "candidate_postprocessed": matching,
                "candidate_preblend": changed,
                "candidate_current_blend": changed,
                "candidate_final": changed,
            },
        }

    payload = _generate(tmp_path, trace_runner=trace)

    assert payload["comparison_status"] == "DIVERGED"
    assert payload["summary"]["first_pipeline_divergence"] == {
        "snapshot_id": SNAPSHOT_ID,
        "captured_at_utc": CAPTURED_AT,
        "stage": "candidate_preblend",
    }
    instant = payload["instants"][0]
    assert instant["feature_vector"]["exact_match"] is True
    assert instant["distribution_components"]["first_divergence"] is None
    assert instant["base_distribution"]["strict_match"] is True
    assert instant["inactive_incumbent"]["strict_match"] is True
    assert instant["candidate_stage_matches_recorded_production"][
        "candidate_postprocessed"
    ]["strict_match"] is True
    assert instant["candidate_stage_matches_recorded_production"][
        "candidate_preblend"
    ]["strict_match"] is False


def test_forward_shadow_localizes_first_feature_field_divergence(
    tmp_path: Path,
):
    class ChangedFeatureModel(FakeModel):
        def live_feature_record(
            self,
            _sources,
            cutoff_hour,
            *,
            captured_at,
            model_version,
        ):
            feature = super().live_feature_record(
                _sources,
                cutoff_hour,
                captured_at=captured_at,
                model_version=model_version,
            )
            feature["cutoff_hour"] = 8
            return feature

    matching = {"eq_1c": 0.4, "eq_2c": 0.6}
    payload = _generate(
        tmp_path,
        trace_runner=_trace(matching),
        model_factory=lambda **_kwargs: ChangedFeatureModel(),
    )

    instant = payload["instants"][0]
    assert instant["first_pipeline_divergence"] == "feature_vector"
    assert instant["feature_vector"]["first_field_divergence"] == {
        "field": "cutoff_hour",
        "recorded_present": True,
        "inactive_present": True,
        "recorded_value_sha256": canonical_payload_sha256({"value": 7}),
        "inactive_value_sha256": canonical_payload_sha256({"value": 8}),
        "recorded_value": 7,
        "inactive_value": 8,
    }


def test_forward_shadow_rejects_tampered_captured_input(tmp_path: Path):
    captured_path, snapshot_path = _write_sources(tmp_path)
    captured = json.loads(captured_path.read_text(encoding="utf-8"))
    captured["sources"]["tampered"] = True
    captured_path.write_text(json.dumps(captured) + "\n", encoding="utf-8")

    with pytest.raises(
        InactiveReleaseForwardShadowError,
        match="invalid self-hash",
    ):
        generate_inactive_release_forward_shadow(
            release_dir=tmp_path / "releases" / "release-r1",
            expected_manifest_sha256="a" * 64,
            market_id="austin",
            target_date="2026-07-29",
            captured_inputs_path=captured_path,
            snapshot_tape_path=snapshot_path,
            window_start="2026-07-29T05:00:00+00:00",
            window_end="2026-07-29T05:01:00+00:00",
            active_pointer_path=tmp_path / "releases" / "current_release.json",
            repo_root=tmp_path,
            check_runtime=False,
            bundle_loader=lambda *_args, **_kwargs: _bundle(),
            model_factory=lambda **_kwargs: FakeModel(),
            trace_runner=_trace({"eq_1c": 0.4, "eq_2c": 0.6}),
        )

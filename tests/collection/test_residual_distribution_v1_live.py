import json
import pickle
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from weather.collection.live_variant_predictions import build_live_variant_prediction_rows
from weather.reporting.candidate_lifecycle.variant_registry import (
    SCHEMA_VERSION as REGISTRY_SCHEMA_VERSION,
)


class FakeModelClient:
    target_date = date(2026, 7, 12)

    def bin_probability(self, distribution, bin_data, calibration_context=None):
        del distribution, bin_data, calibration_context
        raise AssertionError(
            "residual_distribution_v1 must return band probabilities directly"
        )


class FallbackTrapModelClient(FakeModelClient):
    def predict_variant_distribution(self, variant, **kwargs):
        del variant, kwargs
        raise AssertionError(
            "generic model fallback must not run for residual_distribution_v1"
        )


def write_artifact(path: Path) -> Path:
    with path.open("wb") as handle:
        pickle.dump(
            {
                "schema_version": "residual_distribution_v1",
                # These traps prove the shadow adapter does not enter incumbent
                # density calibration or pooled postprocessing paths.
                "density_postprocess": {"enabled": True},
                "postprocess": {
                    "partition_normalization_enabled": True,
                    "current_blend_enabled": True,
                },
            },
            handle,
        )
    return path


def write_registry(path: Path, artifact: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": REGISTRY_SCHEMA_VERSION,
                "variants": [
                    {
                        "variant_id": "residual-shadow-v1",
                        "variant_family": "residual_distribution",
                        "lifecycle": "shadow",
                        "track": "no_market",
                        "active_for_headline": False,
                        "live_capture_enabled": True,
                        "artifact_path": str(artifact),
                        "live_runtime": "residual_distribution_v1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def band_rows():
    return [
        {
            "snapshot_id": "snap-residual",
            "range_label": "20 C or lower",
            "bin_kind": "lte",
            "bin_value_c": 20,
            "bin_value_hi_c": 20,
            "model_probability": 0.44,
            "market_yes": 0.40,
            "market_no": 0.60,
            "condition_id": "condition-residual",
            "market_status": "active",
        }
    ]


def build_rows(
    registry_path: Path,
    *,
    model=None,
    model_client=None,
    market_id="toronto",
):
    return build_live_variant_prediction_rows(
        snapshot_id="snap-residual",
        captured_at=datetime(2026, 7, 12, 16, 0, tzinfo=timezone.utc),
        event={
            "slug": "highest-temperature-in-toronto-on-july-12-2026",
            "updatedAt": "2026-07-12T15:59:00Z",
        },
        model=model
        or {
            "distribution": {20: 1.0},
            "feature_vector": {"cutoff_hour": 12, "forecast_high": 22.0},
            "source_diagnostics": [
                {"source": "open_meteo", "status": "fresh", "age_minutes": 5.0}
            ],
        },
        model_client=model_client or FakeModelClient(),
        band_rows=band_rows(),
        event_slug="highest-temperature-in-toronto-on-july-12-2026",
        market_id=market_id,
        target_date=date(2026, 7, 12),
        serving_model_version="incumbent-v1",
        captured_input_hash="c" * 64,
        runtime_fields={"runtime_code_state": "current"},
        registry_path=registry_path,
    )


def test_live_adapter_passes_exact_inputs_and_preserves_raw_probability(tmp_path):
    artifact = write_artifact(tmp_path / "residual.pkl")
    registry = write_registry(tmp_path / "registry.json", artifact)
    core_payload = {
        "status": "predicted",
        "probabilities": {"lte_20c": 0.23},
        "model_version": "residual-core-v1",
        "prediction_detail": "literal_core_distribution",
    }

    with patch(
        "weather.model.residual_distribution_v1.predict_residual_distribution_v1",
        return_value=core_payload,
    ) as predictor:
        rows = build_rows(registry, model_client=FallbackTrapModelClient())

    assert len(rows) == 1
    row = rows[0]
    assert row["prediction_status"] == "predicted"
    assert row["live_runtime"] == "residual_distribution_v1"
    assert row["model_version"] == "residual-core-v1"
    assert row["variant_probability"] == pytest.approx(0.23)
    assert row["serving_model_probability"] == pytest.approx(0.44)
    kwargs = predictor.call_args.kwargs
    assert kwargs["feature_vector"] == {"cutoff_hour": 12, "forecast_high": 22.0}
    assert kwargs["source_diagnostics"] == [
        {"source": "open_meteo", "status": "fresh", "age_minutes": 5.0}
    ]
    assert kwargs["market_id"] == "toronto"
    assert kwargs["unit"] == "C"
    assert kwargs["band_rows"] == band_rows()
    assert kwargs["artifact"]["schema_version"] == "residual_distribution_v1"


@pytest.mark.parametrize("status", ["skipped", "failed"])
def test_live_adapter_preserves_named_terminal_status_and_details(tmp_path, status):
    artifact = write_artifact(tmp_path / "residual.pkl")
    registry = write_registry(tmp_path / "registry.json", artifact)
    reason = f"named_{status}_reason"
    detail = f"named {status} detail"

    with patch(
        "weather.model.residual_distribution_v1.predict_residual_distribution_v1",
        return_value={
            "status": status,
            "failure_reason": reason,
            "failure_detail": detail,
        },
    ):
        rows = build_rows(registry)

    assert len(rows) == 1
    assert rows[0]["prediction_status"] == status
    assert rows[0]["failure_reason"] == reason
    assert rows[0]["failure_detail"] == detail
    assert rows[0]["variant_probability"] is None
    assert rows[0]["serving_model_probability"] == pytest.approx(0.44)


def test_live_adapter_contains_core_exception_without_touching_incumbent(tmp_path):
    artifact = write_artifact(tmp_path / "residual.pkl")
    registry = write_registry(tmp_path / "registry.json", artifact)

    with patch(
        "weather.model.residual_distribution_v1.predict_residual_distribution_v1",
        side_effect=RuntimeError("shadow boom"),
    ):
        rows = build_rows(registry)

    assert len(rows) == 1
    assert rows[0]["prediction_status"] == "failed"
    assert rows[0]["failure_reason"] == "runtime_exception"
    assert "shadow boom" in rows[0]["failure_detail"]
    assert rows[0]["live_runtime"] == "residual_distribution_v1"
    assert rows[0]["serving_model_probability"] == pytest.approx(0.44)


def test_live_adapter_preserves_real_core_invalid_artifact_failure(tmp_path):
    artifact = write_artifact(tmp_path / "residual.pkl")
    registry = write_registry(tmp_path / "registry.json", artifact)

    rows = build_rows(registry)

    assert len(rows) == 1
    assert rows[0]["prediction_status"] == "failed"
    assert rows[0]["failure_reason"] == "invalid_artifact"
    assert "artifact" in rows[0]["failure_detail"].lower()
    assert rows[0]["live_runtime"] == "residual_distribution_v1"
    assert rows[0]["serving_model_probability"] == pytest.approx(0.44)


def test_live_adapter_rejects_unknown_market_before_core_call(tmp_path):
    artifact = write_artifact(tmp_path / "residual.pkl")
    registry = write_registry(tmp_path / "registry.json", artifact)

    with patch(
        "weather.model.residual_distribution_v1.predict_residual_distribution_v1"
    ) as predictor:
        rows = build_rows(registry, market_id="not-a-registered-market")

    assert len(rows) == 1
    assert rows[0]["prediction_status"] == "skipped"
    assert rows[0]["failure_reason"] == "abstain_unknown_market"
    assert "not-a-registered-market" in rows[0]["failure_detail"]
    predictor.assert_not_called()

from __future__ import annotations

import ast
import csv
import inspect
from datetime import timedelta

import pytest
from sklearn.ensemble import HistGradientBoostingRegressor

from weather.calibration import multiyear_nwp_residual_external as subject
from weather.schema_registry import schema_version


def test_frozen_source_model_and_transfer_identities_are_exact():
    assert subject.SOURCE_BRANCH == (
        "codex/workstation-multiyear-nwp-residual-2026-09-88a"
    )
    assert subject.SOURCE_TIP == "798225bc200d2909fb32175e21d870f86877faef"
    assert subject.SOURCE_TREE == "c9bb99a756bb81d7f3458f0763e63b15ebebb894"
    assert subject.FROZEN_DESIGN_FILE_SHA256 == (
        "0667fdc204360122f44e35f2ef31dad5d6f7f53afd83bfd09ba0f0a50874bc65"
    )
    assert subject.FROZEN_DESIGN_SHA256 == (
        "bd4bdb2ebcdd67a498e461b455f77bc9ca5a88f73bb19dae389e4bb28e26c0fb"
    )
    assert subject.FROZEN_MODEL_SHA256 == {
        "temperature_residual_baseline": (
            "c1ee07eef33016633ebf1ffdf847c7b55d90a2420b198eac7fb07ee88f5c2797"
        ),
        "eleven_field_residual_challenger": (
            "0ae3e67cfcda420a9c0103959b2c79cac6438d7fadf162b41f36a47919862ab5"
        ),
    }
    assert subject.TRANSFER_MANIFEST_SHA256 == (
        "1794455e40f967411d05660ff4ac785e1fab48caccb8fbdfb3df7aa31438712a"
    )


def test_external_cohorts_are_exact_and_never_overlap():
    pre_start, pre_end = subject.COHORTS["pre_boundary"]
    post_start, post_end = subject.COHORTS["post_boundary_directional"]

    assert (pre_end - pre_start).days + 1 == 58
    assert (post_end - post_start).days + 1 == 10
    assert pre_end + timedelta(days=1) == post_start
    assert post_start.isoformat() == "2026-07-31"
    assert subject.BOUNDARY_ANCHOR == "b77cfbed"


def _evaluation(point: float) -> dict:
    return {
        "crossed_bootstrap": {
            "endpoints": {
                "primary__squared_error_improvement": {"point": point},
                "all_leads_sensitivity__squared_error_improvement": {
                    "point": point
                },
            }
        }
    }


@pytest.mark.parametrize(
    ("pre", "post", "expected"),
    [
        (0.1, 0.2, "EXTERNAL_DIRECTION_CONSISTENT"),
        (0.1, -0.2, "EXTERNAL_DIRECTION_MIXED"),
        (-0.1, -0.2, "EXTERNAL_DIRECTION_ADVERSE"),
        (0.0, 0.2, "EXTERNAL_DIRECTION_MIXED"),
    ],
)
def test_external_disposition_is_directional_and_non_authorizing(
    pre, post, expected
):
    result = subject.external_disposition(
        {
            "pre_boundary": _evaluation(pre),
            "post_boundary_directional": _evaluation(post),
        }
    )

    assert result["disposition"] == expected
    assert result["changes_original_verdict"] is False
    assert result["original_verdict"] == "INCONCLUSIVE_UNDERPOWERED"
    assert result["can_authorize_distribution"] is False


def test_no_refit_guard_forbids_estimator_fit():
    estimator = HistGradientBoostingRegressor()

    with subject._no_refit_guard() as audit:
        with pytest.raises(subject.IntegrityError, match="refit attempted"):
            estimator.fit([[0.0], [1.0]], [0.0, 1.0])

    assert audit == {"fit_calls_attempted": 1, "active": False}


def test_external_evaluator_contains_no_estimator_fit_call():
    tree = ast.parse(inspect.getsource(subject))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "fit"
    ]
    assert calls == []


def test_outcome_loader_skips_2025_before_reading_outcome_value(tmp_path):
    fieldnames = (
        "schema_version",
        "local_date",
        "temperature_unit",
        "row_count",
        "max_temp_bucket_native",
    )
    inventory = []
    for market, path in subject.frozen._outcome_paths(tmp_path).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "schema_version": "fixture_v1",
                    "local_date": "2025-07-01",
                    "temperature_unit": subject.frozen.MARKET_UNITS[market],
                    "row_count": 24,
                    "max_temp_bucket_native": "MUST_NOT_BE_PARSED",
                }
            )
            for start, end in subject.COHORTS.values():
                for target_date in subject._date_range(start, end):
                    writer.writerow(
                        {
                            "schema_version": "fixture_v1",
                            "local_date": target_date,
                            "temperature_unit": subject.frozen.MARKET_UNITS[
                                market
                            ],
                            "row_count": 24,
                            "max_temp_bucket_native": 25,
                        }
                    )
        inventory.append(
            {
                "market": market,
                "station": subject.frozen.MARKET_STATIONS[market],
                "relative_path": path.relative_to(tmp_path).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": subject.frozen.sha256_file(path),
            }
        )
    amendment = {
        "input_binding": {
            "mirror_root": str(tmp_path),
            "outcome_source_file_inventory": inventory,
            "outcome_source_file_inventory_sha256": (
                subject.frozen.canonical_sha256(inventory)
            ),
        }
    }

    outcomes, audit = subject.load_2026_outcomes(amendment)

    assert len(outcomes) == 68 * len(subject.frozen.MARKETS)
    assert audit["outcome_value_access_2025"] == 0
    assert audit["semantic_outcome_value_access_by_year"] == {"2026": 816}
    assert audit["ignored_non_2026_rows_without_outcome_value_access"] == 12


def test_attempt_seal_is_create_only_and_authorizes_no_refit(tmp_path):
    amendment = tmp_path / "amendment.json"
    amendment.write_text("{}\n", encoding="utf-8")

    path, attempt = subject._seal_attempt(tmp_path / "run", amendment, {})

    assert path.is_file()
    assert attempt["model_refits_authorized"] == 0
    assert attempt["probability_model_refits_authorized"] == 0
    assert attempt["2025_outcome_access_authorized"] == 0
    assert attempt["rerun_authorized"] is False
    with pytest.raises(subject.IntegrityError, match="create-only"):
        subject._seal_attempt(tmp_path / "run", amendment, {})


def test_external_evidence_schemas_are_registered():
    assert schema_version("multiyear_nwp_residual_external_transfer") == (
        subject.TRANSFER_SCHEMA
    )
    assert schema_version("multiyear_nwp_residual_external_amendment") == (
        subject.AMENDMENT_SCHEMA
    )
    assert schema_version("multiyear_nwp_residual_external_attempt") == (
        subject.ATTEMPT_SCHEMA
    )
    assert schema_version("multiyear_nwp_residual_external_result") == (
        subject.RESULT_SCHEMA
    )
    assert schema_version("multiyear_nwp_residual_external_verification") == (
        subject.VERIFICATION_SCHEMA
    )

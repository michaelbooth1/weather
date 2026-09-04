from __future__ import annotations

import ast
import csv
from datetime import date
import inspect
import json
from pathlib import Path

import pytest

from weather.calibration import (
    multiyear_nwp_residual_external_completion as subject,
)
from weather.schema_registry import schema_version


def test_completion_identities_and_accounting_are_exact():
    assert subject.SOURCE_TIP == "734f14adba7055ba7459db8a9ab4a16983a1b202"
    assert subject.SOURCE_TREE == "1468c089b62e09a09a13006a1936c32787e4c64b"
    assert subject.SOURCE_IMPLEMENTATION == (
        "e47857bad276e767f15baa98ccf0347cf2048ec0"
    )
    assert subject.EXPORT_PAYLOAD_SHA256 == (
        "3cef2fe7553cfd0450e78e7c45deda2d186beb607f34318ead545ce5e3863860"
    )
    assert subject.FROZEN_MODEL_SHA256 == {
        "temperature_residual_baseline": (
            "c1ee07eef33016633ebf1ffdf847c7b55d90a2420b198eac7fb07ee88f5c2797"
        ),
        "eleven_field_residual_challenger": (
            "0ae3e67cfcda420a9c0103959b2c79cac6438d7fadf162b41f36a47919862ab5"
        ),
    }
    assert subject.EXPECTED == {
        "requested_cells": 816,
        "admitted_old": 720,
        "admitted_export": 94,
        "admitted_union": 814,
        "exclusions": 2,
        "pre_expected": 696,
        "pre_admitted": 694,
        "pre_exclusions": 2,
        "pre_dates": 58,
        "post_expected": 120,
        "post_admitted": 120,
        "post_exclusions": 0,
        "post_dates": 10,
    }
    assert subject.EXPECTED_EXCLUSIONS == {
        ("atlanta", "2026-06-06"),
        ("miami", "2026-06-06"),
    }


def _evaluation(primary: float, sensitivity: float) -> dict:
    return {
        "crossed_bootstrap": {
            "endpoints": {
                "primary__squared_error_improvement": {"point": primary},
                "all_leads_sensitivity__squared_error_improvement": {
                    "point": sensitivity
                },
            }
        }
    }


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        ((0.1, 0.2, 0.3, 0.4), "EXTERNAL_DIRECTION_CONSISTENT"),
        ((-0.1, -0.2, -0.3, -0.4), "EXTERNAL_DIRECTION_ADVERSE"),
        ((0.1, 0.2, -0.3, -0.4), "EXTERNAL_DIRECTION_MIXED"),
        ((0.0, 0.2, 0.3, 0.4), "EXTERNAL_DIRECTION_MIXED"),
    ],
)
def test_directional_rule_uses_only_four_predeclared_mse_signs(points, expected):
    result = subject.external_disposition(
        {
            "pre_boundary": _evaluation(points[0], points[1]),
            "post_boundary_directional": _evaluation(points[2], points[3]),
        }
    )

    assert result["disposition"] == expected
    assert result["original_verdict"] == "INCONCLUSIVE_UNDERPOWERED"
    assert result["changes_original_verdict"] is False
    assert result["confirmation"] is False
    assert result["authorized_actions"] == []


def test_completion_evaluator_contains_no_fit_or_partial_fit_call():
    tree = ast.parse(inspect.getsource(subject))
    forbidden = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"fit", "partial_fit"}
    ]
    assert forbidden == []


def _gap_entries(request_keys: set[tuple[str, str]]) -> list[dict]:
    entries = []
    for market in subject.frozen.MARKETS:
        for target in sorted(subject._required_dates()):
            key = (market, target)
            if key in request_keys:
                status = "missing"
                row_count = None
            elif key in subject.EXPECTED_EXCLUSIONS:
                status = "present_below_threshold"
                row_count = 12
            else:
                status = "present_admissible"
                row_count = 24
            entries.append(
                {
                    "market": market,
                    "target_date": target,
                    "status": status,
                    "row_count": row_count,
                }
            )
    return entries


def test_old_loader_skips_2025_values_and_preserves_the_720_plus_2_gap(
    tmp_path: Path,
):
    completion_spec = json.loads(
        (
            Path(__file__).parents[2]
            / "docs/roadmap/wu-outcome-admissible-gap-production-export-spec-2026-09-100g.json"
        ).read_text(encoding="utf-8")
    )
    request_keys = {
        (row["market"], row["target_date"])
        for row in completion_spec["request"]["keys"]
    }
    inventory = []
    for market, path in subject.frozen._outcome_paths(tmp_path).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(
                (
                    "schema_version",
                    "local_date",
                    "temperature_unit",
                    "row_count",
                    "max_temp_bucket_native",
                )
            )
            writer.writerow(("fixture_v1", "2025-07-01", "BAD", 24, "DO_NOT_PARSE"))
            for target in sorted(subject._required_dates()):
                key = (market, target)
                if key in request_keys:
                    continue
                row_count = 12 if key in subject.EXPECTED_EXCLUSIONS else 24
                writer.writerow(
                    (
                        "fixture_v1",
                        target,
                        subject.frozen.MARKET_UNITS[market],
                        row_count,
                        25,
                    )
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
        }
    }
    gap = {"entries": _gap_entries(request_keys)}

    outcomes, exclusions, audit = subject.load_old_outcomes_once(amendment, gap)

    assert len(outcomes) == 720
    assert len(exclusions) == 2
    assert audit["files_opened_once"] == 12
    assert audit["admitted_outcome_values_parsed"] == 720
    assert audit["outcome_value_access_2025"] == 0
    assert audit["ignored_non_2026_rows_without_outcome_value_access"] == 12


def _protected_case(tmp_path: Path):
    market = "toronto"
    target = "2026-08-08"
    request = {
        "market": market,
        "target_date": target,
        "provenance_side": "post_boundary_directional",
        "settlement_unit": "C",
        "station": "cyyz",
    }
    configured = next(item for item in subject.BUILTIN_SPECS if item.id == market)
    ledger_path = f"data/settlements/{market}/ledger.jsonl"
    daily_path = "data/wunderground/cyyz/daily/daily_summary.csv"
    ledger_sha = "a" * 64
    daily_sha = "b" * 64
    row = {
        "schema_version": subject.export_contract.EXPORT_ROW_SCHEMA,
        "market": market,
        "target_date": target,
        "provenance_side": "post_boundary_directional",
        "settlement_bucket_native": 31,
        "settlement_unit": "C",
        "wu_daily_row_count": 24,
        "settlement_source": "daily_summary",
        "resolution_source_type": "wunderground_history",
        "resolution_wu_history_id": configured.wu_history_id,
        "resolution_station": configured.icao,
        "resolution_timezone": configured.timezone,
        "source_event_slug": f"{configured.slug_prefix}-august-8-2026",
        "source_revision_id": "revision-1",
        "source_revision_number": 1,
        "source_recorded_at_utc": "2026-09-04T00:00:00+00:00",
        "source_label_hash": "c" * 64,
        "source_ledger_relative_path": ledger_path,
        "source_ledger_sha256": ledger_sha,
        "source_daily_summary_relative_path": daily_path,
        "source_daily_summary_sha256": daily_sha,
    }
    payload = tmp_path / "wu-outcomes.jsonl"
    payload.write_bytes(subject.export_contract.canonical_json_bytes(row) + b"\n")
    manifest = {
        "payload_file": {"rows": 1},
        "source_files": [
            {
                "role": "settlement_ledger",
                "relative_path": ledger_path,
                "bytes_before": 1,
                "bytes_after": 1,
                "sha256_before": ledger_sha,
                "sha256_after": ledger_sha,
            },
            {
                "role": "wu_daily_summary",
                "relative_path": daily_path,
                "bytes_before": 1,
                "bytes_after": 1,
                "sha256_before": daily_sha,
                "sha256_after": daily_sha,
            },
        ],
    }
    return payload, request, manifest


def test_protected_loader_validates_and_retains_one_native_outcome(tmp_path: Path):
    payload, request, manifest = _protected_case(tmp_path)

    outcomes, audit = subject.load_protected_outcomes_once(
        payload_path=payload,
        requests=[request],
        manifest=manifest,
    )

    assert outcomes[("toronto", "2026-08-08")] == {
        "outcome_native": 31,
        "native_unit": "C",
        "wu_daily_row_count": 24,
        "outcome_source_class": subject.EXPORT_SOURCE_CLASS,
        "outcome_source_identity": "c" * 64,
    }
    assert audit["files_opened_once"] == 1
    assert audit["admitted_outcome_values_parsed"] == 1


def test_combination_rejects_overlap_and_closes_exact_814_plus_2():
    request_keys = {
        ("atlanta", "2026-06-15"),
        ("austin", "2026-06-15"),
    }
    required = {
        (market, target)
        for market in subject.frozen.MARKETS
        for target in subject._required_dates()
    }
    exported_keys = set(sorted(required - subject.EXPECTED_EXCLUSIONS)[:94])
    old_keys = required - subject.EXPECTED_EXCLUSIONS - exported_keys
    old = {key: {} for key in old_keys}
    exported = {key: {} for key in exported_keys}
    exclusions = [
        {"market": market, "target_date": target}
        for market, target in subject.EXPECTED_EXCLUSIONS
    ]

    combined, audit = subject.combine_outcomes(
        old=old, exported=exported, exclusions=exclusions
    )
    assert len(combined) == 814
    assert audit["accounted_cells"] == 816

    duplicate = next(iter(old))
    with pytest.raises(subject.IntegrityError, match="accounting"):
        subject.combine_outcomes(
            old=old,
            exported={**exported, duplicate: {}},
            exclusions=exclusions,
        )


def test_attempt_seal_is_create_only_fsynced_and_non_refitting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("WEATHER_WORKSTATION_WRAPPER_ACTIVE", "1")
    amendment_path = tmp_path / "amendment.json"
    amendment_path.write_text("{}\n", encoding="utf-8")
    amendment = {
        "amendment_sha256": "a" * 64,
        "cohorts": {},
        "input_binding": {
            "prior_audit": {"audit_sha256": "b" * 64},
            "outcome_contract_audit": {"audit_sha256": "c" * 64},
        },
        "result_contract": {"attempt": "attempt.json"},
    }

    path, attempt = subject._seal_attempt(
        tmp_path / "run", amendment_path, amendment, {}
    )

    assert path.is_file()
    assert attempt["file_fsync_required"] is True
    assert attempt["model_refits_authorized"] == 0
    assert attempt["partial_fits_authorized"] == 0
    assert attempt["probability_model_refits_authorized"] == 0
    assert attempt["model_writes_authorized"] == 0
    assert attempt["rerun_authorized"] is False
    with pytest.raises(subject.IntegrityError, match="already exists"):
        subject._seal_attempt(tmp_path / "run", amendment_path, amendment, {})


def test_completion_schemas_and_wrapper_module_are_registered():
    assert schema_version("multiyear_nwp_residual_external_completion_amendment") == (
        subject.AMENDMENT_SCHEMA
    )
    assert schema_version("multiyear_nwp_residual_external_completion_attempt") == (
        subject.ATTEMPT_SCHEMA
    )
    assert schema_version("multiyear_nwp_residual_external_completion_result") == (
        subject.RESULT_SCHEMA
    )
    assert schema_version(
        "multiyear_nwp_residual_external_completion_verification"
    ) == subject.VERIFICATION_SCHEMA
    wrapper = (
        Path(__file__).parents[2] / "scripts/ops/workload_admission.ps1"
    ).read_text(encoding="utf-8-sig")
    assert (
        '"weather.calibration.multiyear_nwp_residual_external_completion"'
        in wrapper
    )

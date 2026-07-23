from __future__ import annotations

from pathlib import Path

import pytest

from weather.market.market_registry import REGISTRY
from weather.reporting.research.ordinal_smoothing_fresh_confirmation_audit import (
    FreshConfirmationAuditError,
    PlanningInputs,
    _daily_summary_source,
    _parse_positive_grid,
    build_cost_estimate,
    build_date_panel,
    run_w0_replay_gate,
    validate_paths,
)


def _entry(market_id: str, **overrides):
    row = {
        "market_id": market_id,
        "target_date": "2026-07-11",
        "pin_complete": True,
        "settlement_bucket_present": True,
        "daily_summary_settlement": True,
        "identity_complete": True,
        "exact_current_identity_complete": True,
    }
    row.update(overrides)
    return row


def test_date_panel_requires_every_contract_for_all_canonical_markets():
    rows = [_entry(market_id) for market_id in REGISTRY]

    panel, strict, counterfactual = build_date_panel(("2026-07-11",), rows)

    assert strict == ["2026-07-11"]
    assert counterfactual == ["2026-07-11"]
    assert panel[0]["strict_confirmation_eligible"] is True


def test_date_panel_fails_closed_on_one_stale_identity():
    rows = [_entry(market_id) for market_id in REGISTRY]
    rows[0]["exact_current_identity_complete"] = False

    panel, strict, counterfactual = build_date_panel(("2026-07-11",), rows)

    assert strict == []
    assert counterfactual == ["2026-07-11"]
    assert panel[0]["exact_12_market_panel"] is True
    assert panel[0]["exact_current_identity_complete"] is False
    assert panel[0]["strict_confirmation_eligible"] is False


def test_date_panel_fails_closed_on_missing_market():
    rows = [_entry(market_id) for market_id in list(REGISTRY)[:-1]]

    panel, strict, counterfactual = build_date_panel(("2026-07-11",), rows)

    assert strict == []
    assert counterfactual == []
    assert panel[0]["market_count"] == len(REGISTRY) - 1
    assert panel[0]["exact_12_market_panel"] is False
    assert panel[0]["missing_markets"]


def test_cost_estimate_separates_validated_reuse_from_cold_start():
    planning = PlanningInputs(
        existing_sigma=0.75,
        sigmas=(0.5, 0.75, 1.0, 1.5),
        weights=(0.1, 0.25, 0.5, 0.75, 1.0),
        tune_arm_minutes=25.0,
        tune_cache_bytes=2_000_000_000,
        reference_holdout_dates=15,
        holdout_arm_minutes=34.0,
        holdout_cache_bytes=3_000_000_000,
        old_tune_dates=17,
    )

    result = build_cost_estimate(planning, confirmation_dates=10)

    assert result["factorial_best_case_reuse"]["new_tune_arms"] == 15
    assert result["factorial_best_case_reuse"]["estimated_tune_minutes"] == 375.0
    assert result["factorial_cold_start"]["tune_arms"] == 21
    assert result["preferred_one_variable_sigma_refinement_best_case"]["new_tune_arms"] == 4
    assert result["unit_semantics"]["f_market_bandwidth_c_equivalent"] == pytest.approx(
        0.75 / 1.8
    )
    assert result["selection_firewall"]["original_h1_holdout_opened_for_selection"] is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("daily_summary", True),
        ("promotion_corpus:daily_summary", True),
        ("manual_override", False),
        (None, False),
    ],
)
def test_daily_summary_source_contract(value, expected):
    assert _daily_summary_source(value) is expected


def test_positive_grid_is_strictly_sorted_and_unique():
    assert _parse_positive_grid("0.5,0.75,1", "sigma") == (0.5, 0.75, 1.0)
    with pytest.raises(FreshConfirmationAuditError, match="unique and sorted"):
        _parse_positive_grid("0.75,0.5", "sigma")
    with pytest.raises(FreshConfirmationAuditError, match="positive"):
        _parse_positive_grid("0,0.5", "sigma")


def test_output_paths_cannot_alias_snapshot_root(tmp_path: Path):
    snapshots = tmp_path / "data" / "snapshots"
    snapshots.mkdir(parents=True)

    with pytest.raises(FreshConfirmationAuditError, match="read-only input data tree"):
        validate_paths(
            snapshots,
            snapshots / "manifest.json",
            tmp_path / "audit.json",
            tmp_path / "audit.md",
        )


def test_output_paths_must_be_distinct(tmp_path: Path):
    snapshots = tmp_path / "data" / "snapshots"
    snapshots.mkdir(parents=True)
    duplicate = tmp_path / "audit.json"

    with pytest.raises(FreshConfirmationAuditError, match="distinct"):
        validate_paths(snapshots, duplicate, duplicate, tmp_path / "audit.md")


class _FakeModel:
    def __init__(self, market_id):
        self.market_id = market_id
        self.record = None


def _fake_replay(model, record):
    model.record = record
    return record["current_distribution"]


def _fake_identity(model):
    return model.record["current_identity"]


def _identity(value):
    return {
        "schema_version": "weather_model_replay_identity_v0.1",
        "model_version": "v-test",
        "market_id": "atlanta",
        "active_model_kind": "hgb",
        "code_hash": value,
        "artifact_hash": "artifact",
        "identity_hash": value,
    }


def test_counterfactual_w0_gate_can_pass_with_changed_recorded_identity(tmp_path: Path):
    recorded = _identity("recorded")
    current = _identity("current")
    record = {
        "model_identity": recorded,
        "model_version": "v-test",
        "recorded_distribution": {"70": 0.4, "71": 0.6},
        "current_distribution": {"70": 0.3, "71": 0.7},
        "current_identity": current,
    }
    manifest = {
        "entries": [
            {
                "target_date": "2026-07-11",
                "market_id": "atlanta",
                "folder_name": "atlanta-day",
                "snapshot_ids": ["one"],
            }
        ]
    }

    result = run_w0_replay_gate(
        manifest,
        snapshots_root=tmp_path,
        target_dates=("2026-07-11",),
        corpus_warning_count=0,
        record_loader=lambda _folder: {"one": record},
        model_factory=_FakeModel,
        replay_fn=_fake_replay,
        replay_identity_fn=_fake_identity,
    )

    # One-market fixtures intentionally fail the production 12-market per-date
    # display row, but the global replay/fidelity/corpus gate itself is clean.
    assert result["status"] == "PASS"
    assert result["fidelity"]["same_identity_n"] == 0
    assert result["fidelity"]["changed_identity_n"] == 1
    assert result["fidelity"]["changed_identity_mean_l1"] == pytest.approx(0.2)
    assert result["determinism_canary"]["mismatch_count"] == 0
    assert result["outcome_blind"] is True


def test_counterfactual_w0_gate_blocks_nondeterministic_repeat(tmp_path: Path):
    current = _identity("current")
    calls = 0

    def nondeterministic(model, record):
        nonlocal calls
        calls += 1
        model.record = record
        return {"70": 0.4, "71": 0.6} if calls == 1 else {"70": 0.5, "71": 0.5}

    record = {
        "model_identity": current,
        "model_version": "v-test",
        "recorded_distribution": {"70": 0.4, "71": 0.6},
        "current_identity": current,
    }
    manifest = {
        "entries": [
            {
                "target_date": "2026-07-11",
                "market_id": "atlanta",
                "folder_name": "atlanta-day",
                "snapshot_ids": ["one"],
            }
        ]
    }

    result = run_w0_replay_gate(
        manifest,
        snapshots_root=tmp_path,
        target_dates=("2026-07-11",),
        corpus_warning_count=0,
        record_loader=lambda _folder: {"one": record},
        model_factory=_FakeModel,
        replay_fn=nondeterministic,
        replay_identity_fn=_fake_identity,
    )

    assert result["status"] == "BLOCK"
    assert result["determinism_canary"]["mismatch_count"] == 1
    assert any("repeat canary" in reason for reason in result["blockers"])

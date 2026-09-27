"""Synthetic International economics snapshots; no venue or runtime inputs."""

from copy import deepcopy
import json

import pytest

from weather.market import exchange_economics as economics


NOW = "2026-09-27T12:00:00+00:00"
TARGET_DATE = "2026-09-27"
# Captured from the synthetic 55-market fixture on unmodified master 965374a0.
LEGACY_SNAPSHOT_HASH = "e06d9b8849f77e0eba10e6ca2889682d"


def _bind(payload):
    payload["source_hash"] = economics.source_proof_hash(payload)
    payload["source_hash_sha256"] = payload["source_hash"]
    payload["exchange_economics_hash"] = economics.snapshot_hash(payload)
    payload["snapshot_id"] = "xecon-" + payload["exchange_economics_hash"][:16]
    return payload


def _snapshot(fine_counts=(12, 15), *, previous_day=False):
    payload = economics.build_snapshot_payload(
        target_date=TARGET_DATE,
        verified_at_utc=NOW,
        effective_date="2026-03-30",
    )
    prototype = payload["markets"][0]
    payload["markets"] = []
    for location, count, fine_count in zip(("atlanta", "nyc"), (33, 22), fine_counts):
        for index in range(count):
            market = deepcopy(prototype)
            identity = len(payload["markets"]) + 1
            market.update(
                location_id=location,
                condition_id=f"0x{identity:064x}",
                token_ids=[str(2 * identity), str(2 * identity + 1)],
                order_price_min_tick_size=0.001 if index < fine_count else 0.01,
            )
            payload["markets"].append(market)
    payload["market_rules"]["tick_size"] = None
    verification = payload["source_verification"]
    for key in ("condition_count", "registry_condition_count", "gamma_condition_count"):
        verification[key] = len(payload["markets"])
    if previous_day:
        payload["target_date"] = payload["verified_for_target_date"] = "2026-09-26"
        payload["verified_at_utc"] = "2026-09-26T10:00:00+00:00"
    return _bind(payload)


def _report(tmp_path, current, accepted):
    current_path = tmp_path / "current.json"
    accepted_path = tmp_path / "accepted.json"
    current_path.write_text(json.dumps(current), encoding="utf-8")
    accepted_bytes = json.dumps(accepted).encode("utf-8")
    accepted_path.write_bytes(accepted_bytes)
    report = economics.build_drift_report(
        current_path, accepted_path, target_date=TARGET_DATE, now=NOW,
    )
    assert accepted_path.read_bytes() == accepted_bytes
    return report


def test_tick_mix_shift_passes_with_previous_day_accepted_baseline(tmp_path):
    accepted = _snapshot(previous_day=True)
    assert accepted["exchange_economics_hash"] == LEGACY_SNAPSHOT_HASH
    accepted["accepted_at_utc"] = "2026-09-26T12:00:00+00:00"
    accepted["accepted_gate"] = {
        "status": "PASS",
        "snapshot_hash": accepted["exchange_economics_hash"],
        "payout_asset_conflict_acknowledged": True,
    }
    current = _snapshot((15, 12))

    report = _report(tmp_path, current, accepted)

    assert report["current_gate"]["status"] == "PASS"
    assert report["status"] == "PASS"
    assert report["material_changes"] == []
    assert report["rescore_required"] is False
    assert report["blockers"] == []
    assert report["accepted_snapshot_hash"] == accepted["accepted_gate"]["snapshot_hash"]
    assert report["current_snapshot_hash"] != report["accepted_snapshot_hash"]
    assert report["market_tick_size_mixes"] == {
        "accepted": [
            {"location_id": "atlanta", "tick_sizes": [
                {"tick_size": 0.001, "market_count": 12},
                {"tick_size": 0.01, "market_count": 21},
            ]},
            {"location_id": "nyc", "tick_sizes": [
                {"tick_size": 0.001, "market_count": 15},
                {"tick_size": 0.01, "market_count": 7},
            ]},
        ],
        "current": [
            {"location_id": "atlanta", "tick_sizes": [
                {"tick_size": 0.001, "market_count": 15},
                {"tick_size": 0.01, "market_count": 18},
            ]},
            {"location_id": "nyc", "tick_sizes": [
                {"tick_size": 0.001, "market_count": 12},
                {"tick_size": 0.01, "market_count": 10},
            ]},
        ],
    }


@pytest.mark.parametrize("field,value", [
    ("rate", 0.06), ("rebate_rate", 0.3), ("exponent", 2),
    ("taker_only", False), ("fees_enabled", False), ("order_min_size", 10),
])
def test_real_fee_profile_change_still_blocks(tmp_path, field, value):
    accepted = _snapshot(previous_day=True)
    current = _snapshot((15, 12))
    market = current["markets"][0]
    if field in market["fee_schedule"]:
        market["fee_schedule"][field] = value
    else:
        market[field] = value
    _bind(current)

    report = _report(tmp_path, current, accepted)

    assert report["status"] == "BLOCK"
    assert report["rescore_required"] is True
    assert [row["field"] for row in report["material_changes"]] == ["market_fee_rule_profiles"]
    assert "exchange_economics_material_drift_rescore_required" in {
        row["code"] for row in report["blockers"]
    }


@pytest.mark.parametrize("new_tick", [0.005, 0.0001, None])
def test_new_or_missing_tick_value_is_material(tmp_path, new_tick):
    accepted = _snapshot(previous_day=True)
    current = _snapshot((15, 12))
    current["markets"][0]["order_price_min_tick_size"] = new_tick
    _bind(current)

    report = _report(tmp_path, current, accepted)

    assert report["status"] == "BLOCK"
    assert report["rescore_required"] is True
    assert [row["field"] for row in report["material_changes"]] == ["market_tick_size_values"]


@pytest.mark.parametrize("fine_counts", [(0, 15), (33, 15), (12, 0), (12, 22)])
def test_distinct_tick_value_disappearance_is_material(tmp_path, fine_counts):
    report = _report(tmp_path, _snapshot(fine_counts), _snapshot(previous_day=True))

    assert report["current_gate"]["status"] == "PASS"
    assert report["status"] == "BLOCK"
    assert [row["field"] for row in report["material_changes"]] == ["market_tick_size_values"]


def test_profiles_are_distinct_per_city_not_pooled_across_cities():
    accepted = _snapshot()
    current = deepcopy(accepted)
    # Both cities already contain both ticks; moving a fee profile between
    # cities must remain visible even when the fleet-wide set is unchanged.
    accepted["markets"][0]["fee_schedule"]["rate"] = 0.06
    current["markets"][-1]["fee_schedule"]["rate"] = 0.06
    assert [row["field"] for row in economics.compare_snapshots(current, accepted)] == [
        "market_fee_rule_profiles",
    ]


def test_profile_counts_and_market_order_are_not_material():
    accepted = _snapshot()
    current = deepcopy(accepted)
    current["markets"].pop()
    current["markets"].reverse()
    assert economics.compare_snapshots(current, accepted) == []


def test_snapshot_hash_stays_legacy_compatible_and_drift_does_not_mutate_inputs():
    accepted = _snapshot(previous_day=True)
    current = _snapshot((15, 12))
    before = deepcopy((accepted, current))

    economics.compare_snapshots(current, accepted)

    assert (accepted, current) == before
    assert economics.snapshot_hash(accepted) == LEGACY_SNAPSHOT_HASH
    assert economics.snapshot_hash(json.loads(json.dumps(accepted))) == LEGACY_SNAPSHOT_HASH
    assert economics.snapshot_hash(_snapshot(previous_day=True)) == LEGACY_SNAPSHOT_HASH
    assert economics.snapshot_hash(current) != LEGACY_SNAPSHOT_HASH


def test_distinct_fee_profiles_preserve_removal_and_ignore_multiplicity():
    accepted = _snapshot()
    accepted["markets"][0]["fee_schedule"]["rate"] = 0.06
    current = deepcopy(accepted)
    current["markets"][1]["fee_schedule"]["rate"] = 0.06
    assert economics.compare_snapshots(current, accepted) == []
    current["markets"][0]["fee_schedule"]["rate"] = 0.05
    current["markets"][1]["fee_schedule"]["rate"] = 0.05
    assert [row["field"] for row in economics.compare_snapshots(current, accepted)] == [
        "market_fee_rule_profiles",
    ]


def test_tick_mix_change_does_not_bypass_hash_or_freshness_gate(tmp_path):
    accepted = _snapshot(previous_day=True)
    current = _snapshot((15, 12))
    current["exchange_economics_hash"] = accepted["exchange_economics_hash"]
    report = _report(tmp_path, current, accepted)
    assert report["status"] == "BLOCK"
    assert "snapshot_hash_matches_content" in report["current_gate"]["missing"]
    assert report["rescore_required"] is False

    current = _snapshot((15, 12))
    current["verified_at_utc"] = "2026-09-25T12:00:00+00:00"
    report = _report(tmp_path, current, accepted)
    assert report["status"] == "BLOCK"
    assert "verified_at_recent" in report["current_gate"]["missing"]
    assert report["rescore_required"] is False

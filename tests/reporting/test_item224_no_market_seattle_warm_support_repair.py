from weather.reporting.item224_no_market_seattle_warm_support_repair import (
    METADATA_DEFAULTS,
    apply_repair,
    repair_rule_for_group,
)


def _eq_row(bin_value, probability, *, market="seattle", regime="early", captured_at="2026-06-12T03:10:00-04:00"):
    return {
        "market_id": market,
        "target_date": "2026-06-12",
        "snapshot_id": f"{market}-{regime}-{captured_at}",
        "band_key": f"eq:{bin_value}.0-{bin_value + 1}.0",
        "bin_type": "eq",
        "bin_value": str(float(bin_value)),
        "probability": str(probability),
        "recorded_probability": str(probability),
        "current_probability": "0.1",
        "market_yes": "0.1",
        "outcome": "0",
        "cutoff_regime": regime,
        "captured_at_local": captured_at,
    }


def test_center70_weak_slot_uses_full_plus_two_shift():
    rows = [_eq_row(value, probability) for value, probability in [
        (62, 0.01),
        (64, 0.02),
        (66, 0.03),
        (68, 0.04),
        (70, 0.50),
        (72, 0.30),
        (74, 0.08),
        (76, 0.01),
        (78, 0.01),
    ]]

    rule = repair_rule_for_group(rows, {190})
    repaired, summary = apply_repair(rows, {190})
    by_value = {float(row["bin_value"]): float(row["probability"]) for row in repaired}

    assert rule["rule_id"] == "seattle_center70_weak_plus2_full"
    assert summary["changed_group_count"] == 1
    assert summary["changed_eq_row_count"] == 9
    assert by_value[74.0] == 0.5
    assert by_value[76.0] == 0.3
    assert {row["variant_id"] for row in repaired} == {METADATA_DEFAULTS["variant_id"]}
    assert {row["uses_market_features"] for row in repaired} == {"false"}


def test_non_seattle_rows_keep_probabilities_but_receive_candidate_metadata():
    rows = [_eq_row(value, 0.1, market="nyc") for value in range(62, 80, 2)]

    repaired, summary = apply_repair(rows, {190})

    assert summary["changed_group_count"] == 0
    assert [row["probability"] for row in repaired] == [row["probability"] for row in rows]
    assert {row["variant_family"] for row in repaired} == {METADATA_DEFAULTS["variant_family"]}

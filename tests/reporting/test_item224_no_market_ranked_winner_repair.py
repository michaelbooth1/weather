import csv
import json
from pathlib import Path

from weather.reporting.item224_no_market_ranked_winner_repair import (
    SCHEMA_VERSION,
    build_payload,
    render_report,
    write_json_report,
)


FIELDS = [
    "variant_id",
    "variant_family",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "market_yes",
    "outcome",
    "captured_at_local",
    "bin_type",
    "bin_value",
    "settlement_distance_bucket",
    "cutoff_regime",
    "source_freshness_state",
    "forecast_source_count_bucket",
    "forecast_disagreement_bucket",
    "forecast_bucket_pressure",
    "cutoff_hour",
]


def write_variant_rows(path: Path, variant_id: str, probabilities: dict[tuple[str, str, str, str], float]) -> None:
    rows = []
    for date in ("2026-06-07", "2026-06-08", "2026-06-12", "2026-06-13"):
        for market in ("seattle", "miami"):
            for snapshot_index in range(2):
                snapshot_id = f"{date}-{market}-{snapshot_index}"
                winning_band = "eq:70" if snapshot_index == 0 else "eq:72"
                for band_key, bin_value in (("eq:70", 70), ("eq:72", 72)):
                    key = (market, date, snapshot_id, band_key)
                    outcome = 1 if band_key == winning_band else 0
                    rows.append({
                        "variant_id": variant_id,
                        "variant_family": "synthetic_item224_repair",
                        "market_id": market,
                        "target_date": date,
                        "snapshot_id": snapshot_id,
                        "band_key": band_key,
                        "probability": str(probabilities[key]),
                        "current_probability": "0.62" if outcome else "0.38",
                        "market_yes": "0.68" if outcome else "0.32",
                        "outcome": str(outcome),
                        "captured_at_local": f"{date}T04:00:00-04:00",
                        "bin_type": "eq",
                        "bin_value": str(bin_value),
                        "settlement_distance_bucket": "0" if outcome else "1",
                        "cutoff_regime": "early" if snapshot_index == 0 else "midday",
                        "source_freshness_state": "fresh",
                        "forecast_source_count_bucket": "multi",
                        "forecast_disagreement_bucket": "low" if market == "miami" else "medium",
                        "forecast_bucket_pressure": "inside",
                        "cutoff_hour": "4" if snapshot_index == 0 else "12",
                    })
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def synthetic_probabilities(*, favor_winners: bool) -> dict[tuple[str, str, str, str], float]:
    probabilities = {}
    for date in ("2026-06-07", "2026-06-08", "2026-06-12", "2026-06-13"):
        for market in ("seattle", "miami"):
            for snapshot_index in range(2):
                snapshot_id = f"{date}-{market}-{snapshot_index}"
                winning_band = "eq:70" if snapshot_index == 0 else "eq:72"
                for band_key in ("eq:70", "eq:72"):
                    key = (market, date, snapshot_id, band_key)
                    is_winner = band_key == winning_band
                    if favor_winners:
                        probabilities[key] = 0.78 if is_winner else 0.22
                    else:
                        probabilities[key] = 0.55 if is_winner else 0.45
    return probabilities


def test_ranked_winner_repair_outputs_development_no_market_rows(tmp_path):
    current = tmp_path / "bottom_current_max_trust_variant_rows.csv"
    alpha = tmp_path / "bottom_item147_time_split_alpha_variant_rows.csv"
    rows_out = tmp_path / "ranked_rows.csv"
    json_out = tmp_path / "ranked.json"
    report_out = tmp_path / "ranked.md"
    write_variant_rows(current, "current_max_trust", synthetic_probabilities(favor_winners=False))
    write_variant_rows(alpha, "time_split_alpha", synthetic_probabilities(favor_winners=True))

    payload = build_payload(
        [current, alpha],
        rows_out=rows_out,
        train_dates=("2026-06-07", "2026-06-08"),
        eval_dates=("2026-06-12", "2026-06-13"),
    )
    json_path, report_path = write_json_report(payload, json_out, report_out)
    output_rows = list(csv.DictReader(rows_out.open("r", encoding="utf-8", newline="")))
    probabilities = [float(row["probability"]) for row in output_rows]
    report = render_report(payload)
    written_payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["evidence_classification"] == "development_time_split_no_market_diagnostic_not_promotion_evidence"
    assert set(payload["excluded_label_derived_features"]) == {"outcome", "market_yes", "settlement_distance_bucket"}
    assert payload["eval"]["rows"] > 0
    assert set(payload["by_eval_market"]) == {"miami", "seattle"}
    assert rows_out.exists()
    assert json_path.exists()
    assert report_path.exists()
    assert written_payload["schema_version"] == SCHEMA_VERSION
    assert all(0.0 < probability < 1.0 for probability in probabilities)
    assert {row["uses_market_features"] for row in output_rows} == {"false"}
    assert {row["counts_toward_weather_model_promotion"] for row in output_rows} == {"false"}
    assert {row["quote_risk_eligible"] for row in output_rows} == {"false"}
    assert {row["quote_risk_gate_reason"] for row in output_rows} == {
        "development_diagnostic_not_promotion_evidence",
    }
    assert "Item 224 No-Market Ranked Winner Repair" in report

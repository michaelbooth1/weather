import csv
import hashlib
import json
from pathlib import Path

import pytest

from weather.reporting.research.profit_edge_analysis import (
    build_profit_edge_analysis,
    choose_naive_taker_trade,
    render_report,
    summarize_trades,
    taker_fee_per_share,
    uncertainty_metrics,
    write_outputs,
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _partition(
    snapshot_id: str,
    captured_at_local: str,
    *,
    model=(0.10, 0.80, 0.10),
    market=(0.01, 0.98, 0.01),
    winner=1,
) -> list[dict]:
    return [
        {
            "variant_id": "frozen-candidate",
            "market_id": "alpha",
            "target_date": "2026-07-01",
            "snapshot_id": snapshot_id,
            "captured_at_local": captured_at_local,
            "band_key": band_key,
            "bin_type": bin_type,
            "bin_value": value,
            "probability": model_probability,
            "market_yes": market_probability,
            "outcome": int(index == winner),
        }
        for index, (
            band_key,
            bin_type,
            value,
            model_probability,
            market_probability,
        ) in enumerate(
            zip(
                ("lte:79.0", "eq:80.0-81.0", "gte:82.0"),
                ("lte", "eq", "gte"),
                ("79.0", "80.0", "82.0"),
                model,
                market,
            )
        )
    ]


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    rows = []
    rows.extend(_partition("s18a", "2026-07-01T18:01:00-04:00"))
    rows.extend(
        _partition(
            "s18b",
            "2026-07-01T18:31:00-04:00",
            model=(0.20, 0.60, 0.20),
            market=(0.10, 0.80, 0.10),
        )
    )
    rows.extend(
        _partition(
            "s20",
            "2026-07-01T20:01:00-04:00",
            model=(0.10, 0.70, 0.20),
            market=(0.05, 0.70, 0.25),
            winner=2,
        )
    )
    rows_path = tmp_path / "candidate.csv"
    _write_csv(rows_path, rows)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "market_id": "alpha",
                        "target_date": "2026-07-01",
                        "band_count": 3,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return rows_path, manifest_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_uncertainty_metrics_normalize_raw_market_mass_and_freeze_boundaries():
    near = uncertainty_metrics([0.01, 0.98, 0.02])
    low = uncertainty_metrics([0.81, 0.10, 0.09])
    moderate = uncertainty_metrics([0.60, 0.20, 0.20])
    high = uncertainty_metrics([0.34, 0.33, 0.33])

    assert near["raw_mass"] == pytest.approx(1.01)
    assert near["top_probability"] == pytest.approx(0.98 / 1.01)
    assert near["bucket"] == "near_resolved_top_ge_0.95"
    assert low["bucket"] == "low_top_0.80_to_0.95"
    assert moderate["bucket"] == "moderate_top_0.60_to_0.80"
    assert high["bucket"] == "high_top_lt_0.60"
    assert high["normalized_entropy"] > near["normalized_entropy"]


def test_naive_taker_trade_uses_complementary_no_price_and_symmetric_fee():
    rows = [
        {
            "band_key": "a",
            "model_probability": 0.10,
            "market_probability": 0.40,
            "outcome": 0,
        },
        {
            "band_key": "b",
            "model_probability": 0.90,
            "market_probability": 0.60,
            "outcome": 1,
        },
    ]

    chosen = choose_naive_taker_trade(rows)

    assert chosen is not None
    assert chosen["band_key"] == "a"
    assert chosen["side"] == "NO"
    assert chosen["contract_price"] == pytest.approx(0.60)
    assert chosen["taker_fee_per_share"] == pytest.approx(0.012)
    assert chosen["predicted_net_edge_per_share"] == pytest.approx(0.288)
    assert taker_fee_per_share(0.4) == pytest.approx(taker_fee_per_share(0.6))


def test_build_analysis_stratifies_all_rows_but_debursts_hourly_trades(tmp_path):
    rows_path, manifest_path = _fixture(tmp_path)

    payload = build_profit_edge_analysis(
        variant_rows=rows_path,
        corpus_manifest=manifest_path,
        variant_id="frozen-candidate",
        expected_variant_sha256=_sha256(rows_path),
        expected_manifest_sha256=_sha256(manifest_path),
        generated_at_utc="2026-07-26T00:00:00+00:00",
        code_identity="test",
    )
    report = render_report(payload)
    outputs = write_outputs(
        payload,
        json_out=tmp_path / "out" / "analysis.json",
        report_out=tmp_path / "out" / "analysis.md",
        trade_slices_out=tmp_path / "out" / "slices.csv",
    )

    assert payload["schema_version"] == "profit_edge_analysis_v0.1"
    assert payload["status"] == "PASS"
    assert payload["population"]["complete_partition_count"] == 3
    assert payload["population"]["scored_row_count"] == 9
    assert payload["population"]["target_day_hourly_representative_partition_count"] == 2
    assert payload["population"]["trade_count"] == 2
    assert sum(
        row["partition_population_weight"] for row in payload["uncertainty_brier"]
    ) == pytest.approx(1.0)
    buckets = {row["label"]: row for row in payload["uncertainty_brier"]}
    assert buckets["near_resolved_top_ge_0.95"]["partitions"] == 1
    assert buckets["low_top_0.80_to_0.95"]["partitions"] == 1
    assert buckets["moderate_top_0.60_to_0.80"]["partitions"] == 1
    assert payload["evening_18_23_naive_taker_liability"]["trades"] == 2
    ranked_totals = [
        row["total_taker_net_pnl_per_share_positions"]
        for row in payload["profit_ranking"]
        if row.get("total_taker_net_pnl_per_share_positions") is not None
    ]
    assert ranked_totals == sorted(ranked_totals, reverse=True)
    assert "favorable rebate sensitivity" in report
    assert all(path.exists() for path in outputs)


def test_hash_mismatch_fails_before_analysis(tmp_path):
    rows_path, manifest_path = _fixture(tmp_path)

    with pytest.raises(ValueError, match="frozen identity"):
        build_profit_edge_analysis(
            variant_rows=rows_path,
            corpus_manifest=manifest_path,
            expected_variant_sha256="0" * 64,
        )


def test_verified_same_second_collision_scores_both_copies_but_never_trades(tmp_path):
    rows = _partition(
        "collision",
        "2026-07-01T20:01:00.100000-04:00",
        model=(0.05, 0.40, 0.05),
    )
    rows += _partition(
        "collision",
        "2026-07-01T20:01:00.700000-04:00",
        model=(0.05, 0.40, 0.05),
    )
    rows_path = tmp_path / "collision.csv"
    _write_csv(rows_path, rows)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "market_id": "alpha",
                        "target_date": "2026-07-01",
                        "band_count": 3,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = build_profit_edge_analysis(
        variant_rows=rows_path,
        corpus_manifest=manifest_path,
        variant_id="frozen-candidate",
    )

    assert payload["population"]["complete_partition_count"] == 1
    assert payload["population"]["scored_row_count"] == 6
    assert payload["population"]["collision_partition_count"] == 1
    assert payload["population"]["collision_trade_partition_skips"] == 1
    assert payload["population"]["trade_count"] == 0
    assert payload["uncertainty_brier"][0]["label"] == "near_resolved_top_ge_0.95"
    assert payload["uncertainty_brier"][0]["partitions"] == 1


def test_exploitability_rule_uses_market_day_means_and_fixed_support():
    trades = []
    for day in range(30):
        for index in range(4):
            trades.append(
                {
                    "market_day": f"alpha|2026-07-{day + 1:02d}",
                    "market_id": "alpha",
                    "target_date": f"2026-07-{day + 1:02d}",
                    "side": "YES",
                    "contract_price": 0.5,
                    "predicted_gross_edge_per_share": 0.1,
                    "predicted_net_edge_per_share": 0.0875,
                    "taker_fee_per_share": 0.0125,
                    "gross_pnl_per_share": 0.1 + 0.001 * index,
                    "taker_net_pnl_per_share": 0.0875 + 0.001 * index,
                    "maker_rebate_sensitivity_per_share": 0.103125 + 0.001 * index,
                    "gross_pnl_per_dollar_notional": 0.2 + 0.002 * index,
                    "taker_net_pnl_per_dollar_notional": 0.175 + 0.002 * index,
                    "maker_rebate_sensitivity_per_dollar_notional": 0.20625
                    + 0.002 * index,
                }
            )

    summary = summarize_trades("candidate", trades)

    assert summary["trades"] == 120
    assert summary["market_days"] == 30
    assert summary["market_day_mean_taker_net_pnl_per_share_ci95_low"] > 0
    assert summary["positive_market_day_rate"] == 1.0
    assert summary["meets_exploitability_rule"] is True


def test_date_sensitivities_retain_equal_market_day_estimand():
    trades = []
    date_specs = (
        ("2026-07-01", 10, 0.1),
        ("2026-07-02", 5, -0.2),
        ("2026-07-03", 1, 0.5),
    )
    for target_date, market_days, pnl in date_specs:
        for index in range(market_days):
            trades.append(
                {
                    "market_day": f"market-{index}|{target_date}",
                    "market_id": f"market-{index}",
                    "target_date": target_date,
                    "side": "YES",
                    "contract_price": 0.5,
                    "predicted_gross_edge_per_share": 0.1,
                    "predicted_net_edge_per_share": 0.0875,
                    "taker_fee_per_share": 0.0125,
                    "gross_pnl_per_share": pnl + 0.0125,
                    "taker_net_pnl_per_share": pnl,
                    "maker_rebate_sensitivity_per_share": pnl + 0.015625,
                    "gross_pnl_per_dollar_notional": (pnl + 0.0125) / 0.5,
                    "taker_net_pnl_per_dollar_notional": pnl / 0.5,
                    "maker_rebate_sensitivity_per_dollar_notional": (
                        pnl + 0.015625
                    )
                    / 0.5,
                }
            )

    first = summarize_trades("date-block-test", trades)
    second = summarize_trades("date-block-test", trades)

    assert first["market_day_mean_taker_net_pnl_per_share"] == pytest.approx(
        0.5 / 16
    )
    assert first["leave_one_date_out_min_mean_taker_net_pnl_per_share"] == pytest.approx(
        -0.5 / 6
    )
    assert (
        first["date_block_bootstrap_mean_taker_net_pnl_per_share_ci95_low"]
        == second["date_block_bootstrap_mean_taker_net_pnl_per_share_ci95_low"]
    )

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.reporting.research import workstation_maker_research as maker


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_classify_run_separates_named_proof_and_rejects_quarantine(tmp_path):
    folder = tmp_path / "2026-06-23" / "item277-proof-3-20260623T2229Z"
    folder.mkdir(parents=True)
    (folder / "run_config.json").write_text(
        json.dumps({"mode": "paper-live-forward", "target_date": "2026-06-23"}),
        encoding="utf-8",
    )
    (folder / "run_summary.json").write_text(
        json.dumps({"run_id": "proof-3", "evidence_mode": "active_day_live_forward"}),
        encoding="utf-8",
    )
    _write_csv(
        folder / "quote_intents_long.csv",
        [{
            "target_date": "2026-06-23",
            "market_id": "toronto",
            "event_slug": "highest-temperature-in-toronto-on-june-23-2026",
            "quote_permission": "true",
            "bid_price": "0.4",
            "bid_size": "5",
            "ask_price": "0.6",
            "ask_size": "5",
        }],
    )
    result = maker.classify_run_folder(folder)
    assert result["run_class"] == "named_operator_proof"
    assert result["quote_legs"] == 2
    assert result["primary_pool_eligible"] is False

    quarantined = tmp_path / "_quarantine" / "run"
    quarantined.mkdir(parents=True)
    with pytest.raises(maker.MakerResearchError, match="quarantined"):
        maker.classify_run_folder(quarantined)


def test_ws_validation_excludes_price_change_and_blocks_unknown_type(tmp_path):
    folder = tmp_path / "highest-temperature-in-toronto-on-june-23-2026"
    rows = [
        {
            "event_type": "price_change",
            "event_slug": folder.name,
            "received_at_utc": "2026-06-23T12:00:00Z",
            "asset_id": "yes-token",
            "price": "0.39",
            "size": "999",
            "side": "SELL",
        },
        {
            "event_type": "last_trade_price",
            "event_slug": folder.name,
            "received_at_utc": "2026-06-23T12:01:00Z",
            "asset_id": "yes-token",
            "price": "0.38",
            "size": "2",
            "side": "SELL",
        },
    ]
    _write_csv(folder / "market_ws_events.csv", rows)
    diagnostics, trades = maker.read_validated_ws_events(folder)
    assert diagnostics["event_type_contract_status"] == "PASS"
    assert diagnostics["event_types"] == {"last_trade_price": 1, "price_change": 1}
    assert len(trades) == 1
    assert trades[0]["price"] == 0.38

    rows.append({**rows[0], "event_type": "mystery_event"})
    _write_csv(folder / "market_ws_events.csv", rows)
    diagnostics, trades = maker.read_validated_ws_events(folder)
    assert diagnostics["event_type_contract_status"] == "BLOCK"
    assert diagnostics["unknown_ws_event_rows"] == 1
    assert len(trades) == 1


def test_reconstruction_uses_strict_last_trade_through_and_computes_markouts(
    tmp_path, monkeypatch
):
    folder = tmp_path / "highest-temperature-in-toronto-on-june-23-2026"
    trade_time = datetime(2026, 6, 23, 12, 1, tzinfo=timezone.utc)
    _write_csv(
        folder / "market_ws_events.csv",
        [
            {
                "event_type": "price_change",
                "event_slug": folder.name,
                "received_at_utc": "2026-06-23T12:00:30Z",
                "asset_id": "yes-token",
                "price": "0.10",
                "size": "500",
                "side": "SELL",
            },
            {
                "event_type": "last_trade_price",
                "event_slug": folder.name,
                "received_at_utc": trade_time.isoformat(),
                "asset_id": "yes-token",
                "price": "0.39",
                "size": "2",
                "side": "SELL",
            },
        ],
    )

    def book(at, bid, ask):
        return {
            "_captured_at": at,
            "clob_token_id": "yes-token",
            "best_bid": bid,
            "best_ask": ask,
            "midpoint": (bid + ask) / 2,
            "spread": ask - bid,
            "tick_size": 0.01,
            "bid_size_at_best": 10,
            "ask_size_at_best": 12,
            "bid_depth_1pct": 10,
            "ask_depth_1pct": 12,
            "bid_depth_all": 20,
            "ask_depth_all": 25,
        }

    books = [
        book(trade_time - timedelta(seconds=30), 0.40, 0.42),
        book(trade_time + timedelta(minutes=1), 0.41, 0.43),
        book(trade_time + timedelta(minutes=5), 0.42, 0.44),
        book(trade_time + timedelta(minutes=30), 0.43, 0.45),
    ]
    monkeypatch.setattr(maker, "load_book_rows", lambda _folders: list(books))
    market_day, diagnostics, marks, fills = maker.reconstruct_market_day(
        {
            "folder": str(folder),
            "event_slug": folder.name,
            "target_date": "2026-06-23",
            "market_id": "toronto",
        },
        tune_end="2026-07-01",
    )
    assert diagnostics["last_trade_price_rows"] == 1
    assert market_day["book_matched_trade_rows"] == 1
    assert marks[0]["markout_30m_per_share"] == pytest.approx(0.05)
    assert {row["policy_id"] for row in fills} == {"at_touch", "one_tick_inside"}
    assert all(row["through_trade_size"] == 2.0 for row in fills)
    assert all(row["evidence_source"] == "synthetic_periodic_book_quote" for row in fills)


def _policy_day(date, market, policy, net, fills):
    return {
        "target_date": date,
        "market_id": market,
        "split": "tune",
        "policy_id": policy,
        "net_after_modeled_costs_30m_usdc": net,
        "markout_30m_complete_fill_count": fills,
    }


def test_paired_inference_is_deterministic_and_clusters_whole_fleet_dates():
    rows = [
        _policy_day("2026-06-21", "a", "at_touch", 0.0, 4),
        _policy_day("2026-06-21", "a", "variant", 1.0, 4),
        _policy_day("2026-06-21", "b", "at_touch", 0.0, 4),
        _policy_day("2026-06-21", "b", "variant", 1.0, 4),
        _policy_day("2026-06-22", "a", "at_touch", 0.0, 4),
        _policy_day("2026-06-22", "a", "variant", -1.0, 4),
        _policy_day("2026-06-23", "a", "at_touch", 0.0, 4),
        _policy_day("2026-06-23", "a", "variant", 0.0, 4),
    ]
    first = maker.paired_policy_comparison(
        rows,
        split="tune",
        variant_policy_id="variant",
        seed=7,
        replicates=500,
    )
    second = maker.paired_policy_comparison(
        rows,
        split="tune",
        variant_policy_id="variant",
        seed=7,
        replicates=500,
    )
    assert first == second
    assert first["equal_market_day_delta"]["mean"] == pytest.approx(0.25)
    assert first["fleet_date_cluster_delta"]["mean"] == pytest.approx(1 / 3)
    assert first["fleet_date_cluster_delta"]["positive_count"] == 1
    assert first["fleet_date_cluster_delta"]["negative_count"] == 1
    assert first["fleet_date_cluster_delta"]["tie_count"] == 1
    assert first["support_status"] == "SUPPORTED"


def test_quote_runs_without_validated_ws_are_labeled_and_not_loaded(monkeypatch):
    monkeypatch.setattr(
        maker,
        "load_quote_rows",
        lambda _folders: (_ for _ in ()).throw(AssertionError("must not load")),
    )
    manifest = {
        "snapshot_folders": [],
        "run_folders": [
            {
                "run_class": "operator_drill",
                "run_folder": "C:/approved/run",
                "run_id": "run",
                "target_date": "2026-06-19",
                "event_slugs": ["highest-temperature-in-toronto-on-june-19-2026"],
                "quote_rows": 1,
                "quote_permission_rows": 1,
                "quote_legs": 1,
                "quote_market_days": [
                    {
                        "target_date": "2026-06-19",
                        "market_id": "toronto",
                        "event_slug": "highest-temperature-in-toronto-on-june-19-2026",
                        "quote_rows": 1,
                        "quote_permission_rows": 1,
                        "quote_legs": 1,
                    }
                ],
            }
        ],
    }
    fills, days, diagnostics = maker.score_quote_runs(manifest)
    assert fills == []
    assert days[0]["coverage_status"] == "no_valid_ws_trade_tape"
    assert diagnostics[0]["coverage_status"] == "no_valid_ws_trade_tape"
    summary = maker.summarize_quote_run_classes(
        days, diagnostics, tune_end="2026-07-01"
    )
    assert summary["classes"][0]["quote_legs"] == 1
    assert summary["classes"][0]["conservative_fill_count"] == 0
    assert summary["primary_quote_policy_holdout_gate"]["status"] == "BLOCK"


def test_output_root_fails_closed_under_data(tmp_path):
    data_root = tmp_path / "immutable-evidence"
    data_root.mkdir()
    forbidden = data_root / "maker-results"
    with pytest.raises(maker.MakerResearchError, match="read-only root"):
        maker._safe_output_root(forbidden, read_only_data_root=data_root)
    assert not forbidden.exists()


def test_complete_fleet_calendar_requires_twelve_markets_on_every_date():
    market_ids = sorted(maker.EXPECTED_FLEET_MARKET_IDS)
    rows = [
        {"target_date": target_date, "market_id": market_id}
        for target_date in ("2026-06-21", "2026-06-22")
        for market_id in market_ids
    ]
    assert maker._complete_fleet_calendar(rows, "2026-06-21", "2026-06-22")
    assert not maker._complete_fleet_calendar(rows[:-1], "2026-06-21", "2026-06-22")
    duplicate_market = [dict(row) for row in rows]
    duplicate_market[-1]["market_id"] = market_ids[0]
    assert not maker._complete_fleet_calendar(
        duplicate_market, "2026-06-21", "2026-06-22"
    )
    wrong_date = [dict(row) for row in rows]
    wrong_date[-1]["target_date"] = "2026-06-23"
    assert not maker._complete_fleet_calendar(
        wrong_date, "2026-06-21", "2026-06-22"
    )


def test_policy_net_reconciles_to_complete_case_markout_and_flattening_cost():
    manifest = {
        "snapshot_folders": [{
            "target_date": "2026-06-21",
            "market_id": "toronto",
            "event_slug": "event",
        }]
    }
    common = {
        "target_date": "2026-06-21",
        "market_id": "toronto",
        "policy_id": "at_touch",
        "fill_size": 5.0,
        "gross_spread_capture_usdc": 0.1,
        "theoretical_maker_rebate_usdc": 0.02,
    }
    fills = [
        {
            **common,
            "markout_30m_per_share": 0.4,
            "markout_30m_usdc": 2.0,
            "modeled_flattening_cost_usdc": 0.5,
            "net_after_modeled_costs_30m_usdc": 1.5,
            "net_with_theoretical_rebate_30m_usdc": 1.52,
        },
        {
            **common,
            "markout_30m_per_share": None,
            "markout_30m_usdc": None,
            "modeled_flattening_cost_usdc": 0.7,
            "net_after_modeled_costs_30m_usdc": None,
            "net_with_theoretical_rebate_30m_usdc": None,
        },
    ]
    rows = maker.summarize_policy_market_days(
        manifest, fills, tune_end="2026-07-01"
    )
    row = next(item for item in rows if item["policy_id"] == "at_touch")
    assert row["modeled_flattening_cost_usdc"] == pytest.approx(1.2)
    assert row["modeled_flattening_cost_30m_complete_usdc"] == pytest.approx(0.5)
    assert row["net_after_modeled_costs_30m_usdc"] == pytest.approx(
        row["markout_30m_usdc"]
        - row["modeled_flattening_cost_30m_complete_usdc"]
    )

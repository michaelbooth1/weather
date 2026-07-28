import csv
import json
from datetime import datetime, timedelta, timezone

import pytest

from weather.market.mm_paper_scoring import (
    load_mark_rows,
    load_trade_rows,
    rows_between,
    simulate_conservative_fills,
    strict_trade_through,
)


EVENT = "highest-temperature-in-atlanta-on-june-14-2026"


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_load_trade_rows_rejects_price_change_with_trade_shape(tmp_path):
    folder = tmp_path / EVENT
    _write_csv(
        folder / "market_ws_events.csv",
        [
            {
                "event_type": "price_change",
                "received_at_utc": "2026-06-14T16:00:11+00:00",
                "timestamp_utc": "2026-06-14T16:00:10+00:00",
                "asset_id": "token-80",
                "price": "0.48",
                "size": "3",
                "side": "SELL",
                "transaction_hash": "0xnot-a-trade",
            }
        ],
    )
    rows, diagnostics = load_trade_rows(folder)

    assert rows == []
    assert diagnostics["trade_rows"] == 0
    assert diagnostics["rejected_non_execution_rows"] == 1


def test_load_trade_rows_deduplicates_raw_and_csv_and_uses_exchange_time(tmp_path):
    folder = tmp_path / EVENT
    exchange_timestamp_ms = 1_781_452_810_000
    exchange_time = datetime.fromtimestamp(
        exchange_timestamp_ms / 1000,
        timezone.utc,
    )
    received_time = exchange_time + timedelta(seconds=2)
    raw_sha1 = "a" * 40
    _write_jsonl(
        folder / "market_ws.jsonl",
        [
            {
                "received_at_utc": received_time.isoformat(),
                "event_slug": EVENT,
                "raw_sha1": raw_sha1,
                "payload": {
                    "event_type": "last_trade_price",
                    "market": "condition-80",
                    "asset_id": "token-80",
                    "price": "0.4800",
                    "size": "3.000",
                    "side": "SELL",
                    "timestamp": str(exchange_timestamp_ms),
                    "transaction_hash": "0xABC",
                },
            }
        ],
    )
    _write_csv(
        folder / "market_ws_events.csv",
        [
            {
                "received_at_utc": received_time.isoformat(),
                "event_slug": EVENT,
                "event_type": "last_trade_price",
                "asset_id": "token-80",
                "market": "condition-80",
                "price": "0.48",
                "size": "3",
                "side": "SELL",
                "raw_sha1": raw_sha1,
            }
        ],
    )
    _write_csv(
        folder / "market_trades.csv",
        [
            {
                "transactionHash": "0xABC",
                "asset": "token-80",
                "conditionId": "condition-80",
                "price": "0.48",
                "size": "3",
                "side": "SELL",
                "timestamp": str(exchange_timestamp_ms // 1000),
                "fetched_at_utc": (received_time + timedelta(seconds=5)).isoformat(),
            }
        ],
    )

    rows, diagnostics = load_trade_rows(folder)

    assert len(rows) == 1
    trade = rows[0]
    assert trade["time"] == exchange_time
    assert trade["received_time"] == received_time
    assert trade["transaction_hash"] == "0xabc"
    assert trade["condition_id"] == "condition-80"
    assert trade["source_representations"] == (
        "market_trades.csv;market_ws.jsonl;market_ws_events.csv"
    )
    assert diagnostics["duplicate_representation_rows"] == 2
    assert diagnostics["accepted_unique_execution_rows"] == 1

    quote_after_exchange = exchange_time + timedelta(seconds=1)
    assert rows_between(
        rows,
        quote_after_exchange,
        quote_after_exchange + timedelta(seconds=60),
    ) == []


def test_load_trade_rows_parses_data_api_epoch_seconds(tmp_path):
    folder = tmp_path / EVENT
    exchange_timestamp = 1_781_452_810
    _write_csv(
        folder / "market_trades.csv",
        [
            {
                "canonical_execution_id": "data-api-canonical-execution",
                "exchange_timestamp": str(exchange_timestamp),
                "exchange_time_utc": "",
                "timestamp_precision": "epoch_second",
                "transaction_hash": "0xDataApi",
                "asset": "token-80",
                "condition_id": "condition-80",
                "price": "0.48",
                "size": "7",
                "side": "SELL",
                "fetched_at_utc": "2026-06-15T00:00:00+00:00",
            }
        ],
    )

    rows, diagnostics = load_trade_rows(folder)

    assert len(rows) == 1
    assert rows[0]["time"] == datetime.fromtimestamp(
        exchange_timestamp,
        timezone.utc,
    )
    assert rows[0]["exchange_time_precision_seconds"] == 1.0
    assert rows[0]["canonical_execution_id"].startswith("execution_")
    assert (
        rows[0]["supplied_canonical_execution_id"]
        == "data-api-canonical-execution"
    )
    assert rows[0]["clob_token_id"] == "token-80"
    assert rows[0]["condition_id"] == "condition-80"
    assert diagnostics["accepted_unique_execution_rows"] == 1


def test_strict_trade_through_requires_matching_taker_side():
    assert strict_trade_through("YES_BID", 0.48, 0.49, "SELL")
    assert not strict_trade_through("YES_BID", 0.48, 0.49, "BUY")
    assert not strict_trade_through("YES_BID", 0.48, 0.49, "")
    assert strict_trade_through("YES_ASK", 0.52, 0.51, "BUY")
    assert not strict_trade_through("YES_ASK", 0.52, 0.51, "SELL")


def test_load_trade_rows_keeps_same_transaction_distinct_full_fingerprints(tmp_path):
    folder = tmp_path / EVENT
    common = {
        "trade_time_utc": "2026-06-14T16:00:10+00:00",
        "clob_token_id": "token-80",
        "condition_id": "condition-80",
        "price": "0.48",
        "side": "SELL",
    }
    _write_csv(
        folder / "trades_long.csv",
        [
            {**common, "size": "3"},
            {**common, "size": "3", "transaction_hash": "0xconflict"},
            {**common, "size": "4", "transaction_hash": "0xconflict"},
            {
                **common,
                "size": "3",
                "transaction_hash": "0xidentity-conflict",
                "canonical_execution_id": "canonical-a",
            },
            {
                **common,
                "size": "3",
                "transaction_hash": "0xidentity-conflict",
                "canonical_execution_id": "canonical-b",
            },
        ],
    )

    rows, diagnostics = load_trade_rows(folder)

    assert len(rows) == 2
    assert {row["size"] for row in rows} == {3.0, 4.0}
    assert diagnostics["rejected_missing_identity_rows"] == 1
    assert diagnostics["transaction_alias_collision_rows"] == 1
    assert diagnostics["conflicting_representation_rows"] == 1
    assert diagnostics["conflicting_execution_ids"] == 1


def test_load_trade_rows_deduplicates_across_partial_native_aliases(tmp_path):
    folder = tmp_path / EVENT
    common = {
        "native_execution_id": "native-trade-123",
        "trade_time_utc": "2026-06-14T16:00:10+00:00",
        "clob_token_id": "token-80",
        "condition_id": "condition-80",
        "price": "0.48",
        "size": "3",
        "side": "SELL",
    }
    _write_csv(
        folder / "trades_long.csv",
        [
            {**common, "transaction_hash": "0xbridge"},
            common,
        ],
    )

    rows, diagnostics = load_trade_rows(folder)

    assert len(rows) == 1
    assert rows[0]["native_execution_id"] == "native-trade-123"
    assert rows[0]["transaction_hash"] == "0xbridge"
    assert diagnostics["duplicate_representation_rows"] == 1


def test_load_trade_rows_accepts_current_nested_ws_trade_wrapper(tmp_path):
    folder = tmp_path / EVENT
    timestamp_ms = 1_781_452_810_123
    _write_jsonl(
        folder / "market_ws.jsonl",
        [
            {
                "received_at_utc": "2026-06-14T16:00:11+00:00",
                "raw_sha1": "b" * 40,
                "payload": {
                    "type": "last_trade_price",
                    "payload": {
                        "market": "condition-80",
                        "tokenId": "token-80",
                        "price": "0.52",
                        "size": "2",
                        "side": "BUY",
                        "timestamp": str(timestamp_ms),
                        "transactionHash": "0xNested",
                    },
                },
            }
        ],
    )

    rows, diagnostics = load_trade_rows(folder)

    assert len(rows) == 1
    assert rows[0]["time"] == datetime.fromtimestamp(
        timestamp_ms / 1000,
        timezone.utc,
    )
    assert rows[0]["side"] == "BUY"
    assert rows[0]["transaction_hash"] == "0xnested"
    assert diagnostics["rejected_non_execution_rows"] == 0


def test_load_trade_rows_rejects_conflicting_normalized_raw_link(tmp_path):
    folder = tmp_path / EVENT
    timestamp_ms = 1_781_452_810_000
    raw_sha1 = "c" * 40
    _write_jsonl(
        folder / "market_ws.jsonl",
        [
            {
                "received_at_utc": "2026-06-14T16:00:11+00:00",
                "raw_sha1": raw_sha1,
                "payload": {
                    "event_type": "last_trade_price",
                    "market": "condition-80",
                    "asset_id": "token-80",
                    "price": "0.48",
                    "size": "3",
                    "side": "SELL",
                    "timestamp": str(timestamp_ms),
                    "transaction_hash": "0xraw",
                },
            }
        ],
    )
    _write_csv(
        folder / "market_ws_events.csv",
        [
            {
                "event_type": "last_trade_price",
                "received_at_utc": "2026-06-14T16:00:11+00:00",
                "asset_id": "token-80",
                "market": "wrong-condition",
                "price": "0.48",
                "size": "3",
                "side": "SELL",
                "raw_sha1": raw_sha1,
            }
        ],
    )

    rows, diagnostics = load_trade_rows(folder)

    assert len(rows) == 1
    assert rows[0]["condition_id"] == "condition-80"
    assert diagnostics["rejected_conflicting_raw_link_rows"] == 1


def test_load_trade_rows_fails_closed_on_bad_condition_side_and_clock(tmp_path):
    folder = tmp_path / EVENT
    common = {
        "exchange_timestamp": "1781452810",
        "asset": "token-80",
        "price": "0.48",
        "size": "3",
    }
    _write_csv(
        folder / "market_trades.csv",
        [
            {
                **common,
                "transaction_hash": "0xmissingcondition",
                "side": "SELL",
            },
            {
                **common,
                "transaction_hash": "0xbadside",
                "condition_id": "condition-80",
                "side": "BID",
            },
            {
                **common,
                "transaction_hash": "0xbadclock",
                "condition_id": "condition-80",
                "side": "SELL",
                "fetched_at_utc": "2026-06-14T15:59:00+00:00",
            },
        ],
    )

    rows, diagnostics = load_trade_rows(folder)

    assert rows == []
    assert diagnostics["rejected_missing_condition_rows"] == 1
    assert diagnostics["rejected_invalid_side_rows"] == 1
    assert diagnostics["rejected_negative_latency_rows"] == 1


def test_load_mark_rows_rejects_price_change_levels(tmp_path):
    folder = tmp_path / EVENT
    _write_csv(
        folder / "market_ws_events.csv",
        [
            {
                "event_type": "price_change",
                "received_at_utc": "2026-06-14T16:00:11+00:00",
                "timestamp_utc": "2026-06-14T16:00:10+00:00",
                "asset_id": "token-80",
                "price": "0.48",
                "size": "100",
                "side": "BUY",
            }
        ],
    )

    assert load_mark_rows(folder) == []


@pytest.mark.parametrize(
    ("side", "trade_side"),
    [
        ("YES_BID", "BUY"),
        ("YES_ASK", "SELL"),
    ],
)
def test_wrong_side_execution_cannot_fill(side, trade_side):
    quote_price = 0.49 if side == "YES_BID" else 0.51
    trade_price = 0.48 if side == "YES_BID" else 0.52
    assert not strict_trade_through(
        side,
        trade_price,
        quote_price,
        trade_side,
    )


def test_materialized_fill_loop_rejects_wrong_side_execution(tmp_path):
    folder = tmp_path / EVENT
    _write_csv(
        folder / "trades_long.csv",
        [
            {
                "native_execution_id": "wrong-side-execution",
                "trade_time_utc": "2026-06-14T16:00:10+00:00",
                "clob_token_id": "token-80",
                "condition_id": "condition-80",
                "price": "0.48",
                "size": "3",
                "side": "BUY",
            }
        ],
    )
    quote_time = datetime(2026, 6, 14, 16, 0, tzinfo=timezone.utc)
    legs = [
        {
            "leg_id": "leg-wrong-side",
            "event_slug": EVENT,
            "clob_token_id": "token-80",
            "side": "YES_BID",
            "quote_price": 0.49,
            "quote_size": 3.0,
            "quote_time": quote_time,
            "quote_expires_at": quote_time + timedelta(seconds=60),
        }
    ]

    fills, _queues, diagnostics, _folders = simulate_conservative_fills(
        legs,
        tmp_path,
        {},
        {},
    )

    assert fills == []
    assert diagnostics[EVENT]["trade_rows"] == 1

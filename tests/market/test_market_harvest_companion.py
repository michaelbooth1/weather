import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from weather.market import market_harvest_companion


TARGET_DATE = "2026-06-14"
EVENT = "highest-temperature-in-atlanta-on-june-14-2026"


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["empty"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _jsonl_rows(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line
    ]


def write_score_fixture(
    root,
    *,
    trades,
    quote_token="token-80",
    book_token="token-80",
    settlement_overrides=None,
):
    runs_root = root / "mm_runs"
    run_folder = runs_root / TARGET_DATE / "paper-run" / "market_harvest_companion"
    run_folder.mkdir(parents=True)
    binding = {
        "book_capture_ids": ["book-1"],
        "book_captured_at_utc": ["2026-06-14T15:59:50+00:00"],
        "book_rows_sha256": "a" * 64,
        "token_rows_sha256": "b" * 64,
        "source_status_rows_sha256": "c" * 64,
        "source_hashes_sha256": "d" * 64,
    }
    run_config = {
        "schema_version": "mm_run_v0.2",
        "companion_schema_version": market_harvest_companion.SCHEMA_VERSION,
        "run_id": "paper-run--market-harvest",
        "parent_run_id": "paper-run",
        "mode": "paper-live-forward",
        "target_date": TARGET_DATE,
        "policy_hash": "harvest-policy",
        "permission_profile": "market_harvest",
        "platform_id": "polymarket_global",
        "evidence_mode": market_harvest_companion.EVIDENCE_MODE,
        "input_bindings_by_market": {"atlanta": binding},
        "live_trade_permission_allowed": False,
        "authenticated_execution_evidence": False,
        "realized_pnl_eligible": False,
        "policy_config": {"quote_ttl_seconds": 120.0},
    }
    (run_folder / "run_config.json").write_text(json.dumps(run_config), encoding="utf-8")
    summary = {
        **run_config,
        "counts_toward_live_forward_gate": False,
        "evidence_mode": market_harvest_companion.EVIDENCE_MODE,
    }
    (run_folder / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    quote = {
        "run_id": "paper-run--market-harvest",
        "target_date": TARGET_DATE,
        "run_mode": "paper-live-forward",
        "generated_at_utc": "2026-06-14T16:00:00+00:00",
        "captured_at_utc": "2026-06-14T15:59:50+00:00",
        "policy_hash": "harvest-policy",
        "quote_permission": "True",
        "live_trade_permission": "False",
        "market_id": "atlanta",
        "event_slug": EVENT,
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": "80",
        "bin_value_hi": "81",
        "clob_token_id": quote_token,
        "condition_id": "condition-80",
        "market_mid": "0.50",
        "bid_price": "0.49",
        "bid_size": "5",
        "ask_price": "0.51",
        "ask_size": "5",
        "regime": "market_harvest",
        "source_fresh": "True",
        "source_freshness_state": "fresh",
        "model_variant_id": "market_harvest_v0",
        "model_variant_family": "market_harvest",
        "model_variant_role": "paper_permission_profile",
        "model_variant_counterfactual": "True",
        "reason_code": "QUOTE_MARKET_HARVEST_MID",
        "evidence_class": "quote_opportunity",
        "evidence_surface": "public_market_data_counterfactual",
        "platform_id": "polymarket_global",
        "parent_run_id": "paper-run",
        "companion_schema_version": market_harvest_companion.SCHEMA_VERSION,
        "companion_tick_id": "e" * 64,
        "companion_row_id": "f" * 64,
        "book_capture_ids": "book-1",
        "book_captured_at_utc": "2026-06-14T15:59:50+00:00",
        "book_rows_sha256": "a" * 64,
        "token_rows_sha256": "b" * 64,
        "source_status_rows_sha256": "c" * 64,
        "source_hashes_sha256": "d" * 64,
        "authenticated_fill": "False",
        "realized_pnl_eligible": "False",
    }
    write_csv(run_folder / "quote_intents_long.csv", [quote])
    write_csv(run_folder / "model_variant_quote_intents_long.csv", [])

    snapshots_root = root / "snapshots"
    snapshot_folder = snapshots_root / EVENT
    snapshot_folder.mkdir(parents=True)
    if trades:
        write_csv(snapshot_folder / "trades_long.csv", trades)
    books = [
        {
            "captured_at_utc": "2026-06-14T15:59:50+00:00",
            "event_slug": EVENT,
            "market_id": "atlanta",
            "range_label": "80-81 F",
            "clob_token_id": book_token,
            "best_bid": "0.49",
            "best_ask": "0.51",
            "midpoint": "0.50",
            "bid_size_at_best": "10",
            "ask_size_at_best": "10",
            "bid_depth_1pct": "10",
            "ask_depth_1pct": "10",
            "tick_size": "0.001",
        },
        {
            "captured_at_utc": "2026-06-14T16:02:01+00:00",
            "event_slug": EVENT,
            "market_id": "atlanta",
            "range_label": "80-81 F",
            "clob_token_id": book_token,
            "best_bid": "0.48",
            "best_ask": "0.51",
            "midpoint": "0.495",
            "bid_size_at_best": "5",
            "ask_size_at_best": "10",
            "bid_depth_1pct": "5",
            "ask_depth_1pct": "10",
            "tick_size": "0.001",
        },
    ]
    write_csv(snapshot_folder / "order_books_summary.csv", books)
    write_csv(snapshot_folder / "price_history.csv", [{
        "point_time_utc": "2026-06-14T16:30:30+00:00",
        "clob_token_id": book_token,
        "price": "0.54",
    }])
    settlement = {
        "event_slug": EVENT,
        "market_id": "atlanta",
        "target_date": TARGET_DATE,
        "settlement_bucket": 80,
        "settlement_unit": "F",
        "winning_band": "80-81 F",
        "quality_grade": "complete",
        "promotion_countable": True,
    }
    settlement.update(settlement_overrides or {})
    (snapshot_folder / "settlement.json").write_text(
        json.dumps(settlement),
        encoding="utf-8",
    )
    return runs_root, snapshots_root, run_folder


def trade(price, size, trade_id, *, condition_id="condition-80"):
    return {
        "execution_id": trade_id,
        "trade_time_utc": "2026-06-14T16:00:20+00:00",
        "received_at_utc": "2026-06-14T16:00:21+00:00",
        "transaction_hash": f"0x{trade_id}",
        "raw_sha1": (trade_id[-1:] or "1") * 40,
        "clob_token_id": "token-80",
        "condition_id": condition_id,
        "price": str(price),
        "size": str(size),
        "side": "SELL",
    }


def score(root, runs_root, snapshots_root, run_folder):
    return market_harvest_companion.score_runs(
        runs_root,
        snapshots_root,
        root / "backtest",
        selected_run_folders=[run_folder],
        now="2026-06-14T18:00:00+00:00",
        exchange_economics_required=False,
    )


def test_strict_companion_scoring_caps_fill_and_never_claims_auth_or_realized_pnl(tmp_path):
    touch = trade("0.49", "10", "touch1")
    through = trade("0.48", "3", "through2")
    runs_root, snapshots_root, run_folder = write_score_fixture(
        tmp_path,
        trades=[touch, through],
    )

    receipt = score(tmp_path, runs_root, snapshots_root, run_folder)
    report = json.loads(Path(receipt["report_path"]).read_text(encoding="utf-8"))
    fills = read_csv(receipt["fills_path"])
    queue = read_csv(receipt["queue_path"])

    assert receipt["status"] == "PASS"
    assert report["summary"]["opportunities"] == 1
    assert report["summary"]["simulated_posted_legs"] == 2
    assert report["summary"]["conservative_fills"] == 1
    assert report["summary"]["public_counterfactual_countable_market_days"] == 1
    assert report["summary"]["authenticated_account_countable_market_days"] == 0
    assert report["summary"]["authenticated_fill_count"] == 0
    assert report["summary"]["realized_pnl_count"] == 0
    assert len(fills) == 1
    assert fills[0]["native_execution_id"] == "through2"
    assert float(fills[0]["fill_size"]) == 3.0
    assert fills[0]["conservative_fill_rule"] == "strict_trade_through_price_and_recorded_size"
    assert fills[0]["evidence_class"] == "simulated_fill"
    assert fills[0]["public_execution_evidence_class"] == "public_trade"
    assert fills[0]["authenticated_fill"] == "False"
    assert fills[0]["realized_pnl_eligible"] == "False"
    assert float(fills[0]["realized_pnl_usdc"]) == 0.0
    assert float(fills[0]["authoritative_fee_usdc"]) == 0.0
    assert float(fills[0]["authoritative_rebate_usdc"]) == 0.0
    assert float(fills[0]["authoritative_incentive_usdc"]) == 0.0
    assert float(fills[0]["settlement_outcome"]) == 1.0
    assert queue
    assert {row["evidence_class"] for row in queue} == {"simulated_queue"}
    assert {row["authenticated_fill"] for row in queue} == {"False"}


def test_touch_only_and_missing_size_never_become_strict_companion_fills(tmp_path):
    touch_root = tmp_path / "touch"
    runs_root, snapshots_root, run_folder = write_score_fixture(
        touch_root,
        trades=[trade("0.49", "10", "touch1")],
    )
    touch_receipt = score(touch_root, runs_root, snapshots_root, run_folder)
    assert read_csv(touch_receipt["fills_path"]) == []

    missing_root = tmp_path / "missing-size"
    missing = trade("0.48", "", "missing1")
    runs_root, snapshots_root, run_folder = write_score_fixture(
        missing_root,
        trades=[missing],
    )
    missing_receipt = score(missing_root, runs_root, snapshots_root, run_folder)
    missing_report = json.loads(Path(missing_receipt["report_path"]).read_text(encoding="utf-8"))
    assert missing_receipt["status"] == "BLOCK"
    assert read_csv(missing_receipt["fills_path"]) == []
    assert "missing_size_trade_rows" in missing_report["summary"]["fill_evidence_blockers"]
    assert missing_report["summary"]["public_counterfactual_countable_market_days"] == 0


def test_token_mismatch_blocks_companion_countability(tmp_path):
    runs_root, snapshots_root, run_folder = write_score_fixture(
        tmp_path,
        trades=[trade("0.48", "3", "through2")],
        quote_token="different-token",
    )
    receipt = score(tmp_path, runs_root, snapshots_root, run_folder)
    report = json.loads(Path(receipt["report_path"]).read_text(encoding="utf-8"))

    assert receipt["status"] == "BLOCK"
    assert read_csv(receipt["fills_path"]) == []
    assert report["summary"]["public_counterfactual_countable_market_days"] == 0
    assert "missing_book_queue_legs" in report["summary"]["fill_evidence_blockers"]


def test_condition_mismatch_blocks_companion_countability(tmp_path):
    runs_root, snapshots_root, run_folder = write_score_fixture(
        tmp_path,
        trades=[
            trade(
                "0.48",
                "3",
                "through2",
                condition_id="different-condition",
            )
        ],
    )
    receipt = score(tmp_path, runs_root, snapshots_root, run_folder)
    report = json.loads(Path(receipt["report_path"]).read_text(encoding="utf-8"))

    assert receipt["status"] == "BLOCK"
    assert read_csv(receipt["fills_path"]) == []
    assert report["summary"]["public_counterfactual_countable_market_days"] == 0
    assert "execution_condition_mismatch" in report["summary"]["fill_evidence_blockers"]
    assert report["execution_identity_gate"]["status"] == "BLOCK"


@pytest.mark.parametrize(
    "settlement_overrides, blocker",
    [
        ({"promotion_countable": False}, "settlement_not_promotion_countable"),
        ({"settlement_unit": "C"}, "settlement_unit_mismatch"),
        ({"target_date": "2026-06-13"}, "settlement_target_date_mismatch"),
    ],
)
def test_incomplete_or_mismatched_settlement_is_never_countable(
    tmp_path,
    settlement_overrides,
    blocker,
):
    runs_root, snapshots_root, run_folder = write_score_fixture(
        tmp_path,
        trades=[trade("0.48", "3", "through2")],
        settlement_overrides=settlement_overrides,
    )

    receipt = score(tmp_path, runs_root, snapshots_root, run_folder)
    report = json.loads(Path(receipt["report_path"]).read_text(encoding="utf-8"))

    assert receipt["status"] == "BLOCK"
    assert report["summary"]["public_counterfactual_countable_market_days"] == 0
    assert report["settlement_countability_gate"]["status"] == "BLOCK"
    assert blocker in report["settlement_countability_gate"]["blockers"]


def test_ambiguous_legacy_settlement_revision_fails_closed(tmp_path):
    runs_root, snapshots_root, run_folder = write_score_fixture(
        tmp_path,
        trades=[trade("0.48", "3", "through2")],
    )
    (snapshots_root / EVENT / "settlement.json").unlink()
    ledger_root = tmp_path / "ledger"
    ledger_path = ledger_root / "atlanta" / "ledger.jsonl"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(
        "\n".join([
            json.dumps({"event_slug": EVENT, "settlement_bucket": 80}),
            json.dumps({"event_slug": EVENT, "settlement_bucket": 81}),
        ])
        + "\n",
        encoding="utf-8",
    )

    receipt = market_harvest_companion.score_runs(
        runs_root,
        snapshots_root,
        tmp_path / "backtest",
        selected_run_folders=[run_folder],
        ledger_root=ledger_root,
        exchange_economics_required=False,
    )
    report = json.loads(Path(receipt["report_path"]).read_text(encoding="utf-8"))

    assert receipt["status"] == "BLOCK"
    assert report["summary"]["public_counterfactual_countable_market_days"] == 0
    assert report["settlement_countability_gate"]["status"] == "BLOCK"
    assert "settlement_not_promotion_countable" in (
        report["settlement_countability_gate"]["blockers"]
    )


def test_us_platform_identity_is_refused_before_scoring_outputs(tmp_path):
    runs_root, snapshots_root, run_folder = write_score_fixture(
        tmp_path,
        trades=[trade("0.48", "3", "through2")],
    )
    backtest_root = tmp_path / "backtest"

    with pytest.raises(ValueError, match="International Polymarket"):
        market_harvest_companion.score_runs(
            runs_root,
            snapshots_root,
            backtest_root,
            selected_run_folders=[run_folder],
            exchange_economics_platform="polymarket_us",
            exchange_economics_required=False,
        )

    assert not backtest_root.exists()
    with pytest.raises(ValueError, match="International Polymarket"):
        market_harvest_companion.input_binding(
            [],
            [{"platform_id": "polymarket_us", "clob_token_id": "us-token"}],
            [],
            {"exchange_economics_platform": "polymarket_global"},
        )


def test_us_platform_identity_in_companion_tape_is_refused(tmp_path):
    runs_root, snapshots_root, run_folder = write_score_fixture(
        tmp_path,
        trades=[trade("0.48", "3", "through2")],
    )
    quote_path = run_folder / "quote_intents_long.csv"
    rows = read_csv(quote_path)
    rows[0]["platform_id"] = "polymarket_us"
    write_csv(quote_path, rows)

    with pytest.raises(ValueError, match="International Polymarket"):
        score(tmp_path, runs_root, snapshots_root, run_folder)

    assert not (tmp_path / "backtest").exists()


@pytest.mark.parametrize(
    "field",
    [
        "live_trade_permission",
        "authenticated_fill",
        "realized_pnl_eligible",
        "reward_eligible",
        "release_eligible",
        "promotion_eligible",
        "serving_eligible",
    ],
)
def test_prohibited_eligibility_in_companion_tape_is_refused(tmp_path, field):
    runs_root, snapshots_root, run_folder = write_score_fixture(
        tmp_path,
        trades=[trade("0.48", "3", "through2")],
    )
    quote_path = run_folder / "quote_intents_long.csv"
    rows = read_csv(quote_path)
    rows[0][field] = "True"
    write_csv(quote_path, rows)

    with pytest.raises(ValueError, match="prohibited eligibility"):
        score(tmp_path, runs_root, snapshots_root, run_folder)

    assert not (tmp_path / "backtest").exists()


def single_tick_args(parent):
    now = datetime(2026, 6, 14, 16, 0, tzinfo=timezone.utc)
    return (
        parent,
        "parent-run",
        TARGET_DATE,
        "paper-live-forward",
        25.0,
        now,
        [{
            "generated_at_utc": now.isoformat(),
            "policy_hash": "harvest-policy",
            "quote_permission": True,
            "live_trade_permission": False,
            "market_id": "atlanta",
            "event_slug": EVENT,
            "condition_id": "condition-80",
            "clob_token_id": "token-80",
            "range_label": "80-81 F",
            "bid_price": 0.49,
            "bid_size": 5.0,
            "ask_price": 0.51,
            "ask_size": 5.0,
            "reason_code": "QUOTE_MARKET_HARVEST_MID",
        }],
        [{"market_id": "atlanta", "status": "PASS"}],
        {"atlanta": {
            "book_capture_ids": ["book-atlanta"],
            "book_captured_at_utc": [now.isoformat()],
            "book_rows_sha256": "a" * 64,
            "token_rows_sha256": "b" * 64,
            "source_status_rows_sha256": "c" * 64,
            "source_hashes_sha256": "d" * 64,
            "exchange_economics_platform": "polymarket_global",
        }},
        {"quote_ttl_seconds": 120.0, "max_daily_loss": 25.0},
    )


def test_crash_before_checkpoint_recovers_without_duplicate_rows(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    args = single_tick_args(parent)
    original = market_harvest_companion.write_json_atomic
    failed = False

    def fail_first_state_write(path, payload):
        nonlocal failed
        if Path(path).name == "companion_state.json" and not failed:
            failed = True
            raise RuntimeError("injected checkpoint crash")
        return original(path, payload)

    with patch.object(
        market_harvest_companion,
        "write_json_atomic",
        side_effect=fail_first_state_write,
    ):
        with pytest.raises(RuntimeError, match="injected checkpoint crash"):
            market_harvest_companion.write_tick(*args)

    folder = parent / market_harvest_companion.ARTIFACT_DIRECTORY
    quote_before = (folder / "quote_intents_long.csv").read_bytes()
    lifecycle_before = (folder / "order_lifecycle.jsonl").read_bytes()
    recovered = market_harvest_companion.write_tick(*args, append=True)

    assert recovered["status"] == "DUPLICATE_SKIPPED"
    assert (folder / "quote_intents_long.csv").read_bytes() == quote_before
    assert (folder / "order_lifecycle.jsonl").read_bytes() == lifecycle_before
    assert not (folder / "pending_tick.json").exists()


def test_crash_after_lifecycle_append_recovers_partial_phase_once(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    args = single_tick_args(parent)
    original = market_harvest_companion._append_jsonl_rows_durable
    failed = False

    def append_then_crash(path, rows):
        nonlocal failed
        original(path, rows)
        if Path(path).name == "order_lifecycle.jsonl" and not failed:
            failed = True
            raise RuntimeError("injected lifecycle phase crash")

    with patch.object(
        market_harvest_companion,
        "_append_jsonl_rows_durable",
        side_effect=append_then_crash,
    ):
        with pytest.raises(RuntimeError, match="injected lifecycle phase crash"):
            market_harvest_companion.write_tick(*args)

    folder = parent / market_harvest_companion.ARTIFACT_DIRECTORY
    before = _jsonl_rows(folder / "order_lifecycle.jsonl")
    recovered = market_harvest_companion.write_tick(*args, append=True)
    after = _jsonl_rows(folder / "order_lifecycle.jsonl")

    assert recovered["status"] == "DUPLICATE_SKIPPED"
    assert after == before
    assert len({row["companion_row_id"] for row in after}) == len(after)
    assert not (folder / "pending_tick.json").exists()


def test_corrupt_checkpoint_fails_closed_without_mutating_evidence(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    args = single_tick_args(parent)
    market_harvest_companion.write_tick(*args)
    folder = parent / market_harvest_companion.ARTIFACT_DIRECTORY
    state_path = folder / "companion_state.json"
    state_path.write_text("{not-json", encoding="utf-8")
    quote_before = (folder / "quote_intents_long.csv").read_bytes()
    lifecycle_before = (folder / "order_lifecycle.jsonl").read_bytes()

    with pytest.raises(RuntimeError, match="checkpoint"):
        market_harvest_companion.write_tick(*args, append=True)

    assert (folder / "quote_intents_long.csv").read_bytes() == quote_before
    assert (folder / "order_lifecycle.jsonl").read_bytes() == lifecycle_before
    assert state_path.read_text(encoding="utf-8") == "{not-json"


def test_processed_tick_identity_cap_fails_closed_without_eviction(tmp_path):
    parent = tmp_path / "parent"
    folder = parent / market_harvest_companion.ARTIFACT_DIRECTORY
    folder.mkdir(parents=True)
    state = {
        "schema_version": market_harvest_companion.SCHEMA_VERSION,
        "parent_run_id": "parent-run",
        "processed_tick_ids": [f"{index:064x}" for index in range(2048)],
        "open_orders": {},
        "cumulative_counts": {"ticks": 2048},
    }
    state_path = folder / "companion_state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(RuntimeError, match="processed-tick cap"):
        market_harvest_companion.write_tick(*single_tick_args(parent), append=True)

    assert json.loads(state_path.read_text(encoding="utf-8")) == state
    assert not (folder / "pending_tick.json").exists()


def test_lifecycle_rows_retain_exact_tick_input_bindings(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    args = single_tick_args(parent)
    receipt = market_harvest_companion.write_tick(*args)
    lifecycle = [
        json.loads(line)
        for line in (Path(receipt["run_folder"]) / "order_lifecycle.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]

    assert lifecycle
    for row in lifecycle:
        assert row["companion_tick_id"] == receipt["tick_id"]
        assert len(row["companion_row_id"]) == 64
        assert row["book_rows_sha256"] == "a" * 64
        assert row["token_rows_sha256"] == "b" * 64
        assert row["source_status_rows_sha256"] == "c" * 64
        assert row["source_hashes_sha256"] == "d" * 64
        assert row["platform_id"] == "polymarket_global"
        assert row["authenticated_fill"] is False
        assert row["realized_pnl_eligible"] is False


def test_tick_persistence_is_bounded_by_companion_risk_budget(tmp_path):
    now = datetime(2026, 6, 14, 16, 0, tzinfo=timezone.utc)
    raw_rows = [
        {
            "generated_at_utc": now.isoformat(),
            "policy_hash": "harvest-policy",
            "quote_permission": True,
            "live_trade_permission": False,
            "market_id": f"market-{index // 11:02d}",
            "event_slug": f"event-{index // 11:02d}",
            "condition_id": f"condition-{index:03d}",
            "clob_token_id": f"token-{index:03d}",
            "range_label": f"range-{index:03d}",
            "bid_price": 0.49,
            "bid_size": 5.0,
            "ask_price": 0.51,
            "ask_size": 5.0,
            "reason_code": "QUOTE_MARKET_HARVEST_MID",
        }
        for index in range(132)
    ]
    preflight = [
        {"market_id": f"market-{index:02d}", "status": "PASS"}
        for index in range(12)
    ]
    bindings = {
        f"market-{index:02d}": {
            "book_capture_ids": [f"book-{index:02d}"],
            "book_captured_at_utc": [now.isoformat()],
            "book_rows_sha256": "a" * 64,
            "token_rows_sha256": "b" * 64,
            "source_status_rows_sha256": "c" * 64,
            "source_hashes_sha256": "d" * 64,
        }
        for index in range(12)
    }

    parent = tmp_path / "parent"
    parent.mkdir()
    economics_bytes = b'{"snapshot_id":"economics-test"}'
    economics_hash = hashlib.sha256(economics_bytes).hexdigest()
    (parent / "exchange_economics_snapshot.json").write_bytes(economics_bytes)
    receipt = market_harvest_companion.write_tick(
        parent,
        "parent-run",
        TARGET_DATE,
        "paper-live-forward",
        500.0,
        now,
        raw_rows,
        preflight,
        bindings,
        {"quote_ttl_seconds": 600.0, "max_daily_loss": 25.0},
        exchange_economics_capture={
            "captured": True,
            "status": "CAPTURED",
            "filename": "exchange_economics_snapshot.json",
            "file_sha256": economics_hash,
            "snapshot_id": "economics-test",
            "snapshot_hash": "e" * 64,
            "source_hash": "f" * 64,
        },
    )
    persisted = read_csv(Path(receipt["run_folder"]) / "quote_intents_long.csv")
    lifecycle = [
        json.loads(line)
        for line in (Path(receipt["run_folder"]) / "order_lifecycle.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line
    ]

    assert receipt["latest_tick"]["opportunities"] == 132
    assert receipt["latest_tick"]["simulated_posted_quotes"] == 5
    assert len(persisted) == 5
    assert len(lifecycle) == 20
    assert {row["transition"] for row in lifecycle} == {"intended", "paper_posted"}
    assert receipt["open_order_count"] == 10
    assert receipt["budget_reserved_usdc"] <= 25.0
    assert (
        Path(receipt["run_folder"]) / "exchange_economics_snapshot.json"
    ).read_bytes() == economics_bytes
    run_config = json.loads(
        (Path(receipt["run_folder"]) / "run_config.json").read_text(encoding="utf-8")
    )
    assert run_config["exchange_economics_capture"]["file_sha256"] == economics_hash

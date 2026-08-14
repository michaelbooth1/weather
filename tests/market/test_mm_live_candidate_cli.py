import json
from pathlib import Path

import pytest

from weather.market.exchange_economics import build_snapshot_payload
from weather.market import mm_live_candidate_cli as candidate_cli


NOW = "2026-08-14T00:15:00+00:00"
TARGET_DATE = "2026-08-14"
CONDITION = "0x" + "1" * 64


def write_snapshot(path, *, verified_at=NOW):
    payload = build_snapshot_payload(
        target_date=TARGET_DATE,
        verified_at_utc=verified_at,
        platform="polymarket_global",
        condition_id=CONDITION,
        token_ids=["101", "102"],
        reward_daily_rate_usdc=1,
        rewards_min_size=20,
        rewards_max_spread_cents=4.5,
    )
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def book(token_id, bid, ask, *, bid_size=100, ask_size=100, condition=CONDITION):
    return {
        "asset_id": str(token_id),
        "market": condition,
        "bids": [{"price": str(bid), "size": str(bid_size)}],
        "asks": [{"price": str(ask), "size": str(ask_size)}],
        "min_order_size": "5",
        "tick_size": "0.01",
        "neg_risk": False,
    }


def test_selector_binds_current_economics_and_nonmarketable_stage1_intent(tmp_path):
    snapshot = write_snapshot(tmp_path / "economics.json")
    output = tmp_path / "candidate.json"
    seen = {}

    def read_books(tokens):
        seen["tokens"] = list(tokens)
        return [
            book("101", 0.32, 0.33, bid_size=575, ask_size=180),
            book("102", 0.67, 0.68, bid_size=180, ask_size=575),
        ]

    plan = candidate_cli.select_live_pilot_candidate(
        snapshot,
        TARGET_DATE,
        output,
        now=NOW,
        book_reader=read_books,
    )

    assert plan["status"] == "PASS"
    assert set(seen["tokens"]) == {"101", "102"}
    assert plan["selected"]["token_id"] == "101"
    assert plan["selected"]["condition_id"] == CONDITION
    assert plan["selected"]["stage1_intent"] == {
        "side": "BUY",
        "price": 0.01,
        "size": 5.0,
        "notional_pusd": 0.05,
        "post_only": True,
    }
    assert plan["selected"]["lifecycle_probe_reward_min_size_met"] is False
    assert plan["selection_is_trading_authorization"] is False
    assert plan["selection_policy"]["plan_max_age_seconds"] == 300
    assert plan["selected"]["neg_risk"] is False
    assert plan["plan_sha256"] == candidate_cli.candidate_plan_sha256(plan)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved == plan


def test_selector_blocks_extreme_crossed_or_wrong_condition_books(tmp_path):
    snapshot = write_snapshot(tmp_path / "economics.json")
    output = tmp_path / "candidate-block.json"

    plan = candidate_cli.select_live_pilot_candidate(
        snapshot,
        TARGET_DATE,
        output,
        now=NOW,
        book_reader=lambda _tokens: [
            book("101", 0.98, 0.99),
            book("102", 0.40, 0.39),
            book("101", 0.40, 0.41, condition="0x" + "2" * 64),
        ],
    )

    assert plan["status"] == "BLOCK"
    assert plan["candidate_count"] == 0
    assert plan["selected"] is None
    assert plan["missing"] == ["current_safe_fee_eligible_book_candidate"]


def test_selector_blocks_stale_economics_before_public_book_fetch(tmp_path):
    snapshot = write_snapshot(
        tmp_path / "economics-stale.json",
        verified_at="2026-08-13T20:00:00+00:00",
    )
    output = tmp_path / "candidate-stale.json"
    called = False

    def read_books(_tokens):
        nonlocal called
        called = True
        return []

    plan = candidate_cli.select_live_pilot_candidate(
        snapshot,
        TARGET_DATE,
        output,
        now=NOW,
        book_reader=read_books,
    )

    assert plan["status"] == "BLOCK"
    assert called is False
    assert plan["economics_gate_ok"] is False
    assert plan["missing"] == ["current_exchange_economics_gate"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_order_size", "10"),
        ("tick_size", "0.001"),
        ("neg_risk", "false"),
    ],
)
def test_selector_rejects_book_rule_drift(tmp_path, field, value):
    snapshot = write_snapshot(tmp_path / "economics.json")
    output = tmp_path / f"candidate-{field}.json"
    drifted_book = book("101", 0.40, 0.41)
    drifted_book[field] = value

    plan = candidate_cli.select_live_pilot_candidate(
        snapshot,
        TARGET_DATE,
        output,
        now=NOW,
        book_reader=lambda _tokens: [drifted_book],
    )

    assert plan["status"] == "BLOCK"
    assert plan["candidate_count"] == 0


def test_selector_rejects_economics_snapshot_change_after_gate(
    tmp_path,
    monkeypatch,
):
    snapshot = write_snapshot(tmp_path / "economics.json")
    output = tmp_path / "candidate.json"
    monkeypatch.setattr(
        candidate_cli,
        "load_exchange_economics_gate",
        lambda *_args, **_kwargs: {
            "ok": True,
            "snapshot_id": "old-snapshot",
            "exchange_economics_hash": "not-the-current-hash",
            "missing": [],
        },
    )

    with pytest.raises(RuntimeError, match="changed after validation"):
        candidate_cli.select_live_pilot_candidate(
            snapshot,
            TARGET_DATE,
            output,
            now=NOW,
            book_reader=lambda _tokens: [],
        )

    assert not output.exists()


def test_selector_requires_new_output_path(tmp_path):
    snapshot = write_snapshot(tmp_path / "economics.json")
    output = tmp_path / "existing.json"
    output.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="must be new"):
        candidate_cli.select_live_pilot_candidate(
            snapshot,
            TARGET_DATE,
            output,
            now=NOW,
            book_reader=lambda _tokens: [],
        )


def test_main_never_prints_raw_network_exception(monkeypatch, capsys):
    monkeypatch.setattr(
        candidate_cli,
        "select_live_pilot_candidate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("RAW-PUBLIC-NETWORK-DETAIL")
        ),
    )

    status = candidate_cli.main([
        "--economics-snapshot", "economics.json",
        "--target-date", TARGET_DATE,
        "--plan-out", "candidate.json",
    ])

    assert status == 1
    stderr = capsys.readouterr().err
    assert "RuntimeError" in stderr
    assert "RAW-PUBLIC-NETWORK-DETAIL" not in stderr

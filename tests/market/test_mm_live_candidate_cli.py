import csv
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


def write_paper_evidence(tmp_path, snapshot, *, quote_permission=True):
    economics = json.loads(Path(snapshot).read_text(encoding="utf-8"))
    policy_hash = "paper-policy-hash"
    config = tmp_path / "paper-run-config.json"
    config.write_text(json.dumps({
        "schema_version": "mm_run_v0.2",
        "run_id": "paper-run-1",
        "target_date": TARGET_DATE,
        "mode": "paper-live-forward",
        "permission_profile": "market_harvest",
        "markets": ["toronto"],
        "budget_usdc": 25,
        "policy_hash": policy_hash,
        "exchange_economics_snapshot_id": economics["snapshot_id"],
        "exchange_economics_hash": economics["exchange_economics_hash"],
        "shadow_safety": {
            "live_trade_permission_allowed": False,
            "loads_private_keys": False,
            "posts_orders": False,
        },
        "policy_config": {
            "quote_size": 5,
            "quote_ttl_seconds": 120,
            "max_daily_loss": 25,
            "max_event_notional": 25,
            "max_band_notional": 10,
        },
    }), encoding="utf-8")
    quote_path = tmp_path / "paper-quotes.csv"
    fieldnames = [
        "schema_version", "run_id", "target_date", "run_mode", "preflight_status", "market_id",
        "known_edge_permission", "model_variant_probability_source", "shadow_mode",
        "quote_permission", "live_trade_permission", "action", "budget_action",
        "side",
        "exchange_economics_snapshot_id", "exchange_economics_hash", "policy_hash",
        "clob_token_id", "condition_id", "generated_at_utc", "quote_ttl_seconds",
        "bid_price", "bid_size", "ask_price", "ask_size", "quote_risk_usdc",
        "run_budget_usdc", "expected_reward_score", "expected_rebate_value",
        "range_label",
    ]
    with quote_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for token, bid, ask, label in (
            ("101", 0.31, 0.34, "lower"),
            ("102", 0.66, 0.69, "upper"),
        ):
            writer.writerow({
                "schema_version": candidate_cli.QUOTE_SCHEMA_VERSION,
                "run_id": "paper-run-1",
                "target_date": TARGET_DATE,
                "run_mode": "paper-live-forward",
                "preflight_status": "PASS",
                "market_id": "toronto",
                "known_edge_permission": "market_harvest",
                "model_variant_probability_source": "market_mid_no_model",
                "shadow_mode": True,
                "quote_permission": quote_permission,
                "live_trade_permission": False,
                "action": "QUOTE",
                "side": "TWO_SIDED",
                "budget_action": "reserved",
                "exchange_economics_snapshot_id": economics["snapshot_id"],
                "exchange_economics_hash": economics["exchange_economics_hash"],
                "policy_hash": policy_hash,
                "clob_token_id": token,
                "condition_id": CONDITION,
                "generated_at_utc": NOW,
                "quote_ttl_seconds": 120,
                "bid_price": bid,
                "bid_size": 5,
                "ask_price": ask,
                "ask_size": 5,
                "quote_risk_usdc": round(
                    bid * 5 + (1 - ask) * 5,
                    6,
                ),
                "run_budget_usdc": 25,
                "expected_reward_score": 0,
                "expected_rebate_value": 0,
                "range_label": label,
            })
    return config, quote_path


def select(snapshot, target_date, output, *, tmp_path, **kwargs):
    config, quotes = write_paper_evidence(tmp_path, snapshot)
    return candidate_cli.select_live_pilot_candidate(
        snapshot,
        target_date,
        output,
        paper_run_config=config,
        paper_quote_intents=quotes,
        **kwargs,
    )


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

    plan = select(
        snapshot,
        TARGET_DATE,
        output,
        tmp_path=tmp_path,
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
    assert plan["selected"]["paper_quote_proof"]["quote_permission"] is True
    assert plan["selected"]["paper_quote_proof"]["live_trade_permission"] is False
    assert len(plan["paper_quote_evidence"]["quote_intents_sha256"]) == 64
    assert plan["plan_sha256"] == candidate_cli.candidate_plan_sha256(plan)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved == plan


def test_selector_blocks_extreme_crossed_or_wrong_condition_books(tmp_path):
    snapshot = write_snapshot(tmp_path / "economics.json")
    output = tmp_path / "candidate-block.json"

    plan = select(
        snapshot,
        TARGET_DATE,
        output,
        tmp_path=tmp_path,
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
    assert plan["missing"] == ["current_paper_proved_safe_fee_eligible_book_candidate"]


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

    plan = select(
        snapshot,
        TARGET_DATE,
        output,
        tmp_path=tmp_path,
        now=NOW,
        book_reader=read_books,
    )

    assert plan["status"] == "BLOCK"
    assert called is False
    assert plan["economics_gate_ok"] is False
    assert plan["missing"] == ["current_exchange_economics_gate"]


def test_selector_rejects_paper_run_without_quote_permission(tmp_path):
    snapshot = write_snapshot(tmp_path / "economics.json")
    config, quotes = write_paper_evidence(
        tmp_path,
        snapshot,
        quote_permission=False,
    )
    called = False

    def read_books(_tokens):
        nonlocal called
        called = True
        return []

    with pytest.raises(RuntimeError, match="no current qualifying"):
        candidate_cli.select_live_pilot_candidate(
            snapshot,
            TARGET_DATE,
            tmp_path / "candidate.json",
            paper_run_config=config,
            paper_quote_intents=quotes,
            now=NOW,
            book_reader=read_books,
        )

    assert called is False


def test_selector_can_refresh_the_exact_bootstrap_scope(tmp_path):
    snapshot = write_snapshot(tmp_path / "economics.json")
    plan = select(
        snapshot,
        TARGET_DATE,
        tmp_path / "candidate.json",
        tmp_path=tmp_path,
        expected_condition_id=CONDITION,
        expected_token_id="102",
        now=NOW,
        book_reader=lambda _tokens: [
            book("101", 0.32, 0.33),
            book("102", 0.67, 0.68),
        ],
    )

    assert plan["status"] == "PASS"
    assert plan["selected"]["token_id"] == "102"
    assert plan["selection_policy"]["expected_bootstrap_scope"] == {
        "condition_id": CONDITION,
        "token_id": "102",
    }
    gate = candidate_cli.load_stage1_candidate_gate(
        tmp_path / "candidate.json",
        TARGET_DATE,
        expected_condition_id=CONDITION,
        expected_token_id="102",
        now=NOW,
    )
    assert gate["ok"] is True
    assert gate["paper_quote_row_sha256"] == plan["selected"][
        "paper_quote_proof"
    ]["quote_row_sha256"]
    assert gate["stage1_intent"] == plan["selected"]["stage1_intent"]
    assert gate["tick_size"] == plan["selected"]["tick_size"]
    assert gate["order_min_size"] == plan["selected"]["order_min_size"]


def test_stage1_gate_rejects_a_tampered_candidate_plan(tmp_path):
    snapshot = write_snapshot(tmp_path / "economics.json")
    output = tmp_path / "candidate.json"
    plan = select(
        snapshot,
        TARGET_DATE,
        output,
        tmp_path=tmp_path,
        now=NOW,
        book_reader=lambda _tokens: [book("101", 0.32, 0.33)],
    )
    plan["selected"]["token_id"] = "999"
    output.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(RuntimeError, match="plan_hash"):
        candidate_cli.load_stage1_candidate_gate(
            output,
            TARGET_DATE,
            expected_condition_id=CONDITION,
            expected_token_id="101",
            now=NOW,
        )


def test_stage1_gate_rejects_an_unconstrained_prebootstrap_plan(tmp_path):
    snapshot = write_snapshot(tmp_path / "economics.json")
    output = tmp_path / "candidate.json"
    select(
        snapshot,
        TARGET_DATE,
        output,
        tmp_path=tmp_path,
        now=NOW,
        book_reader=lambda _tokens: [book("101", 0.32, 0.33)],
    )

    with pytest.raises(RuntimeError, match="constrained_scope"):
        candidate_cli.load_stage1_candidate_gate(
            output,
            TARGET_DATE,
            expected_condition_id=CONDITION,
            expected_token_id="101",
            now=NOW,
        )


def test_discovery_gate_accepts_only_the_complete_unconstrained_plan(tmp_path):
    snapshot = write_snapshot(tmp_path / "economics.json")
    output = tmp_path / "candidate.json"
    plan = select(
        snapshot,
        TARGET_DATE,
        output,
        tmp_path=tmp_path,
        now=NOW,
        book_reader=lambda _tokens: [book("101", 0.32, 0.33)],
    )

    gate = candidate_cli.load_candidate_discovery_gate(output, now=NOW)

    assert gate["ok"] is True
    assert gate["target_date"] == TARGET_DATE
    assert gate["condition_id"] == CONDITION
    assert gate["token_id"] == "101"
    assert gate["plan_sha256"] == candidate_cli.hashlib.sha256(
        output.read_bytes()
    ).hexdigest()
    assert gate["semantic_plan_sha256"] == plan["plan_sha256"]


@pytest.mark.parametrize(
    ("mutation", "missing_check"),
    [
        (
            lambda payload: payload["selected"]["paper_quote_proof"].update(
                {"quote_permission": False}
            ),
            "paper_permission",
        ),
        (
            lambda payload: payload["selected"].update({"fee_rate": 0}),
            "current_book_rules",
        ),
        (
            lambda payload: payload["selected"].update(
                {"book_sha256": "fabricated"}
            ),
            "current_book_rules",
        ),
        (lambda payload: payload.update({"unexpected": True}), "exact_schema_shape"),
        (
            lambda payload: payload.update(
                {"paper_quote_evidence": list(payload["paper_quote_evidence"].items())}
            ),
            "exact_schema_shape",
        ),
        (lambda payload: payload.update({"platform": "polymarket_us"}), "platform"),
        (lambda payload: payload.update({"settlement_unit": "USDC.e"}), "settlement_unit"),
        (
            lambda payload: payload.update(
                {"economics_gate_missing": ["fabricated-pass"]}
            ),
            "economics",
        ),
        (
            lambda payload: payload.update(
                {"expires_at_utc": payload["created_at_utc"]}
            ),
            "current|expiry_contract",
        ),
        (
            lambda payload: payload["selected"]["paper_quote_proof"].update(
                {"live_trade_permission": True}
            ),
            "paper_mutation_disabled",
        ),
        (
            lambda payload: payload["paper_quote_evidence"].update(
                {"quote_intents_row_count": 0}
            ),
            "paper_hashes",
        ),
        (
            lambda payload: payload["selected"].update({"midpoint": 0.4}),
            "current_book",
        ),
        (
            lambda payload: payload["selected"].update({"tick_size": 0.02}),
            "paper_quote_shape|current_book_rules|intent",
        ),
        (
            lambda payload: payload["selected"]["stage1_intent"].update(
                {"notional_pusd": 0.04}
            ),
            "intent",
        ),
        (
            lambda payload: payload["selected"]["paper_quote_proof"].update(
                {"quote_risk_pusd": 1}
            ),
            "paper_quote_shape",
        ),
        (
            lambda payload: payload["selected"]["paper_quote_proof"].update(
                {"condition_id": "0x" + "9" * 64}
            ),
            "paper_condition",
        ),
        (
            lambda payload: payload["selection_policy"][
                "expected_bootstrap_scope"
            ].update({"condition_id": CONDITION, "token_id": "101"}),
            "unconstrained_scope",
        ),
    ],
)
def test_discovery_gate_rejects_rehashed_contract_fabrication(
    tmp_path,
    mutation,
    missing_check,
):
    snapshot = write_snapshot(tmp_path / "economics.json")
    output = tmp_path / "candidate.json"
    plan = select(
        snapshot,
        TARGET_DATE,
        output,
        tmp_path=tmp_path,
        now=NOW,
        book_reader=lambda _tokens: [book("101", 0.32, 0.33)],
    )
    mutation(plan)
    plan["plan_sha256"] = candidate_cli.candidate_plan_sha256(plan)
    output.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(RuntimeError, match=missing_check):
        candidate_cli.load_candidate_discovery_gate(output, now=NOW)


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

    plan = select(
        snapshot,
        TARGET_DATE,
        output,
        tmp_path=tmp_path,
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
        select(
            snapshot,
            TARGET_DATE,
            output,
            tmp_path=tmp_path,
            now=NOW,
            book_reader=lambda _tokens: [],
        )

    assert not output.exists()


def test_selector_requires_new_output_path(tmp_path):
    snapshot = write_snapshot(tmp_path / "economics.json")
    output = tmp_path / "existing.json"
    output.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="must be new"):
        select(
            snapshot,
            TARGET_DATE,
            output,
            tmp_path=tmp_path,
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
        "--paper-run-config", "run-config.json",
        "--paper-quote-intents", "quotes.csv",
        "--plan-out", "candidate.json",
    ])

    assert status == 1
    stderr = capsys.readouterr().err
    assert "RuntimeError" in stderr
    assert "RAW-PUBLIC-NETWORK-DETAIL" not in stderr

import copy
import hashlib
from decimal import localcontext
import json
from pathlib import Path

import pytest

from weather.market import mm_exchange_reports as reports
from weather.market import mm_incentive_payments as payments
from weather import schema_registry_data as registry
from weather.market.mm_incentive_payments import reconcile_incentive_payments


def test_source_identity_is_the_tested_checkout():
    root = Path(__file__).resolve().parents[2]
    for module, relative in (
        (payments, "src/weather/market/mm_incentive_payments.py"),
        (reports, "src/weather/market/mm_exchange_reports.py"),
        (registry, "src/weather/schema_registry_data.py"),
    ):
        actual = Path(module.__file__).resolve()
        assert actual == root / relative
        print("LOADED_SOURCE " + json.dumps({"path": str(actual), "sha256": hashlib.sha256(actual.read_bytes()).hexdigest()}))


@pytest.fixture
def evidence():
    path = Path(__file__).resolve().parents[1] / "fixtures" / "mm_incentive_payments.json"
    return json.loads(path.read_text(encoding="utf-8"))


def payment(evidence, program="liquidity_reward", amount="0.50", suffix="2"):
    earning = next(row for row in evidence["earnings"] if row["program"] == program)
    earning["amount"] = amount
    distribution = copy.deepcopy(evidence["distributions"][0])
    distribution.update(id="distribution-" + suffix, earning_id=earning["id"],
                        program=program, amount=amount, transaction_hash="0x" + suffix * 64)
    credit = copy.deepcopy(evidence["wallet_credits"][0])
    credit.update(id="credit-" + suffix, amount=amount, transaction_hash=distribution["transaction_hash"])
    evidence["distributions"].append(distribution)
    evidence["wallet_credits"].append(credit)
    return distribution, credit


def rebate_query(evidence):
    scope = evidence["scope"]
    return {
        "status": "OBSERVED", "query_scope": "exact_maker_date", "http_status": 200,
        "response_sha256": "e" * 64, "query_date": scope["query_date"],
        "queried_at_utc": "2026-06-15T01:00:00Z", "payout_cycle_complete": True,
        "maker_address": scope["maker_address"], "condition_id": scope["condition_id"],
        "request_url": "https://clob.polymarket.com/rebates/current?date="
                       + scope["query_date"] + "&maker_address=" + scope["maker_address"],
        "rows": [{
            "date": scope["query_date"], "maker_address": scope["maker_address"],
            "condition_id": scope["condition_id"],
            "asset_address": reports.PUSD_COLLATERAL_PROXY_ADDRESS,
            "rebated_fees_usdc": next(row["amount"] for row in evidence["earnings"]
                                     if row["program"] == "maker_rebate"),
        }],
    }


def cash_episode(evidence, *, ending="25.51", external="0", gross="0"):
    scope = evidence["scope"]
    account, condition = scope["maker_address"], scope["condition_id"]
    return {
        "rewards": {"maker_rebate_evidence": rebate_query(evidence),
                    "incentive_payment_evidence": evidence},
        "balances": {"starting_cash_usdc": "25", "ending_cash_usdc": ending},
        "positions": [],
        "position_evidence": {
            "status": "OBSERVED", "query_scope": "exact_maker_condition",
            "maker_address": account, "condition_id": condition, "rows": [],
            "http_status": 200, "response_sha256": "f" * 64,
            "request_url": "https://data-api.polymarket.com/positions?user="
                           + account + "&market=" + condition + "&sizeThreshold=0&limit=500&offset=0",
        },
        "fees": {"actual_fee_evidence": {
            "status": "OBSERVED", "coverage": "all_pilot_trades_and_exits",
            "includes_taker_and_flattening_fees": True,
            "calculation_basis": "confirmed_trade_events",
            "fee_formula": "shares_x_rate_x_price_x_one_minus_price",
            "maker_fees_zero": True, "precision_decimal_places": 5,
            "confirmed_trade_set_sha256": reports.confirmed_trade_set_sha256([]),
            "maker_address": account, "condition_id": condition,
            "observed_fill_count": 0, "paid_usdc": "0",
        }},
        "financial_identity": {
            "external_cash_flows_usdc": external, "ending_positions_zero": True,
            "settlement_pnl_excludes_fees_and_incentives": True,
        },
        "redemption_status": {"redemption_usdc": "0", "settlement_pnl_usdc": gross},
    }


def test_explicit_transfer_proves_supplied_payment_without_claiming_source_verification(evidence):
    result = reconcile_incentive_payments(evidence)
    assert result["complete"]
    assert result["programs"]["maker_rebate"]["paid_amount"] == "0.010000"
    assert result["programs"]["liquidity_reward"]["completed_zero"]
    assert result["matched_distribution_ids"] == ["rebate-distribution"]
    assert result["source_evidence_independently_verified"] is False
    assert result["live_permission"] is False


@pytest.mark.parametrize("payload", [None, {}, {"schema_version": "unsupported"}, []])
def test_unsupported_or_absent_evidence_cannot_produce_income(payload):
    result = reconcile_incentive_payments(payload)
    assert not result["complete"]
    assert result["programs"] == {}
    assert result["live_permission"] is False


def test_unpaid_accrual_and_estimates_are_separate_from_completed_zero_payment(evidence):
    evidence["earnings"][0]["amount"] = "0.49"
    evidence["distributions"] = []
    evidence["wallet_credits"] = []
    evidence["estimates"] = {"maker_rebate": "99"}
    result = reconcile_incentive_payments(evidence)
    program = result["programs"]["maker_rebate"]
    assert result["complete"]
    assert program["paid_amount"] == "0.000000"
    assert program["accrued_amount"] == "0.49"
    assert program["unpaid_accrual_amount"] == "0.49"
    assert program["estimated_amount"] == "99"


@pytest.mark.parametrize("part,field", [
    ("maker_rebate", "earnings_complete"), ("maker_rebate", "distributions_complete"),
    ("liquidity_reward", "payout_cycle_complete"), ("wallet_query", "complete"),
])
def test_incomplete_query_does_not_establish_paid_zero(evidence, part, field):
    query = evidence[part] if part == "wallet_query" else evidence["queries"][part]
    query[field] = False
    result = reconcile_incentive_payments(evidence)
    assert not result["complete"]
    assert result["programs"]["maker_rebate"]["paid_amount"] is None


def test_query_before_payout_deadline_remains_pending(evidence):
    evidence["queries"]["liquidity_reward"]["payout_due_at_utc"] = "2026-06-16T00:00:00Z"
    result = reconcile_incentive_payments(evidence)
    assert "liquidity_reward_query_incomplete" in result["blockers"]
    assert result["programs"]["liquidity_reward"]["paid_amount"] is None


@pytest.mark.parametrize("field,value", [
    ("maker_address", "0x" + "c" * 40), ("query_date", "2026-06-13"),
    ("asset", "eip155:137/erc20:0x" + "d" * 40), ("condition_id", "0x" + "c" * 64),
])
def test_query_scope_is_bound_to_account_asset_date_and_condition(evidence, field, value):
    evidence["queries"]["maker_rebate"]["scope"][field] = value
    result = reconcile_incentive_payments(evidence)
    assert result["blockers"] == ["programme_query_scope_mismatch"]


def test_out_of_order_records_preserve_reconciliation(evidence):
    payment(evidence)
    expected = reconcile_incentive_payments(evidence)
    for name in ("earnings", "distributions", "wallet_credits"):
        evidence[name].reverse()
    assert reconcile_incentive_payments(evidence) == expected


def test_different_record_ids_cannot_duplicate_a_wallet_transfer(evidence):
    duplicate = dict(evidence["wallet_credits"][0], id="different-record-id")
    evidence["wallet_credits"].append(duplicate)
    assert reconcile_incentive_payments(evidence)["blockers"] == ["wallet_transfer_counted_twice"]


def test_different_earning_ids_cannot_duplicate_the_same_period_scope(evidence):
    evidence["earnings"].append(dict(evidence["earnings"][0], id="duplicate-earning"))
    assert reconcile_incentive_payments(evidence)["blockers"] == ["earning_duplicate_scope"]


def test_same_distribution_is_not_counted_twice(evidence):
    evidence["distributions"].append(copy.deepcopy(evidence["distributions"][0]))
    assert reconcile_incentive_payments(evidence)["blockers"] == ["distributions_duplicate_id"]


def test_different_distribution_ids_cannot_duplicate_an_allocation(evidence):
    evidence["earnings"][0]["amount"] = "0.02"
    evidence["wallet_credits"][0]["amount"] = "0.02"
    evidence["distributions"].append(dict(evidence["distributions"][0], id="copied-distribution"))
    result = reconcile_incentive_payments(evidence)
    assert not result["complete"]
    assert result["blockers"] == ["distribution_duplicate_transfer_allocation"]


def test_one_wallet_credit_cannot_be_claimed_by_both_programmes(evidence):
    evidence["earnings"][0]["amount"] = "0.005"
    evidence["earnings"][1]["amount"] = "0.005"
    first = evidence["distributions"][0]
    first["amount"] = "0.005"
    evidence["distributions"].append(dict(first, id="second-programme",
        earning_id="reward-earning", program="liquidity_reward"))
    result = reconcile_incentive_payments(evidence)
    assert result["blockers"] == ["wallet_credit_claimed_by_multiple_programmes"]


def test_equal_amount_does_not_match_a_different_transaction(evidence):
    evidence["distributions"][0]["transaction_hash"] = "0x" + "2" * 64
    result = reconcile_incentive_payments(evidence)
    assert "wallet_credit_missing" in result["blockers"]
    assert result["programs"]["maker_rebate"]["paid_amount"] is None


@pytest.mark.parametrize("status", ["PENDING", "FAILED", "REVERTED", None])
def test_unconfirmed_credit_is_not_paid_income(evidence, status):
    evidence["wallet_credits"][0]["status"] = status
    result = reconcile_incentive_payments(evidence)
    assert result["blockers"] == ["wallet_credit_not_confirmed"]
    assert result["programs"]["maker_rebate"]["paid_amount"] is None


def test_transfer_amount_must_equal_its_complete_allocation(evidence):
    evidence["wallet_credits"][0]["amount"] = "0.02"
    result = reconcile_incentive_payments(evidence)
    assert result["blockers"] == ["wallet_credit_amount_mismatch"]
    assert result["unresolved_distribution_ids"] == ["rebate-distribution"]


def test_partial_payments_preserve_unpaid_accrual(evidence):
    payment(evidence, program="maker_rebate", amount="0.01")
    evidence["earnings"][0]["amount"] = "0.03"
    result = reconcile_incentive_payments(evidence)
    assert result["complete"]
    assert result["programs"]["maker_rebate"]["paid_amount"] == "0.020000"
    assert result["programs"]["maker_rebate"]["unpaid_accrual_amount"] == "0.01"


def test_portfolio_payment_cannot_be_assigned_to_one_condition(evidence):
    evidence["earnings"][0]["condition_id"] = None
    evidence["distributions"][0]["condition_id"] = None
    result = reconcile_incentive_payments(evidence)
    assert not result["complete"]
    assert "portfolio_payment_not_attributable_to_condition" in result["blockers"]
    assert result["programs"]["maker_rebate"]["paid_amount"] is None


def test_explicit_portfolio_scope_can_reconcile_without_session_attribution(evidence):
    evidence["scope"]["condition_id"] = None
    for query in evidence["queries"].values():
        query["scope"]["condition_id"] = None
    result = reconcile_incentive_payments(evidence)
    assert result["complete"]
    assert result["scope"]["condition_id"] is None
    assert result["programs"]["maker_rebate"]["paid_amount"] == "0.010000"


@pytest.mark.parametrize("amount", [True, 0.1, "NaN", "Infinity", "-1", "1e100", "0.0000000000001"])
def test_invalid_or_unbounded_amounts_fail_closed(evidence, amount):
    evidence["earnings"][0]["amount"] = amount
    assert not reconcile_incentive_payments(evidence)["complete"]


def test_wallet_amount_requires_exact_six_decimal_precision(evidence):
    evidence["wallet_credits"][0]["amount"] = "0.0100001"
    assert reconcile_incentive_payments(evidence)["blockers"] == ["payment_precision_invalid"]


def test_accrual_rounding_is_explicit_and_independent_of_global_decimal_context(evidence):
    evidence["earnings"][0]["amount"] = "0.0099999"
    with localcontext() as context:
        context.prec = 2
        result = reconcile_incentive_payments(evidence)
    assert result["complete"]
    assert result["programs"]["maker_rebate"]["rounding_residual_amount"] == "1E-7"


def test_wrong_wallet_asset_does_not_become_income_by_field_name(evidence):
    evidence["wallet_credits"][0]["asset"] = "eip155:137/erc20:0x" + "d" * 40
    assert reconcile_incentive_payments(evidence)["blockers"] == ["wallet_credit_scope_mismatch"]


def test_no_fill_paid_rewards_reconcile_cash_without_proving_fill_quality(evidence):
    payment(evidence)
    episode = cash_episode(evidence)
    report = reports.build_pilot_report_payload(episode, [{"quote_permission": True}], [], {})
    financial = report["financial_reconciliation"]
    assert financial["complete"]
    assert financial["actual_maker_rebate_usdc"] == 0.01
    assert financial["actual_liquidity_reward_usdc"] == 0.5
    assert financial["actual_total_pnl_after_fees_incentives_usdc"] == 0.51
    assert not report["evidence_complete"]
    assert "live_fills" in report["missing_evidence"]


def test_external_cash_flow_is_not_added_to_profit(evidence):
    payment(evidence)
    financial = reports.build_financial_reconciliation(
        cash_episode(evidence, ending="26.51", external="1"), [], [])
    assert financial["complete"]
    assert financial["actual_total_pnl_after_fees_incentives_usdc"] == 0.51
    assert financial["financial_identity_delta_usdc"] == 0


def test_incentives_already_in_gross_pnl_fail_the_cash_identity(evidence):
    payment(evidence)
    financial = reports.build_financial_reconciliation(cash_episode(evidence, gross="0.51"), [], [])
    assert not financial["complete"]
    assert financial["actual_total_pnl_after_fees_incentives_usdc"] is None
    assert "financial_identity_mismatch" in financial["missing_evidence"]


def test_legacy_positive_rebate_query_is_accrual_until_wallet_attribution_exists(evidence):
    rewards = {"maker_rebate_evidence": rebate_query(evidence)}
    result = reports.maker_rebate_reconciliation(rewards)
    assert result["query_complete"]
    assert result["accrued_maker_rebate_usdc"] == 0.01
    assert result["actual_maker_rebate_usdc"] is None
    assert not result["complete"]


def test_duplicate_venue_rebate_condition_is_rejected(evidence):
    query = rebate_query(evidence)
    query["rows"] *= 2
    result = reports.maker_rebate_reconciliation({"maker_rebate_evidence": query})
    assert "maker_rebate_duplicate_condition" in result["blockers"]
    assert result["actual_maker_rebate_usdc"] is None


def test_payment_version_cannot_be_silently_dropped_by_financial_report(evidence):
    episode = cash_episode(evidence, ending="25.01")
    evidence["schema_version"] = "unsupported"
    result = reports.build_financial_reconciliation(episode, [], [])
    assert not result["complete"]
    assert result["actual_total_pnl_after_fees_incentives_usdc"] is None


def test_financial_report_preserves_explicit_accrual_rounding(evidence):
    evidence["earnings"][0]["amount"] = "0.0099999"
    result = reports.build_financial_reconciliation(cash_episode(evidence, ending="25.01"), [], [])
    assert result["complete"]
    assert result["actual_maker_rebate_usdc"] == 0.01
    assert result["incentive_payment_reconciliation"]["programs"]["maker_rebate"]["rounding_residual_amount"] == "1E-7"


def test_paid_rewards_do_not_bypass_nonzero_position_gate(evidence):
    payment(evidence)
    episode = cash_episode(evidence)
    episode["positions"] = [{"size": "0.01"}]
    episode["position_evidence"]["rows"] = list(episode["positions"])
    result = reports.build_financial_reconciliation(episode, [], [])
    assert not result["complete"]
    assert "ending_positions_nonzero" in result["missing_evidence"]


def test_new_renderer_refuses_old_accrual_report_as_a_payment_report():
    with pytest.raises(ValueError, match="Unsupported pilot report schema"):
        reports.render_pilot_report({"schema_version": "mm_exchange_adapter_v0.2"})

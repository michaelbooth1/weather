"""Synthetic offline receipts; these fixtures are not observed account evidence."""

from copy import deepcopy
from decimal import localcontext

import pytest

from weather.market import mm_exchange_reports as reports
from weather.schema_registry import schema_version


MAKER = "0x" + "a" * 40
CONDITION = "0x" + "b" * 64
ACCRUAL_START = "2026-09-01T00:00:00+00:00"
ACCRUAL_END = "2026-09-02T00:00:00+00:00"
CASH_END = "2026-09-04T00:00:00+00:00"
OBSERVED = "2026-09-04T01:00:00+00:00"
CREDIT_TIME = "2026-09-03T12:00:00+00:00"
SELECTOR = reports.PAID_INCENTIVE_RECONCILIATION_SCHEMA


def evidence_fixture():
    scope = {
        "maker_address": MAKER, "condition_id": CONDITION,
        "cash_asset": deepcopy(reports.INCENTIVE_CASH_ASSET),
        "accrual_start_utc": ACCRUAL_START, "accrual_end_utc": ACCRUAL_END,
        "cash_start_utc": ACCRUAL_START, "cash_end_utc": CASH_END,
    }
    evidence = {
        "schema_version": reports.PAID_INCENTIVE_EVIDENCE_SCHEMA,
        "scope": scope, "as_of_utc": OBSERVED, "sources": {},
        "accruals": [], "distributions": [], "wallet_credits": [],
        "excluded_external_credit_ids": [],
    }
    for index, kind in enumerate(("accruals", "distributions", "wallet_credits"), 1):
        end = ACCRUAL_END if kind == "accruals" else CASH_END
        evidence["sources"][kind] = {
            "status": "OBSERVED", "query_scope": "exact_account_asset_period",
            "request_scope": {
                "maker_address": MAKER, "cash_asset": deepcopy(reports.INCENTIVE_CASH_ASSET),
                "condition_scope": "account", "period_start_utc": ACCRUAL_START,
                "period_end_utc": end,
            },
            "request_sha256": str(index) * 64, "response_sha256": "e" * 64,
            "observed_at_utc": OBSERVED, "coverage_through_utc": end,
            "complete": True, "pagination_complete": True, "payout_cycle_complete": True,
        }
    return evidence


def common_row(amount):
    return {
        "maker_address": MAKER, "cash_asset": deepcopy(reports.INCENTIVE_CASH_ASSET),
        "observed_at_utc": OBSERVED, "source_record_sha256": "f" * 64, "amount": amount,
    }


def add_payment(evidence, programme="maker_rebate", amount="1.250000", index=1,
                condition=CONDITION, accrued=None):
    transaction = "0x" + format(index, "064x")
    credit_id = f"137:{transaction}:0"
    evidence["accruals"].append({
        **common_row(accrued or amount), "accrual_id": f"accrual-{index}",
        "programme": programme, "condition_id": condition, "status": "ACCRUED",
        "period_start_utc": ACCRUAL_START, "period_end_utc": ACCRUAL_END,
    })
    evidence["distributions"].append({
        **common_row(amount), "distribution_id": f"distribution-{index}",
        "accrual_id": f"accrual-{index}", "programme": programme,
        "condition_id": condition, "status": "PAID", "credit_id": credit_id,
    })
    evidence["wallet_credits"].append({
        **common_row(amount), "chain_id": 137, "transaction_hash": transaction,
        "log_index": 0, "credited_at_utc": CREDIT_TIME, "status": "CONFIRMED",
    })
    return credit_id


def financial_fixture(evidence, ending="101.250000"):
    binding = {
        "maker_address": MAKER, "condition_id": CONDITION,
        "cash_asset": deepcopy(reports.INCENTIVE_CASH_ASSET),
        "cash_period": {"start_utc": ACCRUAL_START, "end_utc": CASH_END},
    }
    return {
        "run_id": "synthetic-paid-incentives", "generated_at_utc": OBSERVED,
        "target_date": "2026-09-01", "status": "FIXTURE",
        "rewards": {"paid_incentive_evidence": evidence},
        "balances": {**deepcopy(binding), "starting_cash_usdc": "100", "ending_cash_usdc": ending},
        "fees": {"actual_fee_evidence": {
            **deepcopy(binding), "status": "OBSERVED", "coverage": "all_pilot_trades_and_exits",
            "includes_taker_and_flattening_fees": True, "calculation_basis": "confirmed_trade_events",
            "fee_formula": "shares_x_rate_x_price_x_one_minus_price", "maker_fees_zero": True,
            "precision_decimal_places": 5, "confirmed_trade_set_sha256": reports.confirmed_trade_set_sha256([]),
            "observed_fill_count": 0, "paid_usdc": "0",
        }},
        "positions": [],
        "position_evidence": {
            **deepcopy(binding), "observed_at_utc": OBSERVED, "status": "OBSERVED",
            "query_scope": "exact_maker_condition", "http_status": 200,
            "response_sha256": "d" * 64, "rows": [],
            "request_url": f"https://data-api.polymarket.com/positions?user={MAKER}&market={CONDITION}"
                           "&sizeThreshold=0&limit=500&offset=0",
        },
        "redemption_status": {**deepcopy(binding), "redemption_usdc": "0", "settlement_pnl_usdc": "0"},
        "financial_identity": {
            **deepcopy(binding), "external_cash_flows_usdc": "0", "ending_positions_zero": True,
            "settlement_pnl_excludes_fees_and_incentives": True,
            "external_cash_flows_exclude_incentives": True,
            "external_cash_flow_credit_ids": list(evidence["excluded_external_credit_ids"]),
        },
    }


def financial_result(reconciliation):
    return reports.build_financial_reconciliation(reconciliation, [], [], incentive_schema_version=SELECTOR)


def test_empty_complete_queries_prove_zero_cash_in_both_programmes():
    evidence = evidence_fixture()
    result = reports.reconcile_incentive_payments(evidence)
    assert result["status"] == "COMPLETE"
    assert result["actual_maker_rebate_usdc"] == result["actual_liquidity_reward_usdc"] == 0
    assert all(row["completed_zero_from_empty_query"] for row in result["programmes"].values())
    assert result["network_reads_performed"] is False
    assert financial_result(financial_fixture(evidence, ending="100"))["complete"]


def test_below_threshold_accrual_is_unpaid_with_complete_zero_cash_window():
    evidence = evidence_fixture()
    add_payment(evidence, amount="0.400000")
    evidence["distributions"][0].update(status="PENDING", credit_id=None)
    evidence["wallet_credits"] = []
    result = reports.reconcile_incentive_payments(evidence)
    assert result["complete"]
    assert result["actual_maker_rebate_usdc"] == 0
    assert result["programmes"]["maker_rebate"]["unpaid_accrued_amount"] == "0.400000"
    assert result["accrual_states"][0]["state"] == "UNPAID"
    assert not result["accruals_fully_paid"]
    assert financial_result(financial_fixture(evidence, ending="100"))["complete"]


def test_delayed_credit_matches_retrospectively_without_amount_guessing():
    evidence = evidence_fixture()
    credit_id = add_payment(evidence)
    evidence["distributions"][0]["observed_at_utc"] = "2026-09-02T12:00:00+00:00"
    result = reports.reconcile_incentive_payments(evidence)
    assert result["complete"]
    assert result["actual_maker_rebate_usdc"] == 1.25
    assert result["matched_distributions"][0]["credit_id"] == credit_id
    assert result["record_observed_at_utcs"]["distributions"]["distribution-1"] == [
        "2026-09-02T12:00:00+00:00",
    ]
    evidence["distributions"][0]["credit_id"] = "137:0x" + "9" * 64 + ":0"
    missing = reports.reconcile_incentive_payments(evidence)
    assert missing["status"] == "UNRESOLVED"
    assert missing["actual_maker_rebate_usdc"] is None


def test_partial_payment_books_only_confirmed_cash_and_preserves_unpaid_accrual():
    evidence = evidence_fixture()
    add_payment(evidence, amount="0.400001", accrued="1.100003")
    result = reports.reconcile_incentive_payments(evidence)
    assert result["complete"]
    assert result["actual_maker_rebate_usdc"] == 0.400001
    assert result["programmes"]["maker_rebate"]["unpaid_accrued_amount"] == "0.700002"
    assert result["accrual_states"][0]["state"] == "PARTIALLY_PAID"


def test_paid_liquidity_without_fills_does_not_upgrade_live_evidence():
    evidence = evidence_fixture()
    add_payment(evidence, programme="liquidity_reward")
    reconciliation = financial_fixture(evidence)
    payload = reports.build_pilot_report_payload(reconciliation, [], [], {}, incentive_schema_version=SELECTOR)
    assert payload["schema_version"] == schema_version("mm_paid_incentive_pilot_report")
    assert payload["actual_maker_rebate_usdc"] == 0
    assert payload["actual_liquidity_reward_usdc"] == 1.25
    assert payload["financial_reconciliation_complete"]
    assert payload["financial_reconciliation"]["actual_total_pnl_after_fees_incentives_usdc"] == 1.25
    assert not payload["evidence_complete"]
    assert set(payload["missing_evidence"]) == {"live_fills", "paper_counterfactual_quotes", "markout_30m"}
    markdown = reports.render_pilot_report(payload)
    assert "Matched paid liquidity rewards (pUSD): `1.25`" in markdown
    assert reports.PUSD_COLLATERAL_PROXY_ADDRESS in markdown
    assert "no currency conversion is inferred" in markdown


@pytest.mark.parametrize("cleanup_status", ["CONFIRMED", "MATCHED", "FAILED"])
def test_both_paid_programmes_and_cleanup_fees_require_confirmed_fills(cleanup_status):
    evidence = evidence_fixture()
    add_payment(evidence, programme="maker_rebate", amount="1.250000")
    add_payment(evidence, programme="liquidity_reward", amount="0.400000", index=2)
    reconciliation = financial_fixture(evidence, ending="101.625000")
    fills = []
    for index, role, side, status in (
        (1, "MAKER", "BUY", "CONFIRMED"), (2, "TAKER", "SELL", cleanup_status),
    ):
        fills.append({
            "trade_id": f"synthetic-trade-{index}", "transaction_hash": "0x" + str(index + 2) * 64,
            "lifecycle_key": f"synthetic-order-{index}", "exchange_order_id": f"synthetic-order-{index}",
            "maker_address": MAKER, "condition_id": CONDITION, "clob_token_id": "synthetic-token",
            "liquidity_role": role, "side": side, "fill_price": "0.50", "fill_size": "2",
            "fee_rate_bps": "500", "official_trade_status": status,
            "maker_rebate_estimate_usdc": "1.25" if role == "MAKER" else "0",
        })
    # The maker leg is free; 2 * .05 * .5 * (1 - .5) = .025 pUSD for cleanup.
    reconciliation["fees"]["actual_fee_evidence"].update(
        observed_fill_count=2, paid_usdc="0.02500",
        confirmed_trade_set_sha256=reports.confirmed_trade_set_sha256(fills),
    )
    result = reports.build_financial_reconciliation(
        reconciliation, [], fills, incentive_schema_version=SELECTOR,
    )
    assert result["paid_incentive_reconciliation"]["complete"]
    assert result["actual_maker_rebate_usdc"] == 1.25
    assert result["actual_liquidity_reward_usdc"] == 0.4
    if cleanup_status == "CONFIRMED":
        assert result["complete"]
        assert result["actual_fee_reconciliation"]["complete"]
        assert result["actual_fees_usdc"] == 0.025
        assert result["native_cash_identity"]["actual_fees"] == "0.025000"
        assert result["native_cash_identity"]["balance_delta"] == "1.625000"
        assert result["native_cash_identity"]["total_pnl_after_fees_incentives"] == "1.625000"
        assert result["native_cash_identity"]["residual"] == "0.000000"
        assert result["actual_total_pnl_after_fees_incentives_usdc"] == 1.625
    else:
        assert not result["complete"]
        assert "actual_fee_confirmed_trade_scope_invalid" in result["actual_fee_reconciliation"]["blockers"]
        assert "actual_fees" in result["missing_evidence"]
        assert not result["financial_identity_inputs_verified"]
        assert result["actual_total_pnl_after_fees_incentives_usdc"] is None


def test_duplicates_are_idempotent_and_retain_hashes_and_observation_times():
    evidence = evidence_fixture()
    add_payment(evidence)
    for kind in ("accruals", "distributions", "wallet_credits"):
        repeated = deepcopy(evidence[kind][0])
        repeated["source_record_sha256"] = "7" * 64
        repeated["observed_at_utc"] = "2026-09-04T00:30:00+00:00"
        evidence[kind].append(repeated)
    before = deepcopy(evidence)
    result = reports.reconcile_incentive_payments(evidence)
    assert evidence == before
    assert result["complete"] and result["duplicate_record_count"] == 3
    assert result["actual_maker_rebate_usdc"] == 1.25
    assert result["record_provenance"]["accruals"]["accrual-1"] == ["7" * 64, "f" * 64]
    assert len(result["record_observed_at_utcs"]["accruals"]["accrual-1"]) == 2


def test_order_and_decimal_context_do_not_change_matching_or_native_amounts():
    evidence = evidence_fixture()
    add_payment(evidence, amount="0.000001")
    add_payment(evidence, amount="1.000009", index=2)
    expected = reports.reconcile_incentive_payments(evidence)
    for kind in ("accruals", "distributions", "wallet_credits"):
        evidence[kind].reverse()
    with localcontext() as context:
        context.prec = 2
        actual = reports.reconcile_incentive_payments(evidence)
    expected.pop("evidence_sha256")
    actual.pop("evidence_sha256")
    assert actual == expected
    assert actual["programmes"]["maker_rebate"]["paid_amount"] == "1.000010"


@pytest.mark.parametrize("kind", ["accruals", "distributions", "wallet_credits"])
def test_same_identity_with_conflicting_amount_is_invalid(kind):
    evidence = evidence_fixture()
    add_payment(evidence)
    repeated = deepcopy(evidence[kind][0])
    repeated["amount"] = "1.25"  # Equivalent native units are idempotent.
    evidence[kind].append(repeated)
    assert reports.reconcile_incentive_payments(evidence)["complete"]
    repeated["amount"] = "1.26"
    result = reports.reconcile_incentive_payments(evidence)
    assert result["status"] == "INVALID"
    assert result["blockers"] == [f"incentive_{kind}_duplicate_conflict"]
    assert result["actual_maker_rebate_usdc"] is None


def test_one_wallet_credit_cannot_be_claimed_by_both_programmes_or_external_flow():
    evidence = evidence_fixture()
    first_credit = add_payment(evidence)
    add_payment(evidence, programme="liquidity_reward", index=2)
    evidence["distributions"][1]["credit_id"] = first_credit
    assert reports.reconcile_incentive_payments(evidence)["blockers"] == ["incentive_credit_allocated_twice"]
    evidence = evidence_fixture()
    first_credit = add_payment(evidence)
    evidence["excluded_external_credit_ids"] = [first_credit]
    assert reports.reconcile_incentive_payments(evidence)["blockers"] == ["incentive_credit_allocated_twice"]


@pytest.mark.parametrize("condition", [None, "0x" + "c" * 64])
def test_portfolio_or_other_condition_cash_is_not_attributed_to_selected_condition(condition):
    evidence = evidence_fixture()
    add_payment(evidence, condition=condition)
    result = reports.reconcile_incentive_payments(evidence)
    assert result["status"] == "UNRESOLVED"
    assert result["actual_maker_rebate_usdc"] is None
    assert result["matched_distributions"][0]["condition_attribution"] == "UNKNOWN_FOR_REQUESTED_CONDITION"
    assert result["programmes"]["maker_rebate"]["paid_amount"] == "0.000000"


@pytest.mark.parametrize("status", ["ESTIMATED", "COMPLETED_ZERO"])
def test_estimates_and_explicit_completed_zero_remain_distinct(status):
    evidence = evidence_fixture()
    add_payment(evidence)
    evidence["distributions"] = []
    evidence["wallet_credits"] = []
    evidence["accruals"][0].update(status=status, amount="0" if status == "COMPLETED_ZERO" else "1.25")
    result = reports.reconcile_incentive_payments(evidence)
    assert result["complete"] and result["actual_maker_rebate_usdc"] == 0
    assert result["accrual_states"][0]["state"] == status
    assert bool(result["accrual_unresolved"]) == (status == "ESTIMATED")
    assert not result["programmes"]["maker_rebate"]["completed_zero_from_empty_query"]


@pytest.mark.parametrize("kind", ["accruals", "distributions", "wallet_credits"])
@pytest.mark.parametrize("flag", ["complete", "pagination_complete", "payout_cycle_complete"])
def test_partial_query_cannot_prove_zero_cash(kind, flag):
    evidence = evidence_fixture()
    evidence["sources"][kind][flag] = False
    result = reports.reconcile_incentive_payments(evidence)
    assert result["valid"] and not result["complete"]
    assert result["actual_maker_rebate_usdc"] is None
    assert f"{kind}_{flag}_not_proved" in result["unresolved"]


def test_coverage_before_closed_cash_window_is_incomplete():
    evidence = evidence_fixture()
    evidence["sources"]["wallet_credits"]["coverage_through_utc"] = ACCRUAL_END
    result = reports.reconcile_incentive_payments(evidence)
    assert result["status"] == "UNRESOLVED"
    assert "wallet_credits_period_coverage_incomplete" in result["unresolved"]


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0.0000001", "1e0", 1.25, True, None])
def test_invalid_amount_is_never_rounded_or_coerced(value):
    evidence = evidence_fixture()
    add_payment(evidence)
    evidence["wallet_credits"][0]["amount"] = value
    assert reports.reconcile_incentive_payments(evidence)["blockers"] == ["incentive_amount_invalid"]


@pytest.mark.parametrize("kind", ["accruals", "distributions", "wallet_credits"])
@pytest.mark.parametrize("status", [[], {}])
def test_nonscalar_status_fails_closed(kind, status):
    evidence = evidence_fixture()
    add_payment(evidence)
    evidence[kind][0]["status"] = status
    assert reports.reconcile_incentive_payments(evidence)["status"] == "INVALID"


@pytest.mark.parametrize("time", ["2026-09-05T00:00:00+00:00", "2026-09-03T12:00:00", "0001-01-01T00:00:00+01:00"])
def test_future_naive_and_overflowing_wallet_times_fail_closed(time):
    evidence = evidence_fixture()
    add_payment(evidence)
    evidence["wallet_credits"][0]["credited_at_utc"] = time
    assert reports.reconcile_incentive_payments(evidence)["status"] == "INVALID"


@pytest.mark.parametrize("key,value", [("symbol", "USDC"), ("chain_id", 137.0), ("decimals", 6.0),
                                      ("asset_address", "0x" + "0" * 40)])
def test_cash_asset_requires_exact_native_marker(key, value):
    evidence = evidence_fixture()
    evidence["scope"]["cash_asset"][key] = value
    assert reports.reconcile_incentive_payments(evidence)["blockers"] == ["incentive_cash_asset_invalid"]


def test_observed_account_query_scope_and_row_provenance_are_required():
    evidence = evidence_fixture()
    evidence["sources"]["accruals"]["request_scope"]["maker_address"] = "0x" + "c" * 40
    assert reports.reconcile_incentive_payments(evidence)["status"] == "INVALID"
    evidence = evidence_fixture()
    add_payment(evidence)
    evidence["wallet_credits"][0]["source_record_sha256"] = "unverified"
    assert reports.reconcile_incentive_payments(evidence)["blockers"] == ["incentive_provenance_hash_invalid"]
    evidence["wallet_credits"][0]["source_record_sha256"] = "f" * 64
    evidence["wallet_credits"][0]["maker_address"] = "0x" + "c" * 40
    assert reports.reconcile_incentive_payments(evidence)["blockers"] == ["incentive_row_account_mismatch"]


@pytest.mark.parametrize("selector", [None, "mm_exchange_adapter_v0.2", "unsupported", [], {}])
def test_new_evidence_requires_explicit_supported_selector(selector):
    reconciliation = financial_fixture(evidence_fixture(), ending="100")
    result = reports.build_financial_reconciliation(reconciliation, [], [], incentive_schema_version=selector)
    assert not result["complete"]
    assert result["actual_maker_rebate_usdc"] is None
    assert "paid_incentive_schema_selector_invalid" in result["paid_incentive_reconciliation"]["blockers"]
    assert reports.actual_reward_rebate_usdc(reconciliation["rewards"]) is None


@pytest.mark.parametrize("block", [None, {}, [], {"schema_version": "future"}])
def test_selected_new_schema_with_missing_or_malformed_evidence_cannot_fall_back(block):
    reconciliation = financial_fixture(evidence_fixture(), ending="100")
    reconciliation["rewards"]["paid_incentive_evidence"] = block
    result = financial_result(reconciliation)
    assert not result["complete"] and result["actual_maker_rebate_usdc"] is None
    del reconciliation["rewards"]["paid_incentive_evidence"]
    assert not financial_result(reconciliation)["complete"]


@pytest.mark.parametrize("component", ["financial_identity", "balances", "redemption_status", "fees", "position_evidence"])
@pytest.mark.parametrize("field", ["maker_address", "condition_id", "cash_asset", "cash_period"])
def test_every_cash_component_must_bind_exact_scope(component, field):
    evidence = evidence_fixture()
    add_payment(evidence)
    reconciliation = financial_fixture(evidence)
    target = reconciliation[component]
    if component == "fees":
        target = target["actual_fee_evidence"]
    target[field] = {"maker_address": "0x" + "c" * 40, "condition_id": "0x" + "c" * 64,
                     "cash_asset": {**reports.INCENTIVE_CASH_ASSET, "symbol": "USDC"},
                     "cash_period": {"start_utc": ACCRUAL_START, "end_utc": ACCRUAL_END}}[field]
    result = financial_result(reconciliation)
    assert not result["complete"] and not result["paid_cash_basis_verified"]
    assert result["actual_total_pnl_after_fees_incentives_usdc"] is None


def test_external_credit_exclusion_requires_cash_identity_declaration_and_cannot_hide_incentive():
    evidence = evidence_fixture()
    credit_id = add_payment(evidence)
    evidence["distributions"] = []
    evidence["accruals"] = []
    evidence["excluded_external_credit_ids"] = [credit_id]
    reconciliation = financial_fixture(evidence)
    reconciliation["financial_identity"]["external_cash_flows_usdc"] = "1.25"
    result = financial_result(reconciliation)
    assert result["complete"] and result["actual_total_pnl_after_fees_incentives_usdc"] == 0
    reconciliation["financial_identity"]["external_cash_flow_credit_ids"] = []
    assert not financial_result(reconciliation)["complete"]


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), "-Infinity"])
def test_nonfinite_balance_never_enters_cash_identity(amount):
    reconciliation = financial_fixture(evidence_fixture(), ending=amount)
    result = financial_result(reconciliation)
    assert not result["complete"] and not result["financial_identity_inputs_verified"]
    assert result["actual_total_pnl_after_fees_incentives_usdc"] is None


@pytest.mark.parametrize("observed", [ACCRUAL_END, "2026-09-04T02:00:00+00:00", None])
def test_historical_future_or_undated_empty_position_query_cannot_close_cash_window(observed):
    reconciliation = financial_fixture(evidence_fixture(), ending="100")
    reconciliation["position_evidence"]["observed_at_utc"] = observed
    result = financial_result(reconciliation)
    assert not result["complete"] and not result["paid_cash_basis_verified"]


def test_native_identity_preserves_micro_units_where_float_subtraction_loses_precision():
    reconciliation = financial_fixture(evidence_fixture(), ending="100000000000.000021")
    reconciliation["balances"]["starting_cash_usdc"] = "100000000000.000000"
    result = financial_result(reconciliation)
    assert not result["complete"]
    assert result["native_cash_identity"]["balance_delta"] == "0.000021"
    assert result["native_cash_identity"]["residual"] == "0.000021"
    assert result["actual_total_pnl_after_fees_incentives_usdc"] is None


@pytest.mark.parametrize("start,end", [("10000000000000000.000000", "10000000000000001.000000"),
                                     ("100.0000000", "100"), (100.0, "100")])
def test_out_of_contract_magnitude_precision_or_float_cash_is_rejected(start, end):
    reconciliation = financial_fixture(evidence_fixture(), ending=end)
    reconciliation["balances"]["starting_cash_usdc"] = start
    result = financial_result(reconciliation)
    assert not result["complete"] and result["native_cash_identity"] is None
    assert "paid_native_cash_identity" in result["missing_evidence"]


def test_negative_settlement_pnl_and_external_cash_are_exact_signed_native_amounts():
    reconciliation = financial_fixture(evidence_fixture(), ending="98.999999")
    reconciliation["redemption_status"]["settlement_pnl_usdc"] = "-0.000001"
    reconciliation["financial_identity"]["external_cash_flows_usdc"] = "-1"
    result = financial_result(reconciliation)
    assert result["complete"]
    assert result["native_cash_identity"]["settlement_pnl"] == "-0.000001"
    assert result["native_cash_identity"]["balance_delta"] == "-1.000001"
    assert result["native_cash_identity"]["residual"] == "0.000000"


def test_negative_one_micro_residual_keeps_its_exact_sign_and_scale():
    reconciliation = financial_fixture(evidence_fixture(), ending="99.999999")
    result = financial_result(reconciliation)
    assert result["complete"]
    assert result["financial_identity_delta_usdc"] == -0.000001
    assert result["native_cash_identity"]["residual"] == "-0.000001"


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "0.0000001", "-1"])
def test_redemption_is_validated_as_native_cash_without_counting_it_twice(amount):
    reconciliation = financial_fixture(evidence_fixture(), ending="100")
    reconciliation["redemption_status"]["redemption_usdc"] = amount
    result = financial_result(reconciliation)
    assert not result["complete"] and result["native_cash_identity"] is None


@pytest.mark.parametrize("field", ["starting_cash_usdc", "ending_cash_usdc"])
def test_native_wallet_balance_cannot_be_negative(field):
    reconciliation = financial_fixture(evidence_fixture(), ending="100")
    reconciliation["balances"][field] = "-1"
    assert financial_result(reconciliation)["native_cash_identity"] is None


@pytest.mark.parametrize("ending,complete", [("101.250010", True), ("101.250011", False)])
def test_existing_six_decimal_rounding_and_cash_residual_tolerance_are_preserved(ending, complete):
    evidence = evidence_fixture()
    add_payment(evidence)
    result = financial_result(financial_fixture(evidence, ending=ending))
    assert result["complete"] is complete
    assert result["financial_identity_delta_usdc"] == (0.000010 if complete else 0.000011)


@pytest.mark.parametrize("version", [reports.SCHEMA_VERSION, "unknown", [], {}])
def test_paid_report_cannot_be_rendered_under_legacy_or_unsupported_schema(version):
    payload = reports.build_pilot_report_payload(
        financial_fixture(evidence_fixture(), ending="100"), [], [], {}, incentive_schema_version=SELECTOR,
    )
    payload["schema_version"] = version
    with pytest.raises(ValueError):
        reports.render_pilot_report(payload)


def test_legacy_payload_retains_its_schema_and_does_not_gain_new_cash_fields():
    payload = reports.build_pilot_report_payload({}, [], [], {})
    assert payload["schema_version"] == reports.SCHEMA_VERSION
    assert "paid_incentive_reconciliation" not in payload["financial_reconciliation"]
    assert "actual_liquidity_reward_usdc" not in payload
    assert "Native cash asset" not in reports.render_pilot_report(payload)


@pytest.mark.parametrize("field", ["actual_liquidity_reward_usdc", "incentive_schema_version", "native_cash_identity"])
def test_legacy_renderer_rejects_nested_only_paid_fields(field):
    payload = reports.build_pilot_report_payload({}, [], [], {})
    payload["financial_reconciliation"][field] = None
    with pytest.raises(ValueError):
        reports.render_pilot_report(payload)


def test_new_report_schema_cannot_wrap_a_legacy_financial_result():
    payload = reports.build_pilot_report_payload({}, [], [], {})
    payload["schema_version"] = reports.PAID_INCENTIVE_PILOT_SCHEMA
    payload["cash_asset"] = deepcopy(reports.INCENTIVE_CASH_ASSET)
    payload["actual_liquidity_reward_usdc"] = 0
    with pytest.raises(ValueError):
        reports.render_pilot_report(payload)

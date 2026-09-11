from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json

import pytest

from weather.market.exchange_economics import PUSD_COLLATERAL_PROXY_ADDRESS
from weather.market.exchange_economics_sources import response_evidence
from weather.market.maker_opportunity_capture import RULE_URLS, collect, read_json, token_map, write_new_json
from weather.market.maker_opportunity_inputs import validate_packet
from weather.reporting.market.maker_opportunity_report import build_report, render_markdown


CONDITION = "0x" + "1" * 64


def sources(location="toronto", *, reward_cursor="LTE="):
    slug = f"highest-temperature-in-{location}-on-september-12-2026"
    selection = {"policy_id": "fixed-before-books", "selected": [{
        "location_id": location, "target_date": "2026-09-12", "event_slug": slug,
        "condition_id": CONDITION, "token_ids": {"YES": "2", "NO": "9"},
    }]}
    # Intentionally NO first and descending numerical token order.
    market = {"conditionId": CONDITION, "question": "Example", "outcomes": '["No", "Yes"]',
              "clobTokenIds": '["9", "2"]', "acceptingOrders": True}
    reward = {"condition_id": CONDITION, "event_slug": slug, "rewards_min_size": 20,
              "rewards_max_spread": 4.5,
              "tokens": [{"outcome": "YES", "token_id": "2"}, {"outcome": "NO", "token_id": "9"}],
              "rewards_config": [{"id": 0, "asset_address": PUSD_COLLATERAL_PROXY_ADDRESS,
                                  "start_date": "2026-09-11", "end_date": "2500-12-31",
                                  "rate_per_day": 40, "total_rewards": 0}]}
    documents = {
        RULE_URLS[0]: "posting resting limit orders; daily at midnight UTC; minimum qualifying order size; max spread; min size cutoff; Q<sub>n</sub>; single-sided",
        RULE_URLS[1]: "`min_order_size` is the minimum number of shares.\n| Tick size | Price decimals | Size decimals | Amount decimals |\n| 0.01 | 2 | 2 | 4 |",
        RULE_URLS[7]: "Chain ID: 137. pUSD CollateralToken (Proxy) " + PUSD_COLLATERAL_PROXY_ADDRESS,
    }

    def fetch_json(url, **kwargs):
        if "/events/slug/" in url:
            return {"slug": slug, "markets": [market]}
        if "/clob-markets/" in url:
            return {"t": [{"o": "NO", "t": "9"}, {"o": "YES", "t": "2"}], "mos": 5, "mts": .01, "fd": {"r": .05, "e": 1, "to": True}}
        if "/rewards/markets/" in url:
            return {"data": [reward], "count": 1, "limit": 100, "next_cursor": reward_cursor}
        yes = url.endswith("token_id=2")
        return {"market": CONDITION, "asset_id": "2" if yes else "9", "min_order_size": "5", "tick_size": ".01",
                "bids": [{"price": ".01", "size": "100"}, {"price": ".39" if yes else ".59", "size": "20"}],
                "asks": [{"price": ".99", "size": "100"}, {"price": ".41" if yes else ".61", "size": "20"}]}

    def fetch_text(url, **kwargs):
        return documents.get(url, "Document fixture only.")

    return selection, fetch_json, fetch_text


def fixture_packet(location="toronto"):
    selection, fetch_json, fetch_text = sources(location)
    return collect(selection, selection_sha256="a" * 64, fetch_json=fetch_json, fetch_text=fetch_text)


def rebind_json(record, mutate):
    raw = record["evidence"]
    value = json.loads(base64.b64decode(raw["response_body_base64"]))
    mutate(value)
    body = json.dumps(value).encode()
    replacement = response_evidence(body, url=raw["url"], http_status=200,
                                    content_type="application/json", origin=raw["response_origin"])
    replacement["retrieved_at_utc"] = raw["retrieved_at_utc"]
    record["evidence"] = replacement


@pytest.mark.parametrize("location,unit", [("toronto", "C"), ("nyc", "F")])
def test_real_input_adapter_keeps_native_identity_and_unknown_rewards(location, unit):
    packet = fixture_packet(location)
    report = build_report(packet, capture_sha256="b" * 64, require_http=False)
    assert report["status"] == "EVIDENCE_BLOCKED"
    assert report["synthetic_inputs"] is True
    assert report["live_order_authority"] is False
    assert all(report["source_qualifiers"].values())
    row = report["rows"][0]
    assert row["settlement_unit"] == unit
    assert row["token_ids"] == {"YES": "2", "NO": "9"}
    yes, no, pair = row["order_capital_diagnostics"]
    assert yes["order_feasible"] and yes["capital_feasible"]
    assert [Decimal(value) for value in yes["order_notionals"]] == [Decimal("7.80")]
    assert no["capital_feasible"] is False
    assert pair["capital_feasible"] is False
    assert yes["reward_eligible"] is False
    assert yes["own_q_min"] is None
    assert yes["blockers"]["rewards"] == ["campaign:interval_unqualified", "midpoint:missing"]
    assert all(item["conditional_reward_amount_range"] == [None, None] for item in yes["scenarios"])
    assert report["paid_rewards"] is row["paid_rewards"] is None
    assert row["realized_pnl"] is None
    assert row["configured_allocations"][0]["rate_per_day"] == 40
    assert "EVIDENCE_BLOCKED" in render_markdown(report)


def test_fixture_provenance_cannot_be_upgraded_to_public_capture():
    with pytest.raises(ValueError, match="synthetic_not_public_capture"):
        validate_packet(fixture_packet())


@pytest.mark.parametrize("mutation", ["byte_tamper", "condition_swap", "token_swap", "unknown_url", "missing_doc", "after_capture", "selection_change", "clob_minimum", "bad_count", "bool_tick", "duplicate_level"])
def test_capture_replay_rejects_corrupt_or_wrongly_bound_inputs(mutation):
    packet = fixture_packet()
    books = [record for record in packet["responses"] if record["role"] == "book_yes"]
    if mutation == "byte_tamper":
        books[0]["evidence"]["response_sha256"] = "c" * 64
    elif mutation == "condition_swap":
        rebind_json(books[0], lambda value: value.update(market="0x" + "2" * 64))
    elif mutation == "token_swap":
        rebind_json(books[0], lambda value: value.update(asset_id="9"))
    elif mutation == "unknown_url":
        books[0]["evidence"]["url"] = "https://example.com/book"
    elif mutation == "missing_doc":
        packet["responses"].pop(0)
    elif mutation == "after_capture":
        books[0]["evidence"]["retrieved_at_utc"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    elif mutation == "selection_change":
        packet["selection"]["policy_id"] = "selected-after-books"
    elif mutation == "clob_minimum":
        record = next(record for record in packet["responses"] if record["role"] == "clob_market")
        rebind_json(record, lambda value: value.update(mos=10))
    elif mutation == "bad_count":
        record = next(record for record in packet["responses"] if record["role"] == "rewards")
        rebind_json(record, lambda value: value.update(count=0))
    elif mutation == "bool_tick":
        rebind_json(books[0], lambda value: value.update(tick_size=True))
    elif mutation == "duplicate_level":
        rebind_json(books[0], lambda value: value["bids"].append(value["bids"][0]))
    with pytest.raises(ValueError):
        validate_packet(packet, require_http=False)


def test_capture_rejects_scope_before_io():
    selection, _, _ = sources()
    selection["selected"] *= 7
    def never(*args, **kwargs):
        pytest.fail("Invalid scope must not access the network")
    with pytest.raises(ValueError, match="condition_bound"):
        collect(selection, selection_sha256="a" * 64, fetch_json=never, fetch_text=never)


def test_missing_terminal_page_retains_failure_and_completed_responses():
    selection, fetch_json, fetch_text = sources(reward_cursor="cursor")
    packet = collect(selection, selection_sha256="a" * 64, fetch_json=fetch_json, fetch_text=fetch_text)
    assert packet["status"] == "INCOMPLETE"
    assert packet["errors"]
    assert len(packet["responses"]) == len(RULE_URLS) + 4
    assert not any(record["role"].startswith("book") for record in packet["responses"])
    with pytest.raises(ValueError, match="incomplete_or_wrong_mode"):
        validate_packet(packet, require_http=False)


def test_changed_unit_document_blocks_calculator_without_inference():
    packet = fixture_packet()
    record = packet["responses"][1]
    raw = record["evidence"]
    replacement = response_evidence(b"Unqualified minimum size units.", url=raw["url"],
                                    http_status=200, content_type="text/markdown", origin="caller_supplied_text")
    replacement["retrieved_at_utc"] = raw["retrieved_at_utc"]
    record["evidence"] = replacement
    report = build_report(packet, capture_sha256="b" * 64, require_http=False)
    assert report["source_qualifiers"]["clob_minimum_unit_shares"] is False
    assert report["rows"][0]["order_capital_diagnostics"] == []


def test_loss_grid_remains_hypothetical_and_keeps_zero_payment():
    report = build_report(fixture_packet(), capture_sha256="b" * 64, require_http=False)
    sensitivity = report["rows"][0]["loss_sensitivity"][0]
    assert sensitivity["hypothetical_whole_epoch_pool"] == "40"
    assert sensitivity["assumed_epoch_dates"] is None
    assert sensitivity["expected_payment"] is None
    assert sensitivity["cost_scenarios"][-1]["whole_epoch_share_to_break_even"] == "0.25"
    assert sensitivity["cost_scenarios"][-1]["zero_payment_net"] == "-10"


def test_output_never_replaces_existing_attempt(tmp_path):
    output = tmp_path / "receipt.json"
    write_new_json(output, {"retained": True})
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        write_new_json(output, {"retained": False})
    assert output.read_bytes() == original
    loaded, digest = read_json(output)
    assert loaded == {"retained": True}
    assert digest == hashlib.sha256(original).hexdigest()


def test_input_duplicate_keys_are_rejected(tmp_path):
    output = tmp_path / "receipt.json"
    output.write_text('{"status":"CAPTURED","status":"INCOMPLETE"}')
    with pytest.raises(ValueError, match="duplicate_key"):
        read_json(output)

def test_execution_imports_are_bound_to_this_checkout():
    from pathlib import Path
    from weather.market import maker_opportunity_capture, maker_opportunity_inputs
    from weather.reporting.market import maker_opportunity_report
    from weather import schema_registry_recent_data
    root = Path(__file__).resolve().parents[2]
    proof = {}
    for module in (maker_opportunity_capture, maker_opportunity_inputs, maker_opportunity_report, schema_registry_recent_data):
        path = Path(module.__file__).resolve()
        expected = root / "src" / Path(*module.__name__.split(".")).with_suffix(".py")
        assert path == expected
        proof[module.__name__] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    print(json.dumps({"import_provenance": proof}, sort_keys=True))

def test_unlisted_share_precision_is_not_inferred():
    packet = fixture_packet()
    for record in packet["responses"]:
        if record["role"] == "clob_market":
            rebind_json(record, lambda value: value.update(mts=.001))
        elif record["role"] in ("book_yes", "book_no"):
            rebind_json(record, lambda value: value.update(tick_size=".001"))
    report = build_report(packet, capture_sha256="b" * 64, require_http=False)
    assert report["rows"][0]["order_capital_diagnostics"] == []
    assert any("share_precision:selected_tick_missing_or_ambiguous" in blocker for blocker in report["rows"][0]["blockers"])


def test_token_mapping_drift_stops_before_new_token_requests():
    selection, fetch_json, fetch_text = sources()
    requests = []
    def changed(url, **kwargs):
        requests.append(url)
        value = fetch_json(url, **kwargs)
        if "/events/slug/" in url:
            value["markets"][0]["clobTokenIds"] = '["9", "3"]'
        return value
    packet = collect(selection, selection_sha256="a" * 64, fetch_json=changed, fetch_text=fetch_text)
    assert packet["status"] == "INCOMPLETE"
    assert packet["errors"][0]["message"] == "selection:token_mapping_changed"
    assert len(requests) == 1

def test_file_bound_is_enforced_before_packet_parsing(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * 65)
    with pytest.raises(ValueError, match="file_size_bound"):
        read_json(path, max_bytes=64)

def test_indented_captured_order_precision_table():
    from decimal import Decimal
    from weather.reporting.market.maker_opportunity_report import _share_increment
    # Retained public place-orders.md SHA-256 a3426c3ac3c04c96a4e988009cd6e603d22622a31e1b3c02a453ce3ac22d7563.
    table = "        | Tick size | Price decimals | Size decimals | Amount decimals |\n        | --------- | -------------: | ------------: | --------------: |\n        | `0.1`     |              1 |             2 |               3 |\n        | `0.01`    |              2 |             2 |               4 |\n        | `0.005`   |              3 |             2 |               5 |\n        | `0.0025`  |              4 |             2 |               6 |\n        | `0.001`   |              3 |             2 |               5 |\n        | `0.0001`  |              4 |             2 |               6 |"
    assert _share_increment(table, Decimal("0.01")) == Decimal(".01")
    assert _share_increment(table, Decimal("0.0025")) == Decimal(".01")
    with pytest.raises(ValueError, match="selected_tick_missing_or_ambiguous"):
        _share_increment(table + "\n        | 0.01 | 2 | 3 | 4 |", Decimal("0.01"))

def test_different_reward_asset_does_not_become_pusd_profit():
    packet = fixture_packet()
    reward = next(row for row in packet["responses"] if row["role"] == "rewards")
    other_asset = "0x" + "7" * 40
    rebind_json(reward, lambda value: value["data"][0]["rewards_config"][0].update(asset_address=other_asset))
    row = build_report(packet, capture_sha256="b" * 64, require_http=False)["rows"][0]
    assert row["reward_collateral_same_asset"] is False
    assert "cash:reward_collateral_conversion_unqualified" in row["blockers"]
    assert row["loss_sensitivity"][0]["reward_asset"].endswith(other_asset)
    assert row["order_capital_diagnostics"][0]["capital_feasible"] is True
    assert row["realized_pnl"] is None

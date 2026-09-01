from weather.market.market_registry import all_specs
from weather.operations.settlement_backfill_registry import build_payload


def test_settlement_backfill_registry_uses_canonical_complete_fleet():
    payload = build_payload()

    assert payload["contract"] == "settlement_backfill_market_registry_discovery"
    assert payload["market_ids"] == sorted(spec.id for spec in all_specs())
    assert payload["market_ids"]
    assert len(payload["market_ids"]) == len(set(payload["market_ids"]))
    assert str(payload["module_file"]).replace("\\", "/").endswith(
        "/weather/market/market_registry.py"
    )

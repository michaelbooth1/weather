from weather.operations.all_shadow_release_bootstrap import (
    _runtime_market_inventory,
    all_shadow_promotion,
)


def test_runtime_inventory_is_exact_twelve_market_native_unit_fleet():
    inventory = _runtime_market_inventory()

    assert inventory["market_count"] == 12
    assert inventory["fahrenheit_market_count"] == 11
    assert inventory["toronto_unit"] == "C"
    assert inventory["market_ids"] == sorted(inventory["market_ids"])


def test_all_shadow_promotion_has_no_promote_or_blocked_market():
    promotion = all_shadow_promotion()

    assert promotion["verdict"] == "shadow"
    assert promotion["promote_markets"] == []
    assert promotion["blocked_markets"] == []
    assert len(promotion["shadow_markets"]) == 12
    assert "toronto" in promotion["shadow_markets"]

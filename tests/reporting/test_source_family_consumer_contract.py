from unittest.mock import patch

from weather.reporting.source_gates.source_family_consumer_contract import (
    source_family_inventory_consumer_contract,
)
from tests.reporting.source_family_contract_fixtures import (
    operational_inventory,
)


def test_nonexistent_inventory_receipt_blocks_without_full_current_verifier():
    inventory = operational_inventory([])

    with patch(
        "weather.reporting.source_gates.source_family_consumer_contract."
        "source_family_inventory_current_integrity_contract"
    ) as current_verifier:
        result = source_family_inventory_consumer_contract(inventory)

    assert result["status"] == "BLOCK"
    assert result["serving_or_release_authorization"] is False
    assert (
        result["current_input_verification"][
            "serving_or_release_authorization"
        ]
        is False
    )
    assert any(
        "receipt path does not exist" in blocker
        for blocker in result["blockers"]
    )
    current_verifier.assert_not_called()


def test_existing_inventory_receipt_delegates_to_full_current_verifier(tmp_path):
    ablation = tmp_path / "source_family_ablation.json"
    ablation.write_text("{}", encoding="utf-8")
    inventory = operational_inventory([])
    inventory["ablation_input_receipt"]["path"] = str(ablation)
    expected = {
        "status": "BLOCK",
        "serving_or_release_authorization": False,
        "blockers": ["transitive current check"],
    }

    with patch(
        "weather.reporting.source_gates.source_family_consumer_contract."
        "source_family_inventory_current_integrity_contract",
        return_value=expected,
    ) as current_verifier:
        result = source_family_inventory_consumer_contract(inventory)

    assert result == expected
    current_verifier.assert_called_once_with(inventory)

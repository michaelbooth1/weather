import json
from pathlib import Path
import subprocess
import sys

from weather.market.market_registry import all_specs
from weather.operations.settlement_backfill_registry import build_payload


ROOT = Path(__file__).resolve().parents[2]


def test_settlement_backfill_registry_uses_canonical_complete_fleet():
    payload = build_payload()

    assert payload["contract"] == "settlement_backfill_market_registry_discovery"
    assert payload["market_ids"] == sorted(spec.id for spec in all_specs())
    assert payload["market_ids"]
    assert len(payload["market_ids"]) == len(set(payload["market_ids"]))
    assert str(payload["module_file"]).replace("\\", "/").endswith(
        "/weather/market/market_registry.py"
    )


def test_settlement_backfill_registry_cli_imports_current_checkout():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "weather.operations.settlement_backfill_registry",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    expected_ids = sorted(spec.id for spec in all_specs())
    module_path = Path(payload["module_file"]).resolve()
    assert payload["market_ids"] == expected_ids
    assert len(payload["market_ids"]) == 12
    assert module_path == (ROOT / "src/weather/market/market_registry.py").resolve()

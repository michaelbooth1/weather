from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ops/portable_live_sdk.ps1"


def test_portable_live_sdk_script_is_thin_offline_current_user_entrypoint():
    text = SCRIPT.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "weather.market.live_sdk_portability" in text
    assert "2044d0570d38c34057c520ab19bfcc114c751fe8c76f97091b605acc1deecd13" in text
    assert "AUTHORIZE_NON_SECRET_INTERNATIONAL_LIVE_SDK_EXPORT" in text
    assert "AUTHORIZE_NON_SECRET_INTERNATIONAL_LIVE_SDK_IMPORT" in text
    assert "-i" in lowered
    assert "$arguments.add(\"-b\")" in lowered
    assert "sys.dont_write_bytecode = true" in lowered
    assert "import is current-user-only" in lowered
    assert "drivetype]::fixed" in lowered
    assert "drivetype]::removable" in lowered
    assert "get-command python" not in lowered
    assert "invoke-webrequest" not in lowered
    assert "invoke-restmethod" not in lowered
    assert "scheduledtasks" not in lowered
    assert "register-scheduledtask" not in lowered
    assert "credential" not in lowered
    assert "clob.polymarket.com" not in lowered

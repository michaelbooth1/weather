"""Guards: B074 outer action creation time crosses the native wrapper seam."""
from datetime import datetime, timezone
import json
import os
import subprocess
import pytest

from tests.market.test_lfc_campaign_windowless import fixture, argv


@pytest.mark.spawns
@pytest.mark.skipif(os.name != 'nt', reason='Windows GUI action and process creation time')
def test_windowless_action_passes_its_native_start_to_an_inert_wrapper(tmp_path):
    marker = tmp_path/'observed-start.json'
    body = ("param([string]$ReleasePath,[string]$ReleaseSha256,[DateTimeOffset]$TaskStartedUtc)\n"
        "@{started=$TaskStartedUtc.ToString('o');observed=[DateTimeOffset]::UtcNow.ToString('o')} | "
        "ConvertTo-Json -Compress | Set-Content -LiteralPath '"+str(marker).replace("'", "''")+"'")
    pythonw, launcher, release, row = fixture(tmp_path, body)
    before = datetime.now(timezone.utc)
    child = subprocess.run(argv(pythonw, launcher, release), timeout=15)
    assert child.returncode == 0
    result = json.loads(marker.read_text())
    started, observed = (datetime.fromisoformat(result[key]) for key in ('started', 'observed'))
    assert before <= started <= observed <= datetime.now(timezone.utc)

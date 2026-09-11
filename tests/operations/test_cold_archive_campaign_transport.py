"""Native headless transport and durable controller diagnostics."""
import json
import os
from pathlib import Path
import sys
import pytest
from weather.operations import cold_archive_campaign as campaign
from weather.operations import cold_archive_campaign_io as io
from weather.operations import cold_archive_campaign_state as state

def transport(tmp_path):
    result = object.__new__(io.Transport)
    result.root = result.source = tmp_path
    result.config = {"campaign_id": "fixture"}
    (tmp_path / "scratch/ac-control/fixture").mkdir(parents=True)
    return result

@pytest.mark.skipif(os.name != "nt", reason="native Windows process")
def test_headless_file_transport_retains_output(tmp_path):
    client = transport(tmp_path)
    code, output = client.run([sys.executable, "-c", "print('terminal')"], 5)
    assert code == 0 and output.strip() == "terminal"
    logs = list((tmp_path / "scratch/ac-control/fixture/transport").glob("*.log"))
    assert len(logs) == 1 and logs[0].read_text().strip() == "terminal"

@pytest.mark.skipif(os.name != "nt", reason="native Windows process")
def test_headless_timeout_has_retained_diagnostics(tmp_path):
    client = transport(tmp_path)
    with pytest.raises(state.CampaignPaused, match="retained claim and log"):
        client.run([sys.executable, "-u", "-c", "import time; print('started'); time.sleep(20)"], .5)
    logs = list((tmp_path / "scratch/ac-control/fixture/transport").glob("*.log"))
    assert len(logs) == 1 and logs[0].read_text().strip() == "started"

def test_main_retains_startup_error_when_stdout_has_no_console(tmp_path, monkeypatch):
    config = {"production_root": str(tmp_path), "campaign_id": "fixture"}
    monkeypatch.setattr(campaign.archive, "_load", lambda *a: (config, "sha"))
    def failed(*args, **kwargs):
        raise ValueError("deliberate startup failure")
    monkeypatch.setattr(campaign, "run", failed)
    log = tmp_path / "scratch/ac-control/fixture/controller.log"
    assert campaign.main(["--config", "config", "--config-sha256", "sha", "--log-file", str(log)]) == 1
    assert json.loads(log.read_text())["reason"] == "deliberate startup failure"

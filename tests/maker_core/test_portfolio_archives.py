"""Synthetic helper envelopes; no captured accounts, files or venue calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from maker_core.contracts.portfolio import validate_campaigns
from maker_core.portfolio.ledger import build_book
from maker_core.venue.account_read import adapt_archive

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = "fixture-owner"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture
def config():
    value = json.loads((ROOT / "config/examples/portfolio_campaigns.json").read_text())
    value["account_id"] = ACCOUNT
    value["campaigns"][0].update(start_utc="2026-09-22T00:00:00Z",
        contributions=[dict(id="fixture-capital", at_utc="2026-09-22T00:00:00Z", amount_pusd="148.52")])
    return value


def activity(name, asset, side, size, price, at, fee="0"):
    return dict(id=name, proxyWallet=ACCOUNT, type="TRADE", transactionHash="fixture-" + name,
        timestamp=at, asset=asset, conditionId="condition-" + asset, side=side,
        eventSlug="mrbeast-fixture" if asset == "video" else "highest-temperature-in-" + asset,
        size=str(size), price=price, fee_pusd=fee)


def envelopes():
    chicago = dict(token_id="chicago", condition_id="condition-chicago", event_slug="highest-temperature-in-chicago",
        size="75", avg_price=".43", classification="live", bid=".43", ask=".43", redeemable=False)
    video = dict(token_id="video", condition_id="condition-video", event_slug="mrbeast-fixture",
        size="140", avg_price=".72", classification="live", bid=".72", ask=".72", redeemable=False)
    rows = [activity("miami-buy", "miami", "BUY", 75, ".35", "2026-09-23T12:00:00Z"),
            activity("miami-sell", "miami", "SELL", 75, ".18", "2026-09-24T12:00:00Z", ".55"),
            activity("chicago-buy", "chicago", "BUY", 75, ".43", "2026-09-24T13:00:00Z")]
    # The helper envelope deliberately has no embedded account or completeness.
    first = dict(kind="wallet_ledger_snapshot_v0.1", note="synthetic fixture",
        captured_at_utc="2026-09-25T17:38:00Z", reads=dict(
            summary=dict(cash_pusd="102.97", positions=[chicago], resolved_count=0),
            trades=rows, positions=dict(positions=[chicago], resolved_positions=[])))
    first["reads"]["open-orders"] = []
    second = deepcopy(first)
    second["captured_at_utc"] = "2026-09-26T12:40:00Z"
    resolved = dict(chicago, classification="resolved", terminal_price="0")
    second["reads"]["summary"] = dict(cash_pusd="2.17", positions=[video], resolved_count=1)
    second["reads"]["positions"] = dict(positions=[video], resolved_positions=[resolved])
    second["reads"]["trades"].append(activity("video-buy", "video", "BUY", 140, ".72", "2026-09-26T12:00:00Z"))
    return first, second


def test_envelope_sequence_stays_incomplete_and_all_manual(config):
    values = [adapt_archive(v, account_id=ACCOUNT) for v in envelopes()]
    book = build_book(values, config)
    assert book["status"] == "INCOMPLETE"
    assert "history_completeness_unproven" in book["reasons"]
    assert set(book["campaigns"]) == {"owner-discretionary"}
    owner = book["campaigns"]["owner-discretionary"]
    assert {lot["asset_id"] for lot in owner["open_lots"]} == {"chicago", "video"}
    assert owner["pnl_pusd"] is None and owner["bleed_limit_pusd"] is None
    assert values[1]["cash_pusd"] == "2.17" and values[1]["positions_complete"]
    assert values[1]["positions"][1]["terminal_price"] == "0"


def test_explicit_coverage_preserves_observed_manual_accounting(config):
    values = []
    for envelope in envelopes():
        envelope["reads"]["trades"] = dict(account_activity=envelope["reads"]["trades"],
            history_complete=True, history_start_utc="2026-09-22T00:00:00Z")
        values.append(adapt_archive(envelope, account_id=ACCOUNT))
    book = build_book(values, config)
    owner = book["campaigns"]["owner-discretionary"]
    assert book["status"] == "OBSERVED"
    assert float(owner["realized_pnl_pusd"]) == -45.55
    assert float(owner["cash_pusd"]) == 2.17
    assert owner["bleed_limit_reached"] is False
    assert float(book["reconciliation"]["cash_difference_pusd"]) == 0


def test_empty_recent_list_is_not_history_proof(config):
    envelope = envelopes()[0]
    envelope["reads"]["trades"] = []
    assert not adapt_archive(envelope, account_id=ACCOUNT)["history_complete"]


def test_account_never_guessed_and_conflicts_refused():
    envelope = envelopes()[0]
    with pytest.raises(ValueError, match="explicit_account"):
        adapt_archive(envelope)
    envelope["reads"]["summary"]["account_id"] = "another-account"
    with pytest.raises(ValueError, match="conflicting_account"):
        adapt_archive(envelope, account_id=ACCOUNT)


@pytest.mark.parametrize("fault", ["disabled_owner", "disabled_rule", "disabled_override", "start", "capital", "enabled"])
def test_disabled_campaign_guards(config, fault):
    if fault == "disabled_owner":
        config["campaigns"][0] = dict(id="owner-discretionary", enabled=False)
    elif fault == "disabled_rule":
        config["rules"] = [dict(event_slug_prefix="highest-temperature", campaign="weather-maker")]
    elif fault == "disabled_override":
        config["lot_overrides"] = [dict(transaction_hash="tx", campaign="youtube-maker")]
    elif fault == "start":
        config["campaigns"][1]["start_utc"] = "2026-09-26T00:00:00Z"
    elif fault == "capital":
        config["campaigns"][1]["contributions"] = []
    else:
        config["campaigns"][1]["enabled"] = "false"
    with pytest.raises(ValueError):
        validate_campaigns(config)


@pytest.mark.parametrize("identity_source", ["config", "cli", "missing", "conflict"])
def test_module_cli_exact_envelope(tmp_path, config, identity_source):
    source = tmp_path / "inputs"
    source.mkdir()
    for i, envelope in enumerate(envelopes()):
        (source / f"{i}.json").write_text(json.dumps(envelope))
    originals = {p.name: p.read_bytes() for p in source.iterdir()}
    extra = []
    if identity_source != "config":
        config.pop("account_id")
    if identity_source in {"cli", "conflict"}:
        extra = ["--account-id", ACCOUNT]
    if identity_source == "conflict":
        config["account_id"] = "other"
    cfg = tmp_path / "campaigns.json"
    cfg.write_text(json.dumps(config))
    out = tmp_path / "out"
    run = subprocess.run([sys.executable, "-B", "-m", "maker_core.portfolio", "report",
        "--snapshots", str(source), "--campaigns", str(cfg), "--out", str(out), *extra],
        env=dict(os.environ, PYTHONPATH=str(ROOT / "src")), cwd=tmp_path,
        capture_output=True, text=True, timeout=30)
    assert run.returncode == (1 if identity_source in {"missing", "conflict"} else 2), run.stdout + run.stderr
    if run.returncode == 2:
        result = json.loads(run.stdout)
        assert result["status"] == "INCOMPLETE"
        assert "history_completeness_unproven" in result["reasons"]
        assert len(list(out.glob("*.json"))) == 1
    else:
        assert not out.exists()
    assert {p.name: p.read_bytes() for p in source.iterdir()} == originals

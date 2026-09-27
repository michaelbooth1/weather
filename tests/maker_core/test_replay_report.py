from datetime import date, timedelta
import json
import pytest

from maker_core.evidence.journal import plain
from maker_core.replay import authorization
from maker_core.replay.__main__ import main
from maker_core.replay.engine import ReplayConfig
from maker_core.replay.report import comparison_report, report_bytes
from .fixtures.replay_scenario import Scenario
from .fixtures.replay_authorization import sign_fixture


def panel(tmp_path):
    bundles = []
    for i in range(3):
        s = Scenario(day=date(2020, 1, 1)+timedelta(days=i), minutes=3)
        for market in s.markets:
            for minute in range(3):
                s.book(market, minute*60)
            s.trade(market, 30)
            s.settle(market, 170, p=i % 2)
        bundles.append(s.bundle(tmp_path/str(i)))
    return bundles


def test_dual_bound_three_day_report_is_byte_deterministic(tmp_path):
    bundles = panel(tmp_path)
    config = ReplayConfig(hazard_per_minute=0)
    a = comparison_report(bundles, config, replicates=100)
    b = comparison_report(reversed(bundles), config, replicates=100)
    assert report_bytes(a) == report_bytes(b)
    assert list(a["bounds"]) == ["strictly_through", "at_price"]
    assert a["parity"]["status"] == "FULL_SESSION_NOT_QUALIFIED"
    for bound in a["bounds"].values():
        assert "pull_efficiency" in bound
        assert set(bound["scores"]) == set(authorization.POLICIES)
        assert all(e["status"] == "UNDERPOWERED" for c in bound["intervals"].values()
                   for e in (c.get("intervals") or {}).values())
    assert b"strictly_through" in report_bytes(a)[1] and b"at_price" in report_bytes(a)[1]


@pytest.mark.parametrize("flags", [[], ["--pre-registration", "missing"],
                         ["--pre-registration", "missing", "--pre-registration-sha256", "0"*64]])
def test_cli_cannot_self_approve_or_read_bundle_first(monkeypatch, flags):
    import maker_core.replay.__main__ as cli
    monkeypatch.setattr(cli, "load_bundle", lambda *a, **k: pytest.fail("unauthorized bundle read"))
    with pytest.raises(SystemExit) as exc:
        main(["run", "--bundle", "missing", "--out", "missing", "--compare", *flags])
    assert exc.value.code == 2


def test_pinned_fixture_registration_binds_scope_and_diagnostic_stays_default(tmp_path, monkeypatch):
    bundles = panel(tmp_path)
    config = ReplayConfig(hazard_per_minute=0)
    doc = dict(owner="FICTIONAL TEST OWNER", signed_at="2019-12-31T00:00:00Z",
        hurdles={"fixture_only": True}, clusters=["date", "date_x_market"], policies=list(authorization.POLICIES),
        dates=[b.day.isoformat() for b in bundles], markets=["a", "b"], replay_config=plain(config),
        bootstrap_replicates=100, bootstrap_seed=20260926, metrics=["modeled_net_k1", "modeled_net_k05"])
    path, key, paths = sign_fixture(tmp_path, doc, monkeypatch)
    raw = path.read_bytes()
    args = ["run", "--out", str(tmp_path/"out"), "--compare", "--hazard-per-minute", "0",
            "--bootstrap-replicates", "100", "--pre-registration", str(path), "--pre-registration-sha256", key]
    for name, value in paths.items():
        args += ["--" + name.replace("_", "-"), str(value)]
    for i in range(3):
        args += ["--bundle", str(tmp_path/str(i))]
    assert main(args) == 0
    report = json.loads((tmp_path/"out/report.json").read_bytes())
    assert report["pre_registration_sha256"] == key
    assert main(["run", "--bundle", str(tmp_path/"0"), "--out", str(tmp_path/"diagnostic")]) == 0
    diagnostic = json.loads((tmp_path/"diagnostic/report.json").read_bytes())
    assert diagnostic["mode"] == "diagnostic-only" and "bounds" not in diagnostic
    args[args.index("--out")+1] = str(tmp_path/"bad")
    args += ["--initial-cash", "99"]
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2 and not (tmp_path/"bad").exists()
    path.write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="hash_mismatch"):
        authorization.read_authorization(path, key)

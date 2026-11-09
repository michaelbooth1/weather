"""Guards: WP-05 lazy F3 routing, F2 policy provenance and create-only output."""

import ast
from dataclasses import make_dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather.backtesting import f3_cli


def test_missing_engine(monkeypatch, capsys):
    monkeypatch.setattr(f3_cli.util, "find_spec", lambda name: None)
    assert f3_cli.main(["simulate", "--help"]) == 4
    assert "engine module not present on this branch: weather.backtesting.f3_sim" in capsys.readouterr().out


@pytest.mark.parametrize("command", f3_cli.ROUTES)
@pytest.mark.parametrize("exit_code", [0, 1, 2, 3, 4])
def test_routes_pass_command_arguments_and_exit(monkeypatch, command, exit_code):
    calls = []
    monkeypatch.setattr(f3_cli.util, "find_spec", lambda name: object())

    def load(name):
        assert name == f3_cli.ROUTES[command][0]
        return SimpleNamespace(cli_main=lambda argv: calls.append(argv) or exit_code)

    monkeypatch.setattr(f3_cli, "import_module", load)
    assert f3_cli.main([command, "--x", "1"]) == exit_code
    assert calls == [[command, "--x", "1"]]


def test_no_eager_engine_imports():
    tree = ast.parse(Path(f3_cli.__file__).read_text(encoding="utf-8"))
    imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(name.startswith(("weather.backtesting.f3", "weather.market.f3", "weather.scoring.response_envelope")) for name in imports)


@pytest.mark.parametrize("basis", ["gross", "net_of_retained_gains"])
def test_policy_from_f2_and_create_only(monkeypatch, tmp_path, capsys, basis):
    # Synthetic economic fields of ef3882d25's campaign example; translation
    # belongs to WP-01. No campaign records or example defaults are imported.
    policy = {
        "quote_offset_pusd": "0.025", "sleeve_loss_basis": basis,
        "shares_per_leg": "20", "tick_pusd": "0.01",
        "per_order_cap_pusd": "15.80", "per_band_cap_pusd": "19.60",
        "per_band_daily_filled_cap_pusd": "40", "fill_cooldown_seconds": 60,
    }
    receipt = tmp_path / "freeze.json"
    raw = json.dumps({"policy": policy, "unrelated": "must not be exported"}).encode()
    receipt.write_bytes(raw)
    out = tmp_path / "candidate.json"
    params_type = make_dataclass("F3Params", ["quote_offset_pusd", "sleeve_loss_basis", "f2_source"])

    def translate(value, *, f2_git_sha, f2_policy_sha256):
        assert value == policy
        assert f2_git_sha == "a" * 40
        expected = (json.dumps(policy, sort_keys=True, separators=(",", ":")) + "\n").encode()
        assert f2_policy_sha256 == sha256(expected).hexdigest()
        return params_type(Decimal(value["quote_offset_pusd"]), value["sleeve_loss_basis"],
                           {"git_sha": f2_git_sha, "policy_sha256": f2_policy_sha256})

    monkeypatch.setattr(f3_cli.util, "find_spec", lambda name: object())
    monkeypatch.setattr(f3_cli, "import_module", lambda name: SimpleNamespace(params_from_f2_policy=translate))
    args = ["policy-from-f2", "--f2-freeze", str(receipt), "--f2-git-sha", "A" * 40, "--out", str(out)]
    assert f3_cli.main(args) == 0
    written = out.read_bytes()
    result = json.loads(written)
    assert result["quote_offset_pusd"] == "0.025"
    assert result["sleeve_loss_basis"] == basis
    assert result["f2_source"]["freeze_receipt_sha256"] == sha256(raw).hexdigest()
    assert "unrelated" not in result
    expected_sha = sha256(written.rstrip(b"\n")).hexdigest()
    assert f"policy_sha256: {expected_sha}" in capsys.readouterr().out
    assert f3_cli.main(args) == 3
    assert out.read_bytes() == written


def test_invalid_sha_does_not_open_input(tmp_path, capsys):
    assert f3_cli.main(["policy-from-f2", "--f2-freeze", str(tmp_path / "absent"),
                        "--f2-git-sha", "bad", "--out", str(tmp_path / "out")]) == 4
    assert "expected 40 hex" in capsys.readouterr().out


def test_bad_receipt_is_not_echoed(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(f3_cli.util, "find_spec", lambda name: object())
    source = tmp_path / "bad.json"
    source.write_text('{"policy": "private-content"}', encoding="utf-8")
    assert f3_cli.main(["policy-from-f2", "--f2-freeze", str(source),
                        "--f2-git-sha", "a" * 40, "--out", str(tmp_path / "out")]) == 4
    assert "private-content" not in capsys.readouterr().out


def test_changed_policy_hash_refuses_before_translation(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(f3_cli.util, "find_spec", lambda name: object())
    monkeypatch.setattr(f3_cli, "import_module", lambda name: pytest.fail("must not translate mismatched receipt"))
    source = tmp_path / "freeze.json"
    source.write_text(json.dumps({"policy": {"quote_offset_pusd": "0.025"}, "policy_sha256": "0" * 64}), encoding="utf-8")
    out = tmp_path / "candidate.json"
    assert f3_cli.main(["policy-from-f2", "--f2-freeze", str(source), "--f2-git-sha", "a" * 40, "--out", str(out)]) == 3
    assert "F2 policy hash mismatch" in capsys.readouterr().out
    assert not out.exists()

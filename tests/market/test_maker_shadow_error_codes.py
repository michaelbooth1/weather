"""Shadow G9 paths carry enumerated error codes, never ``str(error)``.

Spec: D-shadow-gate-spec-v3.1 §4.8 rule 2 and G9 (``maker_shadow.py:151`` and ``:292`` @ ``b31185d6b``);
v3.2 §5.1 ("G9's two shadow paths ... which **are** converted"); v3.2 §5.3 (run-time tokens only).
Tokens are generated at run time with ``secrets.token_hex``; no literal token value is in this file.
"""
import ast
import json
from pathlib import Path
import secrets as std_secrets
import socket

import pytest

from maker_core.shadow import secrets as shadow_secrets
from weather.market import maker_shadow

SOURCE = Path(maker_shadow.__file__)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("shadow test attempted network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class _Feed:
    def __init__(self, event):
        self.event = event

    def events(self, slugs):
        return [dict(self.event, slug=slug) for slug in slugs]


def _event(market):
    return {"id": "77", "negRisk": True, "markets": [market]}


def _market():
    return {"conditionId": "0x" + "a" * 64, "active": True, "closed": False, "enableOrderBook": True,
            "clobTokenIds": json.dumps(["1", "2"]), "outcomes": json.dumps(["Yes", "No"]),
            "endDate": "2026-09-30T16:00:00Z", "bestBid": 0.49, "bestAsk": 0.51,
            "clobRewards": [{"rewardsDailyRate": 100}]}


def _no_token(text, token):
    blob = text.encode() if isinstance(text, str) else text
    assert token not in text
    assert shadow_secrets.scan(blob, shadow_secrets.TokenSet([token])) == []


def test_discovery_refusal_reason_is_enumerated_not_str_error(monkeypatch):
    """G9 :151 path: a lower-case ValueError carrying a token never reaches the universe record."""
    token = std_secrets.token_hex(16)

    def leaky(market):
        raise ValueError(f"reward fetch failed https://api.example.invalid/v1?apikey={token}")

    monkeypatch.setattr(maker_shadow, "_rewarded", leaky)
    spec = next(s for s in maker_shadow.all_specs() if s.id == "nyc")
    from datetime import datetime, timezone
    _, record = maker_shadow.discover(_Feed(_event(_market())), [spec], datetime(2026, 9, 28, 12, tzinfo=timezone.utc),
                                      horizons=[1], max_conditions=4)
    _no_token(json.dumps(record), token)
    assert record["refused"] == {"ValueError": 1}


def test_discovery_known_refusal_codes_are_kept(monkeypatch):
    spec = next(s for s in maker_shadow.all_specs() if s.id == "nyc")
    from datetime import datetime, timezone
    market = dict(_market(), closed=True)
    _, record = maker_shadow.discover(_Feed(_event(market)), [spec], datetime(2026, 9, 28, 12, tzinfo=timezone.utc),
                                      horizons=[1], max_conditions=4)
    assert record["refused"] == {"not_open": 1}


def test_cli_refusal_is_enumerated_not_str_error(monkeypatch, capsys):
    """G9 :292 path: the CLI prints an enumerated code, never the exception text."""
    token = std_secrets.token_hex(16)

    def leaky(args):
        raise ValueError(f"page fetch failed apiKey={token}")

    monkeypatch.setattr(maker_shadow, "run", leaky)
    assert maker_shadow.main(["run", "--config", "unused.json"]) == 2
    err = capsys.readouterr().err
    _no_token(err, token)
    assert json.loads(err) == {"refused": "unclassified:ValueError"}


def test_cli_known_refusal_code_is_kept(monkeypatch, capsys):
    def known(args):
        raise ValueError("stop_file_present_at_start")

    monkeypatch.setattr(maker_shadow, "run", known)
    assert maker_shadow.main(["run", "--config", "unused.json"]) == 2
    assert json.loads(capsys.readouterr().err) == {"refused": "stop_file_present_at_start"}


def _literal_codes(tree):
    codes = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
        if name == "_refuse" and len(node.args) == 2 and isinstance(node.args[1], ast.Constant):
            codes.add(node.args[1].value)
        if name == "ValueError" and node.args and isinstance(node.args[0], ast.Constant):
            codes.add(node.args[0].value)
    return codes


def test_every_literal_refusal_code_is_enumerated():
    """Ratchet: a new ``_refuse``/``ValueError`` literal must be added to the closed set, or it prints as unclassified."""
    codes = _literal_codes(ast.parse(SOURCE.read_text(encoding="utf-8")))
    assert codes, "ratchet is vacuous"
    assert codes <= set(maker_shadow.REFUSAL_CODES)
    assert all(code.replace("_", "").isalpha() and code.islower() for code in maker_shadow.REFUSAL_CODES)


def test_no_str_error_left_in_shadow_cli():
    """Mutant guard: re-introducing ``str(error)``/``str(exc)``/``repr(...)`` of an exception fails this ratchet."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    handlers = {h.name for h in ast.walk(tree) if isinstance(h, ast.ExceptHandler) and h.name}
    offenders = [node.lineno for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id in {"str", "repr", "format"} and node.args
                 and isinstance(node.args[0], ast.Name) and node.args[0].id in handlers]
    assert offenders == []


@pytest.fixture
def http_loggers():
    import logging
    saved = {n: logging.getLogger(n).level for n in shadow_secrets.PINNED_LOGGERS}
    yield logging
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def test_mt4_shadow_refuses_to_start_with_unpinned_debug_logger(monkeypatch, http_loggers, tmp_path):
    """MT4 (v3.2 §5.3; v3.1 §4.8 rule 5): ``urllib3`` left at DEBUG in the shadow -> the process refuses to start,
    before any config, fixture or tape is touched. The mutant is the pin step skipped."""
    monkeypatch.setattr(shadow_secrets, "pin_http_loggers", lambda: None)
    http_loggers.getLogger("urllib3").setLevel(http_loggers.DEBUG)
    with pytest.raises(shadow_secrets.HygieneRefusal) as refused:
        maker_shadow.main(["run", "--config", str(tmp_path / "missing.json"), "--output-root", str(tmp_path / "t")])
    assert refused.value.reason == "http_logger_verbose" and not (tmp_path / "t").exists()


def test_shadow_run_pins_http_loggers_at_start(http_loggers, tmp_path):
    http_loggers.getLogger("urllib3").setLevel(http_loggers.DEBUG)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    assert maker_shadow.main(["run", "--config", str(tmp_path / "config.json")]) == 2  # config refusal, after pins
    assert all(not http_loggers.getLogger(n).isEnabledFor(http_loggers.INFO) for n in shadow_secrets.PINNED_LOGGERS)

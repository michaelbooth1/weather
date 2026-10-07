"""``maker_core.shadow.secrets``: token set, scanner, redaction, enumerated codes, sealed writer, pins and hooks.

Spec: D-shadow-gate-spec-v3.1 §4.8 rules 1-6 (OD15 condition, CONSOLIDATED §5), amended by v3.2 §5.2 (patterns,
scan-before-write, transfer fails closed) and v3.2 §5.3 (MT1, MT1b, MT2, MT3, MT4, MT5, MT6).

Every token is generated at run time with ``secrets.token_hex(16)`` (v3.2 §5.3) and every page, URL, row and
exception is assembled in memory. No literal token value is in this file, so the repository ratchet
(``test_no_wu_token_in_repo.py``) holds without an allowlist. Outputs go under ``tmp_path`` (the queue's basetemp).
No network: page fetches are stubs.
"""
import http.client
import io
import json
import logging
import pickle
import secrets as std_secrets
import sys
import threading
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import quote, quote_plus

import pytest

from maker_core.evidence.journal import Journal
from maker_core.shadow import secrets as S

NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)


def tok():
    return std_secrets.token_hex(16)


def ids(data, tokens=None, **kw):
    return {hit.pattern_id for hit in S.scan(data, tokens, **kw)}


# -- token set ------------------------------------------------------------------------------------------------------
def test_token_set_never_exposes_values():
    token = tok()
    tokens = S.TokenSet([token])
    assert token not in repr(tokens) and token not in str(tokens) and len(tokens) == 1
    with pytest.raises(TypeError):
        pickle.dumps(tokens)
    with pytest.raises(TypeError):
        iter(tokens)
    with pytest.raises(ValueError) as short:
        S.TokenSet(["abc"])
    assert "abc" not in str(short.value)


def test_exact_token_found_in_every_encoding():
    token = tok() + "/+ &\"<"  # non-alnum suffix so every encoding differs from the raw form
    tokens = S.TokenSet([token])
    forms = [token, quote(token), quote_plus(token), quote(quote(token)), json.dumps(token)[1:-1],
             __import__("html").escape(token), quote(token).lower()]
    for form in forms:
        assert any(i.startswith("exact_token") for i in ids(("x " + form + " y").encode(), tokens)), form


# -- structural patterns (v3.2 §5.2) -----------------------------------------------------------------------------
@pytest.mark.parametrize("template", [
    "https://api.example.invalid/v1/x.json?apiKey={t}&units=e",
    "apikey={t}", "API_KEY = '{t}'", "api-key: {t}", "api_key:{t}",
    "{{'apiKey': '{t}', 'units': 'e'}}", '{{"apiKey": "{t}"}}', '"API_KEY":"{t}"',
    "apiKey%3D{t}", "apiKey%3d{t}", "apiKey%3A{t}", "apiKey%253D{t}", "apiKey%253a{t}",
    '\\"apiKey\\":\\"{t}\\"', "&quot;API_KEY&quot;:&quot;{t}", "&#34;apiKey&#34;:&#34;{t}", "&q;API_KEY&q;:&q;{t}",
])
def test_structural_patterns_hit_without_the_exact_token(template):
    assert "apikey_value" in ids(template.format(t=tok()).encode())


def test_hex32_near_apikey_pattern():
    assert "hex32_near_apikey" in ids(f"apiKey is set (len 32) value {tok()}".encode())


@pytest.mark.parametrize("text", [
    "apiKey=<redacted>", "apiKey=<page-token>", "api_key=None", "apiKey={token}", "api_key_sha256: " + "a" * 64,
    "apiKey=short123", "the api key is configured", "PUBLIC_WU_ACCESS_PARAM = \"apiKey\"",
])
def test_value_shape_rule_has_no_false_hits_on_placeholders(text):
    assert ids(text.encode()) == set()


def test_scan_reports_ids_and_offsets_never_bytes():
    token = tok()
    hits = S.scan(f"..apiKey={token}".encode(), S.TokenSet([token]))
    assert hits and all(set(vars(h)) == {"pattern_id", "offset"} for h in hits)
    assert all(token not in h.pattern_id for h in hits)


# -- redaction helpers ---------------------------------------------------------------------------------------------
def test_redaction_removes_exact_and_structural_values():
    token, other = tok(), tok()
    tokens = S.TokenSet([token])
    text = f"GET /v1?apiKey={other}&x=1 then raw {token} and {quote(token)}"
    clean = S.redact_text(text, tokens)
    assert token not in clean and other not in clean and "apiKey=<redacted>&x=1" in clean
    assert S.scan(clean.encode(), tokens) == []


# -- enumerated error codes (v3.1 §4.8 rule 2) -----------------------------------------------------------------------
def test_error_codes_are_enumerated_and_never_carry_text():
    token = tok()
    url = f"https://api.example.invalid/v1?apiKey={token}"
    cases = {
        ("api", HTTPError(url, 403, "Forbidden", {}, None)): "api_token_rejected",
        ("api", HTTPError(url, 500, "err", {}, None)): "api_http_500",
        ("page", HTTPError(url, 404, "nf", {}, None)): "page_http_404",
        ("page", HTTPError(url, 429, "slow", {}, None)): "rate_limited",
        ("api", TimeoutError(url)): "api_timeout",
        ("page", ConnectionResetError(url)): "page_connection_error",
        ("api", json.JSONDecodeError(url, "doc", 0)): "api_json_invalid",
        ("api", ValueError(url)): "unclassified:ValueError",
        ("api", type("WeirdError", (Exception,), {})(url)): "unclassified:other",
        ("page", S.TokenFetchFailed("page_token_not_found")): "page_token_not_found",
    }
    for (channel, exc), expected in cases.items():
        code = S.error_code(exc, channel=channel)
        assert code == expected and S.is_enumerated_code(code) and token not in code
    assert not S.is_enumerated_code("unclassified:" + token)
    assert S.TokenFetchFailed(token).code == "unclassified:other"


# -- sealed writer, scan before write (v3.2 §5.2) -------------------------------------------------------------------
def test_sealed_writer_writes_clean_bytes_atomically(tmp_path):
    writer = S.SealedWriter(S.TokenSet([tok()]))
    path = tmp_path / "out" / "receipt.json"
    sha = writer.write_new(path, b'{"ok":true}\n', path_class="receipt")
    assert path.read_bytes() == b'{"ok":true}\n' and len(sha) == 64 and writer.outputs_scanned == 1
    assert not list(tmp_path.rglob("*" + S.TEMP_SUFFIX))
    with pytest.raises(FileExistsError):
        writer.write_new(path, b"{}", path_class="receipt")


def test_mt1_page_body_with_token_refused_before_any_byte(tmp_path):
    """MT1: a page body carrying "API_KEY":"<run-time token>" handed to the input-store writer."""
    token = tok()
    body = f'<html><script>const data = {{"API_KEY":"{token}"}};</script></html>'.encode()
    writer = S.SealedWriter(S.TokenSet([token]))
    with pytest.raises(S.SecretInOutput) as refused:
        writer.write_new(tmp_path / "store" / "wu.json", body, path_class=S.INPUT_STORE)
    assert refused.value.reason == "secret_in_output" and "apikey_value" in refused.value.pattern_ids
    assert token not in str(refused.value) and not (tmp_path / "store").exists()


def test_mt1b_page_body_without_token_refused_by_sniff(tmp_path):
    """MT1b: the page_token_not_found case; rule 1 holds even without a token."""
    body = b"<!DOCTYPE html><html><body>history page, token block missing</body></html>"
    writer = S.SealedWriter(S.TokenSet())
    with pytest.raises(S.SecretInOutput) as refused:
        writer.write_new(tmp_path / "wu.json", body, path_class=S.INPUT_STORE)
    assert refused.value.pattern_ids == (S.PAGE_BODY_ID,) and not list(tmp_path.iterdir())
    # The sniff is scoped to the input store; an API JSON body passes.
    writer.write_new(tmp_path / "api.json", b'{"observations":[{"temp":71}]}', path_class=S.INPUT_STORE)


def test_mt2_input_gap_row_from_str_http_error_refused_at_seal(tmp_path):
    """MT2: an ``input_gap`` row built from ``str(HTTPError)`` whose URL holds the token."""
    token = tok()
    error = HTTPError(f"https://api.example.invalid/v1/obs.json?apiKey={token}&units=e", 500, "x", {}, None)
    row = {"event": "input_gap", "source": "wu", "error": f"{error} {error.url}"}  # the forbidden pattern
    line = (json.dumps(row) + "\n").encode()
    writer = S.SealedWriter(S.TokenSet([token]))
    tape = tmp_path / "day.tape.jsonl"
    with pytest.raises(S.SecretInOutput) as refused:
        writer.append(tape, line, path_class="tape")
    assert {"apikey_value", "exact_token:raw"} <= set(refused.value.pattern_ids) and not tape.exists()
    # The enumerated row passes; the whole file is re-scanned at seal.
    writer.append(tape, (json.dumps({**row, "error": S.error_code(error, channel="api")}) + "\n").encode(),
                  path_class="tape")
    assert len(writer.seal_check(tape, path_class="tape")) == 64
    with tape.open("ab") as handle:  # a token appended behind the writer's back is caught at seal
        handle.write(token.encode())
    with pytest.raises(S.SecretInOutput):
        writer.seal_check(tape, path_class="tape")


def test_scanning_guard_refuses_journal_row_before_append(tmp_path):
    token = tok()
    guard = S.ScanningGuard(S.SealedWriter(S.TokenSet([token])), "tape")
    path = tmp_path / "t.jsonl"
    journal = Journal(path, clock=lambda: NOW, scope={"run": "x"}, guard=guard)
    size = path.stat().st_size
    with pytest.raises(S.SecretInOutput):
        journal.record("minute", note=f"url ?apiKey={token}")
    journal.close()
    assert path.stat().st_size == size and token.encode() not in path.read_bytes()


# -- transfer scan, both ends, fails closed (v3.1 §4.8 rule 4; v3.2 §5.2; MT3) ----------------------------------------
def _package(token):
    trigger_row = json.dumps({"market": "fictional", "previous_observation": {"error": f"x?apiKey={token}"}})
    return {"trigger_rows.jsonl": trigger_row.encode(), "bundle.json": b'{"day":"2026-09-28"}'}


def test_mt3_each_transfer_end_refuses_independently():
    """MT3: one run with the send end alone, one with the receive end alone; each refuses on its own."""
    token = tok()
    package = _package(token)
    for end in ("send", "receive"):
        result = S.scan_package(package, end=end, fetch_exact_token=lambda: token)
        assert result.status == "refused" and result.reason == "secret_in_output"
        assert {pid for _, pid in result.hits} >= {"apikey_value", "exact_token:raw"}
        assert token not in repr(result)
    # Exact-token-only plant (no structural shape): only the exact scan sees it.
    bare = {"rows.jsonl": json.dumps({"note": token}).encode()}
    assert S.scan_package(bare, end="receive", fetch_exact_token=lambda: token).status == "refused"


def test_transfer_fails_closed_when_exact_token_unavailable():
    def fail():
        raise S.TokenFetchFailed("page_http_503")

    clean = {"bundle.json": b'{"day":"2026-09-28"}'}
    deferred = S.scan_package(clean, end="send", fetch_exact_token=fail)
    assert (deferred.status, deferred.reason, deferred.failure_code) == ("deferred", S.TRANSFER_DEFERRED,
                                                                       "page_http_503")
    assert S.scan_package(clean, end="send", fetch_exact_token=lambda: (_ for _ in ()).throw(TimeoutError("x"))
                          ).failure_code == "page_timeout"
    # A structural hit still refuses without the exact token.
    assert S.scan_package(_package(tok()), end="receive", fetch_exact_token=fail).status == "refused"
    assert S.scan_package(clean, end="receive", fetch_exact_token=tok).status == "clean"


# -- logger pins and pre-fetch checks (MT4, MT6) ----------------------------------------------------------------------
@pytest.fixture
def http_state():
    saved = {n: logging.getLogger(n).level for n in S.PINNED_LOGGERS}
    levels = (http.client.HTTPConnection.debuglevel, http.client.HTTPSConnection.debuglevel)
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)
    http.client.HTTPConnection.debuglevel, http.client.HTTPSConnection.debuglevel = levels


def test_mt4_unpinned_debug_logger_refuses_start(http_state):
    """MT4: ``urllib3`` left at DEBUG -> the process refuses to start; pinning fixes it."""
    for name in S.PINNED_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG)
        with pytest.raises(S.HygieneRefusal) as refused:
            S.check_http_hygiene()
        assert refused.value.reason == "http_logger_verbose" and isinstance(refused.value, SystemExit)
        S.enforce_http_logger_pins()
    assert all(logging.getLogger(n).getEffectiveLevel() >= logging.WARNING for n in S.PINNED_LOGGERS)


@pytest.mark.parametrize("cls", [http.client.HTTPConnection, http.client.HTTPSConnection])
def test_mt6_debuglevel_set_after_start_refuses_before_fetch(http_state, cls):
    """MT6: ``debuglevel = 1`` set after start prints via ``print``; the check before every fetch refuses."""
    S.enforce_http_logger_pins()
    calls = []
    assert S.guarded_fetch(lambda: calls.append(1) or "ok") == "ok"
    cls.debuglevel = 1
    with pytest.raises(S.HygieneRefusal) as refused:
        S.guarded_fetch(lambda: calls.append(2))
    assert refused.value.reason == "http_debuglevel_enabled" and calls == [1]
    with pytest.raises(SystemExit):  # a broad ``except Exception`` in a fetch loop cannot swallow it
        try:
            S.guarded_fetch(lambda: None)
        except Exception:
            pytest.fail("refusal was an Exception")


# -- exception hooks (MT5) -------------------------------------------------------------------------------------------
def _raise_http_error(token):
    raise HTTPError(f"https://api.example.invalid/v1?apiKey={token}", 401, "denied", {}, None)


def test_mt5_uncaught_http_error_reaches_hooks_without_token():
    """MT5: an uncaught ``HTTPError`` whose URL holds the token, through ``sys`` and ``threading`` excepthooks."""
    token = tok()
    tokens = S.TokenSet([token])
    stream = io.StringIO()
    previous = S.install_exception_hooks(tokens, stream=stream)
    try:
        try:
            _raise_http_error(token)
        except HTTPError:
            sys.excepthook(*sys.exc_info())
        worker = threading.Thread(target=_raise_http_error, args=(token,))
        worker.start()
        worker.join()
    finally:
        S.restore_exception_hooks(previous)
    out = stream.getvalue()
    assert out.count("Uncaught HTTPError code=api_token_rejected") == 2
    assert token not in out and "apiKey" not in out and "denied" not in out
    assert S.scan(out.encode(), tokens) == []
    frames = [line for line in out.splitlines() if line.startswith("  at ")]
    assert frames and all(line.rsplit(":", 1)[1].isdigit() for line in frames)


# -- mutants of the implementation: each must make a required-outcome check fail ----------------------------------
def _mt1_holds(tmp_path):
    token = tok()
    try:
        S.SealedWriter(S.TokenSet([token])).write_new(tmp_path / "m.json", f'"API_KEY":"{token}"'.encode(),
                                                      path_class=S.INPUT_STORE)
    except S.SecretInOutput:
        return not (tmp_path / "m.json").exists()
    return False


def test_mutant_scanner_disabled_is_killed(tmp_path, monkeypatch):
    assert _mt1_holds(tmp_path / "a")
    monkeypatch.setattr(S, "scan", lambda *a, **k: [])
    assert not _mt1_holds(tmp_path / "b")


def test_mutant_percent_encoded_separators_dropped_is_killed(monkeypatch):
    text = f"apiKey%253D{tok()}".encode()
    assert "apikey_value" in ids(text)
    weak = __import__("re").compile(rb"(?i)api[_-]?key[\"']?\s*(?:=|:)\s*[\"']?([A-Za-z0-9]{16,128})")
    monkeypatch.setitem(S.STRUCTURAL_PATTERNS, "apikey_value", weak)
    assert "apikey_value" not in ids(text)


def test_mutant_prefetch_check_only_at_start_is_killed(http_state, monkeypatch):
    S.enforce_http_logger_pins()
    http.client.HTTPConnection.debuglevel = 1
    monkeypatch.setattr(S, "check_http_hygiene", lambda: None)
    assert S.guarded_fetch(lambda: "fetched") == "fetched"  # the MT6 test above would fail on this mutant


# -- conformance with WU-T's scanner (v3.2 §5.2) ---------------------------------------------------------------------
def test_every_wu_t_hit_is_also_a_gate_hit():
    """Runs only where WU-T (``claude/wu-token-leak-scan-20261007``) has landed; skipped on this branch."""
    wu_token_scan = pytest.importorskip("weather.operations.wu_token_scan")
    corpus = [template.format(t=tok()).encode() for template in (
        "?apiKey={t}", '"apiKey":"{t}"', "'apiKey': '{t}'", 'API_KEY = "{t}"', "apiKey%3D{t}",
        "&quot;API_KEY&quot;:&quot;{t}", "apiKey value {t}", '\\"api_key\\":\\"{t}\\"')]
    for blob in corpus:
        if any(p.search(blob) for p in wu_token_scan.PATTERNS.values()):
            assert S.scan(blob), blob[:12]

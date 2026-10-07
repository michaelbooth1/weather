"""B0w: weather-kind provenance (D-shadow-gate-spec-v3 §6.2) and the ``b0w_result`` contract.

Fictional records and raw bodies only; no tape, data/ or settlement row is read. The plugin-bound rebuilders are not
on this branch, so tests replace ``_plugin_rebuilders`` with fictional rebuilders that parse a JSON raw body.
"""
import hashlib
import json
import secrets as std_secrets

import pytest

from maker_core.shadow import b0w_result
from maker_core.shadow.secrets import SealedWriter, SecretInOutput, TokenSet
from weather.market import maker_shadow_gate_b0 as b0w

SEAL = hashlib.sha256(b"fictional sealed tape").hexdigest()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _rebuild(identity, bodies):
    merged = {}
    for body in bodies:
        merged.update(json.loads(body))
    return {"kind": identity["kind"], **merged}


REBUILDERS = {kind: _rebuild for kind in b0w.KINDS}


@pytest.fixture
def bound(monkeypatch):
    monkeypatch.setattr(b0w, "_plugin_rebuilders", lambda: REBUILDERS)


def record(kind, raw_bodies, payload=None, **extra):
    refs = [sha(b) for b in raw_bodies]
    if payload is None:
        payload = _rebuild({"kind": kind}, raw_bodies)
    return {"kind": kind, "condition_id": "0xfiction", "at": "2026-09-28T12:00:00+00:00", "payload": payload,
            "raw": refs, **extra}


def store(*bodies):
    return {sha(b): b for b in bodies}


GAMMA = b'{"horizon_days": 1, "tick": "0.01"}'
NBP = b'{"mean": 71.2}'


def test_unbound_rebuilders_refuse_fail_closed():
    result = b0w.run([record("descriptor", [GAMMA])], store(GAMMA), seal_sha256=SEAL)
    assert result["verdict"] == "REFUSED" and result["refusals"] == [{"reason": b0w.REBUILDERS_UNBOUND}]


def test_byte_equal_rebuild_passes(bound):
    rows = [record("descriptor", [GAMMA]), record("outcome_view", [NBP]), record("info_event", [GAMMA, NBP]),
            {"kind": "book", "condition_id": "0xfiction", "payload": {"x": 1}}]  # venue kind: B0's, skipped
    result = b0w.run(rows, store(GAMMA, NBP), seal_sha256=SEAL)
    assert result["verdict"] == "PASS" and result["records_checked"] == 3
    assert result["module_sha256"] == b0w.module_sha256() and result["seal_sha256"] == SEAL


def test_mismatch_is_fail_with_hashes_only(bound):
    """K12/K13-style plant: the recorded descriptor's horizon differs from what the raw Gamma body rebuilds."""
    planted = record("descriptor", [GAMMA], payload={"kind": "descriptor", "horizon_days": 2, "tick": "0.01"})
    result = b0w.run([planted], store(GAMMA), seal_sha256=SEAL)
    assert result["verdict"] == "FAIL" and len(result["mismatches"]) == 1
    entry = result["mismatches"][0]
    assert set(entry) <= b0w_result.MISMATCH_FIELDS and entry["recorded_sha256"] != entry["rebuilt_sha256"]
    assert "horizon_days" not in json.dumps(result)


def test_rebuild_error_is_a_mismatch_with_class_name_only(bound, monkeypatch):
    token = std_secrets.token_hex(16)

    def boom(identity, bodies):
        raise ValueError(f"cannot parse ?apiKey={token}")

    monkeypatch.setattr(b0w, "_plugin_rebuilders", lambda: {**REBUILDERS, "outcome_view": boom})
    result = b0w.run([record("outcome_view", [NBP])], store(NBP), seal_sha256=SEAL)
    assert result["verdict"] == "FAIL" and result["mismatches"][0]["error_class"] == "ValueError"
    assert token not in json.dumps(result)


@pytest.mark.parametrize("raw_store,cause", [({}, "absent"), ({sha(NBP): GAMMA}, "sha256_mismatch")])
def test_raw_missing_is_refused(bound, raw_store, cause):
    result = b0w.run([record("outcome_view", [NBP])], raw_store, seal_sha256=SEAL)
    assert result["verdict"] == "REFUSED"
    assert result["refusals"][0]["reason"] == b0w.RAW_MISSING and result["refusals"][0]["cause"] == cause
    assert b0w.run([{**record("outcome_view", [NBP]), "raw": []}], store(NBP),
                   seal_sha256=SEAL)["refusals"][0]["cause"] == "no_raw_reference"


@pytest.mark.parametrize("flag", [{"reopen": True}, {"derived": "local_midnight"}])
def test_reopen_and_derived_records_refused_until_their_rule_lands(bound, flag):
    """v3.2 §3.1 / §4.3 acceptance waits for F1-F3; until then such a record is never accepted unchecked."""
    result = b0w.run([record("descriptor", [GAMMA], **flag)], store(GAMMA), seal_sha256=SEAL)
    assert result["verdict"] == "REFUSED" and result["refusals"][0]["reason"] == b0w.REOPEN_PENDING


def test_mutant_comparison_disabled_is_killed(bound, monkeypatch):
    planted = record("descriptor", [GAMMA], payload={"kind": "descriptor", "horizon_days": 2})
    assert b0w.run([planted], store(GAMMA), seal_sha256=SEAL)["verdict"] == "FAIL"
    monkeypatch.setattr(b0w, "_sha", lambda data: "0" * 64)  # mutant: every payload hashes equal
    assert b0w.run([planted], store(GAMMA), seal_sha256=SEAL)["verdict"] != "FAIL"


# -- the data contract the core gate verifies (v3 §6.2 "Import boundary") ------------------------------------------
def test_binding_check_names_module_hash_and_seal(bound):
    result = b0w.run([record("descriptor", [GAMMA])], store(GAMMA), seal_sha256=SEAL)
    assert b0w_result.verify_binding(result, bound_module_sha256=b0w.module_sha256(), seal_sha256=SEAL) == "PASS"
    with pytest.raises(b0w_result.B0wResultInvalid, match="b0w_module_unbound"):
        b0w_result.verify_binding(result, bound_module_sha256="f" * 64, seal_sha256=SEAL)
    with pytest.raises(b0w_result.B0wResultInvalid, match="b0w_seal_mismatch"):
        b0w_result.verify_binding(result, bound_module_sha256=b0w.module_sha256(), seal_sha256="e" * 64)
    for broken in ({**result, "verdict": "PASS", "mismatches": [{"kind": "descriptor"}]},
                   {**result, "mismatches": [{"kind": "descriptor", "raw_bytes": "x"}]},
                   {**result, "extra": 1}):
        with pytest.raises(b0w_result.B0wResultInvalid):
            b0w_result.validate(broken)


def test_result_written_through_the_sealed_writer(bound, tmp_path):
    result = b0w.run([record("descriptor", [GAMMA])], store(GAMMA), seal_sha256=SEAL)
    token = std_secrets.token_hex(16)
    path = tmp_path / "b0w_result.json"
    b0w.write_result(path, result, writer=SealedWriter(TokenSet([token])))
    assert json.loads(path.read_bytes()) == result
    leaky = {**result, "verdict": "FAIL", "mismatches": [{"kind": "descriptor", "condition_id": token}]}
    with pytest.raises(SecretInOutput):
        b0w.write_result(tmp_path / "leak.json", leaky, writer=SealedWriter(TokenSet([token])))
    assert not (tmp_path / "leak.json").exists()

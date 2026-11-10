"""Synthetic closed-pack, seal and executable-boundary witnesses.

Guards: T093 LOW-ASK-1 no-order-path, immutable inputs and hash-only agent output.
"""

import ctypes
import json
import os
import struct
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from tests.backtesting.test_low_ask_core import H, synthetic_rows, synthetic_event
from weather.backtesting.low_ask import runner, seal
from weather.backtesting.low_ask.contracts import (CAPS, FIRST, LAST, ROLES, UTC,
                                                  Refusal, canonical, digest, json_bytes, timezone_fingerprint)
from weather.backtesting.low_ask.isolation import PaperImportBoundary, assert_no_order_path
from weather.backtesting.low_ask.pack import load_pack, validate_row
from weather.backtesting.low_ask.inference import evaluate, holm_pass, interval, panel_from_ledger
from weather.backtesting.low_ask.core import simulate
from weather.backtesting.low_ask.contracts import LOOK, number


def write_pack(root, rows=None, as_of="2026-11-18T12:00:00Z"):
    root.mkdir(parents=True, exist_ok=True)
    rows = deepcopy(rows or synthetic_rows())
    specs = []
    for role in ROLES:
        tail, chunks = "0" * 64, []
        ordered = sorted(rows[role], key=lambda r: r["received_utc"])
        for index, row in enumerate(ordered, 1):
            if role != "events":
                row.update(sequence=index, previous_sha256=tail)
            tail = digest(canonical(row))
            chunks.append(canonical(row) + b"\n")
        data = b"".join(chunks)
        name = role + ".jsonl"
        (root / name).write_bytes(data)
        specs.append({"path": name, "role": role, "bytes": len(data), "sha256": digest(data),
            "schema_version": "low_ask_rows_v1", "receipt_min_utc": min((r["received_utc"] for r in ordered), default=as_of),
            "receipt_max_utc": max((r["received_utc"] for r in ordered), default=as_of),
            "source_files": [{"physical_path": "synthetic/" + name, "bytes": len(data), "sha256": digest(data)}],
            "chain_id": role, "first_sequence": 1, "previous_sha256": "0" * 64, "last_sha256": tail})
    manifest = {"schema_version": "low_ask_inputs_v1", "trial": "LOW-ASK-1", "platform": "polymarket_international", "first_date": FIRST.isoformat(),
        "last_date": LAST.isoformat(), "as_of_utc": as_of, "producer_id": "synthetic-exporter",
        "reader_sha256": runner.code_hashes()["src/weather/backtesting/low_ask/pack.py"],
        "transform_sha256": H, "timezone_sha256": timezone_fingerprint(), "timezone_version": "synthetic-version-receipt",
        "latency_receipt": {"p95_seconds": "0.1", "frozen_L_seconds": "30", "samples": 100,
                            "deployed_path_sha256": H, "evidence_sha256": H, "synthetic": True},
        "capital": CAPS, "files": specs, "previous_receipt_sha256": None}
    path = root / "INPUTS.json"
    path.write_bytes(canonical(manifest))
    return path, manifest


def test_closed_pack_hashes_token_identity_and_duplicate_json(tmp_path):
    path, _ = write_pack(tmp_path)
    manifest, loaded = load_pack(path)
    assert loaded["receipt"]["row_counts"]["observations"] == 18
    assert loaded["rows"]["books"][0]["asks"][0] == ["0.40", "5"]
    assert manifest["trial"] == "LOW-ASK-1"
    (tmp_path / "books.jsonl").write_bytes(b"changed price")
    with pytest.raises(Refusal, match="file_hash"):
        load_pack(path)
    with pytest.raises(Refusal):
        json_bytes(b'{"price":"0.4","price":"0.7"}')


def test_compatibility_platform_is_never_a_trial_input(tmp_path):
    path, manifest = write_pack(tmp_path)
    manifest["platform"] = "polymarket_us"
    path.write_bytes(canonical(manifest))
    with pytest.raises(Refusal, match="platform_scope"):
        load_pack(path)


@pytest.mark.parametrize("mutation", ["unknown_token", "outcome_sidecar", "bad_chain", "future_date", "wrong_raw_hash", "aliased_event_token"])
def test_pack_refuses_unbound_or_unscoped_data(tmp_path, mutation):
    rows = synthetic_rows()
    if mutation == "unknown_token":
        rows["books"][0]["yes_token"] = "another-event"
    elif mutation == "outcome_sidecar":
        rows["books"][0]["label"] = 1
    elif mutation == "future_date":
        rows["events"][0]["target_date"] = "2027-01-31"
    elif mutation == "wrong_raw_hash":
        rows["observations"][0]["raw_sha256"] = "0" * 64
    elif mutation == "aliased_event_token":
        other = synthetic_event("miami")
        other["bins"][0]["yes_token"] = rows["events"][0]["bins"][0]["yes_token"]
        rows["events"].append(other)
    path, manifest = write_pack(tmp_path, rows)
    if mutation == "bad_chain":
        manifest["files"][1]["previous_sha256"] = H
        path.write_bytes(canonical(manifest))
    with pytest.raises(Refusal):
        load_pack(path)


def test_immutable_cumulative_receipt_and_no_backdated_additions(tmp_path):
    path, manifest = write_pack(tmp_path)
    _, loaded = load_pack(path)
    previous = loaded["receipt"]
    manifest["as_of_utc"] = "2026-11-18T13:00:00Z"
    manifest["previous_receipt_sha256"] = digest(canonical(previous))
    path.write_bytes(canonical(manifest))
    _, second = load_pack(path, previous)
    assert second["receipt"]["files"] == previous["files"]
    changed = deepcopy(manifest)
    changed["files"][0]["source_files"][0]["physical_path"] = "replacement"
    path.write_bytes(canonical(changed))
    with pytest.raises(Refusal, match="immutable_input"):
        load_pack(path, previous)
    extra = deepcopy(manifest["files"][0])
    extra["path"] = "new-events.jsonl"
    manifest["files"].append(extra)
    path.write_bytes(canonical(manifest))
    with pytest.raises(Refusal, match="backdated_input"):
        load_pack(path, previous)


def test_no_trading_client_in_closure_and_runtime_imports_blocked():
    assert_no_order_path()
    guard = PaperImportBoundary()
    for module in ("py_clob_client", "polymarket", "weather.market.international_client", "socket", "requests", "maker_core.venue"):
        with pytest.raises(ImportError, match="paper import boundary"):
            guard.find_spec(module)
    assert guard.find_spec("weather.market.metar_reports") is None
    assert guard.find_spec("decimal") is None


def test_dedicated_executable_blocks_actual_import_before_client_load():
    source = (
        "from weather.backtesting.low_ask.isolation import install_boundary, allowed\n"
        "import sys\n"
        "import subprocess\n"
        "install_boundary()\n"
        "assert 'subprocess' not in sys.modules\n"
        "from weather.backtesting.low_ask.contracts import timezone_fingerprint\n"
        "assert len(timezone_fingerprint()) == 64\n"
        "import importlib, sys\n"
        "for name in ['py_clob_client', 'weather.market.international_client', 'requests', 'socket', 'urllib.request', 'ccxt', 'weather.backtesting.low_ask_calibration', 'subprocess', 'sitecustomize']:\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except ImportError as error:\n"
        "        assert 'paper import boundary' in str(error)\n"
        "        assert name not in sys.modules\n"
        "    else:\n"
        "        raise AssertionError('unexpected client import')\n"
        "print('PAPER_BOUNDARY_OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", source], cwd=runner.repo_path(),
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PAPER_BOUNDARY_OK"
    help_result = subprocess.run([sys.executable, "-m", "weather.backtesting.low_ask", "--help"],
                                 cwd=runner.repo_path(), capture_output=True, text=True, timeout=15)
    assert help_result.returncode == 0, help_result.stderr
    assert "offline paper-only sealed accrual" in help_result.stdout


def synthetic_freeze(manifest):
    return {"schema_version": "low_ask_freeze_v1", "trial": "LOW-ASK-1", "frozen_utc": "2026-11-15T12:00:00Z", "code_sha256": runner.code_hashes(),
        "prereg_sha256": digest(runner.repo_path("docs/research/low-ask-1/PREREG_LOW_ASK_1.md").read_bytes()),
        "input_contract_sha256": digest(runner.repo_path("docs/research/low-ask-1/INPUT_CONTRACT.md").read_bytes()),
        **{k: manifest[k] for k in ("producer_id", "reader_sha256", "transform_sha256", "timezone_sha256", "timezone_version", "latency_receipt", "capital")},
        "public_key_sha256": H, "claimants": ["F3-SIM-1", "LOW-ASK-1"], "state_root": str(Path.cwd() / "synthetic-state"),
        "gates": {k: True for k in ("foundations_landed", "capture_verified", "scoped_pack_verified", "latency_verified",
                    "authority_amendment", "claimant_scope_zero_exposure", "master_defaults_confirmed", "two_replays_match")},
        "calibration": {"status": "SCREEN_ONLY", "receipt_sha256": None, "critical_value": None, "power_lower": None}}


def test_agent_receipt_and_errors_never_reveal_values(tmp_path, monkeypatch, capsys):
    path, manifest = write_pack(tmp_path / "pack")
    freeze = synthetic_freeze(manifest)
    freeze["state_root"] = str(tmp_path)
    key = {"n_hex": "synthetic-public-only", "e": 65537}
    freeze["public_key_sha256"] = digest(canonical(key))
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_bytes(canonical(freeze))
    captured = []
    monkeypatch.setattr(runner, "read_public_key", lambda _: key)
    def fake_seal(value, _):
        captured.append(value)
        return b"synthetic-encrypted", {"ciphertext_sha256": H, "public_key_sha256": H, "bytes": 19}
    monkeypatch.setattr(runner, "seal_payload", fake_seal)
    if os.name != "nt":
        from contextlib import nullcontext
        monkeypatch.setattr(runner, "state_lock", lambda _: nullcontext())
    receipt = runner.accrue(path, freeze_path, digest(canonical(freeze)), tmp_path / "public.json", tmp_path / "sealed",
                            now=datetime(2026, 11, 18, 13, tzinfo=UTC))
    # Economic fields exist only in the payload handed to the sealer.
    assert captured[0]["ledger"]["decisions"][0]["ask"] == "0.40"
    public = canonical(receipt)
    for forbidden in (b'"ask"', b'"cost"', b'"net_lower"', b'"cash"', b'"filled"', b'"reason"', b'"replay_sha256"', b'"band_id"'):
        assert forbidden not in public
    assert {p.name for p in (tmp_path / "sealed").iterdir()} == {"ledger.sealed", "receipt.json"}
    assert (tmp_path / "sealed" / "ledger.sealed").read_bytes() == b"synthetic-encrypted"
    def fail(*args, **kwargs):
        raise ValueError("SECRET_ASK_0.40_SECRET_PNL_5.78")
    monkeypatch.setattr(runner, "accrue", fail)
    code = runner.main(["--manifest", str(path), "--freeze", str(freeze_path), "--freeze-sha", H,
                        "--public-key", "public.json", "--out", str(tmp_path / "fail")])
    printed = capsys.readouterr()
    assert code == 2 and printed.err == ""
    assert json.loads(printed.out) == {"status": "REFUSED", "integrity_failure_count": 1}
    assert "SECRET" not in printed.out


def test_freeze_deadline_and_code_binding(tmp_path):
    _, manifest = write_pack(tmp_path)
    freeze = synthetic_freeze(manifest)
    now = datetime(2026, 11, 18, tzinfo=UTC)
    runner.validate_freeze(freeze, digest(canonical(freeze)), now)
    freeze["frozen_utc"] = "2026-11-17T05:00:00Z"
    with pytest.raises(Refusal, match="freeze_deadline"):
        runner.validate_freeze(freeze, digest(canonical(freeze)), now)
    freeze["frozen_utc"] = "2026-11-15T12:00:00Z"
    freeze["code_sha256"] = {}
    with pytest.raises(Refusal, match="code_binding"):
        runner.validate_freeze(freeze, digest(canonical(freeze)), now)


def test_final_look_time_gate_consumed_once_even_on_failure(tmp_path, monkeypatch):
    path, manifest = write_pack(tmp_path / "pack")
    freeze = synthetic_freeze(manifest)
    freeze["state_root"] = str(tmp_path)
    key = {"n_hex": "synthetic-public-only", "e": 65537}
    freeze["public_key_sha256"] = digest(canonical(key))
    monkeypatch.setattr(runner, "read_public_key", lambda _: key)
    (tmp_path / "family.json").write_bytes(b"{}")
    frozen_path = tmp_path / "freeze.json"
    frozen_path.write_bytes(canonical(freeze))
    if os.name != "nt":
        from contextlib import nullcontext
        monkeypatch.setattr(runner, "state_lock", lambda _: nullcontext())
    from datetime import timedelta
    args = (path, frozen_path, digest(canonical(freeze)), tmp_path / "public.json", tmp_path / "look")
    with pytest.raises(Refusal, match="look_clock"):
        runner.accrue(*args, now=LOOK-timedelta(seconds=1), look=True, family_path=tmp_path / "family.json")
    assert not (tmp_path / "LOOK_CONSUMED").exists()
    def fail(*args, **kwargs):
        raise Refusal("synthetic_after_consume_failure")
    monkeypatch.setattr(runner, "process_snapshot", fail)
    with pytest.raises(Refusal, match="after_consume"):
        runner.accrue(*args, now=LOOK, look=True, family_path=tmp_path / "family.json")
    assert (tmp_path / "LOOK_CONSUMED").exists()
    with pytest.raises(FileExistsError):
        runner.accrue(*args, now=LOOK, look=True, family_path=tmp_path / "family.json")


def test_final_report_releases_account_summary_only_at_consumed_look(tmp_path, monkeypatch):
    from weather.backtesting.low_ask import inference
    path, manifest = write_pack(tmp_path / "pack", as_of="2027-02-09T23:00:00Z")
    freeze = synthetic_freeze(manifest)
    freeze["state_root"] = str(tmp_path)
    key = {"n_hex": "synthetic-public-only", "e": 65537}
    freeze["public_key_sha256"] = digest(canonical(key))
    frozen_path = tmp_path / "freeze.json"
    frozen_path.write_bytes(canonical(freeze))
    family_path = tmp_path / "family.json"
    family_path.write_bytes(canonical({"claimants": freeze["claimants"], "pvalues": {"F3-SIM-1": 1}}))
    monkeypatch.setattr(runner, "read_public_key", lambda _: key)
    monkeypatch.setattr(runner, "seal_payload", lambda *_: (b"synthetic-cipher", {"ciphertext_sha256": H}))
    monkeypatch.setattr(inference, "evaluate", lambda *_, **__: {"verdict": "DESCRIBE", "pvalue": 1})
    if os.name != "nt":
        from contextlib import nullcontext
        monkeypatch.setattr(runner, "state_lock", lambda _: nullcontext())
    runner.accrue(path, frozen_path, digest(canonical(freeze)), tmp_path / "public.json", tmp_path / "look",
                  now=LOOK, look=True, family_path=family_path)
    report = json.loads((tmp_path / "look" / "final_report.json").read_bytes())
    assert (tmp_path / "LOOK_CONSUMED").exists()
    assert report["schema_version"] == "low_ask_result_v1"
    assert number(report["recorded_cash"]) == number("295.78")
    assert number(report["recorded_locked_cost"]) == number("4.22")
    assert report["unresolved_max_payout"] == "10"
    assert report["freeze_sha256"] == digest(canonical(freeze))


def test_primary_fixed_population_and_missing_calibration_prevent_pass():
    ledger = simulate(synthetic_rows(), as_of=LOOK, latency_seconds=number("30"))
    panel = panel_from_ledger(ledger)
    assert len(panel) == 75 and all(len(row) == 12 for row in panel)
    assert sum(map(sum, panel)) == pytest.approx(-4.22)
    report = evaluate(ledger, calibration={"status": "SCREEN_ONLY"}, family_pvalues={"F3-SIM-1": 0.001},
                      claimants=["F3-SIM-1", "LOW-ASK-1"], resamples=128)
    assert report["mean"] == pytest.approx(-4.22/900)
    assert report["verdict"] == "DESCRIBE"
    assert report["both_filled_city_days"] == 1 and report["adequate_dates"] == 0
    assert report["both_filled_by_city"]["atlanta"] == 1
    assert len(report["both_filled_by_date"]) == 75
    assert report["scheduled_slots"] == 1800 and report["filled_slots"] == 2


def test_bootstrap_positive_control_and_full_family_holm():
    panel = [[0.5] * 12 for _ in range(75)]
    result = interval(panel, critical=3.0, resamples=128)
    assert result["mean"] == result["lower"] == result["upper"] == 0.5
    assert result["pvalue"] == 0.0125
    assert holm_pass({"F3-SIM-1": .0375, "LOW-ASK-1": .0125}, ["F3-SIM-1", "LOW-ASK-1"])
    assert not holm_pass({"LOW-ASK-1": .03, "F3-SIM-1": .04}, ["F3-SIM-1", "LOW-ASK-1"])
    with pytest.raises(Refusal, match="family_claimants"):
        holm_pass({"LOW-ASK-1": .0125}, ["F3-SIM-1", "LOW-ASK-1"])
    with pytest.raises(Refusal, match="family_pvalue"):
        holm_pass({"LOW-ASK-1": .0125, "F3-SIM-1": False}, ["F3-SIM-1", "LOW-ASK-1"])


def test_ineligible_trial_exports_one_for_family_not_a_small_diagnostic_pvalue():
    from datetime import timedelta
    from weather.backtesting.low_ask.contracts import CITIES
    ledger = {"decisions": [
        {"target_date": (FIRST+timedelta(days=d)).isoformat(), "city": city, "cut": hour,
         "status": "resolved", "shares": "5", "conservative_net": "0.25"}
        for d in range(75) for city in CITIES for hour in (17, 18)],
        "doubtful_fills": 1, "unresolved": 0}
    report = evaluate(ledger, calibration={"status": "CALIBRATED", "critical_value": "3"},
                      family_pvalues={"F3-SIM-1": .03}, claimants=["F3-SIM-1", "LOW-ASK-1"], resamples=128)
    assert report["verdict"] == "DESCRIBE"
    assert report["pvalue"] == 1.0
    assert report["diagnostic_pvalue"] == .0125
    assert not report["family_holm_pass"]
@pytest.mark.skipif(os.name != "nt", reason="Native Windows CNG seal")
def test_native_oaep_seal_roundtrip_randomness_and_fixed_length():
    # Ephemeral SYNTHETIC crypto key in RAM only. No account, credential or file.
    api = ctypes.WinDLL("bcrypt.dll")
    pointer, u32 = ctypes.c_void_p, ctypes.c_uint32
    api.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(pointer), ctypes.c_wchar_p, ctypes.c_wchar_p, u32]
    api.BCryptGenerateKeyPair.argtypes = [pointer, ctypes.POINTER(pointer), u32, u32]
    api.BCryptFinalizeKeyPair.argtypes = [pointer, u32]
    api.BCryptExportKey.argtypes = [pointer, pointer, ctypes.c_wchar_p, pointer, u32, ctypes.POINTER(u32), u32]
    api.BCryptDecrypt.argtypes = [pointer, pointer, u32, pointer, pointer, u32, pointer, u32, ctypes.POINTER(u32), u32]
    api.BCryptDestroyKey.argtypes = [pointer]
    api.BCryptCloseAlgorithmProvider.argtypes = [pointer, u32]
    provider, key = pointer(), pointer()
    assert api.BCryptOpenAlgorithmProvider(ctypes.byref(provider), "RSA", None, 0) == 0
    try:
        assert api.BCryptGenerateKeyPair(provider, ctypes.byref(key), 3072, 0) == 0
        assert api.BCryptFinalizeKeyPair(key, 0) == 0
        blob, written = ctypes.create_string_buffer(2048), u32()
        assert api.BCryptExportKey(key, None, "RSAPUBLICBLOB", blob, len(blob), ctypes.byref(written), 0) == 0
        _, _, exponent_bytes, modulus_bytes, _, _ = struct.unpack("<6I", blob.raw[:24])
        modulus = blob.raw[24 + exponent_bytes:24 + exponent_bytes + modulus_bytes]
        public = {"n_hex": modulus.hex(), "e": 65537}
        a = seal.encrypt(b'{"ask":"0.40","cash":"295.78"}', public, padded_bytes=1024)
        b = seal.encrypt(b'{"skip":true}', public, padded_bytes=1024)
        assert len(a) == len(b) and a != b and b'"ask"' not in a
        class Padding(ctypes.Structure):
            _fields_ = [("algorithm", ctypes.c_wchar_p), ("label", pointer), ("label_size", u32)]
        label = ctypes.create_string_buffer(seal.LABEL)
        padding = Padding("SHA256", ctypes.cast(label, pointer), len(seal.LABEL))
        k, blocks = struct.unpack(">II", a[4:12])
        plain = bytearray()
        for index in range(blocks):
            source = ctypes.create_string_buffer(a[12 + index*k:12 + (index+1)*k])
            target, used = ctypes.create_string_buffer(k), u32()
            assert api.BCryptDecrypt(key, source, k, ctypes.byref(padding), None, 0, target, k, ctypes.byref(used), seal.BCRYPT_PAD_OAEP) == 0
            plain.extend(target.raw[:used.value])
        size = struct.unpack(">Q", plain[:8])[0]
        assert bytes(plain[8:8 + size]) == b'{"ask":"0.40","cash":"295.78"}'
    finally:
        if key:
            api.BCryptDestroyKey(key)
        api.BCryptCloseAlgorithmProvider(provider, 0)

import json
from pathlib import Path

import pytest

from weather.market import mm_credential_import_cli as importer


WALLET = "0x0000000000000000000000000000000000000002"
FUNDER = "0x0000000000000000000000000000000000000001"


def source_values(**overrides):
    values = {
        "POLYMM_CLOB_HOST": "https://clob.polymarket.com",
        "POLYMM_CHAIN_ID": "137",
        "POLYMM_WALLET_ADDRESS": WALLET,
        "POLYMM_FUNDER_ADDRESS": FUNDER,
        "POLYMM_SIGNATURE_TYPE": "2",
        "POLYMM_API_KEY": "fixture-api-key",
        "POLYMM_API_SECRET": "fixture-api-secret",
        "POLYMM_API_PASSPHRASE": "fixture-passphrase",
        "POLYMM_PRIVATE_KEY": "fixture-private-key",
        "POLYMM_RELAYER_API_KEY": "ignored-relayer-secret",
        "POLYMM_POLYGON_RPC_URL": "https://rpc.invalid/ignored-secret",
        "POLYMM_LIVE_TRADING": "true",
    }
    values.update(overrides)
    return values


def write_source(path, values=None):
    values = values or source_values()
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    return path


def external_paths(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    source = write_source(tmp_path / "pilot.env.txt")
    return repo_root, source, tmp_path / "refs.json", tmp_path / "receipt.json"


def import_args(tmp_path, **overrides):
    repo_root, source, manifest, receipt = external_paths(tmp_path)
    values = {
        "source_path": source,
        "manifest_path": manifest,
        "receipt_path": receipt,
        "confirmation": importer.CONFIRMATION,
        "source_acl_private_confirmed": True,
        "repo_root": repo_root,
        "platform_name": "nt",
        "account_deriver": lambda _key: WALLET,
    }
    values.update(overrides)
    return values


def test_import_writes_only_four_new_vault_entries_and_public_manifest(tmp_path):
    stored = {}
    args = import_args(
        tmp_path,
        credential_exists=lambda target: target in stored,
        credential_writer=lambda target, value: stored.__setitem__(target, value),
        credential_deleter=lambda target: stored.pop(target, None),
    )

    result = importer.import_live_pilot_credentials(**args)

    assert result["receipt"]["status"] == "PASS"
    assert result["receipt"]["credential_value_count_written"] == 4
    assert len(stored) == 4
    manifest_raw = Path(args["manifest_path"]).read_text(encoding="utf-8")
    receipt_raw = Path(args["receipt_path"]).read_text(encoding="utf-8")
    for secret in (
        "fixture-api-key",
        "fixture-api-secret",
        "fixture-passphrase",
        "fixture-private-key",
        "ignored-relayer-secret",
        "ignored-secret",
    ):
        assert secret not in manifest_raw
        assert secret not in receipt_raw
    manifest = json.loads(manifest_raw)
    assert manifest["wallet_type"] == "gnosis_safe"
    assert manifest["signature_type"] == "POLY_GNOSIS_SAFE"
    assert manifest["signature_type_id"] == 2
    assert set(manifest["credential_references"]) == set(
        importer.REFERENCE_ENV.values()
    )
    assert manifest["public_environment"][importer.FUNDER_ENV] == FUNDER


def test_import_supports_deposit_wallet_topology(tmp_path):
    args = import_args(
        tmp_path,
        credential_exists=lambda _target: False,
        credential_writer=lambda _target, _value: None,
        credential_deleter=lambda _target: None,
    )
    write_source(args["source_path"], source_values(POLYMM_SIGNATURE_TYPE="3"))

    result = importer.import_live_pilot_credentials(**args)

    assert result["manifest"]["wallet_type"] == "deposit_wallet"
    assert result["manifest"]["signature_type"] == "POLY_1271"


def test_import_refuses_existing_target_before_writing_any_secret(tmp_path):
    writes = []
    args = import_args(
        tmp_path,
        credential_exists=lambda _target: True,
        credential_writer=lambda target, _value: writes.append(target),
        credential_deleter=lambda _target: None,
    )

    with pytest.raises(RuntimeError, match="already exist"):
        importer.import_live_pilot_credentials(**args)

    assert writes == []
    receipt = json.loads(Path(args["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"
    assert receipt["missing"] == ["fixed_credential_targets_are_new"]


def test_partial_vault_write_rolls_back_and_emits_no_secret(tmp_path):
    stored = {}

    def write(target, value):
        if len(stored) == 2:
            raise OSError("RAW-VAULT-FAILURE")
        stored[target] = value

    args = import_args(
        tmp_path,
        credential_exists=lambda _target: False,
        credential_writer=write,
        credential_deleter=lambda target: stored.pop(target),
    )

    with pytest.raises(OSError, match="RAW-VAULT-FAILURE"):
        importer.import_live_pilot_credentials(**args)

    assert stored == {}
    assert not Path(args["manifest_path"]).exists()
    raw = Path(args["receipt_path"]).read_text(encoding="utf-8")
    receipt = json.loads(raw)
    assert receipt["status"] == "FAIL"
    assert receipt["rollback_attempted"] is True
    assert receipt["rollback_ok"] is True
    assert "RAW-VAULT-FAILURE" not in raw


def test_validation_failure_records_check_names_without_secret_values(tmp_path):
    args = import_args(
        tmp_path,
        account_deriver=lambda _key: FUNDER,
        credential_exists=lambda _target: False,
        credential_writer=lambda _target, _value: None,
        credential_deleter=lambda _target: None,
    )

    with pytest.raises(RuntimeError, match="private_key_matches_wallet_address"):
        importer.import_live_pilot_credentials(**args)

    raw = Path(args["receipt_path"]).read_text(encoding="utf-8")
    receipt = json.loads(raw)
    assert "private_key_matches_wallet_address" in receipt["missing"]
    assert "fixture-private-key" not in raw


def test_wrong_confirmation_or_repo_local_source_stops_before_vault(tmp_path):
    called = False
    args = import_args(tmp_path)

    def write(_target, _value):
        nonlocal called
        called = True

    args["credential_writer"] = write
    args["credential_exists"] = lambda _target: False
    args["credential_deleter"] = lambda _target: None
    args["confirmation"] = "yes"
    with pytest.raises(RuntimeError, match="exact confirmation"):
        importer.import_live_pilot_credentials(**args)
    assert called is False
    assert not Path(args["receipt_path"]).exists()

    repo_source = write_source(Path(args["repo_root"]) / "secret.env.txt")
    args["source_path"] = repo_source
    args["confirmation"] = importer.CONFIRMATION
    with pytest.raises(RuntimeError, match="outside the repository"):
        importer.import_live_pilot_credentials(**args)
    assert called is False


def test_main_never_prints_raw_exception_text(monkeypatch, capsys):
    monkeypatch.setattr(
        importer,
        "import_live_pilot_credentials",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("RAW-SOURCE-SECRET")
        ),
    )

    status = importer.main([
        "--source-env", "outside.env",
        "--manifest-out", "refs.json",
        "--receipt-out", "receipt.json",
        "--confirm-source-acl-private",
        "--confirmation", importer.CONFIRMATION,
    ])

    assert status == 1
    stderr = capsys.readouterr().err
    assert "RuntimeError" in stderr
    assert "RAW-SOURCE-SECRET" not in stderr

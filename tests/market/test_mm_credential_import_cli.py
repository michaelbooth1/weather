import json
from datetime import datetime
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
        "credential_reader": lambda _target: (_ for _ in ()).throw(
            AssertionError("credential reader must not be called")
        ),
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
    assert result["receipt"]["schema_version"] == (
        "mm_live_credential_import_receipt_v0.4"
    )
    assert result["receipt"]["credential_mode"] == "create_new"
    assert result["receipt"]["credential_value_count_written"] == 4
    assert (
        result["receipt"]["credential_value_count_existing_exact_verified"]
        == 0
    )
    assert result["receipt"]["credential_store_mutation_attempted"] is True
    assert result["receipt"]["execution_host_id"] == (
        importer.current_execution_host_id()
    )
    assert result["receipt"]["execution_principal_id"] == (
        importer.current_execution_principal_id()
    )
    assert datetime.fromisoformat(result["receipt"]["prepared_at_utc"]).tzinfo
    assert len(stored) == 4
    manifest_raw = Path(args["manifest_path"]).read_text(encoding="utf-8")
    receipt_raw = Path(args["receipt_path"]).read_text(encoding="utf-8")
    for secret in (
        "fixture-api-key",
        "fixture-api-secret",
        "fixture-passphrase",
        "fixture-private-key",
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
    reads = []
    args = import_args(
        tmp_path,
        credential_exists=lambda _target: True,
        credential_reader=lambda target: reads.append(target),
        credential_writer=lambda target, _value: writes.append(target),
        credential_deleter=lambda _target: None,
    )

    with pytest.raises(RuntimeError, match="already exist"):
        importer.import_live_pilot_credentials(**args)

    assert writes == []
    assert reads == []
    receipt = json.loads(Path(args["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"
    assert receipt["missing"] == ["fixed_credential_targets_are_new"]


def test_verify_existing_exact_matches_all_four_without_mutation(
    tmp_path,
    monkeypatch,
):
    source = source_values(POLYMM_API_SECRET="fixture-api-sëcret")
    expected_by_field = {
        field: source[source_key]
        for field, source_key in importer.SOURCE_SECRET_KEYS.items()
    }
    stored = {
        target: expected_by_field[field]
        for field, target in importer.WINCRED_TARGETS.items()
    }
    reads = []
    writes = []
    deletes = []
    comparisons = []
    original_compare_digest = importer.hmac.compare_digest

    def compare_digest(actual, expected):
        comparisons.append((actual, expected))
        return original_compare_digest(actual, expected)

    monkeypatch.setattr(importer.hmac, "compare_digest", compare_digest)
    args = import_args(
        tmp_path,
        confirmation=importer.VERIFY_EXISTING_EXACT_CONFIRMATION,
        verify_existing_exact=True,
        credential_exists=lambda target: target in stored,
        credential_reader=lambda target: reads.append(target) or stored[target],
        credential_writer=lambda target, value: writes.append((target, value)),
        credential_deleter=lambda target: deletes.append(target),
    )
    write_source(args["source_path"], source)

    result = importer.import_live_pilot_credentials(**args)

    receipt = result["receipt"]
    assert receipt["status"] == "PASS"
    assert receipt["credential_mode"] == "verify_existing_exact"
    assert receipt["credential_value_count_written"] == 0
    assert receipt["credential_value_count_existing_exact_verified"] == 4
    assert receipt["credential_store_mutation_attempted"] is False
    assert reads == list(importer.WINCRED_TARGETS.values())
    assert writes == []
    assert deletes == []
    assert len(comparisons) == 4
    assert all(
        isinstance(actual, bytes) and isinstance(expected, bytes)
        for actual, expected in comparisons
    )
    manifest_raw = Path(args["manifest_path"]).read_text(encoding="utf-8")
    receipt_raw = Path(args["receipt_path"]).read_text(encoding="utf-8")
    for secret in source.values():
        if secret.startswith("fixture-"):
            assert secret not in manifest_raw
            assert secret not in receipt_raw


def test_verify_existing_exact_refuses_incomplete_set_before_reads_or_mutation(
    tmp_path,
):
    first_target = next(iter(importer.WINCRED_TARGETS.values()))
    reads = []
    writes = []
    deletes = []
    args = import_args(
        tmp_path,
        confirmation=importer.VERIFY_EXISTING_EXACT_CONFIRMATION,
        verify_existing_exact=True,
        credential_exists=lambda target: target == first_target,
        credential_reader=lambda target: reads.append(target),
        credential_writer=lambda target, value: writes.append((target, value)),
        credential_deleter=lambda target: deletes.append(target),
    )

    with pytest.raises(RuntimeError, match="could not be verified exactly"):
        importer.import_live_pilot_credentials(**args)

    assert reads == []
    assert writes == []
    assert deletes == []
    assert not Path(args["manifest_path"]).exists()
    receipt = json.loads(Path(args["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["credential_value_count_existing_exact_verified"] == 0
    assert receipt["credential_store_mutation_attempted"] is False
    assert receipt["missing"] == [
        "fixed_credential_targets_all_exist_and_match_source"
    ]


def test_verify_existing_exact_reads_and_compares_all_four_before_generic_mismatch(
    tmp_path,
    monkeypatch,
):
    expected_by_field = {
        field: source_values()[source_key]
        for field, source_key in importer.SOURCE_SECRET_KEYS.items()
    }
    stored = {
        target: expected_by_field[field]
        for field, target in importer.WINCRED_TARGETS.items()
    }
    stored[next(iter(stored))] = "fixture-wrong-secret"
    reads = []
    comparisons = []
    writes = []
    deletes = []
    original_compare_digest = importer.hmac.compare_digest

    def compare_digest(actual, expected):
        comparisons.append((actual, expected))
        return original_compare_digest(actual, expected)

    monkeypatch.setattr(importer.hmac, "compare_digest", compare_digest)
    args = import_args(
        tmp_path,
        confirmation=importer.VERIFY_EXISTING_EXACT_CONFIRMATION,
        verify_existing_exact=True,
        credential_exists=lambda _target: True,
        credential_reader=lambda target: reads.append(target) or stored[target],
        credential_writer=lambda target, value: writes.append((target, value)),
        credential_deleter=lambda target: deletes.append(target),
    )

    with pytest.raises(RuntimeError, match="could not be verified exactly"):
        importer.import_live_pilot_credentials(**args)

    assert len(reads) == 4
    assert len(comparisons) == 4
    assert writes == []
    assert deletes == []
    assert not Path(args["manifest_path"]).exists()
    raw = Path(args["receipt_path"]).read_text(encoding="utf-8")
    receipt = json.loads(raw)
    assert receipt["credential_value_count_existing_exact_verified"] == 0
    assert receipt["credential_store_mutation_attempted"] is False
    assert "fixture-wrong-secret" not in raw


def test_verify_existing_exact_masks_reader_error_and_continues_all_reads(tmp_path):
    expected_by_field = {
        field: source_values()[source_key]
        for field, source_key in importer.SOURCE_SECRET_KEYS.items()
    }
    stored = {
        target: expected_by_field[field]
        for field, target in importer.WINCRED_TARGETS.items()
    }
    first_target = next(iter(stored))
    reads = []

    def read(target):
        reads.append(target)
        if target == first_target:
            raise OSError("RAW-VAULT-DETAIL")
        return stored[target]

    args = import_args(
        tmp_path,
        confirmation=importer.VERIFY_EXISTING_EXACT_CONFIRMATION,
        verify_existing_exact=True,
        credential_exists=lambda _target: True,
        credential_reader=read,
        credential_writer=lambda _target, _value: pytest.fail("unexpected write"),
        credential_deleter=lambda _target: pytest.fail("unexpected delete"),
    )

    with pytest.raises(RuntimeError, match="could not be verified exactly"):
        importer.import_live_pilot_credentials(**args)

    assert len(reads) == 4
    raw = Path(args["receipt_path"]).read_text(encoding="utf-8")
    assert "RAW-VAULT-DETAIL" not in raw


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


def test_validator_dependency_failure_is_not_reported_as_a_bad_key(tmp_path):
    args = import_args(
        tmp_path,
        account_deriver=lambda _key: (_ for _ in ()).throw(
            importer.CredentialValidationDependencyError("dependency unavailable")
        ),
        credential_exists=lambda _target: False,
        credential_writer=lambda _target, _value: None,
        credential_deleter=lambda _target: None,
    )

    with pytest.raises(importer.CredentialValidationDependencyError):
        importer.import_live_pilot_credentials(**args)

    raw = Path(args["receipt_path"]).read_text(encoding="utf-8")
    receipt = json.loads(raw)
    assert receipt["missing"] == []
    assert receipt["exception_type"] == "CredentialValidationDependencyError"
    assert "fixture-private-key" not in raw


def test_owned_output_cleanup_does_not_delete_a_replacement(tmp_path):
    path = tmp_path / "reserved.json"
    marker = b"unrelated-race-winner\n"
    output = importer._CreateOnlyOutput(path, label="fixture output")
    output.close()
    path.unlink()
    path.write_bytes(marker)

    assert output.remove_if_owned() is False
    assert path.read_bytes() == marker


def test_manifest_reservation_race_stops_before_vault_and_preserves_winner(
    tmp_path,
    monkeypatch,
):
    vault_calls = []
    args = import_args(
        tmp_path,
        credential_exists=lambda target: vault_calls.append(target) or False,
        credential_writer=lambda target, value: vault_calls.append(
            (target, value)
        ),
        credential_deleter=lambda target: vault_calls.append(("delete", target)),
    )
    manifest = Path(args["manifest_path"])
    marker = b"manifest-race-winner\n"
    original_open = importer.os.open
    raced = False

    def open_with_race(path, flags, mode=0o777):
        nonlocal raced
        if Path(path) == manifest and flags & importer.os.O_EXCL and not raced:
            raced = True
            manifest.write_bytes(marker)
        return original_open(path, flags, mode)

    monkeypatch.setattr(importer.os, "open", open_with_race)

    with pytest.raises(RuntimeError, match="manifest output path must be new"):
        importer.import_live_pilot_credentials(**args)

    assert raced is True
    assert vault_calls == []
    assert manifest.read_bytes() == marker
    assert not Path(args["receipt_path"]).exists()


def test_receipt_reservation_race_cleans_owned_manifest_before_vault(
    tmp_path,
    monkeypatch,
):
    vault_calls = []
    args = import_args(
        tmp_path,
        credential_exists=lambda target: vault_calls.append(target) or False,
        credential_writer=lambda target, value: vault_calls.append(
            (target, value)
        ),
        credential_deleter=lambda target: vault_calls.append(("delete", target)),
    )
    manifest = Path(args["manifest_path"])
    receipt = Path(args["receipt_path"])
    marker = b"receipt-race-winner\n"
    original_open = importer.os.open
    raced = False

    def open_with_race(path, flags, mode=0o777):
        nonlocal raced
        if Path(path) == receipt and flags & importer.os.O_EXCL and not raced:
            raced = True
            receipt.write_bytes(marker)
        return original_open(path, flags, mode)

    monkeypatch.setattr(importer.os, "open", open_with_race)

    with pytest.raises(RuntimeError, match="receipt output path must be new"):
        importer.import_live_pilot_credentials(**args)

    assert raced is True
    assert vault_calls == []
    assert not manifest.exists()
    assert receipt.read_bytes() == marker


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


def test_unrelated_source_key_is_rejected_before_vault_access(tmp_path):
    vault_calls = []
    args = import_args(
        tmp_path,
        credential_exists=lambda target: vault_calls.append(target) or False,
        credential_writer=lambda target, value: vault_calls.append((target, value)),
        credential_deleter=lambda target: vault_calls.append(("delete", target)),
    )
    write_source(
        args["source_path"],
        source_values(POLYMM_LIVE_TRADING="true"),
    )

    with pytest.raises(RuntimeError, match="unknown key"):
        importer.import_live_pilot_credentials(**args)

    assert vault_calls == []


def test_source_snapshot_refuses_a_replaced_path_identity(tmp_path, monkeypatch):
    source = write_source(tmp_path / "source.env.txt")
    replacement = write_source(
        tmp_path / "replacement.env.txt",
        source_values(POLYMM_API_KEY="replacement-secret"),
    )
    original_read = importer.os.read
    original_stat = Path.stat
    read_started = False

    def read_and_mark(descriptor, count):
        nonlocal read_started
        block = original_read(descriptor, count)
        if block:
            read_started = True
        return block

    def replacement_stat(path, *args, **kwargs):
        if Path(path) == source and read_started:
            return original_stat(replacement, *args, **kwargs)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(importer.os, "read", read_and_mark)
    monkeypatch.setattr(Path, "stat", replacement_stat)

    with pytest.raises(RuntimeError, match="identity or bytes changed"):
        importer._read_source_snapshot(source)


def test_verify_existing_exact_requires_separate_confirmation_before_vault(tmp_path):
    called = False
    args = import_args(
        tmp_path,
        verify_existing_exact=True,
        confirmation=importer.CONFIRMATION,
    )

    def exists(_target):
        nonlocal called
        called = True
        return True

    args["credential_exists"] = exists
    with pytest.raises(RuntimeError, match="exact confirmation"):
        importer.import_live_pilot_credentials(**args)

    assert called is False
    assert not Path(args["receipt_path"]).exists()


def test_main_passes_explicit_verify_existing_mode(monkeypatch, capsys):
    captured = []
    monkeypatch.setattr(
        importer,
        "_activate_sdk_overlay",
        lambda _path, _digest: {
            "status": "PASS",
            "process_path_activated": True,
            "shared_environment_mutated": False,
        },
    )

    def prepare(*_args, **kwargs):
        captured.append(kwargs)
        return {
            "receipt": {
                "credential_value_count_written": 0,
                "credential_value_count_existing_exact_verified": 4,
            }
        }

    monkeypatch.setattr(importer, "import_live_pilot_credentials", prepare)

    status = importer.main([
        "--source-env", "outside.env",
        "--manifest-out", "refs.json",
        "--receipt-out", "receipt.json",
        "--sdk-overlay-manifest", "sealed-sdk.json",
        "--sdk-overlay-manifest-sha256", "a" * 64,
        "--confirm-source-acl-private",
        "--verify-existing-exact",
        "--confirmation", importer.VERIFY_EXISTING_EXACT_CONFIRMATION,
    ])

    assert status == 0
    assert captured == [{
        "confirmation": importer.VERIFY_EXISTING_EXACT_CONFIRMATION,
        "source_acl_private_confirmed": True,
        "verify_existing_exact": True,
    }]
    assert "credential preparation PASS: 4 entries" in capsys.readouterr().out


def test_main_activates_sealed_overlay_and_never_prints_raw_exception_text(
    monkeypatch,
    capsys,
):
    activation = []
    monkeypatch.setattr(
        importer,
        "_activate_sdk_overlay",
        lambda path, digest: (
            activation.append((path, digest))
            or {
                "status": "PASS",
                "process_path_activated": True,
                "shared_environment_mutated": False,
            }
        ),
    )
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
        "--sdk-overlay-manifest", "sealed-sdk.json",
        "--sdk-overlay-manifest-sha256", "a" * 64,
        "--confirm-source-acl-private",
        "--confirmation", importer.CONFIRMATION,
    ])

    assert status == 1
    assert activation == [("sealed-sdk.json", "a" * 64)]
    stderr = capsys.readouterr().err
    assert "RuntimeError" in stderr
    assert "RAW-SOURCE-SECRET" not in stderr

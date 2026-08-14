import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather.market import mm_live_pilot_cli as cli
from weather.market.mm_credentials import STAGE0_AUTHORIZATION
from weather.market.mm_geoblock import collect_official_geoblock_evidence
from weather.market.mm_live_lifecycle_probe import CONFIRMATION as STAGE1_CONFIRMATION


ADDRESS = "0x" + "a" * 40
CONDITION_ID = "0x" + "b" * 64
TOKEN_ID = "12345"


class FakeStream:
    def __init__(self, journal_path):
        self.started = False
        self.stopped = False
        self.rows = []
        self.journal_path = Path(journal_path)

    def start(self):
        self.started = True
        self.journal_path.write_text(
            '{"event_type":"subscription_sent"}\n',
            encoding="utf-8",
        )

    def stop(self):
        self.stopped = True
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write('{"event_type":"stream_stopped"}\n')

    def bootstrap_evidence(self):
        return {
            "account_wide_subscription_sent": self.started,
            "server_pong_observed": self.started,
            "transport_active": self.started and not self.stopped,
            "transport_state": (
                "STOPPED" if self.stopped else "TRANSPORT_CONNECTED_UNPROVEN"
            ),
            "journal_sha256": hashlib.sha256(self.journal_path.read_bytes()).hexdigest(),
        }

    def health(self):
        return {
            "state": "STOPPED" if self.stopped else "TRANSPORT_CONNECTED_UNPROVEN",
            "failure_type": None,
        }

    def events(self):
        return list(self.rows)


class FakeAdapter:
    maker_address = ADDRESS
    condition_id = CONDITION_ID

    def __init__(self):
        self.cancel_calls = 0

    def cancel_all(self):
        self.cancel_calls += 1
        return {"canceled": []}

    def open_orders(self):
        return []

    def positions(self):
        return []

    def position_evidence(self, positions):
        return {
            "status": "OBSERVED",
            "query_scope": "exact_maker_condition",
            "maker_address": ADDRESS,
            "condition_id": CONDITION_ID,
            "request_url": (
                "https://data-api.polymarket.com/positions?"
                f"user={ADDRESS}&market={CONDITION_ID}&sizeThreshold=0&limit=500&offset=0"
            ),
            "http_status": 200,
            "response_sha256": "c" * 64,
            "rows": list(positions),
        }


def context(tmp_path, name="context-stream.jsonl"):
    stream = FakeStream(tmp_path / name)
    adapter = FakeAdapter()
    return cli.LivePilotContext(
        credentials=object(),
        client=object(),
        user_stream=stream,
        adapter=adapter,
    )


def args(tmp_path, command):
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"public": "identity"}), encoding="utf-8")
    common = {
        "command": command,
        "identity": str(identity),
        "target_date": "2026-08-14",
        "condition_id": CONDITION_ID,
        "token_id": TOKEN_ID,
        "budget": 100.0,
        "user_stream_journal": str(tmp_path / f"{command}-stream.jsonl"),
        "receipt_out": str(tmp_path / f"{command}-receipt.json"),
        "user_stream_ready_timeout_seconds": 5.0,
    }
    if command == "stage0":
        common.update(
            confirmation=STAGE0_AUTHORIZATION,
            bootstrap_out=str(tmp_path / "bootstrap.json"),
        )
    else:
        bootstrap = tmp_path / "bootstrap-input.json"
        bootstrap.write_text("{}", encoding="utf-8")
        common.update(
            confirmation=STAGE1_CONFIRMATION,
            bootstrap=str(bootstrap),
            cancellation_mode="cancel_all",
            lifecycle_journal=str(tmp_path / "lifecycle.jsonl"),
            result_out=str(tmp_path / "stage1-result.json"),
        )
    return SimpleNamespace(**common)


def prepare_args(tmp_path):
    return SimpleNamespace(
        command="prepare-identity",
        funder_address=ADDRESS,
        wallet_type="deposit_wallet",
        signature_type="POLY_1271",
        budget=100.0,
        identity_out=str(tmp_path / "identity-prepared.json"),
        receipt_out=str(tmp_path / "identity-receipt.json"),
        confirm_international_platform=True,
        confirm_physical_location_match=True,
        confirm_no_circumvention=True,
        confirm_isolated_wallet=True,
        confirmation=cli.IDENTITY_CONFIRMATION,
    )


def doctor_args(tmp_path, identity_path):
    return SimpleNamespace(
        command="doctor",
        identity=str(identity_path),
        target_date="2026-08-14",
        condition_id=CONDITION_ID,
        token_id=TOKEN_ID,
        budget=100.0,
        receipt_out=str(tmp_path / "doctor-receipt.json"),
        confirmation=cli.DOCTOR_CONFIRMATION,
    )


def credential_reference_env():
    return {
        "POLYMARKET_API_KEY_STORAGE_REF": "wincred://Weather/Pilot/ApiKey",
        "POLYMARKET_API_SECRET_STORAGE_REF": "wincred://Weather/Pilot/ApiSecret",
        "POLYMARKET_API_PASSPHRASE_STORAGE_REF": "wincred://Weather/Pilot/Passphrase",
        "POLYMARKET_PRIVATE_KEY_STORAGE_REF": "wincred://Weather/Pilot/PrivateKey",
        "POLYMARKET_FUNDER_ADDRESS": ADDRESS,
    }


def geoblock_evidence(*, blocked=False):
    class Response:
        status = 200

        def read(self, _limit):
            return json.dumps(
                {
                    "blocked": blocked,
                    "country": "CH",
                    "region": "ZH",
                    "ip": "203.0.113.9",
                }
            ).encode("utf-8")

        def close(self):
            pass

    return collect_official_geoblock_evidence(
        opener=lambda _request, timeout: Response(),
        proxy_detector=lambda: {},
    )


def test_prepare_identity_fetches_ip_redacted_evidence_and_derives_signature_id(tmp_path):
    command_args = prepare_args(tmp_path)

    receipt = cli.run_prepare_identity(
        command_args,
        geoblock_collector=geoblock_evidence,
    )

    assert receipt["status"] == "PASS"
    identity = json.loads(Path(command_args.identity_out).read_text(encoding="utf-8"))
    raw = Path(command_args.identity_out).read_text(encoding="utf-8")
    assert identity["platform"] == "polymarket_global"
    assert identity["settlement_unit"] == "pUSD"
    assert identity["signature_type"] == "POLY_1271"
    assert identity["signature_type_id"] == 3
    assert identity["geographic_eligibility"]["blocked"] is False
    assert identity["geographic_eligibility"]["requesting_ip_retained"] is False
    assert "203.0.113.9" not in raw
    assert receipt["cleanup"]["reason"] == "read_only_command_no_exchange_authentication"


def test_prepare_identity_writes_fail_receipt_but_no_manifest_when_location_blocked(tmp_path):
    command_args = prepare_args(tmp_path)

    with pytest.raises(RuntimeError, match="did not pass"):
        cli.run_prepare_identity(
            command_args,
            geoblock_collector=lambda: geoblock_evidence(blocked=True),
        )

    assert not Path(command_args.identity_out).exists()
    receipt = json.loads(Path(command_args.receipt_out).read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"
    assert receipt["geographic_eligibility"]["blocked"] is True
    assert "physical_geo_eligibility" in receipt["missing"]


@pytest.mark.parametrize(
    ("wallet_type", "signature_type", "missing_check"),
    [
        ("eoa", "POLY_1271", "pilot_wallet_signature_topology"),
        ("deposit_wallet", "EOA", "pilot_wallet_signature_topology"),
        ("gnosis_safe", "POLY_1271", "pilot_wallet_signature_topology"),
    ],
)
def test_prepare_identity_rejects_non_deposit_wallet_topology(
    tmp_path,
    wallet_type,
    signature_type,
    missing_check,
):
    command_args = prepare_args(tmp_path)
    command_args.wallet_type = wallet_type
    command_args.signature_type = signature_type

    with pytest.raises(RuntimeError, match="did not pass"):
        cli.run_prepare_identity(command_args, geoblock_collector=geoblock_evidence)

    receipt = json.loads(Path(command_args.receipt_out).read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"
    assert missing_check in receipt["missing"]
    assert not Path(command_args.identity_out).exists()


def test_prepare_identity_accepts_existing_gnosis_safe_topology(tmp_path):
    command_args = prepare_args(tmp_path)
    command_args.wallet_type = "gnosis_safe"
    command_args.signature_type = "POLY_GNOSIS_SAFE"

    receipt = cli.run_prepare_identity(
        command_args,
        geoblock_collector=geoblock_evidence,
    )

    identity = json.loads(Path(command_args.identity_out).read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS"
    assert identity["wallet_type"] == "gnosis_safe"
    assert identity["signature_type"] == "POLY_GNOSIS_SAFE"
    assert identity["signature_type_id"] == 2


def test_prepare_identity_wrong_confirmation_does_not_fetch_geoblock(tmp_path):
    command_args = prepare_args(tmp_path)
    command_args.confirmation = "yes"
    called = False

    def collect():
        nonlocal called
        called = True
        return geoblock_evidence()

    with pytest.raises(RuntimeError, match="exact confirmation"):
        cli.run_prepare_identity(command_args, geoblock_collector=collect)

    assert called is False
    assert not Path(command_args.identity_out).exists()
    assert not Path(command_args.receipt_out).exists()


def test_keyless_doctor_passes_without_resolving_credential_targets(tmp_path):
    prepare = prepare_args(tmp_path)
    cli.run_prepare_identity(prepare, geoblock_collector=geoblock_evidence)
    command_args = doctor_args(tmp_path, prepare.identity_out)
    env = credential_reference_env()

    receipt = cli.run_doctor(
        command_args,
        env=env,
        sdk_version_getter=lambda: "1.1.0",
        platform_name="nt",
    )

    assert receipt["status"] == "PASS"
    assert receipt["missing"] == []
    assert receipt["credential_reference_present_count"] == 4
    raw = Path(command_args.receipt_out).read_text(encoding="utf-8")
    assert "Weather/Pilot" not in raw
    assert "wincred://" not in raw


def test_keyless_doctor_names_missing_sdk_and_reference_without_reading_secrets(tmp_path):
    prepare = prepare_args(tmp_path)
    cli.run_prepare_identity(prepare, geoblock_collector=geoblock_evidence)
    command_args = doctor_args(tmp_path, prepare.identity_out)
    env = credential_reference_env()
    del env["POLYMARKET_API_SECRET_STORAGE_REF"]

    with pytest.raises(RuntimeError, match="blocking setup checks"):
        cli.run_doctor(
            command_args,
            env=env,
            sdk_version_getter=lambda: None,
            platform_name="nt",
        )

    raw = Path(command_args.receipt_out).read_text(encoding="utf-8")
    receipt = json.loads(raw)
    assert receipt["status"] == "FAIL"
    assert "credential_reference_variables_complete" in receipt["missing"]
    assert "credential_reference_shapes_valid" in receipt["missing"]
    assert "official_sdk_exact_version_installed" in receipt["missing"]
    assert receipt["credential_reference_present_count"] == 3
    assert "Weather/Pilot" not in raw


def test_stage0_boundary_writes_bootstrap_only_after_zero_state_cleanup(tmp_path):
    command_args = args(tmp_path, "stage0")
    live_context = context(tmp_path)

    receipt = cli.run_stage0(
        command_args,
        context_builder=lambda *_args, **_kwargs: live_context,
        stream_waiter=lambda stream, **_kwargs: stream.start(),
        bootstrap_collector=lambda _adapter, stream, *_args, **_kwargs: {
            "schema_version": "mm_platform_bootstrap_v0.1",
            "status": "PASS",
            "secret_values_redacted": True,
            "user_stream": stream.bootstrap_evidence(),
        },
    )

    assert receipt["status"] == "PASS"
    assert live_context.adapter.cancel_calls == 1
    assert live_context.user_stream.stopped
    assert json.loads(open(command_args.bootstrap_out, encoding="utf-8").read())["status"] == "PASS"
    saved_receipt = json.loads(open(command_args.receipt_out, encoding="utf-8").read())
    assert saved_receipt["cleanup"]["zero_open_orders_verified"] is True
    assert saved_receipt["cleanup"]["zero_positions_verified"] is True
    final_sha256 = hashlib.sha256(live_context.user_stream.journal_path.read_bytes()).hexdigest()
    assert saved_receipt["cleanup"]["user_stream_journal_sha256"] == final_sha256
    assert saved_receipt["secret_values_redacted"] is True
    saved_bootstrap = json.loads(open(command_args.bootstrap_out, encoding="utf-8").read())
    assert saved_bootstrap["user_stream"]["transport_active_at_collection"] is True
    assert saved_bootstrap["user_stream"]["transport_stopped_cleanly_after_collection"] is True
    assert saved_bootstrap["user_stream"]["journal_sha256_at_collection"] != final_sha256
    assert saved_bootstrap["user_stream"]["journal_sha256"] == final_sha256


def test_stage1_boundary_writes_result_after_exact_gate_and_final_cleanup(tmp_path):
    command_args = args(tmp_path, "stage1")
    live_context = context(tmp_path)
    seen = {}

    def execute(adapter, gate, **kwargs):
        seen.update(gate=gate, kwargs=kwargs)
        kwargs["journal_path"].write_text('{"event_type":"probe_passed"}\n', encoding="utf-8")
        return {
            "schema_version": "mm_live_lifecycle_probe_v0.1",
            "status": "PASS",
            "secret_values_redacted": True,
        }

    receipt = cli.run_stage1(
        command_args,
        context_builder=lambda *_args, **_kwargs: live_context,
        stream_waiter=lambda stream, **_kwargs: stream.start(),
        bootstrap_loader=lambda *_args, **_kwargs: {
            "ok": True,
            "platform": "polymarket_global",
        },
        lifecycle_executor=execute,
    )

    assert receipt["status"] == "PASS"
    assert seen["kwargs"]["confirmation"] == STAGE1_CONFIRMATION
    assert seen["kwargs"]["cancellation_mode"] == "cancel_all"
    assert live_context.adapter.cancel_calls == 1
    assert live_context.user_stream.stopped
    assert json.loads(open(command_args.result_out, encoding="utf-8").read())["status"] == "PASS"


def test_stage1_failure_receipt_never_serializes_raw_exception_text(tmp_path):
    command_args = args(tmp_path, "stage1")
    live_context = context(tmp_path)

    with pytest.raises(RuntimeError, match="TOP-SECRET-SDK-TEXT"):
        cli.run_stage1(
            command_args,
            context_builder=lambda *_args, **_kwargs: live_context,
            stream_waiter=lambda stream, **_kwargs: stream.start(),
            bootstrap_loader=lambda *_args, **_kwargs: {"ok": True},
            lifecycle_executor=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("TOP-SECRET-SDK-TEXT")
            ),
        )

    raw = open(command_args.receipt_out, encoding="utf-8").read()
    receipt = json.loads(raw)
    assert receipt["status"] == "FAIL"
    assert receipt["exception_type"] == "RuntimeError"
    assert "TOP-SECRET-SDK-TEXT" not in raw
    assert live_context.adapter.cancel_calls == 1


def test_stage1_result_write_failure_still_emits_fail_receipt(
    tmp_path,
    monkeypatch,
):
    command_args = args(tmp_path, "stage1")
    live_context = context(tmp_path)
    real_writer = cli.write_json_atomic

    def writer(path, payload, **kwargs):
        if Path(path) == Path(command_args.result_out):
            raise OSError("RAW-RESULT-WRITE-DETAIL")
        return real_writer(path, payload, **kwargs)

    monkeypatch.setattr(cli, "write_json_atomic", writer)

    with pytest.raises(OSError, match="RAW-RESULT-WRITE-DETAIL"):
        cli.run_stage1(
            command_args,
            context_builder=lambda *_args, **_kwargs: live_context,
            stream_waiter=lambda stream, **_kwargs: stream.start(),
            bootstrap_loader=lambda *_args, **_kwargs: {"ok": True},
            lifecycle_executor=lambda *_args, **_kwargs: {
                "schema_version": "mm_live_lifecycle_probe_v0.1",
                "status": "PASS",
                "secret_values_redacted": True,
            },
        )

    raw = Path(command_args.receipt_out).read_text(encoding="utf-8")
    receipt = json.loads(raw)
    assert receipt["status"] == "FAIL"
    assert receipt["exception_type"] == "OSError"
    assert "RAW-RESULT-WRITE-DETAIL" not in raw
    assert not Path(command_args.result_out).exists()


def test_offline_bundle_command_binds_both_results_without_exchange_cleanup(tmp_path):
    command_args = args(tmp_path, "stage1")
    cancel_result = tmp_path / "cancel-result.json"
    dead_result = tmp_path / "dead-result.json"
    cancel_result.write_text(json.dumps({"mode": "cancel_all"}), encoding="utf-8")
    dead_result.write_text(json.dumps({"mode": "dead_man"}), encoding="utf-8")
    command_args.command = "bundle"
    command_args.confirmation = cli.BUNDLE_CONFIRMATION
    command_args.cancel_all_result = str(cancel_result)
    command_args.dead_man_result = str(dead_result)
    command_args.bundle_out = str(tmp_path / "bundle.json")
    command_args.receipt_out = str(tmp_path / "bundle-receipt.json")
    seen = {}

    def builder(gate, cancel_all, dead_man):
        seen.update(gate=gate, cancel_all=cancel_all, dead_man=dead_man)
        return {
            "schema_version": "mm_stage1_lifecycle_bundle_v0.1",
            "status": "PASS",
        }

    receipt = cli.run_bundle(
        command_args,
        bootstrap_loader=lambda *_args, **_kwargs: {"ok": True},
        bundle_builder=builder,
    )

    assert receipt["status"] == "PASS"
    assert seen["cancel_all"]["mode"] == "cancel_all"
    assert seen["dead_man"]["mode"] == "dead_man"
    assert json.loads(open(command_args.bundle_out, encoding="utf-8").read())["status"] == "PASS"
    saved_receipt = json.loads(open(command_args.receipt_out, encoding="utf-8").read())
    assert saved_receipt["cleanup"]["reason"] == "offline_command_no_exchange_state"


def test_wrong_confirmation_stops_before_credentials_or_mutation(tmp_path):
    command_args = args(tmp_path, "stage1")
    command_args.confirmation = "yes"
    called = False

    def build(*_args, **_kwargs):
        nonlocal called
        called = True
        return context(tmp_path)

    with pytest.raises(RuntimeError, match="exact lifecycle confirmation"):
        cli.run_stage1(command_args, context_builder=build)

    assert called is False
    assert not (tmp_path / "stage1-receipt.json").exists()
    assert not (tmp_path / "stage1-result.json").exists()


def test_output_directories_are_proved_writable_before_context_construction(tmp_path):
    command_args = args(tmp_path, "stage1")
    output_root = tmp_path / "new" / "protected-pilot"
    command_args.result_out = str(output_root / "result.json")
    command_args.receipt_out = str(output_root / "receipt.json")
    command_args.user_stream_journal = str(output_root / "stream.jsonl")
    command_args.lifecycle_journal = str(output_root / "lifecycle.jsonl")
    called = False

    def build(*_args, **_kwargs):
        nonlocal called
        called = True
        raise RuntimeError("stop after storage preflight")

    with pytest.raises(RuntimeError, match="stop after storage preflight"):
        cli.run_stage1(
            command_args,
            context_builder=build,
            bootstrap_loader=lambda *_args, **_kwargs: {"ok": True},
        )

    assert called is True
    assert output_root.is_dir()
    assert list(output_root.iterdir()) == [output_root / "receipt.json"]
    receipt = json.loads((output_root / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"


def test_context_wires_only_in_memory_secrets_and_exact_readers(tmp_path):
    class Credentials:
        api_key = "key-secret"
        api_secret = "api-secret"
        api_passphrase = "pass-secret"
        private_key = "private-secret"
        funder = ADDRESS

    captured = {}

    class StreamFactory(FakeStream):
        def __init__(self, **kwargs):
            super().__init__(kwargs["journal_path"])
            captured["stream"] = kwargs

    class AdapterFactory:
        def __init__(self, client, **kwargs):
            captured["adapter_client"] = client
            captured["adapter"] = kwargs

        def diagnostics(self):
            return {"supports_trading": True}

    def position_fetcher(maker, condition):
        captured["position_scope"] = (maker, condition)
        return {"rows": []}

    client = object()
    result = cli.build_live_pilot_context(
        {"identity": "public"},
        token_id=TOKEN_ID,
        condition_id=CONDITION_ID,
        user_stream_journal=tmp_path / "stream.jsonl",
        credential_loader=lambda _env: Credentials(),
        client_builder=lambda credentials, identity: client,
        user_stream_factory=StreamFactory,
        adapter_factory=AdapterFactory,
        position_fetcher=position_fetcher,
    )

    assert repr(result) == (
        "LivePilotContext(credentials=<redacted>, client=<redacted>, stream=<redacted>)"
    )
    assert captured["adapter"]["authoritative_readers_verified"] is True
    assert captured["adapter"]["max_order_notional"] == 10.0
    assert captured["stream"]["journal_path"] == tmp_path / "stream.jsonl"
    captured["adapter"]["position_reader"]()
    assert captured["position_scope"] == (ADDRESS, CONDITION_ID)


@pytest.mark.parametrize("command", ["stage0", "stage1", "stage2"])
def test_parser_does_not_expose_exchange_mutation_commands(command):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args([command])

    assert exc.value.code == 2


def test_main_reports_only_exception_type_not_raw_message(monkeypatch, capsys, tmp_path):
    identity = tmp_path / "identity.json"
    identity.write_text("{}", encoding="utf-8")
    argv = [
        "doctor",
        "--identity", str(identity),
        "--target-date", "2026-08-14",
        "--condition-id", CONDITION_ID,
        "--token-id", TOKEN_ID,
        "--budget", "100",
        "--receipt-out", str(tmp_path / "doctor-receipt.json"),
        "--confirmation", cli.DOCTOR_CONFIRMATION,
    ]
    monkeypatch.setattr(
        cli,
        "run_doctor",
        lambda _args: (_ for _ in ()).throw(RuntimeError("RAW-SECRET-MESSAGE")),
    )

    assert cli.main(argv) == 1
    stderr = capsys.readouterr().err
    assert "RuntimeError" in stderr
    assert "RAW-SECRET-MESSAGE" not in stderr

import hashlib
import json
from pathlib import Path

import pytest

from weather.backtesting.settlement_io import (
    LEDGER_AUTHORITY_STATUS,
    SIDECAR_FALLBACK_STATUS,
    SettlementAuthorityError,
    resolve_market_day_label,
)


SLUG = "highest-temperature-in-toronto-on-may-27-2026"
TARGET_DATE = "2026-05-27"


def _write_case(tmp_path, monkeypatch, *, ledger_overrides=None):
    ledger_root = tmp_path / "settlements"
    monkeypatch.setenv("SETTLEMENT_LEDGER_ROOT", str(ledger_root))
    folder = tmp_path / "snapshots" / SLUG
    folder.mkdir(parents=True)
    tape = folder / "snapshots_long.csv"
    tape.write_text(
        "snapshot_id,range_label\nsnapshot-1,20 C\n",
        encoding="utf-8",
    )
    (folder / "settlement.json").write_text(
        json.dumps(
            {
                "event_slug": SLUG,
                "target_date": TARGET_DATE,
                "settlement_bucket": 99,
            }
        ),
        encoding="utf-8",
    )
    ledger_row = {
        "event_slug": SLUG,
        "market_id": "toronto",
        "target_date": TARGET_DATE,
        "settlement_bucket": 20,
        "snapshot_tape_path": (
            "C:\\production\\weather\\data\\snapshots\\"
            f"{SLUG}\\snapshots_long.csv"
        ),
        "evidence": {
            "raw_resolution_hashes": {
                "snapshot_tape_sha256": hashlib.sha256(tape.read_bytes()).hexdigest(),
            }
        },
    }
    ledger_row.update(ledger_overrides or {})
    ledger = ledger_root / "toronto" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps(ledger_row) + "\n", encoding="utf-8")
    return folder


def _forbid_sidecar_read(monkeypatch):
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        if path.name == "settlement.json":
            raise AssertionError("ledger authority failure must not read the sidecar")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)


def test_relocated_ledger_root_uses_matching_tape_content_identity(
    tmp_path, monkeypatch
):
    folder = _write_case(tmp_path, monkeypatch)

    resolved = resolve_market_day_label(folder)

    assert resolved["label"]["settlement_bucket"] == 20
    assert resolved["authority"] == {
        "status": LEDGER_AUTHORITY_STATUS,
        "ledger_row_exists": True,
        "sidecar_fallback": False,
    }


def test_bad_tape_hash_blocks_even_when_recorded_path_matches_and_never_falls_back(
    tmp_path, monkeypatch
):
    folder = _write_case(
        tmp_path,
        monkeypatch,
        ledger_overrides={
            "snapshot_tape_path": str(
                tmp_path / "snapshots" / SLUG / "snapshots_long.csv"
            ),
            "evidence": {
                "raw_resolution_hashes": {"snapshot_tape_sha256": "0" * 64}
            },
        },
    )
    _forbid_sidecar_read(monkeypatch)

    with pytest.raises(SettlementAuthorityError, match="tape binding is invalid"):
        resolve_market_day_label(folder)


def test_identityless_ledger_row_blocks_without_sidecar_fallback(
    tmp_path, monkeypatch
):
    folder = _write_case(
        tmp_path,
        monkeypatch,
        ledger_overrides={
            "snapshot_tape_path": None,
            "evidence": {},
        },
    )
    _forbid_sidecar_read(monkeypatch)

    with pytest.raises(SettlementAuthorityError, match="tape binding is invalid"):
        resolve_market_day_label(folder)


def test_absolute_only_tape_identity_blocks_even_at_the_recorded_location(
    tmp_path, monkeypatch
):
    folder = _write_case(
        tmp_path,
        monkeypatch,
        ledger_overrides={
            "snapshot_tape_path": str(
                tmp_path / "snapshots" / SLUG / "snapshots_long.csv"
            ),
            "evidence": {},
        },
    )
    _forbid_sidecar_read(monkeypatch)

    with pytest.raises(SettlementAuthorityError, match="tape binding is invalid"):
        resolve_market_day_label(folder)


@pytest.mark.parametrize("recorded_date", (None, "2026-05-28"))
def test_missing_or_mismatched_ledger_target_date_blocks_without_sidecar_fallback(
    tmp_path, monkeypatch, recorded_date
):
    folder = _write_case(
        tmp_path,
        monkeypatch,
        ledger_overrides={"target_date": recorded_date},
    )
    _forbid_sidecar_read(monkeypatch)

    with pytest.raises(SettlementAuthorityError, match="target_date is invalid"):
        resolve_market_day_label(folder)


@pytest.mark.parametrize(
    ("ledger_text", "message"),
    (
        ('{"event_slug":\n', "invalid JSON"),
        ('["not", "an", "object"]\n', "not an object"),
        (
            f'{{"event_slug":"{SLUG}","event_slug":"hidden"}}\n',
            "duplicate JSON key",
        ),
        (
            f'{{"event_slug":"{SLUG}","settlement_bucket":NaN}}\n',
            "non-finite JSON constant",
        ),
    ),
)
def test_corrupt_ledger_blocks_before_valid_sidecar_can_be_read(
    tmp_path, monkeypatch, ledger_text, message
):
    folder = _write_case(tmp_path, monkeypatch)
    ledger = tmp_path / "settlements" / "toronto" / "ledger.jsonl"
    ledger.write_text(ledger_text, encoding="utf-8")
    _forbid_sidecar_read(monkeypatch)

    with pytest.raises(SettlementAuthorityError, match=message):
        resolve_market_day_label(folder)


def test_non_utf8_ledger_blocks_before_valid_sidecar_can_be_read(
    tmp_path, monkeypatch
):
    folder = _write_case(tmp_path, monkeypatch)
    ledger = tmp_path / "settlements" / "toronto" / "ledger.jsonl"
    ledger.write_bytes(b"\xff\n")
    _forbid_sidecar_read(monkeypatch)

    with pytest.raises(SettlementAuthorityError, match="not valid UTF-8"):
        resolve_market_day_label(folder)


def test_inaccessible_ledger_is_not_misclassified_as_absent(tmp_path, monkeypatch):
    folder = _write_case(tmp_path, monkeypatch)
    ledger = tmp_path / "settlements" / "toronto" / "ledger.jsonl"
    original_stat = Path.stat

    def guarded_stat(path, *args, **kwargs):
        if path == ledger:
            raise PermissionError("test-denied ledger")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", guarded_stat)
    _forbid_sidecar_read(monkeypatch)

    with pytest.raises(SettlementAuthorityError, match="ledger is unreadable"):
        resolve_market_day_label(folder)


def test_unknown_slug_scans_ledgers_and_never_bypasses_an_existing_row(
    tmp_path, monkeypatch
):
    folder = _write_case(tmp_path, monkeypatch)
    legacy_slug = "legacy-temperature-market-on-may-27-2026"
    legacy_folder = folder.with_name(legacy_slug)
    folder.rename(legacy_folder)
    sidecar = legacy_folder / "settlement.json"
    sidecar_payload = json.loads(sidecar.read_text(encoding="utf-8"))
    sidecar_payload["event_slug"] = legacy_slug
    sidecar.write_text(json.dumps(sidecar_payload), encoding="utf-8")
    ledger = tmp_path / "settlements" / "toronto" / "ledger.jsonl"
    ledger_payload = json.loads(ledger.read_text(encoding="utf-8"))
    ledger_payload["event_slug"] = legacy_slug
    ledger.write_text(json.dumps(ledger_payload) + "\n", encoding="utf-8")
    _forbid_sidecar_read(monkeypatch)

    with pytest.raises(SettlementAuthorityError, match="target_date is invalid"):
        resolve_market_day_label(legacy_folder)


def test_failed_ledger_history_integrity_blocks_without_sidecar_fallback(
    tmp_path, monkeypatch
):
    folder = _write_case(
        tmp_path,
        monkeypatch,
        ledger_overrides={
            "ledger_record_type": "settlement_revision",
            "revision_number": 1,
            "revision_id": "sha256:" + "0" * 64,
            "recorded_at_utc": "2026-05-28T00:00:00+00:00",
            "label_hash": "0" * 64,
            "revision_changes": [],
        },
    )
    _forbid_sidecar_read(monkeypatch)

    with pytest.raises(SettlementAuthorityError, match="history integrity failure"):
        resolve_market_day_label(folder)


def test_wrong_market_id_blocks_without_sidecar_fallback(tmp_path, monkeypatch):
    folder = _write_case(
        tmp_path,
        monkeypatch,
        ledger_overrides={"market_id": "atlanta"},
    )
    _forbid_sidecar_read(monkeypatch)

    with pytest.raises(SettlementAuthorityError, match="market_id is invalid"):
        resolve_market_day_label(folder)


def test_sidecar_fallback_is_loud_only_when_no_ledger_row(tmp_path, monkeypatch):
    ledger_root = tmp_path / "settlements"
    monkeypatch.setenv("SETTLEMENT_LEDGER_ROOT", str(ledger_root))
    folder = tmp_path / "snapshots" / SLUG
    folder.mkdir(parents=True)
    (folder / "settlement.json").write_text(
        json.dumps({"event_slug": SLUG, "settlement_bucket": 21}),
        encoding="utf-8",
    )

    resolved = resolve_market_day_label(folder)

    assert resolved["label"]["settlement_bucket"] == 21
    assert resolved["authority"] == {
        "status": SIDECAR_FALLBACK_STATUS,
        "ledger_row_exists": False,
        "sidecar_fallback": True,
    }

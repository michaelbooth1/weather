from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from weather.operations import wu_outcome_export_contract as contract


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _request(market: str = "atlanta", target_date: str = "2026-06-03") -> dict:
    return {
        "market": market,
        "target_date": target_date,
        "provenance_side": (
            "post_boundary_directional"
            if target_date >= "2026-07-31"
            else "pre_boundary"
        ),
        "local_status": "missing",
        "station": "katl",
        "settlement_unit": "F",
    }


def _row(request: dict) -> dict:
    digest = "a" * 64
    return {
        "schema_version": contract.EXPORT_ROW_SCHEMA,
        "market": request["market"],
        "target_date": request["target_date"],
        "provenance_side": request["provenance_side"],
        "settlement_bucket_native": 80,
        "settlement_unit": request["settlement_unit"],
        "wu_daily_row_count": 24,
        "settlement_source": "daily_summary",
        "resolution_source_type": "wunderground_history",
        "resolution_wu_history_id": "KATL:9:US",
        "resolution_station": request["station"],
        "resolution_timezone": "America/New_York",
        "source_event_slug": "highest-temperature-in-atlanta-on-june-3-2026",
        "source_revision_id": "revision-1",
        "source_revision_number": 1,
        "source_recorded_at_utc": "2026-09-04T00:00:00+00:00",
        "source_label_hash": "b" * 64,
        "source_ledger_relative_path": "atlanta/ledger.jsonl",
        "source_ledger_sha256": digest,
        "source_daily_summary_relative_path": "wunderground/katl/daily/daily_summary.csv",
        "source_daily_summary_sha256": digest,
    }


def _make_export(
    tmp_path: Path,
    requests: list[dict] | None = None,
    rows: list[dict] | None = None,
) -> tuple[Path, Path, dict, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    requests = requests or [_request()]
    rows = rows or [_row(request) for request in requests]
    spec = {
        "schema_version": contract.SPEC_SCHEMA,
        "gap_binding": {"self_hash": "c" * 64},
        "request": {"requested_rows": len(requests), "keys": requests},
    }
    spec["spec_sha256"] = contract.self_hash(spec, "spec_sha256")
    spec_path = tmp_path / "spec.json"
    _write_json(spec_path, spec)

    export_root = tmp_path / "export"
    export_root.mkdir()
    payload_path = export_root / "wu-outcomes.jsonl"
    raw = b"".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        for row in rows
    )
    payload_path.write_bytes(raw)
    sddl = "O:SYG:SYD:(A;;FA;;;SY)"
    manifest = {
        "schema_version": contract.EXPORT_MANIFEST_SCHEMA,
        "status": "COMPLETE_CREATE_ONLY_EXPORT",
        "spec_sha256": spec["spec_sha256"],
        "gap_manifest_sha256": spec["gap_binding"]["self_hash"],
        "requested_rows": len(requests),
        "exported_rows": len(requests),
        "destination_acl_proof": {
            "owner": "SYSTEM",
            "sddl": sddl,
            "sddl_sha256": hashlib.sha256(sddl.encode("utf-8")).hexdigest(),
        },
        "payload_file": {
            "relative_path": "wu-outcomes.jsonl",
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "rows": len(rows),
        },
        "source_files": [
            {
                "role": "settlement_ledger",
                "relative_path": "atlanta/ledger.jsonl",
                "bytes_before": 123,
                "bytes_after": 123,
                "sha256_before": "a" * 64,
                "sha256_after": "a" * 64,
            },
            {
                "role": "wu_daily_summary",
                "relative_path": "wunderground/katl/daily/daily_summary.csv",
                "bytes_before": 456,
                "bytes_after": 456,
                "sha256_before": "a" * 64,
                "sha256_after": "a" * 64,
            },
        ],
    }
    manifest["manifest_sha256"] = contract.self_hash(manifest, "manifest_sha256")
    _write_json(export_root / "manifest.json", manifest)
    return spec_path, export_root, spec, manifest


def _reseal_manifest(export_root: Path, manifest: dict, rows: list[dict]) -> None:
    raw = b"".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        for row in rows
    )
    (export_root / "wu-outcomes.jsonl").write_bytes(raw)
    manifest["payload_file"] = {
        "relative_path": "wu-outcomes.jsonl",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "rows": len(rows),
    }
    manifest["manifest_sha256"] = contract.self_hash(manifest, "manifest_sha256")
    _write_json(export_root / "manifest.json", manifest)


def test_support_classification_and_latest_revision_are_value_blind(tmp_path: Path) -> None:
    source = tmp_path / "daily.csv"
    source.write_text(
        "schema_version,local_date,temperature_unit,row_count,max_temp_native\n"
        "wu_daily_native_v2,2026-06-03,F,17,77\n"
        "wu_daily_native_v2,2026-06-03,F,24,999\n",
        encoding="utf-8",
    )
    selected = contract._read_wu_support(source, "F")
    assert selected["2026-06-03"]["row_count"] == 24
    assert selected["2026-06-03"]["revision_count"] == 2
    assert "max_temp_native" not in selected["2026-06-03"]
    assert contract.classify_wu_support(None)[0] == "missing"
    assert contract.classify_wu_support({"row_count": 17})[0] == "present_below_threshold"
    assert contract.classify_wu_support({"row_count": 18})[0] == "present_admissible"


def test_gap_contract_has_all_keys_and_rejects_outcome_content() -> None:
    payload = {
        "schema_version": contract.GAP_SCHEMA,
        "entries": [{"market": "atlanta", "status": "missing"} for _ in range(816)],
        "outcome_values_read": 0,
        "outcome_fields_accessed": [],
    }
    payload["gap_manifest_sha256"] = contract.self_hash(payload, "gap_manifest_sha256")
    contract._validate_gap(payload)
    payload["entries"][0]["settlement_bucket_native"] = 80
    payload["gap_manifest_sha256"] = contract.self_hash(payload, "gap_manifest_sha256")
    with pytest.raises(contract.ContractError, match="outcome-bearing"):
        contract._validate_gap(payload)


def test_authoritative_revision_dedup_and_collisions() -> None:
    rows = [
        {"market_id": "atlanta", "target_date": "2026-06-03", "revision_number": 1, "value": "old"},
        {"market_id": "atlanta", "target_date": "2026-06-03", "revision_number": 2, "value": "new"},
    ]
    assert contract.latest_authoritative_ledger_rows(rows)[("atlanta", "2026-06-03")]["value"] == "new"
    with pytest.raises(contract.ContractError, match="conflicting duplicate"):
        contract.latest_authoritative_ledger_rows(
            [rows[0], {**rows[0], "value": "different"}]
        )
    with pytest.raises(contract.ContractError, match="case collision"):
        contract.latest_authoritative_ledger_rows(
            [rows[0], {**rows[0], "market_id": "Atlanta"}]
        )


def test_create_only_and_containment_fail_closed(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    contract.write_json_create_only(output, {"status": "PASS"})
    with pytest.raises(contract.ContractError, match="already exists"):
        contract.write_json_create_only(output, {"status": "PASS"})
    with pytest.raises(contract.ContractError, match="portable relative"):
        contract._contained(tmp_path, "../escape.json", "test")


def test_valid_export_and_boundary_pass(tmp_path: Path) -> None:
    request = _request(target_date="2026-07-31")
    spec_path, export_root, _, _ = _make_export(tmp_path, [request])
    result = contract.validate_export(spec_path=spec_path, export_root=export_root)
    assert result["status"] == "PASS"
    assert result["validated_rows"] == 1
    assert result["outcome_values_reported"] == 0


@pytest.mark.parametrize("failure", ["absent", "duplicate", "below", "boundary"])
def test_export_row_failures(failure: str, tmp_path: Path) -> None:
    requests = [_request()]
    spec_path, export_root, _, manifest = _make_export(tmp_path, requests)
    row = _row(requests[0])
    if failure == "absent":
        rows = []
    elif failure == "duplicate":
        rows = [row, dict(row)]
    elif failure == "below":
        rows = [{**row, "wu_daily_row_count": 17}]
    else:
        rows = [{**row, "provenance_side": "post_boundary_directional"}]
    _reseal_manifest(export_root, manifest, rows)
    with pytest.raises(contract.ContractError):
        contract.validate_export(spec_path=spec_path, export_root=export_root)


def test_manifest_and_payload_tampering_fail_closed(tmp_path: Path) -> None:
    spec_path, export_root, _, _ = _make_export(tmp_path)
    manifest_path = export_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["requested_rows"] = 2
    _write_json(manifest_path, manifest)
    with pytest.raises(contract.ContractError, match="self-hash"):
        contract.validate_export(spec_path=spec_path, export_root=export_root)

    spec_path, export_root, _, _ = _make_export(tmp_path / "second")
    with (export_root / "wu-outcomes.jsonl").open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(contract.ContractError, match="byte count"):
        contract.validate_export(spec_path=spec_path, export_root=export_root)


def test_reparse_export_root_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec_path, export_root, _, _ = _make_export(tmp_path)
    original = contract._is_reparse
    monkeypatch.setattr(
        contract,
        "_is_reparse",
        lambda path: path == export_root or original(path),
    )
    with pytest.raises(contract.ContractError, match="reparse point"):
        contract.validate_export(spec_path=spec_path, export_root=export_root)

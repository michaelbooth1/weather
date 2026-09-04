from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from weather.market.market_registry import BUILTIN_SPECS
from weather.operations import wu_outcome_export_contract as contract
from weather.operations import wu_outcome_production_exporter as exporter


DATES = (
    "2026-06-15",
    "2026-06-16",
    "2026-06-17",
    "2026-06-18",
    "2026-06-24",
    "2026-06-25",
    "2026-06-26",
    "2026-08-08",
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=True) + "\n",
        encoding="utf-8",
    )


def _write_ledger(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, allow_nan=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def _daily_text(unit: str, buckets: dict[str, int], counts: dict[str, int] | None = None) -> str:
    counts = counts or {}
    lines = [
        "schema_version,local_date,temperature_unit,row_count,max_temp_bucket_native\n"
    ]
    for target, bucket in buckets.items():
        lines.append(
            f"wu_daily_native_v2,{target},{unit},{counts.get(target, 24)},{bucket}\n"
        )
    return "".join(lines)


def _base_label(repo_relative_market: str, configured, target: str, bucket: int) -> dict:
    ledger_relative = f"data/settlements/{repo_relative_market}/ledger.jsonl"
    daily_relative = (
        f"data/wunderground/{configured.icao.casefold()}/daily/daily_summary.csv"
    )
    return {
        "schema_version": "settlement_ledger_v2",
        "event_slug": exporter._event_slug(configured, contract.date.fromisoformat(target)),
        "market_id": repo_relative_market,
        "target_date": target,
        "settlement_bucket": bucket,
        "settlement_unit": configured.display_unit,
        "settlement_source": "daily_summary",
        "resolution_source_type": "wunderground_history",
        "resolution_wu_history_id": configured.wu_history_id,
        "resolution_station": configured.icao,
        "resolution_timezone": configured.timezone,
        "daily_max_window": "00:00:00-23:59:59 local",
        "rounding": "round_half_up whole degree",
        "daily_summary_path": daily_relative,
        "ledger_path": ledger_relative,
        "evidence": {
            "summary": {
                "bucket": bucket,
                "row_count": 24,
                "path": daily_relative,
            }
        },
        "note": "synthetic label",
        "finalized_at_utc": "2026-09-04T00:00:00+00:00",
    }


def _explicit_revision(previous: dict, current: dict, number: int = 1) -> dict:
    recorded_at = f"2026-09-04T00:00:0{number}+00:00"
    label_hash = exporter._label_hash(current)
    supersedes = exporter._revision_id(previous)
    seed = {
        "event_slug": current["event_slug"],
        "revision_number": number,
        "recorded_at_utc": recorded_at,
        "label_hash": label_hash,
        "supersedes_revision_id": supersedes,
    }
    row = dict(current)
    row.update(
        {
            "ledger_record_type": "settlement_revision",
            "revision_id": f"sha256:{exporter._ledger_canonical_sha256(seed)}",
            "revision_number": number,
            "recorded_at_utc": recorded_at,
            "supersedes_revision_id": supersedes,
            "previous_label_hash": exporter._label_hash(previous),
            "label_hash": label_hash,
            "revision_changes": exporter._revision_changes(previous, current),
            "revision_provenance": {},
        }
    )
    return row


def _make_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    repo_root = (tmp_path / "repo").absolute()
    repo_root.mkdir(parents=True)
    configured = {item.id: item for item in BUILTIN_SPECS}
    requests = []
    ledger_paths = {}
    daily_paths = {}
    for market in sorted(configured):
        market_spec = configured[market]
        buckets = {
            target: 20 + index + (0 if market_spec.display_unit == "C" else 50)
            for index, target in enumerate(DATES)
        }
        ledger_path = repo_root / "data" / "settlements" / market / "ledger.jsonl"
        daily_path = (
            repo_root
            / "data"
            / "wunderground"
            / market_spec.icao.casefold()
            / "daily"
            / "daily_summary.csv"
        )
        daily_path.parent.mkdir(parents=True, exist_ok=True)
        daily_path.write_text(
            _daily_text(market_spec.display_unit, buckets), encoding="utf-8"
        )
        rows = [
            _base_label(market, market_spec, target, buckets[target])
            for target in DATES
        ]
        if market == "atlanta":
            original = rows[0]
            revised = {**original, "note": "synthetic explicit current label"}
            rows.insert(1, _explicit_revision(original, revised))
        if market == "austin":
            original = rows[0]
            rows.insert(1, {**original, "note": "synthetic append-order current label"})
        _write_ledger(ledger_path, rows)
        ledger_paths[market] = ledger_path
        daily_paths[market] = daily_path
        for target in DATES:
            requests.append(
                {
                    "market": market,
                    "target_date": target,
                    "provenance_side": (
                        "post_boundary_directional"
                        if target >= "2026-07-31"
                        else "pre_boundary"
                    ),
                    "local_status": "missing",
                    "station": market_spec.icao.casefold(),
                    "settlement_unit": market_spec.display_unit,
                }
            )
    spec = {
        "schema_version": contract.SPEC_SCHEMA,
        "gap_binding": {
            "self_hash": exporter.TRACKED_GAP_SELF_SHA256,
            "file_sha256": exporter.TRACKED_GAP_FILE_SHA256,
        },
        "request": {"requested_rows": 96, "keys": requests},
        "downstream_authority": {
            "model_refit_authorized": False,
            "probability_generation_authorized": False,
            "scoring_authorized": False,
            "promotion_authorized": False,
            "live_use_authorized": False,
        },
    }
    spec["spec_sha256"] = contract.self_hash(spec, "spec_sha256")
    spec_path = repo_root / "synthetic-spec.json"
    _write_json(spec_path, spec)
    monkeypatch.setattr(exporter, "_load_frozen_spec", lambda _root, _path: spec)
    output_parent = (tmp_path / "outside").absolute()
    output_parent.mkdir()
    return {
        "repo": repo_root,
        "spec": spec,
        "spec_path": spec_path,
        "destination": output_parent / "export",
        "ledgers": ledger_paths,
        "dailies": daily_paths,
    }


def _invoke(case: dict) -> dict:
    return contract.export_production(
        repo_root=case["repo"],
        spec_path=case["spec_path"],
        destination=case["destination"],
    )


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _git(root: Path, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", os.fspath(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=30,
    )
    assert result.returncode == expected, result.stderr
    return result


def _commit(root: Path, message: str) -> None:
    _git(
        root,
        "-c",
        "user.name=Synthetic Test",
        "-c",
        "user.email=synthetic@example.invalid",
        "commit",
        "-m",
        message,
    )


def _write_sources_for_spec(repo_root: Path, spec: dict) -> list[int]:
    configured = {item.id: item for item in BUILTIN_SPECS}
    synthetic_values: list[int] = []
    requests_by_market: dict[str, list[dict]] = {}
    for request in spec["request"]["keys"]:
        requests_by_market.setdefault(request["market"], []).append(request)
    for market_index, market in enumerate(sorted(configured)):
        market_spec = configured[market]
        requests = requests_by_market[market]
        buckets = {
            request["target_date"]: 700_000 + market_index * 100 + date_index
            for date_index, request in enumerate(requests)
        }
        synthetic_values.extend(buckets.values())
        ledger_path = repo_root / "data" / "settlements" / market / "ledger.jsonl"
        daily_path = (
            repo_root
            / "data"
            / "wunderground"
            / market_spec.icao.casefold()
            / "daily"
            / "daily_summary.csv"
        )
        daily_path.parent.mkdir(parents=True, exist_ok=True)
        daily_path.write_text(
            _daily_text(market_spec.display_unit, buckets), encoding="utf-8"
        )
        _write_ledger(
            ledger_path,
            [
                _base_label(
                    market,
                    market_spec,
                    request["target_date"],
                    buckets[request["target_date"]],
                )
                for request in requests
            ],
        )
    return synthetic_values


def _make_split_root_case(tmp_path: Path) -> dict:
    data_root = (tmp_path / "data-root").absolute()
    spec_root = (tmp_path / "spec-root").absolute()
    data_root.mkdir(parents=True)
    _git(data_root, "init")
    (data_root / ".gitignore").write_text("data/\n", encoding="utf-8")
    _git(data_root, "add", "--", ".gitignore")
    _commit(data_root, "synthetic base")
    _git(data_root, "worktree", "add", "-b", "synthetic-spec", os.fspath(spec_root))

    source_spec = Path(__file__).resolve().parents[2].joinpath(
        *exporter.TRACKED_SPEC_RELATIVE.parts
    )
    spec_path = spec_root.joinpath(*exporter.TRACKED_SPEC_RELATIVE.parts)
    spec_path.parent.mkdir(parents=True)
    spec_path.write_bytes(source_spec.read_bytes())
    _git(spec_root, "add", "--", exporter.TRACKED_SPEC_RELATIVE.as_posix())
    _commit(spec_root, "track frozen synthetic-test spec")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    synthetic_values = _write_sources_for_spec(data_root, spec)
    output_parent = (tmp_path / "outside").absolute()
    output_parent.mkdir()
    return {
        "data_root": data_root,
        "spec_root": spec_root,
        "spec_path": spec_path,
        "spec": spec,
        "synthetic_values": synthetic_values,
        "output_parent": output_parent,
    }


def test_frozen_spec_is_exact_tracked_file() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    spec_path = repo_root.joinpath(*exporter.TRACKED_SPEC_RELATIVE.parts)
    spec = exporter._load_frozen_spec(repo_root, spec_path)
    assert spec["spec_sha256"] == exporter.TRACKED_SPEC_SELF_SHA256
    assert len(spec["request"]["keys"]) == 96


def test_public_cli_exports_with_distinct_clean_data_and_spec_worktrees(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = _make_split_root_case(tmp_path)
    destinations = [case["output_parent"] / "first", case["output_parent"] / "second"]
    for destination in destinations:
        assert contract.main(
            [
                "export-production",
                "--repo-root",
                os.fspath(case["data_root"]),
                "--spec",
                os.fspath(case["spec_path"]),
                "--destination",
                os.fspath(destination),
            ]
        ) == 0
    captured = capsys.readouterr()
    assert all(
        str(value) not in captured.out + captured.err
        for value in case["synthetic_values"]
    )
    assert (destinations[0] / "manifest.json").read_bytes() == (
        destinations[1] / "manifest.json"
    ).read_bytes()
    assert (destinations[0] / "wu-outcomes.jsonl").read_bytes() == (
        destinations[1] / "wu-outcomes.jsonl"
    ).read_bytes()
    assert _git(case["data_root"], "status", "--porcelain").stdout == ""
    assert _git(case["spec_root"], "status", "--porcelain").stdout == ""
    assert (
        _git(
            case["data_root"],
            "ls-files",
            "--error-unmatch",
            "--",
            exporter.TRACKED_SPEC_RELATIVE.as_posix(),
            expected=1,
        ).returncode
        == 1
    )


def test_split_root_spec_identity_falsifiers_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_split_root_case(tmp_path)
    exact_bytes = case["spec_path"].read_bytes()

    untracked = case["data_root"].joinpath(*exporter.TRACKED_SPEC_RELATIVE.parts)
    untracked.parent.mkdir(parents=True)
    untracked.write_bytes(exact_bytes)
    with pytest.raises(contract.ContractError, match="E_SPEC_NOT_TRACKED"):
        exporter._load_frozen_spec(case["data_root"], untracked)
    untracked.unlink()
    untracked.parent.rmdir()
    untracked.parent.parent.rmdir()

    wrong_relative = case["spec_root"] / "other" / exporter.TRACKED_SPEC_RELATIVE.name
    wrong_relative.parent.mkdir()
    wrong_relative.write_bytes(exact_bytes)
    with pytest.raises(contract.ContractError, match="E_SPEC_PATH_MISMATCH"):
        exporter._load_frozen_spec(case["data_root"], wrong_relative)

    wrong_case = (
        case["spec_root"]
        / "DOCS"
        / "roadmap"
        / exporter.TRACKED_SPEC_RELATIVE.name
    )
    expected_case_error = "E_PATH_CASE_COLLISION" if os.name == "nt" else "E_SPEC_MISSING"
    with pytest.raises(contract.ContractError, match=expected_case_error):
        exporter._load_frozen_spec(case["data_root"], wrong_case)

    original_reparse = contract._is_reparse
    monkeypatch.setattr(
        contract,
        "_is_reparse",
        lambda path: path == case["spec_path"] or original_reparse(path),
    )
    with pytest.raises(contract.ContractError, match="reparse point"):
        exporter._load_frozen_spec(case["data_root"], case["spec_path"])
    monkeypatch.setattr(contract, "_is_reparse", original_reparse)

    other_root = (tmp_path / "other-repository").absolute()
    other_root.mkdir()
    _git(other_root, "init")
    other_spec = other_root.joinpath(*exporter.TRACKED_SPEC_RELATIVE.parts)
    other_spec.parent.mkdir(parents=True)
    other_spec.write_bytes(exact_bytes)
    _git(other_root, "add", "--", exporter.TRACKED_SPEC_RELATIVE.as_posix())
    with pytest.raises(contract.ContractError, match="E_SPEC_REPOSITORY_IDENTITY"):
        exporter._load_frozen_spec(case["data_root"], other_spec)


def test_exact_96_row_export_is_stable_native_and_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    result = _invoke(case)
    destination = case["destination"]
    payload = _rows(destination / "wu-outcomes.jsonl")
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert result["manifest_file_sha256"] == contract.sha256_file(
        destination / "manifest.json"
    )
    assert len(payload) == 96
    assert [(row["market"], row["target_date"]) for row in payload] == [
        (row["market"], row["target_date"]) for row in case["spec"]["request"]["keys"]
    ]
    assert {row["market"] for row in payload} == {item.id for item in BUILTIN_SPECS}
    assert next(row for row in payload if row["market"] == "toronto")["settlement_unit"] == "C"
    assert next(row for row in payload if row["market"] == "atlanta")["settlement_unit"] == "F"
    atlanta = next(row for row in payload if row["market"] == "atlanta")
    austin = next(row for row in payload if row["market"] == "austin")
    assert atlanta["source_revision_number"] == 1
    assert austin["source_revision_number"] == 0
    assert austin["source_revision_id"].startswith("sha256:legacy:")
    assert len(manifest["source_files"]) == 24
    assert all(
        row["bytes_before"] == row["bytes_after"]
        and row["sha256_before"] == row["sha256_after"]
        for row in manifest["source_files"]
    )
    assert all(value is False for value in manifest["downstream_authority"].values())
    assert manifest["destination_acl_proof"] == exporter._windows_acl_proof(destination)
    assert contract.validate_export(
        spec_path=case["spec_path"], export_root=destination
    )["status"] == "PASS"


def test_two_fresh_roots_reproduce_byte_identical_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _make_case(tmp_path / "one", monkeypatch)
    _invoke(first)
    first_payload = (first["destination"] / "wu-outcomes.jsonl").read_bytes()
    first_manifest = (first["destination"] / "manifest.json").read_bytes()
    second = _make_case(tmp_path / "two", monkeypatch)
    _invoke(second)
    assert (second["destination"] / "wu-outcomes.jsonl").read_bytes() == first_payload
    assert (second["destination"] / "manifest.json").read_bytes() == first_manifest


def test_irrelevant_daily_semantics_do_not_block_exact_stable_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    irrelevant_rows = [
        "wu_daily_legacy_v0,not-a-date,K,not-a-count,",
        "wrong_schema,2025-01-01,C,-1,81.5",
        "wu_daily_native_v2,also-not-a-date,K,NaN,Infinity",
    ]
    for path in case["dailies"].values():
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1:1] = irrelevant_rows[:2]
        lines.append(irrelevant_rows[2])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    sources = [*case["ledgers"].values(), *case["dailies"].values()]
    source_identity = {
        path.relative_to(case["repo"]).as_posix(): (
            path.stat().st_size,
            contract.sha256_file(path),
        )
        for path in sources
    }
    _invoke(case)
    first_payload = (case["destination"] / "wu-outcomes.jsonl").read_bytes()
    first_manifest = (case["destination"] / "manifest.json").read_bytes()
    second_destination = case["destination"].with_name("export-second")
    contract.export_production(
        repo_root=case["repo"],
        spec_path=case["spec_path"],
        destination=second_destination,
    )

    assert (second_destination / "wu-outcomes.jsonl").read_bytes() == first_payload
    assert (second_destination / "manifest.json").read_bytes() == first_manifest
    payload = [json.loads(line) for line in first_payload.splitlines()]
    expected_keys = [
        (row["market"], row["target_date"])
        for row in case["spec"]["request"]["keys"]
    ]
    assert len(payload) == 96
    assert [(row["market"], row["target_date"]) for row in payload] == expected_keys
    manifest = json.loads(first_manifest)
    assert len(manifest["source_files"]) == 24
    assert {
        row["relative_path"]: (row["bytes_before"], row["sha256_before"])
        for row in manifest["source_files"]
    } == source_identity
    assert all(
        row["bytes_before"] == row["bytes_after"]
        and row["sha256_before"] == row["sha256_after"]
        for row in manifest["source_files"]
    )
    assert source_identity == {
        path.relative_to(case["repo"]).as_posix(): (
            path.stat().st_size,
            contract.sha256_file(path),
        )
        for path in sources
    }


def _copied_acl_proof() -> dict[str, str]:
    sddl = "O:S-1-5-21-222D:(A;;FA;;;S-1-5-21-222)"
    return {
        "owner": "S-1-5-21-222",
        "sddl": sddl,
        "sddl_sha256": hashlib.sha256(sddl.encode("utf-8")).hexdigest(),
    }


def test_portable_copy_requires_hashes_and_returns_actual_acl_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    secret = 314_159_265
    ledger_rows = _rows(case["ledgers"]["chicago"])
    ledger_row = next(
        row for row in ledger_rows if row["target_date"] == DATES[0]
    )
    ledger_row["settlement_bucket"] = secret
    ledger_row["evidence"]["summary"]["bucket"] = secret
    _write_ledger(case["ledgers"]["chicago"], ledger_rows)
    daily_path = case["dailies"]["chicago"]
    daily_lines = daily_path.read_text(encoding="utf-8").splitlines()
    daily_lines[1] = daily_lines[1].rsplit(",", 1)[0] + f",{secret}"
    daily_path.write_text("\n".join(daily_lines) + "\n", encoding="utf-8")
    _invoke(case)
    copied = (tmp_path / "portable-copy").absolute()
    shutil.copytree(case["destination"], copied)
    manifest_path = copied / "manifest.json"
    payload_path = copied / "wu-outcomes.jsonl"
    manifest_hash = contract.sha256_file(manifest_path)
    payload_hash = contract.sha256_file(payload_path)
    producer_acl = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "destination_acl_proof"
    ]
    copied_acl = _copied_acl_proof()
    before = {
        path.name: (path.stat().st_size, contract.sha256_file(path))
        for path in copied.iterdir()
    }

    monkeypatch.setattr(
        contract,
        "_actual_export_acl_proof",
        lambda path: copied_acl if path == copied else producer_acl,
    )
    with pytest.raises(contract.ContractError, match="ACL proof does not match"):
        contract.validate_export(spec_path=case["spec_path"], export_root=copied)
    assert contract.validate_export(
        spec_path=case["spec_path"], export_root=case["destination"]
    )["status"] == "PASS"

    result = contract.validate_portable_copy(
        spec_path=case["spec_path"],
        export_root=copied,
        expected_producer_manifest_sha256=manifest_hash,
        expected_producer_payload_sha256=payload_hash,
    )
    assert result["status"] == "PASS"
    assert result["validation_mode"] == "portable_copy"
    assert result["producer_manifest_file_sha256"] == manifest_hash
    assert result["payload_sha256"] == payload_hash
    assert result["actual_destination_acl_proof"] == copied_acl

    evidence_path = (tmp_path / "portable-validation.json").absolute()
    assert contract.main(
        [
            "validate-portable-copy",
            "--spec",
            os.fspath(case["spec_path"]),
            "--export-root",
            os.fspath(copied),
            "--expected-producer-manifest-sha256",
            manifest_hash,
            "--expected-producer-payload-sha256",
            payload_hash,
            "--output",
            os.fspath(evidence_path),
        ]
    ) == 0
    captured = capsys.readouterr()
    assert str(secret) not in captured.out + captured.err
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["actual_destination_acl_proof"] == copied_acl
    assert evidence["producer_manifest_file_sha256"] == manifest_hash
    after = {
        path.name: (path.stat().st_size, contract.sha256_file(path))
        for path in copied.iterdir()
    }
    assert after == before


def test_portable_copy_rejects_missing_partial_and_wrong_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    _invoke(case)
    destination = case["destination"]
    manifest_hash = contract.sha256_file(destination / "manifest.json")
    payload_hash = contract.sha256_file(destination / "wu-outcomes.jsonl")
    monkeypatch.setattr(
        contract, "_actual_export_acl_proof", lambda _path: _copied_acl_proof()
    )
    with pytest.raises(contract.ContractError, match="requires both producer hashes"):
        contract._validate_export(
            spec_path=case["spec_path"],
            export_root=destination,
            expected_producer_manifest_sha256=manifest_hash,
        )
    with pytest.raises(contract.ContractError, match="requires both producer hashes"):
        contract._validate_export(
            spec_path=case["spec_path"],
            export_root=destination,
            expected_producer_payload_sha256=payload_hash,
        )
    with pytest.raises(contract.ContractError, match="manifest hash mismatch"):
        contract.validate_portable_copy(
            spec_path=case["spec_path"],
            export_root=destination,
            expected_producer_manifest_sha256="0" * 64,
            expected_producer_payload_sha256=payload_hash,
        )
    with pytest.raises(contract.ContractError, match="payload hash mismatch"):
        contract.validate_portable_copy(
            spec_path=case["spec_path"],
            export_root=destination,
            expected_producer_manifest_sha256=manifest_hash,
            expected_producer_payload_sha256="0" * 64,
        )
    with pytest.raises(SystemExit) as missing_cli_hash:
        contract.main(
            [
                "validate-portable-copy",
                "--spec",
                os.fspath(case["spec_path"]),
                "--export-root",
                os.fspath(destination),
                "--expected-producer-manifest-sha256",
                manifest_hash,
            ]
        )
    assert missing_cli_hash.value.code == 2


@pytest.mark.parametrize("fault", ["manifest", "payload", "extra", "reparse"])
def test_portable_copy_tampering_and_path_faults_fail_closed(
    fault: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    _invoke(case)
    copied = (tmp_path / "portable-copy").absolute()
    shutil.copytree(case["destination"], copied)
    manifest_hash = contract.sha256_file(copied / "manifest.json")
    payload_hash = contract.sha256_file(copied / "wu-outcomes.jsonl")
    monkeypatch.setattr(
        contract, "_actual_export_acl_proof", lambda _path: _copied_acl_proof()
    )
    if fault == "manifest":
        with (copied / "manifest.json").open("ab") as handle:
            handle.write(b" ")
    elif fault == "payload":
        with (copied / "wu-outcomes.jsonl").open("ab") as handle:
            handle.write(b" ")
    elif fault == "extra":
        (copied / "extra.txt").write_text("synthetic", encoding="utf-8")
    else:
        original = contract._is_reparse
        monkeypatch.setattr(
            contract,
            "_is_reparse",
            lambda path: path == copied or original(path),
        )
    with pytest.raises(contract.ContractError):
        contract.validate_portable_copy(
            spec_path=case["spec_path"],
            export_root=copied,
            expected_producer_manifest_sha256=manifest_hash,
            expected_producer_payload_sha256=payload_hash,
        )


def test_create_only_refuses_second_invocation_without_changing_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    _invoke(case)
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in case["destination"].iterdir()
    }
    with pytest.raises(contract.ContractError, match="E_DESTINATION_EXISTS"):
        _invoke(case)
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in case["destination"].iterdir()
    }
    assert after == before


@pytest.mark.parametrize(
    "kind", ["existing", "final_reparse", "repo_root", "repo_data", "ancestor_reparse"]
)
def test_destination_falsifiers_leave_final_absent(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    if kind in {"existing", "final_reparse"}:
        case["destination"].mkdir()
        if kind == "final_reparse":
            original = contract._is_reparse
            destination = case["destination"]
            monkeypatch.setattr(
                contract,
                "_is_reparse",
                lambda path: path == destination or original(path),
            )
    elif kind == "repo_root":
        case["destination"] = case["repo"]
    elif kind == "repo_data":
        case["destination"] = case["repo"] / "data" / "forbidden-export"
    else:
        parent = case["destination"].parent
        original = contract._is_reparse
        monkeypatch.setattr(
            contract, "_is_reparse", lambda path: path == parent or original(path)
        )
    with pytest.raises(contract.ContractError):
        _invoke(case)
    if kind not in {"existing", "final_reparse", "repo_root"}:
        assert not case["destination"].exists()


def _mutate_ledger(case: dict, mutation: str) -> None:
    path = case["ledgers"]["chicago"]
    rows = _rows(path)
    index = next(
        index
        for index, row in enumerate(rows)
        if row.get("target_date") == DATES[0]
    )
    row = rows[index]
    if mutation == "nonobject":
        path.write_text("[]\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
        return
    if mutation == "wrong_market":
        row["market_id"] = "atlanta"
    elif mutation == "case_market":
        row["market_id"] = "Chicago"
    elif mutation == "invalid_date":
        row["target_date"] = "2026-99-99"
    elif mutation == "invalid_revision":
        row["revision_number"] = -1
    elif mutation == "conflicting_revision":
        first = {**row, "revision_number": 1, "conflict": "first"}
        second = {**row, "revision_number": 1, "conflict": "second"}
        rows.extend((first, second))
    elif mutation == "bucket_absent":
        row["settlement_bucket"] = None
    elif mutation == "bucket_nonfinite":
        row["settlement_bucket"] = float("nan")
    elif mutation == "bucket_bool":
        row["settlement_bucket"] = True
    elif mutation == "bucket_nonintegral":
        row["settlement_bucket"] = 81.5
    elif mutation == "revision_identity_absent":
        row.pop("finalized_at_utc", None)
    elif mutation == "wrong_path":
        row["ledger_path"] = "data/settlements/atlanta/ledger.jsonl"
    elif mutation == "wrong_station":
        row["resolution_station"] = "KXXX"
    elif mutation == "wrong_unit":
        row["settlement_unit"] = "C"
    elif mutation == "wrong_timezone":
        row["resolution_timezone"] = "UTC"
    elif mutation == "wrong_history":
        row["resolution_wu_history_id"] = "KXXX:9:US"
    elif mutation == "wrong_source":
        row["settlement_source"] = "metar"
    elif mutation == "wrong_type":
        row["resolution_source_type"] = "open_meteo"
    elif mutation == "missing_label":
        rows.pop(index)
    elif mutation == "bucket_disagreement":
        row["settlement_bucket"] += 1
    _write_ledger(path, rows)


@pytest.mark.parametrize(
    "mutation",
    [
        "nonobject",
        "wrong_market",
        "case_market",
        "invalid_date",
        "invalid_revision",
        "conflicting_revision",
        "bucket_absent",
        "bucket_nonfinite",
        "bucket_bool",
        "bucket_nonintegral",
        "revision_identity_absent",
        "wrong_path",
        "wrong_station",
        "wrong_unit",
        "wrong_timezone",
        "wrong_history",
        "wrong_source",
        "wrong_type",
        "missing_label",
        "bucket_disagreement",
    ],
)
def test_adversarial_ledger_evidence_leaves_final_absent(
    mutation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    _mutate_ledger(case, mutation)
    with pytest.raises(contract.ContractError):
        _invoke(case)
    assert not case["destination"].exists()


@pytest.mark.parametrize("content", ["\n", "{not-json}\n"])
def test_blank_or_malformed_ledger_leaves_final_absent(
    content: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    with case["ledgers"]["chicago"].open("a", encoding="utf-8") as handle:
        handle.write(content)
    with pytest.raises(contract.ContractError):
        _invoke(case)
    assert not case["destination"].exists()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("missing", "E_DAILY_REQUEST_SET_MISMATCH"),
        ("below", "E_DAILY_BELOW_THRESHOLD"),
        ("duplicate", "E_DAILY_DUPLICATE_DATE"),
        ("wrong_unit", "E_DAILY_UNIT"),
        ("wrong_schema", "E_DAILY_SCHEMA"),
        ("blank_bucket", "E_DAILY_BUCKET"),
        ("nonintegral_bucket", "E_DAILY_BUCKET"),
        ("nonfinite_bucket", "E_DAILY_BUCKET"),
        ("invalid_row_count", "E_DAILY_ROW_COUNT"),
        ("invalid_date", "E_DAILY_REQUEST_SET_MISMATCH"),
    ],
)
def test_adversarial_daily_evidence_leaves_final_absent(
    mutation: str,
    error: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    path = case["dailies"]["chicago"]
    lines = path.read_text(encoding="utf-8").splitlines()
    if mutation == "missing":
        lines = [line for line in lines if DATES[0] not in line]
    elif mutation == "below":
        lines[1] = lines[1].replace(",24,", ",17,")
    elif mutation == "duplicate":
        lines.append(lines[1])
    elif mutation == "wrong_unit":
        lines[1] = lines[1].replace(",F,", ",C,")
    elif mutation == "wrong_schema":
        lines[1] = lines[1].replace("wu_daily_native_v2", "wu_daily_legacy_v0")
    elif mutation == "blank_bucket":
        lines[1] = lines[1].rsplit(",", 1)[0] + ","
    elif mutation == "nonintegral_bucket":
        lines[1] = lines[1].rsplit(",", 1)[0] + ",81.5"
    elif mutation == "nonfinite_bucket":
        lines[1] = lines[1].rsplit(",", 1)[0] + ",NaN"
    elif mutation == "invalid_row_count":
        lines[1] = lines[1].replace(",24,", ",many,")
    else:
        lines[1] = lines[1].replace(DATES[0], "not-a-date")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(contract.ContractError, match=error):
        _invoke(case)
    assert not case["destination"].exists()


@pytest.mark.parametrize(
    ("row", "error"),
    [
        ("legacy,not-a-date,K,broken", "E_DAILY_ROW_SHAPE"),
        ("legacy,not-a-date,K,broken,,extra", "E_DAILY_EXTRA_COLUMNS"),
        ('"unterminated', "E_DAILY_CSV"),
    ],
)
def test_irrelevant_daily_csv_shape_faults_fail_closed(
    row: str,
    error: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    path = case["dailies"]["chicago"]
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(row + "\n")
    with pytest.raises(contract.ContractError, match=error):
        _invoke(case)
    assert not case["destination"].exists()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("empty_market", "E_REQUEST_DATE_SET_EMPTY"),
        ("non_iso_date", "E_REQUEST_DATE"),
        ("duplicate", "E_REQUEST_DUPLICATE"),
        ("wrong_market", "E_REQUEST_MARKET_MISMATCH"),
    ],
)
def test_requested_dates_are_derived_independently_per_market(
    mutation: str,
    error: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    configured = {item.id: item for item in BUILTIN_SPECS}
    requests = [dict(row) for row in case["spec"]["request"]["keys"]]
    if mutation == "empty_market":
        requests = [row for row in requests if row["market"] != "chicago"]
    elif mutation == "non_iso_date":
        requests[0]["target_date"] = "20260615"
    elif mutation == "duplicate":
        requests[1] = dict(requests[0])
    else:
        requests[0]["market"] = "not-configured"
    with pytest.raises(contract.ContractError, match=error):
        exporter._requested_dates_by_market(requests, configured)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra", "cross_boundary"])
def test_adversarial_request_set_leaves_final_absent(
    mutation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    keys = case["spec"]["request"]["keys"]
    if mutation == "missing":
        keys.pop()
        case["spec"]["request"]["requested_rows"] = 95
    elif mutation == "duplicate":
        keys[-1] = dict(keys[0])
    elif mutation == "extra":
        keys.append({**keys[0], "target_date": "2026-06-27"})
        case["spec"]["request"]["requested_rows"] = 97
    else:
        keys[0]["provenance_side"] = "post_boundary_directional"
    case["spec"]["spec_sha256"] = contract.self_hash(
        case["spec"], "spec_sha256"
    )
    _write_json(case["spec_path"], case["spec"])
    with pytest.raises(contract.ContractError):
        _invoke(case)
    assert not case["destination"].exists()


def test_source_escape_and_reparse_leave_final_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    source = case["ledgers"]["chicago"]
    original = contract._is_reparse
    monkeypatch.setattr(
        contract, "_is_reparse", lambda path: path == source or original(path)
    )
    with pytest.raises(contract.ContractError):
        _invoke(case)
    assert not case["destination"].exists()

    case = _make_case(tmp_path / "escape", monkeypatch)
    monkeypatch.setattr(
        exporter,
        "_resolve_source",
        lambda *_args: (_ for _ in ()).throw(contract.ContractError("E_SOURCE_ESCAPE")),
    )
    with pytest.raises(contract.ContractError):
        _invoke(case)
    assert not case["destination"].exists()


def test_source_pre_post_drift_leaves_final_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    original = exporter._read_source
    calls = 0

    def drifting(*args):
        nonlocal calls
        calls += 1
        snapshot = original(*args)
        if calls == 25:
            return replace(snapshot, sha256="f" * 64)
        return snapshot

    monkeypatch.setattr(exporter, "_read_source", drifting)
    with pytest.raises(contract.ContractError, match="E_SOURCE_PRE_POST_DRIFT"):
        _invoke(case)
    assert not case["destination"].exists()


def test_source_disappearance_during_recheck_leaves_final_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    original = exporter._read_source
    calls = 0

    def disappearing(*args):
        nonlocal calls
        calls += 1
        if calls == 25:
            raise contract.ContractError("E_SOURCE_DISAPPEARED")
        return original(*args)

    monkeypatch.setattr(exporter, "_read_source", disappearing)
    with pytest.raises(contract.ContractError, match="E_SOURCE_DISAPPEARED"):
        _invoke(case)
    assert not case["destination"].exists()


def test_source_read_coexists_with_normal_writer_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    path = case["ledgers"]["chicago"]
    with path.open("ab") as writer:
        snapshot = exporter._read_source(
            case["repo"],
            "settlement_ledger",
            "data/settlements/chicago/ledger.jsonl",
        )
        writer.flush()
    assert snapshot.byte_count == path.stat().st_size


@pytest.mark.parametrize(
    "fault", ["write", "payload_tamper", "manifest_tamper", "validation", "extra_file", "rename", "cross_volume", "oversize"]
)
def test_injected_publication_failures_leave_final_absent(
    fault: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    if fault in {"write", "payload_tamper", "manifest_tamper"}:
        original_write = exporter._write_bytes_create_only

        def faulty_write(path: Path, raw: bytes) -> None:
            if fault == "write":
                raise OSError("synthetic write failure")
            original_write(path, raw)
            if fault == "payload_tamper" and path.name == "wu-outcomes.jsonl":
                with path.open("ab") as handle:
                    handle.write(b" ")
            if fault == "manifest_tamper" and path.name == "manifest.json":
                with path.open("ab") as handle:
                    handle.write(b" ")

        monkeypatch.setattr(exporter, "_write_bytes_create_only", faulty_write)
    elif fault in {"validation", "extra_file"}:
        original_validate = contract.validate_export

        def faulty_validate(*, spec_path: Path, export_root: Path):
            if fault == "validation":
                raise contract.ContractError("E_INJECTED_VALIDATION")
            (export_root / "extra.txt").write_text("x", encoding="utf-8")
            return original_validate(spec_path=spec_path, export_root=export_root)

        monkeypatch.setattr(contract, "validate_export", faulty_validate)
    elif fault == "rename":
        monkeypatch.setattr(
            exporter.os,
            "rename",
            lambda *_args: (_ for _ in ()).throw(OSError("synthetic rename failure")),
        )
    elif fault == "cross_volume":
        monkeypatch.setattr(
            exporter,
            "_volume_identity",
            lambda path: 1 if "wu-export-staging" in path.name else 2,
        )
    else:
        monkeypatch.setattr(contract, "MAX_EXPORT_BYTES", 1)
    with pytest.raises((contract.ContractError, OSError)):
        _invoke(case)
    assert not case["destination"].exists()
    assert not list(case["destination"].parent.glob(".*.wu-export-staging-*"))


def test_validator_rejects_tampering_and_cli_does_not_leak_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    case = _make_case(tmp_path, monkeypatch)
    secret = 314159265
    path = case["ledgers"]["chicago"]
    rows = _rows(path)
    rows[0]["settlement_bucket"] = secret
    _write_ledger(path, rows)
    result = contract.main(
        [
            "export-production",
            "--repo-root",
            str(case["repo"]),
            "--spec",
            str(case["spec_path"]),
            "--destination",
            str(case["destination"]),
        ]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert str(secret) not in captured.out + captured.err
    assert not case["destination"].exists()

    clean = _make_case(tmp_path / "tamper", monkeypatch)
    _invoke(clean)
    payload = clean["destination"] / "wu-outcomes.jsonl"
    with payload.open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(contract.ContractError):
        contract.validate_export(spec_path=clean["spec_path"], export_root=clean["destination"])


def test_acl_proof_is_actual_and_hashed(tmp_path: Path) -> None:
    proof = exporter._windows_acl_proof(tmp_path)
    assert proof["owner"]
    assert proof["sddl"]
    assert proof["sddl_sha256"] == hashlib.sha256(
        proof["sddl"].encode("utf-8")
    ).hexdigest()

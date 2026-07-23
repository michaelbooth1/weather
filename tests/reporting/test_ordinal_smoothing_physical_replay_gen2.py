import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from weather.market.market_registry import REGISTRY
from weather.reporting.promotion.promotion_corpus import corpus_hash
from weather.reporting.research import ordinal_smoothing_physical_replay_gen2 as gen2


def _paths(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "src" / "weather").mkdir(parents=True)
    (repo / "src" / "weather" / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    (repo / "sitecustomize.py").write_text("BOOTSTRAP = True\n", encoding="utf-8")
    (repo / "weather").mkdir()
    (repo / "weather" / "__init__.py").write_text("SHIM = True\n", encoding="utf-8")
    (repo / "artifacts").mkdir()
    (repo / "artifacts" / "model.json").write_text("{}\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "markets.yaml").write_text("markets: []\n", encoding="utf-8")
    data = tmp_path / "data"
    snapshots = data / "snapshots"
    snapshots.mkdir(parents=True)
    corpus = tmp_path / "corpus.json"
    corpus.write_text("{}\n", encoding="utf-8")
    dates = tmp_path / "tune_dates.txt"
    dates.write_text(f"{gen2.CANARY_DATE}\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.chdir(repo)
    return repo, data, snapshots, corpus, dates, output


def _args(tmp_path: Path, monkeypatch) -> Namespace:
    repo, data, snapshots, corpus, dates, output = _paths(tmp_path, monkeypatch)
    return Namespace(
        repo_root=str(repo),
        mirror_data_root=str(data),
        staged_data_root=str(data),
        snapshots_root=str(snapshots),
        tune_corpus=str(corpus),
        tune_dates_file=str(dates),
        generation_dir=str(output / "gen2-fixture"),
    )


def _entry(market_id: str) -> dict:
    slug = f"{market_id}-{gen2.CANARY_DATE}"
    return {
        "market_id": market_id,
        "target_date": gen2.CANARY_DATE,
        "event_slug": slug,
        "folder_relative_to_snapshots_root": slug,
        "snapshot_ids": [f"{market_id}-snapshot"],
    }


def _build_data(data: Path, snapshots: Path, entries: list[dict]) -> None:
    for entry in entries:
        folder = snapshots / entry["event_slug"]
        folder.mkdir()
        (folder / "snapshots.jsonl").write_text("{}\n", encoding="utf-8")
        (folder / "snapshots_long.csv").write_text("snapshot_id\n", encoding="utf-8")
        (folder / "replay_inputs.jsonl").write_text("{}\n", encoding="utf-8")
    for market_id, spec in REGISTRY.items():
        wu = data / "wunderground" / spec.icao.lower()
        (wu / "daily").mkdir(parents=True)
        (wu / "daily" / "daily_summary.csv").write_text(
            "date,max_temp\n", encoding="utf-8"
        )
        hourly = wu / "hourly" / "year=2026" / "month=07"
        hourly.mkdir(parents=True)
        (hourly / "observations.jsonl").write_text("{}\n", encoding="utf-8")


def _arm(physical_by_family):
    rows = []
    distributions = []
    for market_id, unit in (("toronto", "C"), ("atlanta", "F")):
        anchor = 0.0 if physical_by_family is None else float(physical_by_family[unit])
        probability = 0.40 + 0.10 * anchor
        snapshot_id = f"{market_id}-snapshot"
        rows.append(
            {
                "market_id": market_id,
                "target_date": gen2.CANARY_DATE,
                "snapshot_id": snapshot_id,
                "captured_at_local": f"{gen2.CANARY_DATE}T12:00:00-04:00",
                "band": "warm",
                "bin_type": "eq",
                "bin_value_c": 1.0,
                "bin_value_hi": 1.0,
                "replayed_p": probability,
                "outcome": 1,
                "market_yes": 0.60,
                "unit": unit,
            }
        )
        distributions.append(
            {
                "market_id": market_id,
                "target_date": gen2.CANARY_DATE,
                "snapshot_id": snapshot_id,
                "captured_at_local": f"{gen2.CANARY_DATE}T12:00:00-04:00",
                "cutoff_hour": 12,
                "unit": unit,
                "distribution": {"0": 1.0 - probability, "1": probability},
            }
        )
    return {
        "partition": "tune",
        "model_graph": "RESEARCH_UNBOUND",
        "rows": rows,
        "distribution_rows": distributions,
        "replay": {
            "snaps_in_corpus": 2,
            "snaps_scored": 2,
            "total_rows": 2,
            "fidelity": {},
            "corpus_warnings": [],
            "blockers": [],
        },
    }


def test_parser_is_a_tune_only_firewall():
    destinations = {action.dest for action in gen2.build_parser()._actions}
    assert destinations == {
        "help",
        "repo_root",
        "mirror_data_root",
        "staged_data_root",
        "snapshots_root",
        "tune_corpus",
        "tune_dates_file",
        "generation_dir",
    }
    assert not any(
        token in destination
        for destination in destinations
        for token in ("fresh", "holdout", "h1_result", "cache", "resume")
    )


def test_path_contract_rejects_existing_generation_and_data_output(tmp_path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    generation = Path(args.generation_dir)
    generation.mkdir()
    with pytest.raises(gen2.Gen2ReplayError, match="no resume/reuse"):
        gen2.validate_paths(args)

    generation.rmdir()
    args.generation_dir = str(Path(args.staged_data_root) / "unsafe")
    with pytest.raises(gen2.Gen2ReplayError, match="read-only data"):
        gen2.validate_paths(args)


def test_path_contract_rejects_reparse_generation_parent(tmp_path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    target = Path(args.generation_dir).parent
    alias = tmp_path / "output-alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as symlink_error:
        if os.name != "nt":
            pytest.skip(f"directory alias unavailable: {symlink_error}")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(f"directory junction unavailable: {result.stderr}")

    args.generation_dir = str(alias / "generation")
    with pytest.raises(gen2.Gen2ReplayError, match="parent must already exist"):
        gen2.validate_paths(args)
    assert not (target / "generation").exists()


def test_fingerprint_binds_design_identity_arm_and_fresh_w0(tmp_path, monkeypatch):
    from weather.execution_identity import (
        ClosureSpec,
        EnvironmentSpec,
        InvocationSpec,
        PathBinding,
        capture_execution_identity,
    )

    repo, *_ = _paths(tmp_path, monkeypatch)
    anchor = repo / "anchor.txt"
    anchor.write_text("anchor\n", encoding="utf-8")
    manifest = capture_execution_identity(
        ClosureSpec(
            name="fingerprint",
            base_root=repo,
            invocation=InvocationSpec.current(run_parameters={"case": "fingerprint"}),
            path_bindings=(PathBinding("anchor", anchor),),
            environment=EnvironmentSpec(include_packages=False),
        )
    )
    contract = {"arm_name": "candidate", "physical_c_sigma_by_family": {"C": 0.5, "F": 0.5}}
    first = gen2._cache_fingerprint(
        arm_contract=contract,
        start=manifest,
        corpus_hash="corpus",
        design_digest="a" * 64,
        w0_sha256="b" * 64,
    )
    second = gen2._cache_fingerprint(
        arm_contract=contract,
        start=manifest,
        corpus_hash="corpus",
        design_digest="a" * 64,
        w0_sha256="c" * 64,
    )
    assert len(first) == 64
    assert first != second


def test_tune_loader_accepts_only_literal_exact_panel(tmp_path, monkeypatch):
    entries = [_entry(market_id) for market_id in sorted(REGISTRY)]
    manifest = {
        "schema_version": "promotion_corpus_v0.1",
        "corpus_hash": corpus_hash(entries),
        "entries": entries,
        "skipped": [],
        "materialization": {
            "schema_version": "ordinal_smoothing_literal_panel_v0.1",
            "kind": "tune",
            "dates": [gen2.CANARY_DATE],
            "entry_count": len(entries),
            "source_manifest_sha256": "a" * 64,
            "source_corpus_hash": "b" * 64,
            "excluded_entry_count": 1,
        },
    }
    path = tmp_path / "literal-tune.json"
    path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(gen2, "EXPECTED_TUNE_DATES", (gen2.CANARY_DATE,))
    monkeypatch.setattr(gen2, "EXPECTED_TUNE_ENTRY_COUNT", len(entries))
    monkeypatch.setattr(gen2, "EXPECTED_TUNE_CORPUS_HASH", manifest["corpus_hash"])
    monkeypatch.setattr(gen2, "EXPECTED_SOURCE_CORPUS_FILE_SHA256", "a" * 64)
    monkeypatch.setattr(gen2, "EXPECTED_SOURCE_CORPUS_HASH", "b" * 64)
    monkeypatch.setattr(
        gen2,
        "EXPECTED_TUNE_CORPUS_FILE_SHA256",
        __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
    )
    loaded, loaded_entries = gen2.load_tune_only_manifest(path)
    assert loaded["skipped"] == []
    assert len(loaded_entries) == len(REGISTRY)

    forbidden = dict(entries[0])
    forbidden["target_date"] = "2026-06-22"
    forbidden["event_slug"] += "-forbidden-holdout"
    forbidden["folder_relative_to_snapshots_root"] = forbidden["event_slug"]
    manifest["entries"] = [*entries, forbidden]
    manifest["corpus_hash"] = corpus_hash(manifest["entries"])
    manifest["materialization"]["entry_count"] = len(entries)
    path = tmp_path / "relabeled-broad.json"
    path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(gen2, "EXPECTED_TUNE_CORPUS_HASH", manifest["corpus_hash"])
    monkeypatch.setattr(
        gen2,
        "EXPECTED_TUNE_CORPUS_FILE_SHA256",
        __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
    )
    with pytest.raises(gen2.Gen2ReplayError, match="exact preregistered panel"):
        gen2.load_tune_only_manifest(path)


def test_tune_date_contract_binds_file_hash_and_exact_tuple(tmp_path, monkeypatch):
    dates = tmp_path / "dates.txt"
    dates.write_text(f"# sealed\n{gen2.CANARY_DATE}\n", encoding="utf-8")
    digest = __import__("hashlib").sha256(dates.read_bytes()).hexdigest()
    monkeypatch.setattr(gen2, "EXPECTED_TUNE_DATES_FILE_SHA256", digest)
    monkeypatch.setattr(gen2, "EXPECTED_TUNE_DATES", (gen2.CANARY_DATE,))
    assert gen2.load_tune_dates_contract(dates) == (gen2.CANARY_DATE,)
    monkeypatch.setattr(gen2, "EXPECTED_TUNE_DATES", ("2026-06-22",))
    with pytest.raises(gen2.Gen2ReplayError, match="tuple"):
        gen2.load_tune_dates_contract(dates)


def test_synthetic_full_generation_cold_runs_all_seven_arms(
    tmp_path, monkeypatch
):
    args = _args(tmp_path, monkeypatch)
    entries = [_entry(market_id) for market_id in sorted(REGISTRY)]
    _build_data(Path(args.staged_data_root), Path(args.snapshots_root), entries)
    tune_manifest = {
        "schema_version": "promotion_corpus_v0.1",
        "source_corpus_hash": "fixture-corpus",
        "entries": entries,
        "skipped": [],
    }
    monkeypatch.setattr(gen2, "EXPECTED_TUNE_DATES", (gen2.CANARY_DATE,))
    monkeypatch.setattr(gen2, "EXPECTED_TUNE_ENTRY_COUNT", len(entries))
    monkeypatch.setattr(
        gen2, "load_tune_dates_contract", lambda path: (gen2.CANARY_DATE,)
    )
    monkeypatch.setattr(
        gen2,
        "load_tune_only_manifest",
        lambda path: (
            json.loads(json.dumps(tune_manifest)),
            json.loads(json.dumps(entries)),
        ),
    )
    monkeypatch.setattr(gen2, "configure_staged_data_root", lambda path: None)
    monkeypatch.setattr(gen2, "validate_staged_daily_inputs", lambda entries, root: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gen2-fixture",
            "--repo-root",
            str(Path(args.repo_root).resolve()),
            "--mirror-data-root",
            str(Path(args.mirror_data_root).resolve()),
            "--staged-data-root",
            str(Path(args.staged_data_root).resolve()),
            "--snapshots-root",
            str(Path(args.snapshots_root).resolve()),
            "--tune-corpus",
            str(Path(args.tune_corpus).resolve()),
            "--tune-dates-file",
            str(Path(args.tune_dates_file).resolve()),
            "--generation-dir",
            str(Path(args.generation_dir).resolve()),
        ],
    )
    calls = []

    def fake_run_partition_arm(**kwargs):
        calls.append(
            (
                kwargs["arm_name"],
                kwargs["physical_c_sigma_by_family"],
                len(kwargs["folders"]),
            )
        )
        return _arm(kwargs["physical_c_sigma_by_family"])

    monkeypatch.setattr(gen2, "run_partition_arm", fake_run_partition_arm)
    payload, commit = gen2.run_experiment(args)

    generation = Path(args.generation_dir)
    assert payload["status"] == "COMPLETE"
    assert payload["selected_physical_c_sigmas"] == {"C": 1.25, "F": 1.25}
    assert payload["prior_h1_result_or_cache_used"] is False
    assert payload["fresh_panel_opened"] is False
    assert payload["profile_gate"]["status"] == "PASS"
    labels = {
        row["label"] for row in payload["execution_identity"]["start"]["identity"]["bindings"]
    }
    assert "contract:sitecustomize" in labels
    assert "contract:weather_import_shim" in labels
    assert payload["terminal_seals"]["sitecustomize"]["sha256"]
    assert payload["terminal_seals"]["weather_import_shim"]["sha256"]
    assert len(calls) == 7
    assert calls[0][1] is None and calls[1][1] is None
    assert [call[1]["C"] for call in calls[2:]] == list(gen2.PHYSICAL_C_SIGMA_ANCHORS)
    assert (generation / "COMPLETE.json").is_file()
    assert commit["status"] == "COMPLETE"
    assert commit["execution_identity"]["identical_full_manifest"] is True
    output_names = {row["name"] for row in commit["outputs"]}
    assert gen2.RESULT_NAME in output_names
    assert gen2.REPORT_NAME in output_names
    assert len([name for name in output_names if name.startswith("cache/")]) == 7
    written = json.loads((generation / gen2.RESULT_NAME).read_text(encoding="utf-8"))
    assert written["execution_identity"]["identical_full_manifest"] is True
    assert all(
        record["identity_gates"]["identical_full_manifest"]
        for record in written["cache_records"]
    )


def test_schemas_are_registered():
    assert gen2.SCHEMA_VERSION == "ordinal_smoothing_physical_replay_gen2_v0.1"
    assert (
        gen2.GENERATION_SCHEMA_VERSION
        == "ordinal_smoothing_physical_replay_gen2_generation_commit_v0.1"
    )
    assert gen2.EXPECTED_TUNE_DATES_FILE_SHA256 == (
        "e546cb4dfe7def0225c8c4ce8165f5dfffdd235903d896aaafdcb2e77eab2041"
    )
    assert gen2.EXPECTED_TUNE_CORPUS_FILE_SHA256 == (
        "d1492ea5e4ae33eca68c59b9d55cc0aa2aef881acc62cce05f8d9c6d65e14acb"
    )
    assert gen2.EXPECTED_TUNE_CORPUS_HASH == (
        "ef4cfa84f6c18b433063cd8766f0e0af7d6f2eda0d3febdccb7756f2a016cff6"
    )

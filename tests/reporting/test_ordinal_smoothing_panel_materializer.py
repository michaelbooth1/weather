import hashlib
import json
from pathlib import Path

import pytest

from weather.execution_identity import ExclusivePublicationError
from weather.market.market_registry import REGISTRY
from weather.reporting.promotion.promotion_corpus import corpus_hash
from weather.reporting.research import ordinal_smoothing_panel_materializer as materializer


def _source(tmp_path: Path, *, mismatched_folder: bool = False):
    date = "2026-01-01"
    entries = []
    for index, market_id in enumerate(sorted(REGISTRY)):
        slug = f"{market_id}-{date}"
        entries.append(
            {
                "market_id": market_id,
                "target_date": date,
                "event_slug": slug,
                "folder_relative_to_snapshots_root": (
                    "wrong-folder" if mismatched_folder and index == 0 else slug
                ),
                "settlement_bucket": index,
                "settlement_unit": "C" if market_id == "toronto" else "F",
                "settlement_source": "daily_summary",
                "quality_grade": "complete",
                "snapshot_ids": [f"{slug}-snapshot"],
                "replay_record_hashes": {},
                "tape_row_hashes": {},
                "label_hash": hashlib.sha256(slug.encode()).hexdigest(),
            }
        )
    entries.append(
        {
            "market_id": "toronto",
            "target_date": "2026-02-01",
            "event_slug": "forbidden-holdout-outcome-marker",
            "folder_relative_to_snapshots_root": "forbidden-holdout-outcome-marker",
            "settlement_bucket": 999,
            "settlement_unit": "C",
            "settlement_source": "daily_summary",
            "quality_grade": "complete",
            "snapshot_ids": ["forbidden"],
            "replay_record_hashes": {},
            "tape_row_hashes": {},
            "label_hash": "f" * 64,
        }
    )
    manifest = {
        "schema_version": "promotion_corpus_v0.1",
        "as_of": "2026-02-02",
        "admit_promotion_countable": True,
        "include_reconstructed": False,
        "allow_unsettled": False,
        "entries": entries,
        "skipped": [],
        "corpus_hash": corpus_hash(entries),
    }
    path = tmp_path / "source.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path, manifest, date


def _install_contract(monkeypatch, path: Path, manifest: dict, date: str):
    contract = materializer.MaterializationContract(
        kind="fixture",
        dates=(date,),
        expected_entries=len(REGISTRY),
        source_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_corpus_hash=manifest["corpus_hash"],
    )
    monkeypatch.setitem(materializer.CONTRACTS, "fixture", contract)


def test_literal_materialization_excludes_every_nonpanel_outcome(tmp_path, monkeypatch):
    source, source_manifest, date = _source(tmp_path)
    _install_contract(monkeypatch, source, source_manifest, date)
    output = tmp_path / "derived.json"
    manifest, receipt = materializer.materialize_panel(
        kind="fixture", source_manifest=source, output=output
    )

    assert receipt["entry_count"] == len(REGISTRY)
    assert receipt["dates"] == [date]
    assert manifest["materialization"]["source_entry_count"] == len(REGISTRY) + 1
    assert manifest["materialization"]["excluded_entry_count"] == 1
    assert "forbidden-holdout-outcome-marker" not in output.read_text(encoding="utf-8")
    assert manifest["corpus_hash"] == corpus_hash(manifest["entries"])


def test_materialization_rejects_folder_alias_before_publication(tmp_path, monkeypatch):
    source, source_manifest, date = _source(tmp_path, mismatched_folder=True)
    _install_contract(monkeypatch, source, source_manifest, date)
    output = tmp_path / "derived.json"
    with pytest.raises(materializer.PanelMaterializationError, match="folder identity"):
        materializer.materialize_panel(
            kind="fixture", source_manifest=source, output=output
        )
    assert not output.exists()


def test_materialization_hard_pins_source_file_and_refuses_overwrite(
    tmp_path, monkeypatch
):
    source, source_manifest, date = _source(tmp_path)
    _install_contract(monkeypatch, source, source_manifest, date)
    contract = materializer.CONTRACTS["fixture"]
    monkeypatch.setitem(
        materializer.CONTRACTS,
        "fixture",
        materializer.MaterializationContract(
            kind=contract.kind,
            dates=contract.dates,
            expected_entries=contract.expected_entries,
            source_file_sha256="0" * 64,
            source_corpus_hash=contract.source_corpus_hash,
        ),
    )
    with pytest.raises(materializer.PanelMaterializationError, match="file hash"):
        materializer.materialize_panel(
            kind="fixture", source_manifest=source, output=tmp_path / "blocked.json"
        )

    _install_contract(monkeypatch, source, source_manifest, date)
    output = tmp_path / "derived.json"
    materializer.materialize_panel(kind="fixture", source_manifest=source, output=output)
    with pytest.raises(ExclusivePublicationError, match="overwrite"):
        materializer.materialize_panel(kind="fixture", source_manifest=source, output=output)


def test_production_contracts_are_literal_and_disjoint():
    tune = materializer.CONTRACTS["tune"]
    fresh = materializer.CONTRACTS["fresh"]
    assert tune.dates == materializer.TUNE_DATES
    assert tune.expected_entries == 143
    assert fresh.dates == materializer.FRESH_DATES
    assert fresh.expected_entries == 60
    assert set(tune.dates).isdisjoint(fresh.dates)
    assert len(tune.source_file_sha256) == len(fresh.source_file_sha256) == 64
    assert (
        materializer.LITERAL_PANEL_SCHEMA_VERSION
        == "ordinal_smoothing_literal_panel_v0.1"
    )

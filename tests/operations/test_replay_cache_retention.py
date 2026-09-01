import hashlib
import json
import os
import pickle
from dataclasses import replace
from pathlib import Path

import pytest
import pandas as pd

from weather.backtesting import replay_cache
from weather.io import sha256_file
from weather.operations import replay_cache_retention
from weather.operations import replay_cache_retention_serving
from weather.paths import REPO_ROOT
from weather.calibration.pooled_feature_model import SOURCE_RELIABILITY_COLUMNS
from weather.reporting.promotion.promotion_corpus import (
    _record_hashes,
    _snapshot_tape_hashes,
    corpus_hash,
)


@pytest.fixture(autouse=True)
def _stub_cache_off_compute(monkeypatch):
    """Exercise retention orchestration without claiming real-model parity."""

    pinned_serving_bundle = object()

    def serving_context(pointer_path, releases_root):
        binding = {
            "active_pointer_path": str(Path(pointer_path).resolve()),
            "active_pointer_file_sha256": "a" * 64,
            "releases_root": str(Path(releases_root).resolve()),
            "release_dir": str(Path(releases_root).resolve() / "r1"),
            "release_id": "r1",
            "manifest_sha256": "b" * 64,
            "manifest_file_sha256": "c" * 64,
            "market_ids": ["nyc"],
            "source_contract_sha256": replay_cache.fingerprint([]),
            "binding": (
                "genuine_active_pointer_plus_retained_release_inventory"
            ),
        }
        binding["identity"] = replay_cache.fingerprint(binding)
        return binding, []

    def compute(
        args,
        manifest,
        folder,
        artifact,
        *,
        family_unit,
        prediction_mode,
        defer_settlement_join,
        serving_bundle,
    ):
        assert Path(args.snapshots_root).resolve() == Path(
            manifest["snapshots_root"]
        ).resolve()
        assert Path(folder).name == manifest["entries"][0]["event_slug"]
        assert Path(manifest["entries"][0]["folder"]).resolve() == Path(
            folder
        ).resolve()
        assert defer_settlement_join is False
        assert serving_bundle is pinned_serving_bundle
        return {
            "candidate_rows": [
                {"snapshot_id": "snap1", "candidate_p": 0.61}
            ],
            "replay_results": {
                "all_rows": [{"snapshot_id": "snap1", "p": 0.61}]
            },
            "coverage": {"candidate_rows": 1},
            "diagnostics": {"source_freshness_snapshots": 1},
        }

    monkeypatch.setattr(
        replay_cache_retention,
        "_compute_pooled_candidate_day",
        compute,
    )
    monkeypatch.setattr(
        replay_cache_retention,
        "_load_serving_rebuild_context",
        serving_context,
    )
    monkeypatch.setattr(
        replay_cache_retention,
        "_load_pinned_serving_bundle",
        lambda _binding: pinned_serving_bundle,
    )


def _entry(slug="nyc-2026-07-07"):
    return {
        "event_slug": slug,
        "market_id": "nyc",
        "target_date": "2026-07-07",
        "snapshot_ids": ["snap1"],
        "replay_record_hashes": {"snap1": "replay-1"},
        "tape_row_hashes": {"snap1": "tape-1"},
        "settlement_bucket": 82,
        "settlement_high": 82,
        "settlement_unit": "F",
        "settlement_source": "wu",
        "winning_band": "82-83 F",
        "winning_band_kind": "range",
        "winning_band_value": 82,
        "winning_band_value_hi": 83,
        "quality_grade": "complete",
        "admitted_by": "quality_grade",
        "promotion_countable": True,
        "label_hash": "label-1",
    }


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_artifact(path, artifact_hash):
    context = {
        "artifact_type": "pooled_production_static_feature_context",
        "preselection_hash": "a" * 64,
        "window_lock_id": "b" * 64,
        "prior_as_of_exclusive": "2026-01-01",
        "context_fields": [
            "climate_normal",
            "climate_std",
            *SOURCE_RELIABILITY_COLUMNS,
        ],
        "markets": {
            "nyc": {
                "climate_normal": 82.0,
                "climate_std": 5.0,
                **{
                    field: float(index + 1)
                    for index, field in enumerate(
                        SOURCE_RELIABILITY_COLUMNS
                    )
                },
            }
        },
        "external_sidecar_policy": {
            "reanalysis_synoptic": "disabled_unpinned",
            "marine_water_contrast": "disabled_unpinned",
        },
    }
    context["context_sha256"] = hashlib.sha256(
        json.dumps(
            context,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(
            {
                "artifact_hash": artifact_hash,
                "schema_version": "pooled_feature_model_v0.test",
                "feature_schema_version": "feature_v0.test",
                "prediction_mode": "band_binary",
                "family_unit": "F",
                "models": {0: {"model": "fixture"}},
                "postprocess": {"schema_version": "postprocess_v0.test"},
                "point_in_time_training": {
                    "preselection_lock": {
                        "preselection_hash": "a" * 64,
                        "window_lock_id": "b" * 64,
                    }
                },
                "production_static_context": context,
            },
            handle,
        )
    return path


def _write_corpus(path, entries):
    snapshots_root = path.parent / "data" / "snapshots"
    prepared_entries = []
    for raw_entry in entries:
        entry = dict(raw_entry)
        folder = snapshots_root / entry["event_slug"]
        folder.mkdir(parents=True, exist_ok=True)
        tape_path = folder / "snapshots_long.csv"
        pd.DataFrame(
            [
                {
                    "snapshot_id": "snap1",
                    "range_label": "82-83 F",
                    "captured_at_local": "2026-07-07T12:00:00-04:00",
                }
            ]
        ).to_csv(tape_path, index=False)
        replay_record = {
            "snapshot_id": "snap1",
            "built_at": "2026-07-07T12:00:00-04:00",
            "sources": {},
        }
        replay_path = folder / "replay_inputs.jsonl"
        replay_path.write_text(
            json.dumps(replay_record, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        frame = pd.read_csv(tape_path)
        records = {"snap1": replay_record}
        entry.update(
            {
                "folder": str(folder),
                "folder_name": folder.name,
                "folder_relative_to_snapshots_root": folder.name,
                "snapshot_tape_path": str(tape_path),
                "snapshot_count": 1,
                "row_count": 1,
                "replay_record_count": 1,
                "replay_record_hashes": _record_hashes(records, ["snap1"]),
                "tape_row_hashes": _snapshot_tape_hashes(frame, ["snap1"]),
            }
        )
        prepared_entries.append(entry)
    manifest = {
        "schema_version": "promotion_corpus_v0.1",
        "generated_at_utc": "2026-07-27T00:00:00+00:00",
        "snapshots_root": str(snapshots_root),
        "include_reconstructed": False,
        "entries": prepared_entries,
        "skipped": [],
    }
    manifest["corpus_hash"] = corpus_hash(prepared_entries)
    return _write_json(path, manifest), manifest


def _write_registry(path, active_artifact, archived_artifact):
    return _write_json(
        path,
        {
            "schema_version": "model_variant_registry_v0.1",
            "variants": [
                {
                    "variant_id": "active",
                    "lifecycle": "active",
                    "artifact_path": str(active_artifact),
                    "artifact_required": True,
                    "live_runtime": "pooled_candidate_replay",
                    "postprocess_config_hash": "active-config",
                },
                {
                    "variant_id": "archived",
                    "lifecycle": "archived",
                    "artifact_path": str(archived_artifact),
                    "artifact_required": True,
                    "live_runtime": "pooled_candidate_replay",
                    "postprocess_config_hash": "archived-config",
                },
            ],
        },
    )


def _cache_key(entry, artifact, manifest, *, variant_config):
    config = replay_cache_retention._artifact_family_config(
        artifact,
        manifest,
        registry_postprocess_config_hash=variant_config,
        clob_max_age_seconds=180.0,
    )
    return replay_cache.key_for_entry(
        entry,
        consumer="pooled_candidate_replay",
        model_fp=artifact["artifact_hash"],
        config_fp=replay_cache.config_fingerprint(config),
    )


def _write_cache(root, key):
    return replay_cache.write_entry(
        root,
        key,
        rows=[{"snapshot_id": "snap1", "candidate_p": 0.61}],
        replay_results={"all_rows": [{"snapshot_id": "snap1", "p": 0.61}]},
        coverage={"candidate_rows": 1},
        diagnostics={"source_freshness_snapshots": 1},
    )


def _fixture(tmp_path):
    entry = _entry()
    corpus_path, manifest = _write_corpus(tmp_path / "promotion_corpus.json", [entry])
    entry = manifest["entries"][0]
    active_path = _write_artifact(tmp_path / "active.pkl", "active-model")
    archived_path = _write_artifact(tmp_path / "archived.pkl", "archived-model")
    registry = _write_registry(tmp_path / "registry.json", active_path, archived_path)
    with active_path.open("rb") as handle:
        active = pickle.load(handle)
    with archived_path.open("rb") as handle:
        archived = pickle.load(handle)
    protected_root = tmp_path / "data"
    root = protected_root / "backtest" / "replay_cache"
    reachable_path = _write_cache(
        root,
        _cache_key(entry, active, manifest, variant_config="active-config"),
    )
    candidate_path = _write_cache(
        root,
        _cache_key(entry, archived, manifest, variant_config="archived-config"),
    )
    return {
        "entry": entry,
        "corpus": corpus_path,
        "registry": registry,
        "active_artifact": active_path,
        "archived_artifact": archived_path,
        "root": root,
        "output": tmp_path / "receipts",
        "protected_roots": [protected_root],
        "reachable": reachable_path,
        "candidate": candidate_path,
    }


def _plan(fixture, **overrides):
    kwargs = {
        "cache_root": fixture["root"],
        "corpora": [fixture["corpus"]],
        "registry_path": fixture["registry"],
        "output_root": fixture["output"],
        "protected_roots": fixture["protected_roots"],
        "generated_at_utc": "2026-07-27T01:00:00+00:00",
    }
    kwargs.update(overrides)
    return replay_cache_retention.build_retention_plan(**kwargs)


def _approve_and_write(plan, path):
    plan["operator_review"] = {
        "approved": True,
        "approved_by": "fixture-operator",
        "approved_at_utc": "2026-07-27T02:00:00+00:00",
        "note": "reviewed exact fixture paths",
    }
    return _write_json(path, plan)


def test_plan_selects_only_exact_unreachable_rebuildable_key(tmp_path):
    fixture = _fixture(tmp_path)

    plan = _plan(fixture)

    assert plan["status"] == "PASS"
    assert plan["reachability"]["status"] == "COMPLETE"
    assert plan["summary"]["reachable_count"] == 1
    assert plan["summary"]["selected_count"] == 1
    selected = plan["candidates"][0]
    assert selected["path"] == fixture["candidate"].relative_to(fixture["root"]).as_posix()
    assert selected["reason"] == "unreachable_full_key"
    assert selected["bytes"] == fixture["candidate"].stat().st_size
    assert selected["sha256"] == sha256_file(fixture["candidate"])
    assert selected["full_key"]["model_fp"] == "archived-model"
    assert selected["identity"]
    assert selected["file_identity"]["mtime_ns"]
    assert selected["rebuild_sources"][0]["artifact_path"] == str(
        fixture["archived_artifact"].resolve()
    )
    assert selected["rebuild_sources"][0][
        "production_static_context_sha256"
    ]
    assert plan["serving_rebuild"]["binding"] == (
        "genuine_active_pointer_plus_retained_release_inventory"
    )
    assert all("modified" not in row["reason"] for row in plan["candidates"])


def test_serving_rebuild_context_pins_and_reloads_exact_release_graph(
    monkeypatch,
    tmp_path,
):
    from tests.test_release_serving import _active_fixture
    from weather.release_serving import load_verified_active_serving_bundle

    paths, _frozen, _result, releases, pointer = _active_fixture(
        tmp_path,
        functional=True,
    )
    strict_loads = []

    def load_fixture_bundle(
        *,
        pointer_path,
        releases_root,
    ):
        strict_loads.append(
            (Path(pointer_path).resolve(), Path(releases_root).resolve())
        )
        return load_verified_active_serving_bundle(
            pointer_path=pointer_path,
            releases_root=releases_root,
            repo_root=REPO_ROOT,
            check_runtime=False,
        )

    monkeypatch.setattr(
        replay_cache_retention_serving,
        "load_verified_active_serving_bundle",
        load_fixture_bundle,
    )

    binding, sources = (
        replay_cache_retention_serving.load_serving_rebuild_context(
            pointer,
            releases,
        )
    )
    bundle = replay_cache_retention_serving.load_pinned_serving_bundle(
        binding,
    )

    source_kinds = {row["kind"] for row in sources}
    assert "active_release_pointer" in source_kinds
    assert "active_release_manifest" in source_kinds
    assert {
        f"active_release_artifact:{role}"
        for role in bundle.artifact_paths
    }.issubset(source_kinds)
    assert bundle.release_id == binding["release_id"]
    assert bundle.manifest_sha256 == binding["manifest_sha256"]
    assert "pointer_payload" not in binding
    assert strict_loads == [
        (pointer.resolve(), releases.resolve()),
        (pointer.resolve(), releases.resolve()),
    ]

    for drift in (
        {"release_id": "new-active-release"},
        {"manifest_sha256": "f" * 64},
        {"release_dir": str(releases / "new-active-release")},
    ):
        monkeypatch.setattr(
            replay_cache_retention_serving,
            "load_verified_active_serving_bundle",
            lambda _drift=drift, **_kwargs: replace(bundle, **_drift),
        )
        with pytest.raises(
            ValueError,
            match="genuine active serving release no longer matches",
        ):
            replay_cache_retention_serving.load_pinned_serving_bundle(binding)


def test_legacy_artifact_without_frozen_static_context_is_retained(tmp_path):
    fixture = _fixture(tmp_path)
    with fixture["archived_artifact"].open("rb") as handle:
        artifact = pickle.load(handle)
    artifact.pop("point_in_time_training")
    artifact.pop("production_static_context")
    with fixture["archived_artifact"].open("wb") as handle:
        pickle.dump(artifact, handle)

    plan = _plan(fixture)

    assert plan["status"] == "BLOCK"
    assert plan["candidates"] == []
    assert any(
        row.get("full_key", {}).get("model_fp") == "archived-model"
        and row["reason"] == "unreachable_but_rebuild_identity_is_not_proven"
        for row in plan["ambiguities"]
    )


def test_serving_release_without_corpus_market_blocks_reachability(
    monkeypatch,
    tmp_path,
):
    fixture = _fixture(tmp_path)
    original = replay_cache_retention._load_serving_rebuild_context

    def missing_market(pointer_path, releases_root):
        binding, sources = original(pointer_path, releases_root)
        binding = dict(binding)
        binding["market_ids"] = []
        binding.pop("identity")
        binding["identity"] = replay_cache.fingerprint(binding)
        return binding, sources

    monkeypatch.setattr(
        replay_cache_retention,
        "_load_serving_rebuild_context",
        missing_market,
    )

    plan = _plan(fixture)

    assert plan["status"] == "BLOCK"
    assert plan["reachability"]["status"] == "INCOMPLETE"
    assert plan["candidates"] == []
    assert any(
        "pinned serving release lacks corpus markets" in blocker
        for blocker in plan["blockers"]
    )


def test_ambiguous_cache_entry_retains_everything_and_blocks(tmp_path):
    fixture = _fixture(tmp_path)
    (fixture["root"] / "unexpected.bin").write_bytes(b"not a cache entry")

    plan = _plan(fixture)

    assert plan["status"] == "BLOCK"
    assert plan["candidates"] == []
    assert plan["summary"]["provisional_candidate_count"] == 1
    assert "ambiguous_cache_or_reachability_state" in plan["blockers"]
    assert any(row["reason"] == "unexpected_non_json_cache_file" for row in plan["ambiguities"])


def test_incomplete_reachability_retains_all_and_blocks(tmp_path):
    fixture = _fixture(tmp_path)
    fixture["active_artifact"].unlink()

    plan = _plan(fixture)

    assert plan["status"] == "BLOCK"
    assert plan["reachability"]["status"] == "INCOMPLETE"
    assert plan["candidates"] == []
    assert any(item.startswith("reachability_incomplete") for item in plan["blockers"])


def test_quota_is_diagnostic_and_never_selects_reachable(tmp_path):
    fixture = _fixture(tmp_path)

    plan = _plan(fixture, quota_bytes=1)

    assert plan["status"] == "BLOCK"
    assert plan["quota"]["reachable_exceeds_quota"] is True
    assert plan["summary"]["selected_count"] == 1
    assert all(
        row["full_key"]["model_fp"] != "active-model"
        for row in plan["candidates"]
    )


def test_apply_requires_review_and_then_deletes_only_manifest_candidate(tmp_path):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert receipt["status"] == "APPLIED"
    assert receipt["deleted_count"] == 1
    assert not fixture["candidate"].exists()
    assert fixture["reachable"].exists()
    assert fixture["candidate"].parent.exists()
    assert (fixture["output"] / "replay_cache_retention_apply_receipt.json").exists()
    assert (fixture["output"] / "replay_cache_retention_apply_receipt.md").exists()
    action = receipt["actions"][0]
    assert action["cache_off_rebuild_parity"]["status"] == "PASS"
    assert (
        action["immediate_pre_unlink_cache_off_rebuild_parity"]["status"]
        == "PASS"
    )
    assert action["cache_off_rebuild_parity"]["mode"] == "cache_off_compute"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "cleanup_manifest_v0.stale", "cleanup manifest schema"),
        (
            "tool_schema_version",
            "replay_cache_retention_v0.stale",
            "retention tool schema",
        ),
    ],
)
def test_apply_rejects_stale_manifest_schema_before_unlink(
    field,
    value,
    message,
    tmp_path,
):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    plan[field] = value
    manifest_path = _approve_and_write(
        plan,
        fixture["output"] / "approved.json",
    )

    with pytest.raises(ValueError, match=message):
        replay_cache_retention.apply_retention_manifest(
            manifest_path,
            expected_manifest_sha256=sha256_file(manifest_path),
            cache_root=fixture["root"],
            corpora=[fixture["corpus"]],
            registry_path=fixture["registry"],
            output_root=fixture["output"],
            protected_roots=fixture["protected_roots"],
        )

    assert fixture["candidate"].exists()


def test_apply_runs_cache_off_compute_twice_around_pre_unlink(
    monkeypatch,
    tmp_path,
):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")
    calls = []

    def compute(*args, **kwargs):
        calls.append(fixture["candidate"].exists())
        return {
            "candidate_rows": [
                {"snapshot_id": "snap1", "candidate_p": 0.61}
            ],
            "replay_results": {
                "all_rows": [{"snapshot_id": "snap1", "p": 0.61}]
            },
            "coverage": {"candidate_rows": 1},
            "diagnostics": {"source_freshness_snapshots": 1},
        }

    monkeypatch.setattr(
        replay_cache_retention,
        "_compute_pooled_candidate_day",
        compute,
    )

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert receipt["status"] == "APPLIED"
    assert calls == [True, True]
    assert not fixture["candidate"].exists()


def test_cache_off_compute_ignores_external_manifest_folder_alias(tmp_path):
    fixture = _fixture(tmp_path)
    external_alias = tmp_path / "external-alias" / fixture["entry"]["event_slug"]
    external_alias.mkdir(parents=True)
    corpus = json.loads(fixture["corpus"].read_text(encoding="utf-8"))
    corpus["entries"][0]["folder"] = str(external_alias)
    _write_json(fixture["corpus"], corpus)
    plan = _plan(fixture)
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert receipt["status"] == "APPLIED"
    assert not fixture["candidate"].exists()


def test_apply_retains_candidate_when_cache_off_compute_diverges(
    monkeypatch,
    tmp_path,
):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")

    def divergent_compute(*args, **kwargs):
        return {
            "candidate_rows": [
                {"snapshot_id": "snap1", "candidate_p": 0.62}
            ],
            "replay_results": {
                "all_rows": [{"snapshot_id": "snap1", "p": 0.61}]
            },
            "coverage": {"candidate_rows": 1},
            "diagnostics": {"source_freshness_snapshots": 1},
        }

    monkeypatch.setattr(
        replay_cache_retention,
        "_compute_pooled_candidate_day",
        divergent_compute,
    )

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert receipt["status"] == "FAILED"
    assert "cache-off rebuild parity blocked" in receipt["actions"][0]["error"]
    assert receipt["actions"][0]["cache_off_rebuild_parity"]["status"] == "BLOCK"
    assert fixture["candidate"].exists()


def test_apply_rechecks_sources_after_second_parity_receipt(
    monkeypatch,
    tmp_path,
):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")
    original = replay_cache_retention._write_apply_receipt
    changed = False

    def mutate_after_second_parity(receipt, *, json_path, report_path):
        nonlocal changed
        result = original(receipt, json_path=json_path, report_path=report_path)
        action = (receipt.get("actions") or [{}])[0]
        if (
            not changed
            and action.get("status") == "PRE_UNLINK"
            and "immediate_pre_unlink_cache_off_rebuild_parity" in action
        ):
            fixture["archived_artifact"].write_bytes(
                fixture["archived_artifact"].read_bytes() + b"changed"
            )
            changed = True
        return result

    monkeypatch.setattr(
        replay_cache_retention,
        "_write_apply_receipt",
        mutate_after_second_parity,
    )

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert changed is True
    assert receipt["status"] == "FAILED"
    assert "source file identity changed" in receipt["actions"][0]["error"]
    assert fixture["candidate"].exists()


def test_apply_stops_before_unlink_when_source_hash_changes(tmp_path):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")
    fixture["archived_artifact"].write_bytes(
        fixture["archived_artifact"].read_bytes() + b"changed"
    )

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert receipt["status"] == "FAILED"
    assert receipt["actions"][0]["status"] == "FAILED"
    assert "source file identity changed" in receipt["actions"][0]["error"]
    assert fixture["candidate"].exists()
    assert fixture["reachable"].exists()


def test_apply_blocks_when_optional_rebuild_input_appears(tmp_path):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")
    event_folder = Path(fixture["entry"]["folder"])
    (event_folder / "features_long.csv").write_text(
        "snapshot_id,feature\nsnap1,changed\n",
        encoding="utf-8",
    )

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert receipt["status"] == "FAILED"
    assert "optional rebuild input appeared" in receipt["actions"][0]["error"]
    assert fixture["candidate"].exists()


def test_apply_blocks_changed_candidate_in_cleanup_preflight(tmp_path):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")
    fixture["candidate"].write_text(
        fixture["candidate"].read_text(encoding="utf-8") + " ",
        encoding="utf-8",
    )

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert receipt["status"] == "BLOCKED_BY_CLEANUP_PREFLIGHT"
    assert receipt["actions"][0]["status"] == "UNATTEMPTED"
    assert fixture["candidate"].exists()


def test_rebuild_one_proves_all_cache_consumed_fields(tmp_path):
    fixture = _fixture(tmp_path)
    cached = json.loads(fixture["reachable"].read_text(encoding="utf-8"))
    rebuilt_path = _write_json(
        tmp_path / "rebuilt.json",
        {
            "key": cached["key"],
            "rows": cached["rows"],
            "replay_results": cached["replay_results"],
            "coverage": cached["coverage"],
            "diagnostics": cached["diagnostics"],
        },
    )

    passed = replay_cache_retention.rebuild_one_parity(
        fixture["reachable"],
        rebuilt_path,
    )
    rebuilt = json.loads(rebuilt_path.read_text(encoding="utf-8"))
    rebuilt["diagnostics"]["source_freshness_snapshots"] = 2
    _write_json(rebuilt_path, rebuilt)
    blocked = replay_cache_retention.rebuild_one_parity(
        fixture["reachable"],
        rebuilt_path,
    )

    assert passed["status"] == "PASS"
    assert {row["field"] for row in passed["checks"]} == {
        "rows",
        "replay_results",
        "coverage",
        "diagnostics",
        "key",
    }
    assert blocked["status"] == "BLOCK"
    assert next(row for row in blocked["checks"] if row["field"] == "diagnostics")[
        "status"
    ] == "BLOCK"


def test_rebuild_one_cli_does_not_require_plan_inputs(tmp_path):
    fixture = _fixture(tmp_path)
    cached = json.loads(fixture["reachable"].read_text(encoding="utf-8"))
    rebuilt_path = _write_json(
        tmp_path / "rebuilt.json",
        {
            field: cached[field]
            for field in (
                "key",
                "rows",
                "replay_results",
                "coverage",
                "diagnostics",
            )
        },
    )

    status = replay_cache_retention.main(
        [
            "--output-root",
            str(fixture["output"]),
            "--protected-root",
            str(fixture["protected_roots"][0]),
            "--rebuild-one-cache-entry",
            str(fixture["reachable"]),
            "--rebuild-one-payload",
            str(rebuilt_path),
        ]
    )

    assert status == 0
    assert (
        fixture["output"] / "replay_cache_rebuild_one_parity.json"
    ).exists()


def test_output_root_is_rejected_anywhere_inside_enclosing_data_tree(tmp_path):
    fixture = _fixture(tmp_path)
    data_root = fixture["protected_roots"][0]

    with pytest.raises(ValueError, match="protected data/mirror"):
        replay_cache_retention._validated_output_root(
            fixture["root"],
            data_root / "receipts",
            fixture["protected_roots"],
        )


def test_every_explicit_mirror_root_is_protected_from_output(tmp_path):
    fixture = _fixture(tmp_path)
    mirror_root = tmp_path / "weather-mirror"
    mirror_root.mkdir()

    with pytest.raises(ValueError, match="protected data/mirror"):
        replay_cache_retention._validated_output_root(
            fixture["root"],
            mirror_root / "receipts",
            [*fixture["protected_roots"], mirror_root],
        )


def test_unreadable_walk_subtree_is_an_ambiguity(monkeypatch, tmp_path):
    cache_root = tmp_path / "replay_cache"
    cache_root.mkdir()

    def fake_walk(root, *, followlinks, onerror):
        assert Path(root) == cache_root
        assert followlinks is False
        onerror(PermissionError(13, "denied", str(cache_root / "sealed")))
        return []

    monkeypatch.setattr(replay_cache_retention.os, "walk", fake_walk)

    files, ambiguities = replay_cache_retention._iter_cache_files(cache_root)

    assert files == []
    assert ambiguities[0]["path"].endswith("sealed")
    assert ambiguities[0]["reason"].startswith("unreadable_cache_subtree:")


def test_source_symlink_is_rejected_before_resolution(tmp_path):
    fixture = _fixture(tmp_path)
    alias = tmp_path / "corpus-alias.json"
    try:
        alias.symlink_to(fixture["corpus"])
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    plan = replay_cache_retention.build_retention_plan(
        cache_root=fixture["root"],
        corpora=[alias],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert plan["status"] == "BLOCK"
    assert any(
        "link or reparse point" in blocker
        for blocker in plan["blockers"]
        if blocker.startswith("reachability_incomplete")
    )


def test_apply_recomputes_and_blocks_manifest_injected_reachable_key(tmp_path):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    plan["candidates"] = [dict(plan["reachable"][0])]
    plan["summary"]["selected_count"] = 1
    plan["summary"]["selected_bytes"] = plan["reachable"][0]["bytes"]
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert receipt["status"] == "FAILED"
    assert "now reachable" in receipt["actions"][0]["error"]
    assert fixture["reachable"].exists()
    assert fixture["candidate"].exists()


def test_apply_persists_pre_unlink_write_ahead_state(monkeypatch, tmp_path):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")
    observed_statuses = []
    original = replay_cache_retention._write_apply_receipt

    def capture(receipt, *, json_path, report_path):
        observed_statuses.append(
            [row["status"] for row in receipt.get("actions") or []]
        )
        return original(receipt, json_path=json_path, report_path=report_path)

    monkeypatch.setattr(replay_cache_retention, "_write_apply_receipt", capture)

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert receipt["status"] == "APPLIED"
    assert ["PRE_UNLINK"] in observed_statuses
    assert observed_statuses.index(["PRE_UNLINK"]) < observed_statuses.index(["DELETED"])


def test_apply_does_not_unlink_when_durable_pre_unlink_write_fails(
    monkeypatch,
    tmp_path,
):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")
    original = replay_cache_retention._write_text_durable_atomic

    def fail_pre_unlink(path, text):
        if '"status": "PRE_UNLINK"' in text:
            raise OSError("synthetic fsync-backed receipt failure")
        return original(path, text)

    monkeypatch.setattr(
        replay_cache_retention,
        "_write_text_durable_atomic",
        fail_pre_unlink,
    )

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert receipt["status"] == "FAILED"
    assert "fsync-backed receipt failure" in receipt["actions"][0]["error"]
    assert fixture["candidate"].exists()
    persisted = json.loads(
        (fixture["output"] / "replay_cache_retention_apply_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["status"] == "FAILED"


def test_apply_rejects_reparse_ancestor_in_candidate_lexical_path(
    monkeypatch,
    tmp_path,
):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")
    candidate_parent = fixture["candidate"].parent
    path_type = type(candidate_parent)
    original = path_type.is_symlink

    def synthetic_reparse(self):
        return self == candidate_parent or original(self)

    monkeypatch.setattr(path_type, "is_symlink", synthetic_reparse)

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert receipt["status"] == "FAILED"
    assert "candidate path contains a link or reparse point" in (
        receipt["actions"][0]["error"]
    )
    assert fixture["candidate"].exists()


def test_apply_requires_explicit_operator_approval(tmp_path):
    fixture = _fixture(tmp_path)
    manifest_path = _write_json(fixture["output"] / "unapproved.json", _plan(fixture))

    with pytest.raises(ValueError, match="operator approval"):
        replay_cache_retention.apply_retention_manifest(
            manifest_path,
            expected_manifest_sha256=sha256_file(manifest_path),
            cache_root=fixture["root"],
            corpora=[fixture["corpus"]],
            registry_path=fixture["registry"],
            output_root=fixture["output"],
            protected_roots=fixture["protected_roots"],
        )

    assert fixture["candidate"].exists()


def test_apply_pins_source_file_identity_even_when_bytes_and_hash_match(tmp_path):
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    manifest_path = _approve_and_write(plan, fixture["output"] / "approved.json")
    before = fixture["archived_artifact"].stat()
    os.utime(
        fixture["archived_artifact"],
        ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000),
    )

    receipt = replay_cache_retention.apply_retention_manifest(
        manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        cache_root=fixture["root"],
        corpora=[fixture["corpus"]],
        registry_path=fixture["registry"],
        output_root=fixture["output"],
        protected_roots=fixture["protected_roots"],
    )

    assert receipt["status"] == "FAILED"
    assert "source file identity changed" in receipt["actions"][0]["error"]
    assert fixture["candidate"].exists()

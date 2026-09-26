"""New Drive-lane scopes, archive-aware readers and a >10k-file synthetic tar.

No production inputs, network, encryption keys or venue calls are used.
"""
from contextlib import ExitStack, nullcontext
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import pytest

from weather import cold_archive_locations as locations
from weather.operations import cold_archive_catalog as catalog
from weather.operations import cold_archive_families as families
from weather.operations import cold_archive_reclaim as reclaim
from weather.operations import production_cold_archive_stage as stage
from weather.operations import production_cold_archive_stage_cli as cli
from weather.operations import bulk_cold_archive_crypt as bridge
from tests.operations import test_cold_archive_catalog as fixtures
from tests.operations.test_cold_archive_catalog import corpus
from tests.operations.test_cold_archive_reclaim import approved_plan, reclaim_args

EVENT = "snapshots/highest-temperature-in-toronto-on-june-15-2026"
CASES = [
    ("snapshots", {"diagnostics.20260615T230000Z.jsonl": b'{"kind":"diagnostic"}\n'}),
    ("mm_runs/2026-06-15/run-a", {"quote_intents_long.csv": b"a,b\n1,2\n"}),
    (EVENT, {"variant_predictions.jsonl": b'{"variant_name":"baseline","probability":0.6}\n'}),
    (EVENT + "/price_history_raw", {"a.json": b'{"history":[{"t":1,"p":0.5}]}'}),
]


def adopt_part_a_fixture(monkeypatch):
    """Supply Part A's independently delivered registry row for integration tests."""
    from weather.operations import storage_classes as registry
    row = registry.ArtifactFamilyClassification(
        "rotated_capture_diagnostics", "operations", registry.OPERATOR_CACHE,
        ("snapshots/clob_diagnostics.*.jsonl", "snapshots/diagnostics.*.jsonl",
         "snapshots/clob_diagnostics.*.jsonl.gz", "snapshots/diagnostics.*.jsonl.gz"),
        "operator_log_archive", "retained diagnostic archive",
        "verified_archive_and_reviewed_exact_path_manifest", False)
    monkeypatch.setattr(registry, "ARTIFACT_FAMILIES", (row, *registry.ARTIFACT_FAMILIES))


def test_family_order_whole_subtree_and_ordinary_member_bound():
    rows = [{"path": folder + "/" + name, "size_bytes": 1}
            for folder, contents in reversed(CASES) for name in contents]
    chunks = stage._chunks(rows, 1024, stage.STORAGE_GROUPING)
    assert [families.family_group(c["files"][0]["path"])[0] for c in chunks] == list(families.FAMILY_ORDER)
    raw = [{"path": EVENT + f"/price_history_raw/{n:05}.json", "size_bytes": 1} for n in range(10001)]
    chunks = stage._chunks(raw, 20000, stage.STORAGE_GROUPING)
    assert len(chunks) == 1 and len(chunks[0]["files"]) == 10001
    assert stage.archive_byte_bound(raw) > 10001 * 1024
    with pytest.raises(stage.ArchiveStageError, match="never split"):
        stage._chunks(raw, 10000, stage.STORAGE_GROUPING)
    too_many = [{"path": EVENT + f"/price_history_raw/{n:05}.json", "size_bytes": 0}
                for n in range(locations.MAX_PRICE_MEMBERS + 1)]
    with pytest.raises(stage.ArchiveStageError, match="never split"):
        stage._chunks(too_many, 20000, stage.STORAGE_GROUPING)
    ordinary = [{"path": f"snapshots/diagnostics.20260615T230000Z.{n}.jsonl", "size_bytes": 1} for n in range(257)]
    assert [len(c["files"]) for c in stage._chunks(ordinary, 1024, stage.STORAGE_GROUPING)] == [256, 1]
    with pytest.raises(locations.CatalogIntegrityError):
        locations.member_limit(ordinary)


@pytest.mark.parametrize("day,allowed", [("2026-07-30", True), ("2026-07-31", False),
                                         ("2026-08-08", False), ("2026-08-09", True),
                                         ("2026-08-27", False)])
def test_cli_keeps_ef8bb_dates_and_thirty_day_boundary_hot(tmp_path, day, allowed):
    row = {"path": f"mm_runs/{day}/run-a/quote_intents_long.csv", "size_bytes": 3}
    chunk = {"chunk_id": "chunk-00000", "files": [row], "logical_bytes": 3}
    plan = {"source_root": str(tmp_path / "data"), "chunks": [chunk], "chunk_grouping": stage.STORAGE_GROUPING}
    now = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    if allowed:
        assert cli.validate_chunk(plan, "chunk-00000", tmp_path, now) == chunk
    else:
        with pytest.raises(ValueError):
            cli.validate_chunk(plan, "chunk-00000", tmp_path, now)


@pytest.mark.parametrize("name", ["diagnostics.jsonl", "clob_diagnostics.jsonl",
                                 "observation_trigger.20260615.jsonl", "snapshots.jsonl"])
def test_new_grouping_does_not_admit_active_or_unapproved_families(name):
    with pytest.raises(ValueError):
        families.validate_cold_source(EVENT + "/" + name, date(2026, 9, 26), extended=True)


@pytest.mark.parametrize("case", CASES)
def test_exact_owner_approval_binds_new_grouping(tmp_path, monkeypatch, case):
    monkeypatch.setattr(bridge, "_file_pin", fixtures.FixturePin)
    folder, contents = case
    request, entry = approved_plan(tmp_path, relative=folder + "/" + next(iter(contents)),
                                   grouping=stage.STORAGE_GROUPING)
    with ExitStack() as stack:
        _, digest, kind, _ = reclaim._approval(request, stack, entry)
    assert digest == request["owner_approval"]["sha256"] and kind == "primary"


@pytest.mark.parametrize("corpus", CASES, indirect=True)
def test_new_layouts_reclaim_only_with_existing_proofs_and_no_event_manifest(corpus, monkeypatch):
    adopt_part_a_fixture(monkeypatch)
    assert not list(corpus.root.rglob("event_day_manifest.json"))
    args = reclaim_args(corpus, monkeypatch)
    result = reclaim.reclaim_chunk(**args)
    assert result["status"] == "PASS" and result["selection_kind"] == "primary"
    assert result["deleted_files"] == len(corpus.contents)
    for name in corpus.contents:
        with pytest.raises(locations.ArchivedInputRequired):
            locations.resolve_local_path(corpus.day / name)


@pytest.mark.parametrize("corpus", [("mm_runs/2026-08-08/run-a", {"quote_intents_long.csv": b"a\n1\n"})], indirect=True)
def test_reclaim_also_refuses_protected_maker_dates(corpus, monkeypatch):
    args = reclaim_args(corpus, monkeypatch)
    with pytest.raises(locations.CatalogIntegrityError, match="EF 8bb"):
        reclaim.reclaim_chunk(**args)
    assert (corpus.day / "quote_intents_long.csv").is_file()


@pytest.mark.parametrize("corpus", [CASES[0]], indirect=True)
def test_diagnostic_reclaim_refuses_active_writer(corpus, monkeypatch):
    from tests.operations.test_cold_archive_reclaim import amend
    adopt_part_a_fixture(monkeypatch)
    args = reclaim_args(corpus, monkeypatch)
    amend(args["request"]["source_review"], lambda v: v["checks"]["rotated_logs_closed"].update(active_writer=True))
    with pytest.raises(locations.CatalogIntegrityError, match="writer-free"):
        reclaim.reclaim_chunk(**args)
    assert all((corpus.day / name).exists() for name in corpus.contents)


@pytest.mark.parametrize("corpus", [CASES[0]], indirect=True)
def test_diagnostic_reclaim_requires_part_a_adoption(corpus, monkeypatch):
    args = reclaim_args(corpus, monkeypatch)
    monkeypatch.setattr(reclaim, "classification_payload", lambda path: {"artifact_family": "unclassified"})
    with pytest.raises(locations.CatalogIntegrityError, match="Part A"):
        reclaim.reclaim_chunk(**args)
    assert all((corpus.day / name).exists() for name in corpus.contents)


@pytest.mark.parametrize("name", ["quote_intents_long.csv", "model_variant_quote_intents_long.csv"])
def test_quote_intents_have_canonical_evidence_classification(name):
    from weather.operations.storage_classes import classification_payload
    row = classification_payload("mm_runs/2026-06-15/run-a/" + name)
    assert row["storage_class"] == "canonical_evidence" and row["protected"]


@pytest.mark.parametrize("corpus", [CASES[2]], indirect=True)
def test_archived_variant_discovery_keeps_missing_payload_visible(corpus):
    from weather.reporting.scorecards import live_variant_settlement_scorecard as score
    fixtures.register(corpus)
    original = corpus.day / "variant_predictions.jsonl"
    original.unlink()
    assert score.discover_tapes(corpus.root / "snapshots") == [original]
    with pytest.raises(locations.ArchivedInputRequired):
        score.read_rows(original)


@pytest.mark.parametrize("corpus", [(EVENT, CASES[2][1], 1781481600)], indirect=True)
def test_variant_cache_reads_keep_logical_identity_hash_and_original_freshness(corpus):
    from weather.reporting.scorecards import live_variant_settlement_scorecard as score
    from weather.reporting.scorecards import captured_input_parity_evidence as parity
    catalog.publish_cache(**fixtures.cached(corpus))
    original = corpus.day / "variant_predictions.jsonl"
    original.unlink()
    assert score.discover_tapes(corpus.root / "snapshots") == [original]
    rows = score.read_rows(original)
    assert rows[0]["_source_path"] == str(original) and rows[0]["probability"] == 0.6
    assert score._prediction_path_sha256(original) == hashlib.sha256(CASES[2][1][original.name]).hexdigest()
    assert parity._read_rows_strict(original, role="variant predictions", max_rows=10)[0]["probability"] == 0.6
    with pytest.raises(parity.CapturedInputParityEvidenceError, match="old"):
        parity._require_regular_fresh_file(original, now=datetime.now(timezone.utc),
                                           max_age_hours=24, role="variant predictions")


@pytest.mark.parametrize("corpus", [
    (EVENT, {"snapshot_explanations.jsonl": b'{"snapshot_id":"s1","note":"retained"}\n'}),
    (EVENT, {"snapshot_explanations_long.csv": b"snapshot_id,note\ns1,retained\n"}),
    (EVENT, {"variant_predictions_long.csv": b"snapshot_id,note\ns1,retained\n"}),
], indirect=True)
def test_other_variant_representations_keep_strict_parity_reader_access(corpus):
    from weather.reporting.scorecards import captured_input_parity_evidence as parity
    catalog.publish_cache(**fixtures.cached(corpus))
    original = corpus.day / next(iter(corpus.contents))
    original.unlink()
    assert parity._read_rows_strict(original, role="served tape", max_rows=10) == [
        {"snapshot_id": "s1", "note": "retained"}]


@pytest.mark.parametrize("corpus", [CASES[1]], indirect=True)
def test_archived_maker_runs_remain_discoverable_and_readable(corpus):
    from weather.market import mm_paper_scoring as scoring, mm_scoring_projection as projection
    catalog.publish_cache(**fixtures.cached(corpus))
    original = corpus.day / "quote_intents_long.csv"
    original.unlink()
    assert scoring.discover_run_folders(corpus.root / "mm_runs") == [corpus.day]
    assert projection.discover_run_folders(corpus.root / "mm_runs") == [corpus.day]
    assert scoring.read_csv_rows(original) == [{"a": "1", "b": "2"}]


@pytest.mark.parametrize("corpus", [CASES[3]], indirect=True)
def test_raw_price_reader_uses_verified_cache(corpus):
    from weather.market.market_microstructure_capture import read_price_history_raw_response
    catalog.publish_cache(**fixtures.cached(corpus))
    (corpus.day / "a.json").unlink()
    assert read_price_history_raw_response({"raw_response_path": "price_history_raw/a.json"},
                                           root=corpus.day.parent) == {"history": [{"t": 1, "p": 0.5}]}


@pytest.mark.parametrize("corpus", [CASES[3]], indirect=True)
def test_raw_price_archive_is_not_silently_missing(corpus):
    from weather.market.market_microstructure_capture import read_price_history_raw_response
    fixtures.register(corpus)
    (corpus.day / "a.json").unlink()
    with pytest.raises(locations.ArchivedInputRequired):
        read_price_history_raw_response({"raw_response_path": "price_history_raw/a.json"}, root=corpus.day.parent)


def raw_plan(tmp_path, monkeypatch, count):
    monkeypatch.setattr(stage, "_source_pin", fixtures.FixturePin)
    monkeypatch.setattr(bridge, "_file_pin", fixtures.FixturePin)
    monkeypatch.setattr(stage, "_directory_pin", lambda path: nullcontext())
    root = tmp_path / "data"
    folder = root / EVENT / "price_history_raw"
    folder.mkdir(parents=True)
    rows = []
    for n in range(count):
        path = folder / f"{n:05}.json"
        path.write_bytes(json.dumps({"p": n}).encode())
        rows.append({"path": path.relative_to(root).as_posix(), **fixtures.metadata(path)})
    selection = {"schema_version": "large_archive_candidate_selection_v1",
                 "status": "MEASURED_CANDIDATE_NOT_DELETE_AUTHORITY", "source_root": str(root),
                 "files": rows, "file_count": count,
                 "logical_bytes": sum(r["size_bytes"] for r in rows),
                 "allocated_bytes": sum(r["allocated_bytes"] for r in rows)}
    selection_path, plan_path = tmp_path / "selection.json", tmp_path / "plan.json"
    selection_path.write_text(json.dumps(selection))
    stage.plan_selection(selection_path, fixtures.sha(selection_path), plan_path, chunk_grouping=stage.STORAGE_GROUPING)
    return root, folder, plan_path


def test_ten_thousand_and_one_raw_files_stage_verify_and_restore_as_one_tar(tmp_path, monkeypatch):
    root, folder, plan = raw_plan(tmp_path, monkeypatch, 10001)
    deadline = time.monotonic() + 240
    result = stage.stage_chunk(plan, fixtures.sha(plan), "chunk-00000", tmp_path / "stage",
                              source_root=root, admission=lambda: True, deadline_monotonic=deadline,
                              free_space_reserve_bytes=0)
    assert result["status"] == "PASS" and result["source_retained"]
    manifest = json.loads((tmp_path / "stage/manifest.json").read_bytes())
    assert len(manifest["files"]) == 10001
    bridge.validate_production_evidence(manifest, result, fixtures.sha(plan))
    restored_root = tmp_path / "restored"
    with ExitStack() as stack:
        restored = bridge._materialize(tmp_path / "stage/archive.tar.gz", restored_root, manifest, deadline, stack)
    assert len(restored) == 10001 and len(list(folder.iterdir())) == 10001
    for row in restored:
        assert (restored_root / row["path"]).read_bytes() == (root / row["path"]).read_bytes()


def test_raw_subtree_selection_cannot_omit_a_file(tmp_path, monkeypatch):
    root, folder, plan = raw_plan(tmp_path, monkeypatch, 2)
    (folder / "not-selected.json").write_bytes(b"{}")
    with pytest.raises(stage.ArchiveStageError, match="complete event subtree"):
        stage.stage_chunk(plan, fixtures.sha(plan), "chunk-00000", tmp_path / "stage",
                          source_root=root, admission=lambda: True, deadline_monotonic=time.monotonic() + 30,
                          free_space_reserve_bytes=0)
    assert len(list(folder.iterdir())) == 3

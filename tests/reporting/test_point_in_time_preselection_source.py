import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import weather.calibration.pooled_candidate_replay as pooled_replay
from weather.calibration.pooled_candidate_replay import (
    BoundedCandidateReplayError,
    iter_bounded_preselection_source_market_days,
    load_bounded_preselection_folder_inputs,
)
from weather.reporting.data_quality.feature_quality_quarantine import (
    audit_folder_feature_quality,
    audit_folder_feature_quality_from_rows,
    read_csv_rows,
)
from weather.reporting.promotion.promotion_corpus import (
    PROMOTION_CORPUS_SCHEMA_VERSION,
    build_promotion_corpus,
    corpus_hash,
)
from weather.reporting.validation.point_in_time_evaluation import (
    CONTRACT_SCHEMA_VERSION,
    MATERIALIZER_SCHEMA_VERSION,
    POINT_IN_TIME_ARROW_SCHEMA,
    PRODUCTION_PRESELECTION_SOURCE_ARROW_SCHEMA,
    PRODUCTION_PRESELECTION_SOURCE_SCHEMA_VERSION,
    BoundedReadError,
    ContractViolation,
    _verify_preselection_source_corpus,
    canonical_json,
    canonicalize_raw_row,
    materialize_production_preselection_source,
    selection_universe_contract,
    sha256_text,
    validate_production_preselection_source_row,
    verify_production_preselection_source_manifest,
)


FORBIDDEN_SOURCE_FIELDS = {
    "candidate_id",
    "variant_id",
    "release_id",
    "prediction_probability",
    "runtime_identity",
    "source_payload_json",
    "source_payload_sha256",
    "source_provenance_json",
}


def _label_hash(entry):
    payload = {
        key: entry.get(key)
        for key in (
            "event_slug",
            "market_id",
            "target_date",
            "settlement_bucket",
            "settlement_unit",
            "settlement_source",
            "quality_grade",
            "winning_band",
        )
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _event_slug(target_date):
    parsed = date.fromisoformat(target_date)
    return (
        "highest-temperature-in-nyc-on-"
        f"{parsed.strftime('%B').lower()}-{parsed.day}-{parsed.year}"
    )


def _entry(target_date, *, folder=None, market_id="nyc", row_count=2):
    slug = _event_slug(target_date)
    snapshot_id = f"snapshot-{target_date}"
    entry = {
        "event_slug": slug,
        "market_id": market_id,
        "city": "New York City",
        "target_date": target_date,
        "folder": str(folder) if folder is not None else slug,
        "folder_name": slug,
        "folder_relative_to_snapshots_root": slug,
        "snapshot_tape_path": str(Path(folder or slug) / "snapshots_long.csv"),
        "settlement_bucket": 80,
        "settlement_unit": "F",
        "settlement_source": "weather_underground_history",
        "winning_band": "80-81",
        "winning_band_kind": "range",
        "winning_band_value": 80,
        "winning_band_value_hi": 81,
        "quality_grade": "complete",
        "quality_reason": "verified",
        "admitted_by": "quality_grade",
        "promotion_countable": True,
        "snapshot_ids": [snapshot_id],
        "snapshot_count": 1,
        "snapshot_count_in_tape": 1,
        "missing_replay_input_count": 0,
        "reconstructed_excluded_count": 0,
        "reconstructed_record_count": 0,
        "feature_quality_excluded_snapshot_ids": [],
        "feature_quality_excluded_snapshot_count": 0,
        "feature_quality_excluded_band_row_count": 0,
        "feature_quality_quarantine": {},
        "replay_record_count": 1,
        "identity_record_count": 1,
        "band_count": row_count,
        "row_count": row_count,
        "recorded_versions": ["captured-v1"],
        "replay_record_hashes": {snapshot_id: "1" * 64},
        "tape_row_hashes": {snapshot_id: "2" * 64},
    }
    entry["label_hash"] = _label_hash(entry)
    return entry


def _write_replay_manifest(path, entries, *, snapshots_root, **overrides):
    payload = {
        "schema_version": PROMOTION_CORPUS_SCHEMA_VERSION,
        "generated_at_utc": "2026-07-03T12:00:00+00:00",
        "as_of": "2026-07-03",
        "snapshots_root": str(snapshots_root),
        "quality_grades": ["complete", "manual_override"],
        "admit_promotion_countable": False,
        "include_reconstructed": False,
        "allow_unsettled": False,
        "min_snapshots": 1,
        "market_filter": None,
        "entries": list(entries),
        "summary": {"market_day_count": len(entries)},
        "skipped": [],
    }
    payload.update(overrides)
    payload["corpus_hash"] = corpus_hash(payload["entries"])
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def _write_proof_grade_replay(tmp_path, *, bands):
    snapshots_root = tmp_path / "snapshots"
    slug = _event_slug("2026-06-01")
    folder = snapshots_root / slug
    folder.mkdir(parents=True)
    snapshot_id = "snapshot-2026-06-01"
    captured_at = "2026-06-01T16:00:00+00:00"
    tape_rows = [
        {
            "snapshot_id": snapshot_id,
            "captured_at_local": captured_at,
            "event_slug": slug,
            "range_label": range_label,
            "bin_kind": bin_kind,
            "bin_value_c": bin_value,
        }
        for range_label, bin_kind, bin_value in bands
    ]
    with (folder / "snapshots_long.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(tape_rows[0]))
        writer.writeheader()
        writer.writerows(tape_rows)
    replay_record = {
        "schema_version": "captured_replay_inputs_v1",
        "snapshot_id": snapshot_id,
        "captured_at_local": captured_at,
        "event_slug": slug,
        "target_date": "2026-06-01",
        "source": "captured",
    }
    (folder / "replay_inputs.jsonl").write_text(
        json.dumps(replay_record, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    settlement = {
        "schema_version": "settlement_ledger_v1",
        "event_slug": slug,
        "market_id": "nyc",
        "city": "New York City",
        "target_date": "2026-06-01",
        "settlement_high": 80,
        "settlement_bucket": 80,
        "settlement_unit": "F",
        "winning_band": "80-81",
        "winning_band_kind": "range",
        "winning_band_value": 80,
        "winning_band_value_hi": 81,
        "settlement_source": "weather_underground_history",
        "quality_grade": "complete",
        "quality_reason": "verified test settlement",
    }
    (folder / "settlement.json").write_text(
        json.dumps(settlement, sort_keys=True),
        encoding="utf-8",
    )
    manifest = build_promotion_corpus(
        [folder],
        snapshots_root=snapshots_root,
        as_of="2026-07-03",
        admit_promotion_countable=False,
    )
    assert manifest["summary"]["market_day_count"] == 1
    manifest_path = tmp_path / "replay.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return snapshots_root, manifest_path, manifest


def _consume_preselection_replay(manifest_path, snapshots_root, *, max_rows=250_000):
    return list(
        iter_bounded_preselection_source_market_days(
            corpus_manifest_path=manifest_path,
            expected_manifest_sha256=hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            snapshots_root=snapshots_root,
            max_market_days=60,
            max_rows_per_market_day=max_rows,
        )
    )


def _write_minimal_tape(path, *, row_count=1, range_label="80-81"):
    rows = [
        {
            "snapshot_id": f"snapshot-{index}",
            "captured_at_local": "2026-06-01T16:00:00+00:00",
            "range_label": range_label,
            "bin_kind": "eq",
            "bin_value_c": 80,
        }
        for index in range(row_count)
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _materialize_valid_staged_source(tmp_path):
    entry = _entry("2026-06-01")
    replay = tmp_path / "replay.json"
    _write_replay_manifest(replay, [entry], snapshots_root=tmp_path / "snapshots")
    corpus = tmp_path / "source.parquet"
    source_manifest = tmp_path / "source-manifest.json"
    with patch(
        "weather.reporting.validation.point_in_time_evaluation."
        "iter_bounded_preselection_source_market_days",
        return_value=iter([_source_day(entry)]),
    ):
        materialize_production_preselection_source(
            replay_manifest=replay,
            parquet_out=corpus,
            manifest_out=source_manifest,
            snapshots_root=tmp_path / "snapshots",
        )
    return corpus, source_manifest, replay


def _write_self_hashed_manifest(path, payload):
    payload.pop("manifest_hash", None)
    payload["manifest_hash"] = sha256_text(canonical_json(payload))
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _refresh_staged_corpus_binding(corpus, source_manifest):
    payload = json.loads(source_manifest.read_text(encoding="utf-8"))
    payload["derived_artifact"]["sha256"] = hashlib.sha256(
        corpus.read_bytes()
    ).hexdigest()
    payload["derived_artifact"]["bytes"] = corpus.stat().st_size
    _write_self_hashed_manifest(source_manifest, payload)


def _rewrite_staged_rows(corpus, source_manifest, mutate):
    rows = pq.read_table(corpus).to_pylist()
    for row in rows:
        mutate(row)
    pq.write_table(
        pa.Table.from_pylist(
            rows,
            schema=PRODUCTION_PRESELECTION_SOURCE_ARROW_SCHEMA,
        ),
        corpus,
        compression="zstd",
    )
    _refresh_staged_corpus_binding(corpus, source_manifest)


def _rewrite_replay_and_rebind(replay, source_manifest, mutate):
    replay_payload = json.loads(replay.read_text(encoding="utf-8"))
    mutate(replay_payload)
    replay.write_text(
        json.dumps(replay_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    source_payload = json.loads(source_manifest.read_text(encoding="utf-8"))
    source_payload["source_replay_manifest"]["sha256"] = hashlib.sha256(
        replay.read_bytes()
    ).hexdigest()
    source_payload["source_replay_manifest"]["corpus_hash"] = replay_payload[
        "corpus_hash"
    ]
    _write_self_hashed_manifest(source_manifest, source_payload)


def _source_day(entry, *, market_id=None, time="16:00:00+00:00"):
    snapshot_id = entry["snapshot_ids"][0]
    rows = []
    for band, label in (("80-81", 1.0), ("82-83", 0.0)):
        rows.append(
            {
                "target_date": entry["target_date"],
                "market_id": market_id or entry["market_id"],
                "cutoff_or_snapshot": snapshot_id,
                "band": band,
                "feature_available_at_utc": f"{entry['target_date']}T{time}",
                "prediction_boundary_at_utc": f"{entry['target_date']}T{time}",
                "label_quality": "complete",
                "countable": True,
                "claim_lane": "weather_only",
                "source_quality": "healthy",
                "label": label,
            }
        )
    return rows


def _write_source_parquet(path, rows):
    canonical = [
        validate_production_preselection_source_row(
            {
                "schema_version": PRODUCTION_PRESELECTION_SOURCE_SCHEMA_VERSION,
                **row,
            }
        )
        for row in rows
    ]
    pq.write_table(
        pa.Table.from_pylist(
            canonical,
            schema=PRODUCTION_PRESELECTION_SOURCE_ARROW_SCHEMA,
        ),
        path,
    )


def _write_candidate_parquet(
    path,
    source_rows,
    *,
    probabilities=(0.7, 0.3),
    variant="candidate-v1",
    release="release-v1",
    runtime="runtime-v1",
    mutate=None,
):
    rows = []
    for index, source in enumerate(source_rows):
        raw = {
            "schema_version": CONTRACT_SCHEMA_VERSION,
            "target_date": source["target_date"],
            "market_id": source["market_id"],
            "snapshot_id": source["cutoff_or_snapshot"],
            "range_label": source["band"],
            "variant_id": variant,
            "release_id": release,
            "feature_available_at_utc": source["feature_available_at_utc"],
            "captured_at_utc": source["prediction_boundary_at_utc"],
            "label_quality": source["label_quality"],
            "countable": source["countable"],
            "claim_lane": source["claim_lane"],
            "replay_serve_parity": "pass",
            "source_quality": source["source_quality"],
            "prediction_probability": probabilities[index],
            "label": source["label"],
            "runtime_identity": runtime,
        }
        if mutate is not None:
            mutate(raw, index)
        rows.append(
            canonicalize_raw_row(
                raw,
                provenance={"source_mode": "bounded_candidate_replay"},
            )
        )
    pq.write_table(
        pa.Table.from_pylist(rows, schema=POINT_IN_TIME_ARROW_SCHEMA),
        path,
    )


def test_production_prelock_rejects_the_legacy_candidate_bearing_source(tmp_path):
    corpus = tmp_path / "legacy.parquet"
    corpus.write_bytes(b"not consulted")
    manifest = {
        "schema_version": MATERIALIZER_SCHEMA_VERSION,
        "artifact_type": "point_in_time_materialization_manifest",
        "status": "PASS",
    }
    manifest["manifest_hash"] = sha256_text(canonical_json(manifest))
    manifest_path = tmp_path / "legacy-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with patch(
        "weather.reporting.validation.point_in_time_evaluation."
        "verify_materialization_manifest",
        side_effect=AssertionError("legacy verifier must not be a production fallback"),
    ) as legacy_verifier:
        with pytest.raises(ContractViolation, match="candidate-independent|preselection source"):
            _verify_preselection_source_corpus(corpus, manifest_path)
    legacy_verifier.assert_not_called()


@pytest.mark.parametrize(
    ("override", "value"),
    (
        ("max_market_days", 61),
        ("max_rows_per_market_day", 250_001),
        ("batch_rows", 65_537),
    ),
)
def test_production_bounds_fail_before_loading_the_replay_manifest(
    tmp_path, override, value
):
    kwargs = {
        "replay_manifest": tmp_path / "missing-replay.json",
        "parquet_out": tmp_path / "source.parquet",
        "manifest_out": tmp_path / "source-manifest.json",
        "max_market_days": 60,
        "max_rows_per_market_day": 250_000,
        "batch_rows": 65_536,
    }
    kwargs[override] = value
    with patch(
        "weather.reporting.validation.point_in_time_evaluation."
        "load_promotion_corpus_manifest"
    ) as loader:
        with pytest.raises(ValueError, match="bound|streaming|market|row|batch"):
            materialize_production_preselection_source(**kwargs)
    loader.assert_not_called()


def test_materializer_reports_an_empty_replay_manifest(tmp_path):
    replay = tmp_path / "replay.json"
    _write_replay_manifest(replay, [], snapshots_root=tmp_path / "snapshots")
    corpus = tmp_path / "source.parquet"
    manifest = tmp_path / "source-manifest.json"

    with pytest.raises(BoundedReadError, match="replay manifest is empty"):
        materialize_production_preselection_source(
            replay_manifest=replay,
            parquet_out=corpus,
            manifest_out=manifest,
            snapshots_root=tmp_path / "snapshots",
        )

    assert not corpus.exists()
    assert not manifest.exists()


def test_materializer_rejects_an_iterator_that_omits_a_replay_market_day(tmp_path):
    entries = [_entry("2026-06-01"), _entry("2026-06-02")]
    replay = tmp_path / "replay.json"
    _write_replay_manifest(replay, entries, snapshots_root=tmp_path / "snapshots")
    corpus = tmp_path / "source.parquet"
    manifest = tmp_path / "source-manifest.json"

    with patch(
        "weather.reporting.validation.point_in_time_evaluation."
        "iter_bounded_preselection_source_market_days",
        return_value=iter([_source_day(entries[0])]),
    ):
        with pytest.raises((ContractViolation, BoundedCandidateReplayError), match="inventory|market-day|replay"):
            materialize_production_preselection_source(
                replay_manifest=replay,
                parquet_out=corpus,
                manifest_out=manifest,
                snapshots_root=tmp_path / "snapshots",
            )

    assert not corpus.exists()
    assert not manifest.exists()


def test_materializer_rejects_the_right_date_with_the_wrong_market(tmp_path):
    entry = _entry("2026-06-01")
    replay = tmp_path / "replay.json"
    _write_replay_manifest(replay, [entry], snapshots_root=tmp_path / "snapshots")
    corpus = tmp_path / "source.parquet"
    manifest = tmp_path / "source-manifest.json"

    with patch(
        "weather.reporting.validation.point_in_time_evaluation."
        "iter_bounded_preselection_source_market_days",
        return_value=iter([_source_day(entry, market_id="boston")]),
    ):
        with pytest.raises((ContractViolation, BoundedCandidateReplayError), match="inventory|market-day|market"):
            materialize_production_preselection_source(
                replay_manifest=replay,
                parquet_out=corpus,
                manifest_out=manifest,
                snapshots_root=tmp_path / "snapshots",
            )

    assert not corpus.exists()
    assert not manifest.exists()


def test_iterator_rejects_a_manifest_folder_outside_snapshots_root(tmp_path):
    snapshots_root = tmp_path / "snapshots"
    snapshots_root.mkdir()
    outside = tmp_path / "outside" / _event_slug("2026-06-01")
    outside.mkdir(parents=True)
    entry = _entry("2026-06-01", folder=outside)
    replay = tmp_path / "replay.json"
    _write_replay_manifest(replay, [entry], snapshots_root=snapshots_root)

    iterator = iter_bounded_preselection_source_market_days(
        corpus_manifest_path=replay,
        expected_manifest_sha256=hashlib.sha256(replay.read_bytes()).hexdigest(),
        snapshots_root=snapshots_root,
        max_market_days=60,
        max_rows_per_market_day=250_000,
    )
    with pytest.raises(BoundedCandidateReplayError, match="snapshots root|outside"):
        next(iterator)


@pytest.mark.parametrize(
    ("flag", "match"),
    (
        ("include_reconstructed", "reconstructed"),
        ("allow_unsettled", "unsettled"),
    ),
)
def test_iterator_rejects_non_proof_grade_manifest_modes(tmp_path, flag, match):
    snapshots_root = tmp_path / "snapshots"
    snapshots_root.mkdir()
    replay = tmp_path / "replay.json"
    _write_replay_manifest(
        replay,
        [_entry("2026-06-01")],
        snapshots_root=snapshots_root,
        **{flag: True},
    )

    iterator = iter_bounded_preselection_source_market_days(
        corpus_manifest_path=replay,
        expected_manifest_sha256=hashlib.sha256(replay.read_bytes()).hexdigest(),
        snapshots_root=snapshots_root,
        max_market_days=60,
        max_rows_per_market_day=250_000,
    )
    with pytest.raises(BoundedCandidateReplayError, match=match):
        next(iterator)


@pytest.mark.parametrize(
    "missing_flag",
    ("include_reconstructed", "allow_unsettled", "admit_promotion_countable"),
)
def test_iterator_requires_explicit_false_production_manifest_flags(
    tmp_path, missing_flag
):
    snapshots_root, replay, manifest = _write_proof_grade_replay(
        tmp_path,
        bands=(("80-81", "eq", 80), ("82-83", "eq", 82)),
    )
    del manifest[missing_flag]
    replay.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(BoundedCandidateReplayError, match=missing_flag):
        _consume_preselection_replay(replay, snapshots_root)


def test_iterator_recomputes_and_rejects_a_stale_label_hash(tmp_path):
    snapshots_root, replay, manifest = _write_proof_grade_replay(
        tmp_path,
        bands=(("80-81", "eq", 80), ("82-83", "eq", 82)),
    )
    manifest["entries"][0]["settlement_source"] = "tampered_source"
    manifest["corpus_hash"] = corpus_hash(manifest["entries"])
    replay.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(BoundedCandidateReplayError, match="label hash is invalid"):
        _consume_preselection_replay(replay, snapshots_root)


@pytest.mark.parametrize(
    "bands",
    (
        (("78-79", "eq", 78), ("82-83", "eq", 82)),
        (
            ("80 or below", "lte", 80),
            ("80-81", "eq", 80),
            ("82-83", "eq", 82),
        ),
    ),
    ids=("zero-winners", "two-winners"),
)
def test_iterator_requires_exactly_one_winner_per_snapshot(tmp_path, bands):
    snapshots_root, replay, _manifest = _write_proof_grade_replay(
        tmp_path,
        bands=bands,
    )

    with pytest.raises(BoundedCandidateReplayError, match="exactly one winner"):
        _consume_preselection_replay(replay, snapshots_root)


def test_direct_tape_reader_enforces_the_byte_bound_before_parsing(tmp_path):
    tape = tmp_path / "snapshots_long.csv"
    tape.write_bytes(b"x" * 32)

    with patch.object(pooled_replay, "_PRESELECTION_MAX_TAPE_BYTES", 31):
        with pytest.raises(BoundedCandidateReplayError, match="tape byte bound"):
            pooled_replay._bounded_preselection_tape(tape, max_rows=10)


def test_direct_tape_reader_enforces_the_field_bound(tmp_path):
    tape = tmp_path / "snapshots_long.csv"
    _write_minimal_tape(tape, range_label="x" * 128)

    with patch.object(pooled_replay, "_PRESELECTION_MAX_TAPE_FIELD_BYTES", 32):
        with pytest.raises(BoundedCandidateReplayError, match="within bounds"):
            pooled_replay._bounded_preselection_tape(tape, max_rows=10)


def test_direct_tape_reader_enforces_the_raw_row_bound(tmp_path):
    tape = tmp_path / "snapshots_long.csv"
    _write_minimal_tape(tape, row_count=2)

    with pytest.raises(BoundedCandidateReplayError, match="raw tape row bound"):
        pooled_replay._bounded_preselection_tape(tape, max_rows=1)


def test_direct_replay_reader_enforces_the_byte_bound_before_parsing(tmp_path):
    replay = tmp_path / "replay_inputs.jsonl"
    replay.write_text(
        json.dumps({"snapshot_id": "snapshot-1"}) + "\n",
        encoding="utf-8",
    )

    with patch.object(
        pooled_replay,
        "_PRESELECTION_MAX_REPLAY_BYTES",
        replay.stat().st_size - 1,
    ):
        with pytest.raises(BoundedCandidateReplayError, match="replay byte bound"):
            pooled_replay._bounded_preselection_replay_records(
                replay,
                pinned_snapshot_ids={"snapshot-1"},
                max_records=10,
            )


def test_direct_replay_reader_enforces_the_line_bound(tmp_path):
    replay = tmp_path / "replay_inputs.jsonl"
    replay.write_text(
        json.dumps({"snapshot_id": "snapshot-1", "padding": "x" * 64}) + "\n",
        encoding="utf-8",
    )

    with patch.object(pooled_replay, "_PRESELECTION_MAX_REPLAY_LINE_BYTES", 32):
        with pytest.raises(BoundedCandidateReplayError, match="line 1.*byte bound"):
            pooled_replay._bounded_preselection_replay_records(
                replay,
                pinned_snapshot_ids={"snapshot-1"},
                max_records=10,
            )


def test_direct_replay_reader_enforces_the_raw_record_bound(tmp_path):
    replay = tmp_path / "replay_inputs.jsonl"
    replay.write_text(
        "\n".join(
            json.dumps({"snapshot_id": snapshot_id})
            for snapshot_id in ("snapshot-1", "snapshot-2")
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(BoundedCandidateReplayError, match="record bound"):
        pooled_replay._bounded_preselection_replay_records(
            replay,
            pinned_snapshot_ids={"snapshot-1"},
            max_records=1,
        )


def test_staged_source_rejects_same_row_count_snapshot_substitution(tmp_path):
    corpus, source_manifest, replay = _materialize_valid_staged_source(tmp_path)
    _rewrite_staged_rows(
        corpus,
        source_manifest,
        lambda row: row.update({"cutoff_or_snapshot": "substituted-snapshot"}),
    )

    with pytest.raises(ContractViolation) as caught:
        verify_production_preselection_source_manifest(
            corpus,
            source_manifest,
            replay_manifest=replay,
        )

    assert caught.value.code == "preselection_source_replay_mismatch"


@pytest.mark.parametrize("winner_mode", ("wrong-band", "zero-winner"))
def test_staged_source_rejects_wrong_or_missing_winner(tmp_path, winner_mode):
    corpus, source_manifest, replay = _materialize_valid_staged_source(tmp_path)

    def mutate(row):
        row["label"] = (
            1.0
            if winner_mode == "wrong-band" and row["band"] == "82-83"
            else 0.0
        )

    _rewrite_staged_rows(corpus, source_manifest, mutate)

    with pytest.raises(ContractViolation) as caught:
        verify_production_preselection_source_manifest(
            corpus,
            source_manifest,
            replay_manifest=replay,
        )

    assert caught.value.code == "preselection_source_replay_mismatch"


@pytest.mark.parametrize(
    "missing_flag",
    ("include_reconstructed", "allow_unsettled", "admit_promotion_countable"),
)
def test_staged_source_requires_explicit_false_replay_flags(tmp_path, missing_flag):
    corpus, source_manifest, replay = _materialize_valid_staged_source(tmp_path)
    _rewrite_replay_and_rebind(
        replay,
        source_manifest,
        lambda payload: payload.pop(missing_flag),
    )

    with pytest.raises(ContractViolation) as caught:
        verify_production_preselection_source_manifest(
            corpus,
            source_manifest,
            replay_manifest=replay,
        )

    assert caught.value.code == "preselection_source_replay_mismatch"


def test_staged_source_rejects_target_on_replay_as_of_date(tmp_path):
    corpus, source_manifest, replay = _materialize_valid_staged_source(tmp_path)
    _rewrite_replay_and_rebind(
        replay,
        source_manifest,
        lambda payload: payload.update({"as_of": "2026-06-01"}),
    )

    with pytest.raises(ContractViolation) as caught:
        verify_production_preselection_source_manifest(
            corpus,
            source_manifest,
            replay_manifest=replay,
        )

    assert caught.value.code == "preselection_source_replay_mismatch"


def test_bounded_folder_loader_rejects_an_input_file_symlink_escape(tmp_path):
    snapshots_root, _replay, _manifest = _write_proof_grade_replay(
        tmp_path,
        bands=(("80-81", "eq", 80), ("82-83", "eq", 82)),
    )
    folder = snapshots_root / _event_slug("2026-06-01")
    tape = folder / "snapshots_long.csv"
    outside = tmp_path / "outside-snapshots-long.csv"
    outside.write_bytes(tape.read_bytes())
    tape.unlink()
    try:
        tape.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable on this host: {exc}")

    with pytest.raises(BoundedCandidateReplayError, match="symlink|escaped"):
        load_bounded_preselection_folder_inputs(
            folder,
            snapshots_root=snapshots_root,
            max_rows_per_market_day=100,
        )


def test_bounded_feature_quality_audit_matches_legacy_fixture(tmp_path):
    snapshots_root, _replay, _manifest = _write_proof_grade_replay(
        tmp_path,
        bands=(("80-81", "eq", 80), ("82-83", "eq", 82)),
    )
    folder = snapshots_root / _event_slug("2026-06-01")
    feature = {
        "snapshot_id": "snapshot-2026-06-01",
        "captured_at_local": "2026-06-01T16:00:00+00:00",
        "event_slug": folder.name,
        "target_date": "2026-06-01",
        "high_so_far": "80",
        "current_temp": "80",
        "trusted_current_max": "110",
    }
    with (folder / "features_long.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(feature))
        writer.writeheader()
        writer.writerow(feature)
    (folder / "observation_payloads_long.csv").write_text(
        "snapshot_id,source,status\n"
        "snapshot-2026-06-01,wu_current,fresh\n",
        encoding="utf-8",
    )
    replay_records = {
        record["snapshot_id"]: record
        for record in (
            json.loads(line)
            for line in (folder / "replay_inputs.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        )
    }
    pure = audit_folder_feature_quality_from_rows(
        folder,
        feature_rows=read_csv_rows(folder / "features_long.csv"),
        snapshot_rows=read_csv_rows(folder / "snapshots_long.csv"),
        replay_records=replay_records,
        settlement_unit="F",
    )
    legacy = audit_folder_feature_quality(folder)
    bounded = load_bounded_preselection_folder_inputs(
        folder,
        snapshots_root=snapshots_root,
        max_rows_per_market_day=100,
    )["feature_quality"]

    assert pure == legacy
    assert bounded == legacy
    assert legacy["summary"]["quarantine_row_count"] == 1
    assert legacy["summary"]["recovered_row_count"] == 1


def test_source_mutation_publishes_neither_half_of_the_artifact_pair(tmp_path):
    entries = [_entry("2026-06-01"), _entry("2026-06-02")]
    replay = tmp_path / "replay.json"
    _write_replay_manifest(replay, entries, snapshots_root=tmp_path / "snapshots")
    corpus = tmp_path / "source.parquet"
    manifest = tmp_path / "source-manifest.json"

    def mutating_stream(**_kwargs):
        yield _source_day(entries[0])
        raise BoundedCandidateReplayError("source changed during replay")

    with patch(
        "weather.reporting.validation.point_in_time_evaluation."
        "iter_bounded_preselection_source_market_days",
        side_effect=mutating_stream,
    ):
        with pytest.raises(BoundedCandidateReplayError, match="changed"):
            materialize_production_preselection_source(
                replay_manifest=replay,
                parquet_out=corpus,
                manifest_out=manifest,
                snapshots_root=tmp_path / "snapshots",
            )

    assert not corpus.exists()
    assert not manifest.exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_existing_source_outputs_are_immutable(tmp_path):
    corpus = tmp_path / "source.parquet"
    manifest = tmp_path / "source-manifest.json"
    corpus.write_bytes(b"existing corpus")
    manifest.write_bytes(b"existing manifest")

    with patch(
        "weather.reporting.validation.point_in_time_evaluation."
        "load_promotion_corpus_manifest",
        side_effect=AssertionError("existing outputs must fail before input loading"),
    ) as loader:
        with pytest.raises(FileExistsError):
            materialize_production_preselection_source(
                replay_manifest=tmp_path / "replay.json",
                parquet_out=corpus,
                manifest_out=manifest,
            )

    loader.assert_not_called()
    assert corpus.read_bytes() == b"existing corpus"
    assert manifest.read_bytes() == b"existing manifest"


def test_materialized_source_physically_excludes_all_candidate_fields(tmp_path):
    entry = _entry("2026-06-01")
    entry["settlement_label_authority"] = {
        "status": "sidecar_fallback_no_ledger_row",
        "sidecar_fallback": True,
    }
    replay = tmp_path / "replay.json"
    _write_replay_manifest(replay, [entry], snapshots_root=tmp_path / "snapshots")
    corpus = tmp_path / "source.parquet"
    manifest_path = tmp_path / "source-manifest.json"

    with patch(
        "weather.reporting.validation.point_in_time_evaluation."
        "iter_bounded_preselection_source_market_days",
        return_value=iter([_source_day(entry)]),
    ):
        manifest = materialize_production_preselection_source(
            replay_manifest=replay,
            parquet_out=corpus,
            manifest_out=manifest_path,
            snapshots_root=tmp_path / "snapshots",
        )

    schema_names = set(pq.ParquetFile(corpus).schema_arrow.names)
    persisted_rows = pq.read_table(corpus).to_pylist()
    assert schema_names == set(PRODUCTION_PRESELECTION_SOURCE_ARROW_SCHEMA.names)
    assert schema_names.isdisjoint(FORBIDDEN_SOURCE_FIELDS)
    assert all(set(row).isdisjoint(FORBIDDEN_SOURCE_FIELDS) for row in persisted_rows)
    assert manifest["candidate_dependent_fields_included"] == []
    assert manifest["summary"]["settlement_label_authority"] == {
        "sidecar_fallback_no_ledger_row": 1
    }


def test_selection_universe_is_probability_independent_but_not_population_blind(
    tmp_path,
):
    entry = _entry("2026-06-01")
    source_rows = _source_day(entry)
    source = tmp_path / "source.parquet"
    candidate_a = tmp_path / "candidate-a.parquet"
    candidate_b = tmp_path / "candidate-b.parquet"
    _write_source_parquet(source, source_rows)
    _write_candidate_parquet(
        candidate_a,
        source_rows,
        probabilities=(0.99, 0.01),
        variant="candidate-a",
        release="release-a",
        runtime="runtime-a",
    )
    _write_candidate_parquet(
        candidate_b,
        source_rows,
        probabilities=(0.2, 0.8),
        variant="candidate-b",
        release="release-b",
        runtime="runtime-b",
    )

    expected = selection_universe_contract(source, batch_rows=1)
    assert selection_universe_contract(candidate_a, batch_rows=1) == expected
    assert selection_universe_contract(candidate_b, batch_rows=1) == expected

    mutations = {
        "coordinate": lambda row, index: row.update(
            {"range_label": "changed-band"}
        )
        if index == 1
        else None,
        "timestamp": lambda row, index: row.update(
            {
                "feature_available_at_utc": "2026-06-01T16:01:00+00:00",
                "captured_at_utc": "2026-06-01T16:01:00+00:00",
            }
        )
        if index == 1
        else None,
        "label": lambda row, index: row.update({"label": 1.0})
        if index == 1
        else None,
        "quality": lambda row, index: row.update(
            {"label_quality": "manual_override"}
        )
        if index == 1
        else None,
    }
    for name, mutation in mutations.items():
        path = tmp_path / f"candidate-{name}.parquet"
        _write_candidate_parquet(path, source_rows, mutate=mutation)
        assert selection_universe_contract(path, batch_rows=1) != expected

import csv
import json
from datetime import date, timedelta

import pyarrow.parquet as pq
import pytest

from weather.point_in_time_contract import (
    ContractViolation as FrozenContractViolation,
    verify_materialization_manifest as verify_frozen_materialization_manifest,
)
from weather.reporting.validation.point_in_time_evaluation import (
    CLAIM_LANES,
    CONTRACT_SCHEMA_VERSION,
    MATERIALIZER_SCHEMA_VERSION,
    VALIDATION_PLAN_SCHEMA_VERSION,
    _read_bounded_contract_json,
    _read_contract_json,
    _verified_stage_selection_binding,
    _verify_production_latest_target_freshness,
    ContractViolation,
    RollingOriginFold,
    build_nested_rolling_origin_folds,
    build_rolling_origin_folds,
    build_window_lock,
    canonical_json,
    canonicalize_raw_row,
    date_clustered_bootstrap_interval,
    evaluate_point_in_time_rows,
    iter_point_in_time_parquet,
    materialize_point_in_time_table,
    materialize_production_candidate_packet,
    point_in_time_key,
    run_training_only_pipeline,
    sha256_text,
    validate_canonical_row,
    validation_plan_payload,
    verify_materialization_manifest,
    verify_streaming_evaluation_payload,
    verify_validation_plan_payload,
)


PROVENANCE = {
    "artifact_family": "snapshots_long",
    "source_mode": "validated_parquet",
    "manifest_hash": "manifest-hash",
    "source_file_hash": "source-hash",
}


def test_bounded_contract_json_rejects_nested_exponent_overflow(tmp_path):
    contract = tmp_path / "control.json"
    contract.write_text(
        '{"contract":{"receipts":[{"seconds":1e999}]}}',
        encoding="utf-8",
    )

    with pytest.raises(
        ContractViolation,
        match=r"non-finite JSON number at \$\.contract\.receipts\[0\]\.seconds",
    ):
        _read_bounded_contract_json(
            contract,
            code="overflow_control",
            max_bytes=1024,
        )


def test_contract_json_rejects_nested_exponent_overflow(tmp_path):
    contract = tmp_path / "full-contract.json"
    contract.write_text(
        '{"contract":{"receipts":[{"seconds":1e999}]}}',
        encoding="utf-8",
    )

    with pytest.raises(
        ContractViolation,
        match=r"non-finite JSON number at \$\.contract\.receipts\[0\]\.seconds",
    ):
        _read_contract_json(contract, code="overflow_full_contract")


def test_stage_selection_binding_rejects_self_hashed_locked_inventory():
    locked_dates = [
        (date(2026, 6, 1) + timedelta(days=offset)).isoformat()
        for offset in range(14)
    ]
    inventory = {
        "entries": [{"target_date": locked_dates[0]}],
        "entry_count": 1,
    }
    inventory["sha256"] = sha256_text(canonical_json(inventory))
    binding = {
        "preselection_hash": "a" * 64,
        "window_lock_id": "b" * 64,
        "locked_dates": locked_dates,
        "used_for_selection": False,
        "source_folder_date_inventory_sha256": inventory["sha256"],
        "source_inventory": inventory,
    }
    binding["binding_sha256"] = sha256_text(canonical_json(binding))

    with pytest.raises(ContractViolation, match="includes locked dates"):
        _verified_stage_selection_binding(
            {"point_in_time_selection_binding": binding},
            preselection={
                "preselection_hash": "a" * 64,
                "window_lock": {
                    "window_lock_id": "b" * 64,
                    "target_dates": locked_dates,
                },
            },
            stage="calibration",
        )


def test_stage_selection_binding_rejects_self_hashed_out_of_universe_inventory():
    universe_dates = [
        (date(2026, 5, 26) + timedelta(days=offset)).isoformat()
        for offset in range(20)
    ]
    locked_dates = universe_dates[-14:]
    inventory = {
        "entries": [{"target_date": "2026-05-01"}],
        "entry_count": 1,
    }
    inventory["sha256"] = sha256_text(canonical_json(inventory))
    binding = {
        "preselection_hash": "a" * 64,
        "window_lock_id": "b" * 64,
        "locked_dates": locked_dates,
        "used_for_selection": False,
        "source_folder_date_inventory_sha256": inventory["sha256"],
        "source_inventory": inventory,
    }
    binding["binding_sha256"] = sha256_text(canonical_json(binding))

    with pytest.raises(ContractViolation, match="outside the immutable"):
        _verified_stage_selection_binding(
            {"point_in_time_selection_binding": binding},
            preselection={
                "preselection_hash": "a" * 64,
                "window_lock": {
                    "window_lock_id": "b" * 64,
                    "target_dates": locked_dates,
                },
                "selection_universe": {"fleet_dates": universe_dates},
            },
            stage="calibration",
        )


def test_production_preselection_rejects_stale_latest_target_date():
    with pytest.raises(ContractViolation, match="latest target date is stale"):
        _verify_production_latest_target_freshness(
            ["2026-01-01"],
            locked_at_utc="2026-02-01T12:00:00+00:00",
            require_current_prelock=False,
        )


def test_production_qualification_rejects_oversized_market_day_declaration():
    with pytest.raises(ValueError, match="max_rows_per_market_day"):
        materialize_production_candidate_packet(
            candidate_id="candidate-r1",
            release_id="candidate-r1",
            corpus_out="corpus.parquet",
            manifest_out="manifest.json",
            validation_plan_out="plan.json",
            evaluation_out="evaluation.json",
            model_artifact="model.pkl",
            calibration_artifact="calibration.json",
            routing_artifact="routing.json",
            preselection_lock="preselection.json",
            replay_manifest="replay.json",
            max_rows_per_market_day=250_001,
        )
    with pytest.raises(ValueError, match="batch_rows"):
        materialize_production_candidate_packet(
            candidate_id="candidate-r1",
            release_id="candidate-r1",
            corpus_out="corpus.parquet",
            manifest_out="manifest.json",
            validation_plan_out="plan.json",
            evaluation_out="evaluation.json",
            model_artifact="model.pkl",
            calibration_artifact="calibration.json",
            routing_artifact="routing.json",
            preselection_lock="preselection.json",
            replay_manifest="replay.json",
            batch_rows=65_537,
        )


def _raw_row(
    *,
    target_date="2026-06-01",
    market_id="toronto",
    snapshot="08:00",
    band="low",
    variant="weather-v1",
    release="release-1",
    probability=0.7,
    label=1,
    lane="weather_only",
    parity="pass",
    label_quality="complete",
    countable=True,
    source_quality="healthy",
    runtime="runtime-1",
):
    return {
        "target_date": target_date,
        "market_id": market_id,
        "snapshot_id": snapshot,
        "range_label": band,
        "variant_id": variant,
        "release_id": release,
        "feature_available_at_utc": f"{target_date}T11:55:00+00:00",
        "captured_at_utc": f"{target_date}T12:00:00+00:00",
        "label_quality": label_quality,
        "countable": countable,
        "claim_lane": lane,
        "replay_serve_parity": parity,
        "source_quality": source_quality,
        "prediction_probability": probability,
        "label": label,
        "runtime_identity": runtime,
    }


def _canonical(**kwargs):
    return canonicalize_raw_row(_raw_row(**kwargs), provenance=PROVENANCE)


def _distribution_rows(
    *,
    target_date,
    market_id,
    lane,
    variant,
    release,
    winner_probability,
    parity=None,
    runtime="runtime-1",
):
    parity = parity or ("pass" if lane in {"weather_only", "market_informed"} else "not_applicable")
    return [
        _canonical(
            target_date=target_date,
            market_id=market_id,
            band="low",
            lane=lane,
            variant=variant,
            release=release,
            probability=winner_probability,
            label=1,
            parity=parity,
            runtime=runtime,
        ),
        _canonical(
            target_date=target_date,
            market_id=market_id,
            band="high",
            lane=lane,
            variant=variant,
            release=release,
            probability=1.0 - winner_probability,
            label=0,
            parity=parity,
            runtime=runtime,
        ),
    ]


def test_contract_persists_exact_key_payload_hash_and_provenance():
    canonical = _canonical(lane="weather_only_core_model")

    assert canonical["schema_version"] == CONTRACT_SCHEMA_VERSION
    assert point_in_time_key(canonical) == (
        "2026-06-01",
        "toronto",
        "08:00",
        "low",
        "weather-v1",
        "release-1",
    )
    assert canonical["claim_lane"] == "weather_only"
    assert json.loads(canonical["source_payload_json"])["release_id"] == "release-1"
    assert json.loads(canonical["source_provenance_json"])["source_mode"] == "validated_parquet"
    assert validate_canonical_row(canonical) == canonical


def test_contract_rejects_future_features_and_payload_tampering():
    raw = _raw_row()
    raw["feature_available_at_utc"] = "2026-06-01T12:01:00+00:00"
    with pytest.raises(ContractViolation, match="availability") as future:
        canonicalize_raw_row(raw, provenance=PROVENANCE)
    assert future.value.code == "feature_available_after_prediction"

    canonical = _canonical()
    payload = json.loads(canonical["source_payload_json"])
    payload["release_id"] = "tampered-release"
    canonical["source_payload_json"] = canonical_json(payload)
    with pytest.raises(ContractViolation) as tampered:
        validate_canonical_row(canonical)
    assert tampered.value.code == "source_payload_hash_mismatch"

    canonical = _canonical()
    canonical["source_payload_json"] += " "
    canonical["source_payload_sha256"] = sha256_text(canonical["source_payload_json"])
    with pytest.raises(ContractViolation) as noncanonical:
        validate_canonical_row(canonical)
    assert noncanonical.value.code == "noncanonical_source_payload"


def test_materializer_reads_one_text_market_day_and_keeps_raw_immutable(tmp_path):
    snapshots_root = tmp_path / "snapshots"
    folder = snapshots_root / "highest-temperature-in-toronto-on-june-1-2026"
    folder.mkdir(parents=True)
    source = folder / "snapshots_long.csv"
    rows = [
        _raw_row(band="low", probability=0.7, label=1),
        _raw_row(band="high", probability=0.3, label=0),
    ]
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    before = source.read_bytes()
    parquet_out = tmp_path / "derived" / "rows.parquet"
    manifest_out = tmp_path / "derived" / "manifest.json"

    manifest = materialize_point_in_time_table(
        [folder],
        parquet_out=parquet_out,
        manifest_out=manifest_out,
        snapshots_root=snapshots_root,
        archive_root=tmp_path / "archive",
        prefer_archive=False,
        max_market_days=1,
        max_rows_per_market_day=10,
        generated_at_utc="2026-06-20T00:00:00+00:00",
    )

    assert manifest["status"] == "PASS"
    assert manifest["schema_version"] == MATERIALIZER_SCHEMA_VERSION
    assert manifest["generated_at_utc"] == "2026-06-20T00:00:00+00:00"
    assert "generated_at" not in manifest
    unhashed = dict(manifest)
    manifest_hash = unhashed.pop("manifest_hash")
    assert manifest_hash == sha256_text(canonical_json(unhashed))
    assert manifest["raw_evidence_mutated"] is False
    assert manifest["counts"]["source_modes"] == {"text_tape": 1}
    assert manifest["streaming_bounds"]["raw_market_days_retained_at_once"] == 1
    assert source.read_bytes() == before
    assert pq.ParquetFile(parquet_out).metadata.num_rows == 2
    assert verify_materialization_manifest(parquet_out, manifest_out) == manifest
    with pytest.raises(FrozenContractViolation) as unmanifested:
        verify_frozen_materialization_manifest(
            parquet_out,
            manifest_out,
            require_manifest_backed_inputs=True,
        )
    assert unmanifested.value.code == "materialization_inputs_not_proof_grade"
    materialized = list(iter_point_in_time_parquet(parquet_out, batch_rows=1))
    assert [row["band"] for row in materialized] == ["high", "low"]
    provenance = json.loads(materialized[0]["source_provenance_json"])
    assert provenance["source_mode"] == "text_tape"
    assert provenance["source_file_hash"]


def test_materializer_blocks_missing_release_lineage_without_guessing(tmp_path):
    snapshots_root = tmp_path / "snapshots"
    folder = snapshots_root / "highest-temperature-in-toronto-on-june-1-2026"
    folder.mkdir(parents=True)
    raw = _raw_row()
    raw.pop("release_id")
    source = folder / "snapshots_long.csv"
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw))
        writer.writeheader()
        writer.writerow(raw)

    manifest = materialize_point_in_time_table(
        [folder],
        parquet_out=tmp_path / "rows.parquet",
        manifest_out=tmp_path / "manifest.json",
        snapshots_root=snapshots_root,
        archive_root=tmp_path / "archive",
        prefer_archive=False,
    )

    assert manifest["status"] == "BLOCK"
    assert manifest["counts"]["accepted_rows"] == 0
    assert manifest["counts"]["exclusions_by_reason"] == {"missing_release_id": 1}
    with pytest.raises(ContractViolation) as blocked:
        verify_materialization_manifest(tmp_path / "rows.parquet", tmp_path / "manifest.json")
    assert blocked.value.code == "materialization_not_pass"


def test_rolling_origin_folds_group_dates_and_apply_calendar_embargo():
    start = date(2026, 6, 1)
    dates = [(start + timedelta(days=offset)).isoformat() for offset in range(18)]

    folds = build_rolling_origin_folds(
        dates,
        min_train_dates=5,
        validation_dates=2,
        embargo_days=3,
    )

    first = folds[0]
    assert first.train_dates == tuple(dates[:5])
    assert first.embargo_dates == tuple(dates[5:8])
    assert first.validation_dates == tuple(dates[8:10])
    assert set(first.train_dates).isdisjoint(first.validation_dates)
    assert set(first.embargo_dates).isdisjoint(first.train_dates + first.validation_dates)
    first_validation = date.fromisoformat(first.validation_dates[0])
    assert all(
        (first_validation - date.fromisoformat(item)).days > 3
        for item in first.train_dates
    )

    nested = build_nested_rolling_origin_folds(
        dates,
        outer_min_train_dates=10,
        inner_min_train_dates=3,
        embargo_days=3,
    )
    assert nested
    for item in nested:
        outer_train = set(item.outer.train_dates)
        for inner in item.inner:
            assert set(inner.train_dates + inner.embargo_dates + inner.validation_dates) <= outer_train

    plan = validation_plan_payload(
        dates,
        outer_min_train_dates=10,
        inner_min_train_dates=3,
        embargo_days=3,
        generated_at_utc="2026-06-20T00:00:00+00:00",
    )
    assert plan["schema_version"] == VALIDATION_PLAN_SCHEMA_VERSION
    assert plan["generated_at_utc"] == "2026-06-20T00:00:00+00:00"
    assert "generated_at" not in plan
    assert plan["status"] == "PASS"


def test_embargo_must_be_predeclared_between_three_and_seven_days():
    dates = [f"2026-06-{day:02d}" for day in range(1, 12)]
    with pytest.raises(ValueError, match="between 3 and 7"):
        build_rolling_origin_folds(dates, min_train_dates=3, embargo_days=2)
    with pytest.raises(ValueError, match="between 3 and 7"):
        build_rolling_origin_folds(dates, min_train_dates=3, embargo_days=8)


def test_pipeline_fits_fresh_hooks_on_training_dates_only():
    fold = RollingOriginFold(
        fold_id="outer-1",
        train_dates=("2026-06-01", "2026-06-02"),
        embargo_dates=("2026-06-03", "2026-06-04", "2026-06-05"),
        validation_dates=("2026-06-06",),
        embargo_days=3,
    )
    rows_by_date = {
        target: [{"target_date": target, "stages": []}]
        for target in fold.train_dates + fold.embargo_dates + fold.validation_dates
    }
    fit_receipts = []
    instance_ids = []

    class SpyHook:
        def __init__(self, name):
            self.name = name
            instance_ids.append(id(self))

        def fit(self, rows):
            fit_receipts.append((self.name, {row["target_date"] for row in rows}))

        def transform(self, rows):
            return [
                {**row, "stages": [*row["stages"], self.name]}
                for row in rows
            ]

    result = run_training_only_pipeline(
        fold,
        rows_by_date,
        [
            ("scaling_imputation", lambda: SpyHook("scaling_imputation")),
            ("calibration", lambda: SpyHook("calibration")),
            ("regime_router", lambda: SpyHook("regime_router")),
        ],
    )

    assert len(set(instance_ids)) == 3
    assert all(dates == set(fold.train_dates) for _, dates in fit_receipts)
    assert all("2026-06-06" not in dates for _, dates in fit_receipts)
    assert [row["target_date"] for row in result.validation_rows] == ["2026-06-06"]
    assert result.validation_rows[0]["stages"] == [
        "scaling_imputation",
        "calibration",
        "regime_router",
    ]
    assert all(
        receipt["stage_input_sha256"]
        == sha256_text(canonical_json(receipt["stage_input_payload"]))
        and receipt["stage_output_sha256"]
        == sha256_text(canonical_json(receipt["stage_output_payload"]))
        for receipt in result.fit_receipts
    )
    for prior, current in zip(result.fit_receipts, result.fit_receipts[1:]):
        assert (
            current["stage_input_payload"]["upstream_stage_output_sha256"]
            == prior["stage_output_sha256"]
        )
        assert current["fit_input_sha256"] == prior["fit_output_sha256"]
        assert (
            current["validation_input_sha256"]
            == prior["validation_output_sha256"]
        )


def test_research_validation_plan_remains_valid_without_production_output_receipts():
    dates = [f"2026-06-{day:02d}" for day in range(1, 19)]
    plan = validation_plan_payload(
        dates,
        outer_min_train_dates=10,
        inner_min_train_dates=3,
        embargo_days=3,
    )

    assert plan["fit_receipt_contract"]["payload_binding_required"] is False
    assert verify_validation_plan_payload(plan) == plan


def test_pipeline_rejects_rows_put_in_the_wrong_fleet_date_bucket():
    fold = RollingOriginFold(
        fold_id="outer-1",
        train_dates=("2026-06-01",),
        embargo_dates=("2026-06-02", "2026-06-03", "2026-06-04"),
        validation_dates=("2026-06-05",),
        embargo_days=3,
    )
    rows_by_date = {
        "2026-06-01": [{"target_date": "2026-06-05"}],
        "2026-06-05": [{"target_date": "2026-06-05"}],
    }

    with pytest.raises(ContractViolation) as mismatch:
        run_training_only_pipeline(fold, rows_by_date, [])
    assert mismatch.value.code == "fleet_date_bucket_mismatch"


def test_streaming_evaluator_isolates_lanes_and_weights_market_days_and_dates():
    rows = []
    market_days = [
        ("2026-06-01", "austin", 0.9),
        ("2026-06-01", "toronto", 0.5),
        ("2026-06-02", "toronto", 0.8),
    ]
    for target_date, market_id, probability in market_days:
        rows.extend(
            _distribution_rows(
                target_date=target_date,
                market_id=market_id,
                lane="weather_only",
                variant="weather-v1",
                release="release-weather",
                winner_probability=probability,
            )
        )
        rows.extend(
            _distribution_rows(
                target_date=target_date,
                market_id=market_id,
                lane="market_benchmark",
                variant="market-tape",
                release="market-release",
                winner_probability=0.6,
            )
        )
    rows.sort(key=point_in_time_key)

    payload = evaluate_point_in_time_rows(
        rows,
        locked_dates=["2026-06-01", "2026-06-02"],
        bootstrap_iterations=100,
        bootstrap_seed=7,
        generated_at_utc="2026-06-03T00:00:00+00:00",
    )

    assert payload["status"] == "PASS"
    assert payload["generated_at_utc"] == "2026-06-03T00:00:00+00:00"
    assert "generated_at" not in payload
    assert payload["lane_isolation"] == {
        "status": "PASS",
        "lanes": list(CLAIM_LANES),
        "cross_lane_pooling": False,
    }
    assert len(payload["lanes"]["weather_only"]) == 1
    assert len(payload["lanes"]["market_benchmark"]) == 1
    assert payload["lanes"]["market_informed"] == []
    assert payload["lanes"]["trading"] == []
    weather = payload["lanes"]["weather_only"][0]
    market = payload["lanes"]["market_benchmark"][0]
    assert weather["release_id"] == "release-weather"
    assert market["release_id"] == "market-release"
    equal_market_day = weather["metrics"]["categorical_brier"]["equal_market_day"]
    equal_fleet_date = weather["metrics"]["categorical_brier"]["equal_fleet_date"]
    assert equal_market_day["market_days"] == 3
    assert equal_market_day["fleet_dates"] == 2
    assert equal_market_day["point_estimate"] != equal_fleet_date["point_estimate"]
    assert payload["counts"]["market_days"] == 3
    assert payload["counts"]["fleet_dates"] == 2
    assert payload["streaming_memory_contract"]["active_market_days"] == 1
    assert payload["runtime_identities"] == ["runtime-1"]


def _valid_streaming_evaluation_for_verification():
    target_dates = ["2026-06-01", "2026-06-02"]
    rows = []
    for target_date in target_dates:
        rows.extend(
            _distribution_rows(
                target_date=target_date,
                market_id="toronto",
                lane="weather_only",
                variant="weather-v1",
                release="release-weather",
                winner_probability=0.8,
            )
        )
    lock = build_window_lock(
        target_dates,
        input_sha256="a" * 64,
        window_days=2,
        generated_at_utc="2026-06-03T00:00:00+00:00",
    )
    return evaluate_point_in_time_rows(
        sorted(rows, key=point_in_time_key),
        locked_dates=target_dates,
        window_lock=lock,
        bootstrap_iterations=20,
        generated_at_utc="2026-06-03T00:00:00+00:00",
        evaluation_started_at_utc="2026-06-03T00:00:00+00:00",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("point_estimate", None),
        ("lower", float("-inf")),
        ("upper", "not-a-number"),
    ],
)
def test_streaming_verifier_rejects_nonfinite_or_nonnumeric_interval_values(
    field,
    value,
):
    payload = _valid_streaming_evaluation_for_verification()
    interval = payload["lanes"]["weather_only"][0]["metrics"][
        "categorical_brier"
    ]["equal_market_day"]
    interval[field] = value
    payload.pop("evaluation_hash")
    payload["evaluation_hash"] = sha256_text(canonical_json(payload))

    with pytest.raises(
        ContractViolation,
        match="point_estimate/lower/upper must be finite numbers",
    ):
        verify_streaming_evaluation_payload(payload)


def test_streaming_verifier_rejects_interval_bounds_excluding_point_estimate():
    payload = _valid_streaming_evaluation_for_verification()
    interval = payload["lanes"]["weather_only"][0]["metrics"][
        "categorical_brier"
    ]["equal_market_day"]
    interval["lower"] = interval["point_estimate"] + 1.0
    payload.pop("evaluation_hash")
    payload["evaluation_hash"] = sha256_text(canonical_json(payload))

    with pytest.raises(
        ContractViolation,
        match="interval bounds do not contain the point estimate",
    ):
        verify_streaming_evaluation_payload(payload)


def test_date_clustered_interval_is_deterministic_and_uses_fleet_date_clusters():
    rows = []
    for target_date, market_id, probability in [
        ("2026-06-01", "austin", 0.9),
        ("2026-06-01", "toronto", 0.6),
        ("2026-06-02", "toronto", 0.7),
    ]:
        payload = evaluate_point_in_time_rows(
            sorted(
                _distribution_rows(
                    target_date=target_date,
                    market_id=market_id,
                    lane="weather_only",
                    variant="v1",
                    release="r1",
                    winner_probability=probability,
                ),
                key=point_in_time_key,
            ),
            locked_dates=[target_date],
            bootstrap_iterations=10,
        )
        metric = payload["lanes"]["weather_only"][0]["market_day_rows"][0]
        from weather.reporting.validation.point_in_time_evaluation import MarketDayMetric

        rows.append(MarketDayMetric(**metric))

    first = date_clustered_bootstrap_interval(
        rows, metric="categorical_brier", iterations=200, seed=99
    )
    second = date_clustered_bootstrap_interval(
        rows, metric="categorical_brier", iterations=200, seed=99
    )
    assert first == second
    assert first["cluster_unit"] == "fleet_target_date"
    assert first["fleet_dates"] == 2
    assert first["market_days"] == 3


def test_partial_parity_failure_poisons_the_entire_cutoff():
    rows = _distribution_rows(
        target_date="2026-06-01",
        market_id="toronto",
        lane="weather_only",
        variant="weather-v1",
        release="release-1",
        winner_probability=0.8,
        parity="pass",
    )
    rows[0]["replay_serve_parity"] = "fail"
    rows.extend(
        _distribution_rows(
            target_date="2026-06-01",
            market_id="toronto",
            lane="market_benchmark",
            variant="market",
            release="market-release",
            winner_probability=0.6,
        )
    )
    quarantined = _raw_row(
        target_date="2026-06-01",
        market_id="toronto",
        snapshot="09:00",
        band="diagnostic",
        variant="quarantined-v1",
        release="release-q",
        probability=0.5,
        label=None,
        label_quality="quarantined",
        countable=False,
        lane="weather_only",
    )
    rows.append(canonicalize_raw_row(quarantined, provenance=PROVENANCE))
    rows.sort(key=point_in_time_key)

    payload = evaluate_point_in_time_rows(
        rows,
        locked_dates=["2026-06-01"],
        bootstrap_iterations=20,
    )

    assert payload["status"] == "BLOCK"
    assert payload["lanes"]["weather_only"] == []
    assert len(payload["lanes"]["market_benchmark"]) == 1
    assert payload["excluded_rows_by_reason"]["replay_serve_parity:fail"] == 1
    assert payload["excluded_cutoffs_by_reason"] == {
        "invalid_cutoff:replay_serve_parity:fail": 1
    }
    assert payload["excluded_rows_by_reason"]["non_countable_label:quarantined"] == 1
    assert payload["selected_labels"]["quarantined"] == 1


def test_duplicate_row_poisons_cutoff_even_when_other_metric_lanes_survive():
    weather = _distribution_rows(
        target_date="2026-06-01",
        market_id="toronto",
        lane="weather_only",
        variant="weather-v1",
        release="release-1",
        winner_probability=0.8,
    )
    rows = [*weather, dict(weather[0])]
    rows.extend(
        _distribution_rows(
            target_date="2026-06-01",
            market_id="toronto",
            lane="market_benchmark",
            variant="market",
            release="market-release",
            winner_probability=0.6,
        )
    )
    rows.sort(key=point_in_time_key)

    payload = evaluate_point_in_time_rows(
        rows,
        locked_dates=["2026-06-01"],
        bootstrap_iterations=20,
    )

    assert payload["status"] == "BLOCK"
    assert payload["lanes"]["weather_only"] == []
    assert len(payload["lanes"]["market_benchmark"]) == 1
    assert payload["contract_errors"] == {"duplicate_point_in_time_key": 1}
    assert payload["excluded_cutoffs_by_reason"] == {
        "invalid_cutoff:contract:duplicate_point_in_time_key": 1
    }


def _single_band_source_quality_rows(row_count, *, stale_rows):
    rows = [
        _canonical(
            snapshot=f"cutoff-{index:03d}",
            band="only",
            probability=1.0,
            label=1,
            source_quality="stale" if index < stale_rows else "healthy",
        )
        for index in range(row_count)
    ]
    return sorted(rows, key=point_in_time_key)


def test_source_quality_target_is_strictly_below_five_percent():
    at_boundary = evaluate_point_in_time_rows(
        _single_band_source_quality_rows(20, stale_rows=1),
        locked_dates=["2026-06-01"],
        bootstrap_iterations=20,
    )
    below_boundary = evaluate_point_in_time_rows(
        _single_band_source_quality_rows(21, stale_rows=1),
        locked_dates=["2026-06-01"],
        bootstrap_iterations=20,
    )

    assert at_boundary["source_quality"]["stale_or_failed_rate"] == 0.05
    assert at_boundary["source_quality"]["target_status"] == "BLOCK"
    assert at_boundary["status"] == "BLOCK"
    assert below_boundary["source_quality"]["stale_or_failed_rate"] < 0.05
    assert below_boundary["source_quality"]["target_status"] == "PASS"
    assert below_boundary["status"] == "PASS"


def test_window_lock_is_calendar_based_and_fixed_before_scoring():
    lock = build_window_lock(
        ["2026-06-01", "2026-06-03", "2026-06-04"],
        input_sha256="abc",
        window_days=4,
        window_end="2026-06-04",
        generated_at_utc="2026-06-05T00:00:00+00:00",
    )

    assert lock["status"] == "BLOCK"
    assert lock["generated_at_utc"] == "2026-06-05T00:00:00+00:00"
    assert "generated_at" not in lock
    assert lock["window_start"] == "2026-06-01"
    assert lock["missing_calendar_dates"] == ["2026-06-02"]
    assert lock["candidate_selection_permission"] == "forbidden"
    assert lock["locked_before_scoring"] is True

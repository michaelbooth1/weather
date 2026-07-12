from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timedelta, timezone

import pytest
import weather.reporting.scorecards.live_variant_settlement_scorecard as scorecard_module

from weather.reporting.scorecards.live_variant_settlement_scorecard import (
    LANE_MARKET,
    build_captured_input_replay_parity,
    build_scorecard,
    compare_replay_to_served,
    load_expected_variants,
    load_snapshot_partition_contracts,
    main,
    merge_scorecards,
    operational_status_payload,
    persist_captured_input_replay_parity,
    render_scorecard,
)


BANDS = (
    ("lte_69", "lte", 69, 69),
    ("eq_70", "eq", 70, 70),
    ("gte_71", "gte", 71, 71),
)


def tape_rows(
    *,
    variant_id="weather-v1",
    release_id="release-1",
    lane="weather_only_core_model",
    probabilities=(0.2, 0.6, 0.2),
    statuses=("predicted", "predicted", "predicted"),
    failure_reason="",
    snapshot_id="snapshot-1",
    market_probabilities=(0.1, 0.7, 0.2),
):
    rows = []
    for (band_key, kind, value, value_hi), probability, status, market_probability in zip(
        BANDS,
        probabilities,
        statuses,
        market_probabilities,
    ):
        rows.append(
            {
                "target_date": "2026-07-01",
                "market_id": "test-market",
                "snapshot_id": snapshot_id,
                "variant_id": variant_id,
                "variant_family": "fixture",
                "release_id": release_id,
                "claim_lane": lane,
                "band_key": band_key,
                "range_label": band_key,
                "bin_kind": kind,
                "bin_value_c": value,
                "bin_value_hi_c": value_hi,
                "prediction_status": status,
                "failure_reason": failure_reason if status != "predicted" else "",
                "variant_probability": probability if status == "predicted" else "",
                "serving_model_probability": (0.3, 0.4, 0.3)[len(rows)],
                "market_yes": market_probability,
            }
        )
    return rows


LABELS = {
    ("2026-07-01", "test-market"): {
        "settlement_bucket": 70,
        "promotion_countable": True,
    }
}


def snapshot_partition(
    snapshot_id="snapshot-1",
    *,
    target_date="2026-07-01",
    market_id="test-market",
):
    return {
        "target_date": target_date,
        "market_id": market_id,
        "evaluation_point_type": "snapshot",
        "evaluation_point_id": f"snapshot:{snapshot_id}",
        "source_path": f"{market_id}/snapshots_long.csv",
        "bands": [
            {
                "band_identity": f"{kind}:{value:g}:{value_hi:g}",
                "band_key": band_key,
                "range_label": band_key,
                "bin_kind": kind,
                "bin_value": value,
                "bin_value_hi": value_hi,
                "serving_probability": (0.3, 0.4, 0.3)[index],
                "market_probability": (0.1, 0.7, 0.2)[index],
                "outcome": int(kind == "eq" and value == 70),
                "outcome_source": "settlement_bucket",
                "settlement_countable": True,
            }
            for index, (band_key, kind, value, value_hi) in enumerate(BANDS)
        ],
    }


def test_scorecard_scores_complete_variant_release_partition():
    payload = build_scorecard(
        tape_rows(),
        labels=LABELS,
        generated_at_utc="2026-07-02T00:00:00+00:00",
    )

    assert payload["status"] == "PASS"
    assert payload["coverage"]["eligible_prediction_coverage"] == 1.0
    assert payload["coverage"]["market_day_count"] == 1
    assert payload["coverage"]["fleet_date_count"] == 1
    partition = payload["partitions"][0]
    assert partition["winner_count"] == 1
    assert partition["probability_sum"] == pytest.approx(1.0)
    assert partition["metrics"]["brier"] == pytest.approx(0.08)
    assert partition["metrics"]["top1_hit"] == 1
    assert partition["metrics"]["winner_rank"] == 1
    assert partition["metrics"]["rps"] == pytest.approx(0.04)
    assert partition["metrics"]["ece"] == pytest.approx(0.8 / 3)
    assert partition["metrics"]["ece_bin_count"] == 10
    assert partition["metrics"]["categorical_log_loss"] == pytest.approx(-math.log(0.6))
    assert partition["market_benchmark_metrics"]["brier"] == pytest.approx(0.14 / 3)
    market_lane = next(row for row in payload["lane_summaries"] if row["evidence_lane"] == LANE_MARKET)
    assert market_lane["valid_partition_count"] == 1


def test_numeric_zero_settlement_bucket_is_not_treated_as_missing():
    rows = tape_rows()
    zero_bands = (
        ("lte_neg_1", "lte", -1, -1),
        ("eq_0", "eq", 0, 0),
        ("gte_1", "gte", 1, 1),
    )
    for row, (band_key, kind, value, value_hi) in zip(rows, zero_bands):
        row.update(
            {
                "band_key": band_key,
                "range_label": band_key,
                "bin_kind": kind,
                "bin_value_c": value,
                "bin_value_hi_c": value_hi,
                "settlement_bucket": 0,
            }
        )

    payload = build_scorecard(rows)

    assert payload["status"] == "PASS"
    assert payload["partitions"][0]["winner_count"] == 1
    assert payload["partitions"][0]["metrics"]["winner_probability"] == pytest.approx(0.6)


def test_unresolved_settlement_partition_blocks_even_when_another_partition_is_valid():
    resolved = tape_rows(snapshot_id="resolved-snapshot")
    unresolved = tape_rows(snapshot_id="unresolved-snapshot")
    for row in unresolved:
        row["market_id"] = "unresolved-market"

    payload = build_scorecard([*resolved, *unresolved], labels=LABELS)

    assert payload["status"] == "BLOCK"
    assert payload["coverage"]["eligible_partition_count"] == 1
    assert payload["coverage"]["valid_prediction_partition_count"] == 1
    assert payload["coverage"]["unresolved_settlement_partition_count"] == 1
    assert any(blocker["code"] == "unresolved_settlement_partitions" for blocker in payload["blockers"])
    unresolved_partition = next(
        partition for partition in payload["partitions"] if partition["market_id"] == "unresolved-market"
    )
    assert unresolved_partition["status"] == "UNRESOLVED"
    assert unresolved_partition["unresolved_settlement"] is True


def test_scorecard_blocks_duplicates_missing_bands_and_bad_simplex():
    complete = tape_rows(variant_id="complete")
    incomplete = tape_rows(variant_id="incomplete", probabilities=(0.4, 0.4, 0.2))[:2]
    incomplete.append(dict(incomplete[0]))

    payload = build_scorecard([*complete, *incomplete], labels=LABELS)

    assert payload["status"] == "BLOCK"
    bad = next(row for row in payload["partitions"] if row["variant_id"] == "incomplete")
    assert "duplicate_band_rows" in bad["blocker_codes"]
    assert "missing_bands" in bad["blocker_codes"]
    assert "incomplete_probability_partition" in bad["blocker_codes"]
    assert bad["metrics"] is None
    assert payload["coverage"]["eligible_prediction_coverage"] == 0.5


def test_scorecard_reports_unsupported_runtime_skips_and_coverage():
    predicted = tape_rows(variant_id="predicted")
    skipped = tape_rows(
        variant_id="skipped",
        statuses=("skipped", "skipped", "skipped"),
        failure_reason="unsupported_runtime",
    )

    payload = build_scorecard([*predicted, *skipped], labels=LABELS)

    assert payload["status"] == "BLOCK"
    assert payload["coverage"]["eligible_prediction_coverage"] == 0.5
    assert payload["coverage"]["unsupported_runtime_skip_band_count"] == 3
    assert payload["coverage"]["skip_failure_reasons"] == {"unsupported_runtime": 3}
    skipped_partition = next(row for row in payload["partitions"] if row["variant_id"] == "skipped")
    assert skipped_partition["prediction_status_counts"] == {"skipped": 3}
    assert "missing_predictions" in skipped_partition["blocker_codes"]


def test_scorecard_rejects_nonfinite_out_of_range_and_nonunique_outcome():
    rows = tape_rows(probabilities=("nan", 1.2, -0.2))
    for row in rows:
        row["outcome"] = 0

    payload = build_scorecard(rows)

    assert payload["status"] == "BLOCK"
    codes = set(payload["partitions"][0]["blocker_codes"])
    assert "nonfinite_probabilities" in codes
    assert "out_of_range_probabilities" in codes
    assert "winner_count_mismatch" in codes
    assert payload["partitions"][0]["metrics"] is None


def test_expected_variant_contract_detects_variant_missing_from_tape_entirely():
    payload = build_scorecard(
        tape_rows(),
        labels=LABELS,
        expected_variants=["weather-v1", "missing-v2"],
    )

    assert payload["status"] == "BLOCK"
    assert payload["configuration"]["expected_variant_contract"] == "explicit_manifest"
    assert payload["coverage"]["missing_expected_variant_partition_count"] == 1
    assert payload["coverage"]["eligible_prediction_coverage"] == 0.5
    missing = next(row for row in payload["partitions"] if row["variant_id"] == "missing-v2")
    assert missing["skip_failure_reasons"] == {"missing_variant_partition": 3}


def test_sibling_contract_detects_band_missing_across_every_variant():
    first = tape_rows(variant_id="first")[:-1]
    second = tape_rows(variant_id="second")[:-1]

    payload = build_scorecard(
        [*first, *second],
        labels=LABELS,
        expected_variants=[
            {"variant_id": "first", "release_id": "release-1"},
            {"variant_id": "second", "release_id": "release-1"},
        ],
        expected_partitions=[snapshot_partition()],
        expected_partition_contract="sibling_snapshot_tape",
        bootstrap_iterations=20,
    )

    assert payload["status"] == "BLOCK"
    assert payload["configuration"]["expected_partition_contract"] == "sibling_snapshot_tape"
    assert payload["coverage"]["expected_snapshot_partition_count"] == 1
    assert payload["coverage"]["missing_expected_snapshot_partition_count"] == 0
    assert payload["coverage"]["missing_expected_snapshot_band_count"] == 1
    assert payload["coverage"]["missing_prediction_band_count"] == 2
    assert all("gte:71:71" in row["missing_bands"] for row in payload["partitions"])
    assert any(
        blocker["code"] == "missing_expected_snapshot_bands"
        for blocker in payload["blockers"]
    )


def test_sibling_contract_materializes_entire_missing_snapshot_variant_partition():
    payload = build_scorecard(
        tape_rows(snapshot_id="snapshot-1"),
        labels=LABELS,
        expected_variants=[
            {
                "variant_id": "weather-v1",
                "release_id": "release-1",
                "claim_lane": "weather_only",
            }
        ],
        expected_partitions=[
            snapshot_partition("snapshot-1"),
            snapshot_partition("snapshot-2"),
        ],
        expected_partition_contract="sibling_snapshot_tape",
        bootstrap_iterations=20,
    )

    assert payload["status"] == "BLOCK"
    assert payload["coverage"]["expected_snapshot_partition_count"] == 2
    assert payload["coverage"]["observed_expected_snapshot_partition_count"] == 1
    assert payload["coverage"]["missing_expected_snapshot_partition_count"] == 1
    assert payload["coverage"]["missing_expected_variant_partition_count"] == 1
    assert payload["inputs"]["synthetic_missing_snapshot_band_row_count"] == 3
    missing = next(
        row
        for row in payload["partitions"]
        if row["evaluation_point_id"] == "snapshot:snapshot-2"
    )
    assert missing["valid"] is False
    assert missing["skip_failure_reasons"] == {"missing_variant_partition": 3}
    assert any(
        blocker["code"] == "missing_expected_snapshot_partitions"
        for blocker in payload["blockers"]
    )


def test_variant_release_and_claim_lanes_never_collapse():
    rows = [
        *tape_rows(variant_id="weather", release_id="release-1"),
        *tape_rows(variant_id="weather", release_id="release-2", probabilities=(0.1, 0.8, 0.1)),
        *tape_rows(
            variant_id="overlay",
            release_id="release-1",
            lane="market_informed_overlay",
            probabilities=(0.15, 0.7, 0.15),
        ),
    ]
    payload = build_scorecard(rows, labels=LABELS)

    assert payload["status"] == "PASS"
    summaries = payload["variant_release_summaries"]
    assert len(summaries) == 3
    assert {(row["variant_id"], row["release_id"], row["evidence_lane"]) for row in summaries} == {
        ("weather", "release-1", "weather_only"),
        ("weather", "release-2", "weather_only"),
        ("overlay", "release-1", "market_informed"),
    }
    market_lane = next(row for row in payload["lane_summaries"] if row["evidence_lane"] == LANE_MARKET)
    # The market benchmark is deduplicated by base partition/release, not
    # repeated once for each candidate.
    assert market_lane["valid_partition_count"] == 2


def test_scorecard_blocks_conflicting_market_benchmark_rows():
    first = tape_rows(variant_id="first")
    second = tape_rows(variant_id="second", market_probabilities=(0.2, 0.6, 0.2))

    payload = build_scorecard([*first, *second], labels=LABELS)

    assert payload["status"] == "BLOCK"
    assert any(row["code"] == "comparator_probability_conflict" for row in payload["blockers"])


def test_market_overround_keeps_binary_benchmark_but_not_distribution_scores():
    payload = build_scorecard(
        tape_rows(market_probabilities=(0.2, 0.8, 0.2)),
        labels=LABELS,
    )

    assert payload["status"] == "PASS"
    metrics = payload["partitions"][0]["market_benchmark_metrics"]
    assert metrics["brier"] is not None
    assert metrics["log_loss"] is not None
    assert metrics["ece"] is not None
    assert metrics["simplex_valid"] is False
    assert metrics["categorical_log_loss"] is None
    assert metrics["rps"] is None


def test_scorecard_requires_explicit_release_id_by_default():
    rows = tape_rows()
    for row in rows:
        row.pop("release_id")
        row["runtime_git_commit"] = "abc123"
        row["runtime_source_fingerprint"] = "source-hash"
        row["serving_model_version"] = "served-v1"

    blocked = build_scorecard(rows, labels=LABELS)
    diagnostic = build_scorecard(rows, labels=LABELS, require_explicit_release_id=False)

    assert blocked["status"] == "BLOCK"
    assert "explicit_release_id_required" in blocked["partitions"][0]["blocker_codes"]
    assert diagnostic["status"] == "PASS"
    assert diagnostic["partitions"][0]["release_identity_sources"] == ["derived_runtime"]


def parity_rows(probabilities=(0.2, 0.6, 0.2), *, route_id="route-a", include_hash=True):
    rows = tape_rows(probabilities=probabilities)
    for row in rows:
        row.update(
            {
                "captured_input_hash": "captured-input-123" if include_hash else "",
                "live_runtime": "fixture-runtime",
                "route_id": route_id,
                "model_version": "model-v1",
                "artifact_hash": "artifact-123",
                "postprocess_config_hash": "postprocess-123",
                "release_manifest_sha256": "a" * 64,
            }
        )
    return rows


def test_captured_input_replay_parity_passes_within_tolerance():
    served = parity_rows()
    replay = parity_rows((0.2 + 1e-13, 0.6 - 1e-13, 0.2))

    payload = compare_replay_to_served(served, replay)

    assert payload["status"] == "PASS"
    assert payload["summary"]["compared_row_count"] == 3
    assert payload["summary"]["compared_probability_count"] == 3
    assert payload["summary"]["mismatch_count"] == 0
    assert payload["release_id"] == "release-1"
    assert payload["manifest_sha256"] == "a" * 64


def test_captured_input_replay_parity_fails_closed_on_identity_hash_and_probability():
    served = parity_rows(include_hash=False)
    replay = parity_rows((0.25, 0.55, 0.2), route_id="route-b", include_hash=False)

    payload = compare_replay_to_served(served, replay)

    assert payload["status"] == "BLOCK"
    codes = {row["code"] for row in payload["mismatches"]}
    assert "captured_input_hash_missing" in codes
    assert "serving_identity_mismatch" in codes
    assert "probability_mismatch" in codes


def test_captured_input_replay_parity_compares_skip_decisions_and_row_coverage():
    served = parity_rows()
    served[0]["prediction_status"] = "skipped"
    served[0]["failure_reason"] = "unsupported_runtime"
    served[0]["variant_probability"] = ""
    replay = parity_rows()
    replay.pop()

    payload = compare_replay_to_served(served, replay)

    codes = {row["code"] for row in payload["mismatches"]}
    assert payload["status"] == "BLOCK"
    assert "skip_decision_mismatch" in codes
    assert "skip_reason_mismatch" in codes
    assert "missing_replay_row" in codes


def _write_csv(path, rows):
    fields = sorted({field for row in rows for field in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_captured_input_parity_path_contract_blocks_missing_stale_and_wrong_release(tmp_path):
    served = tmp_path / "served.csv"
    replay = tmp_path / "replay.csv"
    _write_csv(served, parity_rows())
    _write_csv(replay, parity_rows())
    now = datetime.now(timezone.utc)

    passed = build_captured_input_replay_parity(
        served,
        replay,
        expected_release_id="release-1",
        expected_manifest_sha256="a" * 64,
        now=now,
    )
    missing = build_captured_input_replay_parity(
        served,
        tmp_path / "missing-replay.csv",
        expected_release_id="release-1",
        expected_manifest_sha256="a" * 64,
        now=now,
    )
    old = now - timedelta(hours=49)
    os.utime(replay, (old.timestamp(), old.timestamp()))
    stale = build_captured_input_replay_parity(
        served,
        replay,
        expected_release_id="release-1",
        expected_manifest_sha256="a" * 64,
        now=now,
    )
    mismatch = build_captured_input_replay_parity(
        served,
        replay,
        expected_release_id="other-release",
        expected_manifest_sha256="b" * 64,
        max_input_age_hours=72,
        now=now,
    )

    assert passed["status"] == "PASS"
    missing_codes = {row["code"] for row in missing["mismatches"]}
    assert missing["status"] == "BLOCK"
    assert "replay_parity_input_missing" in missing_codes
    assert "do not infer or fabricate" in next(
        row["next_action"]
        for row in missing["mismatches"]
        if row["code"] == "replay_parity_input_missing"
    )
    assert "replay_parity_input_stale" in {
        row["code"] for row in stale["mismatches"]
    }
    mismatch_codes = {row["code"] for row in mismatch["mismatches"]}
    assert "parity_release_identity_mismatch" in mismatch_codes
    assert "parity_manifest_identity_mismatch" in mismatch_codes


def test_parity_write_failure_replaces_or_removes_seeded_pass(tmp_path, monkeypatch):
    served = tmp_path / "served.csv"
    replay = tmp_path / "replay.csv"
    json_out = tmp_path / "parity.json"
    report_out = tmp_path / "parity.md"
    _write_csv(served, parity_rows())
    _write_csv(replay, parity_rows())
    json_out.write_text('{"status":"PASS"}\n', encoding="utf-8")

    def fail_write(*_args, **_kwargs):
        raise OSError("primary write failed")

    monkeypatch.setattr(scorecard_module, "write_outputs", fail_write)
    payload, proof_path, _report_path = persist_captured_input_replay_parity(
        served,
        replay,
        json_out=json_out,
        report_out=report_out,
        expected_release_id="release-1",
        expected_manifest_sha256="a" * 64,
    )
    persisted = json.loads(json_out.read_text(encoding="utf-8"))

    assert payload["status"] == "BLOCK"
    assert proof_path == json_out
    assert persisted["status"] == "BLOCK"
    assert any(row["code"] == "parity_output_persistence_failed" for row in persisted["mismatches"])

    json_out.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(scorecard_module, "write_json_atomic", fail_write)
    payload, proof_path, _report_path = persist_captured_input_replay_parity(
        served,
        replay,
        json_out=json_out,
        report_out=report_out,
        expected_release_id="release-1",
        expected_manifest_sha256="a" * 64,
    )
    assert payload["status"] == "BLOCK"
    assert proof_path is None
    assert not json_out.exists()


def test_cli_parity_runs_independently_and_writes_new_outputs(tmp_path):
    served = tmp_path / "served.csv"
    replay = tmp_path / "replay.csv"
    json_out = tmp_path / "parity.json"
    report_out = tmp_path / "parity.md"
    _write_csv(served, parity_rows())
    _write_csv(replay, parity_rows())

    exit_code = main(
        [
            "parity",
            "--served",
            str(served),
            "--replay",
            str(replay),
            "--json-out",
            str(json_out),
            "--report-out",
            str(report_out),
            "--fail-on-block",
        ]
    )

    assert exit_code == 0
    assert json.loads(json_out.read_text(encoding="utf-8"))["status"] == "PASS"
    assert "Captured-Input Replay / Served Parity" in report_out.read_text(encoding="utf-8")


def test_cli_score_joins_sibling_settlement_and_writes_outputs(tmp_path):
    event = tmp_path / "fixture-event"
    event.mkdir()
    tape = event / "variant_predictions_long.csv"
    _write_csv(tape, tape_rows())
    _write_csv(event / "snapshots_long.csv", tape_rows())
    (event / "settlement.json").write_text(
        json.dumps(
            {
                "target_date": "2026-07-01",
                "market_id": "test-market",
                "settlement_bucket": 70,
                "promotion_countable": True,
            }
        ),
        encoding="utf-8",
    )
    json_out = tmp_path / "scorecard.json"
    report_out = tmp_path / "scorecard.md"
    contracts, contract_blockers = load_snapshot_partition_contracts([tape])

    assert contract_blockers == []
    assert len(contracts) == 1
    assert contracts[0]["evaluation_point_id"] == "snapshot:snapshot-1"
    assert len(contracts[0]["bands"]) == 3

    exit_code = main(
        [
            "score",
            "--tape",
            str(tape),
            "--json-out",
            str(json_out),
            "--report-out",
            str(report_out),
            "--fail-on-block",
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["configuration"]["expected_partition_contract"] == "sibling_snapshot_tape"
    assert payload["coverage"]["expected_snapshot_partition_count"] == 1
    assert payload["coverage"]["valid_prediction_partition_count"] == 1
    assert "Live Variant Settlement Scorecard" in report_out.read_text(encoding="utf-8")


def test_snapshot_partition_loader_and_cli_fail_closed_without_sibling_tape(tmp_path):
    event = tmp_path / "fixture-event"
    event.mkdir()
    tape = event / "variant_predictions_long.csv"
    _write_csv(tape, tape_rows())
    (event / "settlement.json").write_text(
        json.dumps(
            {
                "target_date": "2026-07-01",
                "market_id": "test-market",
                "settlement_bucket": 70,
                "promotion_countable": True,
            }
        ),
        encoding="utf-8",
    )

    contracts, blockers = load_snapshot_partition_contracts([tape])
    assert contracts == []
    assert [row["code"] for row in blockers] == ["expected_snapshot_tape_missing"]

    json_out = tmp_path / "blocked.json"
    exit_code = main(
        [
            "score",
            "--tape",
            str(tape),
            "--bootstrap-iterations",
            "20",
            "--json-out",
            str(json_out),
            "--report-out",
            str(tmp_path / "blocked.md"),
            "--fail-on-block",
        ]
    )
    payload = json.loads(json_out.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert payload["status"] == "BLOCK"
    assert payload["configuration"]["expected_partition_contract"] == "sibling_snapshot_tape"
    assert payload["coverage"]["expected_snapshot_partition_count"] == 0
    assert any(row["code"] == "expected_snapshot_tape_missing" for row in payload["blockers"])


def test_expected_variant_manifest_filters_inactive_and_control_entries(tmp_path):
    manifest = tmp_path / "release.json"
    manifest.write_text(
        json.dumps(
            {
                "variants": [
                    {"variant_id": "weather", "lifecycle": "active", "track": "no_market"},
                    {"variant_id": "overlay", "lifecycle": "active", "track": "market_informed"},
                    {"variant_id": "retired", "lifecycle": "retired", "track": "no_market"},
                    {"variant_id": "control", "lifecycle": "active", "track": "no_market", "roles": ["control"]},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert load_expected_variants(manifest) == [
        {"variant_id": "overlay", "evidence_lane": "market_informed", "release_id": None},
        {"variant_id": "weather", "evidence_lane": "weather_only", "release_id": None},
    ]


def test_bounded_merge_combines_market_tapes_without_raw_rows():
    first = build_scorecard(tape_rows(snapshot_id="s1"), labels=LABELS, source_paths=["market-a.csv"])
    second_rows = tape_rows(snapshot_id="s2")
    for row in second_rows:
        row["market_id"] = "other-market"
    second = build_scorecard(
        second_rows,
        labels={("2026-07-01", "other-market"): LABELS[("2026-07-01", "test-market")]},
        source_paths=["market-b.csv"],
    )

    payload = merge_scorecards([first, second], target_date="2026-07-01")

    assert payload["status"] == "PASS"
    assert payload["inputs"]["source_path_count"] == 2
    assert payload["coverage"]["eligible_partition_count"] == 2
    assert payload["coverage"]["market_day_count"] == 2
    assert payload["coverage"]["fleet_date_count"] == 1
    assert payload["configuration"]["bounded_merge"] is True


def _market_day_child(target_date, market_id, snapshot_count, probabilities, source_path):
    rows = []
    for index in range(snapshot_count):
        snapshot_rows = tape_rows(
            snapshot_id=f"{market_id}-{target_date}-{index:03d}",
            probabilities=probabilities,
        )
        for row in snapshot_rows:
            row["target_date"] = target_date
            row["market_id"] = market_id
        rows.extend(snapshot_rows)
    return build_scorecard(
        rows,
        labels={
            (target_date, market_id): {
                "settlement_bucket": 70,
                "promotion_countable": True,
            }
        },
        source_paths=[source_path],
        bootstrap_iterations=50,
        bootstrap_seed=7,
    )


def test_headline_metrics_weight_market_days_and_cluster_whole_fleet_dates():
    children = [
        _market_day_child(
            "2026-07-01",
            "market-a",
            10,
            (0.45, 0.10, 0.45),
            "day1-market-a.csv",
        ),
        _market_day_child(
            "2026-07-01",
            "market-b",
            1,
            (0.05, 0.90, 0.05),
            "day1-market-b.csv",
        ),
        _market_day_child(
            "2026-07-02",
            "market-a",
            1,
            (0.05, 0.90, 0.05),
            "day2-market-a.csv",
        ),
    ]

    first = merge_scorecards(children)
    second = merge_scorecards(children)
    summary = first["variant_release_summaries"][0]
    views = summary["metric_views"]

    assert first["status"] == "PASS"
    assert first["configuration"]["aggregate_weighting"] == "equal_market_day"
    assert first["configuration"]["equal_partition_metrics_are_diagnostic_only"] is True
    assert views["headline_weighting"] == "equal_market_day"
    assert views["equal_market_day"]["market_day_count"] == 3
    assert views["equal_fleet_date"]["fleet_date_count"] == 2
    assert views["equal_partition_diagnostic"]["partition_count"] == 12
    assert summary["metrics"] == views["equal_market_day"]
    assert views["equal_market_day"]["brier"] != views["equal_partition_diagnostic"]["brier"]
    assert views["equal_market_day"]["brier"] != views["equal_fleet_date"]["brier"]
    interval = views["date_clustered_intervals"]
    assert interval["fleet_date_count"] == 2
    assert interval["market_day_count"] == 3
    assert interval["metrics"]["brier"]["point_estimate"] == pytest.approx(
        views["equal_market_day"]["brier"]
    )
    assert interval == second["variant_release_summaries"][0]["metric_views"]["date_clustered_intervals"]


def test_merge_scorecards_blocks_inconsistent_contracts_and_silent_child_failure():
    first = build_scorecard(
        tape_rows(snapshot_id="s1"),
        labels=LABELS,
        bootstrap_iterations=20,
    )
    inconsistent = json.loads(json.dumps(first))
    inconsistent["configuration"]["expected_partition_contract"] = "sibling_snapshot_tape"

    merged = merge_scorecards([first, inconsistent])

    assert merged["status"] == "BLOCK"
    assert any(
        row["code"] == "inconsistent_child_configuration"
        and row["field"] == "expected_partition_contract"
        for row in merged["blockers"]
    )
    assert merged["coverage"]["valid_prediction_partition_count"] == 0
    assert merged["variant_release_summaries"][0]["metrics"] is None

    silent = json.loads(json.dumps(first))
    silent["status"] = "BLOCK"
    silent["blockers"] = []
    silent["blocker_count"] = 0
    silent_merge = merge_scorecards([silent])
    assert silent_merge["status"] == "BLOCK"
    assert silent_merge["first_blocker"]["code"] == "child_scorecard_not_pass"


def test_operational_skipped_payload_is_canonical_and_reports_reason():
    payload = operational_status_payload(
        "SKIPPED",
        "no_live_variant_tape_for_target_date",
        target_date="2026-07-01",
    )

    assert payload["status"] == "SKIPPED"
    assert payload["blocker_count"] == 0
    assert payload["coverage"]["partition_count"] == 0
    assert "SKIPPED" in render_scorecard(payload)

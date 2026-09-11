"""Cheap numerical-control fixtures; no historical data, artifacts or fitting."""

import csv
import json
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from weather.backtesting import replay_backtest as replay
from weather.backtesting.replay_fidelity import (
    FIDELITY_FAITHFUL_L1,
    distribution_fidelity,
    fidelity_summary,
    fidelity_support,
    incumbent_control_validation,
)
from weather.market.worker_release_binding import RECORDED_DISTRIBUTION_MASS_TOLERANCE

SLUG = "highest-temperature-in-toronto-on-june-3-2026"


def _row(snapshot_id="snap1", l1=0.0, **changes):
    return {
        "event_slug": SLUG,
        "snapshot_id": snapshot_id,
        "recorded_version": "incumbent",
        "replayed_version": "incumbent",
        "recorded_identity_hash": "incumbent-identity",
        "replayed_identity_hash": "incumbent-identity",
        "reconstructed": False,
        "l1": l1,
        **changes,
    }


def _manifest(snapshot_ids=("snap1",)):
    entry = {
        "event_slug": SLUG,
        "snapshot_ids": list(snapshot_ids),
        "settlement_bucket": 25,
        "settlement_source": "fixture",
        "replay_record_hashes": {value: "1" * 64 for value in snapshot_ids},
        "tape_row_hashes": {value: "2" * 64 for value in snapshot_ids},
    }
    entries = [entry]
    return {"entries": entries, "corpus_hash": replay.corpus_hash(entries)}


def _results(rows, manifest=None):
    manifest = _manifest() if manifest is None else manifest
    return {
        "fidelity_rows": rows,
        "fidelity": fidelity_summary(rows),
        "fidelity_support": fidelity_support(rows, manifest),
        "corpus_warnings": [],
        "promotion_corpus": {"corpus_hash": manifest.get("corpus_hash")},
        "incumbent_control": {"requested": False, "status": "NOT_REQUESTED"},
        "snaps_scored": len(rows),
        "total_rows": len(rows),
        "days": [],
        "all_rows": [],
        "aggregate": {
            "replayed_brier": 0.1, "recorded_brier": 0.1,
            "market_brier": 0.12, "code_effect": 0.0,
        },
    }


def test_concentrated_error_fails_even_when_mean_passes_old_canary():
    rows = [_row(f"snap{index}") for index in range(20)] + [_row("bad", 0.2)]
    results = _results(rows, _manifest([row["snapshot_id"] for row in rows]))
    fid = results["fidelity"]
    assert fid["same_identity_mean_l1"] < FIDELITY_FAITHFUL_L1
    assert fid["same_identity_max_l1"] == 0.2
    assert fid["same_identity_above_tolerance_n"] == 1
    assert not fid["same_identity_faithful"]
    assert not fid["same_version_faithful"]
    assert incumbent_control_validation(results)["status"] == "FAIL"


@pytest.mark.parametrize("l1", [-0.1, float("nan"), float("inf"), -float("inf"), None, True, "invalid"])
def test_invalid_l1_never_becomes_a_faithful_control(l1):
    results = _results([_row(l1=l1)])
    assert results["fidelity"]["same_identity_invalid_n"] == 1
    assert results["fidelity"]["same_identity_max_l1"] is None
    assert incumbent_control_validation(results)["status"] == "FAIL"


@pytest.mark.parametrize("l1", [0.0, FIDELITY_FAITHFUL_L1])
def test_faithful_incumbent_and_existing_tolerance_boundary_pass(l1):
    results = _results([_row(l1=l1)])
    assert incumbent_control_validation(results)["status"] == "PASS"


def test_zero_control_population_fails():
    results = _results([], _manifest(()))
    control = incumbent_control_validation(results)
    assert control["status"] == "FAIL"
    assert "the pinned control population is empty" in control["reasons"]


@pytest.mark.parametrize("changes, cohort", [
    ({"recorded_identity_hash": None}, "legacy_same_version"),
    ({"replayed_identity_hash": "candidate-identity"}, "changed_version"),
    ({"reconstructed": True}, "reconstructed"),
])
def test_excluded_identity_cohorts_cannot_supply_an_incumbent_control(changes, cohort):
    results = _results([_row(**changes)])
    assert results["fidelity"][f"{cohort}_n"] == 1
    assert results["fidelity"]["same_identity_n"] == 0
    assert incumbent_control_validation(results)["status"] == "FAIL"


@pytest.mark.parametrize("mutation, field", [
    ("missing", "missing_snapshot_count"),
    ("unexpected", "unexpected_snapshot_count"),
    ("duplicate_observed", "duplicate_observed_snapshot_count"),
    ("duplicate_expected", "duplicate_expected_snapshot_count"),
    ("duplicate_raw", "duplicate_replay_record_count"),
    ("missing_hash", "manifest_pin_problem_count"),
    ("invalid_hash", "manifest_pin_problem_count"),
])
def test_pinned_population_and_complete_hash_coverage_are_required(mutation, field):
    rows = [_row()]
    manifest = _manifest()
    duplicate_raw = 0
    if mutation == "missing":
        rows = []
    elif mutation == "unexpected":
        rows.append(_row("outside"))
    elif mutation == "duplicate_observed":
        rows.append(_row())
    elif mutation == "duplicate_expected":
        manifest["entries"][0]["snapshot_ids"].append("snap1")
    elif mutation == "duplicate_raw":
        duplicate_raw = 1
    elif mutation == "missing_hash":
        manifest["entries"][0]["replay_record_hashes"] = {}
    elif mutation == "invalid_hash":
        manifest["entries"][0]["tape_row_hashes"]["snap1"] = "not-a-sha256"
    results = _results(rows, manifest)
    results["fidelity_support"] = fidelity_support(rows, manifest, duplicate_raw)
    assert results["fidelity_support"][field] == 1
    assert incumbent_control_validation(results)["status"] == "FAIL"


@pytest.mark.parametrize("field, value", [
    ("settlement_bucket", None), ("settlement_bucket", True),
    ("settlement_bucket", 25.5), ("settlement_bucket", float("nan")),
    ("settlement_bucket", "25.0"), ("settlement_bucket", "2.5e1"),
    ("settlement_bucket", float("inf")), ("settlement_source", ""),
    ("settlement_source", "   "), ("settlement_source", None),
])
def test_unusable_settlement_pins_block_strict_control(field, value):
    manifest = _manifest()
    manifest["entries"][0][field] = value
    results = _results([_row()], manifest)
    assert results["fidelity_support"]["manifest_pin_problem_count"] == 1
    assert incumbent_control_validation(results)["status"] == "FAIL"


def test_shared_snapshot_id_does_not_hide_a_missing_market_day():
    manifest = _manifest()
    other = deepcopy(manifest["entries"][0])
    other["event_slug"] = "highest-temperature-in-nyc-on-june-3-2026"
    manifest["entries"].append(other)
    results = _results([_row()], manifest)
    assert results["fidelity_support"]["missing_snapshot_count"] == 1
    assert incumbent_control_validation(results)["status"] == "FAIL"


def test_missing_pin_and_corpus_warnings_block_control():
    results = _results([_row()], {})
    assert incumbent_control_validation(results)["status"] == "FAIL"
    results = _results([_row()])
    results["corpus_warnings"] = ["captured inputs changed"]
    assert incumbent_control_validation(results)["status"] == "FAIL"


@pytest.mark.parametrize("distribution", [
    {}, None, {25: 0.0}, {25: -1.0}, {25: float("nan")},
    {25: float("inf")}, {25: 1.01}, {25: True},
    {25.5: 1.0}, {float("inf"): 1.0}, {True: 1.0},
    {25: 0.5, "25": 0.5},
    {"kind": "continuous_density_f", "density_f": {}},
    {"kind": "continuous_density_f", "density_f": {25.1: -1.0}},
])
def test_invalid_distributions_cannot_create_a_false_zero(distribution):
    l1, error = distribution_fidelity(distribution, distribution)
    assert l1 is None
    assert error


def test_distribution_mass_uses_existing_captured_record_tolerance():
    tolerance = RECORDED_DISTRIBUTION_MASS_TOLERANCE
    l1, error = distribution_fidelity({25: 1 - tolerance / 2}, {25: 1})
    assert error is None
    assert l1 == pytest.approx(tolerance / 2)
    l1, error = distribution_fidelity({25: 1 - tolerance * 2}, {25: 1})
    assert l1 is None
    assert "probability mass" in error


def test_continuous_coordinates_are_compared_without_integer_collapse():
    left = {"kind": "continuous_density_f", "density_f": {32.1: 1.0}}
    right = {"kind": "continuous_density_f", "density_f": {"32.2": 1.0}}
    assert distribution_fidelity(left, right) == (2.0, None)
    assert distribution_fidelity(left, json.loads(json.dumps(left))) == (0.0, None)
    assert distribution_fidelity(left, {32: 1.0})[1] == "distribution representations differ"


def test_diagnostic_gate_retains_failed_fidelity_and_accepts_changed_candidates(tmp_path):
    baseline = tmp_path / "baseline.json"
    replay.save_baseline(baseline, _results([_row()]))
    unfaithful = _results([_row(l1=0.5)])
    passed, message = replay.gate(baseline, unfaithful, 0.003)
    assert passed
    assert "DIAGNOSTIC PASS" in message
    assert "FIDELITY WARNING" in message
    candidate = _results([_row(replayed_identity_hash="candidate")])
    passed, message = replay.gate(baseline, candidate, 0.003)
    assert passed
    assert "DIAGNOSTIC PASS" in message
    assert "FIDELITY UNAVAILABLE" in message


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -0.1])
def test_diagnostic_gate_refuses_invalid_scores_or_tolerance(tmp_path, value):
    baseline = tmp_path / "baseline.json"
    replay.save_baseline(baseline, _results([_row()]))
    current = _results([_row()])
    current["aggregate"]["replayed_brier"] = value
    assert not replay.gate(baseline, current, 0.003)[0]
    assert not replay.gate(baseline, _results([_row()]), value)[0]


def _mock_cli(monkeypatch, results, manifest=None):
    manifest = _manifest() if manifest is None else manifest
    monkeypatch.setattr(replay, "load_manifest", lambda path: manifest)
    monkeypatch.setattr(replay, "folders_from_manifest", lambda *args: [SLUG])
    monkeypatch.setattr(replay, "long_job_guard", lambda *args, **kwargs: nullcontext({}))
    runner = Mock(return_value=results)
    monkeypatch.setattr(replay, "run_replay_backtest", runner)
    return runner


@pytest.mark.parametrize("rows", [[], [_row(l1=0.5)]])
def test_requested_cli_control_fails_before_baseline_overwrite(monkeypatch, tmp_path, rows):
    results = _results(rows)
    results["incumbent_control"] = incumbent_control_validation(results)
    runner = _mock_cli(monkeypatch, results)
    baseline = tmp_path / "baseline.json"
    baseline.write_text("existing evidence", encoding="utf-8")
    monkeypatch.setattr("sys.argv", [
        "replay_backtest", "--corpus", "fixture.json", "--require-incumbent-control",
        "--save-baseline", str(baseline), "--out", str(tmp_path / "report.md"),
    ])
    with pytest.raises(SystemExit) as stopped:
        replay.main()
    assert stopped.value.code == 1
    assert baseline.read_text(encoding="utf-8") == "existing evidence"
    assert runner.call_args.kwargs["require_incumbent_control"] is True
    with pytest.raises(ValueError, match="refusing baseline publication"):
        replay.save_baseline(baseline, results)


def test_empty_pinned_corpus_does_not_fall_back_to_discovery(monkeypatch):
    _mock_cli(monkeypatch, _results([]), _manifest(()))
    monkeypatch.setattr(replay, "folders_from_manifest", lambda *args: [])
    monkeypatch.setattr("sys.argv", [
        "replay_backtest", "--corpus", "empty.json", "--require-incumbent-control",
    ])
    with pytest.raises(SystemExit, match="no pinned snapshot tapes"):
        replay.main()


@pytest.mark.parametrize("arguments", [
    ["--require-incumbent-control"],
    ["--corpus", "fixture.json", "--require-incumbent-control", "--settle", "2026-06-03=25"],
    ["--corpus", "fixture.json", "--require-incumbent-control", "--include-reconstructed"],
    ["--save-baseline", "baseline.json", "--gate", "baseline.json"],
])
def test_invalid_control_or_baseline_arguments_fail_before_replay(monkeypatch, arguments):
    runner = _mock_cli(monkeypatch, _results([]))
    monkeypatch.setattr("sys.argv", ["replay_backtest", *arguments])
    with pytest.raises(SystemExit) as stopped:
        replay.main()
    assert stopped.value.code == 2
    runner.assert_not_called()


def test_faithful_requested_cli_control_can_save_diagnostic_baseline(monkeypatch, tmp_path):
    results = _results([_row()])
    results["incumbent_control"] = incumbent_control_validation(results)
    _mock_cli(monkeypatch, results)
    baseline = tmp_path / "baseline.json"
    monkeypatch.setattr("sys.argv", [
        "replay_backtest", "--corpus", "fixture.json", "--require-incumbent-control",
        "--save-baseline", str(baseline), "--out", str(tmp_path / "report.md"),
    ])
    replay.main()
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert payload["comparison_claim"] == "diagnostic_aggregate_brier"
    assert payload["incumbent_control"]["status"] == "PASS"


def test_changed_candidate_cli_remains_diagnostic_by_default(monkeypatch, tmp_path, capsys):
    results = _results([_row(replayed_identity_hash="changed-candidate")])
    runner = _mock_cli(monkeypatch, results)
    baseline = tmp_path / "baseline.json"
    replay.save_baseline(baseline, _results([_row()]))
    monkeypatch.setattr("sys.argv", [
        "replay_backtest", SLUG, "--gate", str(baseline), "--out", str(tmp_path / "report.md"),
    ])
    replay.main()
    output = capsys.readouterr().out
    assert "DIAGNOSTIC PASS" in output
    assert "FIDELITY UNAVAILABLE" in output
    assert runner.call_args.kwargs["require_incumbent_control"] is False


def test_report_preserves_each_snapshot_error_in_fidelity_sidecar(tmp_path):
    rows = [_row(), _row("bad", None, distribution_error="recorded: invalid probability")]
    results = _results(rows, _manifest(("snap1", "bad")))
    results["incumbent_control"] = incumbent_control_validation(results)
    out = tmp_path / "report.md"
    replay.write_report(results, out)
    with out.with_suffix(".fidelity.csv").open(encoding="utf-8", newline="") as handle:
        diagnostics = list(csv.DictReader(handle))
    assert [row["snapshot_id"] for row in diagnostics] == ["snap1", "bad"]
    assert diagnostics[1]["distribution_error"] == "recorded: invalid probability"
    report = out.read_text(encoding="utf-8")
    assert "DIAGNOSTIC" in report
    assert "FIDELITY WARNING" in report
    assert "report.fidelity.csv" in report


@pytest.mark.parametrize("mode", [
    "faithful", "duplicate_raw", "empty_recorded", "empty_replayed",
    "negative_replayed", "nonfinite_recorded", "missing_label",
])
def test_run_retains_invalid_and_duplicate_control_evidence(monkeypatch, tmp_path, mode):
    folder = tmp_path / SLUG
    folder.mkdir()
    band = {
        "snapshot_id": "snap1", "bin_kind": "eq", "bin_value_c": 25,
        "range_label": "25 C", "market_yes": 0.5, "model_probability": 1.0,
        "captured_at_local": "2026-06-03T14:30:00-04:00",
    }
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(band))
        writer.writeheader()
        writer.writerow(band)
    identity = {"identity_hash": "a" * 64}
    record = {
        "snapshot_id": "snap1", "model_identity": identity,
        "model_version": "incumbent", "recorded_distribution": {25: 1.0},
    }
    if mode == "empty_recorded":
        record["recorded_distribution"] = {}
    if mode == "nonfinite_recorded":
        record["recorded_distribution"] = {25: float("nan")}
    records = [record, deepcopy(record)] if mode == "duplicate_raw" else [record]
    monkeypatch.setattr(replay, "load_replay_records", lambda path: records)
    projector = Mock(return_value=1.0)
    monkeypatch.setattr(replay, "TorontoHighTempModel", lambda **kwargs: SimpleNamespace(
        bin_probability=projector,
    ))
    distribution = {} if mode == "empty_replayed" else {25: -1.0} if mode == "negative_replayed" else {25: 1.0}
    monkeypatch.setattr(replay, "replay_distribution", lambda *args: distribution)
    monkeypatch.setattr(replay, "replay_model_identity", lambda model: identity)
    monkeypatch.setattr(replay, "replay_model_version", lambda model: "incumbent")
    monkeypatch.setattr(replay, "load_feature_vectors", lambda path: {})
    monkeypatch.setattr(replay, "verify_entry_inputs", lambda *args: [])
    mutable_labels = Mock(side_effect=AssertionError("strict controls must not read mutable labels"))
    monkeypatch.setattr(replay, "load_daily_summary", mutable_labels)
    manifest = _manifest()
    if mode == "missing_label":
        del manifest["entries"][0]["settlement_bucket"]
        manifest["corpus_hash"] = replay.corpus_hash(manifest["entries"])
    results = replay.run_replay_backtest(
        [folder], None, {}, None, write=False, corpus_manifest=manifest,
        require_incumbent_control=True,
    )
    assert len(results["fidelity_rows"]) == 1
    mutable_labels.assert_not_called()
    assert results["incumbent_control"]["status"] == ("PASS" if mode == "faithful" else "FAIL")
    if mode == "duplicate_raw":
        assert results["fidelity_support"]["duplicate_replay_record_count"] == 1
    if mode.startswith("empty") or mode in {"negative_replayed", "nonfinite_recorded"}:
        assert results["fidelity"]["same_identity_invalid_n"] == 1
        assert results["fidelity_rows"][0]["distribution_error"]
        projector.assert_not_called()

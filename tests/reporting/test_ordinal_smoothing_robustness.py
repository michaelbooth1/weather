import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from weather.reporting.research.ordinal_smoothing_robustness import (
    H1_SCHEMA_VERSION,
    SCHEMA_VERSION,
    RobustnessConfigurationError,
    build_additional_diagnostics,
    build_manifest_index,
    build_sensitivity_summaries,
    compare_primary_summary,
    render_report,
    run_analysis,
    stream_baseline_rows,
    stream_candidate_rows,
    validate_paths,
)
from weather.reporting.research.ordinal_smoothing_sweep import (
    paired_fleet_date_rows,
    paired_summary,
)


def _rows(
    *,
    market_id,
    target_date,
    unit,
    winner_probability,
    snapshot_id="s1",
    recorded_p=None,
):
    output = []
    for band, outcome, probability, market_probability, value in (
        ("winner", 1, winner_probability, 0.65, 20),
        ("loser", 0, 1.0 - winner_probability, 0.35, 21),
    ):
        output.append(
            {
                "market_id": market_id,
                "target_date": target_date,
                "unit": unit,
                "snapshot_id": snapshot_id,
                "captured_at_local": f"{target_date}T03:00:00-04:00",
                "band": band,
                "bin_type": "eq",
                "bin_value_c": value,
                "bin_value_hi": value,
                "outcome": outcome,
                "market_yes": market_probability,
                "replayed_p": probability,
                "recorded_p": recorded_p,
            }
        )
    return output


def _write_cache(path, *, weight, rows, fingerprint_char):
    payload = {
        "schema_version": H1_SCHEMA_VERSION,
        "fingerprint": fingerprint_char * 64,
        "arm": {
            "split": "holdout",
            "weight": weight,
            "sigma": 0.75,
            "rows": rows,
            "distribution_rows": [],
            "replay": {"blockers": []},
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _manifest(entries, corpus_hash="a" * 64):
    return {"corpus_hash": corpus_hash, "entries": entries}


def _entry(market_id, target_date, unit, source="daily_summary"):
    return {
        "market_id": market_id,
        "target_date": target_date,
        "settlement_unit": unit,
        "settlement_source": source,
        "event_slug": f"{market_id}-{target_date}",
    }


def test_manifest_source_join_and_exact_panel_sets():
    manifest = _manifest(
        [
            _entry("toronto", "2026-06-01", "C"),
            _entry("nyc", "2026-06-01", "F"),
            _entry("toronto", "2026-06-02", "C"),
            _entry("nyc", "2026-06-02", "F", "snapshot_high"),
            _entry("toronto", "2026-06-03", "C"),
        ]
    )
    index, evidence = build_manifest_index(
        manifest,
        ("2026-06-01", "2026-06-02", "2026-06-03"),
        {"toronto": "C", "nyc": "F"},
    )

    assert index[("nyc", "2026-06-02")].settlement_source == "snapshot_high"
    assert evidence["manifest_complete_12_market_dates"] == [
        "2026-06-01",
        "2026-06-02",
    ]
    assert evidence["manifest_daily_summary_complete_12_market_dates"] == [
        "2026-06-01"
    ]
    assert evidence["manifest_settlement_sources"] == {
        "daily_summary": 4,
        "snapshot_high": 1,
    }


def test_baseline_duplicate_ignores_recorded_probability_but_conflict_blocks(tmp_path):
    manifest, _ = build_manifest_index(
        _manifest([_entry("toronto", "2026-06-01", "C")]),
        ("2026-06-01",),
        {"toronto": "C"},
    )
    original = _rows(
        market_id="toronto",
        target_date="2026-06-01",
        unit="C",
        winner_probability=0.55,
        recorded_p=0.1,
    )
    recorded_only = dict(original[0], recorded_p=0.9)
    cache = tmp_path / "holdout-weight-0p00.json"
    _write_cache(cache, weight=0.0, rows=original + [recorded_only], fingerprint_char="a")

    rows, evidence, _, blockers = stream_baseline_rows(cache, manifest)

    assert len(rows) == 2
    assert evidence["duplicate_extras"] == 1
    assert evidence["conflicting_duplicates"] == 0
    assert blockers == []

    conflict = dict(original[0], replayed_p=0.9)
    _write_cache(cache, weight=0.0, rows=original + [conflict], fingerprint_char="a")
    _, evidence, _, blockers = stream_baseline_rows(cache, manifest)
    assert evidence["conflicting_duplicates"] == 1
    assert "conflicting duplicate" in blockers[0]


def test_candidate_duplicate_and_alignment_fail_closed(tmp_path):
    manifest, _ = build_manifest_index(
        _manifest([_entry("toronto", "2026-06-01", "C")]),
        ("2026-06-01",),
        {"toronto": "C"},
    )
    baseline_source = _rows(
        market_id="toronto",
        target_date="2026-06-01",
        unit="C",
        winner_probability=0.55,
    )
    candidate_source = _rows(
        market_id="toronto",
        target_date="2026-06-01",
        unit="C",
        winner_probability=0.65,
    )
    baseline_cache = tmp_path / "holdout-weight-0p00.json"
    candidate_cache = tmp_path / "holdout-weight-0p25.json"
    _write_cache(
        baseline_cache,
        weight=0.0,
        rows=baseline_source,
        fingerprint_char="a",
    )
    baseline, _, _, _ = stream_baseline_rows(baseline_cache, manifest)

    harmless_duplicate = dict(candidate_source[0], recorded_p=0.99)
    _write_cache(
        candidate_cache,
        weight=0.25,
        rows=candidate_source + [harmless_duplicate],
        fingerprint_char="b",
    )
    evidence, _, blockers = stream_candidate_rows(
        candidate_cache,
        baseline_rows=baseline,
        manifest_index=manifest,
        selected_units={"C"},
        accumulators={},
    )
    assert blockers == []
    assert evidence["duplicate_extras"] == 1

    conflicting_duplicate = dict(candidate_source[0], replayed_p=0.95)
    _write_cache(
        candidate_cache,
        weight=0.25,
        rows=candidate_source + [conflicting_duplicate],
        fingerprint_char="b",
    )
    evidence, _, blockers = stream_candidate_rows(
        candidate_cache,
        baseline_rows=baseline,
        manifest_index=manifest,
        selected_units={"C"},
        accumulators={},
    )
    assert evidence["conflicting_duplicates"] == 1
    assert any("conflicting duplicate" in blocker for blocker in blockers)


def test_output_paths_must_stay_outside_input_data_root(tmp_path):
    data_root = tmp_path / "data"
    corpus = data_root / "backtest" / "promotion_corpus.json"
    h1 = tmp_path / "h1.json"
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    corpus.parent.mkdir(parents=True)
    for path in (corpus, h1, baseline, candidate):
        path.write_text("{}", encoding="utf-8")

    with pytest.raises(RobustnessConfigurationError, match="outside input data root"):
        validate_paths(
            h1_result=h1,
            corpus_manifest=corpus,
            baseline_cache=baseline,
            candidate_caches=[candidate],
            json_out=data_root / "research" / "result.json",
            report_out=tmp_path / "result.md",
        )


def test_existing_output_hardlink_to_immutable_input_is_rejected(tmp_path):
    data_root = tmp_path / "data"
    corpus = data_root / "backtest" / "promotion_corpus.json"
    h1 = tmp_path / "h1.json"
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    corpus.parent.mkdir(parents=True)
    for path in (corpus, h1, baseline, candidate):
        path.write_text("{}", encoding="utf-8")
    json_out = tmp_path / "result.json"
    try:
        os.link(baseline, json_out)
    except OSError as exc:
        pytest.skip(f"hardlinks unavailable: {exc}")

    with pytest.raises(RobustnessConfigurationError, match="aliases an immutable input"):
        validate_paths(
            h1_result=h1,
            corpus_manifest=corpus,
            baseline_cache=baseline,
            candidate_caches=[candidate],
            json_out=json_out,
            report_out=tmp_path / "result.md",
        )
    assert baseline.read_text(encoding="utf-8") == "{}"


def test_candidate_cache_hardlink_aliases_are_not_unique(tmp_path):
    data_root = tmp_path / "data"
    corpus = data_root / "backtest" / "promotion_corpus.json"
    h1 = tmp_path / "h1.json"
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    candidate_alias = tmp_path / "candidate-alias.json"
    corpus.parent.mkdir(parents=True)
    for path in (corpus, h1, baseline, candidate):
        path.write_text("{}", encoding="utf-8")
    try:
        os.link(candidate, candidate_alias)
    except OSError as exc:
        pytest.skip(f"hardlinks unavailable: {exc}")

    with pytest.raises(RobustnessConfigurationError, match="must be unique"):
        validate_paths(
            h1_result=h1,
            corpus_manifest=corpus,
            baseline_cache=baseline,
            candidate_caches=[candidate, candidate_alias],
            json_out=tmp_path / "result.json",
            report_out=tmp_path / "result.md",
        )


def test_streamed_sensitivities_preserve_h1_fleet_date_weighting(tmp_path):
    dates = ("2026-06-01", "2026-06-02", "2026-06-03")
    manifest_payload = _manifest(
        [
            _entry("toronto", dates[0], "C"),
            _entry("nyc", dates[0], "F"),
            _entry("toronto", dates[1], "C"),
            _entry("nyc", dates[1], "F", "snapshot_high"),
            _entry("toronto", dates[2], "C"),
        ]
    )
    manifest, _ = build_manifest_index(
        manifest_payload, dates, {"toronto": "C", "nyc": "F"}
    )
    baseline_rows = []
    candidate_rows = []
    for entry in manifest.values():
        baseline_rows.extend(
            _rows(
                market_id=entry.market_id,
                target_date=entry.target_date,
                unit=entry.unit,
                winner_probability=0.55,
            )
        )
        candidate_rows.extend(
            _rows(
                market_id=entry.market_id,
                target_date=entry.target_date,
                unit=entry.unit,
                winner_probability=0.65,
            )
        )
    baseline_cache = tmp_path / "holdout-weight-0p00.json"
    candidate_cache = tmp_path / "holdout-weight-0p25.json"
    _write_cache(
        baseline_cache, weight=0.0, rows=baseline_rows, fingerprint_char="a"
    )
    _write_cache(
        candidate_cache, weight=0.25, rows=candidate_rows, fingerprint_char="b"
    )
    baseline, _, _, baseline_blockers = stream_baseline_rows(
        baseline_cache, manifest
    )
    accumulators = {}
    alignment, _, candidate_blockers = stream_candidate_rows(
        candidate_cache,
        baseline_rows=baseline,
        manifest_index=manifest,
        selected_units={"C", "F"},
        accumulators=accumulators,
    )
    summaries, panels = build_sensitivity_summaries(
        accumulators,
        selected_weights={"C": 0.25, "F": 0.25},
        expected_markets={"toronto", "nyc"},
    )
    additional = build_additional_diagnostics(
        accumulators,
        selected_weights={"C": 0.25, "F": 0.25},
    )

    assert baseline_blockers == []
    assert candidate_blockers == []
    assert alignment["status"] == "PASS"
    assert panels["observed_complete_12_market_dates"] == list(dates[:2])
    assert panels["observed_daily_summary_complete_12_market_dates"] == [dates[0]]
    assert (
        summaries["all_pinned_recomputed"]["units"]["C"]["summary"]["fleet_dates"]
        == 3
    )
    assert (
        summaries["daily_summary_only"]["units"]["F"]["summary"]["fleet_dates"]
        == 1
    )
    assert (
        summaries["complete_12_market_dates"]["units"]["F"]["summary"]["fleet_dates"]
        == 2
    )
    assert (
        summaries["daily_summary_complete_12_market_dates"]["units"]["C"][
            "summary"
        ]["fleet_dates"]
        == 1
    )
    assert additional["per_market"]["toronto"]["summary"]["fleet_dates"] == 3
    assert additional["snapshot_high_only"]["units"]["F"]["summary"][
        "fleet_dates"
    ] == 1
    assert additional["leave_one_fleet_date_out"]["C"]["exclusions"] == 3
    assert additional["leave_one_fleet_date_out"]["C"][
        "all_exclusions_negative_both"
    ] is True


def test_primary_parity_is_tolerant_only_to_roundoff():
    daily = [
        {
            "target_date": "2026-06-01",
            "rows": 2,
            "markets": 1,
            "baseline_brier": 0.4,
            "candidate_brier": 0.3,
            "brier_delta": -0.1,
            "baseline_logloss": 0.6,
            "candidate_logloss": 0.5,
            "logloss_delta": -0.1,
            "market_brier": 0.35,
            "market_logloss": 0.55,
            "candidate_brier_delta_vs_market": -0.05,
            "candidate_logloss_delta_vs_market": -0.05,
        }
    ]
    summary = paired_summary(daily, split="holdout", unit="C", weight=0.25)
    assert compare_primary_summary(summary, summary)["status"] == "PASS"

    changed = json.loads(json.dumps(summary))
    changed["mean_brier_delta"] += 1e-6
    result = compare_primary_summary(summary, changed)
    assert result["status"] == "BLOCK"
    assert any("mean_brier_delta" in blocker for blocker in result["blockers"])


def test_run_analysis_requires_completed_h1_and_never_reselects(tmp_path):
    data_root = tmp_path / "data"
    corpus_path = data_root / "backtest" / "promotion_corpus.json"
    cache_root = tmp_path / "scratch" / "cache"
    output_root = tmp_path / "scratch" / "output"
    h1_path = output_root / "h1.json"
    baseline_path = cache_root / "holdout-weight-0p00.json"
    candidate_path = cache_root / "holdout-weight-0p25.json"
    target_date = "2026-06-01"
    market_units = {"toronto": "C", "nyc": "F"}
    manifest = _manifest(
        [
            _entry("toronto", target_date, "C"),
            _entry("nyc", target_date, "F"),
        ]
    )
    corpus_path.parent.mkdir(parents=True)
    corpus_path.write_text(json.dumps(manifest), encoding="utf-8")
    baseline_rows = []
    candidate_rows = []
    for market_id, unit in market_units.items():
        baseline_rows.extend(
            _rows(
                market_id=market_id,
                target_date=target_date,
                unit=unit,
                winner_probability=0.55,
            )
        )
        candidate_rows.extend(
            _rows(
                market_id=market_id,
                target_date=target_date,
                unit=unit,
                winner_probability=0.65,
            )
        )
    _write_cache(
        baseline_path, weight=0.0, rows=baseline_rows, fingerprint_char="a"
    )
    _write_cache(
        candidate_path, weight=0.25, rows=candidate_rows, fingerprint_char="b"
    )
    primary = {
        unit: paired_summary(
            paired_fleet_date_rows(baseline_rows, candidate_rows, unit),
            split="holdout",
            unit=unit,
            weight=0.25,
        )
        for unit in ("C", "F")
    }
    h1 = {
        "schema_version": H1_SCHEMA_VERSION,
        "status": "COMPLETE",
        "research_only": True,
        "promotion_authorized": False,
        "experiment": {"selection_uses_holdout": False},
        "inputs": {
            "corpus_path": str(corpus_path),
            "corpus_hash": manifest["corpus_hash"],
        },
        "outputs": {
            "json_out": str(h1_path),
            "lock_path": str(output_root / "h1.lock"),
            "cache_files": [str(baseline_path), str(candidate_path)],
        },
        "split": {"tune_dates": [], "holdout_dates": [target_date]},
        "tune": {
            "status": "PASS",
            "selected_weights": {"C": 0.25, "F": 0.25},
        },
        "holdout": {
            "status": "PASS",
            "dispositions": {"C": "SUPPORTED", "F": "SUPPORTED"},
            "paired": primary,
        },
    }
    output_root.mkdir(parents=True)
    h1_path.write_text(json.dumps(h1), encoding="utf-8")
    args = argparse.Namespace(
        h1_result=str(h1_path),
        corpus_manifest=str(corpus_path),
        baseline_cache=str(baseline_path),
        candidate_cache=[str(candidate_path)],
        json_out=str(output_root / "robustness.json"),
        report_out=str(output_root / "robustness.md"),
    )

    with patch(
        "weather.reporting.research.ordinal_smoothing_robustness.expected_market_units",
        return_value=market_units,
    ):
        payload = run_analysis(args)

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "COMPLETE"
    assert payload["design"]["selected_weights_copied_from_h1_tune"] == {
        "C": 0.25,
        "F": 0.25,
    }
    assert payload["design"]["selection_uses_post_hoc_results"] is False
    assert payload["safety"]["model_replay_performed"] is False
    assert payload["primary_reference"]["parity"]["C"]["status"] == "PASS"
    assert set(payload["additional_diagnostics"]["per_market"]) == {
        "nyc",
        "toronto",
    }
    report = render_report(payload)
    assert "preregistered all-pinned H1 holdout remains primary" in report
    assert "leave-one-fleet-date-out" in report

    h1["status"] = "BLOCK"
    h1_path.write_text(json.dumps(h1), encoding="utf-8")
    with patch(
        "weather.reporting.research.ordinal_smoothing_robustness.expected_market_units",
        return_value=market_units,
    ), pytest.raises(RobustnessConfigurationError, match="must be COMPLETE"):
        run_analysis(args)

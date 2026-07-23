import os
import subprocess
from pathlib import Path

import pytest

from weather.model.calibration_runtime import ordinal_smooth_distribution
from weather.reporting.research import ordinal_smoothing_physical_replay as replay


def _make_directory_alias(alias: Path, target: Path) -> None:
    try:
        alias.symlink_to(target, target_is_directory=True)
        return
    except (NotImplementedError, OSError) as symlink_error:
        if os.name == "nt":
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return
        pytest.skip(f"directory alias unavailable: {symlink_error}")


def _path_inputs(tmp_path):
    data = tmp_path / "data"
    snapshots = data / "snapshots"
    output = tmp_path / "scratch" / "physical"
    snapshots.mkdir(parents=True)
    files = {}
    for name in ("corpus", "h1", "dates", "baseline", "control"):
        path = tmp_path / f"{name}.json"
        path.write_text("{}", encoding="utf-8")
        files[name] = path
    return data, snapshots, output, files


def _validate(tmp_path, *, output=None):
    data, snapshots, default_output, files = _path_inputs(tmp_path)
    output = output or default_output
    return replay.validate_paths(
        mirror_data_root=data,
        staged_data_root=data,
        snapshots_root=snapshots,
        corpus_path=files["corpus"],
        h1_result_path=files["h1"],
        tune_dates_path=files["dates"],
        baseline_cache_path=files["baseline"],
        determinism_cache_path=files["control"],
        output_root=output,
        cache_root=output / "cache",
        json_out=output / "result.json",
        report_out=output / "result.md",
        lock_path=output / "run.lock",
    )


def _distribution(market_id, unit, probabilities):
    return {
        "market_id": market_id,
        "target_date": "2026-06-03",
        "snapshot_id": f"{market_id}-snap",
        "captured_at_local": "2026-06-03T12:00:00-04:00",
        "cutoff_hour": 12,
        "unit": unit,
        "distribution": probabilities,
    }


def _rows(distribution):
    rows = []
    for bucket, probability in sorted(distribution["distribution"].items()):
        rows.append(
            {
                "market_id": distribution["market_id"],
                "target_date": distribution["target_date"],
                "snapshot_id": distribution["snapshot_id"],
                "captured_at_local": distribution["captured_at_local"],
                "band": str(bucket),
                "bin_type": "eq",
                "bin_value_c": float(bucket),
                "bin_value_hi": float(bucket),
                "replayed_p": probability,
                "outcome": int(bucket == 2),
                "market_yes": 1.0 / 3.0,
                "unit": distribution["unit"],
            }
        )
    return rows


def _arm(anchor=None):
    base = {0: 0.85, 1: 0.10, 2: 0.05}
    distributions = []
    rows = []
    for market_id, unit in (("toronto", "C"), ("atlanta", "F")):
        probabilities = (
            base
            if anchor is None
            else ordinal_smooth_distribution(
                base, sigma=replay.native_sigma(anchor, unit), blend_weight=1.0
            )
        )
        distribution = _distribution(market_id, unit, probabilities)
        distributions.append(distribution)
        rows.extend(_rows(distribution))
    return {
        "rows": rows,
        "distribution_rows": distributions,
        "replay": {"blockers": []},
    }


def test_family_config_maps_physical_width_without_serving_default_change():
    c = replay.family_smoothing_config(0.75, "toronto")
    f = replay.family_smoothing_config(0.75, "atlanta")
    assert c["sigma"] == 0.75
    assert f["sigma"] == pytest.approx(1.35)
    assert c["blend_weight"] == f["blend_weight"] == 1.0
    assert c["source"] == "research_physical_sigma_tune_only"


def test_factory_rejects_nonpreregistered_anchor_before_model_construction():
    with pytest.raises(replay.ExperimentConfigurationError, match="preregistered grid"):
        replay.make_family_model_factory(0.6)


def test_output_guard_rejects_direct_data_subtree(tmp_path):
    data, snapshots, _, files = _path_inputs(tmp_path)
    unsafe = data / "research-output"
    with pytest.raises(replay.ExperimentConfigurationError, match="read-only data"):
        replay.validate_paths(
            mirror_data_root=data,
            staged_data_root=data,
            snapshots_root=snapshots,
            corpus_path=files["corpus"],
            h1_result_path=files["h1"],
            tune_dates_path=files["dates"],
            baseline_cache_path=files["baseline"],
            determinism_cache_path=files["control"],
            output_root=unsafe,
            cache_root=unsafe / "cache",
            json_out=unsafe / "result.json",
            report_out=unsafe / "result.md",
            lock_path=unsafe / "run.lock",
        )
    assert not unsafe.exists()


def test_output_guard_rejects_junction_alias_into_data(tmp_path):
    data, snapshots, _, files = _path_inputs(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    alias = scratch / "data-alias"
    _make_directory_alias(alias, data)
    unsafe = alias / "research-output"
    with pytest.raises(replay.ExperimentConfigurationError, match="read-only data"):
        replay.validate_paths(
            mirror_data_root=data,
            staged_data_root=data,
            snapshots_root=snapshots,
            corpus_path=files["corpus"],
            h1_result_path=files["h1"],
            tune_dates_path=files["dates"],
            baseline_cache_path=files["baseline"],
            determinism_cache_path=files["control"],
            output_root=unsafe,
            cache_root=unsafe / "cache",
            json_out=unsafe / "result.json",
            report_out=unsafe / "result.md",
            lock_path=unsafe / "run.lock",
        )
    assert not (data / "research-output").exists()


def test_output_guard_accepts_resolved_scratch_and_enforces_budget(tmp_path):
    paths = _validate(tmp_path)
    assert paths["output_root"].name == "physical"
    assert len(replay.PHYSICAL_C_SIGMA_ANCHORS) * replay.MEASURED_MINUTES_PER_ARM <= 240
    assert (
        len(replay.PHYSICAL_C_SIGMA_ANCHORS)
        * replay.PROJECTED_COMPACT_BYTES_PER_ARM
        <= 25 * 1024**3
    )


def test_compact_scoring_row_drops_feature_payload():
    source = {
        "market_id": "toronto",
        "target_date": "2026-06-03",
        "snapshot_id": "x",
        "captured_at_local": "x",
        "band": "x",
        "bin_type": "eq",
        "bin_value_c": 1,
        "bin_value_hi": 1,
        "replayed_p": 0.5,
        "outcome": 1,
        "market_yes": 0.4,
        "unit": "C",
        "feature_large_payload": [1, 2, 3],
    }
    compact = replay.compact_scoring_row(source)
    assert "feature_large_payload" not in compact
    assert compact["replayed_p"] == 0.5


def test_candidate_analysis_enforces_mass_alignment_and_returns_family_summaries():
    gate, summaries = replay.analyze_candidate(_arm(), _arm(0.75), 0.75)
    assert gate["status"] == "PASS"
    assert gate["mass"]["status"] == "PASS"
    assert gate["alignment"]["status"] == "PASS"
    assert set(summaries) == {"C", "F"}
    assert summaries["F"]["native_sigma"] == pytest.approx(1.35)
    assert summaries["C"]["mean_brier_delta_vs_w0"] < 0


def test_candidate_analysis_blocks_alignment_loss():
    candidate = _arm(0.75)
    candidate["rows"].pop()
    with pytest.raises(replay.ExperimentConfigurationError, match="gate failed"):
        replay.analyze_candidate(_arm(), candidate, 0.75)


def test_cache_fingerprint_binds_anchor_code_and_baseline():
    manifest = {"source_corpus_hash": "corpus"}
    entries = [
        {
            "event_slug": "slug",
            "target_date": "2026-06-03",
            "market_id": "toronto",
            "snapshot_ids": ["a"],
        }
    ]
    first = replay.cache_fingerprint(
        physical_c_sigma=0.25,
        tune_manifest=manifest,
        entries=entries,
        code_hash="code-a",
        baseline_sha256="base",
    )
    second = replay.cache_fingerprint(
        physical_c_sigma=0.5,
        tune_manifest=manifest,
        entries=entries,
        code_hash="code-a",
        baseline_sha256="base",
    )
    third = replay.cache_fingerprint(
        physical_c_sigma=0.25,
        tune_manifest=manifest,
        entries=entries,
        code_hash="code-b",
        baseline_sha256="base",
    )
    assert len(first) == 64
    assert first != second
    assert first != third


def test_code_digest_binds_complete_canonical_weather_source_closure(tmp_path, monkeypatch):
    from weather.backtesting import replay as replay_owner
    from weather.backtesting import settlement_io

    repository_root = replay._repository_root()
    bound = replay.code_digest_paths()
    expected = {
        Path(replay_owner.__file__).resolve(),
        Path(settlement_io.__file__).resolve(),
        Path(replay.__file__).resolve(),
    }
    assert expected <= set(bound)
    assert bound == tuple(
        sorted(bound, key=lambda path: path.relative_to(repository_root).as_posix())
    )
    assert set(bound) == {
        path.resolve() for path in (repository_root / "src" / "weather").rglob("*.py")
    }

    first = tmp_path / "owner_a.py"
    second = tmp_path / "owner_b.py"
    first.write_text("anchor = 0.25\n", encoding="utf-8")
    second.write_text("unit = 'F'\n", encoding="utf-8")
    before = replay.digest_files((first, second))
    second.write_text("unit = 'C'\n", encoding="utf-8")
    after = replay.digest_files((first, second))
    assert before != after

    monkeypatch.setattr(replay, "code_digest_paths", lambda: (first, second))
    monkeypatch.setattr(replay, "_repository_root", lambda: tmp_path)
    before = replay.code_digest()
    first.write_text("anchor = 0.50\n", encoding="utf-8")
    assert replay.code_digest() != before


def test_mid_run_code_change_is_a_hard_failure(monkeypatch):
    monkeypatch.setattr(replay, "code_digest", lambda: "after")
    with pytest.raises(replay.ExperimentConfigurationError, match="changed while"):
        replay.require_unchanged_code_digest("before")


def test_schema_is_registered():
    assert replay.SCHEMA_VERSION == "ordinal_smoothing_physical_replay_v0.1"

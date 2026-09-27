import json

from weather.reporting.hourly import hourly_model_scoring as scoring
from weather.reporting.hourly.hourly_model_context import build_hourly_performance
from weather.reporting.hourly.ten_minute_model_performance import build_ten_minute_performance
from tests.reporting.test_hourly_model_performance import write_snapshot_folder, write_labels_csv


def test_both_aggregations_reuse_exact_scored_rows(tmp_path, monkeypatch):
    folder = write_snapshot_folder(tmp_path)
    labels = write_labels_csv(tmp_path, folder)
    label = scoring.discover_labeled_folders(labels_csv=labels, snapshots_root=folder.parent)[0][0]["label"]
    full = scoring.score_folder(folder, label, use_cache=False)
    cold = scoring.score_folder(folder, label)
    assert cold == full
    original = scoring.backtest_tape
    calls = []

    def count(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(scoring, "backtest_tape", count)
    assert scoring.score_folder(folder, label) == full
    hourly = build_hourly_performance(labels_csv=labels, snapshots_root=folder.parent,
                                      context_root=tmp_path / "context")
    ten = build_ten_minute_performance(labels_csv=labels, snapshots_root=folder.parent,
                                       item147_rows=tmp_path / "absent.csv")
    assert calls == []
    assert hourly["corpus"]["scored_market_days"] == 1
    assert ten["corpus"]["scored_market_days"] == 1
    changed_label = dict(label, settlement_bucket="9")
    assert scoring.score_folder(folder, changed_label) == scoring.score_folder(folder, changed_label, use_cache=False)
    assert len(calls) == 2
    tape = folder / "snapshots_long.csv"
    tape.write_text(tape.read_text().replace("0.80", "0.75"))
    scoring.score_folder(folder, changed_label)
    assert len(calls) == 3
    scoring.score_folder(folder, changed_label, thresholds=(0.25,))
    assert len(calls) == 4


def test_cache_corruption_and_feature_schema_inputs_invalidate(tmp_path, monkeypatch):
    folder = write_snapshot_folder(tmp_path)
    labels = write_labels_csv(tmp_path, folder)
    label = scoring.discover_labeled_folders(labels_csv=labels, snapshots_root=folder.parent)[0][0]["label"]
    expected = scoring.score_folder(folder, label)
    cache = folder / ".scored_rows_cache.json"
    document = json.loads(cache.read_text())
    document["payload"][0][0]["model_probability"] = 0.123
    cache.write_text(json.dumps(document))
    assert scoring.score_folder(folder, label) == expected
    original = scoring.backtest_tape
    calls = []

    def count(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(scoring, "backtest_tape", count)
    (folder / "features_long.csv").write_text("snapshot_id,forecast_gap\ns9,2\n")
    scoring.score_folder(folder, label)
    assert calls == [1]
    monkeypatch.setattr(scoring, "SCHEMA_VERSION", "fixture-scorer-revision")
    scoring.score_folder(folder, label)
    assert calls == [1, 1]


def test_full_and_incremental_report_outputs_match(tmp_path, monkeypatch):
    folder = write_snapshot_folder(tmp_path)
    labels = write_labels_csv(tmp_path, folder)
    original = scoring.cached_score

    def reports():
        return [build_hourly_performance(labels_csv=labels, snapshots_root=folder.parent,
                                         context_root=tmp_path / "context"),
                build_ten_minute_performance(labels_csv=labels, snapshots_root=folder.parent,
                                             item147_rows=tmp_path / "absent.csv")]

    def stable(value):
        if isinstance(value, dict):
            return {key: stable(item) for key, item in value.items()
                    if key not in {"generated_at_utc", "generated_at", "evaluated_at_utc"}}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    monkeypatch.setattr(scoring, "cached_score", lambda folder, label, thresholds, schema, score:
                        score(folder, label, thresholds))
    full = stable(reports())
    monkeypatch.setattr(scoring, "cached_score", original)
    assert stable(reports()) == full
    assert stable(reports()) == full

from pathlib import Path

from weather.backtesting import replay_cache


def _entry(**overrides):
    payload = {
        "event_slug": "highest-temperature-in-nyc-on-july-7-2026",
        "market_id": "nyc",
        "target_date": "2026-07-07",
        "snapshot_ids": ["snap1", "snap2"],
        "replay_record_hashes": {"snap1": "r1", "snap2": "r2"},
        "tape_row_hashes": {"snap1": "t1", "snap2": "t2"},
        "settlement_bucket": 82,
        "settlement_high": 82.4,
        "settlement_unit": "F",
        "settlement_source": "wu",
        "winning_band": "82-83 F",
        "winning_band_kind": "range",
        "winning_band_value": 82,
        "winning_band_value_hi": 83,
        "quality_grade": "complete",
        "admitted_by": "quality_grade",
        "label_hash": "label-1",
    }
    payload.update(overrides)
    return payload


def test_entry_inputs_fingerprint_changes_on_label_or_snapshot_change():
    base = replay_cache.entry_inputs_fingerprint(_entry())
    label_changed = replay_cache.entry_inputs_fingerprint(_entry(settlement_bucket=83))
    snapshot_changed = replay_cache.entry_inputs_fingerprint(_entry(snapshot_ids=["snap1"]))

    assert base != label_changed
    assert base != snapshot_changed


def test_replay_cache_write_read_and_flush_consumer(tmp_path):
    root = tmp_path / "replay_cache"
    key = replay_cache.key_for_entry(
        _entry(),
        consumer="pooled_candidate_replay",
        model_fp="model-abc",
        config_fp="config-def",
    )
    rows = [{"market_id": "nyc", "snapshot_id": "snap1", "candidate_p": 0.61}]

    path = replay_cache.write_entry(
        root,
        key,
        rows=rows,
        replay_results={"all_rows": [{"snapshot_id": "snap1"}]},
        coverage={"candidate_rows": 1},
        diagnostics={"source_freshness_snapshots": 1},
    )
    loaded = replay_cache.read_entry(root, key)
    wrong_key = replay_cache.key_for_entry(
        _entry(settlement_bucket=83),
        consumer="pooled_candidate_replay",
        model_fp="model-abc",
        config_fp="config-def",
    )
    flush = replay_cache.flush_consumer(root, "pooled_candidate_replay")

    assert path == replay_cache.cache_path(root, key)
    assert loaded is not None
    assert loaded["rows"] == rows
    assert replay_cache.read_entry(root, wrong_key) is None
    assert flush["removed_count"] == 1
    assert not Path(path).exists()


def test_replay_cache_policy_modes():
    assert replay_cache.replay_cache_policy("off") == {"mode": "off", "read": False, "write": False}
    assert replay_cache.replay_cache_policy("write_only") == {"mode": "write_only", "read": False, "write": True}
    assert replay_cache.replay_cache_policy("read_write") == {"mode": "read_write", "read": True, "write": True}

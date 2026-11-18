import json

from weather.backtesting.replay import (
    RECONSTRUCTED_FILENAME,
    REPLAY_INPUTS_FILENAME,
    load_replay_records,
    replay_input_status_rows,
)


def test_non_object_lines_preserve_capture_precedence_and_missing_status(tmp_path):
    captured = {"snapshot_id": "captured", "origin": "original"}
    rebuilt = {"snapshot_id": "rebuilt", "origin": "reconstructed"}
    snapshots = [captured, rebuilt, {"snapshot_id": "missing"}]
    invalid_rows = [None, [], "text", 19, False]
    files = {
        REPLAY_INPUTS_FILENAME: [*invalid_rows, captured],
        RECONSTRUCTED_FILENAME: [{**captured, "origin": "reconstructed"}, *invalid_rows, rebuilt],
        "snapshots.jsonl": [snapshots[0], *invalid_rows, *snapshots[1:]],
    }
    for name, rows in files.items():
        (tmp_path / name).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    assert load_replay_records(tmp_path) == [captured, rebuilt]
    statuses = {row["snapshot_id"]: row["replay_input_status"] for row in replay_input_status_rows(tmp_path)}
    assert statuses == {"captured": "captured", "rebuilt": "reconstructed", "missing": "evaluation_only"}

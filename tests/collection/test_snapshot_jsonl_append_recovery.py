"""SnapshotStore.append_jsonl separates a new record from an unterminated partial line.

The writer streams a record in chunks, so a process killed mid-append leaves a partial
line with no newline. Before this guard the next append was glued onto it and read_jsonl
skipped the merged line, losing the complete record too (nyc 2026-08-12 replay_inputs
line 123 in the le0929 replay-input bundle).

Guards: captured-input replay (AGENTS.md) - a torn append must cost only the torn record,
  never the next complete one; clean files gain no blank or extra lines.
"""
from weather.collection.snapshot_store import SnapshotStore


def _store():
    return SnapshotStore.__new__(SnapshotStore)


def test_append_after_torn_line_keeps_the_next_record(tmp_path):
    store = _store()
    path = tmp_path / "replay_inputs.jsonl"
    store.append_jsonl(path, {"seq": 1})
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 2, "source": "marine_con')  # killed mid-write
    store.append_jsonl(path, {"seq": 3})

    assert [row["seq"] for row in store.read_jsonl(path)] == [1, 3]


def test_truncated_last_line_then_append_loses_exactly_one_record(tmp_path):
    store = _store()
    path = tmp_path / "replay_inputs.jsonl"
    for seq in range(5):
        store.append_jsonl(path, {"seq": seq, "payload": "x" * 64})
    data = path.read_bytes()
    last_start = data.rstrip(b"\r\n").rfind(b"\n") + 1
    path.write_bytes(data[: last_start + (len(data) - last_start) // 2])  # cut record 4 mid-line
    store.append_jsonl(path, {"seq": 5, "payload": "y"})

    assert [row["seq"] for row in store.read_jsonl(path)] == [0, 1, 2, 3, 5]


def test_clean_appends_add_no_extra_lines(tmp_path):
    store = _store()
    path = tmp_path / "replay_inputs.jsonl"
    for seq in range(3):
        store.append_jsonl(path, {"seq": seq}, durable=seq == 1)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert all(line.strip() for line in lines)
    assert [row["seq"] for row in store.read_jsonl(path)] == [0, 1, 2]


def test_empty_existing_file_gets_no_leading_separator(tmp_path):
    store = _store()
    path = tmp_path / "replay_inputs.jsonl"
    path.write_bytes(b"")
    store.append_jsonl(path, {"seq": 0})

    assert path.read_text(encoding="utf-8").splitlines() == ['{"seq": 0}']
